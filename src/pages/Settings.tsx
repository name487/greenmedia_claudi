import { useState } from 'react';
import { Badge, Card, PageHeader } from '../components/ui';
import { resetDemo, update, useDB } from '../data/store';
import { ROLE_LABELS, type Role, type Settings } from '../data/types';
import { canSee, type Section } from '../lib/permissions';
import { runtimePlatform } from '../lib/platform';

const SECTIONS: Section[] = ['dashboard', 'clients', 'gmb', 'reviews', 'content', 'creative', 'social', 'seo', 'analytics', 'reports', 'tasks', 'settings'];
const INTEGRATIONS = [
  ['Google Business Profile API', 'Reviews, posts, insights'],
  ['Google Search Console', 'Queries, clicks, positions'],
  ['Google Analytics 4', 'Sessions, conversions'],
  ['Meta Graph API', 'Facebook & Instagram publishing'],
  ['LinkedIn Marketing API', 'Company page posts'],
  ['YouTube Data API', 'Video metadata & community'],
  ['WhatsApp Business', 'Report delivery & alerts'],
];

export function SettingsPage() {
  const db = useDB();
  const [api, setApi] = useState(db.settings.apiUrl);
  const [health, setHealth] = useState<string>('');
  const set = (patch: Partial<Settings>) => update((d) => ({ settings: { ...d.settings, ...patch } }), { action: `settings: ${Object.keys(patch).join(', ')}`, entity: 'settings' });

  const test = async () => {
    setHealth('Checking…');
    try {
      const r = await fetch(`${api.replace(/\/$/, '')}/api/health`);
      const j = await r.json();
      setHealth(r.ok ? `Connected · AI ${j.ai ? `on (${j.provider})` : 'off — add an API key on the server'}` : `HTTP ${r.status}`);
    } catch {
      setHealth('Could not reach the server');
    }
  };

  return (
    <>
      <PageHeader title="Settings" subtitle={`Running on ${runtimePlatform()}`} />
      <div className="grid cols-2">
        <Card title="Backend & AI">
          <div className="form">
            <label className="field">API server URL
              <input className="input" value={api} placeholder="https://api.yourdomain.com" onChange={(e) => setApi(e.target.value)} />
            </label>
            <p className="muted small" style={{ margin: 0 }}>AI keys live on the server only. Leave empty to run offline with demo data and template replies.</p>
            <div className="btn-row">
              <button className="btn" onClick={() => set({ apiUrl: api.trim() })} disabled={api === db.settings.apiUrl}>Save</button>
              <button className="btn ghost" onClick={test} disabled={!api}>Test connection</button>
            </div>
            {health && <div className="notice info">{health}</div>}
          </div>
        </Card>
        <Card title="Workflow & notifications">
          <div className="form">
            <label className="check"><input type="checkbox" checked={db.settings.notifyOnNegativeReview} onChange={(e) => set({ notifyOnNegativeReview: e.target.checked })} /> Alert account manager on negative reviews</label>
            <label className="check"><input type="checkbox" checked={db.settings.requireClientApproval} onChange={(e) => set({ requireClientApproval: e.target.checked })} /> Require client approval before content is scheduled</label>
            <label className="field">Theme
              <select className="input" value={db.settings.theme} onChange={(e) => set({ theme: e.target.value as Settings['theme'] })}>
                <option value="system">Match system</option><option value="light">Light</option><option value="dark">Dark</option>
              </select>
            </label>
            <p className="muted small" style={{ margin: 0 }}>Auto-publish is configured per client and per channel in each client workspace.</p>
          </div>
        </Card>
      </div>
      <Card title="Integrations">
        <ul className="list">
          {INTEGRATIONS.map(([n, d]) => (
            <li key={n} className="row between"><span>{n}<div className="muted small">{d}</div></span><Badge tone="gray">Configure on server</Badge></li>
          ))}
        </ul>
      </Card>
      <Card title="Role permissions">
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>Section</th>{(Object.keys(ROLE_LABELS) as Role[]).map((r) => <th key={r}>{ROLE_LABELS[r]}</th>)}</tr></thead>
            <tbody>
              {SECTIONS.map((s) => (
                <tr key={s}><td style={{ textTransform: 'capitalize' }}>{s}</td>{(Object.keys(ROLE_LABELS) as Role[]).map((r) => <td key={r}>{canSee(r, s) ? '✓' : <span className="muted">—</span>}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      <Card title="Demo data">
        <div className="row between">
          <span className="muted">Restore the 24 sample clients and discard local changes.</span>
          <button className="btn danger" onClick={() => { if (confirm('Reset all demo data on this device?')) resetDemo(); }}>Reset demo</button>
        </div>
      </Card>
    </>
  );
}
