import { useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Badge, Card, ClientSelect, Empty, PageHeader, StatusBadge, fmtDateTime } from '../components/ui';
import { matchClient, useClientFilter, useVisibleClients } from '../data/scope';
import { getDB, uid, update, useCurrentUser, useDB } from '../data/store';
import { PLATFORM_LABELS, type ContentItem, type ContentStatus, type Platform, type Role } from '../data/types';
import { generateContent, type GeneratedContent } from '../lib/ai';
import { can } from '../lib/permissions';

const TYPES = ['post', 'offer', 'event', 'update'] as const;

export function setContent(id: string, patch: Partial<ContentItem>, action: string) {
  const item = getDB().content.find((c) => c.id === id)!;
  update((d) => ({ content: d.content.map((c) => (c.id === id ? { ...c, ...patch } : c)) }), { clientId: item.clientId, action, entity: `content:${id}` });
}

function localInputValue(d: Date) {
  const off = d.getTimezoneOffset() * 60000;
  return new Date(d.getTime() - off).toISOString().slice(0, 16);
}

export function ContentStudio() {
  const db = useDB();
  const user = useCurrentUser()!;
  const clients = useVisibleClients();
  const [params] = useSearchParams();
  const [filter, setFilter, pinned] = useClientFilter(params.get('client') ?? 'all');

  const [clientId, setClientId] = useState(params.get('client') ?? clients[0].id);
  const client = db.clients.find((c) => c.id === clientId)!;
  const available: Platform[] = ['gmb', ...client.social.map((s) => s.platform)];
  const [topic, setTopic] = useState('');
  const [type, setType] = useState<(typeof TYPES)[number]>('post');
  const [platforms, setPlatforms] = useState<Platform[]>(['gmb']);
  const [draft, setDraft] = useState<(GeneratedContent & { source: string }) | null>(null);
  const [when, setWhen] = useState(() => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(10, 0, 0, 0); return localInputValue(d); });
  const [busy, setBusy] = useState(false);

  const togglePlatform = (p: Platform) => setPlatforms((ps) => (ps.includes(p) ? ps.filter((x) => x !== p) : [...ps, p]));
  const selected = platforms.filter((p) => available.includes(p));

  const generate = async () => {
    setBusy(true);
    const res = await generateContent(client, topic, type, selected);
    setDraft({ ...res.data, source: res.source });
    setBusy(false);
  };

  const save = (status: ContentStatus) => {
    if (!draft) return;
    const item: ContentItem = {
      id: uid('ct'), clientId, topic, contentType: type, masterCopy: draft.masterCopy, hashtags: draft.hashtags, variants: draft.variants,
      status, scheduledAt: new Date(when).toISOString(), createdBy: user.id, createdAt: new Date().toISOString(),
    };
    update((d) => ({ content: [item, ...d.content] }), { clientId, action: `content ${status.replace('_', ' ')}`, entity: `content:${item.id}` });
    setDraft(null);
    setTopic('');
  };

  const items = db.content.filter((c) => clients.some((x) => x.id === c.clientId)).filter(matchClient(filter));

  return (
    <>
      <PageHeader title="AI Content Studio" subtitle="Topic → AI draft → platform variants → creative brief → approval → schedule" />
      {can(user.role, 'content.create') && (
        <div className="grid cols-2">
          <Card title="1. Brief">
            <div className="form">
              <label className="field">Client <ClientSelect value={clientId} onChange={(v) => { setClientId(v); setDraft(null); }} allowAll={false} clients={clients} /></label>
              <label className="field">Topic or offer
                <input className="input" value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="e.g. Diwali 20% off teeth whitening" />
              </label>
              <div className="field">Type
                <div className="chips">{TYPES.map((t) => <button type="button" key={t} className={`chip ${type === t ? 'on' : ''}`} onClick={() => setType(t)}>{t}</button>)}</div>
              </div>
              <div className="field">Platforms
                <div className="chips">{available.map((p) => <button type="button" key={p} className={`chip ${selected.includes(p) ? 'on' : ''}`} onClick={() => togglePlatform(p)}>{PLATFORM_LABELS[p]}</button>)}</div>
              </div>
              <p className="muted small" style={{ margin: 0 }}>Voice: {client.brandVoice.tone} · CTA “{client.brandVoice.ctaStyle}” · avoids {client.brandVoice.prohibitedClaims.join(', ')}</p>
              <button className="btn" disabled={!topic.trim() || !selected.length || busy} onClick={generate}><Icon name="sparkle" size={16} /> {busy ? 'Generating…' : draft ? 'Regenerate' : 'Generate with AI'}</button>
            </div>
          </Card>

          <Card title="2. Review & schedule" action={draft && <Badge tone={draft.source === 'ai' ? 'purple' : 'gray'}>{draft.source === 'ai' ? 'AI' : 'Offline template'}</Badge>}>
            {!draft ? <Empty>Your AI draft and platform variants appear here.</Empty> : (
              <div className="form">
                <label className="field">Master copy
                  <textarea className="input" value={draft.masterCopy} onChange={(e) => setDraft({ ...draft, masterCopy: e.target.value })} />
                </label>
                {draft.variants.map((v, i) => (
                  <label className="field" key={v.platform}>
                    <span>{PLATFORM_LABELS[v.platform]} · {v.format} · {v.copy.length} chars</span>
                    <textarea className="input" value={v.copy} onChange={(e) => setDraft({ ...draft, variants: draft.variants.map((x, j) => (j === i ? { ...x, copy: e.target.value } : x)) })} />
                  </label>
                ))}
                <div className="notice info"><strong>Creative brief:</strong> {draft.creativeBrief} <Link to={`/creative?client=${clientId}&headline=${encodeURIComponent(topic)}`}>Open Creative Studio →</Link></div>
                <label className="field">Schedule for
                  <input className="input" type="datetime-local" value={when} onChange={(e) => setWhen(e.target.value)} />
                </label>
                <div className="btn-row">
                  <button className="btn ghost" onClick={() => save('draft')}>Save draft</button>
                  <button className="btn soft" onClick={() => save('in_review')}>Send for approval</button>
                  {canApproveContent(user.role, db.settings.requireClientApproval) && <button className="btn" onClick={() => save('scheduled')}>Approve & schedule</button>}
                </div>
              </div>
            )}
          </Card>
        </div>
      )}

      <Card title="Content pipeline" action={!pinned && <ClientSelect value={filter} onChange={setFilter} clients={clients} />}>
        {items.length === 0 ? <Empty>No content yet.</Empty> : (
          <ul className="list">
            {items.map((c) => (
              <li key={c.id}>
                <div className="row between">
                  <div>
                    <strong>{c.topic}</strong> <StatusBadge status={c.status} />
                    <div className="muted small">{db.clients.find((x) => x.id === c.clientId)?.companyName} · {c.variants.map((v) => PLATFORM_LABELS[v.platform]).join(', ')} · {c.scheduledAt ? fmtDateTime(c.scheduledAt) : 'unscheduled'}</div>
                  </div>
                  <ContentActions item={c} />
                </div>
                <p className="small" style={{ margin: '6px 0 0' }}>{c.masterCopy}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

// With client approval required, only the client-portal user can move content past review.
const canApproveContent = (role: Role, requireClient: boolean) => can(role, 'content.approve') && (!requireClient || role === 'client');

export function ContentActions({ item }: { item: ContentItem }) {
  const user = useCurrentUser()!;
  const approve = canApproveContent(user.role, useDB().settings.requireClientApproval);
  const publish = can(user.role, 'content.publish');
  return (
    <div className="btn-row">
      {item.status === 'draft' && can(user.role, 'content.create') && <button className="btn soft sm" onClick={() => setContent(item.id, { status: 'in_review' }, 'sent for approval')}>Send for approval</button>}
      {item.status === 'in_review' && approve && (
        <>
          <button className="btn ghost sm" onClick={() => setContent(item.id, { status: 'draft' }, 'changes requested')}>Request changes</button>
          <button className="btn sm" onClick={() => setContent(item.id, { status: 'scheduled' }, 'approved & scheduled')}>Approve</button>
        </>
      )}
      {(item.status === 'scheduled' || item.status === 'failed') && publish && (
        <button className="btn sm" onClick={() => setContent(item.id, { status: 'published', scheduledAt: new Date().toISOString() }, item.status === 'failed' ? 'retried publish' : 'published now')}>{item.status === 'failed' ? 'Retry' : 'Publish now'}</button>
      )}
    </div>
  );
}
