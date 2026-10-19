# R1 visual understanding — measurement protocol (S-1.18.3)

**Status:** pre-registered 2026-10-18, before any result existed. Results are appended below the rule, never edited into it.

## Question

Do `[VISUAL @ mm:ss — …]` annotations make the *report* better, or only longer? The pipeline is verified to produce accurate descriptions and deliver them intact (D-067); nothing yet shows the output improves.

## Design

One visual-on topic job on a topic where the picture plausibly carries information the words do not (charting / data-visualisation tutorials: code and plots on screen). Then a **deterministic replay** of that job's own chunks, twice, through `run_report_agent`:

- **ON** — chunks built from `annotate_segments(cached_segments, stored_frames)`, as production did.
- **OFF** — chunks built from the same cached segments with no frames.

Same videos, same transcript text, same chunker, same models, same day. The only difference is the presence of the visual spans. Two searches would not give this: discovery is not deterministic.

Why replay rather than trusting production's ON report alone: both arms must be produced by the same code path at the same time, so run-to-run LLM variance is the noise floor, not a confound.

## Judging

Three independent blind judges (different model families, to blunt self-preference), each given both reports under coin-flipped labels and the annotated transcript so claims can be checked. Rubric, scored per report 1–10:

1. **Substance** — specific, verifiable claims per 100 words (judges are told to suspect the longer text of padding).
2. **Visual information used correctly** — content that could only come from the screen, attributed as shown rather than said.
3. **Attribution errors** — any case where screen content is presented as something the speaker said, or vice versa. Counted, not scored.
4. **Fabrication** — claims absent from the transcript. Counted.

## Decision rule (fixed now)

Build the R1 UI (S-1.18.2) only if **all three** hold:

- At least 2 of 3 judges prefer ON on *substance*, not length.
- ON has **zero** attribution errors across all judges.
- Vision spend for the job is under **$0.10 per video** at the default frame caps.

If ON wins on substance but has attribution errors, fix the contract first and re-run before any UI. If ON does not win, the feature stays backend-only and opt-in, and S-1.18.2 is deferred rather than built.

Side measurements, reported but not part of the rule: `informative` false-positive rate on a hand-checked sample of frames (T-1.18.3.2), and cost per job (T-1.18.3.3).

## Known limits of this design

- It measures the report only. Q&A cannot be compared fairly today because annotations never reach Chroma for a video that was already embedded (T-1.18.1.10), and knowledge extraction never sees them at all (T-1.18.1.11).
- One topic. A positive result on a chart-heavy topic says little about talking-head interviews; a negative one is strong evidence, since this is the favourable case.
- Judges are models. The hand-checked frame sample is the only human-in-the-loop step.

## Results (appended 2026-10-19; the rule above was not edited)

**Run.** Job `419e691d` (tier-test account): topic "matplotlib and seaborn data visualization tutorials", 12 approved, 11 transcripts fetched (1 unavailable), 120 frames captured at 640×360, 119 flagged informative. Replay: ON 515 chunks (119 carry a span), OFF 410 chunks. ON report 10,648 words in 635 s; OFF 6,490 words in 344 s. Artifacts: `backend/data/r1_ab/run1/` (gitignored); compact copy in `docs/notes/2026-10-19-r1-run1-results.json`.

**Judges** (`judge_pair.py`, independent coin flips):

| Judge | Substance ON / OFF | Visual use ON / OFF | Prefers | Attribution errors | Fabrications claimed |
|---|---|---|---|---|---|
| GPT-5.5 medium | 8 / 6 | 9 / 4 | ON | 0 / 0 | 7 ON, 13 OFF |
| Claude Sonnet 5 medium | 8 / 7 | 8 / 5 | ON | 0 / 0 | 0 / 0 |
| Gemini 3.1 Pro preview medium | 9 / 8 | 9 / 8 | ON | 0 / 0 | 0 / 0 |

