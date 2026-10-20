# S-8.5.2 — note retrieval weight: pre-registered measurement (2026-10-19)

**Status:** pre-registered before any run. Results are appended below the rule and the rule is not edited after the run.

**Why.** T-8.5.2.2 ships notes into the D-068 re-rank at `NOTE_RETRIEVAL_WEIGHT = 1.5`, the M5 plan's starting value. The plan's open question 1 asks whether to start at 1.5 or at 1.0. The board says to measure before tuning. D-068's own measurement found that strong channel weights cost breadth. Notes are few, and each is a single vector, so concentration should be small; this checks that rather than assuming it.

**What this can and cannot show.** The user has written no notes yet, so there is nothing real to replay, and an answer-level blind judgement (the E-1.14 method) has no honest input. This measurement is retrieval-level and deterministic, with no LLM calls. It shows where a note lands among the transcript chunks the answer is built from, what it displaces, and whether anything off-topic gets in. It does not show whether answers get better. That judgement waits for real notes; see "Follow-up" below.

## Setup

- **Corpus:** the reference job `0d4db8c3` (200 approved videos on LLMs and agentic coding, about 5.2K chunks). A copy of the Chroma store is read; the user's store is not touched.
- **Retrieval:** the original question only (no sub-query expansion, so no LLM). Transcript retrieval is `chroma_service.query_collection` scoped to the 200 documents with `top_k = 15` and threshold 0.6, exactly as `_scoped_query` does unweighted. Notes come from `note_index.query_notes` for one synthetic tenant over all its notes (library-style scope), merged by `qa_agent._with_notes`.
- **Weights:** `NOTE_RETRIEVAL_WEIGHT` ∈ {1.0, 1.5, 2.0}, plus a no-notes baseline.

### Notes (written before the run, as a user would write them)

On-topic, each paired with one question:

| Id | Note | Paired question |
|---|---|---|
| N1 | My view: context engineering is mostly about pruning, not adding. Every time I stuffed more docs into the window the agent got worse; trimming to the three files it actually edits fixed it. | Q1 |
| N2 | I stopped using most MCP servers. A plain CLI the agent can call is easier to debug and burns far fewer tokens on tool descriptions. | Q2 |
| N3 | Writing the spec first only works if the spec is short. Two pages at most, or the agent drifts and I end up reviewing the spec instead of the code. | Q3 |
| N4 | Multi-agent setups failed for me when the agents shared one scratchpad. Giving each sub-agent its own context and a single orchestrator is what worked. | Q4 |
| N5 | Long contexts degrade quietly. I now restart the session after roughly 100k tokens instead of trusting the model to remember the early instructions. | Q5 |

Off-topic, which must never enter any context:

| Id | Note |
|---|---|
| N6 | Sourdough: feed the starter with rye the night before and bake covered for the first twenty minutes. |
| N7 | Marathon plan: long run on Sundays, add two kilometres a week, rest week every fourth week. |
| N8 | Remember to file the property tax return before the end of the month. |
| N9 | Lisbon trip: tram 28 is packed by ten; walk up to the castle early instead. |
| N10 | The fiddle-leaf fig wants bright indirect light and water only when the top soil is dry. |

### Questions

| Id | Question |
|---|---|
| Q1 | What is context engineering and how should I manage what goes into an agent's context window? |
| Q2 | Should I use MCP servers with coding agents, and what are the alternatives? |
| Q3 | How does spec-driven development work with AI coding agents? |
| Q4 | What orchestration patterns make multi-agent systems work in practice? |
| Q5 | Why does LLM performance degrade as the input context gets longer? |
| Q6 | How do I set up a local agentic coding workflow? |
| Q7 | How can I reduce errors when using Cursor or other AI IDEs? |
| Q8 | What are the main agentic AI design patterns? |
| Q9 | How do self-improving agents learn from their own feedback? |
| Q10 | What does an AI engineering workflow look like at a product company? |

