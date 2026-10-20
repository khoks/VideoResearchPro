import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateShare, useUploadShare } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { MAX_DROP_FILES, isShareableDrag, planDrop } from '../../utils/echoDrop';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

function isEditable(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || typeof el.closest !== 'function') return false;
  return Boolean(el.closest('input, textarea, select, [contenteditable=""], [contenteditable="true"]'));
}

/**
 * Echo's drop zone (S-3.7.3): drop a file, a link or some text anywhere in
 * the app and it lands in the shares inbox (`surface=drag_drop`). A WhatsApp
 * or Takeout export opens the importer instead. Drags that start inside the
 * page, and drops onto text fields, are left alone. Mounted only for tiers
 * with Echo.
 */
export function EchoDropZone() {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const upload = useUploadShare();
  const create = useCreateShare();
  const [active, setActive] = useState(false);
  const internal = useRef(false);
  const depth = useRef(0);

  useEffect(() => {
    const fail = (err: unknown, fallback: string) =>
      pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? fallback);

    const onDragStart = () => {
      internal.current = true;
    };
    const onDragEnd = () => {
      internal.current = false;
    };
    const wanted = (e: DragEvent) =>
      !internal.current && isShareableDrag(e.dataTransfer ? Array.from(e.dataTransfer.types) : null);

    const onDragEnter = (e: DragEvent) => {
      if (!wanted(e)) return;
      depth.current += 1;
      setActive(true);
    };
    const onDragOver = (e: DragEvent) => {
      if (!wanted(e) || isEditable(e.target)) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    };
    const onDragLeave = (e: DragEvent) => {
      if (!wanted(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (depth.current === 0) setActive(false);
    };
    const onDrop = (e: DragEvent) => {
      const ours = wanted(e) && !isEditable(e.target);
      depth.current = 0;
      setActive(false);
      internal.current = false;
      if (!ours || !e.dataTransfer) return;
      e.preventDefault();
      const plan = planDrop({
        types: Array.from(e.dataTransfer.types),
        files: e.dataTransfer.files,
        getData: (type) => e.dataTransfer?.getData(type) ?? '',
      });
      if (plan.kind === 'files') {
        if (plan.exports.length) {
          pushToast('info', 'That looks like an export; the importer shows what is in it first.');
          navigate('/echo/import', { state: { file: plan.exports[0] } });
        }
        for (const file of plan.files) {
          upload.mutate(
            { file, fields: { surface: 'drag_drop' } },
            {
              onSuccess: () => pushToast('success', `Added ${file.name} to Echo.`),
              onError: (err) => fail(err, `Could not add ${file.name}.`),
            },
          );
        }
        if (plan.skipped) pushToast('info', `Only the first ${MAX_DROP_FILES} files were added.`);
      } else if (plan.kind === 'url') {
        create.mutate(
          { url: plan.url, surface: 'drag_drop' },
          { onSuccess: () => pushToast('success', 'Link added to Echo.'), onError: (err) => fail(err, 'Could not add the link.') },
        );
      } else if (plan.kind === 'text') {
        create.mutate(
          { text: plan.text, surface: 'drag_drop' },
          { onSuccess: () => pushToast('success', 'Text added to Echo.'), onError: (err) => fail(err, 'Could not add the text.') },
        );
      }
    };

    document.addEventListener('dragstart', onDragStart);
    document.addEventListener('dragend', onDragEnd);
    window.addEventListener('dragenter', onDragEnter);
    window.addEventListener('dragover', onDragOver);
    window.addEventListener('dragleave', onDragLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      document.removeEventListener('dragstart', onDragStart);
      document.removeEventListener('dragend', onDragEnd);
      window.removeEventListener('dragenter', onDragEnter);
      window.removeEventListener('dragover', onDragOver);
      window.removeEventListener('dragleave', onDragLeave);
      window.removeEventListener('drop', onDrop);
    };
    // The mutations' identities change per render; their mutate functions do not need to.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate, pushToast]);

  if (!active) return null;
  return (
    <div
      aria-hidden
      style={{
        position: 'fixed',
        inset: space['4'],
        zIndex: 1000,
        pointerEvents: 'none',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        borderRadius: radius.lg,
        border: `2px dashed ${c.accent}`,
        background: `color-mix(in srgb, ${c.surface} 85%, transparent)`,
      }}
    >
      <div style={{ textAlign: 'center', maxWidth: 420 }}>
        <div style={{ fontFamily: fonts.display, fontSize: fontSize['2xl'], fontWeight: fontWeight.semibold, color: c.accent }}>
          Drop to add to Echo
        </div>
        <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal, margin: `${space['2']} 0 0` }}>
          Files, links or text go to your shares inbox. A WhatsApp or Takeout export opens the importer.
        </p>
      </div>
    </div>
  );
}
