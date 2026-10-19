import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { useChannelIntelligence, useRefreshChannelIntelligence } from '../../hooks/useChannelIntelligence';
import type { ChannelIntelligence, LabelCount, MonthCounts } from '../../services/channelIntelligenceApi';
import { BarList, ColumnChart, type ColumnRow } from '../charts';
import { Button, Card, EmptyState, Skeleton } from '../primitives';
import { BatchExtract } from './BatchExtract';
import { ConceptMap } from './ConceptMap';
import { KeywordCloud } from './KeywordCloud';
import { useChartColors, useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { formatDate } from '../../utils/formatters';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

function monthLabel(key: string): string {
  const [y, m] = key.split('-');
  return `${MONTHS[Number(m) - 1] ?? m} ${y}`;
}

/** Label January of each year, thinned so labels never collide. */
function yearTicks(rows: ColumnRow[]) {
  const years = new Set(rows.map((r) => r.key.slice(0, 4)));
  const every = years.size > 16 ? 5 : years.size > 8 ? 2 : 1;
  return (row: ColumnRow, i: number) => {
    const isJan = row.key.endsWith('-01') || i === 0;
    const year = Number(row.key.slice(0, 4));
    return isJan && year % every === 0 ? String(year) : null;
  };
}

/**
 * The Intelligence tab of the channel page (S-8.7.3): what the channel says,
 * over the documents of it this reader can see. Panels whose inputs are
 * missing say why and what to do, instead of showing nothing.
 */
export function IntelligenceTab({ channelId }: { channelId: string }) {
  const c = useColors();
  const query = useChannelIntelligence(channelId);
  const refresh = useRefreshChannelIntelligence(channelId);
  const [refreshing, setRefreshing] = useState(false);

  if (query.isLoading) {
    return (
      <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <Skeleton variant="card" height={90} />
        <Skeleton variant="card" height={200} />
        <Skeleton variant="card" height={200} />
      </div>
    );
  }
  if (query.isError || !query.data) {
    return (
      <EmptyState
        size="sm"
        title="Couldn't read this channel."
        description="Something blocked the aggregate. Try again in a moment."
        action={
          <Button size="sm" variant="secondary" onClick={() => void query.refetch()}>
            Retry
          </Button>
        }
      />
    );
  }

  const data = query.data;
  if (data.coverage.documents === 0) {
    return (
      <EmptyState
        size="sm"
        title="Nothing to read yet."
        description={data.notes.documents ?? 'Sync the channel or pick its videos in a research run.'}
      />
    );
  }

  const onRefresh = async () => {
    setRefreshing(true);
    try {
      await refresh();
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: space['3'],
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: c.textMuted,
          flexWrap: 'wrap',
        }}
      >
        <span>
          Read {formatDate(data.computed_at)} over the {data.coverage.documents}{' '}
          {data.coverage.documents === 1 ? 'document' : 'documents'} of this channel on your shelf.
        </span>
        <Button size="sm" variant="tertiary" onClick={() => void onRefresh()} loading={refreshing}>
          Refresh
        </Button>
      </div>

      <CoveragePanel channelId={channelId} data={data} />

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['4'] }}>
        <Panel title="Publishing" grow={2}>
          <CadencePanel data={data} />
        </Panel>
        <Panel title="Length" grow={1}>
          <DurationPanel data={data} />
        </Panel>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['4'] }}>
        <Panel title="Topics" note={data.notes.topics}>
          <LabelPanel items={data.topics} emptyText="No topics yet." />
        </Panel>
        <Panel title="Concepts" note={data.topics.length ? undefined : data.notes.topics}>
          <LabelPanel items={data.concepts} emptyText="No concepts yet." />
        </Panel>
      </div>

      <Panel title="Words it keeps using" note={data.notes.keywords}>
        {data.keywords.length > 0 ? <KeywordCloud keywords={data.keywords} /> : null}
      </Panel>

      <Panel title="Concept map">
        <ConceptMap channelId={channelId} />
      </Panel>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['4'] }}>
        <Panel title="Your questions about it">
          <QAPanel data={data} />
        </Panel>
        <Panel title="Stance and sentiment" note={data.notes.stance}>
          {data.stance ? <StancePanel stance={data.stance} /> : null}
        </Panel>
      </div>
    </div>
  );
}

function Panel({ title, note, grow = 1, children }: { title: string; note?: string; grow?: number; children: ReactNode }) {
  const c = useColors();
  return (
    <Card style={{ flex: `${grow} 1 300px`, minWidth: 0 }}>
      <h3
        style={{
          margin: `0 0 ${space['3']}`,
          fontFamily: fonts.display,
          fontSize: fontSize.md,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
        }}
      >
        {title}
      </h3>
      {note && (
        <p style={{ margin: `0 0 ${space['3']}`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.snug }}>
          {note}
        </p>
      )}
      {children}
    </Card>
  );
}

function CoveragePanel({ channelId, data }: { channelId: string; data: ChannelIntelligence }) {
  const c = useColors();
  const cov = data.coverage;
  const pct = Math.round(cov.ratio * 100);
  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], flexWrap: 'wrap' }}>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xl, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          {pct}%
        </span>
        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
          of this channel's documents have a knowledge report ({cov.with_knowledge} of {cov.documents}). Topics and
          concepts are built from those.
        </span>
      </div>
      <div
        aria-hidden
        style={{ height: 6, marginTop: space['2'], background: c.surfaceAlt, borderRadius: radius.pill, overflow: 'hidden' }}
      >
        <div style={{ height: '100%', width: `${pct}%`, background: c.accent }} />
      </div>
      {cov.without_knowledge > cov.extractable.length && (
        <p style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
          {cov.without_knowledge - cov.extractable.length} of the rest have no transcript yet, so there is nothing to
          extract from.
        </p>
      )}
      <BatchExtract channelId={channelId} extractable={cov.extractable} />
    </Card>
  );
}

