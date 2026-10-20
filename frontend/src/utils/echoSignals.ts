/**
 * Voice and personality signals (S-3.3.1): the closed vocabularies the
 * server enforces (`echo_signal_service.SIGNAL_TYPES`), in the panel's
 * order, with the words the panel shows for each.
 */
import type { LearnResponse, LearningState, VoiceSignal } from '../services/echoApi';

export type SignalLayer = 'style' | 'personality';

export interface SignalTypeMeta {
  type: string;
  layer: SignalLayer;
  label: string;
  hint: string;
}

export const SIGNAL_TYPES: SignalTypeMeta[] = [
  { type: 'vocabulary', layer: 'style', label: 'Words you reach for', hint: 'Words and phrases you use more than most people do.' },
  { type: 'cadence', layer: 'style', label: 'Rhythm', hint: 'How long your sentences run and how fast you move.' },
  { type: 'framing', layer: 'style', label: 'How you frame things', hint: 'How you open, argue and close.' },
  { type: 'recurring_reference', layer: 'style', label: 'References you return to', hint: 'Examples, people or analogies you bring up often.' },
  { type: 'formality_register', layer: 'style', label: 'Formality', hint: 'How formal you are by default.' },
  { type: 'register_per_audience', layer: 'style', label: 'Tone by audience', hint: 'How your tone shifts with who you are talking to.' },
  { type: 'trusted_conclusion', layer: 'personality', label: 'Conclusions you trust', hint: 'Things you have settled and build on.' },
  { type: 'preferred_solution', layer: 'personality', label: 'Solutions you prefer', hint: 'The kind of fix you reach for first.' },
  { type: 'recommendation_lens', layer: 'personality', label: 'How you recommend', hint: 'What you weigh when you recommend something.' },
  { type: 'apprehension', layer: 'personality', label: 'Worries', hint: 'What makes you wary.' },
  { type: 'methodology', layer: 'personality', label: 'How you work things out', hint: 'Your method for reaching a view.' },
  { type: 'topic_emphasis', layer: 'personality', label: 'What you emphasise', hint: 'Topics you give the most weight.' },
  { type: 'perception_lens', layer: 'personality', label: 'How you see things', hint: 'The lens you read events through.' },
  { type: 'interest', layer: 'personality', label: 'Interests', hint: 'What you keep coming back to.' },
];

export const LAYERS: { layer: SignalLayer; label: string; hint: string }[] = [
  { layer: 'style', label: 'How you write', hint: 'Style: the words, rhythm and framing that make something sound like you.' },
  { layer: 'personality', label: 'What you think', hint: 'Personality: the views, methods and worries behind what you say.' },
];

export const SIGNAL_LANGUAGES: { value: string; label: string }[] = [
  { value: 'en', label: 'English' },
  { value: 'hi-Deva', label: 'Hindi (Devanagari)' },
  { value: 'hi-Latn', label: 'Hindi (Roman script)' },
  { value: 'mixed', label: 'Mixed' },
];

export const SIGNAL_REGISTERS: { value: string; label: string }[] = [
  { value: 'intimate', label: 'Intimate' },
  { value: 'casual', label: 'Casual' },
  { value: 'professional', label: 'Professional' },
  { value: 'public', label: 'Public' },
];

const BY_TYPE = new Map(SIGNAL_TYPES.map((m) => [m.type, m]));

export function signalTypeMeta(type: string): SignalTypeMeta {
  return BY_TYPE.get(type) ?? { type, layer: 'personality', label: type, hint: '' };
}

export function languageLabel(value: string | null): string | null {
  return value ? (SIGNAL_LANGUAGES.find((l) => l.value === value)?.label ?? value) : null;
}

export function registerLabel(value: string | null): string | null {
  return value ? (SIGNAL_REGISTERS.find((r) => r.value === value)?.label ?? value) : null;
}

