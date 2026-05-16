import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import { useColors } from '../hooks/useTheme';
import { useJobStore } from '../stores/jobStore';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../theme';

interface OutputRow {
  id: string;
  kind: string;
  status: 'pending' | 'generating' | 'completed' | 'failed';
  title: string | null;
  error_message: string | null;
  created_at: string;
}

const SHIPPED_KINDS = ['book'];
const COMING_SOON_KINDS = ['site', 'deck', 'newsletter', 'reel'];

/**
 * Author Studio — Pro-tier and up.
 *
 * Backend foundation shipped per I-6 (PR #173): outputs table + Outputter
 * Protocol + Book v1 outputter. Site / Deck / Newsletter / Reel return
 * 501 today; the page lists them under "Coming soon".
 */
export function AuthorPage() {
  const c = useColors();
  const qc = useQueryClient();
  const pushToast = useJobStore((s) => s.pushToast);
  const [title, setTitle] = useState('');

  const list = useQuery<OutputRow[]>({
    queryKey: ['author', 'outputs'],
    queryFn: async () => (await api.get('/author/outputs')).data,
  });

  const createBook = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/author/outputs', {
        kind: 'book',
        title: title.trim() || 'Untitled book',
      });
      return data;
    },
    onSuccess: () => {
      setTitle('');
      qc.invalidateQueries({ queryKey: ['author', 'outputs'] });
      pushToast('success', 'Book generation started.');
    },
  });

  return (
    <div style={{ maxWidth: 1000, margin: '0 auto' }}>
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
          Author Studio
        </h1>
        <p
          style={{
            margin: `${space['2']} 0 0`,
            fontFamily: fonts.body,
            fontSize: fontSize.md,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          Generate long-form output from the sources you've curated. Books today; sites, decks, newsletters,
          and reels coming. Every paragraph traces back to the source via citation.
        </p>
      </header>

      {/* Output-kind grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
          gap: space['4'],
          marginBottom: space['6'],
        }}
      >
        {SHIPPED_KINDS.map((kind) => (
          <KindCard key={kind} kind={kind} available />
        ))}
        {COMING_SOON_KINDS.map((kind) => (
          <KindCard key={kind} kind={kind} available={false} />
        ))}
      </div>

      {/* Quick-start: generate a book */}
      <div
        style={{
          background: c.surface,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          padding: space['5'],
          marginBottom: space['6'],
        }}
      >
        <h2 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
          Generate a book
        </h2>
        <p style={{ margin: `${space['2']} 0 ${space['4']}`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
          Pulls from the documents in your library and produces a Markdown manuscript. v1 is straightforward
          concatenation + framing; LLM-driven cohesion polish lands in E-6.1.2.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            createBook.mutate();
          }}
          style={{ display: 'flex', gap: space['3'], alignItems: 'flex-end' }}
        >
          <label style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, fontWeight: fontWeight.medium }}>
              Book title
            </span>
            <input
              type="text"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="e.g. 'Two years of the AI policy debate'"
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                padding: `${space['2']} ${space['3']}`,
                background: c.bg,
                color: c.textPrimary,
                border: `1px solid ${c.border}`,
                borderRadius: radius.sm,
              }}
            />
          </label>
          <button
            type="submit"
            disabled={createBook.isPending}
            style={{
              padding: `${space['2']} ${space['5']}`,
              background: c.accent,
              color: c.bg,
              border: 'none',
              borderRadius: radius.md,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              fontWeight: fontWeight.semibold,
              cursor: createBook.isPending ? 'wait' : 'pointer',
              whiteSpace: 'nowrap',
            }}
          >
            {createBook.isPending ? 'Starting…' : 'Generate'}
          </button>
        </form>
      </div>

      {/* Outputs list */}
      <h2 style={{ margin: `0 0 ${space['3']}`, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
        Your outputs ({list.data?.length ?? 0})
      </h2>
      {list.isLoading && <p style={{ color: c.textMuted }}>Loading…</p>}
      {!list.isLoading && (!list.data || list.data.length === 0) && (
        <p style={{ fontFamily: fonts.body, fontStyle: 'italic', color: c.textMuted }}>
          No outputs yet. Generate your first book above.
        </p>
      )}
      {list.data && list.data.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {list.data.map((row) => (
            <li
              key={row.id}
              style={{
                background: c.surface,
                border: `1px solid ${c.border}`,
                borderRadius: radius.md,
                padding: `${space['3']} ${space['4']}`,
                display: 'flex',
                gap: space['3'],
                alignItems: 'baseline',
              }}
            >
              <StatusBadge status={row.status} />
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary, flex: 1 }}>
                {row.title ?? 'Untitled'}
              </span>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                {row.kind}
              </span>
              {row.status === 'completed' && (
                <a
                  href={`${api.defaults.baseURL}/author/outputs/${row.id}/content`}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    fontFamily: fonts.ui,
                    fontSize: fontSize.sm,
                    fontWeight: fontWeight.semibold,
                    color: c.accent,
                    textDecoration: 'none',
                  }}
                >
                  View →
                </a>
              )}
              {row.status === 'failed' && row.error_message && (
                <span
                  title={row.error_message}
                  style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.error, fontStyle: 'italic' }}
                >
                  {row.error_message.slice(0, 60)}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function KindCard({ kind, available }: { kind: string; available: boolean }) {
  const c = useColors();
  return (
    <div
      style={{
        background: available ? c.surface : c.surfaceAlt,
        border: `1px solid ${c.border}`,
        borderRadius: radius.lg,
        padding: space['4'],
        opacity: available ? 1 : 0.6,
      }}
    >
      <div
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          fontWeight: fontWeight.semibold,
          letterSpacing: '0.08em',
          textTransform: 'uppercase',
          color: available ? c.forest : c.textMuted,
          marginBottom: space['2'],
        }}
      >
        {available ? 'Available now' : 'Coming soon'}
      </div>
      <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary, textTransform: 'capitalize' }}>
        {kind}
      </h3>
    </div>
  );
}

function StatusBadge({ status }: { status: OutputRow['status'] }) {
  const c = useColors();
  const palette = {
    pending: { bg: c.surfaceAlt, fg: c.textSecondary },
    generating: { bg: c.infoSubtle, fg: c.info },
    completed: { bg: c.successSubtle, fg: c.success },
    failed: { bg: c.errorSubtle, fg: c.error },
  }[status];
  return (
    <span
      style={{
        fontFamily: fonts.ui,
        fontSize: fontSize.xs,
        fontWeight: fontWeight.semibold,
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
        background: palette.bg,
        color: palette.fg,
        padding: `2px ${space['2']}`,
        borderRadius: radius.sm,
        whiteSpace: 'nowrap',
      }}
    >
      {status}
    </span>
  );
}