function CadencePanel({ data }: { data: ChannelIntelligence }) {
  const chart = useChartColors();
  const c = useColors();
  if (data.cadence.months.length === 0) {
    return <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>No publish dates on your documents of this channel.</p>;
  }
  const rows: ColumnRow[] = data.cadence.months.map((m) => ({ key: m.month, label: monthLabel(m.month), values: { count: m.count } }));
  const total = rows.reduce((s, r) => s + r.values.count, 0);
  return (
    <>
      <p style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        Documents per month, by publish date ({total} dated
        {data.cadence.undated ? `, ${data.cadence.undated} undated` : ''}).
      </p>
      <ColumnChart
        title="Documents published per month"
        rows={rows}
        series={[{ key: 'count', label: 'Documents', color: chart.series }]}
        unit="documents"
        xLabel={yearTicks(rows)}
      />
    </>
  );
}

function DurationPanel({ data }: { data: ChannelIntelligence }) {
  const chart = useChartColors();
  const c = useColors();
  const d = data.durations;
  return (
    <>
      <BarList
        rows={d.buckets.map((b) => ({ key: b.label, label: b.label, value: b.count }))}
        color={chart.series}
        unit="documents"
      />
      <p style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        {d.median_minutes !== null ? `Median ${d.median_minutes} min.` : 'No durations recorded.'}
        {d.unknown ? ` ${d.unknown} without a length.` : ''}
      </p>
    </>
  );
}

function ExampleList({ item }: { item: LabelCount }) {
  const c = useColors();
  return (
    <ul style={{ margin: 0, paddingLeft: space['4'], display: 'flex', flexDirection: 'column', gap: 2 }}>
      {item.examples.map((d) => (
        <li key={d.id}>
          {d.url ? (
            <a href={d.url} target="_blank" rel="noopener noreferrer" style={{ color: c.accent, textDecoration: 'none' }}>
              {d.title}
            </a>
          ) : (
            d.title
          )}
        </li>
      ))}
      {item.documents > item.examples.length && (
        <li style={{ color: c.textMuted, listStyle: 'none', marginLeft: `-${space['4']}` }}>
          and {item.documents - item.examples.length} more
        </li>
      )}
    </ul>
  );
}

function LabelPanel({ items, emptyText }: { items: LabelCount[]; emptyText: string }) {
  const chart = useChartColors();
  const c = useColors();
  if (items.length === 0) {
    return <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>{emptyText}</p>;
  }
  return (
    <BarList
      rows={items.map((t) => ({ key: t.label, label: t.label, value: t.documents, detail: <ExampleList item={t} /> }))}
      color={chart.series}
      unit="documents"
    />
  );
}

function QAPanel({ data }: { data: ChannelIntelligence }) {
  const c = useColors();
  const qa = data.qa;
  if (qa.exchanges === 0) {
    return (
      <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary }}>
        None of your answers cite this channel yet. Ask the library, or a run that includes it.
      </p>
    );
  }
  return (
    <>
      <p style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
        {qa.exchanges} of your {qa.exchanges === 1 ? 'answer cites' : 'answers cite'} this channel.
      </p>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
        {qa.recent.map((e) => (
          <li key={e.id} style={{ fontFamily: fonts.ui, fontSize: fontSize.sm }}>
            <Link
              to={e.kind === 'job' && e.job_id ? `/jobs/${e.job_id}` : '/library/qa'}
              style={{ color: c.textPrimary, textDecoration: 'none' }}
            >
              {e.question}
            </Link>
            <span style={{ display: 'block', fontSize: fontSize.xs, color: c.textMuted }}>
              {e.kind === 'job' ? 'In a run' : 'Across the library'}
              {e.created_at ? ` · ${formatDate(e.created_at)}` : ''}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function StancePanel({ stance }: { stance: NonNullable<ChannelIntelligence['stance']> }) {
  const chart = useChartColors();
  const c = useColors();
  const toRows = (series: MonthCounts[]): ColumnRow[] =>
    series.map((m) => ({ key: m.month, label: monthLabel(m.month), values: m.counts }));
  const stanceSeries = [
    { key: 'for', label: 'For', color: chart.positive },
    { key: 'neutral', label: 'Neutral', color: chart.neutral },
    { key: 'unclear', label: 'Unclear', color: chart.muted },
    { key: 'against', label: 'Against', color: chart.negative },
  ];
  const sentimentSeries = [
    { key: 'positive', label: 'Positive', color: chart.positive },
    { key: 'neutral', label: 'Neutral', color: chart.neutral },
    { key: 'mixed', label: 'Mixed', color: chart.muted },
    { key: 'negative', label: 'Negative', color: chart.negative },
  ];
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        From {stance.classified_documents} classified {stance.classified_documents === 1 ? 'document' : 'documents'}, by
        publish month.
      </p>
      <ColumnChart title="Stance per month" rows={toRows(stance.stance)} series={stanceSeries} unit="documents" xLabel={(r) => r.label} height={150} />
      <ColumnChart title="Sentiment per month" rows={toRows(stance.sentiment)} series={sentimentSeries} unit="documents" xLabel={(r) => r.label} height={150} />
    </div>
  );
}
