import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  useAddShareToLibrary,
  useDeleteShare,
  useReprocessShare,
  useShares,
  useUpdateShare,
} from '../hooks/useEcho';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useJobStore } from '../stores/jobStore';
import { echoApi, type Share, type ShareProcessingState } from '../services/echoApi';
import { Badge, Button, Card, EmptyState, Input, Modal, Select, Skeleton, Textarea } from '../components/primitives';
import { QuickShare } from '../components/echo/QuickShare';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, radius, space } from '../theme';
import { formatDate } from '../utils/formatters';
import {
  authorshipLabel,
  contentTypeLabel,
  formatBytes,
  processingStateLabel,
  shareReadingLabel,
} from '../utils/echoShares';
import { detailFromErrorBody, type HttpErrorLike } from '../utils/ingestResults';

const PAGE = 100;

function isForbidden(err: unknown): boolean {
  return (err as HttpErrorLike | null)?.response?.status === 403;
}

/**
 * Echo's shares inbox (S-3.7.1): everything the user forwarded, newest
 * first, with its state and what Echo may do with it. Processing (OCR,
 * transcription, embedding) is S-3.7.2, so every share says it is waiting
 * rather than pretending.
 */
export function EchoInboxPage() {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const { has, tier, isLoading: tierLoading } = useTierCapabilities();
  const allowed = has('echo_personal_brain');

  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 300);
    return () => clearTimeout(t);
  }, [search]);
  const [state, setState] = useState<ShareProcessingState | ''>('');
  const [limit, setLimit] = useState(PAGE);
  const [deleting, setDeleting] = useState<Share | null>(null);

  const shares = useShares({ q: q || undefined, state: state || undefined, limit }, allowed);
  const del = useDeleteShare();
  const items = shares.data?.items ?? [];
  const total = shares.data?.total ?? 0;
  const forbidden = isForbidden(shares.error);

  const confirmDelete = () => {
    if (!deleting) return;
    del.mutate(deleting.id, {
      onSuccess: () => {
        pushToast('success', 'Share deleted, with its file and anything derived from it.');
        setDeleting(null);
      },
      onError: () => pushToast('error', 'Delete failed. The share may already be gone.'),
    });
  };

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <header style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: space['4'], flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 420px', minWidth: 0 }}>
          <Link to="/echo" style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.accent, textDecoration: 'none' }}>
            ← Echo
          </Link>
          <h1 style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary, margin: `${space['2']} 0 0`, lineHeight: lineHeight.tight }}>
            Shares inbox
          </h1>
          <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, margin: `${space['2']} 0 0`, lineHeight: lineHeight.normal, maxWidth: measure.reading }}>
            Everything you have handed to Echo, newest first. Nothing here needed approval: sharing it was the choice.
            Correct a type, add why it mattered, mark your own words, or delete it and everything derived from it.
          </p>
        </div>
        {allowed && !forbidden && (
          <div style={{ width: 200 }}>
            <QuickShare />
          </div>
        )}
      </header>

      {!tierLoading && (!allowed || forbidden) ? (
        <EmptyState
          title="Echo opens at Studio."
          description={`The shares inbox is part of Echo, the private store of who you are. Your plan is ${tier}.`}
          action={<Button onClick={() => navigate('/account/subscription?upgrade=studio')}>See plans</Button>}
        />
      ) : (
        <>
          <Card>
            <div style={{ display: 'flex', gap: space['3'], flexWrap: 'wrap', alignItems: 'center' }}>
              <div style={{ flex: '1 1 260px' }}>
                <Input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search text, links, file names, your notes…"
                  aria-label="Search shares"
                />
              </div>
              <div style={{ width: 220 }}>
                <Select value={state} onChange={(e) => setState(e.target.value as ShareProcessingState | '')} aria-label="Filter by state">
                  <option value="">Every state</option>
                  <option value="pending">Waiting for processing</option>
                  <option value="processed">Processed</option>
                  <option value="failed">Processing failed</option>
                  <option value="skipped">Skipped</option>
                </Select>
              </div>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
                {shares.data ? `${total} ${total === 1 ? 'share' : 'shares'}` : ''}
              </span>
            </div>
          </Card>

          {shares.isLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
              <Skeleton variant="row" />
              <Skeleton variant="row" />
              <Skeleton variant="row" />
            </div>
          ) : shares.isError ? (
            <EmptyState
              size="sm"
              title="Couldn't load the inbox."
              description="Something blocked the fetch."
              action={<Button variant="secondary" size="sm" onClick={() => shares.refetch()}>Retry</Button>}
            />
          ) : items.length === 0 ? (
            <EmptyState
              title={q || state ? 'Nothing matches.' : 'Nothing shared yet.'}
              description={
                q || state
                  ? 'Try fewer words or every state.'
                  : 'Use "Add to Echo" in the sidebar for a link, a quote, a screenshot or a voice memo. It lands here.'
              }
            />
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
              {items.map((s) => (
                <ShareCard key={s.id} share={s} onDelete={() => setDeleting(s)} />
              ))}
              {total > items.length && (
                <Button variant="secondary" style={{ alignSelf: 'center' }} onClick={() => setLimit((n) => n + PAGE)}>
                  Show {Math.min(PAGE, total - items.length)} more
                </Button>
              )}
            </div>
          )}
        </>
      )}

      {deleting && (
        <Modal
          open
          onClose={() => setDeleting(null)}
          title="Delete this share?"
          footer={
            <>
              <Button variant="secondary" onClick={() => setDeleting(null)} disabled={del.isPending}>
                Keep it
              </Button>
              <Button variant="danger" onClick={confirmDelete} loading={del.isPending}>
                Delete
              </Button>
            </>
          }
        >
          <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
            The share, its file, and anything Echo derived from it are removed. This cannot be undone.
          </p>
        </Modal>
      )}
    </div>
  );
}

