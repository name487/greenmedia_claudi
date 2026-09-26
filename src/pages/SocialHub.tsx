import { useState } from 'react';
import { Badge, Card, ClientSelect, PageHeader, StatusBadge, fmtDateTime } from '../components/ui';
import { matchClient, useClientFilter, useVisibleClients } from '../data/scope';
import { update, useDB } from '../data/store';
import { PLATFORM_LABELS } from '../data/types';
import { ContentActions } from './ContentStudio';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function SocialHub() {
  const db = useDB();
  const clients = useVisibleClients();
  const [filter, setFilter, pinned] = useClientFilter();
  const [month, setMonth] = useState(() => { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1); });

  const items = db.content.filter((c) => clients.some((x) => x.id === c.clientId)).filter(matchClient(filter));
  const accounts = clients.filter((c) => filter === 'all' || c.id === filter).flatMap((c) => c.social.map((s) => ({ ...s, client: c })));
  const broken = accounts.filter((a) => !a.connected);

  const start = new Date(month);
  start.setDate(1 - ((month.getDay() + 6) % 7)); // Monday-first grid
  const cells = Array.from({ length: 42 }, (_, i) => { const d = new Date(start); d.setDate(start.getDate() + i); return d; });
  const today = new Date().toDateString();
  const onDay = (d: Date) => items.filter((c) => c.scheduledAt && new Date(c.scheduledAt).toDateString() === d.toDateString());

  const reconnect = (clientId: string, platform: string) =>
    update((d) => ({ clients: d.clients.map((c) => (c.id === clientId ? { ...c, social: c.social.map((s) => (s.platform === platform ? { ...s, connected: true } : s)) } : c)) }), { clientId, action: `reconnected ${platform}`, entity: 'social_account' });

  return (
    <>
      <PageHeader title="Social Hub" subtitle="Unified calendar, publishing status and connected accounts" actions={!pinned && <ClientSelect value={filter} onChange={setFilter} clients={clients} />} />
      {broken.length > 0 && (
        <div className="notice" style={{ marginBottom: 16 }}>
          {broken.length} account{broken.length > 1 ? 's need' : ' needs'} reconnection (token expired):{' '}
          {broken.map((b) => (
            <button key={b.client.id + b.platform} className="btn ghost sm" style={{ marginLeft: 6 }} onClick={() => reconnect(b.client.id, b.platform)}>{b.client.companyName} · {PLATFORM_LABELS[b.platform]}</button>
          ))}
        </div>
      )}
      <Card title={month.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })} action={
        <div className="btn-row">
          <button className="btn ghost sm" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>‹</button>
          <button className="btn ghost sm" onClick={() => { const d = new Date(); setMonth(new Date(d.getFullYear(), d.getMonth(), 1)); }}>Today</button>
          <button className="btn ghost sm" onClick={() => setMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>›</button>
        </div>
      }>
        <div className="calendar">
          {WEEKDAYS.map((w) => <div key={w} className="cal-head">{w}</div>)}
          {cells.map((d) => (
            <div key={d.toISOString()} className={`cal-day ${d.getMonth() !== month.getMonth() ? 'other' : ''} ${d.toDateString() === today ? 'today' : ''}`}>
              <span className="cal-num">{d.getDate()}</span>
              {onDay(d).map((c) => <span key={c.id} className="cal-post" title={`${c.topic} — ${db.clients.find((x) => x.id === c.clientId)?.companyName}`}>{c.topic}</span>)}
            </div>
          ))}
        </div>
      </Card>
      <div className="grid cols-2">
        <Card title="Publishing queue">
          <ul className="list">
            {items.filter((c) => c.status !== 'published').sort((a, b) => (a.scheduledAt ?? '').localeCompare(b.scheduledAt ?? '')).map((c) => (
              <li key={c.id}>
                <div className="row between">
                  <span><strong>{c.topic}</strong> <StatusBadge status={c.status} /><div className="muted small">{db.clients.find((x) => x.id === c.clientId)?.companyName} · {c.scheduledAt && fmtDateTime(c.scheduledAt)}</div></span>
                  <ContentActions item={c} />
                </div>
                <div className="chips" style={{ marginTop: 6 }}>{c.variants.map((v) => <Badge key={v.platform} tone="blue">{PLATFORM_LABELS[v.platform]}</Badge>)}</div>
              </li>
            ))}
          </ul>
        </Card>
        <Card title={`Connected accounts (${accounts.length})`}>
          <ul className="list">
            {accounts.slice(0, 20).map((a) => (
              <li key={a.client.id + a.platform} className="row between">
                <span>{PLATFORM_LABELS[a.platform]} <span className="muted small">{a.client.companyName}</span></span>
                {a.connected ? <Badge tone="green">Healthy</Badge> : <Badge tone="red">Expired</Badge>}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
}
