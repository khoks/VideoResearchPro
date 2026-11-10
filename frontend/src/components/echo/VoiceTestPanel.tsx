import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { usePickVoiceTest, useScoreVoiceTest, useStartVoiceTest, useVoiceTest, useVoiceTestPoll } from '../../hooks/useEcho';
import type { VoiceGate, VoiceTest, VoiceTestOffer, VoiceTestSide } from '../../services/echoApi';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';
import { ProgressBar } from '../common/ProgressBar';
import { Button, Skeleton } from '../primitives';
import { inlineErrorMessage } from '../../utils/apiError';

const SIDES: VoiceTestSide[] = ['A', 'B'];

function percent(share: number): number {
  return Math.round(share * 100);
}

function useTextStyle(): React.CSSProperties {
  const c = useColors();
  return { margin: 0, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal };
}

/**
 * The "which of these did you write?" test (D-100, T-3.4.1.8), which turns
 * "speak as me" on per user. Echo sets some of the user's notes aside and
 * writes a draft on each one's topic; the user sees each pair, one at a time,
 * and picks the one they wrote. Writing a test calls the model, so the panel
 * says how much before the button, and only that button starts one. While a
 * gate is shut it says why instead of offering the test. `shown` lists the
 * blockers the card above already prints, so a reason appears once.
 */
