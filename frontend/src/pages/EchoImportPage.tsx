import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useDeleteImport, useImports, usePreviewImport, useRetryImportEmbedding, useRunImport } from '../hooks/useEcho';
import { useTierCapabilities } from '../hooks/useTierCapabilities';
import { useJobStore } from '../stores/jobStore';
import type { EchoImportItem, ImportOptions, ImportPreview } from '../services/echoApi';
import { Badge, Button, Card, EmptyState, Modal, Select, Skeleton } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';
import { formatDate } from '../utils/formatters';
import {
  IMPORT_ACCEPT,
  browserTimeZone,
  importCountsLine,
  importProgress,
  importStatusLabel,
  importerLabel,
} from '../utils/echoImports';
import { detailFromErrorBody, type HttpErrorLike } from '../utils/ingestResults';

const NOT_ME = '__none__';

function errorText(err: unknown, fallback: string): string {
  return detailFromErrorBody((err as HttpErrorLike)?.response?.data) ?? fallback;
}

/**
 * Echo's export-file importer (S-3.7.5): bring a WhatsApp chat export or
 * Google Keep notes from Takeout into the brain. Preview first (nothing is
 * written), choose whose words are whose, then import. The file itself is
 * never kept; each import can be undone.
 */
export function EchoImportPage() {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const { has, tier, isLoading: tierLoading } = useTierCapabilities();
  const allowed = has('echo_personal_brain');

  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [self, setSelf] = useState<string>('');
  const [redact, setRedact] = useState(false);
  const [dateOrder, setDateOrder] = useState<'dmy' | 'mdy' | ''>('');
  const [ownWords, setOwnWords] = useState(true);
  const [includeTrashed, setIncludeTrashed] = useState(false);
  const [undoing, setUndoing] = useState<EchoImportItem | null>(null);

  const imports = useImports(allowed);
  const previewImport = usePreviewImport();
  const runImport = useRunImport();
  const retry = useRetryImportEmbedding();
  const undo = useDeleteImport();
  const tz = browserTimeZone();

  const clearChoices = () => {
    setFile(null);
    setPreview(null);
    setSelf('');
    setRedact(false);
    setDateOrder('');
    setOwnWords(true);
    setIncludeTrashed(false);
  };

  const reset = () => {
    clearChoices();
    if (inputRef.current) inputRef.current.value = '';
  };

  const options = (): ImportOptions => {
    if (preview?.importer === 'whatsapp') {
      return {
        self_name: self && self !== NOT_ME ? self : null,
        redact_other_party: redact,
        timezone: tz,
        ...(dateOrder ? { date_order: dateOrder } : {}),
      };
    }
    if (preview?.importer === 'google_keep') return { own_words: ownWords, include_trashed: includeTrashed };
    return {};
  };

  const pick = (f: File | null) => {
    clearChoices();
    if (!f) return;
    setFile(f);
    previewImport.mutate(
      { file: f, options: { timezone: tz } },
      {
        onSuccess: (pv) => {
          setPreview(pv);
          setDateOrder('');
        },
        onError: (err) => pushToast('error', errorText(err, 'This file could not be read.')),
      },
    );
  };

  const reorder = (order: 'dmy' | 'mdy') => {
    if (!file) return;
    setDateOrder(order);
    previewImport.mutate(
      { file, options: { timezone: tz, date_order: order } },
      { onSuccess: (pv) => setPreview(pv), onError: (err) => pushToast('error', errorText(err, 'Could not re-read the dates.')) },
    );
  };

  const start = () => {
    if (!file || !preview) return;
    runImport.mutate(
      { file, options: options() },
      {
        onSuccess: (item) => {
          pushToast('success', `Imported ${importCountsLine(item.importer, item.counts)}.`);
          reset();
        },
        onError: (err) => pushToast('error', errorText(err, 'The import failed.')),
      },
    );
  };

  const needsSelf = preview?.importer === 'whatsapp' && !self;
  const s = preview?.summary ?? {};

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto', display: 'flex', flexDirection: 'column', gap: space['5'] }}>
      <header>
        <Link to="/echo" style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.accent, textDecoration: 'none' }}>
          ← Echo
        </Link>
        <h1 style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.textPrimary, margin: `${space['2']} 0 0`, lineHeight: lineHeight.tight }}>
          Import an export
        </h1>
        <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, margin: `${space['2']} 0 0`, lineHeight: lineHeight.normal, maxWidth: measure.reading }}>
          Bring in a WhatsApp chat export (the .txt, or the .zip with media) or Google Keep notes from Google Takeout.
          You see what it holds before anything is stored, the file itself is never kept, and any import can be undone.
        </p>
      </header>

      {!tierLoading && !allowed ? (
        <EmptyState
          title="Echo opens at Studio."
          description={`Imports feed Echo, the private store of who you are. Your plan is ${tier}.`}
          action={<Button onClick={() => navigate('/account/subscription?upgrade=studio')}>See plans</Button>}
        />
      ) : (
        <>
          <Card>
            <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
                <input
                  ref={inputRef}
                  type="file"
                  accept={IMPORT_ACCEPT}
                  onChange={(e) => pick(e.target.files?.[0] ?? null)}
                  aria-label="Choose an export file"
                  style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary }}
                />
                {previewImport.isPending && <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>Reading it…</span>}
              </div>

              {preview && (
                <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
                    <Badge tone="accent" size="sm">{preview.label}</Badge>
                    <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
                      {summaryLine(preview)}
                    </span>
                  </div>
                  {preview.warnings.map((w) => (
                    <p key={w} style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.warn }}>{w}</p>
                  ))}

                  {preview.importer === 'whatsapp' && (
                    <>
                      <fieldset style={{ border: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                        <legend style={{ fontFamily: fonts.ui, fontSize: fontSize.base, fontWeight: fontWeight.semibold, color: c.textPrimary, marginBottom: space['2'] }}>
                          Which of these is you?
                        </legend>
                        {preview.participants.map((p) => (
                          <label key={p.name} style={{ display: 'flex', gap: space['2'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
                            <input type="radio" name="self" checked={self === p.name} onChange={() => setSelf(p.name)} style={{ accentColor: c.accent }} />
                            {p.name}
                            <span style={{ color: c.textMuted, fontSize: fontSize.sm }}>{p.messages.toLocaleString()} messages</span>
                          </label>
                        ))}
                        <label style={{ display: 'flex', gap: space['2'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
                          <input type="radio" name="self" checked={self === NOT_ME} onChange={() => { setSelf(NOT_ME); setRedact(false); }} style={{ accentColor: c.accent }} />
                          None of them: keep it all as context
                        </label>
                      </fieldset>
                      <label style={{ display: 'flex', gap: space['2'], alignItems: 'flex-start', fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
                        <input
                          type="checkbox"
                          checked={redact}
                          disabled={!self || self === NOT_ME}
                          onChange={(e) => setRedact(e.target.checked)}
                          style={{ marginTop: 3, accentColor: c.accent }}
                        />
                        <span>
                          Keep only my side of the chat
                          <span style={{ display: 'block', color: c.textMuted, fontSize: fontSize.sm }}>
                            The others' messages are never stored. Without this they are kept as context: searchable, never quoted as yours, never a sample of your voice.
                          </span>
                        </span>
                      </label>
                      {s.date_order_inferred === false && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
                          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>Dates in this chat are</span>
                          <div style={{ width: 220 }}>
                            <Select value={dateOrder || 'dmy'} onChange={(e) => reorder(e.target.value as 'dmy' | 'mdy')} aria-label="Date order">
                              <option value="dmy">Day first (31/01)</option>
                              <option value="mdy">Month first (01/31)</option>
                            </Select>
                          </div>
                        </div>
                      )}
                      {tz && (
                        <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                          Times are read as your phone's local time in {tz}.
                        </span>
                      )}
                    </>
                  )}

                  {preview.importer === 'google_keep' && (
                    <>
                      <label style={{ display: 'flex', gap: space['2'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
                        <input type="checkbox" checked={ownWords} onChange={(e) => setOwnWords(e.target.checked)} style={{ accentColor: c.accent }} />
                        These notes are my own words
                      </label>
                      <label style={{ display: 'flex', gap: space['2'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary }}>
                        <input type="checkbox" checked={includeTrashed} onChange={(e) => setIncludeTrashed(e.target.checked)} style={{ accentColor: c.accent }} />
                        Include notes in the trash
                      </label>
                    </>
                  )}

                  <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
                    <Button onClick={start} loading={runImport.isPending} disabled={needsSelf}>
                      Import
                    </Button>
                    <Button variant="tertiary" onClick={reset} disabled={runImport.isPending}>
                      Cancel
                    </Button>
                    {needsSelf && (
                      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>Say which participant is you first.</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>

          <section style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
            <h2 style={{ fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0 }}>
              Your imports
            </h2>
            {imports.isLoading ? (
              <Skeleton variant="row" />
            ) : (imports.data?.items ?? []).length === 0 ? (
              <EmptyState size="sm" title="Nothing imported yet." description="Imports you run appear here, each with its own undo." />
            ) : (
              (imports.data?.items ?? []).map((item) => (
                <Card key={item.id}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
                      <Badge tone="accent" size="sm">{importerLabel(item.importer)}</Badge>
                      <Badge tone={item.status === 'done' ? 'success' : item.status === 'failed' ? 'error' : 'warn'} size="sm">
                        {importStatusLabel(item.status)}
                      </Badge>
                      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.base, color: c.textPrimary, overflowWrap: 'anywhere' }}>{item.filename}</span>
                      <span style={{ marginLeft: 'auto', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
                        {formatDate(item.created_at)}
                      </span>
                    </div>
                    <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
                      {importCountsLine(item.importer, item.counts)}
                      {item.status === 'embedding' && importProgress(item.counts) ? ` · ${importProgress(item.counts)}` : ''}
                    </span>
                    {item.error && <span role="alert" style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>{item.error}</span>}
                    <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap', alignItems: 'center' }}>
                      <Link to={`/echo/inbox?import=${encodeURIComponent(item.id)}`} style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.accent }}>
                        See what it stored →
                      </Link>
                      {item.status === 'failed' && (
                        <Button size="sm" variant="tertiary" loading={retry.isPending} onClick={() => retry.mutate(item.id, { onError: (err) => pushToast('error', errorText(err, 'Could not retry.')) })}>
                          Retry indexing
                        </Button>
                      )}
                      <Button size="sm" variant="tertiary" style={{ marginLeft: 'auto' }} onClick={() => setUndoing(item)} disabled={item.status === 'deleting'}>
                        Undo import
                      </Button>
                    </div>
                  </div>
                </Card>
              ))
            )}
          </section>
        </>
      )}

      {undoing && (
        <Modal
          open
          onClose={() => setUndoing(null)}
          title="Undo this import?"
          footer={
            <>
              <Button variant="secondary" onClick={() => setUndoing(null)} disabled={undo.isPending}>
                Keep it
              </Button>
              <Button
                variant="danger"
                loading={undo.isPending}
                onClick={() =>
                  undo.mutate(undoing.id, {
                    onSuccess: (r) => {
                      pushToast('success', `Import undone: ${r.shares.toLocaleString()} items removed.`);
                      setUndoing(null);
                    },
                    onError: (err) => pushToast('error', errorText(err, 'Undo failed.')),
                  })
                }
              >
                Undo import
              </Button>
            </>
          }
        >
          <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal }}>
            Everything this import stored ({importCountsLine(undoing.importer, undoing.counts)}) is deleted, with anything Echo derived from it. Shares you
            added yourself are not touched.
          </p>
        </Modal>
      )}
    </div>
  );
}

function summaryLine(pv: ImportPreview): string {
  const s = pv.summary as Record<string, unknown>;
  const num = (k: string) => (typeof s[k] === 'number' ? (s[k] as number) : 0);
  const span = s.first_at && s.last_at ? ` from ${formatDate(String(s.first_at))} to ${formatDate(String(s.last_at))}` : '';
  if (pv.importer === 'whatsapp') {
    const chat = s.chat ? `with ${String(s.chat)}: ` : '';
    return `${chat}${num('messages').toLocaleString()} messages${span}, stored as ${num('turns').toLocaleString()} turns. ${num('media').toLocaleString()} media files are noted, not imported.`;
  }
  if (pv.importer === 'google_keep') {
    const trashed = num('trashed') ? `, ${num('trashed')} in the trash` : '';
    return `${num('notes').toLocaleString()} notes${span}${trashed}. Images are counted, not imported.`;
  }
  return '';
}
