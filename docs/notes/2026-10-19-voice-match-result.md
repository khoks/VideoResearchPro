---
status: result
story: S-3.3.4
date: 2026-10-19
---

# Voice-match harness: result against the pre-registered rule (S-3.3.4)

The rule was fixed in [2026-10-19-voice-match-preregistration.md](2026-10-19-voice-match-preregistration.md) (merged in #338) before any draft was generated. This note applies it as written. Raw data, with every draft, trait card and verdict: [2026-10-19-voice-match-result.json](2026-10-19-voice-match-result.json).

## Verdict

**Voice and quality both pass.** Mode A is good enough on synthetic writers to build S-3.4's agent on this design. It stays off for any real user until tier (iii) passes for that user.

| Rule | Measured | Result |
|---|---|---|
| Voice 1: V preferred in at least 70% of non-abstaining verdicts | 100% | **pass** |
| Voice 2: each judge alone at least 60% | claude-sonnet-5 100% of 18, gemini-3.6-flash 100% of 18 | **pass** |
| Voice 3: at most 50% abstain | 0% of 36 | **pass** |
| Voice 4: no writer below half | asha 100% of 12, bharat 100% of 12, chetan 100% of 12 | **pass** |
| Quality guard: V preferred or tied in at least 40% | 47% (V 17, N 17, tie 0, unparsed 2) | **pass** |
| Tier (i): s(V) > s(N) in at least 12 of 18 (regression gate, not deciding) | 15 of 18 | **pass** |

- **Run settings.** Drafter `openai:gpt-5.5:low`. Judges `anthropic:claude-sonnet-5:off`, `google:gemini-3.6-flash:low`; `gemini-3.6-flash` was declared in advance as the substitute for Gemini 3.1 Pro. Seed 3304.
- **Spend.** $0.31 in all.
- **The first launch was stopped before any verdict.** It failed at the first judge call because `claude-sonnet-5` refuses an explicit temperature of 0 ("temperature is deprecated for this model"). The harness now passes 1.0, every provider's default; the pre-registration fixed no judge temperature. It was then relaunched from the start. Nothing from the first launch was scored.
- **Unparsed quality verdicts.** 2 quality verdicts named neither draft. As written, they count against the voice draft.
- **Tier (i) attribution.** Assigning each draft to the nearest writer's held-out profile put 15 of 18 voice drafts with the right writer, against 12 of 18 neutral drafts.

## Every item

V is shown as A or B by the seeded coin. Each verdict is the letter the judge picked.

| Writer | Prompt | V shown as | Voice verdicts | Quality verdicts | s(V) / s(N) |
|---|---|---|---|---|---|
| asha | A news article says a new import duty on electronics will pr | A | claude A; gemini A | claude B; gemini B | 0.649 / 0.443 |
| asha | A friend forwards a study claiming remote work raises produc | A | claude A; gemini A | claude A; gemini B | 0.527 / 0.373 |
| asha | A video argues the central bank should cut rates because inf | A | claude A; gemini A | claude B; gemini B | 0.608 / 0.354 |
| asha | A founder on a podcast credits their success to waking up at | A | claude A; gemini A | claude A; gemini A | 0.704 / 0.260 |
| asha | A report says exports in a new sector grew 40 percent last q | B | claude B; gemini B | claude UNPARSED; gemini A | 0.278 / 0.514 |
| asha | An influencer says a single chart proves the housing market  | B | claude B; gemini B | claude B; gemini A | 0.538 / 0.343 |
| bharat | A popular documentary blames the Mughal decline on one emper | B | claude B; gemini B | claude B; gemini B | 0.674 / 0.654 |
| bharat | A lecture claims the railways in colonial India were built m | A | claude A; gemini A | claude UNPARSED; gemini B | 0.534 / 0.446 |
| bharat | A review praises a new history of the 1857 uprising for its  | A | claude A; gemini A | claude A; gemini A | 0.548 / 0.644 |
| bharat | A podcast compares the British Empire to Rome. | A | claude A; gemini A | claude A; gemini A | 0.517 / 0.510 |
| bharat | An article describes the 1950s as a golden age of Indian pla | A | claude A; gemini A | claude B; gemini B | 0.575 / 0.575 |
| bharat | A talk argues the Permanent Settlement of 1793 was a complet | A | claude A; gemini A | claude A; gemini A | 0.641 / 0.509 |
| chetan | A quick-commerce startup raised a huge round and promises 10 | A | claude A; gemini A | claude A; gemini B | 0.419 / 0.358 |
| chetan | A founder posts that their app hit one million downloads in  | B | claude B; gemini B | claude B; gemini A | 0.482 / 0.426 |
| chetan | An investor says profitability does not matter in a startup' | B | claude B; gemini B | claude A; gemini A | 0.522 / 0.415 |
| chetan | A friend wants to start a D2C brand and spend most of the mo | A | claude A; gemini A | claude A; gemini B | 0.558 / 0.365 |
| chetan | A podcast guest says AI will replace all customer-support jo | A | claude A; gemini A | claude B; gemini B | 0.437 / 0.382 |
| chetan | A food-delivery company announces it is finally profitable. | A | claude A; gemini A | claude A; gemini A | 0.469 / 0.351 |

## Checks beyond the rule

These checks were not part of the pass rule. They test whether the win could have an uninteresting cause.

- **Position.** The seeded coin showed V as A 13 times and as B 5 times. V won every verdict where it was B (10 of 10), so position does not explain the result.
- **Copying.** 0 of 18 voice drafts share any run of four words with the writer's notes; 1 of 18 neutral drafts do. The style transferred without lifting sentences from the exemplars.
- **Length.** Voice drafts average 69 words, neutral drafts 62.
- **Judge agreement.** The two judges agreed on 18 of 18 voice items.
- **A ceiling, not a margin.** The writers were built to differ sharply, and the neutral drafts are generic. A 100% preference shows the pipeline carries style through; it cannot show how fine a difference the pipeline captures. Tier (iii) and real writing will.

## One pair, in full

Writer **chetan**, prompt: "A quick-commerce startup raised a huge round and promises 10-minute delivery everywhere."

- **Neutral:** 10-minute delivery ka promise sunne mein exciting lagta hai, but “everywhere” thoda over-ambitious bhi hai. Funding se speed, dark stores aur logistics improve ho sakte hain, par traffic, unit economics, rider safety aur local demand ka real test hoga. Convenience achhi hai, lekin sustainable model aur fair working conditions bhi utne hi important hain. Hype se zyada execution matter karega.
- **Voice:** haha headline mast hai, par 10-minute delivery everywhere ka maths kaun samjhayega? dark stores, riders, inventory, wastage, rent — sab ka bill kaun pay kar raha hai? agar customer delivery fee nahi de raha, toh subsidy ka pump kab tak chalega 😂 mujhe toh retention, basket size, contribution margin aur repeat frequency dekhni hai. execution solid ho toh game hai, warna naam bada aur unit economics chhote!
- **Trait card the voice draft got:** personality · interest: Repeatedly focuses on startup economics, sustainability, and operational fundamentals.; personality · recommendation lens: Evaluates businesses by who pays, why they pay, and whether the model can sustain itself.; style · cadence: Uses exclamation marks often; personality · perception lens: Reads startup success through execution and operational reality rather than branding or hype.; personality · preferred solution: Prefers simple, focused execution backed by sustainable unit economics.; style · cadence: Asks questions often (more than one sentence in seven); personality · methodology: Works things out by examining data, customer feedback, retention, and concrete operating metrics.; style · cadence: Writes in medium-length sentences (12 to 20 words on average); style · cadence: Uses emoji; style · cadence: Often starts sentences in lowercase

## What this does and does not show

- **Scope.** These are synthetic writers, built to differ in style, judged by models. A pass shows that the Mode A pipeline carries a writer's style into a draft better than a neutral prompt. It does not show that a real user would mistake a draft for their own writing; that is tier (iii), which waits for at least 40 of the user's own notes (the install has none).
- **The automatic score.** Tier (i) is stylometric similarity over function words and character trigrams. It is a regression gate, and short drafts make it noisy.
