/**
 * <ApprovalCard>
 *
 * The polymorphic candidate-approval card per D-016 / D-018. ONE
 * component handles every source_type (video / reddit_post / hn_story /
 * future Mastodon / Bluesky / etc.); per-source variation lives in
 * config entries in the registry, not in component code.
 *
 * Composition (left-to-right, top-to-bottom):
 *
 *     ┌──────────────────────────────────────────────────────┐
 *     │ <CardHeader>      │ <CardActions> (checkbox + link)  │
 *     │ glyph + Document.title + Document.published_at       │
 *     ├──────────────────────────────────────────────────────┤
 *     │ <CardBody>                                            │
 *     │  excerpt (config.body.excerptField from metadata)     │
 *     ├──────────────────────────────────────────────────────┤
 *     │ <CardMetaRow>                                         │
 *     │  config.metaChips (icon + value, formatted)           │
 *     ├──────────────────────────────────────────────────────┤
 *     │ <CardBadgeRow>                                        │
 *     │  <ClassificationBadgeRow> (D-014 stance/sent/framing) │
 *     └──────────────────────────────────────────────────────┘
 *
 * customSlot escape hatch: if a source_type's config provides one,
 * the card defers all rendering to it; default-path rendering is
 * skipped. This is the D-016 "rare source-type-specific UI" route
 * (e.g. a future podcast card that wants an inline audio scrubber).
 *
 * Field resolution rules:
 *   - <CardHeader> reads document.title + document.published_at +
 *     config.glyph.
 *   - <CardActions> reads document.source_url + selected/onSelectionChange
 *     props.
 *   - <CardBody> reads metadata[config.body.excerptField] when
 *     config.body is set; renders nothing otherwise.
 *   - <CardMetaRow> renders one chip per config.metaChips entry. Each
 *     chip's `field` is type-checked at compile time as keyof T (the
 *     source's metadata shape).
 *   - <CardBadgeRow> renders <ClassificationBadgeRow> when classification
 *     is provided; renders nothing otherwise.
 *
 * Formatting precedence (D-018(c) hybrid):
 *   1. chip.format(value)        — per-chip callback (highest precedence)
 *   2. FORMATTERS[chip.formatter] — registry by name
 *   3. String(value)             — default
 */
import type { CSSProperties, ReactNode } from 'react';
import { Card } from '../primitives/Card';
import { useColors } from '../../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  radius,
  space,
} from '../../theme';
import { ClassificationBadgeRow } from './ClassificationBadgeRow';
import type {
  ApprovalCardConfig,
  ApprovalDocument,
  Classification,
  FormatterName,
  MetaChip,
  SourceMetadata,
} from './types';

// ---------------------------------------------------------------------------
// Formatter registry — D-018(c) hybrid resolution
// ---------------------------------------------------------------------------

/**
 * Named formatters keyed by FormatterName. Each takes the raw value
 * out of source_metadata and returns a display string.
 *
 * Adding a new formatter = adding an entry here + an entry in the
 * FormatterName Literal in types.ts. TypeScript will refuse to
 * compile until both exist.
 */
const FORMATTERS: Record<FormatterName, (v: unknown) => string> = {
  durationSeconds: (v) => {
    const n = Number(v);
    if (!isFinite(n) || n < 0) return String(v);
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    const s = Math.floor(n % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
  },
  relativeTime: (v) => {
    // Accept ISO string or epoch ms.
    const ms = typeof v === 'number' ? v : Date.parse(String(v));
    if (!isFinite(ms)) return String(v);
    const elapsed = (Date.now() - ms) / 1000;
    if (elapsed < 60) return `${Math.floor(elapsed)}s ago`;
    if (elapsed < 3600) return `${Math.floor(elapsed / 60)}m ago`;
    if (elapsed < 86400) return `${Math.floor(elapsed / 3600)}h ago`;
    if (elapsed < 86400 * 30) return `${Math.floor(elapsed / 86400)}d ago`;
    if (elapsed < 86400 * 365) return `${Math.floor(elapsed / (86400 * 30))}mo ago`;
    return `${Math.floor(elapsed / (86400 * 365))}y ago`;
  },
  signedNumber: (v) => {
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    return n > 0 ? `+${n}` : `${n}`;
  },
  numberWithCommas: (v) => {
    const n = Number(v);
    if (!isFinite(n)) return String(v);
    return n.toLocaleString('en-US');
  },
  truncate: (v) => {
    const s = String(v);
    return s.length > 80 ? s.slice(0, 77) + '…' : s;
  },
};

function formatChipValue<T extends SourceMetadata>(
  chip: MetaChip<T>,
  value: unknown,
): string {
  if (chip.format) {
    return chip.format(value as never);
  }
  if (chip.formatter && FORMATTERS[chip.formatter]) {
    return FORMATTERS[chip.formatter](value);
  }
  return String(value ?? '');
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface CardHeaderProps {
  glyph: ReactNode;
  title: string;
  publishedAt: string | null;
}

function CardHeader({ glyph, title, publishedAt }: CardHeaderProps) {
  const c = useColors();
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: space['3'],
        flex: 1,
        minWidth: 0,
      }}
    >
      <div
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: 24,
          height: 24,
          flexShrink: 0,
          color: c.textSecondary,
        }}
        aria-hidden
      >
        {glyph}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <h3
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize.md,
            fontWeight: fontWeight.semibold,
            lineHeight: lineHeight.snug,
            color: c.textPrimary,
            wordBreak: 'break-word',
          }}
        >
          {title}
        </h3>
        {publishedAt && (
          <div
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              color: c.textMuted,
              marginTop: 2,
            }}
          >
            {new Date(publishedAt).toLocaleDateString()}
          </div>
        )}
      </div>
    </div>
  );
}

