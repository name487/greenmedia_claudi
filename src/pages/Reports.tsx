import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Icon } from '../components/Icon';
import { Badge, Card, ClientSelect, Empty, PageHeader, fmtDate } from '../components/ui';
import { useClientFilter, useVisibleClients } from '../data/scope';
import { getDB, uid, update, useCurrentUser, useDB } from '../data/store';
import type { Report } from '../data/types';
import { generateReportSummary, pctChange, sumMetrics } from '../lib/ai';
import { can } from '../lib/permissions';

const KPI: [keyof ReturnType<typeof sumMetrics>, string][] = [
  ['gmbViews', 'GMB profile views'], ['gmbCalls', 'Calls'], ['gmbDirections', 'Direction requests'], ['webClicks', 'Website clicks'],
  ['organicSessions', 'Organic sessions'], ['socialReach', 'Social reach'], ['engagement', 'Engagement'], ['leads', 'Leads'],
];

export function Reports() {
  const db = useDB();
  const user = useCurrentUser()!;
  const clients = useVisibleClients();
  const [params] = useSearchParams();
  const [clientId, setClientId, pinned] = useClientFilter(params.get('client') ?? clients[0].id);
  const [busy, setBusy] = useState(false);
  const [openId, setOpenId] = useState<string | null>(null);
  const client = db.clients.find((c) => c.id === clientId)!;
  const reports = db.reports.filter((r) => r.clientId === clientId);
  const open = reports.find((r) => r.id === openId) ?? reports[0];

  const generate = async () => {
    setBusy(true);
    const m = db.metrics[clientId];
    const kws = db.keywords.filter((k) => k.clientId === clientId);
    const monthAgo = Date.now() - 30 * 864e5;
    const res = await generateReportSummary({
      client, current: m.slice(60), previous: m.slice(30, 60),
      rankUp: kws.filter((k) => k.currentRank < k.previousRank).length,
      rankDown: kws.filter((k) => k.currentRank > k.previousRank).length,
      reviewsReplied: db.reviews.filter((r) => r.clientId === clientId && r.replyStatus === 'published' && r.publishedAt && +new Date(r.publishedAt) > monthAgo).length,
      postsPublished: db.content.filter((c) => c.clientId === clientId && c.status === 'published').length,
    });
    const report: Report = { id: uid('rp'), clientId, periodStart: m[60].date, periodEnd: m[89].date, summary: res.data, createdAt: new Date().toISOString() };
    update((d) => ({ reports: [report, ...d.reports] }), { clientId, action: `generated report (${res.source})`, entity: `report:${report.id}` });
    setOpenId(report.id);
    setBusy(false);
  };

  const deliver = (r: Report, via: 'email' | 'whatsapp') => {
    const text = `${client.companyName} — Monthly marketing report (${fmtDate(r.periodStart)} – ${fmtDate(r.periodEnd)})\n\n${r.summary}\n\n— Green Media Technology`;
    const url = via === 'email'
      ? `mailto:${client.contact.email}?subject=${encodeURIComponent(`Your monthly marketing report — ${client.companyName}`)}&body=${encodeURIComponent(text)}`
      : `https://wa.me/${client.contact.phone.replace(/\D/g, '')}?text=${encodeURIComponent(text)}`;
    window.open(url, '_blank');
    update((d) => ({ reports: d.reports.map((x) => (x.id === r.id ? { ...x, deliveredAt: new Date().toISOString(), deliveredVia: via } : x)) }), { clientId, action: `delivered report via ${via}`, entity: `report:${r.id}` });
  };

  const m = getDB().metrics[clientId];
  const cur = sumMetrics(m.slice(60));
  const prev = sumMetrics(m.slice(30, 60));
  const kws = db.keywords.filter((k) => k.clientId === clientId);

  return (
    <>
      <PageHeader title="Reports" subtitle="AI monthly report → PDF → email / WhatsApp" actions={
        <>
          {!pinned && <ClientSelect value={clientId} onChange={(v) => { setClientId(v); setOpenId(null); }} allowAll={false} />}
          {can(user.role, 'report.deliver') && <button className="btn" disabled={busy} onClick={generate}><Icon name="sparkle" size={16} /> {busy ? 'Generating…' : 'Generate monthly report'}</button>}
        </>
      } />
      {!open ? <Card><Empty>No reports yet for {client.companyName}.{can(user.role, 'report.deliver') && ' Generate the first one above.'}</Empty></Card> : (
        <>
          <Card title={`${client.companyName} · ${fmtDate(open.periodStart)} – ${fmtDate(open.periodEnd)}`} action={
            <div className="btn-row no-print">
              {open.deliveredAt && <Badge tone="green">Sent via {open.deliveredVia}</Badge>}
              <button className="btn ghost sm" onClick={() => window.print()}>PDF</button>
              {can(user.role, 'report.deliver') && <>
                <button className="btn soft sm" onClick={() => deliver(open, 'email')}>Email</button>
                <button className="btn soft sm" onClick={() => deliver(open, 'whatsapp')}>WhatsApp</button>
              </>}
            </div>
          }>
            <pre className="report">{open.summary}</pre>
          </Card>
          <div className="grid cols-2">
            <Card title="KPI comparison">
              <div className="table-wrap">
                <table className="table">
                  <thead><tr><th>Metric</th><th className="num">This period</th><th className="num">Previous</th><th className="num">Change</th></tr></thead>
                  <tbody>
                    {KPI.map(([k, label]) => {
                      const d = pctChange(cur[k], prev[k]);
                      return <tr key={k}><td>{label}</td><td className="num">{cur[k].toLocaleString()}</td><td className="num">{prev[k].toLocaleString()}</td><td className="num"><span className={`delta ${d >= 0 ? 'up' : 'down'}`}>{d >= 0 ? '+' : ''}{d}%</span></td></tr>;
                    })}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Ranking movement">
              <ul className="list">
                {kws.map((k) => <li key={k.id} className="row between"><span>{k.keyword}</span><span className="small">#{k.previousRank} → <strong>#{k.currentRank}</strong></span></li>)}
              </ul>
            </Card>
          </div>
          {reports.length > 1 && (
            <Card title="History" className="no-print">
              <ul className="list">
                {reports.map((r) => <li key={r.id} className="row between"><button className="btn ghost sm" onClick={() => setOpenId(r.id)}>{fmtDate(r.periodStart)} – {fmtDate(r.periodEnd)}</button><span className="muted small">created {fmtDate(r.createdAt)}</span></li>)}
              </ul>
            </Card>
          )}
        </>
      )}
    </>
  );
}
