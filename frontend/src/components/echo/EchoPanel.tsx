/**
 * The always-evokable Echo surface (S-3.8.1, E-3.8): a bubble on every page
 * for Studio users, a panel it opens, and Mod-Shift-E (plus "Ask Echo" in the
 * palette) to open it from anywhere.
 *
 * The panel says it is an AI (EU AI Act Art. 50(1) applies to a
 * conversational surface from 2026-08-02), shows readiness in words, and
 * holds two modes:
 * - **Ask**, over the library or over the user's past questions, through the
 *   same endpoints as the library Q&A and Q&A history pages, so quota, the
 *   Q&A index and history all work as they do there;
 * - **Draft as me** (S-3.4.1). Per D-100 it is switched on per user only
 *   after their voice test passes, so the panel shows that gate in words
 *   instead of hiding the feature.
 *
 * Desktop: a floating bubble at the bottom right, and the panel above it,
 * non-modal. Phones and narrow windows (under 960 px): the bubble moves into
 * the top bar, so it never covers the docked Q&A composer (S-8.12.1), and the
 * panel fills the screen.
 */
import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { CitationLink } from '../citation';
import { Badge, Button, Spinner, Textarea } from '../primitives';
import { useAskLibraryQA } from '../../hooks/useLibraryQA';
import { useAskQAHistoryChat } from '../../hooks/useQAHistoryChat';
import { useEchoConnectors, useEchoStatus } from '../../hooks/useEcho';
import { useFeatureAvailable } from '../../hooks/useFeatureAvailable';
import { isMacPlatform, useShortcuts } from '../../hooks/useShortcuts';
import { useColors, useShadows } from '../../hooks/useTheme';
import { echoApi, type DraftResponse, type EchoCard } from '../../services/echoApi';
import { suggestionsApi, type SuggestionContext } from '../../services/suggestionsApi';
import { useEchoPanelStore, type AskTarget, type EchoTurn } from '../../stores/echoPanelStore';
import { fonts, fontSize, fontWeight, lineHeight, radius, space, target as touch, z } from '../../theme';
import type { LibraryQAExchange, QAHistoryExchange } from '../../types/qa';
import { computeReadiness } from '../../utils/echoReadiness';
import { draftErrorOf } from '../../utils/echoDrafts';
import {
  CARD_KIND_LABELS,
  ECHO_SHORTCUT,
  cardContext,
  draftGateView,
  historyRefHref,
  historyRefLabel,
  readinessLine,
  requestErrorLine,
  shortcutLabel,
  voiceMatchLine,
} from '../../utils/echoPanel';

const PANEL_ID = 'echo-panel';
const TITLE_ID = 'echo-panel-title';

let turnSeq = 0;
function nextTurnId(): string {
  turnSeq += 1;
  return `turn-${Date.now()}-${turnSeq}`;
}

// ---------------------------------------------------------------------------
// Openers
// ---------------------------------------------------------------------------

/** The floating bubble (desktop). Hidden under 960 px by index.css. */
export function EchoBubble() {
  const c = useColors();
  const s = useShadows();
  const open = useEchoPanelStore((st) => st.open);
  const toggle = useEchoPanelStore((st) => st.toggle);
  return (
    <button
      type="button"
      className="pratidhvani-echo-bubble"
      data-echo-opener=""
      onClick={toggle}
      aria-expanded={open}
      aria-controls={PANEL_ID}
      aria-haspopup="dialog"
      title={`Echo (${shortcutLabel(isMacPlatform())})`}
      style={{
        position: 'fixed',
        right: space['6'],
        bottom: `calc(${space['6']} + env(safe-area-inset-bottom, 0px))`,
        zIndex: z.drawer,
        height: 52,
        minWidth: 52,
        padding: `0 ${space['4']}`,
        display: 'flex',
        alignItems: 'center',
        gap: space['2'],
        borderRadius: 999,
        border: `1px solid ${c.accent}`,
        background: open ? c.accent : c.surface,
        color: open ? c.surface : c.accent,
        boxShadow: s.floating,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        fontWeight: fontWeight.semibold,
        cursor: 'pointer',
      }}
    >
      <span aria-hidden style={{ fontFamily: fonts.display, fontSize: fontSize.lg }}>ध्व</span>
      Echo
    </button>
  );
}

