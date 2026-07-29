import { useMemo } from 'react';
import { useColors } from '../hooks/useTheme';
import {
  useLLMSettings,
  useLLMEstimate,
  useSetLLMOverride,
  useResetLLMOverride,
  type EstimateRow,
  type LLMConfig,
  type LLMModelInfo,
  type LLMUseCase,
} from '../hooks/useLLMSettings';
import { Badge, Button, Card, EmptyState, Select, Skeleton, Spinner } from '../components/primitives';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../theme';

/**
 * AI models — per-user LLM routing overrides.
 *
 * Every LLM call site is a named use case with a tuned default
 * (provider, model, reasoning). This panel lets the user override any of
 * them for their own account only. Saves are immediate (optimistic PUT per
 * select change); a sticky cost panel re-estimates the benchmark job after
 * each save (debounced in the hook).
 */
export function AIModelsPage() {
  const c = useColors();
  const settings = useLLMSettings();
  const estimate = useLLMEstimate();
  const setOverride = useSetLLMOverride();
  const resetOverride = useResetLLMOverride();

  const useCases = settings.data?.use_cases ?? [];
  const providers = settings.data?.providers ?? {};
  const reasoningLevels = settings.data?.reasoning_levels ?? [];

  // Group use cases by their `group` field, preserving first-appearance order.
  const groups = useMemo(() => {
    const map = new Map<string, LLMUseCase[]>();
    for (const uc of useCases) {
      const key = uc.group || 'Other';
      const list = map.get(key);
      if (list) list.push(uc);
      else map.set(key, [uc]);
    }
    return [...map.entries()];
  }, [useCases]);

  const header = (
    <header style={{ marginBottom: space['6'] }}>
      <h1
        style={{
          margin: 0,
          fontFamily: fonts.display,
          fontSize: fontSize['2xl'],
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
        }}
      >
        AI models
      </h1>
      <p
        style={{
          margin: `${space['2']} 0 0`,
          fontFamily: fonts.body,
          fontSize: fontSize.md,
          color: c.textSecondary,
          lineHeight: lineHeight.normal,
          maxWidth: '75ch',
        }}
      >
        Defaults are tuned per function; overrides apply only to you and take effect
        immediately. Reset any row to return to the tuned default.
      </p>
    </header>
  );

  if (settings.isLoading) {
    return (
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        {header}
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
          <Skeleton variant="card" height={160} />
          <Skeleton variant="card" height={160} />
          <Skeleton variant="card" height={160} />
        </div>
      </div>
    );
  }

  if (settings.isError || useCases.length === 0) {
    return (
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        {header}
        <EmptyState
          title="Model settings unavailable"
          description={
            settings.isError
              ? 'We could not reach the settings service. Your saved overrides are untouched — try again in a moment.'
              : 'No configurable model use cases were returned. Once the backend registry is reachable, every LLM function will be listed here.'
          }
          action={
            <Button variant="secondary" onClick={() => void settings.refetch()}>
              Try again
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      {header}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: space['5'],
          alignItems: 'flex-start',
        }}
      >
        {/* Use-case sections */}
        <div
          style={{
            flex: '1 1 560px',
            minWidth: 0,
            display: 'flex',
            flexDirection: 'column',
            gap: space['5'],
            alignSelf: 'flex-start',
          }}
        >
          {groups.map(([group, items]) => (
            <GroupSection
              key={group}
              group={group}
              items={items}
              providers={providers}
              reasoningLevels={reasoningLevels}
              onSave={(useCase, config) => setOverride.mutate({ useCase, config })}
              onReset={(useCase) => resetOverride.mutate({ useCase })}
              resettingUseCase={resetOverride.isPending ? resetOverride.variables?.useCase : undefined}
            />
          ))}
        </div>

        {/* Sticky cost panel */}
        <div
          style={{
            flex: '0 1 380px',
            minWidth: 300,
            position: 'sticky',
            top: space['5'],
            alignSelf: 'flex-start',
          }}
        >
          <CostPanel
            estimate={estimate.data}
            isLoading={estimate.isLoading}
            isFetching={estimate.isFetching}
            isError={estimate.isError}
            onRetry={() => void estimate.refetch()}
          />
        </div>
      </div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────
// Group section

interface GroupSectionProps {
  group: string;
  items: LLMUseCase[];
  providers: Record<string, { models: LLMModelInfo[] }>;
  reasoningLevels: string[];
  onSave: (useCase: string, config: LLMConfig) => void;
  onReset: (useCase: string) => void;
  resettingUseCase?: string;
}

function GroupSection({
  group,
  items,
  providers,
  reasoningLevels,
  onSave,
  onReset,
  resettingUseCase,
}: GroupSectionProps) {
  const c = useColors();
  return (
    <Card flush>
      <h2
        style={{
          margin: 0,
          padding: `${space['4']} ${space['5']} ${space['3']}`,
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          borderBottom: `1px solid ${c.border}`,
        }}
      >
        {group}
      </h2>
      {items.map((uc, i) => (
        <UseCaseRow
          key={uc.use_case}
          uc={uc}
          providers={providers}
          reasoningLevels={reasoningLevels}
          onSave={(config) => onSave(uc.use_case, config)}
          onReset={() => onReset(uc.use_case)}
          resetting={resettingUseCase === uc.use_case}
          isLast={i === items.length - 1}
        />
      ))}
    </Card>
  );
}

// ──────────────────────────────────────────────────────────────
// Use-case row

interface UseCaseRowProps {
  uc: LLMUseCase;
  providers: Record<string, { models: LLMModelInfo[] }>;
  reasoningLevels: string[];
  onSave: (config: LLMConfig) => void;
  onReset: () => void;
  resetting: boolean;
  isLast: boolean;
}

function UseCaseRow({ uc, providers, reasoningLevels, onSave, onReset, resetting, isLast }: UseCaseRowProps) {
  const c = useColors();
  const effective = uc.effective;
  const providerNames = Object.keys(providers);
  const models = providers[effective.provider]?.models ?? [];

  const handleProviderChange = (provider: string) => {
    const nextModels = providers[provider]?.models ?? [];
    // Keep the model if the new provider serves it too; otherwise take its first.
    const model = nextModels.some((m) => m.id === effective.model)
      ? effective.model
      : nextModels[0]?.id ?? effective.model;
    onSave({ provider, model, reasoning: effective.reasoning });
  };

  const handleModelChange = (model: string) => {
    onSave({ provider: effective.provider, model, reasoning: effective.reasoning });
  };

  const handleReasoningChange = (reasoning: string) => {
    onSave({ provider: effective.provider, model: effective.model, reasoning });
  };

  return (
    <div
      style={{
        padding: `${space['4']} ${space['5']}`,
        borderBottom: isLast ? 'none' : `1px solid ${c.border}`,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      {/* Line 1 — name + overridden badge + reset */}
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], minWidth: 0 }}>
        <span
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.base,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            whiteSpace: 'nowrap',
          }}
        >
          {prettifyUseCase(uc.use_case)}
        </span>
        {uc.override !== null && (
          <Badge tone="accent" size="sm">
            Overridden
          </Badge>
        )}
        <span style={{ flex: 1 }} />
        {uc.override !== null && (
          <Button variant="tertiary" size="sm" loading={resetting} onClick={onReset}>
            Reset
          </Button>
        )}
      </div>

      {/* Line 2 — summary, single line, tooltip carries the full text */}
      {uc.summary && (
        <p
          title={uc.summary}
          style={{
            margin: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textMuted,
            lineHeight: lineHeight.snug,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {uc.summary}
        </p>
      )}

      {/* Line 3 — provider → model → reasoning */}
      <div style={{ display: 'flex', gap: space['3'], flexWrap: 'wrap', marginTop: space['1'] }}>
        <LabeledSelect
          label="Provider"
          value={effective.provider}
          onChange={handleProviderChange}
          flex="0 1 150px"
        >
          {!providerNames.includes(effective.provider) && (
            <option value={effective.provider}>{effective.provider}</option>
          )}
          {providerNames.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </LabeledSelect>
        <LabeledSelect
          label="Model"
          value={effective.model}
          onChange={handleModelChange}
          flex="1 1 220px"
        >
          {!models.some((m) => m.id === effective.model) && (
            <option value={effective.model}>{effective.model}</option>
          )}
          {models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.id} (window: {formatCompact(m.context_window)})
            </option>
          ))}
        </LabeledSelect>
        <LabeledSelect
          label="Reasoning"
          value={effective.reasoning}
          onChange={handleReasoningChange}
          flex="0 1 130px"
        >
          {!reasoningLevels.includes(effective.reasoning) && (
            <option value={effective.reasoning}>{effective.reasoning}</option>
          )}
          {reasoningLevels.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </LabeledSelect>
      </div>
    </div>
  );
}

