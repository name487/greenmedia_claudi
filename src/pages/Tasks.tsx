import { useState, type FormEvent } from 'react';
import { Card, ClientSelect, PageHeader, StatusBadge, fmtDate, fmtDateTime } from '../components/ui';
import { matchClient, useClientFilter } from '../data/scope';
import { uid, update, useCurrentUser, useDB } from '../data/store';
import { ROLE_LABELS, type Task } from '../data/types';

const COLUMNS: { key: Task['status']; label: string }[] = [
  { key: 'todo', label: 'To do' }, { key: 'in_progress', label: 'In progress' }, { key: 'review', label: 'Review' }, { key: 'done', label: 'Done' },
];

export function Tasks() {
  const db = useDB();
  const user = useCurrentUser()!;
  const [filter, setFilter] = useClientFilter();
  const [mine, setMine] = useState(false);
  const staff = db.users.filter((u) => u.role !== 'client');
  const [form, setForm] = useState({ title: '', clientId: db.clients[0].id, assignedTo: user.id, priority: 'medium' as Task['priority'], dueDate: new Date(Date.now() + 3 * 864e5).toISOString().slice(0, 10) });

  const tasks = db.tasks.filter(matchClient(filter)).filter((t) => !mine || t.assignedTo === user.id);
  const move = (t: Task, status: Task['status']) =>
    update((d) => ({ tasks: d.tasks.map((x) => (x.id === t.id ? { ...x, status } : x)) }), { clientId: t.clientId, action: `task "${t.title}" → ${status}`, entity: `task:${t.id}` });

  const add = (e: FormEvent) => {
    e.preventDefault();
    if (!form.title.trim()) return;
    const t: Task = { id: uid('t'), status: 'todo', ...form, title: form.title.trim() };
    update((d) => ({ tasks: [t, ...d.tasks] }), { clientId: t.clientId, action: `created task "${t.title}"`, entity: `task:${t.id}` });
    setForm({ ...form, title: '' });
  };

  const name = (id: string) => db.users.find((u) => u.id === id)?.name ?? id;

  return (
    <>
      <PageHeader title="Team & Tasks" subtitle="Assignments, approvals and audit trail" actions={
        <>
          <label className="check"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> Only mine</label>
          <ClientSelect value={filter} onChange={setFilter} />
        </>
      } />
      <Card title="New task">
        <form className="toolbar" style={{ margin: 0 }} onSubmit={add}>
          <input className="input" placeholder="What needs doing?" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <ClientSelect value={form.clientId} onChange={(v) => setForm({ ...form, clientId: v })} allowAll={false} />
          <select className="input" value={form.assignedTo} onChange={(e) => setForm({ ...form, assignedTo: e.target.value })} aria-label="Assignee">
            {staff.map((u) => <option key={u.id} value={u.id}>{u.name} · {ROLE_LABELS[u.role]}</option>)}
          </select>
          <select className="input" value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value as Task['priority'] })} aria-label="Priority">
            <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option>
          </select>
          <input className="input" style={{ flex: 'none', width: 'auto' }} type="date" value={form.dueDate} onChange={(e) => setForm({ ...form, dueDate: e.target.value })} aria-label="Due date" />
          <button className="btn" type="submit">Add</button>
        </form>
      </Card>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))' }}>
        {COLUMNS.map((col) => {
          const list = tasks.filter((t) => t.status === col.key);
          return (
            <Card key={col.key} title={`${col.label} (${list.length})`}>
              <ul className="list">
                {list.map((t) => (
                  <li key={t.id}>
                    <div className="row between"><strong>{t.title}</strong><StatusBadge status={t.priority} /></div>
                    <div className="muted small">{db.clients.find((c) => c.id === t.clientId)?.companyName} · {name(t.assignedTo)} · due {fmtDate(t.dueDate)}</div>
                    <select className="input" style={{ marginTop: 6, minHeight: 30, padding: '2px 8px' }} value={t.status} onChange={(e) => move(t, e.target.value as Task['status'])} aria-label="Status">
                      {COLUMNS.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
                    </select>
                  </li>
                ))}
              </ul>
            </Card>
          );
        })}
      </div>
      <Card title="Audit trail">
        {db.audit.length === 0 ? <p className="muted">Actions taken in the app are logged here.</p> : (
          <ul className="list">
            {db.audit.filter(matchClient(filter) as (a: { clientId?: string }) => boolean).slice(0, 30).map((a) => (
              <li key={a.id} className="row between small">
                <span><strong>{name(a.userId)}</strong> {a.action}{a.clientId && <span className="muted"> · {db.clients.find((c) => c.id === a.clientId)?.companyName}</span>}</span>
                <span className="muted">{fmtDateTime(a.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