/** The phone and narrow-window opener, in the top bar: 44 px. */
export function EchoHeaderButton() {
  const c = useColors();
  const open = useEchoPanelStore((st) => st.open);
  const toggle = useEchoPanelStore((st) => st.toggle);
  return (
    <button
      type="button"
      data-echo-opener=""
      onClick={toggle}
      aria-expanded={open}
      aria-controls={PANEL_ID}
      aria-haspopup="dialog"
      aria-label="Echo"
      style={{
        width: touch.primary,
        height: touch.primary,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        border: 'none',
        borderRadius: radius.md,
        background: open ? c.accentSubtle : 'transparent',
        color: c.accent,
        fontFamily: fonts.display,
        fontSize: fontSize.md,
        cursor: 'pointer',
      }}
    >
      <span aria-hidden>ध्व</span>
    </button>
  );
}

/** Mounted once in AppLayout for Studio users: the shortcut and the panel. */
export function EchoPanelHost() {
  const open = useEchoPanelStore((st) => st.open);
  const toggle = useEchoPanelStore((st) => st.toggle);
  // A chord with modifiers, so it works from inside a text field too.
  useShortcuts([{ keys: ECHO_SHORTCUT, run: toggle, allowInInputs: true }]);
  if (!open) return null;
  return createPortal(<EchoPanel />, document.body);
}

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function EchoPanel() {
  const c = useColors();
  const s = useShadows();
  const setOpen = useEchoPanelStore((st) => st.setOpen);
  const mode = useEchoPanelStore((st) => st.mode);
  const setMode = useEchoPanelStore((st) => st.setMode);
  const turns = useEchoPanelStore((st) => st.turns);
  const clearTurns = useEchoPanelStore((st) => st.clearTurns);
  const panelRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);
  const location = useLocation();

  // Focus moves in on open and back to where it was on close. On a wide
  // screen it lands in the composer; on a phone on the close button, so the
  // keyboard does not cover the panel before the user has read it.
  useEffect(() => {
    opener.current = (document.activeElement as HTMLElement | null) ?? null;
    const narrow = window.matchMedia?.('(max-width: 959px)').matches ?? false;
    const panel = panelRef.current;
    const target = (!narrow && panel?.querySelector<HTMLElement>('textarea')) || panel?.querySelector<HTMLElement>('[data-echo-first]');
    target?.focus();
    return () => {
      const back = opener.current;
      if (back && document.contains(back)) back.focus();
      else document.querySelector<HTMLElement>('[data-echo-opener]')?.focus();
    };
  }, []);

  // Following a link out of the panel closes it on phones, where it covers
  // the page; on desktop it stays open beside the page.
  const firstPath = useRef(location.pathname);
  useEffect(() => {
    if (location.pathname !== firstPath.current && window.matchMedia?.('(max-width: 959px)').matches) setOpen(false);
  }, [location.pathname, setOpen]);

  const onKeyDown = (e: ReactKeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Escape') {
      e.stopPropagation();
      setOpen(false);
      return;
    }
    if (e.key !== 'Tab' || !panelRef.current) return;
    const items = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  };

  return (
    <div
      id={PANEL_ID}
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-labelledby={TITLE_ID}
      className="pratidhvani-echo-panel"
      onKeyDown={onKeyDown}
      style={{
        position: 'fixed',
        right: space['6'],
        bottom: `calc(${space['6']} + 64px + env(safe-area-inset-bottom, 0px))`,
        width: 'min(420px, calc(100vw - 32px))',
        height: 'min(640px, calc(100dvh - 128px))',
        zIndex: z.drawer,
        display: 'flex',
        flexDirection: 'column',
        background: c.surface,
        color: c.textPrimary,
        border: `1px solid ${c.border}`,
        borderRadius: radius.lg,
        boxShadow: s.floating,
        overflow: 'hidden',
      }}
    >
      <header style={{ padding: `${space['3']} ${space['4']}`, borderBottom: `1px solid ${c.border}` }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: space['2'] }}>
          <h2 id={TITLE_ID} style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold }}>
            Echo
          </h2>
          <Badge tone="neutral" size="sm">AI</Badge>
          <span style={{ flex: 1 }} />
          {turns.length > 0 && (
            <Button size="sm" variant="tertiary" onClick={clearTurns}>
              Clear
            </Button>
          )}
          <button
            type="button"
            aria-label="Close Echo"
            data-echo-first=""
            onClick={() => setOpen(false)}
            style={{
              width: 36,
              height: 36,
              border: 'none',
              borderRadius: radius.md,
              background: 'transparent',
              color: c.textSecondary,
              fontSize: fontSize.lg,
              cursor: 'pointer',
            }}
          >
            ×
          </button>
        </div>
        <p style={{ margin: `${space['1']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, lineHeight: lineHeight.normal }}>
          You are talking to an AI. It answers from your library, notes and past questions, and can be wrong: check what it cites.
        </p>
        <ReadinessStrip />
        <div role="tablist" aria-label="Echo mode" style={{ display: 'flex', gap: space['1'], marginTop: space['3'] }}>
          <ModeTab id="ask" label="Ask" active={mode === 'ask'} onSelect={() => setMode('ask')} />
          <ModeTab id="draft" label="Draft as me" active={mode === 'draft'} onSelect={() => setMode('draft')} />
        </div>
      </header>

      <div style={{ flex: 1, minHeight: 0, overflowY: 'auto', padding: space['4'] }} aria-live="polite">
        {turns.length === 0 ? (
          <>
            {/* S-3.8.2: only here, only while the conversation is empty. */}
            <AnticipationCards />
            <EmptyThread mode={mode} />
          </>
        ) : (
          <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['4'] }}>
            {turns.map((t) => (
              <li key={t.id}>
                <TurnView turn={t} />
              </li>
            ))}
          </ol>
        )}
      </div>

      <div role="tabpanel" aria-label={mode === 'ask' ? 'Ask' : 'Draft as me'} style={{ borderTop: `1px solid ${c.border}`, padding: space['3'] }}>
        {mode === 'ask' ? <AskComposer /> : <DraftComposer />}
      </div>
    </div>
  );
}

function ModeTab({ id, label, active, onSelect }: { id: string; label: string; active: boolean; onSelect: () => void }) {
  const c = useColors();
  return (
    <button
      type="button"
      role="tab"
      id={`echo-tab-${id}`}
      aria-selected={active}
      onClick={onSelect}
      style={{
        padding: `${space['1']} ${space['3']}`,
        minHeight: 32,
        borderRadius: 999,
        border: `1px solid ${active ? c.accent : c.border}`,
        background: active ? c.accentSubtle : 'transparent',
        color: active ? c.accent : c.textSecondary,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        fontWeight: active ? fontWeight.semibold : fontWeight.medium,
        cursor: 'pointer',
      }}
    >
      {label}
    </button>
  );
}

function ReadinessStrip() {
  const c = useColors();
  const status = useEchoStatus();
  const connectors = useEchoConnectors();
  if (!status.data) return null;
  const readiness = computeReadiness(status.data, connectors.data?.connectors.length ?? 0);
  return (
    <p data-echo-readiness="" style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: readiness.ready ? c.forest : c.textPrimary }}>
      {readinessLine(readiness)}{' '}
      {!readiness.ready && (
        <Link to="/echo" style={{ color: c.accent }}>
          What counts
        </Link>
      )}
    </p>
  );
}

function EmptyThread({ mode }: { mode: 'ask' | 'draft' }) {
  const c = useColors();
  const style = { margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.loose };
  return mode === 'ask' ? (
    <p style={style}>
      Ask anything your library can answer, or ask about your own past questions: “What have I learned about tariffs?”
      Answers are saved with the rest of your Q&A.
    </p>
  ) : (
    <p style={style}>Paste a message you want to answer, and Echo drafts a reply in your voice. It is a draft: nothing is sent.</p>
  );
}

// ---------------------------------------------------------------------------
// Anticipation cards (S-3.8.2)
// ---------------------------------------------------------------------------

/**
 * One-line next steps, shown only in the open panel and only before the
 * first message. How often they show and what dismissing does are
 * pre-registered (docs/notes/2026-10-20-anticipation-cards-preregistration.md)
 * and enforced by the server; the panel renders what it is given.
 */
function AnticipationCards() {
  const c = useColors();
  const location = useLocation();
  const qc = useQueryClient();
  const context = cardContext(location.pathname);
  const cards = useQuery({
    queryKey: ['echo', 'cards', context],
    queryFn: () => echoApi.cards(context),
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ['echo', 'cards'] });

  if (!cards.data) return null;
  const { cards: list, notice, notice_kind, muted_kinds } = cards.data;
  if (!list.length && !notice && !muted_kinds.length) return null;

  const dismiss = async (key: string) => {
    await echoApi.dismissCard(key).catch(() => undefined);
    void refresh();
  };
  const act = (key: string) => {
    void echoApi
      .actOnCard(key)
      .catch(() => undefined)
      .then(refresh);
  };

  return (
    <section aria-label="Suggestions from Echo" data-echo-cards="" style={{ display: 'flex', flexDirection: 'column', gap: space['2'], marginBottom: space['4'] }}>
      {notice && (
        <p role="status" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
          {notice}{' '}
          {notice_kind && (
            <button
              type="button"
              onClick={async () => {
                await echoApi.setCardSettings({ [notice_kind]: true }).catch(() => undefined);
                void refresh();
              }}
              style={linkButton(c.accent)}
            >
              Turn back on
            </button>
          )}
        </p>
      )}
      {list.map((card) =>
        card.kind === 'questions' ? (
          <QuestionsCard key={card.key} card={card} onAct={act} onDismiss={dismiss} />
        ) : (
          <LinkCard key={card.key} card={card} onAct={act} onDismiss={dismiss} />
        ),
      )}
      <button type="button" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((v) => !v)} style={{ ...linkButton(c.textMuted), alignSelf: 'flex-start' }}>
        Card settings
      </button>
      {settingsOpen && <CardSettings onChange={refresh} />}
    </section>
  );
}

function linkButton(color: string) {
  return {
    border: 'none',
    background: 'transparent',
    padding: 0,
    color,
    fontFamily: fonts.ui,
    fontSize: fontSize.xs,
    cursor: 'pointer',
    textDecoration: 'underline',
  } as const;
}

function CardFrame({ card, onDismiss, children }: { card: EchoCard; onDismiss: (key: string) => void; children: ReactNode }) {
  const c = useColors();
  return (
    <div
      data-echo-card={card.kind}
      style={{ position: 'relative', padding: `${space['2']} ${space['8']} ${space['2']} ${space['3']}`, border: `1px solid ${c.border}`, borderRadius: radius.md, background: c.bg }}
    >
      <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>{card.title}</p>
      {children}
      <button
        type="button"
        aria-label={`Dismiss: ${card.title}`}
        onClick={() => onDismiss(card.key)}
        style={{ position: 'absolute', top: 2, right: 2, width: 32, height: 32, border: 'none', background: 'transparent', color: c.textMuted, cursor: 'pointer', fontSize: fontSize.md }}
      >
        ×
      </button>
    </div>
  );
}

function LinkCard({ card, onAct, onDismiss }: { card: EchoCard; onAct: (key: string) => void; onDismiss: (key: string) => void }) {
  const c = useColors();
  const navigate = useNavigate();
  return (
    <CardFrame card={card} onDismiss={onDismiss}>
      {card.body && <p style={{ margin: `${space['1']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>{card.body}</p>}
      {card.href && (
        <button
          type="button"
          onClick={() => {
            onAct(card.key);
            navigate(card.href!);
          }}
          style={{ ...linkButton(c.accent), marginTop: space['1'], textDecoration: 'none' }}
        >
          {card.action_label ?? 'Open'} →
        </button>
      )}
    </CardFrame>
  );
}