**Adversarial verification** (workflow `r1-verify-judges`, 87 agents: three lenses per claimed error, three independent sweeps of ON, three refuters per sweep candidate, majority rules):
- ON "fabrications": 0 of 7 confirmed. Four are reduce-phase metadata leaking into prose ("178 key facts", "thirteen source items"), three restate the supplied statistics.
- OFF fabrications: 5 of 13 confirmed — a seaborn API chronology the corpus never states (`distplot`→`histplot`), two corpus mis-counts ("eight tutorial videos", "nine source items"), a universal negative contradicted by speech, and a subplot placement the speaker never gave.
- **Sweep of ON: 8 candidates, 2 confirmed attribution errors that all three judges missed.** Both have the same shape: a sentence attributed to a named speaker ("— Onur Baltaci (10:21)"; "Absent Data describes it as…") bundles a detail present only in a `[VISUAL @]` span ("confidence band") with things the speaker genuinely said. The four "(values also visible on screen)" candidates were refuted unanimously: that pattern is correct use.

**Hand check** (7 frames across 5 videos): 6 described exactly (slide table columns, chart titles, axis labels, tick ranges, annotated heat-map values, code), 1 minor misread at 360p (`dedup` read as `debug`), 1 borderline "informative" (mostly a code cell). 119/120 informative is consistent with the inclusion bias D-067 predicted, but the sample found no outright wrong description.

**Cost** (T-1.18.3.3, estimated from token counts and the pricing table): selection ≈ 75K in / 10K out, description ≈ 159K in / 23K out, all on gpt-5.5 → **$2.17 for 11 videos, $0.198 per video.**

**Against the rule.**
1. At least 2 of 3 judges prefer ON on substance — **met** (3 of 3; mean 8.33 vs 7.00).
2. Zero attribution errors in ON — **not met** (2, found only by the sweep).
3. Under $0.10 per video — **not met** ($0.198).

**Outcome:** the UI is not built. Per the rule's own branch, the contract is fixed first (speaker-attributed sentences may contain only speech; screen-only details go in a separate clause marked as shown), the two vision use cases move to a cheaper tier, and the measurement is re-run. Tracked as S-1.18.5 and S-1.18.6.

**Also observed.** Both arms leak pipeline metadata and mis-state the corpus inside sections (S-1.14.15); ON had zero confirmed fabrications against OFF's five, which suggests annotations crowd out general-knowledge padding, but one run cannot establish that. Three blind judges missed both attribution errors, so a sweep with independent refuters is now part of the method, not an optional extra.

## Re-tier (S-1.18.5, appended 2026-10-19)

Same job, same 120 frames and 11 transcripts, re-run per model with real token usage (`backend/scripts/retier_vision.py`).

Per-video figures divide by the 11 videos that produced calls (the twelfth approved video had no transcript); a first pass divided by 12 and understated every number by 8%, which the pinned cost test caught.

| Use case / model | Real cost per video | Quality signal |
|---|---|---|
| select · gpt-5.5 medium (baseline) | $0.097 | agrees with its own stored picks 85% (noise floor) |
| select · gpt-5.5 low | $0.067 | 76% agreement with the medium picks |
| select · gpt-5.5 off | $0.064 | 76% |
| select · gpt-5.6-luna off | $0.002 | 59% |
| select · gpt-5.4-mini off | $0.009 | 24% |
| select · gemini-3.1-flash-lite off | $0.003 | 23% |
| describe · gpt-5.5 low (baseline) | $0.133 | mean accuracy 4.52/5, best 54/66, 3 unusable |
| describe · gemini-3.1-flash-lite off | $0.008 | 4.21, best 5/66, 5 unusable |
| describe · gpt-5.6-luna off | $0.004 | 3.97, best 6/66, **22 unusable** |

Description quality: 33 frames stratified across the 11 videos, three descriptions per frame under shuffled blind labels, two independent graders per frame who opened the image (66 gradings), unblinded afterwards. Luna's failures were substantive (wrong dates on an axis, a code cell reported as output, wrong variable names); flash-lite's were mostly casing and label misreads at 360p, which gpt-5.5 also made less often.

**Decision (D-073):** describe on gemini-3.1-flash-lite, select stays on gpt-5.5 at low reasoning: **$0.075 per video** against $0.230 before, under the ceiling. The resolution finding (every model struggled with 640×360 text) is filed as T-1.18.5.5. The protocol re-run with these tiers follows S-1.18.6.
