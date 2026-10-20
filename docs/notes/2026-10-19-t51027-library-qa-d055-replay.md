# T-5.10.2.7 — library Q&A, D-055 replay on the per-user corpus

**Status:** pre-registered 2026-10-19, committed before any answer was generated. Results are appended below the rule, never edited into it.

## Question

[D-055](../decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) asks, per use case, how much answer quality the production tier gives up against a stronger model at maximum effort on the same inputs. Its first run (2026-07-29) measured job Q&A only, before library Q&A was scoped to a per-user corpus ([D-063](../decisions.md#d-063--per-user-isolation-shared-cache-private-catalogue-2026-07-31)), keyed on `document_id` ([D-070](../decisions.md#d-070--document-visibility-keyed-on-document_id-not-the-legacy-video_id-2026-10-19)), and routed through the trust re-rank ([D-068](../decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18)). T-5.10.2.7 re-runs the method on **library Q&A as it now behaves**: is `library_qa_formulate_answer` under-modelled?

## Design

- **Corpus:** the user's library on copies of the dev database and Chroma store (200 visible documents, 92 channels, the reference job `0d4db8c3`'s corpus). The user has set no trust weights, so production's re-rank is the identity, which is the default every user starts from. The weighted path's cost is E-7.1's measurement, not this one.
- **Questions:** the ten fixed in [the E-7.1 protocol](2026-10-19-e71-trust-weighting-measurement.md), reused so nothing is chosen after seeing answers.
- **Production arm:** `POST /library/qa` through the real route. A spy records the exact system and user messages and the token budget the `library_qa_formulate_answer` call receives (production: `anthropic:claude-sonnet-5:medium`), plus the retrieved chunks.
- **Challenger arm:** the same messages, unchanged, through `anthropic:claude-opus-5:high`, given production's budget plus 32,000 tokens of thinking room. Its output goes through the same citation sanitiser production applies. So the two answers share retrieval, refinement, prompts and post-processing; only the model writing the answer differs (D-055 property 1).
- **Judging:** `judge_qa_pairs.py`: three blind judges from three families (GPT-5.5, Claude Sonnet 5, Gemini 3.1 Pro, medium reasoning), independent coin flips, the pooled excerpts the answers were built from; relevance and faithfulness 1–10, unsupported claims, preference. Every flagged claim gets three verifier lenses, 2-of-3 majority. Excerpts now carry no publication dates, as in E-7.1; that inflates both arms equally.

One judge family (Claude) is also the family of both arms. D-055's mitigation applies: the bias, if any, is the same for both arms, since both are Claude.

## Decision rule (fixed now)

**Re-tier warranted** if both hold:

1. The challenger is preferred by at least 2 of 3 judges on at least 7 of the 10 questions.
2. Its mean relevance or mean faithfulness is at least 1.0 higher than production's.

If so, a follow-up story is filed to re-tier `library_qa_formulate_answer`, with a cost comparison; the registry is not changed here. Otherwise the result is recorded as **no re-tier warranted**, with the numbers. Confirmed unsupported claims are reported per arm either way.

## Known limits

- One corpus, ten questions, one run per arm: direction, not effect size.
- The challenger is one step up the same family; the 2026-07-29 run used a different challenger (Claude Fable 5 via subagents) on different questions, so its job-Q&A gaps (5.8 → 8.5 and 7.2 → 7.7) are context, not a baseline.

## Results (appended 2026-10-19; the rule above was not edited)

**Run.** 10 questions, both arms per question, all through the production route on fresh copies of the dev database (migrated to head) and Chroma store. Production `anthropic:claude-sonnet-5:medium`; challenger `anthropic:claude-opus-5:high` with production's budget plus 32,000 tokens of thinking room. Code: commit `57c582f` (master after S-5.10.3, with notes in retrieval, S-8.5.2). The user has no trust weights and, on the copy, no notes, so every answer took the unweighted per-user path. 30 blind verdicts, all parsed; 207 flagged claims, each checked by three lenses.

| | Challenger | Production |
|---|---|---|
| Judge verdicts preferring (tie: 1) | 8 | 21 |
| Questions won (≥ 2 of 3 judges) | 2 | 7 |
| Mean relevance (1–10) | 8.63 | 8.97 |
| Mean faithfulness (1–10) | 6.63 | 7.77 |
| Confirmed unsupported claims | 119 | 54 |
| Mean words per answer | 1559 | 1082 |

By judge, challenger / production / tie:

| Judge | Verdicts |
|---|---|
| claude-sonnet-5 | 4 / 5 / 1 |
| gemini-3.5-flash | 2 / 8 / 0 |
| gpt-5.5 | 2 / 8 / 0 |

Per question (C = challenger preferred, P = production, = tie): q1: PC=, q2: PPP, q3: PPP, q4: PPC, q5: PCC, q6: PPP, q7: PPP, q8: PPC, q9: PCC, q10: PPC.

**Against the rule.** Challenger won 2 of 10 questions (needs 7) and its largest mean gap is -0.33 (needs +1.0). **No re-tier warranted.** Library Q&A on the per-user corpus is not measurably under-modelled at Sonnet 5 medium; the registry stays as it is.

**Deviation from the protocol.** Gemini 3.1 Pro had exhausted its daily quota (it ran out during E-7.1's verification the same day), so the Google judge and verifier lens were `gemini-3.5-flash` (medium and low reasoning) instead. Three families are still represented; the named model is not.

**Length.** Challenger answers averaged 1559 words against production's 1082, under the same length guidance in the prompt. Judges are told not to reward length; more text also means more claims to be unsupported.

**What the unsupported claims are.** 104 of the challenger's 119 confirmed claims, and 50 of production's 54, name a date or a year. The excerpts judges and verifiers saw carried no publication dates, while the answer prompt does (D-072), so a correctly cited date reads as invented. The protocol said this "inflates both arms equally"; it does not, because the challenger cites dates far more often. The remaining claims are mostly statements about what the sources do not cover.

**Sensitivity check, outside the rule: the same answers re-judged with dated excerpts.** `judge_qa_pairs.py --dates-db` adds each source's `published <date>` to the excerpts, as the answer prompt shows it; fresh coins, same judges and verifiers. Verdicts challenger / production / tie: 15 / 11 / 4; questions won 6 / 3; mean relevance 9.03 / 9.00; faithfulness 8.80 / 8.93; confirmed unsupported claims 18 / 8. The conclusion holds with dates visible.

**Caveats.** Ten questions, one run per arm. Excerpts given to judges and verifiers still carry no publication dates, which inflates unsupported-claim counts equally for both arms (the E-7.1 caveat; T-7.1.2.3 fixes the harness). Both arms are Claude, so any Claude-judge self-preference applies to both.
