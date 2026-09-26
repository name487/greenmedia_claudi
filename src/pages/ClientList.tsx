import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Card, PageHeader, Stars, StatusBadge } from '../components/ui';
import { useDB } from '../data/store';

export function ClientList() {
  const db = useDB();
  const nav = useNavigate();
  const [q, setQ] = useState('');
  const [industry, setIndustry] = useState('all');
  const [status, setStatus] = useState('all');
  const [service, setService] = useState('all');

  const industries = useMemo(() => [...new Set(db.clients.map((c) => c.industry))].sort(), [db.clients]);
  const services = useMemo(() => [...new Set(db.clients.flatMap((c) => c.services))].sort(), [db.clients]);
  const rows = db.clients.filter(
    (c) =>
      (industry === 'all' || c.industry === industry) &&
      (status === 'all' || c.status === status) &&
      (service === 'all' || c.services.includes(service)) &&
      `${c.companyName} ${c.city} ${c.contact.name}`.toLowerCase().includes(q.toLowerCase()),
  );
  const pending = (id: string) => db.reviews.filter((r) => r.clientId === id && (r.replyStatus === 'new' || r.replyStatus === 'drafted')).length;

  return (
    <>
      <PageHeader title="Clients" subtitle={`${rows.length} of ${db.clients.length} clients`} />
      <div className="toolbar">
        <input className="input" placeholder="Search client, city or contact…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className="input" value={industry} onChange={(e) => setIndustry(e.target.value)} aria-label="Industry">
          <option value="all">All industries</option>
          {industries.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select className="input" value={service} onChange={(e) => setService(e.target.value)} aria-label="Service">
          <option value="all">All services</option>
          {services.map((i) => <option key={i}>{i}</option>)}
        </select>
        <select className="input" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="all">Any status</option>
          <option value="active">Active</option>
          <option value="onboarding">Onboarding</option>
          <option value="paused">Paused</option>
        </select>
      </div>
      <Card>
        <div className="table-wrap">
          <table className="table responsive">
            <thead>
              <tr><th>Client</th><th>Industry</th><th>Plan</th><th>Rating</th><th>Status</th><th>Quick actions</th></tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="clickable" onClick={() => nav(`/clients/${c.id}`)}>
                  <td className="primary">{c.companyName}<div className="muted small">{c.city} · {c.contact.name}</div></td>
                  <td data-label="Industry">{c.industry}</td>
                  <td data-label="Plan">{c.plan}</td>
                  <td data-label="Rating"><Stars n={c.gmb.rating} /> {c.gmb.rating}</td>
                  <td data-label="Status"><StatusBadge status={c.status} /></td>
                  <td onClick={(e) => e.stopPropagation()}>
                    <div className="btn-row">
                      <Link className="btn soft sm" to={`/clients/${c.id}`}>Open</Link>
                      <Link className="btn soft sm" to={`/reviews?client=${c.id}`}>Reviews{pending(c.id) ? ` (${pending(c.id)})` : ''}</Link>
                      <Link className="btn soft sm" to={`/content?client=${c.id}`}>Content</Link>
                      <Link className="btn soft sm" to={`/reports?client=${c.id}`}>Report</Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
