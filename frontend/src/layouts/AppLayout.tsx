import { useState, type CSSProperties, type ReactNode } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { useJobStore, type AppTab } from '../stores/jobStore';
import { useAuth } from '../contexts/AuthContext';
import { useSystemStatus } from '../hooks/useSystemStatus';
import { SystemStatusBanner } from '../components/common/SystemStatusBanner';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, motion } from '../theme';

/**
 * Editorial sidebar layout.
 *
 * Desktop (≥960px): 240px fixed sidebar on the left, content fills the rest.
 * Mobile (<960px): sidebar collapses into a top header strip with a hamburger
 * that reveals the nav as a drawer panel below the header.
 *
 * The brand lockup (Devanagari `प्रतिध्वनि` + Latin `Pratidhvani`) owns the top
 * of the sidebar; user chrome (email, theme toggle, logout) sits at the bottom.
 */
export function AppLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const c = useColors();
  const setActiveTab = useJobStore((s) => s.setActiveTab);
  const theme = useJobStore((s) => s.theme);
  const toggleTheme = useJobStore((s) => s.toggleTheme);
  const { user, logout } = useAuth();
  const { refetch: refetchSystemStatus } = useSystemStatus();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const handleTabChange = (tab: AppTab) => {
    setActiveTab(tab);
    const routeMap: Record<AppTab, string> = {
      submit: '/submit',
      jobs: '/jobs',
      library: '/library',
      'library-qa': '/library/qa',
      'qa-history': '/qa-history',
      exports: '/exports',
    };
    navigate(routeMap[tab]);
    setMobileNavOpen(false);
  };

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  // `/library/qa` is a prefix of `/library`, so test it first.
  const isLibraryQAActive = location.pathname.startsWith('/library/qa');
  const isLibraryActive = !isLibraryQAActive && location.pathname.startsWith('/library');
  const isJobsActive = location.pathname.startsWith('/jobs');
  const isQAHistoryActive = location.pathname.startsWith('/qa-history');
  const isExportsActive = location.pathname.startsWith('/exports');
  const isSubmitActive = location.pathname === '/' || location.pathname === '/submit';

  const nav = (
    <NavContent
      onChange={handleTabChange}
      active={{
        submit: isSubmitActive,
        jobs: isJobsActive,
        library: isLibraryActive,
        'library-qa': isLibraryQAActive,
        'qa-history': isQAHistoryActive,
        exports: isExportsActive,
      }}
    />
  );

  const chrome = (
    <UserChrome
      email={user?.email}
      theme={theme}
      onToggleTheme={toggleTheme}
      onLogout={handleLogout}
    />
  );

  return (
    <div
      style={{
        minHeight: '100vh',
        background: c.bg,
        color: c.textPrimary,
        display: 'flex',
      }}
    >
      {/* Sidebar — visible as a column on desktop, hidden on mobile. */}
      <aside
        className="pratidhvani-sidebar"
        style={{
          width: 240,
          flexShrink: 0,
          borderRight: `1px solid ${c.border}`,
          background: c.surface,
          display: 'flex',
          flexDirection: 'column',
          position: 'sticky',
          top: 0,
          height: '100vh',
          padding: `${space['5']} ${space['4']}`,
        }}
      >
        <BrandLockup onClick={() => handleTabChange('submit')} />
        <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', marginTop: space['6'] }}>
          {nav}
        </div>
        <div style={{ marginTop: space['4'] }}>{chrome}</div>
      </aside>

      {/* Main column — on mobile, stacks the mobile bar above the content. */}
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
        {/* Mobile top bar — hidden on desktop, sticky-pinned at the top on mobile. */}
        <header
          className="pratidhvani-mobile-bar"
          style={{
            display: 'none',
            position: 'sticky',
            top: 0,
            zIndex: 100,
            padding: `${space['3']} ${space['4']}`,
            background: c.surface,
            borderBottom: `1px solid ${c.border}`,
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <BrandLockup compact onClick={() => handleTabChange('submit')} />
          <HamburgerButton
            open={mobileNavOpen}
            onClick={() => setMobileNavOpen((open) => !open)}
          />
        </header>
        {/* Mobile drawer (renders inline below the header when open). */}
        {mobileNavOpen && (
          <div
            className="pratidhvani-mobile-drawer"
            style={{
              display: 'none',
              background: c.surface,
              borderBottom: `1px solid ${c.border}`,
              padding: space['4'],
            }}
          >
            {nav}
            <div style={{ marginTop: space['4'], paddingTop: space['4'], borderTop: `1px solid ${c.border}` }}>
              {chrome}
            </div>
          </div>
        )}
        <SystemStatusBanner onRetry={() => { void refetchSystemStatus(); }} />
        <main style={{ flex: 1, padding: `${space['6']} ${space['6']} ${space['8']}` }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Internal chrome

interface NavContentProps {
  onChange: (tab: AppTab) => void;
  active: Record<AppTab, boolean>;
}

function NavContent({ onChange, active }: NavContentProps) {
  return (
    <nav aria-label="Primary" style={{ display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <NavGroup label="Research">
        <NavItem active={active.submit}      onClick={() => onChange('submit')}>New research</NavItem>
        <NavItem active={active.jobs}        onClick={() => onChange('jobs')}>Active runs</NavItem>
      </NavGroup>
      <NavGroup label="Library">
        <NavItem active={active.library}     onClick={() => onChange('library')}>All sources</NavItem>
        <NavItem active={active['library-qa']} onClick={() => onChange('library-qa')}>Ask the library</NavItem>
      </NavGroup>
      <NavGroup label="Knowledge">
        <NavItem active={active['qa-history']} onClick={() => onChange('qa-history')}>Echoes (Q&amp;A history)</NavItem>
        <NavItem active={active.exports}      onClick={() => onChange('exports')}>Exports</NavItem>
      </NavGroup>
    </nav>
  );
}

function NavGroup({ label, children }: { label: string; children: ReactNode }) {
  const c = useColors();
  return (
    <div>
      <p
        style={{
          margin: `0 0 ${space['2']} ${space['2']}`,
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          color: c.textMuted,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>{children}</div>
    </div>
  );
}

function NavItem({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);

  const base: CSSProperties = {
    background: active ? c.accentSubtle : hovered ? c.surfaceAlt : 'transparent',
    color: active ? c.accent : c.textPrimary,
    border: 'none',
    borderLeft: `2px solid ${active ? c.accent : 'transparent'}`,
    padding: `${space['2']} ${space['3']}`,
    paddingLeft: active ? `calc(${space['3']} - 2px)` : space['3'],
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    fontWeight: active ? fontWeight.semibold : fontWeight.regular,
    textAlign: 'left',
    cursor: 'pointer',
    borderRadius: radius.sm,
    transition: `background-color ${motion.duration.fast}ms ${motion.easing.standard}, color ${motion.duration.fast}ms ${motion.easing.standard}`,
    outline: focused ? `2px solid ${c.focus}` : 'none',
    outlineOffset: 1,
    width: '100%',
    display: 'block',
  };

  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      aria-current={active ? 'page' : undefined}
      style={base}
    >
      {children}
    </button>
  );
}

function BrandLockup({ onClick, compact = false }: { onClick: () => void; compact?: boolean }) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      aria-label="Pratidhvani — home"
      style={{
        background: 'transparent',
        border: 'none',
        padding: 0,
        cursor: 'pointer',
        textAlign: 'left',
        display: 'block',
        opacity: hovered ? 0.85 : 1,
        transition: `opacity ${motion.duration.fast}ms ${motion.easing.standard}`,
      }}
    >
      <span
        lang="hi"
        style={{
          display: 'block',
          fontFamily: fonts.devanagari,
          fontSize: compact ? fontSize.lg : fontSize['2xl'],
          fontWeight: fontWeight.semibold,
          color: c.accent,
          lineHeight: lineHeight.tight,
        }}
      >
        प्रतिध्वनि
      </span>
      <span
        style={{
          display: 'block',
          fontFamily: fonts.display,
          fontSize: compact ? fontSize.xs : fontSize.sm,
          fontWeight: fontWeight.medium,
          color: c.textSecondary,
          letterSpacing: '0.18em',
          textTransform: 'uppercase',
          marginTop: compact ? 0 : 2,
        }}
      >
        Pratidhvani
      </span>
    </button>
  );
}

interface UserChromeProps {
  email?: string;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  onLogout: () => void;
}

function UserChrome({ email, theme, onToggleTheme, onLogout }: UserChromeProps) {
  const c = useColors();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      {email && (
        <div
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            padding: `0 ${space['2']}`,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
          title={email}
        >
          {email}
        </div>
      )}
      <div style={{ display: 'flex', gap: space['2'] }}>
        <ChromeButton onClick={onToggleTheme} title={`Switch to ${theme === 'light' ? 'dark' : 'light'} mode`}>
          {theme === 'light' ? 'Dark' : 'Light'} mode
        </ChromeButton>
        <ChromeButton onClick={onLogout}>Sign out</ChromeButton>
      </div>
    </div>
  );
}

function ChromeButton({ onClick, title, children }: { onClick: () => void; title?: string; children: ReactNode }) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      title={title}
      style={{
        flex: 1,
        background: hovered ? c.surfaceAlt : 'transparent',
        color: c.textSecondary,
        border: `1px solid ${c.border}`,
        padding: `${space['1']} ${space['2']}`,
        borderRadius: radius.sm,
        cursor: 'pointer',
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        fontWeight: fontWeight.medium,
        transition: `background-color ${motion.duration.fast}ms ${motion.easing.standard}`,
        outline: focused ? `2px solid ${c.focus}` : 'none',
        outlineOffset: 1,
      }}
    >
      {children}
    </button>
  );
}

function HamburgerButton({ open, onClick }: { open: boolean; onClick: () => void }) {
  const c = useColors();
  const bar: CSSProperties = {
    display: 'block',
    height: 2,
    background: c.textPrimary,
    borderRadius: 2,
    width: '100%',
    transition: `transform ${motion.duration.fast}ms ${motion.easing.standard}, opacity ${motion.duration.fast}ms`,
  };
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={open ? 'Close navigation' : 'Open navigation'}
      aria-expanded={open}
      style={{
        background: 'transparent',
        border: 'none',
        padding: space['2'],
        cursor: 'pointer',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        width: 32,
      }}
    >
      <span style={{ ...bar, transform: open ? 'translateY(6px) rotate(45deg)' : 'none' }} />
      <span style={{ ...bar, opacity: open ? 0 : 1 }} />
      <span style={{ ...bar, transform: open ? 'translateY(-6px) rotate(-45deg)' : 'none' }} />
    </button>
  );
}
