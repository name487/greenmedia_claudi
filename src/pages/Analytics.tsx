import { useState } from 'react';
import { BarList, Card, ClientSelect, LineChart, PageHeader, Stat, compact } from '../components/ui';
import { useClientFilter, useVisibleClients } from '../data/scope';
import { useDB } from '../data/store';
import type { MetricDay } from '../data/types';
import { pctChange, sumMetrics } from '../lib/ai';

export function Analytics() {
  const db = useDB();
  const clients = useVisibleClients();
  const [filter, setFilter, pinned] = useClientFilter();
  const [range, setRange] = useState<7 | 30 | 45>(30);

  const ids = filter === 'all' ? clients.map((c) => c.id) : [filter];
  const series = (from: number, to: number): MetricDay[] =>
    Array.from({ length: to - from }, (_, i) => {
      const day = ids.map((id) => db.metrics[id][from + i]);
      const total = sumMetrics(day);
      return { date: day[0].date, ...total };
    });
  const cur = series(90 - range, 90);
  const prev = series(90 - range * 2, 90 - range);
  const c = sumMetrics(cur);
  const p = sumMetrics(prev);
  const labels = cur.map((d) => d.date);

  return (
    <>
      <PageHeader title="Analytics" subtitle="GMB + SEO + Social + leads in one place" actions={
        <>
          {!pinned && <ClientSelect value={filter} onChange={setFilter} clients={clients} />}
          <div className="pill-tabs" style={{ margin: 0 }}>
            {([7, 30, 45] as const).map((r) => <button key={r} className={range === r ? 'on' : ''} onClick={() => setRange(r)}>{r}d</button>)}
          </div>
        </>
      } />
      <div className="grid stats">
        <Stat label="GMB views" value={compact(c.gmbViews)} delta={pctChange(c.gmbViews, p.gmbViews)} />
        <Stat label="GMB actions" value={compact(c.gmbCalls + c.gmbDirections + c.webClicks)} delta={pctChange(c.gmbCalls + c.gmbDirections + c.webClicks, p.gmbCalls + p.gmbDirections + p.webClicks)} />
        <Stat label="Website traffic" value={compact(c.organicSessions)} delta={pctChange(c.organicSessions, p.organicSessions)} />
        <Stat label="Social reach" value={compact(c.socialReach)} delta={pctChange(c.socialReach, p.socialReach)} />
        <Stat label="Engagement" value={compact(c.engagement)} delta={pctChange(c.engagement, p.engagement)} />
        <Stat label="Leads" value={compact(c.leads)} delta={pctChange(c.leads, p.leads)} />
      </div>
      <div className="grid cols-2">
        <Card title="Google Business Profile"><LineChart labels={labels} series={[{ name: 'Views', color: 'var(--c1)', values: cur.map((d) => d.gmbViews) }, { name: 'Actions ×5', color: 'var(--c3)', values: cur.map((d) => (d.gmbCalls + d.gmbDirections + d.webClicks) * 5) }]} /></Card>
        <Card title="Website (GA4)"><LineChart labels={labels} series={[{ name: 'Organic sessions', color: 'var(--c2)', values: cur.map((d) => d.organicSessions) }]} /></Card>
        <Card title="Social"><LineChart labels={labels} series={[{ name: 'Reach', color: 'var(--c4)', values: cur.map((d) => d.socialReach) }, { name: 'Engagement ×10', color: 'var(--c3)', values: cur.map((d) => d.engagement * 10) }]} /></Card>
        <Card title="Leads by source">
          <BarList rows={[{ label: 'Google calls', value: c.gmbCalls }, { label: 'Directions', value: c.gmbDirections }, { label: 'Website clicks', value: c.webClicks }, { label: 'Form & WhatsApp leads', value: c.leads }]} />
        </Card>
      </div>
      {filter === 'all' && clients.length > 1 && (
        <Card title="Top clients by leads">
          <BarList rows={clients.map((cl) => ({ label: cl.companyName, value: sumMetrics(db.metrics[cl.id].slice(90 - range)).leads })).sort((a, b) => b.value - a.value).slice(0, 10)} />
        </Card>
      )}
    </>
  );
}
