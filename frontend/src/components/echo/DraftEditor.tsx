import { useState, type ReactNode } from 'react';
import { useDraftFeedback } from '../../hooks/useEcho';
import type { DraftResponse } from '../../services/echoApi';
import { Button, FormField, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, lineHeight, space } from '../../theme';
import { learnedLine, withDisclosure } from '../../utils/echoDrafts';

/**
 * A "speak as me" draft as the user's own version (S-3.4.2): edit it in
 * place, keep or drop the disclosure line, copy it, save it. Saving sends
 * `POST /echo/drafts/{id}/feedback`; the words the user typed are all Echo
 * learns from, never its own words or the sender's (D-104). One view for the
 * Echo page card and the Echo bubble, which share one contract.
 */
export function DraftEditor({
  draft,
  compact = false,
  onCopy,
  meta,
}: {
  draft: DraftResponse;
  /** The bubble: a shorter box and no hint line. */
  compact?: boolean;
  onCopy?: () => void;
  /** Shown beside the buttons (the voice score). */
  meta?: ReactNode;
}) {
  const c = useColors();
  const feedback = useDraftFeedback();
  const disclosure = draft.disclosure ?? '';
  const [version, setVersion] = useState(draft.final_text ?? draft.draft);
  const [keep, setKeep] = useState(draft.disclosure_kept ?? true);
  const [saved, setSaved] = useState<DraftResponse | null>(draft.final_text != null ? draft : null);
  const [copied, setCopied] = useState(false);
  const small: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted };
  const dirty = !saved || version.trim() !== (saved.final_text ?? '') || keep !== saved.disclosure_kept;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(withDisclosure(version, disclosure, keep));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      onCopy?.();
    } catch {
      /* clipboard refused: the text is on screen to select */
    }
  };
  const save = () =>
    feedback.mutate({ id: draft.id, final_text: version.trim(), disclosure_kept: keep }, { onSuccess: (d) => setSaved(d) });

  return (
    <div data-draft-editor style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <FormField label="Your version" helperText={compact ? undefined : 'Change anything. When you save it, Echo learns from the words you typed, never from its own.'}>
        {(id) => (
          <Textarea
            id={id}
            data-version
            rows={compact ? 4 : 6}
            maxLength={16000}
            value={version}
            onChange={(e) => setVersion(e.target.value)}
            style={{ fontFamily: fonts.body, fontSize: compact ? fontSize.sm : fontSize.base, lineHeight: lineHeight.normal }}
          />
        )}
      </FormField>
      {disclosure && (
        <>
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, cursor: 'pointer' }}>
            <input type="checkbox" data-keep-disclosure checked={keep} onChange={(e) => setKeep(e.target.checked)} style={{ accentColor: c.accent }} />
            Add the disclosure line
          </label>
          {keep && (
            <div data-disclosure style={small}>
              {disclosure}
            </div>
          )}
        </>
      )}
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
        <Button type="button" size="sm" variant="secondary" onClick={copy} disabled={!version.trim()}>
          {copied ? 'Copied' : 'Copy'}
        </Button>
        <Button type="button" size="sm" onClick={save} loading={feedback.isPending} disabled={!version.trim() || !dirty}>
          Save my version
        </Button>
        {meta}
      </div>
      {saved && !dirty && (
        <p data-saved style={{ ...small, margin: 0 }}>
          {learnedLine(saved.edit)}
        </p>
      )}
      {feedback.isError && (
        <p role="alert" style={{ ...small, margin: 0, color: c.error }}>
          Couldn't save your version. Try again.
        </p>
      )}
    </div>
  );
}