/** Where a signal's evidence came from, in words. Only the user's own
 * words ever feed a signal (D-089), so this list is closed too. */
export function sourceLabel(ref: string): string {
  if (ref === 'user') return 'you said so';
  const kind = ref.split(':', 1)[0];
  switch (kind) {
    case 'note':
      return 'a note';
    case 'share':
      return 'a share in your own words';
    case 'qa':
      return 'a question you asked';
    case 'library_qa':
      return 'a library question';
    case 'history_qa':
      return 'a history question';
    case 'event':
      return 'something you wrote elsewhere';
    default:
      return 'your writing';
  }
}

export function originLabel(origin: string, derivedFrom: string[] = []): string {
  switch (origin) {
    case 'user':
      return derivedFrom.some((ref) => ref !== 'user') ? 'You corrected this' : 'You added this';
    case 'stylometry':
      return 'Measured from your writing';
    default:
      return 'Learned from your writing';
  }
}

export interface LearningSummary {
  text: string;
  /** Whether "Learn now" has anything to do. */
  canLearn: boolean;
}

/** The learning line under the panel's intro (S-3.3.2). */
export function learningSummary(state: LearningState | null | undefined, formatDate: (iso: string) => string): LearningSummary | null {
  if (!state) return null;
  const off = state.mode === 'off' ? ' Automatic learning is off on this install.' : '';
  const last = state.last_learned_at ? ` Echo last learned on ${formatDate(state.last_learned_at)}.` : '';
  if (state.inputs === 0 && state.pending === 0) {
    return { text: `Echo learns from your notes, the questions you ask and shares you wrote. Write a note to start.${off}`, canLearn: false };
  }
  if (state.pending === 0) {
    const what = state.inputs === 1 ? 'your one text' : `all ${state.inputs} of your texts`;
    return { text: `Up to date: Echo has read ${what}.${last}${off}`, canLearn: false };
  }
  const waiting = state.pending === 1 ? '1 text is waiting to be read.' : `${state.pending} texts are waiting to be read.`;
  const auto =
    state.mode === 'off'
      ? ''
      : state.pending >= state.threshold
        ? ' Echo will read them shortly.'
        : ` Echo starts on its own once ${state.threshold} are waiting.`;
  return { text: `${waiting}${last}${auto}${off}`, canLearn: state.mode !== 'off' };
}

export function learnToast(status: LearnResponse['status']): { tone: 'success' | 'error'; text: string } {
  switch (status) {
    case 'queued':
      return { tone: 'success', text: 'Learning started. New signals appear here in a minute or two.' };
    case 'ran':
      return { tone: 'success', text: 'Echo has read your new writing.' };
    case 'waiting':
      return { tone: 'success', text: 'Nothing new to learn from yet.' };
    case 'off':
      return { tone: 'error', text: 'Automatic learning is off on this install.' };
    default:
      return { tone: 'error', text: 'Could not start learning. Try again.' };
  }
}

export interface SignalGroup {
  meta: SignalTypeMeta;
  items: VoiceSignal[];
}

/** Signals by layer, then by type in the vocabulary's order; empty types
 * are left out. The server already sorts each type by weight. */
export function groupSignals(items: VoiceSignal[]): Record<SignalLayer, SignalGroup[]> {
  const out: Record<SignalLayer, SignalGroup[]> = { style: [], personality: [] };
  for (const meta of SIGNAL_TYPES) {
    const rows = items.filter((s) => s.signal_type === meta.type);
    if (rows.length) out[meta.layer].push({ meta, items: rows });
  }
  return out;
}

/** Distinct evidence counts for the footer: "3 notes, 1 question". */
export function evidenceSummary(signal: Pick<VoiceSignal, 'derived_from'>): string {
  const counts = new Map<string, number>();
  for (const ref of signal.derived_from) {
    const label = sourceLabel(ref);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return [...counts.entries()].map(([label, n]) => (n === 1 ? label : `${n} × ${label}`)).join(', ');
}
