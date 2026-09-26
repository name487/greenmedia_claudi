import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Badge, Card, ClientSelect, Empty, PageHeader, Stars, StatusBadge, fmtDateTime } from '../components/ui';
import { matchClient, useClientFilter, useVisibleClients } from '../data/scope';
import { getDB, uid, update, useCurrentUser, useDB } from '../data/store';
import type { Review, ReplyStatus } from '../data/types';
import { draftReviewReply } from '../lib/ai';
import { can } from '../lib/permissions';
import { detectLanguage, detectSentiment } from '../lib/sentiment';

const FILTERS: { key: string; label: string; test: (r: Review) => boolean }[] = [
  { key: 'pending', label: 'Needs reply', test: (r) => r.replyStatus === 'new' || r.replyStatus === 'drafted' || r.replyStatus === 'approved' },
  { key: 'approved', label: 'Approved', test: (r) => r.replyStatus === 'approved' },
  { key: 'negative', label: 'Negative', test: (r) => r.sentiment === 'negative' && r.replyStatus !== 'published' },
  { key: 'published', label: 'Published', test: (r) => r.replyStatus === 'published' },
  { key: 'all', label: 'All', test: () => true },
];

const INCOMING = [
  { rating: 5, text: 'Loved the service today, team was super quick and helpful!' },
  { rating: 1, text: 'Booked online but nobody was there when I arrived. Very poor experience.' },
  { rating: 4, text: 'Good experience, will come back again.' },
];

function setReview(id: string, patch: Partial<Review>, action: string) {
  const r = getDB().reviews.find((x) => x.id === id)!;
  update((d) => ({ reviews: d.reviews.map((x) => (x.id === id ? { ...x, ...patch } : x)) }), { clientId: r.clientId, action, entity: `review:${id}` });
}