function ShareCard({ share, onDelete }: { share: Share; onDelete: () => void }) {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const update = useUpdateShare();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(share.user_annotation ?? '');
  const [downloading, setDownloading] = useState(false);
  const who = authorshipLabel(share.author_is_tenant);

  const save = (payload: Parameters<typeof update.mutate>[0]['payload'], ok?: () => void) =>
    update.mutate(
      { id: share.id, payload },
      {
        onSuccess: () => ok?.(),
        onError: (err) => pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Could not save.'),
      },
    );

  const download = async () => {
    setDownloading(true);
    try {
      await echoApi.downloadShareFile(share);
    } catch {
      pushToast('error', 'Could not fetch the file.');
    } finally {
      setDownloading(false);
    }
  };

  const metaStyle: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted };

  return (
    <Card>
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
          <Badge tone="accent" size="sm">{contentTypeLabel(share.content_type)}</Badge>
          <span title={who.hint}>
            <Badge tone={share.author_is_tenant ? 'success' : 'neutral'} size="sm">{who.label}</Badge>
          </span>
          <Badge tone={share.processing_state === 'failed' ? 'error' : share.processing_state === 'processed' ? 'success' : 'warn'} size="sm">
            {processingStateLabel(share.processing_state)}
          </Badge>
          <span style={{ ...metaStyle, marginLeft: 'auto' }}>Shared {formatDate(share.received_at)}</span>
        </div>

        {share.processing?.title && (
          <div style={{ fontFamily: fonts.display, fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
            {share.processing.title}
            {share.processing.author && (
              <span style={{ ...metaStyle, fontWeight: fontWeight.regular, marginLeft: space['2'] }}>{share.processing.author}</span>
            )}
          </div>
        )}
        {share.kind === 'url' && share.url && (
          <a
            href={share.url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ fontFamily: fonts.ui, fontSize: fontSize.base, color: c.accent, overflowWrap: 'anywhere' }}
          >
            {share.url}
          </a>
        )}
        {share.kind === 'text' && share.text && (
          <blockquote
            style={{
              margin: 0,
              padding: `${space['2']} ${space['3']}`,
              borderLeft: `3px solid ${share.author_is_tenant ? c.gold : c.border}`,
              background: c.surfaceAlt,
              borderRadius: radius.sm,
              fontFamily: fonts.body,
              fontSize: fontSize.base,
              color: c.textPrimary,
              lineHeight: lineHeight.normal,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
              maxHeight: 240,
              overflowY: 'auto',
            }}
          >
            {share.text}
          </blockquote>
        )}
        {share.kind === 'file' && share.file && (
          <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary, overflowWrap: 'anywhere' }}>{share.file.filename}</span>
            <span style={metaStyle}>{formatBytes(share.file.size)}</span>
            <Button size="sm" variant="tertiary" onClick={download} loading={downloading}>
              Download
            </Button>
          </div>
        )}

        {share.kind !== 'text' && share.extracted_text && (
          <p
            style={{
              margin: 0,
              fontFamily: fonts.body,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              lineHeight: lineHeight.normal,
              whiteSpace: 'pre-wrap',
              overflowWrap: 'anywhere',
              display: '-webkit-box',
              WebkitLineClamp: 4,
              WebkitBoxOrient: 'vertical',
              overflow: 'hidden',
            }}
          >
            {share.extracted_text}
          </p>
        )}
        <ProcessingLine share={share} />

        {editing ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
            <Textarea rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={5000} aria-label="Why you shared it" />
            <div style={{ display: 'flex', gap: space['2'] }}>
              <Button size="sm" loading={update.isPending} onClick={() => save({ annotation: draft.trim() || null }, () => setEditing(false))}>
                Save
              </Button>
              <Button size="sm" variant="tertiary" onClick={() => { setDraft(share.user_annotation ?? ''); setEditing(false); }}>
                Cancel
              </Button>
            </div>
          </div>
        ) : share.user_annotation ? (
          <p style={{ margin: 0, fontFamily: fonts.body, fontStyle: 'italic', fontSize: fontSize.sm, color: c.textSecondary }}>
            Why: {share.user_annotation}
          </p>
        ) : null}

        <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
          {!editing && (
            <Button size="sm" variant="tertiary" onClick={() => setEditing(true)}>
              {share.user_annotation ? 'Edit why' : 'Add why'}
            </Button>
          )}
          <Button
            size="sm"
            variant="tertiary"
            onClick={() => save({ author_is_tenant: !share.author_is_tenant })}
            title={share.author_is_tenant ? "Treat as someone else's words: context only" : 'Mark as words you wrote'}
          >
            {share.author_is_tenant ? 'Not my words' : 'These are my words'}
          </Button>
          <Button size="sm" variant="tertiary" style={{ color: c.error, marginLeft: 'auto' }} onClick={onDelete}>
            Delete
          </Button>
        </div>
      </div>
    </Card>
  );
}

