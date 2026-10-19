import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateShare, useUploadShare } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import { Button, FormField, Input, Modal, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { authorshipLabel, formatBytes, parseQuickShareInput } from '../../utils/echoShares';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

/**
 * "Add to Echo" (S-3.7.1): the sidebar button and its dialog. A link, a few
 * words, or a file goes straight into the shares inbox with no approval step
 * (`personal-brain.md` § Domain 5). Mounted only for tiers with Echo.
 */
export function QuickShare() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <SidebarButton onClick={() => setOpen(true)} />
      {open && <QuickShareDialog onClose={() => setOpen(false)} />}
    </>
  );
}

function SidebarButton({ onClick }: { onClick: () => void }) {
  const c = useColors();
  const [hovered, setHovered] = useState(false);
  return (
    <button
      type="button"
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      title="Share a link, a quote or a file with Echo"
      style={{
        width: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: space['2'],
        padding: `${space['2']} ${space['3']}`,
        borderRadius: radius.md,
        border: `1px dashed ${hovered ? c.accent : c.borderStrong}`,
        background: hovered ? c.accentSubtle : 'transparent',
        color: c.accent,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        fontWeight: fontWeight.semibold,
        cursor: 'pointer',
      }}
    >
      <span aria-hidden>+</span> Add to Echo
    </button>
  );
}

function QuickShareDialog({ onClose }: { onClose: () => void }) {
  const c = useColors();
  const navigate = useNavigate();
  const pushToast = useJobStore((s) => s.pushToast);
  const createShare = useCreateShare();
  const uploadShare = useUploadShare();
  const fileRef = useRef<HTMLInputElement>(null);

  const [raw, setRaw] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [annotation, setAnnotation] = useState('');
  const [ownWords, setOwnWords] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parsed = parseQuickShareInput(raw);
  const busy = createShare.isPending || uploadShare.isPending;
  const canSubmit = !busy && (file !== null || parsed.kind !== 'empty');
  const authorship = authorshipLabel(ownWords);

  const done = () => {
    pushToast('success', 'Shared with Echo.');
    onClose();
  };
  const fail = (err: unknown) =>
    setError(detailFromErrorBody((err as HttpErrorLike).response?.data) ?? 'Could not share that. Try again.');

  const submit = () => {
    setError(null);
    const note = annotation.trim() || null;
    if (file) {
      uploadShare.mutate(
        { file, fields: { annotation: note, author_is_tenant: ownWords } },
        { onSuccess: done, onError: fail },
      );
      return;
    }
    if (parsed.kind === 'url') {
      createShare.mutate({ url: parsed.url, annotation: note, author_is_tenant: ownWords }, { onSuccess: done, onError: fail });
    } else if (parsed.kind === 'text') {
      createShare.mutate({ text: parsed.text, annotation: note, author_is_tenant: ownWords }, { onSuccess: done, onError: fail });
    }
  };

  const hintStyle: React.CSSProperties = {
    margin: 0,
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    color: c.textMuted,
    lineHeight: lineHeight.snug,
  };

  return (
    <Modal
      open
      onClose={onClose}
      title="Add to Echo"
      footer={
        <>
          <Button
            variant="tertiary"
            onClick={() => {
              onClose();
              navigate('/echo/inbox');
            }}
          >
            Open inbox
          </Button>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!canSubmit} loading={busy}>
            Share
          </Button>
        </>
      }
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}>
        <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
          Paste a link, a quote or a thought, or attach a file. It goes straight into your shares inbox; nothing asks for
          approval, because sharing it is the choice.
        </p>

        {file ? (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['3'],
              padding: space['3'],
              border: `1px solid ${c.border}`,
              borderRadius: radius.md,
              background: c.surfaceAlt,
            }}
          >
            <span style={{ flex: 1, minWidth: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {file.name}
            </span>
            <span style={{ fontFamily: fonts.mono, fontSize: fontSize.xs, color: c.textMuted }}>{formatBytes(file.size)}</span>
            <Button size="sm" variant="tertiary" onClick={() => setFile(null)}>
              Remove
            </Button>
          </div>
        ) : (
          <FormField label="Link or words">
            {(id) => (
              <Textarea
                id={id}
                rows={4}
                value={raw}
                onChange={(e) => setRaw(e.target.value)}
                placeholder="https://… or a quote, a thought, a message you want Echo to keep"
                autoFocus
              />
            )}
          </FormField>
        )}

        <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
          {!file && (
            <>
              <input
                ref={fileRef}
                type="file"
                style={{ display: 'none' }}
                onChange={(e) => {
                  const f = e.target.files?.[0] ?? null;
                  setFile(f);
                  e.target.value = '';
                }}
              />
              <Button size="sm" variant="secondary" onClick={() => fileRef.current?.click()}>
                Attach a file instead
              </Button>
            </>
          )}
          <span style={hintStyle}>
            {file
              ? 'A screenshot, a voice memo, a small export. Up to 25 MB.'
              : parsed.kind === 'url'
                ? 'Shared as a link.'
                : parsed.kind === 'text'
                  ? 'Shared as text. For a link with commentary, put the link here and the why below.'
                  : ''}
          </span>
        </div>

        <FormField label="Why you're sharing it" optional>
          {(id) => (
            <Input
              id={id}
              value={annotation}
              onChange={(e) => setAnnotation(e.target.value)}
              placeholder="This is exactly how I think about…"
              maxLength={5000}
            />
          )}
        </FormField>

        <label style={{ display: 'flex', alignItems: 'flex-start', gap: space['2'], cursor: 'pointer' }}>
          <input
            type="checkbox"
            checked={ownWords}
            onChange={(e) => setOwnWords(e.target.checked)}
            style={{ marginTop: 3, accentColor: c.accent }}
          />
          <span>
            <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.textPrimary }}>
              These are my own words
            </span>
            <span style={{ ...hintStyle, display: 'block', marginTop: 2 }}>{authorship.hint}</span>
          </span>
        </label>

        {error && (
          <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}
