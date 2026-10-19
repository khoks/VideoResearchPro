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

## Re-runs after the contract fix (T-1.18.6.3, appended 2026-10-19)

Both re-runs use the code after PR #227 (R3/R4) and PR #234 (the attribution-boundary rule), the same job and transcripts, and the same unannotated arm (run 2's OFF report, 9,744 words). Only the frame descriptions differ.

| Run | Descriptions | ON words | Judges prefer ON | Mean substance ON / OFF | Confirmed attribution errors in ON | Confirmed fabrications ON / OFF |
|---|---|---|---|---|---|---|
| 1 (before #227/#234) | stored gpt-5.5 | 10,648 vs 6,490 | 3/3 | 8.33 / 7.00 | 2 (screen detail credited to a speaker) | 0 / 5 |
| 2 | gemini-3.1-flash-lite | 9,003 | **1/3** | 7.67 / 7.67 | 1 (screen detail credited to a speaker) | 0 / 0 |
| 3 | gpt-5.5 (re-described) | 10,782 | **3/3** | 8.67 / 7.67 | 2 (**speech presented as screen**) | 2 / 2 |

Verification for runs 2 and 3: the same 3-lens majority per claimed error plus three independent sweeps (108 and 117 agents). Run 2's verification hit a usage limit partway and was resumed from cache.

**What the three runs show.**
- **The substance gain replicates with a strong describer and disappears with a weak one.** Run 1's win was length-confounded (the annotated report was 64% longer); run 3's is not (10% longer), and all three judges still prefer it. Per-frame grading put Flash-Lite at 4.21 against gpt-5.5's 4.52, and that gap was enough to erase the report-level benefit. One run per arm, so this is direction, not effect size.
- **The prompt rule moved the error, it did not remove it.** Before S-1.18.6 the composer credited speakers with screen-only details. After it, the composer claimed the screen showed things that were only spoken: "the video displays Seaborn version 0.13.2 at 03:10", where the presenter *says* 0.13.2 in Bengali and no frame was captured near 3:10.
- **English-only checking is unreliable on this corpus.** A judge flagged that same sentence as fabricated because the evidence is Bengali speech with Bengali digits (০.১৩.২). The verification agents found it once they read the non-Latin speech.

**A deterministic check was tried and is not enough** (S-1.18.7, `backend/scripts/modality_check.py`, scored by `eval_modality_check.py` against the verified labels). At its best thresholds it caught **2 of 5** confirmed errors and raised about eight other flags per report, most of them false positives. Token matching fails for three reasons: four of the eleven videos are spoken in Hindi or Bengali, ASR renders `plt.plot` as "plt dot plot" (or पीएलटी डॉट प्लॉट), and the composer cites every sentence "— Source (mm:ss)", so nearly every sentence reads as speaker-attributed. It stays as a research tool, not a gate.

**Against the rule:** criterion 1 met with gpt-5.5 descriptions (3/3), not with Flash-Lite (1/3); criterion 2 failed in every run (1–2 errors per report); criterion 3 met only with Flash-Lite. No configuration passes, so the UI stays deferred ([D-075](../decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19)).

## Per-frame grading of three mid-priced describers (T-1.18.5.6, appended 2026-10-19)

D-075 ordered a per-frame pass to pick a candidate before any report-level run. Same job and 120 frames, re-described by each model, then a four-way blind grading against the gpt-5.5 baseline: 31 frames, two graders per frame who opened the image (62 gradings), labels re-shuffled per frame (each model appears under every label), unblinded afterwards. Raw data: `backend/data/r1_ab/retier/grading4_unblinded.json` (gitignored); costs from the per-model `*_describe.json` totals, divided by the 11 videos that produced calls.

| Describer | Mean accuracy /5 | Unusable | Best of four | Misreads | Hallucinated details | Cost per video |
|---|---|---|---|---|---|---|
| gemini-3.5-flash | **4.70** | **0 / 62** | 22 | 21 | 8 | $0.051 |
| gpt-5.5 (baseline) | 4.54 | 5 / 62 | 37 | 30 | 8 | $0.133 |
| gpt-5.4-mini | 4.37 | 5 / 62 | 3 | 39 | 2 | $0.018 |
| claude-haiku-4-5 | 2.39 | **55 / 62** | 0 | 146 | 68 | $0.026 |

claude-haiku-4-5 accepts images and is on `VISION_CAPABLE_MODELS`, yet its descriptions are unusable on this corpus; the registry now lists it as unacceptable for `visual_describe_frame` (S-1.14.7), alongside gpt-5.6-luna. Per D-075 the default changes only on a report-level run; gemini-3.5-flash is the candidate.

## Run 4 and where the attribution errors live (T-1.18.5.6 / S-1.18.8, appended 2026-10-19)

Gemini 3.5 Flash is the most accurate. The one figure this run checked by hand is the holiday-spike annotation, whose code on screen reads `54060.10`: Flash read it exactly, gpt-5.5 read `54000.10`, and the speech transcript garbled it to "54,60.10". But graders picked gpt-5.5 as the most useful description far more often, for completeness. Haiku is unusable for frames even though it is on the vision allowlist.

**Run 4** (gemini-3.5-flash descriptions, same code and unannotated arm as runs 2–3): 9,612 words; judges prefer ON **2/3**; mean substance 7.67 vs 8.00; 2 confirmed attribution errors; 0 confirmed fabrications in ON (1 in OFF).

**Report-level ranking follows "picked best", not accuracy:** gpt-5.5 (37 best) → 3/3; Gemini 3.5 Flash (22) → 2/3; Flash-Lite (5 of 66) → 1/3. What helps the composer is what a frame description says, not only whether each reading is exact.

**Where the attribution errors live.** Of the five confirmed errors after the S-1.18.6 rule (runs 2–4), **four are in the one Bengali-language video** (CodeWithMunnaX, 1 of 11 videos). In each, the composer misjudged what was said, because the speech is Bengali:
- it called a ValueError "not spoken" when the presenter read it aloud in Bengali;
- it credited the presenter with dataset names that appear only on screen;
- it said the screen displayed a version number the presenter only spoke.

The English-language videos produced one error across the same three runs. The modality boundary is hardest exactly where the composer cannot read the speech, which is an argument for labelling said/shown at the map stage (S-1.18.8). There the model reads one chunk of native-language speech at a time and the label is fixed before composition. It also ties R1 to R5.
