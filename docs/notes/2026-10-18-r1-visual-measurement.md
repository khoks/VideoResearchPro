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

## Run 5: said/shown provenance (T-1.18.8.4, appended 2026-10-19)

Code after S-1.14.6 (#273) and S-1.18.8 (#277); gpt-5.5 descriptions (the D-081 default); both arms regenerated on the same code.

- **Labels populated:** the annotated arm has 154 map items (96 `said`, 57 `both`, 1 `shown`); the plain arm is all `said`, forced by code. No `[SAID]`/`[SHOWN]` tag leaked into either HTML.
- **Attribution: zero confirmed errors in the annotated report**, the first run of five to meet that criterion. The sweep raised 4 candidates and all 4 were refuted. The plain arm had 2 (it presented an on-screen tool list as recited).
- **Substance is not a clean read.** Judges split 1 ON / 1 OFF / 1 tie (mean 7.0 vs 8.0). Gemini 3.1 Pro hit its daily per-model quota (resets in about 11 hours), so Gemini 3.5 Flash stood in as the third family, a protocol deviation.
- **Run 5 is confounded by an R5 regression.** #268 (T-1.16.2.5 part A) added a map-stage `original` field ("the speaker's words copied EXACTLY"). Map batch 0 mixed 400 chunks from eight channels, including one Bengali and two Hindi videos. For DeepLoop Circle (100% Devanagari speech) the model wrote `original`s in Bengali script: 8 items in the annotated arm, 3 in the plain one. None of those strings exists anywhere in the corpus. The annotated report then quoted Vivek in Bengali seven times; the Flash judge's preference for the plain arm rests on exactly that. Runs 3 and 4, which predate #268, have none. The fix belongs to R5: enforce "copied exactly" in code, by checking each `original` against its own video's transcript.

**Verdict for now:** the provenance labels did what D-075 predicted for attribution (one run). The substance criterion has to be re-measured as run 6, once the R5 fix lands and the Gemini Pro quota resets.

### Run 5, audited mechanically (2026-10-19)

`backend/scripts/audit_quote_fidelity.py` checks every non-English quotation against the speech it claims to come from. It works at two levels: map items' `original` against their own video's speech (visual spans excluded), and every Devanagari/Bengali run in the report against all speech in the corpus. On run 5:

| | `original` items failing | report quotes failing |
|---|---|---|
| ON | 12 of 51 (11 in the wrong script) | **8 of 27** |
| OFF | 4 of 37 (mixed script) | **2 of 14** |

It found two more defects than the hand reading did:
- The plain arm is affected too. Its Hindi quotes have Bengali letters spliced into words (`जানेंगे`), a form that no caption contains.
- One ON item quotes a CodeWithMunnaX sentence about species, island and flipper length. The Bengali speech never mentions those words. It is DeepLoop's Hindi sentence rendered in Bengali under the wrong channel.

The fuzzy match is a deliberate tolerance: the model regularises caption spelling (ম্যাটপ্লোটলিব এ becomes ম্যাটপ্লটলিবে), and that counts as `near`, not invented. Run 4, which predates #268, has no native-script quotes in either report.

## Run 6: pre-registered rules (fixed 2026-10-19, before run 6 exists)

Run 6 replays the same job on the code that carries the R5 fix for `original` quotes. Both arms are regenerated, and descriptions come from gpt-5.5 (D-081).

1. **Quote fidelity (new, deterministic):** `audit_quote_fidelity.py <run6> --check` exits 0. Zero failing report-level quotes in both arms (absent, other-video, visual-only, wrong script, or mixed script). If this fails, the run is invalid for the substance comparison, as run 5 was.
2. **Attribution:** zero confirmed attribution errors in ON after the three-lens verification and the sweep, as in run 5.
3. **Substance:** at least two of three judge families prefer ON, with Gemini 3.1 Pro as the third family. No substitute is allowed. If its quota is exhausted, the run waits.
4. **Fabrication:** ON has no more confirmed fabrications than OFF.

All four pass → R1's quality claim holds, and S-1.18.2 (the R1 UI) is unblocked. Rule 1 fails → the defect goes back to R5 and run 6 is repeated. Rule 2 or 4 fails → the claim is reported as unproven. Rule 3 alone fails → D-081 stands on attribution, and the UI ships as opt-in with no quality claim.

## Run 6: result against the pre-registered rules (2026-10-19)

Same job, regenerated on master after the R5 fix (#294) and the refine/channel contract fix (#292). Descriptions: gpt-5.5 (D-081). ON 75,104 chars, OFF 83,542.

| Rule | Result | Evidence |
|---|---|---|
| 1. Quote fidelity | **pass** | `audit_quote_fidelity.py --check` exits 0. Report level: ON 21 native-script quotes (17 verbatim, 4 near), OFF 26, none failing. The map stage still invents wrong-script `original`s (ON dropped 10 of 57: 8 script mismatch, 1 mixed script, 1 not in speech); the R5 check now drops them before compose |
| 2. Attribution | **fail** | Two confirmed ON errors (3 of 3 votes each). The judges' 3 claims were all refuted; the sweep raised 5 candidates and confirmed 2 |
| 3. Substance | **fail** | GPT-5.5 and Sonnet 5 both prefer OFF (7 vs 8 each). Gemini 3.1 Pro, run once its quota reset at about 15:50 PT, scored a **tie** (10 vs 10) and claimed no errors. Final: 0 ON / 2 OFF / 1 tie, mean 8.0 vs 8.67 |
| 4. Fabrication | **pass** | ON 0 confirmed (1 metadata leak); OFF 4 |

**Both failures trace to the map stage, not to the annotations.**
- *Substance:* both judges gave the same decisive reason. ON never engages Absent Data or Onur Baltaci. The persisted intermediates show the map stage gave those two videos **zero items** in a 400-chunk batch. The same thing happened to the plain arm in run 5. The map model (gpt-5.6-luna) writes about 100 to 140 items per call whatever the batch size. See [2026-10-19-map-coverage.md](2026-10-19-map-coverage.md).
- *Attribution error 1:* CodeWithMunnaX says "0.13.2" in Bengali at 2:57. The report adds "the output was also visible on screen". The only span showing 0.13.2 is in **Simplilearn's** video at 2:54. The map model read both in the same batch and labelled the CodeWithMunnaX item `both`. This is cross-source contamination, which a label-only fix cannot catch.
- *Attribution error 2:* the map item itself reads "the presenter describes the 538-like style as producing ... a light grid". The grid exists only in the 22:33 span. The `both` label is right, but the item's content already mixes speech and screen.

**Verdict:** run 6 fails rules 2 and 3 as pre-registered, so R1's quality claim stays unproven. The failures point to a fix that is not R1-specific: map batches that never mix sources, plus a code-side check that a `shown` or `both` label has a span **from the item's own source** near its moment. That work is measured in the map-coverage note. A run 7 will be pre-registered there once the fix lands, under the same four rules.

## Run 8: pre-registered (2026-10-19, before it runs)

The same job and descriptions (gpt-5.5, D-081), regenerated on master at 7e2ac88. Since run 6, master has:
- packed map batching with the starved-source re-map (D-094);
- truncation as a failure, with retry and per-call budgets (D-090);
- `original` salvage (#307);
- report-level native-script quote checking in code (#309).

The rules are run 6's four, unchanged:
1. `audit_quote_fidelity.py --check` exits 0.
2. Zero confirmed attribution errors in ON after three-lens verification and the sweep.
3. At least two of three families (GPT-5.5, Sonnet 5, Gemini 3.1 Pro; no substitutes, so the run waits on quota) prefer ON on substance.
4. ON has no more confirmed fabrications than OFF.

Rule 1 is now enforced in the pipeline by #309, so its pass is expected and weak evidence. It still gates the run.

**All four pass** → R1's quality claim holds, and S-1.18.2 (the R1 UI) is built. **Rule 3 alone fails** → the UI ships opt-in with no quality claim, as run 6's rule set out. **Rule 2 or 4 fails** → the claim stays unproven, and the UI decision goes to the user with all eight runs summarised.

## Run 8: results (2026-10-19)

ON 136,623 chars (887 s; 3 starved sources re-mapped), OFF 101,375 chars (749 s; 1 re-mapped).

| Rule | Result | Evidence |
|---|---|---|
| 1. Quote fidelity | **pass** | Report level: ON 56 quotes, OFF 52, none failing. Map: 2 of 133 originals dropped |
| 2. Attribution | **pass** | The one judge claim was refuted 3 of 3; the sweep raised 3 candidates and confirmed none. Zero confirmed attribution errors in ON, the second such run (run 5 was the first) |
| 3. Substance | **pending** | Sonnet 5 prefers ON, GPT-5.5 prefers OFF (7 vs 9). Gemini 3.1 Pro is quota-blocked (250 requests per day, shared across sessions). A background waiter judges when it unblocks. Its vote decides |
| 4. Fabrication | **pass** | ON 0 confirmed (1 metadata leak), OFF 0 confirmed |

**Consequence, fixed by the pre-registration:** both remaining outcomes build S-1.18.2. If Gemini prefers ON, all four rules pass and R1's quality claim holds. Otherwise rule 3 alone fails, and the UI ships opt-in with no quality claim. Either way the UI is built now; only the copy waits for the vote.

### Run 8: final (Gemini 3.1 Pro's vote, recorded 2026-10-19 ~21:00 PT)

Gemini 3.1 Pro **preferred ON** (substance 9 vs 9; visual use 9 vs 5). Its claims were verified like every other judge's:
- **Attribution, ON: confirmed 3 of 3.** The executive summary credits Data Analytics Lab with reading the coffee data "to a full analytical story", seven two-decimal weekday totals included. Those totals exist only in the `[VISUAL @ 18:24]` day_totals table; the presenter never speaks a figure. This is the original D-071 shape (a screen detail inside a speaker-credited sentence), and the three-strategy sweep had missed it.
- **"22 March 2026" fabrications, both arms: refuted.** DeepLoop Circle's `published_at` is 2026-03-22, supplied to the composer in the chunk headers. The judges saw only the corpus statistics.

| Rule | Final | Evidence |
|---|---|---|
| 1. Quote fidelity | pass | 0 failing in either arm |
| 2. Attribution | **fail** | 1 confirmed ON error (found by Gemini, missed by the sweep) |
| 3. Substance | pass | ON 2 (Sonnet 5, Gemini 3.1 Pro) / OFF 1 (GPT-5.5). Mean substance favours OFF, 8.33 vs 9.0: both ON preferences were 9-9 ties broken towards ON, and GPT-5.5 scored ON 7, OFF 9 |
| 4. Fabrication | pass | 0 confirmed in either arm |

**Consequence, as pre-registered:** rule 2 failed, so R1's quality claim stays unproven and the UI decision goes to the user. The UI (S-1.18.2, #329) had already shipped on the premise that rules 2 and 4 had passed, which was true until this late claim was verified. It is opt-in, makes no quality claim, and now discloses the measured risk in its copy.

## Eight runs, summarised for the user's decision

| Run | Describer / pipeline | ON attribution errors (confirmed) | Substance (ON / OFF / tie) | Confirmed fabrications ON vs OFF |
|---|---|---|---|---|
| 1 | gpt-5.5, old prompt | 2 | 3 / 0 / 0 (length-confounded) | 0 vs 5 |
| 2 | Flash-Lite | 1 | 1 / 2 / 0 | n/a |
| 3 | gpt-5.5 + attribution rule | 2 (direction reversed) | 3 / 0 / 0 | n/a |
| 4 | Gemini 3.5 Flash | 2 | 2 / 1 / 0 | n/a |
| 5 | gpt-5.5 + said/shown labels | **0** | 1 / 1 / 1 (confounded by the R5 regression) | 0 vs 2 |
| 6 | + R5 fix | 2 (one cross-source) | 0 / 2 / 1 (map starved two channels) | 0 vs 4 |
| 7 | source batching | invalid (quote gate) | exploratory only | n/a |
| 8 | packed + re-map, quote scrub | 1 | 2 / 1 / 0 | 0 vs 0 |

What the eight runs show:
- **Fabrication** is never worse with annotations; where it differs, ON is better (0 vs 2 to 5).
- **Visual use** is consistently judged higher.
- **Substance preference** swings with whatever pipeline defect a run exposed.
- **Attribution** settles at roughly one confirmed error per report: speaker-credited sentences that absorb a screen-only detail. Prompt rules and said/shown labels reduced it from two to about one; they did not remove it. A deterministic guard (`modality_check.py`) caught only 2 of 5 at its best setting, so nothing yet removes it.

## Runs 9 and 10: the deterministic attribution guard, pre-registered (2026-10-24, before either run exists)

D-105 hid R1's UI until a deterministic guard removes the residual attribution error. S-1.18.9 builds that guard (`backend/app/services/attribution_guard.py`), at two points:

- **Map items.** A detail of an item (a number, an identifier, a quoted string, a visual descriptor pair such as "confidence band", or three or more listed names) that sits in a span of the item's own source near its moment, and not in the speech around that moment, is screen-only. An item whose details are all screen-only becomes `shown`; screen-only clauses are split into a `shown` item; otherwise the details are listed in the compose tag (`[SAID+SHOWN; shown on screen: ...]`). Run 8's weekday totals reached the composer as `[SAID+SHOWN]`, and the tag note told it to credit the speaker.
- **The composed report.** A screen-only detail in a part of a sentence credited to a speaker is marked in place, "(on screen at 18:24)", with the span's own timestamp. "Not spoken" is added only for figures and multi-word quotes absent from the source's whole speech, and only in Latin-script speech. An "also visible on screen" with no span of the cited source behind it is removed; "the video displays X", where only the speech has X, is marked as said. The sections are guarded before the executive summary reads them, then the summary is guarded. Every change is counted and disclosed in the report's processing note, and listed in the run's `on.intermediates.json` (`attribution_guard`).

**Offline check (in-sample, not evidence for the rule).** On the stored ON reports of runs 1 to 8 the guard catches 8 of the 10 confirmed attribution errors (`modality_check.py`: 2 of 5). The two misses are a frame-specific reading of a file explorer (run 3) and a sentence with no checkable detail, "This was not spoken" (run 4). The guard was designed against these same labels, so this shows coverage, not generalisation; the two runs below are the test. Every "not spoken" it wrote was checked against the transcripts by hand.

**Setup.** Job `419e691d`, both arms regenerated on the commit that adds this section, with `--descriptions data/r1_ab/retier/baseline_describe.json` (gpt-5.5, D-081) and the models in `backend/.env`, exactly as run 8. Run 9, then run 10, with no code change in between. Judges: `judge_pair.py` with GPT-5.5, Sonnet 5 and Gemini 3.1 Pro (all medium). No substitutes: a run waits for the Gemini quota.

**Verification, unchanged from runs 1 to 8.** Every claim from every judge, Gemini 3.1 Pro's included, gets three lenses, and the majority decides. Then three independent sweeps of ON (every visual reference, every speaker credit, the densest sections), with three refuters per candidate. The D-075 multilingual rule applies throughout. **New:** every sentence the guard changed is also a candidate, checked by the three attribution lenses and by the fabrication lens.

**Pass rule.** Both runs must pass every item:
1. Quote fidelity: `audit_quote_fidelity.py --check` exits 0 (unchanged).
2. Attribution: zero confirmed attribution errors in ON, in either direction, counting every judge's claims and the sweep (unchanged). A wrong guard mark counts here.
3. Substance: at least two of the three families prefer ON (unchanged).
4. Fabrication: ON has no more confirmed fabrications than OFF (unchanged).
5. No rise in fabrication from the guard: zero confirmed errors of either kind among the sentences the guard changed.
6. No substance loss beyond noise. (a) Mechanically, every detail named in a guard record still appears in the ON report: the guard moves details, it never deletes them. A removed "also visible on screen" deletes a claim about the screen, not a detail. (b) ON's mean substance across the three judges is at least **7.67**, which is run 8's 8.33 minus 0.67. The 0.67 is the largest change in one arm's mean substance between consecutive comparable runs (OFF, run 5 to run 6). Judge noise on an identical pair of reports was 0.33 (runs 2 to 4).

**Outcomes, fixed now.**
- Both runs pass: set `featureFlags.visualAnalysis = true`, record a decision that supersedes D-105, and update S-1.18.2, the L6 status and the CHANGELOG.
- Rule 1 fails: that run is invalid. The defect is fixed in its own change and the run is repeated; it does not count toward the two.
- Anything else fails in either run: the guard does not meet D-105's bar, the feature stays hidden, and the failing case is recorded. If run 9 fails, run 10 is not run.

## Run 9: results (2026-10-24; the rule above was not edited)

Commit `05e0fd8`, the commit that added the pre-registration. ON 124,016 chars (867 s), OFF 112,123 chars (853 s); 517 and 410 chunks; 1 starved source re-mapped. Compact record: [2026-10-24-r1-run9-results.json](2026-10-24-r1-run9-results.json); artifacts in `backend/data/r1_ab/run9/` (gitignored).

**What the guard did.**
- *Map items* (ON): 30 listed with their screen-only details, 2 relabelled `shown`, 1 split.
- *Report* (ON): 7 changes in 6 sentences. Five details in speaker-credited sentences were marked "(on screen at mm:ss)": `matplotlib.pyplot`, `sns.lineplot`, `sns.histplot`, `plt.subplots()`, and Onur Baltaci's "confidence band". In one sentence, CodeWithMunnaX's "0.13.2" was marked "(said at 3:10; no captured frame shows it)" twice, and the second copy landed inside the quote's romanised transliteration (a defect; see below).
- *OFF*: no changes, as designed.

| Rule | Result | Evidence |
|---|---|---|
| 1. Quote fidelity | pass | ON 41 report quotes, OFF 60, none failing |
| 2. Attribution | **fail** | 1 confirmed ON error, 3 votes of 3. The judges claimed none in ON. Sweeps checked 262, 193 and 78 sentences; one candidate, confirmed: "Values far outside the 25%–75% range — his examples are 10, 15,000, 0 and 1 — count as outliers (16:04)". DeepLoop Circle says "1024 या फिर है 15,000 … 0 या फिर वन"; the only "10" is the handwritten "10%" in the `[VISUAL @ 17:14]` span. The OFF report, from the same speech, has "1,024, 15,000, 0 and 1" |
| 3. Substance | **fail** | ON 1 (GPT-5.5, 8 vs 8), OFF 0, tie 2 (Sonnet 5 9 vs 9; Gemini 3.1 Pro 9 vs 9). Mean substance 8.67 vs 8.67; visual use 8.67 vs 7.33 |
| 4. Fabrication | not verified | Run 9 had already failed rules 2 and 3, so rule 4 could not change the outcome. Raw judge claims: ON 14, OFF 14 (judge files kept with the run) |
| 5. Guard sentences | pass | 6 distinct sentences, 3 attribution lenses and the fabrication lens each: 1 attribution vote upheld of 18 (the confidence-band sentence, whose composer-written "is also visible on screen" still implies speech; 2 of 3 refuted), no fabrication upheld |
| 6. Substance loss | pass | (a) every detail in the guard records is still in the report; (b) ON mean 8.67 ≥ 7.67 |

**Outcome, as pre-registered:** run 9 fails rules 2 and 3. The guard does not meet D-105's bar, so run 10 is not run and visual analysis stays hidden ([D-106](../decisions.md#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24)).

**Why the error got through.** The map stage wrote "such as 10, 15,000, 0, or 1 in the speaker's examples", labelled `said`. The guard found the "10" in the 17:14 span and not in the speech, and correctly classed it as screen-only. It acts on one strong detail or two weak ones, though, and a lone two-digit figure is weak by design, because "10" occurs in so many spans (`10%`, `figsize=(10, 6)`, axis ticks) that a mark would often cite the wrong thing. Below that threshold the error passed unmarked. The shape is the familiar one, a screen detail inside a speaker credit, now in its smallest form, and again in a non-English video.

**Also found** (none confirmed as attribution errors):
- A guard mark landed inside the romanised transliteration of a Bengali quote. Four verifiers called it a formatting defect, not a misattribution.
- The processing note says marked details were "found only on screen". Where the speech is Bengali, or the captions garble the word ("dot PI plot" for `.pyplot`), the detail was also spoken, and the guard simply could not read it. The marks themselves are true; the note overclaims.
- Four of the five "on screen" marks sit on code the speaker also said. They are redundant rather than wrong, and every verifier refuted them as errors.
- Outside attribution, sweep 1 reported two fabrication-class slips: DeepLoop's "सिक्स" read as "six" where the speaker means "sex", and a Seaborn conclusion credited to Gate Smashers that belongs to CodeWithMunnaX. Rule 4 was not verified, so these are not counted.

**What run 9 shows.** The guard did what it was built to do: every one of its own changes held up under verification, the note on the spoken version number included. But the run still carried one confirmed error, the same count as run 8 without the guard. The substance tie means R1's quality claim (rule 3) failed for a reason the guard cannot touch: on this run the judges found the annotated report exactly as substantive as the plain one.

## Runs 10 and 11: pre-registered (2026-10-25, before either run exists)

The user decided rule 3 for this pair ([D-107](../decisions.md#d-107--r1s-substance-rule-a-tie-passes-any-loss-fails-attribution-stays-zero-error-2026-10-25)): *"For the next pre-registered pair of R1 runs, count a substance tie (no loss) as passing rule 3. Attribution stays zero-error."* Everything else is carried over from runs 9 and 10 unchanged.

**Code.** Both arms of both runs are regenerated on one commit: master after the guard follow-ups T-1.18.9.5 to .7 merge. The results name that commit, and nothing changes between run 10 and run 11.
- T-1.18.9.5: lone figures in speaker credits.
- T-1.18.9.6: quote transliterations treated as quotation.
- T-1.18.9.7: an accurate processing note.
- T-1.18.9.10 (added 2026-10-25, before either run): the "also" in "also visible on screen" is removed when the detail is screen-only around the cited moment. This was run 9's one upheld guard-sentence vote. No rule changes.

**Setup, as for run 9.**
- Job `419e691d`, with `--descriptions data/r1_ab/retier/baseline_describe.json` (gpt-5.5, D-081) and the models in `backend/.env`.
- Judges: GPT-5.5, Sonnet 5 and Gemini 3.1 Pro, all medium. No substitutes: a run waits for the Gemini quota, through a background waiter.

**Verification.**
- Three lenses for every claim from every judge, in both arms and of both kinds. Unlike run 9, every judge claim is verified.
- Three independent sweeps of ON, with three refuters per distinct candidate.
- Three attribution lenses and the fabrication lens for every sentence the guard changed.
- The majority decides. The D-075 multilingual rule applies.

**Pass rule.** Both runs must pass every item:
1. Quote fidelity: `audit_quote_fidelity.py --check` exits 0 (unchanged).
2. Attribution: zero confirmed attribution errors in ON, in either direction, counting every judge's claims, the sweep and the guard's own changes (unchanged).
3. **Substance (amended, D-107):** ON's substance is equal to or higher than OFF's, on both measures, with no margin:
   - (a) ON's mean substance across the three families ≥ OFF's;
   - (b) at least as many families prefer ON as prefer OFF (a tie counts for neither).

   A loss on either measure fails.
4. Fabrication: ON has no more confirmed fabrications than OFF, with every judge claim verified (unchanged).
5. No rise in fabrication from the guard: zero confirmed errors of either kind among the sentences it changed (unchanged).
6. No substance loss beyond noise: every detail in a guard record is still in the report, and ON's mean substance is ≥ 7.67 (unchanged).

**Outcomes, fixed now.**
- Both runs pass: set `featureFlags.visualAnalysis = true`, record a decision that supersedes D-105, and update S-1.18.2, the L6 status and the CHANGELOG.
- Rule 1 fails: the run is invalid. The defect is fixed in its own change and the run is repeated; it does not count toward the two.
- Anything else fails in either run: the result is recorded and the flag stays off. If run 10 fails, run 11 is not run.

## Guard follow-ups: offline check before run 10 (2026-10-25)

The old guard (master before the follow-ups) against the new one, on the stored ON reports of runs 1 to 9 and the persisted map items of runs 5 to 9. Run 9's report was guarded in production, so its seven marks were stripped first. This is in-sample: the follow-ups were written from these runs, and it is no substitute for runs 10 and 11.
- Confirmed errors caught: 9 of 11, up from 8 of 11. The new catch is run 9's "his examples are 10 (on screen at 17:14), 15,000, 0 and 1".
- New marks from the possessive credit, besides run 9's: 4 (2 in run 7, 2 in run 9), all on DeepLoop Circle's code identifiers (`flipper_length_mm`, `body_mass_g`), each shown in a frame within the cited window. These are the same class as run 9's redundant marks on code, which every verifier refuted as errors.
- "Also" removed: 7 (4 in run 1, 3 in run 9), each leaving a true "visible on screen".
- Run 9's mark inside the transliteration is gone. Runs 2 to 6 and 8 are unchanged. At the map stage, the one new listed item is run 9's "10".