function QuestionsCard({ card, onAct, onDismiss }: { card: EchoCard; onAct: (key: string) => void; onDismiss: (key: string) => void }) {
  const c = useColors();
  const setAskText = useEchoPanelStore((st) => st.setAskText);
  const setMode = useEchoPanelStore((st) => st.setMode);
  const setTarget = useEchoPanelStore((st) => st.setTarget);
  const context = (card.context ?? 'library') as SuggestionContext;
  const suggestions = useQuery({
    queryKey: ['suggestions', context],
    queryFn: ({ signal }) => suggestionsApi.get(context, signal),
    staleTime: 5 * 60_000,
    retry: false,
  });
  const items = (suggestions.data?.suggestions ?? []).slice(0, 3);
  // Counted as shown only once a question is on screen (the pre-registered
  // reading must not count empty cards).
  const shown = items.length > 0;
  useEffect(() => {
    if (shown) void echoApi.cardShown(card.key).catch(() => undefined);
  }, [shown, card.key]);
  if (!items.length) return null;
  return (
    <CardFrame card={card} onDismiss={onDismiss}>
      <ul style={{ listStyle: 'none', margin: `${space['1']} 0 0`, padding: 0, display: 'flex', flexDirection: 'column', gap: space['1'] }}>
        {items.map((s) => (
          <li key={s.question}>
            <button
              type="button"
              onClick={() => {
                setMode('ask');
                setTarget('library');
                setAskText(s.question);
                onAct(card.key);
                void suggestionsApi.feedback({ context, question: s.question, action: 'fill', source: s.source }).catch(() => undefined);
                requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('#echo-panel textarea')?.focus());
              }}
              style={{ border: 'none', background: 'transparent', padding: 0, textAlign: 'left', color: c.accent, fontFamily: fonts.body, fontSize: fontSize.sm, cursor: 'pointer' }}
            >
              {s.question}
            </button>
          </li>
        ))}
      </ul>
    </CardFrame>
  );
}