Q6–Q10 have no paired note. They show how often an on-topic note also reaches a neighbouring question; that is reported, not judged.

## Metrics

Per weight, over the questions:

- **M1 paired recall:** the share of Q1–Q5 whose paired note is in the final top 15.
- **M2 paired rank:** the paired note's mean position in the final top 15 (1 = first), over the questions where it is present.
- **M3 off-topic leaks:** the number of times N6–N10 appear in any question's final top 15.
- **M4 displacement:** the mean number of transcript chunks per question pushed out of the top 15 relative to the no-notes baseline.
- **M5 breadth:** the mean change in distinct channels in the top 15 relative to the baseline.
- Also reported: each paired note's raw distance against the top transcript chunk's distance.

## Decision rule (fixed now)

`NOTE_RETRIEVAL_WEIGHT` stays at 1.5 if all of these hold:

1. **M3 = 0 at every weight.** Otherwise the threshold guarantee is broken, and that is a bug to fix before any weight is discussed.
2. **M1 at 1.5 ≥ M1 at 1.0, and M2 at 1.5 ≤ M2 at 1.0.**
3. **At 1.5, M4 ≤ 1.0 chunk per question and M5 ≥ −1.0 channel per question.** Notes must not concentrate the context the way D-068's strong weights did.

If 2 holds only because 1.0 already reaches 100% recall, 1.5 still stays when it improves M2: the note's position decides how prominent it is to the refine step. If 3 fails, the result is recorded and 1.0 goes to the user as the proposal for open question 1.

## Follow-up

The answer-level comparison (does the answer use and cite the note, does it misattribute it) waits until real notes exist. It uses the E-1.14 blind-judge method on replayed questions with the user's own notes, weighted against unweighted.

## Results

Run 2026-10-19 with `backend/scripts/measure_note_weight.py`. The raw output is [`2026-10-19-s852-note-weight-results.json`](2026-10-19-s852-note-weight-results.json). The rule above was not edited.

| Weight | M1 paired recall | M2 paired mean rank | M3 off-topic leaks | M4 displaced chunks per question | M5 channel change per question |
|---|---|---|---|---|---|
| 1.0 | 1 of 5 | 13.0 | 0 | 0.1 | −0.1 |
| **1.5** | **5 of 5** | **5.0** | **0** | **0.7** | **−0.3** |
| 2.0 | 5 of 5 | 1.4 | 0 | 0.8 | −0.3 |

**Every clause holds, so `NOTE_RETRIEVAL_WEIGHT` stays at 1.5.**

1. No off-topic note entered any context at any weight. The nearest off-topic note was at a raw distance of 0.86 against a threshold of 0.6.
2. Paired recall rose from one note in five at 1.0 to all five at 1.5. The mean rank improved from 13 to 5.
3. At 1.5 a note displaced 0.7 transcript chunks per question and cost 0.3 distinct channels per question, inside the 1.0 and −1.0 limits.

**Why 1.0 is not a neutral start.** A note is one short sentence, and a transcript chunk is about 256 tokens of dense speech on the same subject. The paired notes' raw distances (0.29 to 0.55) ran about twice the best transcript chunk's (0.14 to 0.28) for the same question. At 1.0, notes that plainly answer the question sit below fifteen transcript chunks and almost never reach the answer. Equal weight is equal treatment of unequal lengths, not neutrality. 1.5 roughly offsets that gap. 2.0 pushes most notes to the top of the list, which is more prominence than relevance supports.

**Spill-over.** Among the unpaired questions, N4 (multi-agent orchestration) reached Q9 (self-improving agents) at 1.5, and also Q8 (agentic design patterns) at 2.0. Both are neighbouring subjects, and the note is a reasonable thing to show there.

**Limits.** The measurement is retrieval-level only, on synthetic notes written before the run. Whether answers use and cite notes well is the follow-up above.
