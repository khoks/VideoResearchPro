/**
 * One library Q&A exchange (question, Markdown answer, citations, notes),
 * shared by the library Q&A page and the shelf page's Q&A panel (S-8.1.4).
 * A scoped exchange says what it was asked over, so a shelf answer never
 * reads as a library-wide one in the library history (M1 plan risk).
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { CitationLink } from '../citation';
import { NotesPanel } from '../notes';
import { Badge, Button, Spinner } from '../primitives';
import { useShelves } from '../../hooks/useShelves';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import type { LibraryQAExchange, QAScope } from '../../types/qa';

export function InfoStripe({ text }: { text: string }) {
  const c = useColors();
  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: space['3'],
        marginBottom: space['3'],
        padding: space['3'],
        background: c.accentSubtle,
        borderRadius: radius.md,
      }}
    >
      <Spinner size={16} />
      <span
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.sm,
          color: c.accent,
          fontWeight: fontWeight.medium,
        }}
      >
        {text}
      </span>
    </div>
  );
}

/** "Asked on shelf Rates", "From a saved search": what a scoped exchange was asked over. */
export function ScopeNote({ scope }: { scope: QAScope | null | undefined }) {
  const c = useColors();
  const shelves = useShelves();
  if (!scope || (!scope.shelf_id && !scope.saved_search_id)) return null;
  const shelf = scope.shelf_id ? shelves.data?.find((s) => s.id === scope.shelf_id) : undefined;
  const style = { margin: `0 0 ${space['2']}`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary };
  return (
    <p style={style} data-qa-scope="">
      {scope.shelf_id &&
        (shelf ? (
          <>
            Asked on shelf{' '}
            <Link to={`/shelves/${shelf.id}`} style={{ color: c.accent }}>
              {shelf.name}
            </Link>
          </>
        ) : shelves.isLoading ? (
          'Asked on a shelf'
        ) : (
          'Asked on a shelf that no longer exists'
        ))}
      {scope.shelf_id && scope.saved_search_id ? ' · ' : ''}
      {scope.saved_search_id && 'From a saved search'}
    </p>
  );
}

export function LibraryQAExchangeCard({ qa, showScope = true }: { qa: LibraryQAExchange; showScope?: boolean }) {
  const c = useColors();
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(qa.answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (e.g. insecure context) — leave button state unchanged
    }
  };

  return (
    <div
      id={`exchange-${qa.id}`}
      style={{
        padding: space['4'],
        background: c.surfaceAlt,
        borderRadius: radius.md,
        border: `1px solid ${c.border}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['3'],
          marginBottom: space['3'],
        }}
      >
        <div style={{ flex: 1, minWidth: 0 }}>
          {showScope && <ScopeNote scope={qa.scope} />}
          <p
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.md,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              lineHeight: lineHeight.snug,
            }}
          >
            {qa.question}
          </p>
        </div>
        <Button size="sm" variant="tertiary" onClick={handleCopy}>
          {copied ? (
            <Badge tone="success" size="sm">
              Copied
            </Badge>
          ) : (
            'Copy answer'
          )}
        </Button>
      </div>
      <div
        className="reading"
        style={{
          color: c.textPrimary,
          fontFamily: fonts.body,
          fontSize: fontSize.base,
          lineHeight: lineHeight.loose,
        }}
      >
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div
          style={{
            marginTop: space['3'],
            borderTop: `1px solid ${c.border}`,
            paddingTop: space['3'],
          }}
        >
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            References
          </span>
          <div style={{ marginTop: space['2'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            {qa.references.map((ref, i) => (
              <CitationLink key={i} reference={ref} style={{ fontSize: fontSize.sm }} />
            ))}
          </div>
        </div>
      )}
      <NotesPanel targetType="library_qa_exchange" targetId={qa.id} />
    </div>
  );
}
