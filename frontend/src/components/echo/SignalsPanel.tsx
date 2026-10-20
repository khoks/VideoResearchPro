import { useState } from 'react';
import { useCreateSignal, useRejectSignal, useUpdateSignal, useVoiceSignals } from '../../hooks/useEcho';
import { useJobStore } from '../../stores/jobStore';
import { echoApi, type VoiceSignal } from '../../services/echoApi';
import { Badge, Button, Card, FormField, Modal, Select, Skeleton, Textarea } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import {
  LAYERS,
  SIGNAL_LANGUAGES,
  SIGNAL_REGISTERS,
  SIGNAL_TYPES,
  evidenceSummary,
  groupSignals,
  languageLabel,
  originLabel,
  registerLabel,
  signalTypeMeta,
  sourceLabel,
  type SignalGroup,
  type SignalLayer,
} from '../../utils/echoSignals';
import { detailFromErrorBody, type HttpErrorLike } from '../../utils/ingestResults';

interface FormState {
  mode: 'create' | 'edit';
  id?: string;
  signal_type: string;
  value: string;
  language: string;
  register: string;
}

/**
 * "How you sound" (S-3.3.1): what Echo has learned about the user's style
 * and personality, as rows they can read, correct, add to and reject.
 * "That's not me" is a tombstone on the server: the signal leaves the list
 * and extraction never writes it again.
 */
