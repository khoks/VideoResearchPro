import { useRef, useState, type DragEvent } from 'react';
import { usePdfUploadQueue, type UploadItem } from '../../hooks/useLibraryIngest';
import { presentUploadResult } from '../../utils/ingestResults';
import { Badge, Button, type BadgeTone } from '../primitives';
import { ProgressBar } from '../common/ProgressBar';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, transitionAll } from '../../theme';

interface Props {
  /** Switch the page to the Sources tab so the new volumes are visible. */
  onViewShelf: () => void;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function PdfUploadZone({ onViewShelf }: Props) {
  const c = useColors();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const { items, enqueue, remove, clearFinished, isBusy } = usePdfUploadQueue();

  const takeFiles = (list: FileList | null) => {
    if (!list) return;
    enqueue(Array.from(list));
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(false);
    takeFiles(e.dataTransfer.files);
  };

  const finished = items.filter((i) => i.status === 'done' || i.status === 'error');
  const shelved = items.filter((i) => i.status === 'done').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
      <div
        role="button"
        tabIndex={0}
        aria-label="Upload PDFs: drop files here or press Enter to choose"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          if (!dragging) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        style={{
          border: `1px dashed ${dragging ? c.accent : c.borderStrong}`,
          background: dragging ? c.accentSubtle : c.surfaceAlt,
          borderRadius: radius.md,
          padding: `${space['6']} ${space['5']}`,
          textAlign: 'center',
          cursor: 'pointer',
          transition: transitionAll('fast'),
          outline: 'none',
        }}
      >
        <div
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize.lg,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            marginBottom: space['2'],
          }}
        >
          Drop PDFs here
        </div>
        <div
          style={{
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
            marginBottom: space['3'],
          }}
        >
          or choose files from your computer. Text is extracted page by page and shelved once;
          the same file uploaded twice is recognised, not duplicated.
        </div>
        <Button
          variant="secondary"
          size="sm"
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            inputRef.current?.click();
          }}
        >
          Choose PDFs
        </Button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          multiple
          hidden
          onChange={(e) => {
            takeFiles(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      {items.length > 0 && (
        <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {items.map((item) => (
            <UploadRow key={item.id} item={item} onRemove={() => remove(item.id)} />
          ))}
        </ul>
      )}

      {finished.length > 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
            {shelved} of {finished.length} shelved{isBusy ? ', more in flight' : ''}.
          </span>
          {shelved > 0 && (
            <Button size="sm" variant="tertiary" onClick={onViewShelf} trailingIcon={<span aria-hidden>→</span>}>
              See them on the shelf
            </Button>
          )}
          <Button size="sm" variant="tertiary" onClick={clearFinished}>
            Clear finished
          </Button>
        </div>
      )}
    </div>
  );
}

function statusBadge(item: UploadItem): { tone: BadgeTone; label: string } {
  switch (item.status) {
    case 'queued':
      return { tone: 'neutral', label: 'Queued' };
    case 'uploading':
      return { tone: 'info', label: item.progress >= 1 ? 'Extracting' : 'Uploading' };
    case 'done': {
      const p = item.result ? presentUploadResult(item.result) : null;
      return { tone: p?.tone ?? 'success', label: p?.label ?? 'Added' };
    }
    case 'error':
      return { tone: 'error', label: 'Failed' };
  }
}

function UploadRow({ item, onRemove }: { item: UploadItem; onRemove: () => void }) {
  const c = useColors();
  const badge = statusBadge(item);
  const detail =
    item.status === 'done' && item.result
      ? presentUploadResult(item.result).detail
      : item.status === 'error'
        ? item.error ?? 'Upload failed.'
        : item.status === 'uploading'
          ? item.progress >= 1
            ? 'Upload complete. Extracting text and building the index…'
            : `Uploading ${Math.round(item.progress * 100)}%`
          : 'Waiting for the previous file to finish.';

  return (
    <li
      style={{
        background: c.surface,
        border: `1px solid ${c.border}`,
        borderRadius: radius.md,
        padding: `${space['3']} ${space['4']}`,
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'] }}>
        <span
          title={item.file.name}
          style={{
            flex: 1,
            minWidth: 0,
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {item.file.name}
        </span>
        <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textMuted }}>
          {formatBytes(item.file.size)}
        </span>
        <Badge tone={badge.tone} size="sm">
          {badge.label}
        </Badge>
        {item.status !== 'uploading' && (
          <Button size="sm" variant="tertiary" onClick={onRemove} aria-label={`Remove ${item.file.name} from the list`}>
            Remove
          </Button>
        )}
      </div>
      {item.status === 'uploading' && <ProgressBar value={item.progress * 100} tone="info" />}
      <div
        style={{
          fontFamily: fonts.ui,
          fontSize: fontSize.xs,
          color: item.status === 'error' ? c.error : c.textSecondary,
          lineHeight: lineHeight.snug,
        }}
      >
        {detail}
      </div>
    </li>
  );
}
