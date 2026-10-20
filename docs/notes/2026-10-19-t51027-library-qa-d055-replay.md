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

## Results

*(appended after the run)*
