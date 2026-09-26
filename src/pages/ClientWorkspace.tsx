import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Badge, Card, PageHeader, Stars, Stat, StatusBadge, compact, fmtDate, fmtDateTime } from '../components/ui';
import { update, useCurrentUser, useDB } from '../data/store';
import { PLATFORM_LABELS, type Client, type Platform } from '../data/types';
import { pctChange, sumMetrics } from '../lib/ai';
import { can } from '../lib/permissions';

export function ClientWorkspace() {
  const { id } = useParams();
  const db = useDB();
  const user = useCurrentUser()!;
  const client = db.clients.find((c) => c.id === id);
  const [notes, setNotes] = useState(client?.notes ?? '');
  if (!client) return <p>Client not found. <Link to="/clients">Back to clients</Link></p>;

  const editable = can(user.role, 'client.edit');
  const cur = sumMetrics(db.metrics[client.id].slice(60));
  const prev = sumMetrics(db.metrics[client.id].slice(30, 60));
  const reviews = db.reviews.filter((r) => r.clientId === client.id);
  const content = db.content.filter((c) => c.clientId === client.id);
  const kws = db.keywords.filter((k) => k.clientId === client.id);
  const tasks = db.tasks.filter((t) => t.clientId === client.id && t.status !== 'done');
  const reports = db.reports.filter((r) => r.clientId === client.id);
  const set = (patch: Partial<Client>, action: string) =>
    update((d) => ({ clients: d.clients.map((c) => (c.id === client.id ? { ...c, ...patch } : c)) }), { clientId: client.id, action, entity: 'client' });

  const toggleAuto = (key: Platform | 'reviews') => set({ autoPublish: { ...client.autoPublish, [key]: !client.autoPublish[key] } }, `auto-publish ${key} ${client.autoPublish[key] ? 'off' : 'on'}`);

  return (
    <>
      <Link to="/clients" className="row small muted" style={{ textDecoration: 'none', marginBottom: 8 }}><Icon name="back" size={16} /> Clients</Link>
      <PageHeader
        title={client.companyName}
        subtitle={`${client.industry} · ${client.city} · ${client.plan} plan`}
        actions={
          <>
            <StatusBadge status={client.status} />
            <Link className="btn soft" to={`/content?client=${client.id}`}>Create content</Link>
            <Link className="btn" to={`/reports?client=${client.id}`}>Monthly report</Link>
          </>
        }
      />
      <div className="grid stats">
        <Stat label="Google rating" value={<><Stars n={client.gmb.rating} /> {client.gmb.rating}</>} hint={`${client.gmb.reviewCount} reviews`} />
        <Stat label="GMB views (30d)" value={compact(cur.gmbViews)} delta={pctChange(cur.gmbViews, prev.gmbViews)} />
        <Stat label="Calls + directions" value={cur.gmbCalls + cur.gmbDirections} delta={pctChange(cur.gmbCalls + cur.gmbDirections, prev.gmbCalls + prev.gmbDirections)} />
        <Stat label="Leads (30d)" value={cur.leads} delta={pctChange(cur.leads, prev.leads)} />
      </div>

      <div className="grid cols-3">
        <Card title="Company profile">
          <dl className="kv">
            <dt>Website</dt><dd><a href={client.website} target="_blank" rel="noreferrer">{client.website.replace('https://', '')}</a></dd>
            <dt>Contact</dt><dd>{client.contact.name} ({client.contact.designation})</dd>
            <dt>Email</dt><dd>{client.contact.email}</dd>
            <dt>Phone</dt><dd>{client.contact.phone}</dd>
            <dt>Manager</dt><dd>{db.users.find((u) => u.id === client.accountManagerId)?.name}</dd>
            <dt>Services</dt><dd><div className="chips">{client.services.map((s) => <Badge key={s} tone="blue">{s}</Badge>)}</div></dd>
          </dl>
        </Card>
        <Card title="Connected accounts">
          <ul className="list">
            <li className="row between">
              <span>Google Business Profile</span>
              {client.gmb.connected ? <Badge tone="green">Connected</Badge> : <Badge tone="red">Not connected</Badge>}
            </li>
            {client.social.map((s) => (
              <li key={s.platform} className="row between">
                <span>{PLATFORM_LABELS[s.platform]} <span className="muted small">{s.handle}</span></span>
                {s.connected ? <Badge tone="green">Connected</Badge> : <Badge tone="red">Reconnect</Badge>}
              </li>
            ))}
          </ul>
        </Card>
        <Card title="AI brand voice">
          <dl className="kv">
            <dt>Tone</dt><dd>{client.brandVoice.tone}</dd>
            <dt>CTA</dt><dd>{client.brandVoice.ctaStyle}</dd>
            <dt>Languages</dt><dd>{client.brandVoice.languages.join(', ')}</dd>
            <dt>Never say</dt><dd>{client.brandVoice.prohibitedClaims.join(', ')}</dd>
            <dt>Escalation</dt><dd>{client.brandVoice.escalationRule}</dd>
          </dl>
        </Card>
      </div>

      <div className="grid cols-2">
        <Card title="Publishing safety" action={<Badge tone="amber">Human approval by default</Badge>}>
          <p className="muted small" style={{ marginTop: 0 }}>Nothing publishes without approval unless auto-publish is switched on for that channel.</p>
          <ul className="list">
            {(['reviews', 'gmb', ...client.social.map((s) => s.platform)] as (Platform | 'reviews')[]).map((k) => (
              <li key={k} className="row between">
                <span>{k === 'reviews' ? 'Positive review replies' : PLATFORM_LABELS[k]}</span>
                <label className="check">
                  <input type="checkbox" disabled={!editable} checked={!!client.autoPublish[k]} onChange={() => toggleAuto(k)} /> Auto-publish
                </label>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="SEO keywords" action={<Link to="/seo" className="small">SEO Center</Link>}>
          <ul className="list">
            {kws.map((k) => (
              <li key={k.id} className="row between">
                <span>{k.keyword}</span>
                <Badge tone={k.currentRank <= k.previousRank ? 'green' : 'red'}>#{k.currentRank} {k.currentRank < k.previousRank ? `▲${k.previousRank - k.currentRank}` : k.currentRank > k.previousRank ? `▼${k.currentRank - k.previousRank}` : ''}</Badge>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid cols-3">
        <Card title="Latest reviews" action={<Link to={`/reviews?client=${client.id}`} className="small">All</Link>}>
          <ul className="list">
            {reviews.slice(0, 4).map((r) => (
              <li key={r.id}>
                <div className="row between"><Stars n={r.rating} /><StatusBadge status={r.replyStatus} /></div>
                <p className="small" style={{ margin: '4px 0 0' }}>{r.text.slice(0, 80)}{r.text.length > 80 ? '…' : ''}</p>
              </li>
            ))}
          </ul>
        </Card>
        <Card title="Content calendar" action={<Link to="/social" className="small">Calendar</Link>}>
          {content.length === 0 ? <p className="muted">No content yet.</p> : (
            <ul className="list">
              {content.map((c) => (
                <li key={c.id} className="row between">
                  <span>{c.topic}<div className="muted small">{c.scheduledAt ? fmtDateTime(c.scheduledAt) : 'Unscheduled'}</div></span>
                  <StatusBadge status={c.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Open tasks & reports">
          <ul className="list">
            {tasks.map((t) => <li key={t.id} className="row between"><span>{t.title}<div className="muted small">Due {fmtDate(t.dueDate)}</div></span><StatusBadge status={t.status} /></li>)}
            {reports.map((r) => <li key={r.id} className="row between"><span>Report {fmtDate(r.periodStart)} – {fmtDate(r.periodEnd)}</span><Badge tone={r.deliveredAt ? 'green' : 'gray'}>{r.deliveredAt ? 'Delivered' : 'Draft'}</Badge></li>)}
            {tasks.length + reports.length === 0 && <li className="muted">Nothing open.</li>}
          </ul>
        </Card>
      </div>

      <Card title="Notes" action={editable && <button className="btn sm" disabled={notes === client.notes} onClick={() => set({ notes }, 'updated notes')}>Save</button>}>
        <textarea className="input" value={notes} readOnly={!editable} onChange={(e) => setNotes(e.target.value)} placeholder="Meeting notes, preferences, context for the team…" />
      </Card>
    </>
  );
}
