import { useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { logout, useCurrentUser, useDB } from '../data/store';
import { ROLE_LABELS } from '../data/types';
import { canSee, type Section } from '../lib/permissions';
import { runtimePlatform } from '../lib/platform';
import { Icon, type IconName } from './Icon';

const NAV: { to: string; label: string; short?: string; section: Section; icon: IconName }[] = [
  { to: '/', label: 'Dashboard', section: 'dashboard', icon: 'grid' },
  { to: '/clients', label: 'Clients', section: 'clients', icon: 'users' },
  { to: '/gmb', label: 'GMB Center', section: 'gmb', icon: 'pin' },
  { to: '/reviews', label: 'AI Reviews', short: 'Reviews', section: 'reviews', icon: 'star' },
  { to: '/content', label: 'Content Studio', section: 'content', icon: 'pen' },
  { to: '/creative', label: 'Creative Studio', section: 'creative', icon: 'image' },
  { to: '/social', label: 'Social Hub', section: 'social', icon: 'calendar' },
  { to: '/seo', label: 'SEO Center', section: 'seo', icon: 'search' },
  { to: '/analytics', label: 'Analytics', section: 'analytics', icon: 'chart' },
  { to: '/reports', label: 'Reports', section: 'reports', icon: 'file' },
  { to: '/tasks', label: 'Team & Tasks', section: 'tasks', icon: 'check' },
  { to: '/settings', label: 'Settings', section: 'settings', icon: 'gear' },
];

// Bottom tab bar on phones: the four most-used sections for the role, everything else under "More".
const TAB_PRIORITY: Section[] = ['dashboard', 'reviews', 'content', 'social', 'clients', 'analytics', 'reports'];

export function Layout() {
  const user = useCurrentUser()!;
  const db = useDB();
  const [moreOpen, setMoreOpen] = useState(false);
  const { pathname } = useLocation();
  const items = NAV.filter((n) => canSee(user.role, n.section));
  const tabs = TAB_PRIORITY.filter((s) => items.some((i) => i.section === s)).slice(0, 4).map((s) => items.find((i) => i.section === s)!);
  const pending = db.reviews.filter((r) => (r.replyStatus === 'new' || r.replyStatus === 'drafted') && (!user.clientId || r.clientId === user.clientId)).length;
  const client = user.clientId ? db.clients.find((c) => c.id === user.clientId) : null;

  return (
    <div className={`shell platform-${runtimePlatform()}`}>
      <aside className="sidebar">
        <div className="brand">
          <img src="./icon.svg" alt="" width={32} height={32} />
          <div>
            <strong>Green Media</strong>
            <span>AI Command Center</span>
          </div>
        </div>
        <nav>
          {items.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.to === '/'} className="nav-item">
              <Icon name={n.icon} />
              <span>{n.label}</span>
              {n.section === 'reviews' && pending > 0 && <em className="count">{pending}</em>}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="me">
            <span className="avatar">{user.name[0]}</span>
            <div>
              <strong>{user.name}</strong>
              <span>{client ? client.companyName : ROLE_LABELS[user.role]}</span>
            </div>
          </div>
          <button className="btn ghost sm" onClick={logout}>Sign out</button>
        </div>
      </aside>

      <main className="main" key={pathname}>
        <Outlet />
      </main>

      <nav className="tabbar" aria-label="Primary">
        {tabs.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === '/'} className="tab" onClick={() => setMoreOpen(false)}>
            <Icon name={n.icon} />
            <span>{n.short ?? n.label.split(' ')[0]}</span>
            {n.section === 'reviews' && pending > 0 && <em className="count">{pending}</em>}
          </NavLink>
        ))}
        <button className={`tab ${moreOpen ? 'active' : ''}`} onClick={() => setMoreOpen((o) => !o)}>
          <Icon name="menu" />
          <span>More</span>
        </button>
      </nav>

      {moreOpen && (
        <div className="sheet-backdrop" onClick={() => setMoreOpen(false)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <div className="me">
              <span className="avatar">{user.name[0]}</span>
              <div>
                <strong>{user.name}</strong>
                <span>{client ? client.companyName : ROLE_LABELS[user.role]}</span>
              </div>
            </div>
            <div className="sheet-grid">
              {items.filter((i) => !tabs.includes(i)).map((n) => (
                <NavLink key={n.to} to={n.to} className="sheet-item" onClick={() => setMoreOpen(false)}>
                  <Icon name={n.icon} />
                  <span>{n.label}</span>
                </NavLink>
              ))}
            </div>
            <button className="btn ghost block" onClick={logout}>Sign out</button>
          </div>
        </div>
      )}
    </div>
  );
}
