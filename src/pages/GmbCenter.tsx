import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, BarList, Card, ClientSelect, LineChart, PageHeader, Stars, Stat, StatusBadge, compact, fmtDateTime } from '../components/ui';
import { update, useDB } from '../data/store';
import { pctChange, sumMetrics } from '../lib/ai';

export function GmbCenter() {
  const db = useDB();
  const [clientId, setClientId] = useState(db.clients[0].id);
  const client = db.clients.find((c) => c.id === clientId)!;
  const days = db.metrics[client.id];
  const cur = sumMetrics(days.slice(60));
  const prev = sumMetrics(days.slice(30, 60));
  const reviews = db.reviews.filter((r) => r.clientId === client.id);
  const posts = db.content.filter((c) => c.clientId === client.id && c.variants.some((v) => v.platform === 'gmb'));
  const unanswered = reviews.filter((r) => r.replyStatus !== 'published').length;
  const hoursSinceSync = Math.round((Date.now() - new Date(client.gmb.lastSync).getTime()) / 36e5);

  const sync = () =>
    update((d) => ({ clients: d.clients.map((c) => (c.id === client.id ? { ...c, gmb: { ...c.gmb, connected: true, lastSync: new Date().toISOString() } } : c)) }), { clientId: client.id, action: client.gmb.connected ? 'GMB sync' : 'GMB connected', entity: 'gmb_account' });

  return (
    <>
      <PageHeader title="Google Business Profile" subtitle="Posts, reviews, offers, photos, Q&A and insights" actions={<ClientSelect value={clientId} onChange={setClientId} allowAll={false} />} />
      <div className="grid cols-3">
        <Card title="Connection health">
          <div className="form">
            <div className="row between"><span>Status</span>{client.gmb.connected ? <Badge tone="green">Connected</Badge> : <Badge tone="red">Not connected</Badge>}</div>
            <div className="row between"><span>Location</span><span className="muted small">{client.gmb.locationId}</span></div>
            <div className="row between"><span>Last sync</span><span className="muted small">{client.gmb.connected ? `${fmtDateTime(client.gmb.lastSync)}${hoursSinceSync > 24 ? ' · stale' : ''}` : '—'}</span></div>
            <button className="btn soft" onClick={sync}>{client.gmb.connected ? 'Sync now' : 'Connect with Google'}</button>
            {!client.gmb.connected && <p className="muted small" style={{ margin: 0 }}>Uses Google's official OAuth flow; tokens are stored encrypted on the server.</p>}
          </div>
        </Card>
        <Card title="Profile" className="span-2">
          <div className="grid stats">
            <Stat label="Rating" value={<><Stars n={client.gmb.rating} /> {client.gmb.rating}</>} hint={`${client.gmb.reviewCount} total`} />
            <Stat label="Unanswered reviews" value={unanswered} />
            <Stat label="Profile views" value={compact(cur.gmbViews)} delta={pctChange(cur.gmbViews, prev.gmbViews)} />
            <Stat label="Calls" value={cur.gmbCalls} delta={pctChange(cur.gmbCalls, prev.gmbCalls)} />
          </div>
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Insights — 90 days">
          <LineChart labels={days.map((d) => d.date)} series={[{ name: 'Views', color: 'var(--c1)', values: days.map((d) => d.gmbViews) }, { name: 'Web clicks ×10', color: 'var(--c3)', values: days.map((d) => d.webClicks * 10) }]} />
        </Card>
        <Card title="Customer actions (30d)">
          <BarList rows={[{ label: 'Website clicks', value: cur.webClicks }, { label: 'Direction requests', value: cur.gmbDirections }, { label: 'Phone calls', value: cur.gmbCalls }]} />
        </Card>
      </div>
      <div className="grid cols-2">
        <Card title="Posts & offers" action={<Link className="btn sm" to={`/content?client=${client.id}`}>New post</Link>}>
          {posts.length === 0 ? <p className="muted">No GMB posts yet.</p> : (
            <ul className="list">
              {posts.map((p) => (
                <li key={p.id} className="row between">
                  <span>{p.topic}<div className="muted small">{p.contentType} · {p.scheduledAt ? fmtDateTime(p.scheduledAt) : 'unscheduled'}</div></span>
                  <StatusBadge status={p.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recent reviews" action={<Link className="small" to={`/reviews?client=${client.id}`}>Review queue</Link>}>
          <ul className="list">
            {reviews.slice(0, 5).map((r) => (
              <li key={r.id}>
                <div className="row between"><span><Stars n={r.rating} /> <span className="small">{r.author}</span></span><StatusBadge status={r.replyStatus} /></div>
                <p className="small" style={{ margin: '4px 0 0' }}>{r.text}</p>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
