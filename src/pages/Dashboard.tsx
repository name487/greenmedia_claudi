import { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Badge, BarList, Card, LineChart, PageHeader, Stars, Stat, StatusBadge, compact } from '../components/ui';
import { useVisibleClients } from '../data/scope';
import { useCurrentUser, useDB } from '../data/store';
import { pctChange, sumMetrics } from '../lib/ai';

export function Dashboard() {
  const db = useDB();
  const user = useCurrentUser()!;
  const clients = useVisibleClients();
  const nav = useNavigate();
  const ids = new Set(clients.map((c) => c.id));

  const data = useMemo(() => {
    const reviews = db.reviews.filter((r) => ids.has(r.clientId));
    const pending = reviews.filter((r) => r.replyStatus === 'new' || r.replyStatus === 'drafted');
    const negative = pending.filter((r) => r.sentiment === 'negative');
    const posts = db.content.filter((c) => ids.has(c.clientId));
    const kws = db.keywords.filter((k) => ids.has(k.clientId));
    const seoAlerts = kws.filter((k) => k.currentRank - k.previousRank >= 3);
    const daily = Array.from({ length: 30 }, (_, i) => {
      let views = 0, leads = 0, reach = 0;
      clients.forEach((c) => { const d = db.metrics[c.id][60 + i]; views += d.gmbViews; leads += d.leads; reach += d.socialReach; });
      return { views, leads, reach, date: db.metrics[clients[0].id][60 + i].date };
    });
    const perClient = clients.map((c) => {
      const cur = sumMetrics(db.metrics[c.id].slice(60));
      const prev = sumMetrics(db.metrics[c.id].slice(30, 60));
      return { c, cur, leadsDelta: pctChange(cur.leads, prev.leads), viewsDelta: pctChange(cur.gmbViews, prev.gmbViews), pending: pending.filter((r) => r.clientId === c.id).length };
    });
    const cur = sumMetrics(clients.flatMap((c) => db.metrics[c.id].slice(60)));
    const prev = sumMetrics(clients.flatMap((c) => db.metrics[c.id].slice(30, 60)));
    return { pending, negative, posts, seoAlerts, daily, perClient, cur, prev };
  }, [db, clients]);

  const scheduled = data.posts.filter((p) => p.status === 'scheduled').length;
  const failed = data.posts.filter((p) => p.status === 'failed').length;

  return (
    <>
      <PageHeader title={`Good ${new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 17 ? 'afternoon' : 'evening'}, ${user.name.split(' ')[0]}`} subtitle={user.clientId ? clients[0].companyName : `${clients.length} clients · last 30 days`} actions={!user.clientId && <Link className="btn" to="/content">+ New campaign</Link>} />

      <div className="grid stats">
        {!user.clientId && <Stat label="Active clients" value={clients.filter((c) => c.status === 'active').length} hint={`${clients.filter((c) => c.status === 'onboarding').length} onboarding`} />}
        <Stat label="GMB profiles" value={clients.filter((c) => c.gmb.connected).length} hint={`${clients.filter((c) => !c.gmb.connected).length} need connection`} />
        <Stat label="Pending reviews" value={data.pending.length} hint={`${data.negative.length} negative`} />
        <Stat label="Scheduled posts" value={scheduled} hint={failed ? `${failed} failed` : 'none failed'} />
        <Stat label="Leads" value={compact(data.cur.leads)} delta={pctChange(data.cur.leads, data.prev.leads)} />
        <Stat label="SEO alerts" value={data.seoAlerts.length} hint="keywords dropped 3+" />
      </div>

      <div className="grid cols-3">
        <Card title="Growth — last 30 days" className="span-2" >
          <LineChart labels={data.daily.map((d) => d.date)} series={[{ name: 'GMB views', color: 'var(--c1)', values: data.daily.map((d) => d.views) }, { name: 'Social reach ÷10', color: 'var(--c2)', values: data.daily.map((d) => d.reach / 10) }]} />
        </Card>
        <Card title="Needs attention" action={<Link to="/reviews" className="small">Open queue</Link>}>
          {data.negative.length === 0 && data.seoAlerts.length === 0 ? (
            <p className="muted">All clear. 🎉</p>
          ) : (
            <ul className="list">
              {data.negative.slice(0, 3).map((r) => (
                <li key={r.id}>
                  <div className="row between"><strong>{db.clients.find((c) => c.id === r.clientId)?.companyName}</strong><Stars n={r.rating} /></div>
                  <p className="muted small" style={{ margin: 0 }}>{r.text.slice(0, 90)}…</p>
                </li>
              ))}
              {data.seoAlerts.slice(0, 2).map((k) => (
                <li key={k.id} className="row between">
                  <span>“{k.keyword}”</span>
                  <Badge tone="red">#{k.previousRank} → #{k.currentRank}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {!user.clientId && (
        <Card title="Client performance">
          <div className="table-wrap">
            <table className="table responsive">
              <thead>
                <tr><th>Client</th><th>Plan</th><th>Rating</th><th className="num">GMB views</th><th className="num">Leads</th><th className="num">Pending</th><th>Status</th></tr>
              </thead>
              <tbody>
                {data.perClient.slice().sort((a, b) => b.pending - a.pending || b.cur.leads - a.cur.leads).map(({ c, cur, leadsDelta, pending }) => (
                  <tr key={c.id} className="clickable" onClick={() => nav(`/clients/${c.id}`)}>
                    <td className="primary">{c.companyName}<div className="muted small">{c.industry} · {c.city}</div></td>
                    <td data-label="Plan">{c.plan}</td>
                    <td data-label="Rating"><Stars n={c.gmb.rating} /> {c.gmb.rating}</td>
                    <td data-label="GMB views" className="num">{compact(cur.gmbViews)}</td>
                    <td data-label="Leads" className="num">{cur.leads} <span className={`delta ${leadsDelta >= 0 ? 'up' : 'down'}`}>{leadsDelta >= 0 ? '+' : ''}{leadsDelta}%</span></td>
                    <td data-label="Pending" className="num">{pending || '—'}</td>
                    <td data-label="Status"><StatusBadge status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {user.clientId && (
        <Card title="Where your leads come from">
          <BarList rows={[{ label: 'Calls from Google', value: data.cur.gmbCalls }, { label: 'Direction requests', value: data.cur.gmbDirections }, { label: 'Website clicks', value: data.cur.webClicks }, { label: 'Social engagement', value: data.cur.engagement }]} />
        </Card>
      )}
    </>
  );
}
