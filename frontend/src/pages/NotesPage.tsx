import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';
import { useJobStore } from '../stores/jobStore';
import { useDeleteNote, useNotesList, useUpdateNote } from '../hooks/useNotes';
import {
  noteTargetHref,
  noteTargetTypeLabel,
  type Note,
  type NoteTargetType,
} from '../services/notesApi';
import { exportsApi } from '../services/exportsApi';
import { formatDate } from '../utils/formatters';
import { NoteCard, NoteEditor } from '../components/notes';
import { Button, Card, EmptyState, Input, Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';

// The server's largest page. Notes are few and small; the page shows the
// newest PAGE_LIMIT and says so when there are more, rather than paginating
// groups that would then split across pages.
const PAGE_LIMIT = 2000;

/** Group order on the page and in the Markdown export. */
const GROUP_ORDER: NoteTargetType[] = [
  'document',
  'knowledge_artifact',
  'job',
  'qa_exchange',
  'library_qa_exchange',
  'qa_history_exchange',
  'channel',
];

type TypeFilter = NoteTargetType | 'all';

interface Group {
  type: NoteTargetType;
  notes: Note[];
}

export function countByType(notes: Note[]): Record<NoteTargetType, number> {
  const counts = Object.fromEntries(GROUP_ORDER.map((t) => [t, 0])) as Record<NoteTargetType, number>;
  for (const n of notes) counts[n.target_type] = (counts[n.target_type] ?? 0) + 1;
  return counts;
}

/** Newest first within each group; the server already orders that way. */
export function groupNotes(notes: Note[], filter: TypeFilter): Group[] {
  return GROUP_ORDER.filter((t) => filter === 'all' || t === filter)
    .map((type) => ({ type, notes: notes.filter((n) => n.target_type === type) }))
    .filter((g) => g.notes.length > 0);
}

function errorMessage(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return 'Could not save the note. Try again.';
}

export function NotesPage() {
  const c = useColors();
  const { token } = useAuth();
  const pushToast = useJobStore((s) => s.pushToast);

  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  const [typeFilter, setTypeFilter] = useState<TypeFilter>('all');
  const [showWithdrawn, setShowWithdrawn] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);

  const list = useNotesList({ q: q || undefined, include_deleted: showWithdrawn, limit: PAGE_LIMIT });
  const updateNote = useUpdateNote();
  const deleteNote = useDeleteNote();

  const items = useMemo(() => list.data?.items ?? [], [list.data]);
  const total = list.data?.total ?? 0;
  const counts = useMemo(() => countByType(items), [items]);
  const groups = useMemo(() => groupNotes(items, typeFilter), [items, typeFilter]);
  const truncated = total > items.length;

  const handleExport = (kind: 'md' | 'jsonld') => {
    if (!token) {
      pushToast('error', 'You must be signed in to export notes.');
      return;
    }
    // Fetched with the header, saved from a blob: URL (T-8.8.1.5).
    exportsApi
      .download(kind === 'md' ? 'notesMarkdown' : 'notesJsonld')
      .catch(() => pushToast('error', 'Could not fetch your notes for export.'));
  };

  const chipStyle = (active: boolean): React.CSSProperties => ({
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    padding: `${space['1']} ${space['3']}`,
    borderRadius: radius.pill,
    border: `1px solid ${active ? c.accent : c.border}`,
    background: active ? c.accentSubtle : c.surface,
    color: active ? c.accent : c.textSecondary,
    cursor: 'pointer',
  });

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: space['4'],
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 420px', minWidth: 0 }}>
          <h1
            style={{
              fontFamily: fonts.display,
              fontSize: fontSize['2xl'],
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
              margin: 0,
              lineHeight: lineHeight.tight,
            }}
          >
            Your notes
          </h1>
          <p
            style={{
              fontFamily: fonts.body,
              fontSize: fontSize.base,
              color: c.textSecondary,
              margin: `${space['2']} 0 0`,
              lineHeight: lineHeight.normal,
              maxWidth: measure.reading,
            }}
          >
            Everything you have written on sources, runs, answers and channels, newest first. Your
            own voice in the library, and the first thing Echo learns from.
          </p>
        </div>
        <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
          <Button variant="secondary" size="sm" onClick={() => handleExport('md')} disabled={total === 0}>
            Export Markdown
          </Button>
          <Button variant="tertiary" size="sm" onClick={() => handleExport('jsonld')} disabled={total === 0}>
            Export JSON-LD
          </Button>
        </div>
      </header>

      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search your notes…"
              data-page-search
            aria-label="Search your notes"
          />
          <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
            <button type="button" style={chipStyle(typeFilter === 'all')} onClick={() => setTypeFilter('all')}>
              All ({items.length})
            </button>
            {GROUP_ORDER.filter((t) => counts[t] > 0).map((t) => (
              <button
                key={t}
                type="button"
                style={chipStyle(typeFilter === t)}
                onClick={() => setTypeFilter(typeFilter === t ? 'all' : t)}
                aria-pressed={typeFilter === t}
              >
                {noteTargetTypeLabel(t)} ({counts[t]})
              </button>
            ))}
            <label
              style={{
                marginLeft: 'auto',
                display: 'inline-flex',
                alignItems: 'center',
                gap: space['2'],
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.textSecondary,
                cursor: 'pointer',
              }}
            >
              <input
                type="checkbox"
                checked={showWithdrawn}
                onChange={(e) => setShowWithdrawn(e.target.checked)}
              />
              Show withdrawn
            </label>
          </div>
          {truncated && (
            <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
              Showing the newest {items.length.toLocaleString()} of {total.toLocaleString()}. Narrow with a
              search to reach the rest; the export carries everything.
            </p>
          )}
        </div>
      </Card>

      {list.isLoading && (
        <div style={{ textAlign: 'center', padding: space['8'] }}>
          <Spinner size={28} />
        </div>
      )}

      {list.isError && (
        <Card>
          <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
            Could not load your notes.{' '}
            <Button size="sm" variant="tertiary" onClick={() => list.refetch()}>
              Retry
            </Button>
          </p>
        </Card>
      )}

      {!list.isLoading && !list.isError && items.length === 0 && (
        <EmptyState
          title={q ? `Nothing matches “${q}”.` : 'Nothing written yet.'}
          description={
            q
              ? 'Try fewer words, or clear the search to see every note.'
              : 'Add a note from any source row, research run, answer card or channel. Each one collects here, and Echo will learn your voice from them.'
          }
          action={q ? <Button variant="secondary" onClick={() => setSearch('')}>Clear search</Button> : undefined}
        />
      )}

      {groups.map((g) => (
        <section key={g.type} aria-label={noteTargetTypeLabel(g.type)}>
          <h2
            style={{
              margin: `0 0 ${space['3']}`,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            {noteTargetTypeLabel(g.type)}{' '}
            <span style={{ color: c.textMuted, fontWeight: fontWeight.regular }}>({g.notes.length})</span>
          </h2>
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
            {g.notes.map((n) =>
              editingId === n.id ? (
                <NoteEditor
                  key={n.id}
                  heading="Edit note"
                  initialBody={n.body_md}
                  saving={updateNote.isPending}
                  error={updateNote.isError ? errorMessage(updateNote.error) : null}
                  onSave={(body) =>
                    updateNote.mutate(
                      { id: n.id, payload: { body_md: body } },
                      { onSuccess: () => setEditingId(null) },
                    )
                  }
                  onCancel={() => {
                    setEditingId(null);
                    updateNote.reset();
                  }}
                />
              ) : (
                <NoteCard
                  key={n.id}
                  note={n}
                  meta={<TargetLine note={n} />}
                  onEdit={n.deleted_at ? undefined : () => setEditingId(n.id)}
                  onDelete={n.deleted_at ? undefined : () => deleteNote.mutate(n.id)}
                  deleting={deleteNote.isPending && deleteNote.variables === n.id}
                />
              ),
            )}
          </div>
        </section>
      ))}
    </div>
  );
}

/** "on <target>" with a link to the page the target lives on; a withdrawn
 * note says so instead of offering edit controls. */
function TargetLine({ note }: { note: Note }): ReactNode {
  const c = useColors();
  const href = noteTargetHref(note);
  const label = note.target_label ?? 'a target that is no longer available';
  const kind = noteTargetTypeLabel(note.target_type);
  const linkStyle: React.CSSProperties = {
    color: c.accent,
    textDecoration: 'underline',
    textUnderlineOffset: 3,
    fontWeight: fontWeight.medium,
  };
  return (
    <span>
      on {kind}:{' '}
      {href && note.target_label ? (
        <Link to={href} style={linkStyle}>
          {label}
        </Link>
      ) : (
        <span style={{ fontStyle: 'italic' }}>{label}</span>
      )}
      {note.deleted_at && (
        <>
          {' '}
          · <span style={{ color: c.warn }}>withdrawn {formatDate(note.deleted_at)}</span>
        </>
      )}
    </span>
  );
}
