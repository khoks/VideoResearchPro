# E-7.1 trust-weighted retrieval — measurement protocol (T-7.1.1.5)

**Status:** pre-registered 2026-10-19, committed before any answer was generated. Results are appended below the rule, never edited into it.

## Question

[D-068](../decisions.md#d-068--curated-source-ranking-v1-per-tenant-trust-weight-re-ranks-retrieval-perspective-banding-deferred-2026-10-18) re-ranks retrieval as `distance / weight` over a 3× pool, after the raw relevance threshold. Two things must be true before it is called done:

1. **It works.** When a user raises a channel's weight, that channel's passages actually move up in the context the answer is built from, and a lowered channel's move down.
2. **It does not cost relevance.** A trust preference must not make answers less relevant to the question or less faithful to the sources. D-068's whole argument for weighting *after* the threshold is that it only reorders what is relevant; this checks that claim on real answers.

## Corpus and arms

- Reference job `0d4db8c3` (the user's account): 200 approved videos from 92 channels, about 947K transcript words, with a completed report. The user's library is the same 200 documents, so job and library Q&A search the same corpus. Job Q&A also reads the report; library Q&A does not.
- Run on **copies** of the dev database (migrated to head) and the Chroma store (with the D-070 `document_id` backfill), so nothing the running backend uses is touched.
- **OFF:** every weight neutral (1.0). **ON:** the weights below. Same code, same models, same corpus, same day; the arms differ only in the weights. Each question is asked on both surfaces in both arms, with the arm order per question drawn by coin (seed 71).

**Weights, chosen by rule, not by looking at answers.** Channels with at least 5 approved documents in the job (10 qualify), shuffled with `random.Random(68)`: the first three to **2.0**, the next three to **0.0** (clamped to 0.05 at query time), the rest stay 1.0.

| Weight | Channels (documents in the job) |
|---|---|
| 2.0 | IBM Technology (20), IndyDevDan (11), Volo Builds (7) |
| 0.0 | LangChain (10), AI Engineer (7), Google Cloud Tech (5) |
| 1.0 | AI Jason (10), bycloud (13), Prompt Engineering (5), Cole Medin (7), and the other 82 channels |

**Questions** (written from the job topic only, before any answer):

1. What practices do the sources recommend for writing instruction or rules files (such as CLAUDE.md or Cursor rules) for agentic coding tools?
2. How do the sources describe the Model Context Protocol (MCP), and what problems is it meant to solve?
3. What differences do the sources draw between single-agent and multi-agent architectures for software engineering tasks?
4. What do the sources say about when to use retrieval-augmented generation rather than fine-tuning or a long context window?
5. How do the sources recommend handling context-window limits during long agentic coding sessions?
6. Which risks or failure modes of agentic coding tools do the sources warn about, and how do they suggest mitigating them?
7. How do the sources describe evaluating LLM-based features or agents before shipping them?
8. What role do sub-agents or parallel agents play in the workflows the sources describe?
9. What do the sources say about cost and latency trade-offs between LLM models for coding work?
10. How do the sources suggest structuring a codebase or workflow so that AI coding agents work well in it?

## Measures

- **M1 — mechanism.** For each answer, the share of retrieved chunks (the deduplicated context handed to the refine step) whose channel is promoted, and the share whose channel is demoted; the same for the cited references.
- **M2 — the threshold guarantee.** The number of retrieved chunks in ON whose raw distance exceeds `RAG_DISTANCE_THRESHOLD`.
- **R — relevance and faithfulness.** Three blind judges from three model families (`openai:gpt-5.5:medium`, `anthropic:claude-sonnet-5:medium`, `google:gemini-3.1-pro-preview:medium`), each given the question, both answers under independently coin-flipped labels, and the excerpts each answer was built from (pooled and unlabelled, so the excerpts do not reveal the arm). Each scores both answers 1–10 on *relevance* (does it answer the question asked) and *faithfulness* (is every claim supported by the excerpts), lists unsupported claims, and states a preference. Judges are told nothing about weights or channels.
- **V — verification.** Every unsupported claim a judge lists is checked by three verifier lenses (one per model family, low reasoning) against the excerpts that answer was built from; a claim is *confirmed* unsupported on a 2-of-3 majority. Job-Q&A claims may also be supported by the report, so the job-Q&A verifiers see the report text too.

## Decision rule (fixed now)

Weighting ships as built (it applies only for users who set a weight; the default stays neutral) if **all** hold:

1. **M1:** across the 20 answer pairs, the mean promoted-channel share of retrieved chunks is higher in ON than in OFF, and the mean demoted share is lower; and the promoted share rises on at least 7 of the 10 job-Q&A questions.
2. **M2:** zero ON chunks over the raw threshold.
3. **R:** mean relevance ON ≥ mean relevance OFF − 0.5 (over all judges and pairs), **and** of the non-tie preferences, at most 60% favour OFF.
4. **V:** confirmed unsupported claims in ON ≤ those in OFF + 2, over all 20 pairs.

If 1 or 2 fails, the implementation is wrong and is fixed before merging. If 3 or 4 fails, weighting is recorded in D-068 as **hurting relevance** with the numbers; the mechanism still ships, because no user's answers change until they set a weight, but the formula (pool size, floor, range) is reopened as a follow-up rather than tuned here.

## Known limits

- One corpus, one topic, one weight assignment. A pass says the formula is safe on a broad, many-channel corpus; it does not say any particular weight is a good idea.
- The judges cannot know which sources the user trusts, so R measures whether weighting costs relevance, not whether it delivers what the user wanted; M1 is the evidence for the latter.
- Ten questions per surface: direction, not effect size.

## Results

*(appended after the run)*
