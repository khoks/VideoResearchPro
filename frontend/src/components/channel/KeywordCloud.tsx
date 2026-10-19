import { useColors } from '../../hooks/useTheme';
import { fonts, space } from '../../theme';

interface Keyword {
  term: string;
  weight: number;
  documents: number;
}

/**
 * The channel's keyword cloud as real text (M7 plan): inline words sized by
 * the square root of their weight, in reading order (alphabetical), so it
 * reflows, wraps at any width and reads as a list to assistive tech. Ink is
 * the text tokens, never a data colour; heavier words use the primary ink.
 */
export function KeywordCloud({ keywords }: { keywords: Keyword[] }) {
  const c = useColors();
  const ordered = [...keywords].sort((a, b) => a.term.localeCompare(b.term));
  return (
    <ul
      aria-label="Keywords, by how much the channel uses them"
      style={{
        listStyle: 'none',
        margin: 0,
        padding: 0,
        display: 'flex',
        flexWrap: 'wrap',
        alignItems: 'baseline',
        gap: `${space['1']} ${space['3']}`,
        lineHeight: 1.25,
      }}
    >
      {ordered.map((k) => {
        const scale = Math.sqrt(Math.max(0, Math.min(1, k.weight)));
        return (
          <li
            key={k.term}
            title={`${k.term}: in ${k.documents} ${k.documents === 1 ? 'document' : 'documents'}`}
            style={{
              fontFamily: fonts.display,
              fontSize: `${(0.8 + scale * 1.2).toFixed(2)}rem`,
              fontWeight: scale > 0.6 ? 600 : 400,
              color: scale > 0.45 ? c.textPrimary : c.textSecondary,
            }}
          >
            {k.term}
            <span style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
              {`, in ${k.documents} ${k.documents === 1 ? 'document' : 'documents'}`}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
