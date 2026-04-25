import type { ReactNode } from 'react';
import { useColors, useShadows } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

export interface AuthShellProps {
  /** Short caption under the brand lockup (e.g. "Sign in to your library."). */
  title: ReactNode;
  /** Optional tagline shown above the title. Defaults to "Your sources, echoed back." */
  tagline?: ReactNode;
  children: ReactNode;
}

/**
 * Shared warm-editorial wrapper for Login / Register.
 *
 * Lockup: Devanagari `प्रतिध्वनि` as the primary display, Latin
 * `Pratidhvani` underneath. Followed by a tagline and the caller's
 * form content inside a paper-toned card.
 */
export function AuthShell({ title, tagline = 'Your sources, echoed back.', children }: AuthShellProps) {
  const c = useColors();
  const s = useShadows();

  return (
    <div
      style={{
        minHeight: '100vh',
        background: c.bg,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: space['5'],
      }}
    >
      <div
        style={{
          background: c.surface,
          color: c.textPrimary,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          boxShadow: s.floating,
          padding: `${space['7']} ${space['6']}`,
          width: '100%',
          maxWidth: 440,
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: space['6'] }}>
          <h1
            lang="hi"
            style={{
              fontFamily: fonts.devanagari,
              fontSize: fontSize['3xl'],
              fontWeight: fontWeight.semibold,
              color: c.accent,
              margin: 0,
              lineHeight: lineHeight.tight,
              letterSpacing: '0.01em',
            }}
          >
            प्रतिध्वनि
          </h1>
          <p
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.medium,
              color: c.textSecondary,
              margin: `${space['1']} 0 0`,
              letterSpacing: '0.2em',
              textTransform: 'uppercase',
            }}
          >
            Pratidhvani
          </p>
          <p
            style={{
              fontFamily: fonts.body,
              fontStyle: 'italic',
              fontSize: fontSize.sm,
              color: c.textMuted,
              margin: `${space['3']} 0 0`,
            }}
          >
            {tagline}
          </p>
        </div>

        <h2
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: `0 0 ${space['5']}`,
            textAlign: 'center',
          }}
        >
          {title}
        </h2>

        {children}
      </div>
    </div>
  );
}

export interface AuthErrorProps {
  message: ReactNode;
}

/** Surface-styled error strip used inside an auth form. */
export function AuthError({ message }: AuthErrorProps) {
  const c = useColors();
  return (
    <p
      role="alert"
      style={{
        margin: 0,
        padding: `${space['2']} ${space['3']}`,
        background: c.errorSubtle,
        color: c.error,
        border: `1px solid ${c.error}`,
        borderRadius: radius.sm,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
      }}
    >
      {message}
    </p>
  );
}