function CardSettings({ onChange }: { onChange: () => void }) {
  const c = useColors();
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ['echo', 'card-settings'], queryFn: () => echoApi.cardSettings() });
  if (!settings.data) return null;
  return (
    <fieldset style={{ border: `1px solid ${c.border}`, borderRadius: radius.md, margin: 0, padding: space['2'] }}>
      <legend style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>Show cards for</legend>
      {Object.entries(settings.data.kinds).map(([kind, on]) => (
        <label key={kind} style={{ display: 'flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textPrimary }}>
          <input
            type="checkbox"
            checked={on}
            onChange={async (e) => {
              const next = await echoApi.setCardSettings({ [kind]: e.target.checked }).catch(() => null);
              if (next) qc.setQueryData(['echo', 'card-settings'], next);
              onChange();
            }}
            style={{ accentColor: c.accent }}
          />
          {CARD_KIND_LABELS[kind] ?? kind}
        </label>
      ))}
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------

function AskComposer() {
  const c = useColors();
  const target = useEchoPanelStore((st) => st.target);
  const setTarget = useEchoPanelStore((st) => st.setTarget);
  const addTurn = useEchoPanelStore((st) => st.addTurn);
  const updateTurn = useEchoPanelStore((st) => st.updateTurn);
  const askLibrary = useAskLibraryQA();
  const askHistory = useAskQAHistoryChat();
  const libraryUp = useFeatureAvailable('library_qa');
  const historyUp = useFeatureAvailable('qa_history');
  const text = useEchoPanelStore((st) => st.askText);
  const setText = useEchoPanelStore((st) => st.setAskText);

  const available = target === 'library' ? libraryUp : historyUp;
  const busy = askLibrary.isPending || askHistory.isPending;

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    const question = text.trim();
    if (!question || busy || !available) return;
    const id = nextTurnId();
    addTurn({ id, kind: target, text: question, status: 'pending' });
    setText('');
    try {
      const result =
        target === 'library'
          ? await askLibrary.mutateAsync({ question, answer_language: 'en' })
          : await askHistory.mutateAsync({ question });
      updateTurn(id, { status: 'done', result });
    } catch (err) {
      updateTurn(id, { status: 'error', error: requestErrorLine(err) });
    }
  };

  return (
    <form onSubmit={submit}>
      <fieldset style={{ border: 'none', margin: `0 0 ${space['2']}`, padding: 0, display: 'flex', gap: space['3'], flexWrap: 'wrap' }}>
        <legend style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>Ask over</legend>
        <TargetOption value="library" current={target} onPick={setTarget} label="My library" />
        <TargetOption value="history" current={target} onPick={setTarget} label="My past questions" />
      </fieldset>
      <Textarea
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void submit();
          }
        }}
        aria-label={target === 'library' ? 'Ask your library' : 'Ask about your past questions'}
        placeholder={target === 'library' ? 'Ask your library…' : 'Ask about what you have asked before…'}
        style={{ fontSize: 16 }}
      />
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], marginTop: space['2'] }}>
        {!available && (
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>The model for this is down right now.</span>
        )}
        <span style={{ flex: 1 }} />
        <Button type="submit" size="sm" loading={busy} disabled={!text.trim() || busy || !available}>
          Ask
        </Button>
      </div>
    </form>
  );
}

