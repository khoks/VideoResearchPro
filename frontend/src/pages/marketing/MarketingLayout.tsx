import { useState, type CSSProperties, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { useAuth } from '../../contexts/AuthContext';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, motion } from '../../theme';

/**
 * Public marketing layout — shown to anyone, authed or not, on
 * `/landing`, `/pricing`, `/about`. Warm-editorial top bar with the
 * Pratidhvani lockup on the left, marketing nav in the middle, and
 * auth CTAs on the right.
 *
 * Auth-state aware: shows "Sign in" / "Get started free" when logged
 * out, "Open app" + user email when logged in.
 */
export function MarketingLayout() {
  const c = useColors();
  return (
    <div
      style={{
        minHeight: '100vh',
        background: c.bg,
        color: c.textPrimary,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <MarketingHeader />
      <main style={{ flex: 1 }}>
        <Outlet />
      </main>
      <MarketingFooter />
    </div>
  );
}

function MarketingHeader() {
  const c = useColors();
  const { isAuthenticated, user } = useAuth();
  const location = useLocation();

  return (
    <header
      style={{
        borderBottom: `1px solid ${c.border}`,
        background: c.surface,
        position: 'sticky',
        top: 0,
        zIndex: 100,
      }}
    >
      <div
        style={{
          maxWidth: 1200,
          margin: '0 auto',
          padding: `${space['4']} ${space['5']}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: space['5'],
        }}
      >
        <Link
          to="/landing"
          style={{ textDecoration: 'none', color: 'inherit', display: 'block' }}
          aria-label="Pratidhvani — home"
        >
          <span
            lang="hi"
            style={{
              display: 'block',
              fontFamily: fonts.devanagari,
              fontSize: fontSize.xl,
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
              fontSize: fontSize.xs,
              fontWeight: fontWeight.medium,
              color: c.textSecondary,
              letterSpacing: '0.18em',
              textTransform: 'uppercase',
              marginTop: 2,
            }}
          >
            Pratidhvani
          </span>
        </Link>

        <nav style={{ display: 'flex', gap: space['5'], alignItems: 'center' }} aria-label="Marketing">
          <MarketingNavLink to="/landing">How it works</MarketingNavLink>
          <MarketingNavLink to="/pricing">Pricing</MarketingNavLink>
          {isAuthenticated ? (
            <Link
              to="/submit"
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.semibold,
                color: c.bg,
                background: c.accent,
                padding: `${space['2']} ${space['4']}`,
                borderRadius: radius.md,
                textDecoration: 'none',
              }}
              title={user?.email}
            >
              Open app →
            </Link>
          ) : (
            <>
              <Link
                to="/login"
                state={{ from: location }}
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  fontWeight: fontWeight.semibold,
                  color: c.textPrimary,
                  textDecoration: 'none',
                  padding: `${space['2']} ${space['3']}`,
                }}
              >
                Sign in
              </Link>
              <Link
                to="/register"
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  fontWeight: fontWeight.semibold,
                  color: c.bg,
                  background: c.accent,
                  padding: `${space['2']} ${space['4']}`,
                  borderRadius: radius.md,
                  textDecoration: 'none',
                }}
              >
                Get started free
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}

function MarketingNavLink({ to, children }: { to: string; children: ReactNode }) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  return (
    <NavLink
      to={to}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={({ isActive }) => {
        const s: CSSProperties = {
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          fontWeight: isActive ? fontWeight.semibold : fontWeight.medium,
          color: isActive || hovered ? c.accent : c.textSecondary,
          textDecoration: 'none',
          padding: `${space['2']} 0`,
          borderBottom: `2px solid ${isActive ? c.accent : 'transparent'}`,
          transition: `color ${motion.duration.fast}ms ${motion.easing.standard}`,
        };
        return s;
      }}
    >
      {children}
    </NavLink>
  );
}

function MarketingFooter() {
  const c = useColors();
  return (
    <footer
      style={{
        borderTop: `1px solid ${c.border}`,
        background: c.surface,
        padding: `${space['5']} ${space['5']}`,
        marginTop: space['10'],
      }}
    >
      <div
        style={{
          maxWidth: 1200,
          margin: '0 auto',
          display: 'flex',
          flexWrap: 'wrap',
          justifyContent: 'space-between',
          gap: space['4'],
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.textMuted,
        }}
      >
        <div>© Pratidhvani — your sources, echoed back.</div>
        <div style={{ display: 'flex', gap: space['4'] }}>
          <a
            href="https://github.com/khoks/VideoResearchPro"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: c.textMuted, textDecoration: 'none' }}
          >
            GitHub
          </a>
          <Link to="/pricing" style={{ color: c.textMuted, textDecoration: 'none' }}>
            Pricing
          </Link>
        </div>
      </div>
    </footer>
  );
}
