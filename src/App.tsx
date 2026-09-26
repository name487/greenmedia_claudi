import { useEffect, type ReactNode } from 'react';
import { HashRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Layout } from './components/Layout';
import { useCurrentUser, useDB } from './data/store';
import { canSee, type Section } from './lib/permissions';
import { Analytics } from './pages/Analytics';
import { ClientList } from './pages/ClientList';
import { ClientWorkspace } from './pages/ClientWorkspace';
import { ContentStudio } from './pages/ContentStudio';
import { CreativeStudio } from './pages/CreativeStudio';
import { Dashboard } from './pages/Dashboard';
import { GmbCenter } from './pages/GmbCenter';
import { Login } from './pages/Login';
import { Reports } from './pages/Reports';
import { ReviewQueue } from './pages/ReviewQueue';
import { SeoCenter } from './pages/SeoCenter';
import { SettingsPage } from './pages/Settings';
import { SocialHub } from './pages/SocialHub';
import { Tasks } from './pages/Tasks';

function Guard({ section, children }: { section: Section; children: ReactNode }) {
  const user = useCurrentUser();
  if (!user) return <Navigate to="/login" replace />;
  return canSee(user.role, section) ? <>{children}</> : <Navigate to="/" replace />;
}

function useTheme() {
  const { theme } = useDB().settings;
  useEffect(() => {
    if (theme === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);
}

// HashRouter: deep links work from file:// (Electron) and capacitor:// (iOS/Android) without server rewrites.
export function App() {
  const user = useCurrentUser();
  useTheme();
  return (
    <HashRouter>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <Login />} />
        <Route element={user ? <Layout /> : <Navigate to="/login" replace />}>
          <Route index element={<Guard section="dashboard"><Dashboard /></Guard>} />
          <Route path="clients" element={<Guard section="clients"><ClientList /></Guard>} />
          <Route path="clients/:id" element={<Guard section="clients"><ClientWorkspace /></Guard>} />
          <Route path="gmb" element={<Guard section="gmb"><GmbCenter /></Guard>} />
          <Route path="reviews" element={<Guard section="reviews"><ReviewQueue /></Guard>} />
          <Route path="content" element={<Guard section="content"><ContentStudio /></Guard>} />
          <Route path="creative" element={<Guard section="creative"><CreativeStudio /></Guard>} />
          <Route path="social" element={<Guard section="social"><SocialHub /></Guard>} />
          <Route path="seo" element={<Guard section="seo"><SeoCenter /></Guard>} />
          <Route path="analytics" element={<Guard section="analytics"><Analytics /></Guard>} />
          <Route path="reports" element={<Guard section="reports"><Reports /></Guard>} />
          <Route path="tasks" element={<Guard section="tasks"><Tasks /></Guard>} />
          <Route path="settings" element={<Guard section="settings"><SettingsPage /></Guard>} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </HashRouter>
  );
}
