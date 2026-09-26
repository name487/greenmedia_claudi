import type { ReactNode } from 'react';
import { useDB } from '../data/store';
import type { Client } from '../data/types';

export function Card({ title, action, children, className = '' }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-head">
          {title && <h3>{title}</h3>}
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, delta, hint }: { label: string; value: ReactNode; delta?: number; hint?: string }) {
  return (
    <div className="stat">
      <span className="stat-label">{label}</span>
      <strong className="stat-value">{value}</strong>
      {delta !== undefined && <span className={`delta ${delta >= 0 ? 'up' : 'down'}`}>{delta >= 0 ? '▲' : '▼'} {Math.abs(delta)}%</span>}
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  );
}

export type Tone = 'green' | 'amber' | 'red' | 'blue' | 'gray' | 'purple';

export function Badge({ tone = 'gray', children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export const STATUS_TONE: Record<string, Tone> = {
  active: 'green', onboarding: 'blue', paused: 'gray',
  new: 'blue', drafted: 'purple', approved: 'amber', published: 'green', rejected: 'gray', failed: 'red',
  draft: 'gray', in_review: 'amber', scheduled: 'blue',
  positive: 'green', neutral: 'amber', negative: 'red',
  todo: 'gray', in_progress: 'blue', review: 'amber', done: 'green',
  low: 'gray', medium: 'amber', high: 'red',
};

export const StatusBadge = ({ status }: { status: string }) => <Badge tone={STATUS_TONE[status] ?? 'gray'}>{status.replace(/_/g, ' ')}</Badge>;

export function Stars({ n }: { n: number }) {
  return (
    <span className="stars" aria-label={`${n} out of 5 stars`}>
      {'★★★★★'.slice(0, Math.round(n))}
      <span className="stars-off">{'★★★★★'.slice(Math.round(n))}</span>
    </span>
  );
}

export function LineChart({ series, height = 160, labels }: { series: { name: string; values: number[]; color: string }[]; height?: number; labels?: string[] }) {
  const w = 600;
  const max = Math.max(1, ...series.flatMap((s) => s.values));
  const n = Math.max(...series.map((s) => s.values.length));
  const x = (i: number) => (n <= 1 ? 0 : (i / (n - 1)) * w);
  const y = (v: number) => height - 8 - (v / max) * (height - 16);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" role="img" aria-label={series.map((s) => s.name).join(', ')}>
        {[0.25, 0.5, 0.75].map((f) => (
          <line key={f} x1={0} x2={w} y1={height * f} y2={height * f} className="gridline" />
        ))}
        {series.map((s) => (
          <polyline key={s.name} fill="none" stroke={s.color} strokeWidth={2} vectorEffect="non-scaling-stroke" points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
        ))}
      </svg>
      <figcaption className="legend">
        {series.map((s) => (
          <span key={s.name}>
            <i style={{ background: s.color }} /> {s.name}
          </span>
        ))}
        {labels && <span className="legend-range">{labels[0]} → {labels[labels.length - 1]}</span>}
      </figcaption>
    </figure>
  );
}

export function BarList({ rows, format = (v: number) => v.toLocaleString() }: { rows: { label: string; value: number }[]; format?: (v: number) => string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="barlist">
      {rows.map((r) => (
        <li key={r.label}>
          <span className="barlist-label">{r.label}</span>
          <span className="barlist-track">
            <span style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="barlist-value">{format(r.value)}</span>
        </li>
      ))}
    </ul>
  );
}

export function ClientSelect({ value, onChange, allowAll = true, clients }: { value: string; onChange: (id: string) => void; allowAll?: boolean; clients?: Client[] }) {
  const db = useDB();
  const list = clients ?? db.clients;
  return (
    <select className="input" value={value} onChange={(e) => onChange(e.target.value)} aria-label="Client">
      {allowAll && <option value="all">All clients ({list.length})</option>}
      {list.map((c) => (
        <option key={c.id} value={c.id}>
          {c.companyName}
        </option>
      ))}
    </select>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="page-header">
      <div>
        <h1>{title}</h1>
        {subtitle && <p className="muted">{subtitle}</p>}
      </div>
      {actions && <div className="page-actions">{actions}</div>}
    </div>
  );
}

export const fmtDate = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
export const fmtDateTime = (iso: string) => new Date(iso).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
export const compact = (n: number) => Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(n);