export function ReviewQueue() {
  const db = useDB();
  const user = useCurrentUser()!;
  const clients = useVisibleClients();
  const [params] = useSearchParams();
  const [effectiveClient, setClient, pinned] = useClientFilter(params.get('client') ?? 'all');
  const [filter, setFilter] = useState('pending');
  const [busy, setBusy] = useState<string | null>(null);
  const [editing, setEditing] = useState<Record<string, string>>({});

  const f = FILTERS.find((x) => x.key === filter)!;
  const list = db.reviews
    .filter((r) => clients.some((c) => c.id === r.clientId))
    .filter(matchClient(effectiveClient))
    .filter(f.test)
    .sort((a, b) => (a.sentiment === 'negative' ? -1 : 0) - (b.sentiment === 'negative' ? -1 : 0) || b.createdAt.localeCompare(a.createdAt));

  const draft = async (r: Review) => {
    setBusy(r.id);
    const client = db.clients.find((c) => c.id === r.clientId)!;
    const res = await draftReviewReply(r, client);
    setReview(r.id, { reply: res.data, replyStatus: 'drafted' }, `AI drafted reply (${res.source})`);
    setEditing((e) => ({ ...e, [r.id]: res.data }));
    setBusy(null);
  };

  const transition = (r: Review, status: ReplyStatus, action: string) => {
    const reply = editing[r.id] ?? r.reply;
    const patch: Partial<Review> = { replyStatus: status, reply };
    if (status === 'published') patch.publishedAt = new Date().toISOString();
    setReview(r.id, patch, action);
    setEditing(({ [r.id]: _, ...rest }) => rest);
  };

  // Simulates the "Google review event" webhook: fetch → language → sentiment → optional auto-draft.
  const fetchNew = async () => {
    const pool = clients.filter((c) => c.gmb.connected && (effectiveClient === 'all' || c.id === effectiveClient));
    if (!pool.length) return;
    const client = pool[Math.floor(Math.random() * pool.length)];
    const sample = INCOMING[Math.floor(Math.random() * INCOMING.length)];
    const review: Review = { id: uid('rv'), clientId: client.id, author: 'New Customer', rating: sample.rating, text: sample.text, language: detectLanguage(sample.text), sentiment: detectSentiment(sample.text, sample.rating), createdAt: new Date().toISOString(), replyStatus: 'new' };
    update((d) => ({ reviews: [review, ...d.reviews] }), { clientId: client.id, action: 'review received', entity: `review:${review.id}` });
    const res = await draftReviewReply(review, client);
    const auto = client.autoPublish.reviews && review.sentiment === 'positive';
    setReview(review.id, { reply: res.data, replyStatus: auto ? 'published' : 'drafted', publishedAt: auto ? new Date().toISOString() : undefined }, auto ? 'auto-published reply' : 'AI drafted reply');
  };

  const canPublish = can(user.role, 'review.publish');
  const canApprove = can(user.role, 'review.approve');

  return (
    <>
      <PageHeader title="AI Review Queue" subtitle="Detect → sentiment → AI draft → approve → publish" actions={!pinned && <button className="btn soft" onClick={fetchNew}>Sync new reviews</button>} />
      <div className="toolbar">
        {!pinned && <ClientSelect value={effectiveClient} onChange={setClient} />}
      </div>
      <div className="pill-tabs">
        {FILTERS.map((x) => {
          const n = db.reviews.filter((r) => clients.some((c) => c.id === r.clientId)).filter(matchClient(effectiveClient)).filter(x.test).length;
          return <button key={x.key} className={filter === x.key ? 'on' : ''} onClick={() => setFilter(x.key)}>{x.label} ({n})</button>;
        })}
      </div>

      {list.length === 0 && <Card><Empty>No reviews here.</Empty></Card>}
      <div className="grid cols-2">
        {list.map((r) => {
          const client = db.clients.find((c) => c.id === r.clientId)!;
          const escalate = r.rating <= 2;
          const text = editing[r.id] ?? r.reply ?? '';
          const isEditing = r.id in editing;
          return (
            <Card key={r.id}>
              <div className="review">
                <div className="row between">
                  <div>
                    <strong>{r.author}</strong> <Stars n={r.rating} />
                    <div className="muted small">{client.companyName} · {fmtDateTime(r.createdAt)}</div>
                  </div>
                  <div className="row">
                    <StatusBadge status={r.sentiment} />
                    {r.language !== 'en' && <Badge tone="blue">{r.language}</Badge>}
                    <StatusBadge status={r.replyStatus} />
                  </div>
                </div>
                <blockquote>{r.text}</blockquote>
                {escalate && r.replyStatus !== 'published' && <div className="notice">Escalation: {client.brandVoice.escalationRule}</div>}

                {r.replyStatus === 'new' && !isEditing ? (
                  <button className="btn" disabled={busy === r.id} onClick={() => draft(r)}><Icon name="sparkle" size={16} /> {busy === r.id ? 'Drafting…' : 'Generate AI reply'}</button>
                ) : (
                  <div className="reply-box form">
                    {isEditing ? (
                      <textarea className="input" value={text} onChange={(e) => setEditing((s) => ({ ...s, [r.id]: e.target.value }))} />
                    ) : (
                      <p style={{ margin: 0 }}>{r.reply}</p>
                    )}
                    {r.replyStatus !== 'published' && r.replyStatus !== 'rejected' && (
                      <div className="btn-row">
                        {!isEditing && <button className="btn ghost sm" onClick={() => setEditing((s) => ({ ...s, [r.id]: r.reply ?? '' }))}>Edit</button>}
                        {isEditing && <button className="btn ghost sm" onClick={() => transition(r, 'drafted', 'edited reply')}>Save</button>}
                        <button className="btn ghost sm" disabled={busy === r.id} onClick={() => draft(r)}>{busy === r.id ? '…' : 'Regenerate'}</button>
                        <button className="btn ghost sm" onClick={() => transition(r, 'rejected', 'rejected reply')}>Reject</button>
                        {r.replyStatus !== 'approved' && canApprove && <button className="btn soft sm" onClick={() => transition(r, 'approved', 'approved reply')}>Approve</button>}
                        {canPublish && (
                          <button className="btn sm" disabled={!text.trim() || (escalate && r.replyStatus !== 'approved')} title={escalate && r.replyStatus !== 'approved' ? 'Low-rating replies must be approved first' : ''} onClick={() => transition(r, 'published', 'published reply to Google')}>
                            Publish to Google
                          </button>
                        )}
                      </div>
                    )}
                    {r.replyStatus === 'published' && r.publishedAt && <span className="muted small">Published {fmtDateTime(r.publishedAt)}</span>}
                    {r.replyStatus === 'rejected' && <button className="btn ghost sm" onClick={() => transition(r, 'new', 'reopened review')}>Reopen</button>}
                  </div>
                )}
              </div>
            </Card>
          );
        })}
      </div>
    </>
  );
}
