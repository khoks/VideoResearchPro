/**
 * The palette's panel (S-8.2.2), loaded on first open so `cmdk` and its
 * Radix dependencies stay out of the main bundle. See CommandPalette.tsx.
 */
import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from 'react';
import { Command, useCommandState } from 'cmdk';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { modLabel } from '../../hooks/useShortcuts';
import { useColors, useShadows } from '../../hooks/useTheme';
import { useTierCapabilities } from '../../hooks/useTierCapabilities';
import { exportsApi } from '../../services/exportsApi';
import { searchApi, type SearchItem, type SearchType } from '../../services/searchApi';
import { useJobStore } from '../../stores/jobStore';
import { usePaletteStore } from '../../stores/paletteStore';
import { downloadUrl } from '../../utils/download';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, z } from '../../theme';
import {
  GROUP_LABEL,
  countResults,
  loadRecent,
  matchesQuery,
  pushRecent,
  type PaletteAction,
  type RecentItem,
} from './model';

const DEBOUNCE_MS = 180;

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

export default function PalettePanel({ onClose }: { onClose: () => void }) {
  const c = useColors();
  const s = useShadows();
  const navigate = useNavigate();
  const { token } = useAuth();
  const { has } = useTierCapabilities();
  const theme = useJobStore((st) => st.theme);
  const toggleTheme = useJobStore((st) => st.toggleTheme);
  const singleKey = usePaletteStore((st) => st.singleKeyShortcuts);
  const setSingleKey = usePaletteStore((st) => st.setSingleKeyShortcuts);
  const [query, setQuery] = useState('');
  const [recent, setRecent] = useState<RecentItem[]>(() => loadRecent());
  const returnFocus = useRef<HTMLElement | null>(null);
  const input = useRef<HTMLInputElement | null>(null);
  const panel = useRef<HTMLDivElement | null>(null);

  // cmdk only writes `aria-activedescendant` when it changes the selection
  // itself, not when `value` is passed in (as below), and its own prop wins
  // over ours. Mirror the selected option's id onto the combobox and the
  // listbox whenever `aria-selected` moves, so a screen reader always hears
  // the active option.
  useEffect(() => {
    const root = panel.current;
    if (!root) return;
    const sync = () => {
      const id = root.querySelector<HTMLElement>('[cmdk-item][aria-selected="true"]')?.id;
      root.querySelectorAll('[cmdk-input], [cmdk-list]').forEach((el) => {
        if (id) el.setAttribute('aria-activedescendant', id);
        else el.removeAttribute('aria-activedescendant');
      });
    };
    const observer = new MutationObserver(sync);
    observer.observe(root, { subtree: true, childList: true, attributes: true, attributeFilter: ['aria-selected'] });
    sync();
    return () => observer.disconnect();
  }, []);
  const q = useDebounced(query.trim(), DEBOUNCE_MS);

  useEffect(() => {
    returnFocus.current = document.activeElement as HTMLElement | null;
    input.current?.focus();
    return () => returnFocus.current?.focus?.();
  }, []);

  const search = useQuery({
    queryKey: ['search', q],
    queryFn: ({ signal }) => searchApi.search(q, signal),
    enabled: q.length > 0,
    staleTime: 30_000,
    placeholderData: (previous) => previous,
  });

  const go = (href: string, item: RecentItem) => {
    setRecent(pushRecent(item, recent));
    onClose();
    navigate(href);
  };

  const actions: PaletteAction[] = useMemo(() => {
    const nav = (id: string, label: string, href: string, keywords = ''): PaletteAction => ({
      id,
      label,
      keywords,
      run: () => {
        onClose();
        navigate(href);
      },
    });
    const list: PaletteAction[] = [
      nav('new-research', 'New research', '/submit', 'submit topic channel job run start'),
      nav('runs', 'Active runs', '/jobs', 'jobs history'),
      nav('library', 'Library', '/library', 'sources documents videos all'),
      nav('library-qa', 'Ask the library', '/library/qa', 'question library qa'),
      nav('qa-history', 'Echoes — Q&A history', '/qa-history', 'history questions answers knowledge'),
      nav('shelves', 'Shelves', '/shelves', 'collections organise'),
      nav('templates', 'Templates', '/templates', 'job templates starter'),
      nav('notes', 'Your notes', '/notes', 'notes annotations'),
      {
        id: 'notes-md',
        label: 'Export notes as Markdown',
        keywords: 'download notes md',
        run: () => {
          onClose();
          downloadUrl(exportsApi.getNotesMarkdownUrl(token), 'notes.md');
        },
      },
      {
        id: 'notes-jsonld',
        label: 'Export notes as JSON-LD',
        keywords: 'download notes json annotation',
        run: () => {
          onClose();
          downloadUrl(exportsApi.getNotesJsonldUrl(token), 'notes.jsonl');
        },
      },
      nav('exports', 'Exports', '/exports', 'datasets download jsonl'),
    ];
    if (has('author_studio')) list.push(nav('author', 'Author Studio', '/author', 'book write output'));
    if (has('echo_personal_brain')) list.push(nav('echo', 'Echo', '/echo', 'personal brain'));
    list.push(
      nav('ai-models', 'AI models', '/account/ai-models', 'llm settings keys byok'),
      nav('subscription', 'Subscription', '/account/subscription', 'plan tier billing'),
      {
        id: 'theme',
        label: theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode',
        keywords: 'theme toggle dark light',
        run: toggleTheme,
      },
      {
        id: 'single-key',
        label: singleKey ? 'Turn single-key shortcuts off' : 'Turn single-key shortcuts on',
        keywords: 'keyboard shortcuts slash g chords accessibility',
        hint: '/  g r  g l  g k  g a',
        run: () => setSingleKey(!singleKey),
      },
    );
    return list;
  }, [has, navigate, onClose, setSingleKey, singleKey, theme, toggleTheme, token]);

  const shownActions = query.trim() ? actions.filter((a) => matchesQuery(a, query)) : actions;
  const groups = q && search.data ? search.data.groups.filter((g) => g.items.length > 0) : [];

  // Selection is controlled here, not left to cmdk: when results arrive after
  // the list they replace has unmounted, cmdk keeps pointing at the removed
  // item, so nothing is active and Enter does nothing (seen in Chromium).
  const values = [
    ...(!query.trim() ? recent.map((r) => `recent:${r.href}`) : []),
    ...groups.flatMap((g) => g.items.map((item) => `${g.type}:${item.id}`)),
    ...shownActions.map((a) => `action:${a.id}`),
  ];
  const [selected, setSelected] = useState('');
  const valuesKey = values.join('|');
  useEffect(() => {
    if (!values.includes(selected)) setSelected(values[0] ?? '');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valuesKey]);
  const total = countResults(groups, shownActions.length);
  // A query still inside its debounce counts as searching: without this the
  // empty state flashed "Nothing matches" before the request was even sent.
  const settling = query.trim() !== q;
  const searching = settling || (!!q && search.isFetching);
  const status = !query.trim()
    ? ''
    : searching && !search.data
      ? 'Searching'
      : search.isError
        ? 'Search is unavailable; actions still work'
        : `${total} ${total === 1 ? 'result' : 'results'}`;

  return (
    <div
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: z.modal,
        background: 'rgba(20, 17, 14, 0.45)',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'flex-start',
        padding: `max(8vh, ${space['4']}) ${space['3']} ${space['4']}`,
      }}
    >
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        style={{
          width: 'min(640px, 100%)',
          maxHeight: 'min(70dvh, 560px)',
          display: 'flex',
          flexDirection: 'column',
          background: c.surface,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          boxShadow: s.floating,
          overflow: 'hidden',
          fontFamily: fonts.ui,
        }}
      >
        <Command
          label="Search and commands"
          shouldFilter={false}
          value={selected}
          onValueChange={setSelected}
          loop
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              onClose();
            } else if (e.key === 'Tab') {
              // The input is the only stop; the list moves with the arrows.
              e.preventDefault();
            }
          }}
          style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['2'],
              padding: `${space['2']} ${space['4']}`,
              borderBottom: `1px solid ${c.border}`,
            }}
          >
            <span aria-hidden style={{ color: c.textMuted }}>⌕</span>
            <Command.Input
              ref={input}
              value={query}
              onValueChange={setQuery}
              placeholder="Search runs, sources, channels, questions…"
              style={{
                flex: 1,
                minWidth: 0,
                border: 'none',
                outline: 'none',
                background: 'transparent',
                padding: `${space['2']} 0`,
                fontSize: fontSize.base,
                color: c.textPrimary,
              }}
            />
            {searching && <span style={{ fontSize: fontSize.xs, color: c.textMuted }}>Searching…</span>}
          </div>
          <Command.List
            label="Results"
            style={{ overflowY: 'auto', overscrollBehavior: 'contain', padding: space['2'], minHeight: 0 }}
          >
            {!!query.trim() && !searching && total === 0 && (
              <Command.Empty>
                <p style={{ margin: 0, padding: space['4'], fontSize: fontSize.sm, color: c.textSecondary }}>
                  {search.isError
                    ? 'Search is unavailable right now.'
                    : `Nothing in your library matches “${query.trim()}”.`}
                </p>
              </Command.Empty>
            )}
            {!query.trim() && recent.length > 0 && (
              <Section heading="Recent">
                {recent.map((r) => (
                  <Row
                    key={`recent:${r.href}`}
                    value={`recent:${r.href}`}
                    onSelect={() => go(r.href, r)}
                    title={r.title}
                    subtitle={[r.kind, r.subtitle].filter(Boolean).join(' · ')}
                  />
                ))}
              </Section>
            )}
            {groups.map((g) => (
              <Section key={g.type} heading={GROUP_LABEL[g.type]}>
                {g.items.map((item) => (
                  <Row
                    key={`${g.type}:${item.id}`}
                    value={`${g.type}:${item.id}`}
                    onSelect={() => go(item.href, toRecent(g.type, item))}
                    title={item.title}
                    subtitle={item.subtitle}
                  />
                ))}
              </Section>
            ))}
            {shownActions.length > 0 && (
              <Section heading="Go to and do">
                {shownActions.map((a) => (
                  <Row key={`action:${a.id}`} value={`action:${a.id}`} onSelect={a.run} title={a.label} hint={a.hint} />
                ))}
              </Section>
            )}
          </Command.List>
        </Command>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: space['3'],
            padding: `${space['2']} ${space['4']}`,
            borderTop: `1px solid ${c.border}`,
            fontSize: fontSize.xs,
            color: c.textMuted,
          }}
        >
          <span>↑ ↓ to move</span>
          <span>Enter to open</span>
          <span>Esc to close</span>
          <span style={{ marginLeft: 'auto' }}>{modLabel()} K anywhere</span>
        </div>
        <div aria-live="polite" className="reader-sr-only">
          {status}
        </div>
      </div>
    </div>
  );
}

