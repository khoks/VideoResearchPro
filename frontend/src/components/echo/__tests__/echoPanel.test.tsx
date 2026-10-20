/**
 * S-3.8.1: the Echo panel mounted the way AppLayout mounts it. Mod-Shift-E
 * opens it from anywhere (a text field included) and it says it is an AI;
 * readiness reads in words; Ask goes to the library or to past questions
 * through their own endpoints; "Draft as me" shows the gate (D-100) instead
 * of hiding, says when the feature has not shipped, and drafts once on;
 * Escape closes and gives focus back.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EchoBubble, EchoPanelHost } from '../EchoPanel';
import { useEchoPanelStore } from '../../../stores/echoPanelStore';
import type { DraftGate, DraftResponse, EchoCardsResponse, EchoStatus } from '../../../services/echoApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const STATUS: EchoStatus = {
  ready: false,
  total_rows: 40,
  distinct_sources: 1,
  has_personality_trait: false,
  threshold_total: 100,
  threshold_sources: 3,
};

const draftStatusMock = vi.fn<() => Promise<DraftGate>>();
const draftMock = vi.fn<(p: { message: string }) => Promise<DraftResponse>>();
const askLibraryMock = vi.fn();
const askHistoryMock = vi.fn();
const cardsMock = vi.fn<(context?: string) => Promise<EchoCardsResponse>>();
const dismissMock = vi.fn(async (_key: string) => ({ muted_kind: null }));
const actMock = vi.fn(async (_key: string) => undefined);
const shownMock = vi.fn(async (_key: string) => undefined);
const settingsMock = vi.fn(async (kinds: Record<string, boolean>) => ({ kinds }));
const suggestionsMock = vi.fn();
const feedbackMock = vi.fn(async (_b: unknown) => undefined);

vi.mock('../../../services/echoApi', async (orig) => ({
  ...(await orig<typeof import('../../../services/echoApi')>()),
  echoApi: {
    status: async () => STATUS,
    listConnectors: async () => ({ connectors: [] }),
    draftStatus: () => draftStatusMock(),
    draft: (p: { message: string }) => draftMock(p),
    cards: (context?: string) => cardsMock(context),
    dismissCard: (key: string) => dismissMock(key),
    actOnCard: (key: string) => actMock(key),
    cardShown: (key: string) => shownMock(key),
    setCardSettings: (kinds: Record<string, boolean>) => settingsMock(kinds),
    cardSettings: async () => ({ kinds: { saved_search: true, shares: true, questions: true } }),
  },
}));
vi.mock('../../../services/suggestionsApi', () => ({
  suggestionsApi: { get: (context: string) => suggestionsMock(context), feedback: (b: unknown) => feedbackMock(b) },
}));
vi.mock('../../../services/libraryQaApi', () => ({
  libraryQaApi: { ask: (d: unknown) => askLibraryMock(d), getHistory: async () => [], clarify: vi.fn() },
}));
vi.mock('../../../services/qaHistoryApi', () => ({
  qaHistoryApi: { postChat: (d: unknown) => askHistoryMock(d), getExchanges: async () => [] },
}));

function notFound() {
  return Object.assign(new Error('Not Found'), { response: { status: 404 } });
}

let host: HTMLDivElement;
let root: Root;

async function flush(n = 6) {
  for (let i = 0; i < n; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

function mount(path = '/library') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={[path]}>
          <input id="page-field" aria-label="a page field" />
          <EchoBubble />
          <EchoPanelHost />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

function press(key: string, mods: Record<string, boolean>, target: EventTarget) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...mods }));
  });
}

const panel = () => document.querySelector<HTMLElement>('#echo-panel');

function click(el: Element | null) {
  if (!el) throw new Error('element not found');
  act(() => {
    (el as HTMLElement).click();
  });
}

function buttonNamed(name: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll<HTMLButtonElement>('#echo-panel form button[type="submit"]')).find((b) => b.textContent?.trim() === name) ?? null;
}

async function typeInto(el: HTMLTextAreaElement, value: string) {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!;
    setter.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  useEchoPanelStore.setState({ open: false, mode: 'ask', target: 'library', turns: [] });
  draftStatusMock.mockReset();
  draftMock.mockReset();
  askLibraryMock.mockReset();
  askHistoryMock.mockReset();
  cardsMock.mockReset();
  cardsMock.mockResolvedValue({ cards: [], muted_kinds: [] });
  dismissMock.mockClear();
  actMock.mockClear();
  shownMock.mockClear();
  settingsMock.mockClear();
  suggestionsMock.mockReset();
  feedbackMock.mockClear();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('opening', () => {
  it('opens on Mod-Shift-E from inside a text field, says it is an AI and shows readiness in words', async () => {
    mount();
    const field = document.getElementById('page-field')!;
    field.focus();
    press('E', { ctrlKey: true, shiftKey: true }, field);
    await flush();
    const dialog = panel();
    expect(dialog?.getAttribute('role')).toBe('dialog');
    expect(document.activeElement?.getAttribute('aria-label')).toBe('Ask your library');
    expect(dialog?.textContent).toContain('You are talking to an AI');
    expect(dialog?.querySelector('[data-echo-readiness]')?.textContent).toContain(
      '24% ready. Still needs 60 more facts, 2 more sources and a personality trait.',
    );
  });

  it('closes on Escape and gives focus back to the bubble', async () => {
    mount();
    const bubble = document.querySelector<HTMLButtonElement>('.pratidhvani-echo-bubble')!;
    bubble.focus();
    click(bubble);
    await flush();
    expect(bubble.getAttribute('aria-expanded')).toBe('true');
    press('Escape', {}, panel()!.querySelector('textarea')!);
    await flush();
    expect(panel()).toBeNull();
    expect(document.activeElement).toBe(bubble);
  });
});

describe('ask', () => {
  it('asks the library through its own endpoint and shows the answer with its sources', async () => {
    askLibraryMock.mockResolvedValue({
      id: 'lq-1',
      question: 'What raises tariffs?',
      answer: 'Mostly **politics**.',
      references: [{ video_id: 'v1', title: 'Tariffs explained', timestamp: 0 }],
      created_at: '2026-10-20T00:00:00Z',
    });
    useEchoPanelStore.setState({ open: true });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'What raises tariffs?');
    click(buttonNamed('Ask'));
    await flush();
    expect(askLibraryMock).toHaveBeenCalledWith({ question: 'What raises tariffs?', answer_language: 'en' });
    const turn = panel()!.querySelector('[data-echo-turn="library"]')!;
    expect(turn.querySelector('strong')?.textContent).toBe('politics');
    expect(turn.textContent).toContain('Sources');
    expect(useEchoPanelStore.getState().turns[0].status).toBe('done');
  });

  it('asks past questions through the history chat', async () => {
    askHistoryMock.mockResolvedValue({
      id: 'h-1',
      question: 'What have I learned about tariffs?',
      answer: 'That they are taxes.',
      references: [{ source_type: 'library', exchange_id: 'lq-1', question_preview: 'What raises tariffs?', original_created_at: '' }],
      answer_language: 'en',
      created_at: '',
    });
    useEchoPanelStore.setState({ open: true, target: 'history' });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'What have I learned about tariffs?');
    click(buttonNamed('Ask'));
    await flush();
    expect(askHistoryMock).toHaveBeenCalledWith({ question: 'What have I learned about tariffs?' });
    expect(panel()!.querySelector('[data-echo-turn="history"]')?.textContent).toContain('Library Q&AWhat raises tariffs?');
  });

  it('says what went wrong when the answer fails', async () => {
    askLibraryMock.mockRejectedValue(Object.assign(new Error('quota'), { response: { status: 429 } }));
    useEchoPanelStore.setState({ open: true });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'Anything?');
    click(buttonNamed('Ask'));
    await flush();
    expect(panel()!.querySelector('[role="alert"]')?.textContent).toContain('today’s limit');
  });
});

describe('draft as me', () => {
  it('stays visible and says so when the feature has not shipped on this install', async () => {
    draftStatusMock.mockRejectedValue(notFound());
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    mount();
    await flush();
    const gate = panel()!.querySelector('[data-echo-gate]');
    expect(gate?.textContent).toContain('Not on this install yet');
    expect(panel()!.querySelector('textarea')).toBeNull();
  });

  it('shows the voice-test gate in words instead of hiding the feature', async () => {
    draftStatusMock.mockResolvedValue({ enabled: false, state: 'voice_test_needed', notes: 12, notes_needed: 40 });
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    mount();
    await flush();
    const gate = panel()!.querySelector('[data-echo-gate]')!;
    expect(gate.textContent).toContain('Your voice test comes first');
    expect(gate.textContent).toContain('You have 12 notes of the 40 the test needs.');
    expect(gate.querySelector('a')?.getAttribute('href')).toBe('/notes');
  });

  it('drafts once switched on, with the voice match, notes and disclosure', async () => {
    draftStatusMock.mockResolvedValue({ enabled: true, state: 'enabled' });
    draftMock.mockResolvedValue({
      id: 'd-1',
      draft: 'Happy to — Thursday works.',
      voice_match_score: 82,
      deviation_notes: ['Shorter than you usually write.'],
      flags: ['The message names a private person; nothing was added about them.'],
      citations: [
        { kind: 'fact', ref: 'F1', label: 'Works from Pune' },
        { kind: 'source', ref: 'S1', label: 'Tariffs explained', url: 'https://www.youtube.com/watch?v=v1&t=30' },
      ],
      disclosure: 'Drafted with Echo, reviewed by you.',
    });
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'Can we meet Thursday?');
    click(buttonNamed('Draft a reply'));
    await flush();
    expect(draftMock).toHaveBeenCalledWith({ message: 'Can we meet Thursday?' });
    const turn = panel()!.querySelector('[data-echo-turn="draft"]')!;
    expect(turn.textContent).toContain('Happy to — Thursday works.');
    expect(turn.textContent).toContain('Sounds like you: 82%');
    expect(turn.textContent).toContain('Shorter than you usually write.');
    expect(turn.querySelector('[data-echo-draft-flags]')?.textContent).toContain('names a private person');
    expect(turn.textContent).toContain('Drafted with Echo, reviewed by you.');
    expect(turn.textContent).toContain('F1 · what Echo knows about you');
    const source = Array.from(turn.querySelectorAll('a')).find((a) => a.textContent === 'S1 · Tariffs explained')!;
    expect(source.getAttribute('href')).toBe('https://www.youtube.com/watch?v=v1&t=30');
    expect(source.getAttribute('target')).toBe('_blank');
  });
});

describe('drafting through S-3.4.1', () => {
  it('asks before drafting about people the message names, then drafts on confirm', async () => {
    draftStatusMock.mockResolvedValue({ enabled: true, state: 'enabled' });
    draftMock
      .mockRejectedValueOnce(
        Object.assign(new Error('409'), {
          response: { status: 409, data: { detail: { code: 'names_need_confirmation', names: ['Asha Rao'], message: 'This message names someone who looks like a private person: Asha Rao. Confirm to draft.' } } },
        }),
      )
      .mockResolvedValue({ id: 'd-2', draft: 'Sure, tell Asha I said hello.' });
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'Asha Rao asked if you are free.');
    click(buttonNamed('Draft a reply'));
    await flush();
    const turn = () => panel()!.querySelector('[data-echo-turn="draft"]')!;
    expect(turn().textContent).toContain('looks like a private person: Asha Rao');
    click(Array.from(turn().querySelectorAll('button')).find((b) => b.textContent === 'Draft anyway')!);
    await flush();
    expect(draftMock).toHaveBeenLastCalledWith({ message: 'Asha Rao asked if you are free.', acknowledge_names: ['Asha Rao'] });
    expect(turn().textContent).toContain('Sure, tell Asha I said hello.');
  });

  it('shows the server’s own words when a draft is refused', async () => {
    draftStatusMock.mockResolvedValue({ enabled: true, state: 'enabled' });
    draftMock.mockRejectedValue(
      Object.assign(new Error('429'), { response: { status: 429, data: { detail: { code: 'daily_cap', message: 'You have used today’s 20 drafts. More tomorrow.' } } } }),
    );
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    mount();
    await flush();
    await typeInto(panel()!.querySelector('textarea')!, 'Hello?');
    click(buttonNamed('Draft a reply'));
    await flush();
    expect(panel()!.querySelector('[role="alert"]')?.textContent).toBe('You have used today’s 20 drafts. More tomorrow.');
  });
});

describe('anticipation cards (S-3.8.2)', () => {
  const CARDS: EchoCardsResponse = {
    cards: [
      { key: 'saved_search:n1', kind: 'saved_search', title: 'Your saved search changed', body: 'New sources.', href: '/saved-searches', action_label: 'See what changed' },
      { key: 'shares:s1', kind: 'shares', title: 'New in your shares inbox', body: '2 shares were read since you last looked.', href: '/echo/inbox', action_label: 'Open the inbox' },
      { key: 'questions:job:j-1', kind: 'questions', title: 'You might ask', context: 'job:j-1' },
    ],
    muted_kinds: [],
  };

  it('asks for the page in view and shows the cards above the empty conversation', async () => {
    cardsMock.mockResolvedValue(CARDS);
    suggestionsMock.mockResolvedValue({ context: 'job:j-1', suggestions: [{ question: 'Who disagrees?', rationale: '', source: 'generated', origin: null }], cached: true, generated: true });
    useEchoPanelStore.setState({ open: true });
    mount('/jobs/j-1');
    await flush();
    expect(cardsMock).toHaveBeenCalledWith('job:j-1');
    expect(suggestionsMock).toHaveBeenCalledWith('job:j-1');
    const kinds = Array.from(panel()!.querySelectorAll('[data-echo-card]')).map((el) => el.getAttribute('data-echo-card'));
    expect(kinds).toEqual(['saved_search', 'shares', 'questions']);
    expect(panel()!.textContent).toContain('2 shares were read since you last looked.');
    expect(shownMock).toHaveBeenCalledWith('questions:job:j-1');
  });

  it('does not count a questions card that has no questions', async () => {
    cardsMock.mockResolvedValue({ cards: [CARDS.cards[2]], muted_kinds: [] });
    suggestionsMock.mockResolvedValue({ context: 'job:j-1', suggestions: [], cached: true, generated: false });
    useEchoPanelStore.setState({ open: true });
    mount('/jobs/j-1');
    await flush();
    expect(panel()!.querySelector('[data-echo-card]')).toBeNull();
    expect(shownMock).not.toHaveBeenCalled();
  });

  it('puts a question in the Ask field, retires the card and records the fill', async () => {
    cardsMock.mockResolvedValue({ cards: [CARDS.cards[2]], muted_kinds: [] });
    suggestionsMock.mockResolvedValue({ context: 'job:j-1', suggestions: [{ question: 'Who disagrees?', rationale: '', source: 'history', origin: null }], cached: true, generated: false });
    useEchoPanelStore.setState({ open: true, mode: 'draft' });
    draftStatusMock.mockRejectedValue(notFound());
    mount('/jobs/j-1');
    await flush();
    const question = Array.from(panel()!.querySelectorAll('[data-echo-card="questions"] li button')).find((b) => b.textContent === 'Who disagrees?')!;
    click(question);
    await flush();
    expect(useEchoPanelStore.getState().mode).toBe('ask');
    expect(panel()!.querySelector('textarea')!.value).toBe('Who disagrees?');
    expect(actMock).toHaveBeenCalledWith('questions:job:j-1');
    expect(feedbackMock).toHaveBeenCalledWith({ context: 'job:j-1', question: 'Who disagrees?', action: 'fill', source: 'history' });
  });

  it('dismisses with x and asks again', async () => {
    cardsMock.mockResolvedValueOnce({ cards: [CARDS.cards[1]], muted_kinds: [] }).mockResolvedValue({ cards: [], muted_kinds: [] });
    useEchoPanelStore.setState({ open: true });
    mount();
    await flush();
    click(panel()!.querySelector('[aria-label="Dismiss: New in your shares inbox"]'));
    await flush();
    expect(dismissMock).toHaveBeenCalledWith('shares:s1');
    expect(cardsMock).toHaveBeenCalledTimes(2);
    expect(panel()!.querySelector('[data-echo-card]')).toBeNull();
  });

  it('steps aside once the conversation has started', async () => {
    cardsMock.mockResolvedValue(CARDS);
    useEchoPanelStore.setState({ open: true, turns: [{ id: 't', kind: 'library', text: 'q', status: 'pending' }] });
    mount();
    await flush();
    expect(cardsMock).not.toHaveBeenCalled();
    expect(panel()!.querySelector('[data-echo-cards]')).toBeNull();
  });

  it('says once when the dismissal rule turned a kind off, and turns it back on', async () => {
    cardsMock.mockResolvedValue({ cards: [], muted_kinds: ['questions'], notice: 'You dismissed 3 of these, so question cards are off. You can turn them back on.', notice_kind: 'questions' });
    useEchoPanelStore.setState({ open: true });
    mount();
    await flush();
    const status = panel()!.querySelector('[data-echo-cards] [role="status"]')!;
    expect(status.textContent).toContain('question cards are off');
    click(Array.from(status.querySelectorAll('button')).find((b) => b.textContent === 'Turn back on')!);
    await flush();
    expect(settingsMock).toHaveBeenCalledWith({ questions: true });
  });
});
