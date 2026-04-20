import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useJobStore } from '../stores/jobStore';
import { useAuth } from '../contexts/AuthContext';

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const setActiveTab = useJobStore((s) => s.setActiveTab);
  const theme = useJobStore((s) => s.theme);
  const toggleTheme = useJobStore((s) => s.toggleTheme);
  const { user, logout } = useAuth();

  const handleTabChange = (tab: 'submit' | 'jobs' | 'library' | 'library-qa') => {
    setActiveTab(tab);
    const routeMap: Record<typeof tab, string> = {
      submit: '/submit',
      jobs: '/jobs',
      library: '/library',
      'library-qa': '/library/qa',
    };
    navigate(routeMap[tab]);
  };

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  // `/library/qa` is a prefix of `/library`, so test it first.
  const isLibraryQAActive = location.pathname.startsWith('/library/qa');
  const isLibraryActive = !isLibraryQAActive && location.pathname.startsWith('/library');
  const isJobsActive = location.pathname.startsWith('/jobs');
  const isSubmitActive = location.pathname === '/' || location.pathname === '/submit';

  return (
    <div style={{ minHeight: '100vh', background: 'var(--color-bg)' }}>
      <header className="app-header">
        <h1 className="app-header__title" onClick={() => navigate('/')}>
          VideoResearchPro
        </h1>
        <nav className="app-header__nav">
          <TabButton active={isSubmitActive} onClick={() => handleTabChange('submit')}>
            Submit Job
          </TabButton>
          <TabButton active={isJobsActive} onClick={() => handleTabChange('jobs')}>
            Jobs
          </TabButton>
          <TabButton active={isLibraryActive} onClick={() => handleTabChange('library')}>
            Library
          </TabButton>
          <TabButton active={isLibraryQAActive} onClick={() => handleTabChange('library-qa')}>
            Global Q&amp;A
          </TabButton>
        </nav>
        <div className="app-header__actions" style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {user && (
            <span style={{ fontSize: '0.9rem', color: '#fff', opacity: 0.9 }} title={user.email}>
              {user.email}
            </span>
          )}
          <button
            type="button"
            onClick={toggleTheme}
            aria-label={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}
            style={{
              background: 'rgba(255,255,255,0.15)',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.3)',
              padding: '0.4rem 0.8rem',
              borderRadius: 8,
              cursor: 'pointer',
              fontSize: '0.85rem',
              fontWeight: 500,
            }}
          >
            {theme === 'light' ? 'Dark' : 'Light'} mode
          </button>
          <button
            onClick={handleLogout}
            style={{
              background: 'rgba(255,255,255,0.15)',
              color: '#fff',
              border: '1px solid rgba(255,255,255,0.3)',
              padding: '0.4rem 1rem',
              borderRadius: 8,
              cursor: 'pointer',
              fontWeight: 600,
              fontSize: '0.85rem',
            }}
          >
            Logout
          </button>
        </div>
      </header>
      <main className="app-main">
        <Outlet />
      </main>
    </div>
  );
}

function TabButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? 'rgba(255,255,255,0.2)' : 'transparent',
        color: '#fff',
        border: 'none',
        padding: '0.5rem 1.2rem',
        borderRadius: 8,
        cursor: 'pointer',
        fontWeight: active ? 600 : 400,
        fontSize: '0.95rem',
        transition: 'background 0.2s',
      }}
    >
      {children}
    </button>
  );
}