export function VoiceTestPanel({ shown = [] }: { shown?: string[] }) {
  const c = useColors();
  const qc = useQueryClient();
  const overview = useVoiceTest();
  const data = overview.data;
  const test = data?.test ?? null;
  const writing = test?.status === 'generating';
  const poll = useVoiceTestPoll(writing && test ? test.id : null);
  const polled = writing ? poll.data : undefined;
  const done = polled !== undefined && polled.status !== 'generating';
  // A failed read is said here alone: the hook sets `meta` (T-3.4.1.26).
  const loadError = overview.isError ? inlineErrorMessage(overview.error, "Couldn't load the test.") : null;

  useEffect(() => {
    // Written (or failed): the overview holds the pairs and the new offer.
    if (done) qc.invalidateQueries({ queryKey: ['echo', 'voice-test'] });
  }, [done, qc]);

  return (
    <section data-voice-test-panel aria-label="Your voice test" style={{ marginTop: space['4'], paddingTop: space['3'], borderTop: `1px solid ${c.border}` }}>
      <h3 style={{ margin: `0 0 ${space['2']}`, fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
        Your voice test
      </h3>
      {overview.isLoading ? (
        <Skeleton variant="text" />
      ) : overview.isError || !data ? (
        loadError && (
          <div style={{ display: 'flex', gap: space['3'], alignItems: 'center', fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
            <span role="alert">{loadError}</span>
            <Button size="sm" variant="tertiary" onClick={() => overview.refetch()}>
              Retry
            </Button>
          </div>
        )
      ) : writing && test ? (
        <Writing test={polled ?? test} />
      ) : test?.status === 'ready' ? (
        <Pairs key={test.id} test={test} />
      ) : (
        <>
          <LastResult test={test} gate={data.gate} />
          <Offer offer={data.offer} passed={data.gate.status === 'passed'} shown={shown} />
        </>
      )}
    </section>
  );
}

function Writing({ test }: { test: VoiceTest }) {
  const text = useTextStyle();
  return (
    <div data-writing style={{ display: 'flex', flexDirection: 'column', gap: space['2'] }}>
      <p style={text}>
        Echo is writing your test: {test.pairs_built} of {test.pairs_total} pairs. This takes a few minutes, and you can leave
        this page while it runs.
      </p>
      <ProgressBar value={test.pairs_total ? (100 * test.pairs_built) / test.pairs_total : 0} />
    </div>
  );
}

function LastResult({ test, gate }: { test: VoiceTest | null; gate: VoiceGate }) {
  const c = useColors();
  const text = useTextStyle();
  if (test?.status === 'failed') {
    return (
      <p data-test-failed role="alert" style={{ ...text, color: c.error, marginBottom: space['2'] }}>
        {test.error ?? 'Echo could not write the test.'}
      </p>
    );
  }
  if (gate.status === 'not_run' || gate.picked_own_share === null) return null;
  const passed = gate.status === 'passed';
  return (
    <p data-result={gate.status} style={{ ...text, marginBottom: space['2'] }}>
      {passed ? 'Passed' : 'Not passed'}: you picked your own writing in {percent(gate.picked_own_share)}% of {gate.pairs} pairs.
      {passed ? " Echo's drafts can pass for your writing." : ''}
    </p>
  );
}

function Offer({ offer, passed, shown }: { offer: VoiceTestOffer; passed: boolean; shown: string[] }) {
  const c = useColors();
  const text = useTextStyle();
  const start = useStartVoiceTest();
  // A user who has passed asks for it first: a fail would turn drafting off.
  const [retake, setRetake] = useState(false);

  if (!offer.available) {
    const reasons = offer.blockers.filter((b) => !shown.includes(b.code));
    return reasons.length === 0 ? (
      <p data-offer-closed style={text}>You can take the test once the reasons above are sorted out.</p>
    ) : (
      <ul data-offer-closed style={{ margin: 0, paddingLeft: space['5'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
        {reasons.map((b) => (
          <li key={b.code} data-blocker={b.code} style={text}>
            {b.message}
          </li>
        ))}
      </ul>
    );
  }

  if (passed && !retake) {
    return (
      <Button size="sm" variant="tertiary" onClick={() => setRetake(true)}>
        Take the test again
      </Button>
    );
  }

  return (
    <div data-offer style={{ display: 'flex', flexDirection: 'column', gap: space['2'], alignItems: 'flex-start' }}>
      <p style={text}>
        Echo sets {offer.pairs} of your notes aside and writes a note in your voice on each one's topic. You see each pair, one
        at a time, and pick the one you wrote. You pass if you pick your own writing in {percent(offer.pass_share)}% of pairs or
        fewer, because that means Echo's drafts can pass for yours.
      </p>
      <p data-cost style={{ ...text, color: c.textPrimary }}>
        Writing the test makes about {offer.model_calls} calls to {offer.model}, which count toward your usage, and takes a few
        minutes. Nothing starts until you press the button.
      </p>
      {passed && <p style={text}>Your new result replaces this one. If you don't pass, Speak as me turns off until you do.</p>}
      {/* A failure is said by the hook, once, even after the reader has left (T-3.4.1.17). */}
      <Button size="sm" loading={start.isPending} onClick={() => start.mutate()}>
        Start the test
      </Button>
    </div>
  );
}

function Pairs({ test }: { test: VoiceTest }) {
  const c = useColors();
  const text = useTextStyle();
  const pick = usePickVoiceTest();
  const score = useScoreVoiceTest();
  const { pairs, picks } = test;
  const firstOpen = pairs.findIndex((p) => !picks[p.pair]);
  const [index, setIndex] = useState(firstOpen === -1 ? pairs.length - 1 : firstOpen);
  const current = pairs[index];
  const picked = pairs.filter((p) => picks[p.pair]).length;
  const complete = picked === pairs.length;

  if (!current) return null;

  const choose = (side: VoiceTestSide) => {
    pick.mutate(
      { id: test.id, pair: current.pair, pick: side },
      {
        onSuccess: (updated) => {
          // On to the next pair still open after this one, wherever that is.
          const after = pairs.findIndex((p, i) => i > index && !updated.picks[p.pair]);
          const before = pairs.findIndex((p) => !updated.picks[p.pair]);
          const next = after !== -1 ? after : before;
          if (next !== -1) setIndex(next);
        },
      },
    );
  };

  return (
    <div data-pairs style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      <p style={text}>
        Which of these did you write? Pair {index + 1} of {pairs.length}, {picked} picked.
      </p>
      <ProgressBar value={(100 * picked) / pairs.length} />
      <div data-pair={current.pair} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: space['3'] }}>
        {SIDES.map((side) => {
          const chosen = picks[current.pair] === side;
          return (
            <article
              key={side}
              data-side={side}
              style={{
                display: 'flex', flexDirection: 'column', gap: space['2'], padding: space['3'], minWidth: 0,
                border: `1px solid ${chosen ? c.accent : c.border}`, borderRadius: radius.md,
              }}
            >
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>Text {side}</span>
              {/* Plain text for both sides: formatting one would mark it. */}
              <div style={{ ...text, color: c.textPrimary, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', maxHeight: 320, overflowY: 'auto', flex: 1 }}>
                {current[side]}
              </div>
              <div>
                <Button size="sm" variant={chosen ? 'primary' : 'secondary'} aria-pressed={chosen} disabled={pick.isPending || score.isPending} onClick={() => choose(side)}>
                  I wrote {side}
                </Button>
              </div>
            </article>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: space['2'], alignItems: 'center', flexWrap: 'wrap' }}>
        <Button size="sm" variant="tertiary" disabled={index === 0} onClick={() => setIndex(index - 1)}>
          Back
        </Button>
        <Button size="sm" variant="tertiary" disabled={index === pairs.length - 1} onClick={() => setIndex(index + 1)}>
          Next
        </Button>
        {complete && (
          <Button size="sm" loading={score.isPending} onClick={() => score.mutate(test.id)}>
            See my result
          </Button>
        )}
      </div>
    </div>
  );
}
