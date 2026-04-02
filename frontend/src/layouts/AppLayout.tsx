import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useJobStore } from '../stores/jobStore';

export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setActiveTab } = useJobStore();

  const handleTabChange = (tab: 'submit' | 'jobs') => {
    setActiveTab(tab);
    navigate(tab === 'submit' ? '/submit' : '/jobs');
  };

  const isSubmitActive = location.pathname === '/' || location.pathname === '/submit';
  const isJobsActive = location.pathname.startsWith('/jobs');

  return (
    <div style={{ minHeight: '100vh', background: '#f1f5f9' }}>
      <header style={{
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        padding: '1rem 2rem',
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        gap: '2rem',
      }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700, margin: 0, cursor: 'pointer' }}
            onClick={() => navigate('/')}>
          VideoResearchPro
        </h1>
        <nav style={{ display: 'flex', gap: '0.5rem' }}>
          <TabButton active={isSubmitActive} onClick={() => handleTabChange('submit')}>
            Submit Job
          </TabButton>
          <TabButton active={isJobsActive} onClick={() => handleTabChange('jobs')}>
            Jobs
          </TabButton>
        </nav>
      </header>
      <main style={{ maxWidth: 1200, margin: '0 auto', padding: '1.5rem' }}>
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
