import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useJobStore } from '../stores/jobStore';

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const setActiveTab = useJobStore((s) => s.setActiveTab);
  const theme = useJobStore((s) => s.theme);
  const toggleTheme = useJobStore((s) => s.toggleTheme);

  const handleTabChange = (tab: 'submit' | 'jobs') => {
    setActiveTab(tab);
    navigate(tab === 'submit' ? '/submit' : '/jobs');
  };

  const isSubmitActive = location.pathname === '/' || location.pathname === '/submit';
  const isJobsActive = location.pathname.startsWith('/jobs');

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
        </nav>
        <div className="app-header__actions">
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
