import { useState, type FormEvent } from 'react';
import { Badge, Card, ClientSelect, LineChart, PageHeader, Stat, StatusBadge, compact, fmtDate } from '../components/ui';
import { matchClient, useClientFilter } from '../data/scope';
import { uid, update, useDB } from '../data/store';
import { pctChange, sumMetrics } from '../lib/ai';

export function SeoCenter() {
  const db = useDB();
  const [filter, setFilter] = useClientFilter();
  const [sort, setSort] = useState<'change' | 'rank' | 'volume'>('change');
  const [kw, setKw] = useState('');

  const kws = db.keywords.filter(matchClient(filter)).sort((a, b) =>
    sort === 'rank' ? a.currentRank - b.currentRank : sort === 'volume' ? b.volume - a.volume : (b.previousRank - b.currentRank) - (a.previousRank - a.currentRank),
  );
  const ids = filter === 'all' ? db.clients.map((c) => c.id) : [filter];
  const days = Array.from({ length: 90 }, (_, i) => ids.reduce((s, id) => s + db.metrics[id][i].organicSessions, 0));
  const clicks = Array.from({ length: 90 }, (_, i) => ids.reduce((s, id) => s + db.metrics[id][i].webClicks, 0));
  const cur = sumMetrics(ids.flatMap((id) => db.metrics[id].slice(60)));
  const prev = sumMetrics(ids.flatMap((id) => db.metrics[id].slice(30, 60)));
  const top10 = kws.filter((k) => k.currentRank <= 10).length;
  const improved = kws.filter((k) => k.currentRank < k.previousRank).length;
  const tasks = db.tasks.filter(matchClient(filter)).filter((t) => t.assignedTo === 'u_seo');

  const add = (e: FormEvent) => {
    e.preventDefault();
    if (filter === 'all' || !kw.trim()) return;
    const c = db.clients.find((x) => x.id === filter)!;
    const rank = 30 + Math.floor(Math.random() * 40);
    update((d) => ({ keywords: [...d.keywords, { id: uid('kw'), clientId: c.id, keyword: kw.trim(), targetUrl: c.website, location: c.city, currentRank: rank, previousRank: rank, volume: 100 }] }), { clientId: c.id, action: `tracking keyword "${kw.trim()}"`, entity: 'seo_keyword' });
    setKw('');
  };

  return (
    <>
      <PageHeader title="SEO Center" subtitle="Keywords, rankings, Search Console & GA4" actions={<ClientSelect value={filter} onChange={setFilter} />} />
      <div className="grid stats">
        <Stat label="Tracked keywords" value={kws.length} />
        <Stat label="In top 10" value={top10} />
        <Stat label="Improved this month" value={improved} hint={`${kws.length - improved} flat/declined`} />
        <Stat label="Organic sessions (GA4)" value={compact(cur.organicSessions)} delta={pctChange(cur.organicSessions, prev.organicSessions)} />
        <Stat label="Search clicks (GSC)" value={compact(cur.webClicks)} delta={pctChange(cur.webClicks, prev.webClicks)} />
      </div>
      <div className="grid cols-3">
        <Card title="Organic traffic — 90 days" className="span-2">
          <LineChart series={[{ name: 'Organic sessions', color: 'var(--c1)', values: days }, { name: 'GSC clicks ×5', color: 'var(--c4)', values: clicks.map((c) => c * 5) }]} />
        </Card>
        <Card title="Technical tasks">
          {tasks.length === 0 ? <p className="muted">No open SEO tasks.</p> : (
            <ul className="list">{tasks.map((t) => <li key={t.id} className="row between"><span>{t.title}<div className="muted small">{db.clients.find((c) => c.id === t.clientId)?.companyName} · due {fmtDate(t.dueDate)}</div></span><StatusBadge status={t.status} /></li>)}</ul>
          )}
        </Card>
      </div>
      <Card title="Keyword rankings" action={
        <div className="pill-tabs" style={{ margin: 0 }}>
          {(['change', 'rank', 'volume'] as const).map((s) => <button key={s} className={sort === s ? 'on' : ''} onClick={() => setSort(s)}>{s === 'change' ? 'Biggest movers' : s === 'rank' ? 'Best rank' : 'Volume'}</button>)}
        </div>
      }>
        {filter !== 'all' && (
          <form className="toolbar" onSubmit={add}>
            <input className="input" placeholder="Track a new keyword…" value={kw} onChange={(e) => setKw(e.target.value)} />
            <button className="btn" type="submit">Add</button>
          </form>
        )}
        <div className="table-wrap">
          <table className="table responsive">
            <thead><tr><th>Keyword</th><th>Client</th><th className="num">Current</th><th className="num">Previous</th><th className="num">Change</th><th className="num">Volume</th></tr></thead>
            <tbody>
              {kws.map((k) => {
                const ch = k.previousRank - k.currentRank;
                return (
                  <tr key={k.id}>
                    <td className="primary">{k.keyword}<div className="muted small">{k.targetUrl.replace('https://', '')}</div></td>
                    <td data-label="Client">{db.clients.find((c) => c.id === k.clientId)?.companyName}</td>
                    <td data-label="Current" className="num">#{k.currentRank}</td>
                    <td data-label="Previous" className="num">#{k.previousRank}</td>
                    <td data-label="Change" className="num"><Badge tone={ch > 0 ? 'green' : ch < 0 ? 'red' : 'gray'}>{ch > 0 ? `▲ ${ch}` : ch < 0 ? `▼ ${-ch}` : '—'}</Badge></td>
                    <td data-label="Volume" className="num">{k.volume.toLocaleString()}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