/** S-3.7.2: why a share is waiting or failed, Retry, and the library offer. */
function ProcessingLine({ share }: { share: Share }) {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const reprocess = useReprocessShare();
  const addToLibrary = useAddShareToLibrary();
  const p = share.processing;
  const offer = p?.library_offer;
  const failed = share.processing_state === 'failed';
  const skipped = share.processing_state === 'skipped';
  const note = !failed ? p?.note : null;
  const reading = shareReadingLabel(p);
  const canOffer = share.kind === 'url' && offer?.eligible && !share.linked_document_id;
  if (!failed && !skipped && !note && !reading && !canOffer && !share.linked_document_id) return null;

  const line: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.sm, lineHeight: lineHeight.snug };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
      {reading && <span style={{ ...line, color: c.textMuted }}>{reading}</span>}
      {failed && <span role="alert" style={{ ...line, color: c.error }}>{p?.error || 'Processing failed.'}</span>}
      {note && <span style={{ ...line, color: c.textMuted }}>{note}</span>}
      {(failed || skipped) && (
        <>
          <Button
            size="sm"
            variant="tertiary"
            loading={reprocess.isPending}
            onClick={() =>
              reprocess.mutate(share.id, { onError: () => pushToast('error', 'Could not queue the retry.') })
            }
          >
            Retry
          </Button>
        </>
      )}
      {canOffer && (
        <Button
          size="sm"
          variant="secondary"
          loading={addToLibrary.isPending}
          onClick={() =>
            addToLibrary.mutate(share.id, {
              onSuccess: () => pushToast('success', 'Added to your library.'),
              onError: (err) =>
                pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Could not add it to the library.'),
            })
          }
          title="Add this page to your research library. Only you will see it there."
        >
          Add to library
        </Button>
      )}
      {share.linked_document_id && (
        <Link to="/library" style={{ ...line, color: c.forest }}>
          In your library →
        </Link>
      )}
    </div>
  );
}
