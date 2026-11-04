import { Link } from 'react-router-dom';
import { Card } from '../components/primitives';
import { SessionsCard } from '../components/security/SessionsCard';
import { TwoStepCard } from '../components/security/TwoStepCard';
import { ActivityCard } from '../components/security/ActivityCard';
import { SectionTitle } from '../components/security/SectionTitle';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../theme';

/**
 * `/account/security`: E-5.4's backend made visible. Where the account is
 * signed in (T-5.4.7), two-step verification (T-5.4.6), the password reset
 * (T-5.4.3) and recent account activity (T-5.4.4).
 */
export function AccountSecurityPage() {
  const c = useColors();
  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal };
  return (
    <div style={{ maxWidth: 880, margin: '0 auto' }}>
      <header style={{ marginBottom: space['6'] }}>
        <h1 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          Security
        </h1>
        <p style={{ ...text, marginTop: space['2'], fontSize: fontSize.md, maxWidth: '75ch' }}>
          Where your account is signed in, how you sign in, and what has happened on the account lately.
        </p>
      </header>
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['5'] }}>
        <SessionsCard />
        <TwoStepCard />
        <Card>
          <SectionTitle>Password</SectionTitle>
          <p style={text}>
            To set a new password, request a reset code: it goes to your email, or on a self-hosted install without email set up,
            to the server log.{' '}
            <Link to="/forgot-password" style={{ color: c.accent, fontWeight: fontWeight.semibold, textDecoration: 'none' }}>
              Reset your password
            </Link>
          </p>
        </Card>
        <ActivityCard />
      </div>
    </div>
  );
}