function LabeledSelect({
  label,
  value,
  onChange,
  flex,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  flex: string;
  children: React.ReactNode;
}) {
  const c = useColors();
  return (
    <label style={{ flex, minWidth: 120, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <span
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.medium,
          color: c.textMuted,
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
        }}
      >
        {label}
      </span>
      <Select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ fontSize: fontSize.sm, padding: `${space['1']} ${space['2']}` }}
      >
        {children}
      </Select>
    </label>
  );
}

// ──────────────────────────────────────────────────────────────
// Cost panel

interface CostPanelProps {
  estimate: ReturnType<typeof useLLMEstimate>['data'];
  isLoading: boolean;
  isFetching: boolean;
  isError: boolean;
  onRetry: () => void;
}

function CostPanel({ estimate, isLoading, isFetching, isError, onRetry }: CostPanelProps) {
  const c = useColors();

  const rows = useMemo(() => {
    const list = [...(estimate?.per_use_case ?? [])];
    // Priced rows sorted desc by cost; unknown-pricing rows sink to the bottom.
    list.sort((a, b) => {
      if (a.pricing_known !== b.pricing_known) return a.pricing_known ? -1 : 1;
      return b.cost_usd - a.cost_usd;
    });
    return list;
  }, [estimate]);

  const unknownModels = estimate?.totals.unknown_pricing_models ?? [];

  return (
    <Card style={{ padding: space['5'] }}>
      <p
        style={{
          margin: 0,
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          color: c.textMuted,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
        }}
      >
        Cost preview
      </p>
      <h2
        style={{
          margin: `${space['2']} 0 0`,
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          lineHeight: lineHeight.tight,
        }}
      >
        Estimated cost of a job like your 200-video AI research run
      </h2>

      {isLoading && (
        <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], marginTop: space['4'] }}>
          <Spinner size={18} />
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
            Computing estimate…
          </span>
        </div>
      )}

      {isError && !isLoading && (
        <div style={{ marginTop: space['4'] }}>
          <p
            style={{
              margin: `0 0 ${space['3']}`,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textMuted,
              lineHeight: lineHeight.normal,
            }}
          >
            The estimate service is unreachable right now. Model changes still save —
            only this preview is affected.
          </p>
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Retry estimate
          </Button>
        </div>
      )}

      {estimate && !isError && (
        <>
          {estimate.benchmark && (
            <p
              style={{
                margin: `${space['2']} 0 0`,
                fontFamily: fonts.ui,
                fontSize: fontSize.xs,
                color: c.textMuted,
                lineHeight: lineHeight.snug,
              }}
            >
              Benchmark: {estimate.benchmark.label} — {estimate.benchmark.videos} videos,{' '}
              {formatCompact(estimate.benchmark.transcript_words)} transcript words,{' '}
              {estimate.benchmark.questions_assumed} questions,{' '}
              {estimate.benchmark.knowledge_videos_assumed} knowledge reports.
            </p>
          )}

          {/* Total */}
          <div
            style={{
              marginTop: space['4'],
              display: 'flex',
              alignItems: 'baseline',
              gap: space['3'],
            }}
          >
            <span
              style={{
                fontFamily: fonts.display,
                fontSize: fontSize['3xl'],
                fontWeight: fontWeight.bold,
                color: c.accent,
                lineHeight: lineHeight.tight,
              }}
            >
              {formatUsd(estimate.totals.cost_usd)}
            </span>
            {isFetching && <Spinner size={14} label="Recomputing estimate" />}
          </div>

          {unknownModels.length > 0 && (
            <div style={{ marginTop: space['3'] }}>
              <Badge tone="warn" size="sm">
                pricing unknown
              </Badge>
              <p
                style={{
                  margin: `${space['1']} 0 0`,
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                  color: c.textMuted,
                  lineHeight: lineHeight.snug,
                }}
              >
                Excluded from the total (no known pricing): {unknownModels.join(', ')}
              </p>
            </div>
          )}

          {/* Breakdown table */}
          {rows.length > 0 && (
            <div style={{ marginTop: space['4'], overflowX: 'auto' }}>
              <table
                style={{
                  width: '100%',
                  borderCollapse: 'collapse',
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                }}
              >
                <thead>
                  <tr>
                    <Th align="left">Use case</Th>
                    <Th align="left">Model</Th>
                    <Th align="right">Calls</Th>
                    <Th align="right">In / out</Th>
                    <Th align="right">Cost</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <BreakdownRow key={row.use_case} row={row} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function Th({ align, children }: { align: 'left' | 'right'; children: React.ReactNode }) {
  const c = useColors();
  return (
    <th
      style={{
        textAlign: align,
        padding: `${space['1']} ${space['2']}`,
        borderBottom: `1px solid ${c.borderStrong}`,
        color: c.textMuted,
        fontWeight: fontWeight.semibold,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </th>
  );
}

function BreakdownRow({ row }: { row: EstimateRow }) {
  const c = useColors();
  const cell: React.CSSProperties = {
    padding: `${space['1']} ${space['2']}`,
    borderBottom: `1px solid ${c.border}`,
    color: c.textSecondary,
    verticalAlign: 'top',
  };
  return (
    <tr>
      <td style={{ ...cell, color: c.textPrimary }} title={row.use_case}>
        {prettifyUseCase(row.use_case)}
      </td>
      <td style={{ ...cell, fontFamily: fonts.mono, whiteSpace: 'nowrap' }} title={row.model}>
        {row.model}
      </td>
      <td style={{ ...cell, textAlign: 'right', whiteSpace: 'nowrap' }}>{row.calls}</td>
      <td style={{ ...cell, textAlign: 'right', whiteSpace: 'nowrap' }}>
        {formatCompact(row.input_tokens)} / {formatCompact(row.output_tokens)}
      </td>
      <td style={{ ...cell, textAlign: 'right', whiteSpace: 'nowrap' }}>
        {row.pricing_known ? (
          formatUsd(row.cost_usd)
        ) : (
          <Badge tone="warn" size="sm">
            pricing unknown
          </Badge>
        )}
      </td>
    </tr>
  );
}

// ──────────────────────────────────────────────────────────────
// Formatting helpers

const ACRONYMS: Record<string, string> = {
  qa: 'Q&A',
  llm: 'LLM',
  html: 'HTML',
  rag: 'RAG',
};

/** `library_qa_refine_context` → `Library Q&A refine context`. */
function prettifyUseCase(useCase: string): string {
  const words = useCase.split('_').map((w) => ACRONYMS[w] ?? w);
  const first = words[0] ?? '';
  // Capitalizing an acronym is a no-op, so this is safe for both cases.
  const capitalized = first.charAt(0).toUpperCase() + first.slice(1);
  return [capitalized, ...words.slice(1)].join(' ');
}

/** 272000 → "272K", 1340000 → "1.34M", 950 → "950". */
function formatCompact(n: number): string {
  if (!Number.isFinite(n)) return '—';
  if (n >= 1_000_000) {
    const m = n / 1_000_000;
    return `${(Math.round(m * 100) / 100).toString().replace(/\.0+$/, '')}M`;
  }
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return `${n}`;
}

function formatUsd(v: number): string {
  if (!Number.isFinite(v)) return '—';
  if (v > 0 && v < 0.01) return '<$0.01';
  return `$${v.toFixed(2)}`;
}
