import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateShare, useUploadShare } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { MAX_DROP_FILES, isShareableDrag, planDrop } from '../../utils/echoDrop';

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
  // The hooks say each failure, naming the file: a per-call `onError` would run
  // for the last of several dropped files only (T-3.4.1.17).
  const upload = useUploadShare({ toastErrors: true });
  const create = useCreateShare({ toastErrors: true });
  const [active, setActive] = useState(false);
  const internal = useRef(false);
  const depth = useRef(0);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    const onDragStart = () => {
      internal.current = true;
    };
    const onDragEnd = () => {
      internal.current = false;
    };
    const wanted = (e: DragEvent) =>
      !internal.current && isShareableDrag(e.dataTransfer ? Array.from(e.dataTransfer.types) : null);

    // One toast for each thing dropped that landed, every file of a drop
    // included (T-3.4.1.19). Each request's own promise says it: a per-call
    // `onSuccess` runs for an observer's last `mutate` only, so of several
    // files only the last was named. A failure is the hook's toast, and the
    // promise's rejection is handled here. Nothing once the zone has gone with
    // the session, so a file's name stays off the sign-in page.
    const added = (request: Promise<unknown>, message: string) => {
      request.then(
        () => {
          if (mounted.current) pushToast('success', message);
        },
        () => undefined,
      );
    };

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
          added(upload.mutateAsync({ file, fields: { surface: 'drag_drop' } }), `Added ${file.name} to Echo.`);
        }
        if (plan.skipped) pushToast('info', `Only the first ${MAX_DROP_FILES} files were added.`);
      } else if (plan.kind === 'url') {
        added(create.mutateAsync({ url: plan.url, surface: 'drag_drop' }), 'Link added to Echo.');
      } else if (plan.kind === 'text') {
        added(create.mutateAsync({ text: plan.text, surface: 'drag_drop' }), 'Text added to Echo.');
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