function TargetOption({ value, current, onPick, label }: { value: AskTarget; current: AskTarget; onPick: (t: AskTarget) => void; label: string }) {
  const c = useColors();
  return (
    <label style={{ display: 'flex', alignItems: 'center', gap: space['1'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary, cursor: 'pointer' }}>
      <input type="radio" name="echo-ask-target" value={value} checked={current === value} onChange={() => onPick(value)} style={{ accentColor: c.accent }} />
      {label}
    </label>
  );
}

// ---------------------------------------------------------------------------
// Draft as me
// ---------------------------------------------------------------------------

function DraftComposer() {
  const c = useColors();
  const status = useEchoStatus();
  const connectors = useEchoConnectors();
  const gate = useQuery({ queryKey: ['echo', 'draft', 'status'], queryFn: () => echoApi.draftStatus(), retry: false, staleTime: 60_000 });
  const addTurn = useEchoPanelStore((st) => st.addTurn);
  const updateTurn = useEchoPanelStore((st) => st.updateTurn);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);

  const readiness = status.data ? computeReadiness(status.data, connectors.data?.connectors.length ?? 0) : null;
  const view = draftGateView(gate.data, gate.error, readiness);

  if (!view.available) {
    return (
      <div data-echo-gate="" style={{ fontFamily: fonts.ui }}>
        <p style={{ margin: 0, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>{view.title}</p>
        {view.lines.map((line) => (
          <p key={line} style={{ margin: `${space['1']} 0 0`, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal }}>
            {line}
          </p>
        ))}
        {view.action && (
          <Link to={view.action.href} style={{ display: 'inline-block', marginTop: space['2'], fontSize: fontSize.sm, color: c.accent }}>
            {view.action.label} →
          </Link>
        )}
      </div>
    );
  }

  const submit = async (e?: FormEvent) => {
    e?.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    const id = nextTurnId();
    addTurn({ id, kind: 'draft', text: message, status: 'pending' });
    setText('');
    setBusy(true);
    try {
      updateTurn(id, { status: 'done', result: await echoApi.draft({ message }) });
    } catch (err) {
      updateTurn(id, draftFailure(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit}>
      <Textarea
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        aria-label="The message to answer"
        placeholder="Paste the message you want to answer…"
        style={{ fontSize: 16 }}
      />
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: space['2'] }}>
        <Button type="submit" size="sm" loading={busy} disabled={!text.trim() || busy}>
          Draft a reply
        </Button>
      </div>
    </form>
  );
}

/** A failed draft as a turn: S-3.4.1's own words, and the names to confirm
 * when its private-person guard stopped it. */
function draftFailure(err: unknown): Partial<EchoTurn> {
  const e = draftErrorOf(err);
  if (e.code === 'names_need_confirmation') return { status: 'error', error: e.message, confirmNames: e.names };
  return { status: 'error', error: e.code === 'error' ? requestErrorLine(err) : e.message, confirmNames: undefined };
}

// ---------------------------------------------------------------------------
// Turns
// ---------------------------------------------------------------------------

function TurnView({ turn }: { turn: EchoTurn }) {
  const c = useColors();
  const label = turn.kind === 'library' ? 'Your library' : turn.kind === 'history' ? 'Your past questions' : 'Draft as you';
  return (
    <article data-echo-turn={turn.kind} style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <div style={{ alignSelf: 'flex-end', maxWidth: '90%', padding: `${space['2']} ${space['3']}`, background: c.surfaceAlt, borderRadius: radius.md, fontFamily: fonts.body, fontSize: fontSize.sm, whiteSpace: 'pre-wrap' }}>
        {turn.text}
      </div>
      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      {turn.status === 'pending' && (
        <span style={{ display: 'flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
          <Spinner size={14} /> {turn.kind === 'draft' ? 'Drafting…' : 'Reading and answering…'}
        </span>
      )}
      {turn.status === 'error' && (
        <p role="alert" style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: turn.confirmNames ? c.textPrimary : c.error }}>
          {turn.error}
        </p>
      )}
      {turn.status === 'error' && turn.confirmNames && <ConfirmNames turn={turn} />}
      {turn.status === 'done' && turn.kind === 'library' && <LibraryAnswer qa={turn.result as LibraryQAExchange} />}
      {turn.status === 'done' && turn.kind === 'history' && <HistoryAnswer qa={turn.result as QAHistoryExchange} />}
      {turn.status === 'done' && turn.kind === 'draft' && <DraftAnswer draft={turn.result as DraftResponse} />}
    </article>
  );
}

function ConfirmNames({ turn }: { turn: EchoTurn }) {
  const updateTurn = useEchoPanelStore((st) => st.updateTurn);
  const confirm = async () => {
    const names = turn.confirmNames ?? [];
    updateTurn(turn.id, { status: 'pending', error: undefined, confirmNames: undefined });
    try {
      updateTurn(turn.id, { status: 'done', result: await echoApi.draft({ message: turn.text, acknowledge_names: names }) });
    } catch (err) {
      updateTurn(turn.id, draftFailure(err));
    }
  };
  return (
    <div>
      <Button size="sm" variant="secondary" onClick={confirm}>
        Draft anyway
      </Button>
    </div>
  );
}

function AnswerBody({ children }: { children: string }) {
  const c = useColors();
  return (
    <div className="reading" style={{ fontFamily: fonts.body, fontSize: fontSize.sm, lineHeight: lineHeight.loose, color: c.textPrimary }}>
      <ReactMarkdown>{children}</ReactMarkdown>
    </div>
  );
}

function SourcesList({ children }: { children: ReactNode }) {
  const c = useColors();
  return (
    <div style={{ borderTop: `1px solid ${c.border}`, paddingTop: space['2'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, fontWeight: fontWeight.semibold, color: c.textSecondary }}>Sources</span>
      {children}
    </div>
  );
}

function LibraryAnswer({ qa }: { qa: LibraryQAExchange }) {
  const c = useColors();
  return (
    <>
      <AnswerBody>{qa.answer}</AnswerBody>
      {qa.references?.length > 0 && (
        <SourcesList>
          {qa.references.map((ref, i) => (
            <CitationLink key={i} reference={ref} style={{ fontSize: fontSize.xs }} />
          ))}
        </SourcesList>
      )}
      <Link to="/library/qa" style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.accent }}>
        Saved in Library Q&A →
      </Link>
    </>
  );
}

function HistoryAnswer({ qa }: { qa: QAHistoryExchange }) {
  const c = useColors();
  return (
    <>
      <AnswerBody>{qa.answer}</AnswerBody>
      {qa.references?.length > 0 && (
        <SourcesList>
          {qa.references.map((ref, i) => (
            <Link key={i} to={historyRefHref(ref)} style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.accent, textDecoration: 'none' }}>
              <span style={{ color: c.textMuted, marginRight: space['1'] }}>{historyRefLabel(ref.source_type)}</span>
              {ref.question_preview}
            </Link>
          ))}
        </SourcesList>
      )}
    </>
  );
}

