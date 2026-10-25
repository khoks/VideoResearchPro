import { useState } from 'react';
import { useCreateDraft, useDeleteDraft, useDraftStatus, useRecentDrafts } from '../../hooks/useEcho';
import { DraftEditor } from './DraftEditor';
import { useJobStore } from '../../stores/jobStore';
import { openApiLink } from '../../services/apiFiles';
import type { CreateDraftPayload, EchoDraft } from '../../services/echoApi';
import { citedFileFailed } from '../citation/citedFile';
import { Badge, Button, Card, FormField, Input, Select, Skeleton, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { citationLabel, draftErrorOf } from '../../utils/echoDrafts';

/**
 * "Speak as me" (S-3.4.1, S-3.4.2): drafts a reply in the user's voice. Off until
 * every gate is open, and the gates are shown in words: the install switch,
 * readiness, the user's own "which did you write?" test (D-100), the daily
 * cap. Echo drafts; it never sends. The user edits the draft into their own
 * version and may drop the disclosure line; saving it records what they
 * typed, which is all Echo learns from.
 */
export function SpeakAsMePanel() {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const status = useDraftStatus();
  const recent = useRecentDrafts(status.data?.enabled ?? false);
  const create = useCreateDraft();
  const del = useDeleteDraft();
  const [message, setMessage] = useState('');
  const [audience, setAudience] = useState('');
  const [register, setRegister] = useState('');
  const [names, setNames] = useState<string[] | null>(null);
  const [result, setResult] = useState<EchoDraft | null>(null);

  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal };
  const st = status.data;

  const submit = (acknowledge: string[] = []) => {
    const payload: CreateDraftPayload = { message: message.trim() };
    if (audience.trim()) payload.audience = audience.trim();
    if (register) payload.register = register as CreateDraftPayload['register'];
    if (acknowledge.length) payload.acknowledge_names = acknowledge;
    create.mutate(payload, {
      onSuccess: (d) => {
        setResult(d);
        setNames(null);
      },
      onError: (err) => {
        const e = draftErrorOf(err);
        if (e.code === 'names_need_confirmation') setNames(e.names);
        else pushToast('error', e.message);
      },
    });
  };

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], flexWrap: 'wrap', marginBottom: space['2'] }}>
        <h2 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          Speak as me
        </h2>
        {st && (
          <Badge tone={st.enabled ? 'success' : 'neutral'} size="sm">
            {st.enabled ? `On · ${st.drafts_today} of ${st.drafts_per_day} drafts today` : 'Off'}
          </Badge>
        )}
      </div>
      <p style={text}>
        Paste a message and Echo drafts a reply the way you would write it, from your library, your notes and what it
        knows about you. It never sends anything: you read it, change it and decide.
      </p>

      {status.isLoading ? (
        <div style={{ marginTop: space['3'] }}>
          <Skeleton variant="text" />
        </div>
      ) : status.isError ? (
        <div style={{ marginTop: space['3'], display: 'flex', gap: space['3'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
          <span>Couldn't check whether drafting is on.</span>
          <Button size="sm" variant="tertiary" onClick={() => status.refetch()}>
            Retry
          </Button>
        </div>
      ) : st && !st.enabled ? (
        <div data-gate style={{ marginTop: space['3'] }}>
          <p style={{ ...text, fontFamily: fonts.ui, fontWeight: fontWeight.semibold, color: c.textPrimary }}>Not yet, because:</p>
          <ul style={{ margin: `${space['1']} 0 0`, paddingLeft: space['5'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            {st.blockers.map((b) => (
              <li key={b.code} data-blocker={b.code} style={text}>
                {b.message}
              </li>
            ))}
          </ul>
        </div>
      ) : st ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (message.trim() && !create.isPending) submit();
          }}
          style={{ marginTop: space['3'], display: 'flex', flexDirection: 'column', gap: space['3'] }}
        >
          <FormField label="The message you're replying to" required>
            {(id) => <Textarea id={id} rows={4} maxLength={8000} value={message} onChange={(e) => setMessage(e.target.value)} />}
          </FormField>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: space['3'] }}>
            <FormField label="Who it's for" optional>
              {(id) => <Input id={id} maxLength={200} value={audience} placeholder="e.g. my brother" onChange={(e) => setAudience(e.target.value)} />}
            </FormField>
            <FormField label="Register" optional>
              {(id) => (
                <Select id={id} value={register} onChange={(e) => setRegister(e.target.value)}>
                  <option value="">Whatever fits</option>
                  <option value="intimate">Intimate</option>
                  <option value="casual">Casual</option>
                  <option value="professional">Professional</option>
                  <option value="public">Public</option>
                </Select>
              )}
            </FormField>
          </div>
          {names && (
            <div data-names role="alert" style={{ ...text, padding: space['3'], border: `1px solid ${c.border}`, borderRadius: radius.md }}>
              This message names {names.join(', ')}, who looks like a private person. Echo will not add anything about
              them beyond what the message says.
              <div style={{ marginTop: space['2'], display: 'flex', gap: space['2'] }}>
                {/* type="button": inside the form, a submit button would also post the unacknowledged request. */}
                <Button type="button" size="sm" onClick={() => submit(names)} loading={create.isPending}>
                  Draft anyway
                </Button>
                <Button type="button" size="sm" variant="tertiary" onClick={() => setNames(null)}>
                  Cancel
                </Button>
              </div>
            </div>
          )}
          <div>
            <Button type="submit" disabled={!message.trim()} loading={create.isPending && !names}>
              Draft a reply
            </Button>
          </div>
        </form>
      ) : null}

      {result && <DraftView key={result.id} draft={result} onCopy={() => pushToast('success', 'Copied. Read it once more before you send it.')} />}

      {st?.enabled && (recent.data?.items.length ?? 0) > 0 && (
        <details style={{ marginTop: space['4'] }}>
          <summary style={{ cursor: 'pointer', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>Recent drafts</summary>
          <ul style={{ listStyle: 'none', margin: `${space['2']} 0 0`, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
            {recent.data!.items.map((d) => (
              <li key={d.id} data-draft={d.id} style={{ display: 'flex', gap: space['3'], alignItems: 'baseline' }}>
                <span style={{ ...text, flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.draft}</span>
                <Button size="sm" variant="tertiary" onClick={() => setResult(d)}>
                  Open
                </Button>
                <Button size="sm" variant="tertiary" style={{ color: c.error }} onClick={() => del.mutate(d.id, { onSuccess: () => result?.id === d.id && setResult(null) })}>
                  Delete
                </Button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}

function DraftView({ draft, onCopy }: { draft: EchoDraft; onCopy: () => void }) {
  const c = useColors();
  const small: React.CSSProperties = { fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted };
  return (
    <section data-result aria-label="Draft" style={{ marginTop: space['4'], display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <DraftEditor
        draft={draft}
        onCopy={onCopy}
        meta={
          <span style={small}>
            Sounds like you: {Math.round(draft.voice_match_score)}% · grounded {Math.round(draft.confidence * 100)}%
          </span>
        }
      />
      {draft.flags.includes('verbatim_removed') && (
        <p data-flag="verbatim_removed" style={{ ...small, margin: 0 }}>
          A sentence that repeated someone else's words was taken out.
        </p>
      )}
      {draft.citations.length > 0 && (
        <div style={small}>
          Drew on: {draft.citations.map((ct, i) => (
            <span key={i}>
              {i > 0 && ' · '}
              {ct.url ? (
                <a
                  href={ct.url}
                  target="_blank"
                  rel="noreferrer"
                  // An uploaded PDF is served behind the bearer header: opened as a blob URL (T-8.8.1.5).
                  onClick={(e) => openApiLink(e, ct.url, citedFileFailed)}
                  onAuxClick={(e) => openApiLink(e, ct.url, citedFileFailed)}
                  style={{ color: c.textSecondary }}
                >
                  {citationLabel(ct)}
                </a>
              ) : (
                citationLabel(ct)
              )}
            </span>
          ))}
        </div>
      )}
      {draft.deviation_notes.length > 0 && (
        <ul data-notes style={{ margin: 0, paddingLeft: space['5'], ...small }}>
          {draft.deviation_notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
