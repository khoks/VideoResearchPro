import { Link } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

/**
 * Public landing page — hero, value props, "how it works", CTAs.
 * Warm-editorial: serif typography, paper-toned background.
 */
export function LandingPage() {
  const c = useColors();

  return (
    <div style={{ background: c.bg, color: c.textPrimary }}>
      {/* Hero */}
      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['10']} ${space['5']} ${space['8']}`,
          textAlign: 'center',
        }}
      >
        <p
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
            letterSpacing: '0.18em',
            textTransform: 'uppercase',
            margin: 0,
          }}
        >
          A personal research wiki
        </p>
        <h1
          lang="hi"
          style={{
            margin: `${space['3']} 0 0`,
            fontFamily: fonts.devanagari,
            fontSize: fontSize['3xl'],
            color: c.accent,
            lineHeight: lineHeight.tight,
          }}
        >
          प्रतिध्वनि
        </h1>
        <h2
          style={{
            margin: `${space['1']} 0 0`,
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            color: c.textSecondary,
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            fontWeight: fontWeight.medium,
          }}
        >
          Pratidhvani
        </h2>
        <p
          style={{
            margin: `${space['5']} auto 0`,
            maxWidth: 720,
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.xl,
            color: c.textPrimary,
            lineHeight: lineHeight.normal,
          }}
        >
          Your sources, echoed back.
        </p>
        <p
          style={{
            margin: `${space['4']} auto 0`,
            maxWidth: 640,
            fontFamily: fonts.body,
            fontSize: fontSize.md,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          Curate the videos, podcasts, articles, and threads you actually trust. Ask
          citation-grounded questions. Generate books and reports from what you've collected.
          Pratidhvani is the opposite of Wikipedia — your library, your voices, your echo.
        </p>
        <div style={{ display: 'flex', gap: space['3'], justifyContent: 'center', marginTop: space['6'] }}>
          <Link
            to="/register"
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.base,
              fontWeight: fontWeight.semibold,
              color: c.bg,
              background: c.accent,
              padding: `${space['3']} ${space['5']}`,
              borderRadius: radius.md,
              textDecoration: 'none',
            }}
          >
            Get started free →
          </Link>
          <Link
            to="/pricing"
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.base,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              background: 'transparent',
              padding: `${space['3']} ${space['5']}`,
              borderRadius: radius.md,
              border: `1px solid ${c.border}`,
              textDecoration: 'none',
            }}
          >
            See pricing
          </Link>
        </div>
      </section>

      {/* Demo placeholder strip */}
      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['5']} ${space['5']}`,
        }}
      >
        <div
          style={{
            background: c.surface,
            border: `1px solid ${c.border}`,
            borderRadius: radius.lg,
            aspectRatio: '16 / 9',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: fonts.ui,
            color: c.textMuted,
            fontSize: fontSize.sm,
            fontStyle: 'italic',
          }}
          data-todo="record-demo-gif-hero"
        >
          Demo: Submit a job → approve videos → ask the library
        </div>
      </section>

      {/* How it works */}
      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['8']} ${space['5']}`,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            textAlign: 'center',
          }}
        >
          The shape of the system
        </h2>
        <p
          style={{
            maxWidth: 640,
            margin: `${space['3']} auto 0`,
            fontFamily: fonts.body,
            fontSize: fontSize.md,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
            textAlign: 'center',
          }}
        >
          Four steps. Every source type — videos today, podcasts and articles and PDFs and threads tomorrow —
          flows through the same agency surface.
        </p>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
            gap: space['5'],
            marginTop: space['6'],
          }}
        >
          {[
            {
              n: '1',
              title: 'Search',
              body: 'You give the system a topic or a channel. It finds candidate sources and surfaces them for your review.',
            },
            {
              n: '2',
              title: 'Curate',
              body: 'You approve what belongs in your library. The non-official voices you trust make the cut; the rest stay out.',
            },
            {
              n: '3',
              title: 'Ingest',
              body: 'Transcripts, embeddings, and knowledge artifacts are computed once per source and reused across every job.',
            },
            {
              n: '4',
              title: 'Echo',
              body: 'Ask questions across one job, your whole library, or every Q&A you have ever asked. Citations link back to the source.',
            },
          ].map((step) => (
            <div
              key={step.n}
              style={{
                background: c.surface,
                border: `1px solid ${c.border}`,
                borderRadius: radius.lg,
                padding: space['5'],
              }}
            >
              <div
                style={{
                  fontFamily: fonts.display,
                  fontSize: fontSize['2xl'],
                  fontWeight: fontWeight.semibold,
                  color: c.accent,
                  lineHeight: 1,
                }}
              >
                {step.n}
              </div>
              <h3
                style={{
                  margin: `${space['3']} 0 ${space['2']}`,
                  fontFamily: fonts.display,
                  fontSize: fontSize.lg,
                  fontWeight: fontWeight.semibold,
                  color: c.textPrimary,
                }}
              >
                {step.title}
              </h3>
              <p
                style={{
                  margin: 0,
                  fontFamily: fonts.body,
                  fontSize: fontSize.sm,
                  color: c.textSecondary,
                  lineHeight: lineHeight.normal,
                }}
              >
                {step.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Why it differs from Wikipedia */}
      <section
        style={{
          maxWidth: 1100,
          margin: '0 auto',
          padding: `${space['8']} ${space['5']}`,
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            textAlign: 'center',
          }}
        >
          Not a balanced encyclopedia. A personal wiki.
        </h2>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
            gap: space['5'],
            marginTop: space['6'],
            maxWidth: 880,
            marginLeft: 'auto',
            marginRight: 'auto',
          }}
        >
          <div
            style={{
              background: c.surfaceAlt,
              border: `1px solid ${c.border}`,
              borderRadius: radius.lg,
              padding: space['5'],
            }}
          >
            <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
              Wikipedia
            </h3>
            <ul style={{ marginTop: space['3'], paddingLeft: space['4'], fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
              <li>Moderated</li>
              <li>Balanced</li>
              <li>Diluted</li>
              <li>Official sources only</li>
            </ul>
          </div>
          <div
            style={{
              background: c.surface,
              border: `2px solid ${c.accent}`,
              borderRadius: radius.lg,
              padding: space['5'],
            }}
          >
            <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.accent }}>
              Pratidhvani
            </h3>
            <ul style={{ marginTop: space['3'], paddingLeft: space['4'], fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textPrimary, lineHeight: lineHeight.normal }}>
              <li>You curate</li>
              <li>You weight your sources</li>
              <li>Non-official voices welcome</li>
              <li>Citation-grounded answers</li>
            </ul>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section
        style={{
          maxWidth: 720,
          margin: '0 auto',
          padding: `${space['8']} ${space['5']} ${space['10']}`,
          textAlign: 'center',
        }}
      >
        <h2
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          Begin your first shelf.
        </h2>
        <p
          style={{
            margin: `${space['3']} auto 0`,
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.md,
            color: c.textSecondary,
          }}
        >
          Free forever for personal research libraries.
        </p>
        <div style={{ marginTop: space['5'] }}>
          <Link
            to="/register"
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.base,
              fontWeight: fontWeight.semibold,
              color: c.bg,
              background: c.accent,
              padding: `${space['3']} ${space['6']}`,
              borderRadius: radius.md,
              textDecoration: 'none',
            }}
          >
            Get started free →
          </Link>
        </div>
      </section>
    </div>
  );
}