function DraftAnswer({ draft }: { draft: DraftResponse }) {
  const c = useColors();
  const [copied, setCopied] = useState(false);
  const match = voiceMatchLine(draft.voice_match_score);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft.disclosure ? `${draft.draft}\n\n${draft.disclosure}` : draft.draft);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  };
  return (
    <>
      <div style={{ padding: space['3'], border: `1px solid ${c.border}`, borderRadius: radius.md, fontFamily: fonts.body, fontSize: fontSize.sm, lineHeight: lineHeight.loose, whiteSpace: 'pre-wrap' }}>
        {draft.draft}
        {draft.disclosure && <p style={{ margin: `${space['2']} 0 0`, fontSize: fontSize.xs, color: c.textMuted }}>{draft.disclosure}</p>}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
        {match && <Badge tone="neutral" size="sm">{match}</Badge>}
        <span style={{ flex: 1 }} />
        <Button size="sm" variant="tertiary" onClick={copy}>
          {copied ? 'Copied' : 'Copy draft'}
        </Button>
      </div>
      {(draft.deviation_notes ?? []).length > 0 && (
        <ul style={{ margin: 0, paddingLeft: space['4'], fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
          {draft.deviation_notes!.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {(draft.citations ?? []).length > 0 && (
        <SourcesList>
          {draft.citations!.map((cit) =>
            cit.href ? (
              <Link key={cit.ref} to={cit.href} style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.accent }}>
                {cit.label}
              </Link>
            ) : (
              <span key={cit.ref} style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
                {cit.label}
              </span>
            ),
          )}
        </SourcesList>
      )}
    </>
  );
}