function toRecent(type: SearchType, item: SearchItem): RecentItem {
  return { href: item.href, title: item.title, subtitle: item.subtitle, kind: GROUP_LABEL[type] };
}

function Section({ heading, children }: { heading: string; children: ReactNode }) {
  const c = useColors();
  return (
    <Command.Group
      heading={
        <span
          style={{
            display: 'block',
            padding: `${space['2']} ${space['3']} ${space['1']}`,
            fontSize: fontSize.xs,
            fontWeight: fontWeight.semibold,
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: c.textMuted,
          }}
        >
          {heading}
        </span>
      }
    >
      {children}
    </Command.Group>
  );
}

function Row({
  value,
  onSelect,
  title,
  subtitle,
  hint,
}: {
  value: string;
  onSelect: () => void;
  title: string;
  subtitle?: string;
  hint?: string;
}) {
  const c = useColors();
  const selected = useCommandState((state) => state.value === value);
  const style: CSSProperties = {
    display: 'flex',
    alignItems: 'baseline',
    gap: space['3'],
    padding: `${space['2']} ${space['3']}`,
    borderRadius: radius.md,
    cursor: 'pointer',
    background: selected ? c.accentSubtle : 'transparent',
    color: selected ? c.accent : c.textPrimary,
    lineHeight: lineHeight.snug,
  };
  return (
    <Command.Item value={value} onSelect={onSelect} style={style}>
      <span style={{ minWidth: 0, flex: 1 }}>
        <span style={{ display: 'block', fontSize: fontSize.sm, fontWeight: fontWeight.medium, overflowWrap: 'anywhere' }}>
          {title}
        </span>
        {subtitle && (
          <span style={{ display: 'block', fontSize: fontSize.xs, color: c.textMuted, overflowWrap: 'anywhere' }}>
            {subtitle}
          </span>
        )}
      </span>
      {hint && <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textMuted }}>{hint}</span>}
    </Command.Item>
  );
}