export function SignalsPanel() {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const signals = useVoiceSignals();
  const create = useCreateSignal();
  const update = useUpdateSignal();
  const reject = useRejectSignal();
  const [form, setForm] = useState<FormState | null>(null);
  const [rejecting, setRejecting] = useState<VoiceSignal | null>(null);
  const [exporting, setExporting] = useState(false);

  const items = signals.data?.items ?? [];
  const groups = groupSignals(items);
  const text: React.CSSProperties = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal };

  const failed = (err: unknown, fallback: string) =>
    pushToast('error', detailFromErrorBody((err as HttpErrorLike).response?.data) ?? fallback);

  const submit = (state: FormState) => {
    const language = state.language || null;
    const register = state.register || null;
    if (state.mode === 'create') {
      create.mutate(
        { signal_type: state.signal_type, value: state.value.trim(), language, register },
        { onSuccess: () => setForm(null), onError: (e) => failed(e, 'Could not add the signal.') },
      );
    } else if (state.id) {
      update.mutate(
        { id: state.id, payload: { value: state.value.trim(), language, register } },
        { onSuccess: () => setForm(null), onError: (e) => failed(e, 'Could not save the signal.') },
      );
    }
  };

  const confirmReject = () => {
    if (!rejecting) return;
    reject.mutate(rejecting.id, {
      onSuccess: () => {
        setRejecting(null);
        pushToast('success', 'Forgotten. Echo will not learn that again.');
      },
      onError: (e) => failed(e, 'Could not remove the signal.'),
    });
  };

  const doExport = async () => {
    setExporting(true);
    try {
      await echoApi.exportSignals();
    } catch {
      pushToast('error', 'Export failed; try again.');
    } finally {
      setExporting(false);
    }
  };

  const openCreate = (layer: SignalLayer) =>
    setForm({ mode: 'create', signal_type: SIGNAL_TYPES.find((t) => t.layer === layer)!.type, value: '', language: '', register: '' });

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], flexWrap: 'wrap', marginBottom: space['2'] }}>
        <h2 style={{ margin: 0, flex: 1, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          How you sound
        </h2>
        <Button size="sm" variant="secondary" onClick={doExport} loading={exporting} disabled={!items.length}>
          Export voice profile
        </Button>
      </div>
      <p style={text}>
        What Echo has learned about how you write and what you think. It learns only from your own words: your notes, the
        questions you ask, and shares you marked as written by you. Correct anything that is off. "That's not me" removes a
        signal, and Echo never learns it again.
      </p>

      {signals.isLoading ? (
        <div style={{ marginTop: space['3'] }}>
          <Skeleton variant="text" />
        </div>
      ) : signals.isError ? (
        <div style={{ marginTop: space['3'], display: 'flex', gap: space['3'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
          <span>Couldn't load your signals.</span>
          <Button size="sm" variant="tertiary" onClick={() => signals.refetch()}>
            Retry
          </Button>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: space['4'], marginTop: space['4'] }}>
          {LAYERS.map((layer) => (
            <LayerSection
              key={layer.layer}
              label={layer.label}
              hint={layer.hint}
              groups={groups[layer.layer]}
              onAdd={() => openCreate(layer.layer)}
              onEdit={(s) =>
                setForm({ mode: 'edit', id: s.id, signal_type: s.signal_type, value: s.value, language: s.language ?? '', register: s.register ?? '' })
              }
              onReject={setRejecting}
            />
          ))}
        </div>
      )}

      <p style={{ ...text, marginTop: space['3'], fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        Learning terms version {signals.data?.consent_version ?? '…'}. Shares you did not write never shape these signals.
      </p>

      {form && (
        <SignalFormModal
          state={form}
          pending={create.isPending || update.isPending}
          onClose={() => setForm(null)}
          onSubmit={submit}
        />
      )}

      <Modal
        open={rejecting !== null}
        onClose={() => setRejecting(null)}
        title="That's not you?"
        footer={
          <>
            <Button variant="secondary" onClick={() => setRejecting(null)}>
              Keep it
            </Button>
            <Button variant="danger" loading={reject.isPending} onClick={confirmReject}>
              That's not me
            </Button>
          </>
        }
      >
        <p style={{ margin: 0, fontFamily: fonts.body, lineHeight: lineHeight.normal }}>
          Echo will forget “{rejecting?.value}” under {rejecting ? signalTypeMeta(rejecting.signal_type).label.toLowerCase() : ''} and
          will not learn it again from anything you write. The notes and shares it came from are kept.
        </p>
      </Modal>
    </Card>
  );
}

function LayerSection({
  label,
  hint,
  groups,
  onAdd,
  onEdit,
  onReject,
}: {
  label: string;
  hint: string;
  groups: SignalGroup[];
  onAdd: () => void;
  onEdit: (s: VoiceSignal) => void;
  onReject: (s: VoiceSignal) => void;
}) {
  const c = useColors();
  return (
    <section>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'], marginBottom: space['2'] }}>
        <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.md, fontWeight: fontWeight.semibold, color: c.textPrimary }}>{label}</h3>
        <span style={{ flex: 1, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>{hint}</span>
        <Button size="sm" variant="tertiary" onClick={onAdd}>
          Add
        </Button>
      </div>
      {groups.length === 0 ? (
        <p style={{ margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textMuted, fontStyle: 'italic' }}>
          Nothing learned yet. Signals appear as Echo reads your notes and questions, or add one yourself.
        </p>
      ) : (
        <Card flush>
          {groups.map((g, gi) => (
            <div key={g.meta.type} style={{ borderBottom: gi === groups.length - 1 ? 'none' : `1px solid ${c.border}` }}>
              <div style={{ padding: `${space['2']} ${space['4']} 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.textSecondary }}>
                {g.meta.label}
              </div>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {g.items.map((s) => (
                  <SignalRow key={s.id} signal={s} onEdit={() => onEdit(s)} onReject={() => onReject(s)} />
                ))}
              </ul>
            </div>
          ))}
        </Card>
      )}
    </section>
  );
}

function SignalRow({ signal, onEdit, onReject }: { signal: VoiceSignal; onEdit: () => void; onReject: () => void }) {
  const c = useColors();
  const language = languageLabel(signal.language);
  const register = registerLabel(signal.register);
  const evidence = evidenceSummary(signal);
  return (
    <li data-signal={signal.id} style={{ padding: `${space['2']} ${space['4']} ${space['3']}`, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: space['3'] }}>
        <span style={{ flex: 1, minWidth: 0, fontFamily: fonts.body, fontSize: fontSize.base, color: c.textPrimary, lineHeight: lineHeight.normal }}>
          {signal.value}
        </span>
        <Button size="sm" variant="tertiary" onClick={onEdit}>
          Edit
        </Button>
        <Button size="sm" variant="tertiary" style={{ color: c.error }} onClick={onReject}>
          That's not me
        </Button>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap', fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
        {language && <Badge size="sm">{language}</Badge>}
        {register && <Badge size="sm">{register}</Badge>}
        <span>{originLabel(signal.origin)}</span>
        {evidence && signal.origin !== 'user' && (
          <>
            <span aria-hidden>·</span>
            <span>from {evidence}</span>
          </>
        )}
      </div>
      {signal.examples.length > 0 && (
        <details>
          <summary style={{ cursor: 'pointer', fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
            {signal.examples.length === 1 ? '1 example' : `${signal.examples.length} examples`}
          </summary>
          <ul style={{ margin: `${space['1']} 0 0`, paddingLeft: space['5'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            {signal.examples.map((e, i) => (
              <li key={i} style={{ fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
                “{e.text}” <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>({sourceLabel(e.source)})</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

function SignalFormModal({
  state: initial,
  pending,
  onClose,
  onSubmit,
}: {
  state: FormState;
  pending: boolean;
  onClose: () => void;
  onSubmit: (state: FormState) => void;
}) {
  const [state, setState] = useState<FormState>(initial);
  const meta = signalTypeMeta(state.signal_type);
  const canSubmit = state.value.trim().length > 0 && state.value.trim().length <= 500 && !pending;
  return (
    <Modal
      open
      onClose={onClose}
      title={state.mode === 'edit' ? 'Correct this signal' : 'Add a signal'}
      maxWidth={560}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => canSubmit && onSubmit(state)} disabled={!canSubmit} loading={pending}>
            {state.mode === 'edit' ? 'Save' : 'Add'}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSubmit) onSubmit(state);
        }}
        style={{ display: 'flex', flexDirection: 'column', gap: space['4'] }}
      >
        <FormField label="Kind" helperText={state.mode === 'edit' ? 'The kind is fixed; add a new signal for a different one.' : meta.hint}>
          {(id) => (
            <Select id={id} value={state.signal_type} disabled={state.mode === 'edit'} onChange={(e) => setState({ ...state, signal_type: e.target.value })}>
              {LAYERS.map((layer) => (
                <optgroup key={layer.layer} label={layer.label}>
                  {SIGNAL_TYPES.filter((t) => t.layer === layer.layer).map((t) => (
                    <option key={t.type} value={t.type}>
                      {t.label}
                    </option>
                  ))}
                </optgroup>
              ))}
            </Select>
          )}
        </FormField>
        <FormField label="In your words" required>
          {(id) => (
            <Textarea
              id={id}
              rows={3}
              maxLength={500}
              value={state.value}
              onChange={(e) => setState({ ...state, value: e.target.value })}
              placeholder="e.g. I start from incentives before I look at intentions."
              style={{ fontFamily: fonts.body }}
              autoFocus
            />
          )}
        </FormField>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: space['3'] }}>
          <FormField label="Language" optional>
            {(id) => (
              <Select id={id} value={state.language} onChange={(e) => setState({ ...state, language: e.target.value })}>
                <option value="">Any language</option>
                {SIGNAL_LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            )}
          </FormField>
          <FormField label="Audience" optional>
            {(id) => (
              <Select id={id} value={state.register} onChange={(e) => setState({ ...state, register: e.target.value })}>
                <option value="">Any audience</option>
                {SIGNAL_REGISTERS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </Select>
            )}
          </FormField>
        </div>
      </form>
    </Modal>
  );
}
