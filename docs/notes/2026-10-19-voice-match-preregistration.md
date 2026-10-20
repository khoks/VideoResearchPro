---
status: pre-registered — do not edit after the run starts
story: S-3.3.4
date: 2026-10-19
---

# Voice-match harness: what is tested and the pass rule, fixed before the run (S-3.3.4)

S-3.3.4 is the gate for S-3.4 ("speak as me"). This note fixes the material, the conditions, the judges and the pass rule **before any draft is generated or judged**. It is merged on its own first, so the record shows the rule came before the numbers. The result will be recorded against this rule as written, including if it fails.

## The question

The question is whether Mode A, as the plan designs it, makes a draft sound more like its writer than a neutral draft, without making it worse writing. Mode A is retrieval plus exemplars, with no fine-tuning ([plan](../plans/l3-echo-personal-brain.md), Domain 4).

## Material

- **Writers.** The three synthetic writers in `backend/tests/fixtures/echo_voice/personas.json`: Asha, Bharat and Chetan. Synthetic because, on 2026-10-19, the install holds no real user's writing (no notes and 4 questions). That rules out the user-as-judge tier for now (see the last section).
- **Held-out texts.** Six per writer (`held_out`). Extraction, retrieval and the drafter never see them; only the judges and the automatic score do.
- **Prompts.** Six per writer, 18 in all, in `backend/tests/fixtures/echo_voice/draft_prompts.json`, written before this run.

## Pipeline

1. **Extraction.** S-3.3.2 as shipped, with the registry's economy model, over each writer's notes and questions in a scratch database.
2. **Retrieval.** S-3.3.3 as shipped: sync the writer's signals into `personal_context_global`.
3. **Two drafts per prompt**, from the same drafter, both told the writer's language:
   - **N (neutral):** the prompt and "Write a short note of 40 to 90 words in {language} reacting to this."
   - **V (voice):** the same, plus a trait card and five exemplars.
     - The trait card is the 8 signals nearest the prompt from `query_personal_context`, plus every `cadence` signal.
     - The exemplars are five of the writer's notes, chosen for **style diversity, not topic**: spread over the sentence-length range. The plan cites evidence that topical exemplar matching hurt attribution.
4. **Drafter:** `openai:gpt-5.5`, reasoning `low`, temperature left at its default. One draft per condition per prompt.

## Judges (declared before the run)

- **`anthropic:claude-sonnet-5`** (reasoning off) and **`google:gemini-3.6-flash`** (thinking low). Both are from families other than the drafter's.
- **Substitution, declared here.** Gemini 3.1 Pro is the usual Google judge, but its quota is shared and scarce, so **Gemini 3.6 Flash substitutes for it**, as in D-097.
- **Order.** The two drafts appear as A and B. The order is randomised per item with seed 3304; the judges are not told which condition is which.
- **Voice question.** The judge sees the writer's six held-out texts as "samples written by one person", then A and B, and is asked: "Which draft was more likely written by the person who wrote the samples? Answer A, B or UNSURE. Say UNSURE when they are about equally plausible." Abstaining is allowed and counted.
- **Quality question.** The judge sees the prompt and A and B, without the samples, and is asked: "Ignoring whose voice it is, which is the better note: clearer, more coherent, more useful to its reader? Answer A, B or TIE."
- **Verdict counts.** Each judge answers each question once per item: 36 voice verdicts and 36 quality verdicts.

## Tier (i): automatic authorship score

For each prompt, `s(V)` is `echo_stylometry.similarity` between the V draft and the writer's held-out profile; `s(N)` is the same for the N draft. Both drafts answer the same prompt, so topic is held equal and the difference measures style. Also recorded: per-draft attribution to the nearest of the three writers' held-out profiles.

## Pass rule

**Voice, tier (ii).** Passes only when all four hold:
1. V is preferred in **at least 70%** of the non-abstaining voice verdicts, pooled over both judges.
2. **Each judge alone** prefers V in at least 60% of its non-abstaining verdicts.
3. **At most 50%** of all voice verdicts abstain.
4. **No writer** has V preferred in fewer than half of their non-abstaining verdicts.

**Quality guard.** Passes when V is preferred or tied in **at least 40%** of the 36 quality verdicts. A voice win must not come from text that reads clearly worse.

**Automatic score, tier (i).** Passes when `s(V) > s(N)` in **at least 12 of 18** pairs. It is a regression gate: recorded, but it does not decide.

**What follows:**
- **Voice and quality both pass.** Mode A is good enough on synthetic writers to build S-3.4's agent on this design. S-3.4 still stays off for any real user until tier (iii) passes for that user.
- **Either fails.** S-3.4 does not start on this design. The result is recorded with its breakdown (by writer, by judge, by question) and the design is revisited.

## Tier (iii): the user as judge, fixed now, run when there is material

This is a blinded "which of these did you write?" test.
- **Pairs.** One real held-out note of the user, paired with one V draft written for a prompt that names that note's topic. The order is random.
- **Size.** At least 20 pairs.
- **When.** Only once the user has at least 40 live notes in the language tested.
- **Pass, the product gate for enabling S-3.4 for that user.** The user picks their own text in **at most 80%** of pairs (the draft is mistaken for theirs at least one time in five), and the quality guard above holds for the same drafts.

It is not runnable today, because the install holds none of the user's notes. The harness ships with a mode that builds the blinded pairs file and scores the user's answers.

## Cost estimate

Under $1: 36 drafts plus 72 judge calls plus three small extraction runs.