interface CardActionsProps {
  sourceUrl: string;
  selected: boolean;
  onSelectionChange: (next: boolean) => void;
}

function CardActions({ sourceUrl, selected, onSelectionChange }: CardActionsProps) {
  const c = useColors();
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-end',
        gap: space['2'],
        flexShrink: 0,
      }}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={(e) => onSelectionChange(e.target.checked)}
        aria-label="Approve this candidate"
        style={{
          width: 18,
          height: 18,
          accentColor: c.accent,
          cursor: 'pointer',
        }}
      />
      <a
        href={sourceUrl}
        target="_blank"
        rel="noopener noreferrer"
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.textSecondary,
          textDecoration: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        View ↗
      </a>
    </div>
  );
}

interface CardBodyProps {
  excerpt: string | null;
}

function CardBody({ excerpt }: CardBodyProps) {
  const c = useColors();
  if (!excerpt) return null;
  return (
    <div
      style={{
        fontFamily: fonts.body,
        fontSize: fontSize.sm,
        color: c.textSecondary,
        lineHeight: lineHeight.normal,
        marginTop: space['2'],
      }}
    >
      {excerpt}
    </div>
  );
}

interface CardMetaRowProps<T extends SourceMetadata> {
  metadata: T;
  chips: MetaChip<T>[];
}

function CardMetaRow<T extends SourceMetadata>({
  metadata,
  chips,
}: CardMetaRowProps<T>) {
  const c = useColors();
  if (chips.length === 0) return null;
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: space['3'],
        alignItems: 'center',
        marginTop: space['2'],
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        color: c.textSecondary,
      }}
    >
      {chips.map((chip, i) => {
        const rawValue = (metadata as Record<string, unknown>)[
          chip.field as string
        ];
        const display = formatChipValue(chip, rawValue);
        return (
          <span
            key={i}
            title={chip.label}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 4,
              background: c.surfaceAlt,
              padding: `2px ${space['2']}`,
              borderRadius: radius.sm,
              border: `1px solid ${c.border}`,
            }}
          >
            <span aria-hidden style={{ display: 'inline-flex' }}>
              {chip.icon}
            </span>
            <span>{display}</span>
          </span>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Public <ApprovalCard>
// ---------------------------------------------------------------------------

export interface ApprovalCardProps<T extends SourceMetadata = SourceMetadata> {
  document: ApprovalDocument;
  metadata: T;
  classification?: Classification;
  config: ApprovalCardConfig<T>;
  selected: boolean;
  onSelectionChange: (next: boolean) => void;
  /** Visible only when filter chips have toggled "Show low-relevance candidates"; per D-021. */
  showLowRelevance?: boolean;
  style?: CSSProperties;
}

export function ApprovalCard<T extends SourceMetadata>({
  document,
  metadata,
  classification,
  config,
  selected,
  onSelectionChange,
  showLowRelevance = true,
  style,
}: ApprovalCardProps<T>) {
  // D-016 escape hatch: source-type-specific UI defers to customSlot
  // entirely when present; the default composition is skipped.
  if (config.customSlot) {
    return (
      <Card style={style}>
        {config.customSlot({ metadata, document, classification })}
      </Card>
    );
  }

  const excerpt =
    config.body && config.body.excerptField
      ? String(
          (metadata as Record<string, unknown>)[
            config.body.excerptField as string
          ] ?? '',
        )
      : null;

  return (
    <Card style={style}>
      <div
        style={{
          display: 'flex',
          gap: space['3'],
          alignItems: 'flex-start',
        }}
      >
        <CardHeader
          glyph={config.glyph}
          title={document.title}
          publishedAt={document.published_at}
        />
        <CardActions
          sourceUrl={document.source_url}
          selected={selected}
          onSelectionChange={onSelectionChange}
        />
      </div>
      <CardBody excerpt={excerpt} />
      <CardMetaRow metadata={metadata} chips={config.metaChips} />
      {classification && (
        <div style={{ marginTop: space['2'] }}>
          <ClassificationBadgeRow
            classification={classification}
            showLowRelevance={showLowRelevance}
          />
        </div>
      )}
    </Card>
  );
}

// Export pure helper for tests that want to verify formatter behavior
// without rendering React.
export { FORMATTERS, formatChipValue };
