# Newsletter featured section: blind judging (S-6.4.1)

**Status:** complete (2026-10-19). Protocol fixed before any featured section was generated or judged; results appended below. Outcome: `featured` is off by default ([D-097](../decisions.md#d-097--newsletter-featured-section-ships-opt-in-the-rest-of-an-issue-is-listed-from-the-database-2026-10-19)).

## Question

Is the model-written featured deep-dive (`author_newsletter_compose`, claude-sonnet-5 at reasoning low) better for the reader than the source's own summary paragraph, without unsupported claims? The answer decides whether the `featured` section is on by default in new issues and subscriptions.

## Material

Four real reports from the development library (one tenant): matplotlib and seaborn tutorials; machine learning explained in Hinglish; an Indian startup founder podcast (Hinglish); personal finance and career advice in Hinglish. There are no knowledge reports in that account, so none are judged.

For each report, built from a copy of the database by the production code (`newsletter._featured_source` and `_compose`):
- **model**: the featured section the call writes, markers turned into links;
- **summary**: what the issue shows when the call is unusable, the report summary's first cited paragraph (up to 120 words), links made the same way.

Both arms see the same excerpt (the report's summary section and what follows, up to 1,200 words, citations as markers).

## Judging

`backend/scripts/judge_pair.py --rubric featured`: coin-flipped labels, each judge sees both versions and the source excerpt they were written from, scores faithfulness and usefulness, lists unsupported claims with quotes, and states a preference.

Judges, named before the run: `openai:gpt-5.5:medium`, `anthropic:claude-opus-5:medium`, and **`google:gemini-3.6-flash:medium` as the Google judge**, because `gemini-3.1-pro-preview`'s 250-requests-a-day quota is shared across sessions and was exhausted during D-093's run. The model arm is written by an Anthropic model; Opus is a different model but the same family, so rule 2 leans on the other two judges.

## Decision rule (fixed in advance)

`featured` is on by default if **all** of these hold:

1. At least 8 of the 12 verdicts (4 reports × 3 judges) prefer **model**, and on no report does a majority prefer **summary**.
2. The two non-Anthropic judges prefer **model** in at least 6 of their 8 verdicts.
3. Unsupported claims attributed to **model**, summed over all judges, are at most 4 (one per report on average). The only flags discarded are those that quote text appearing in neither section.

Otherwise `featured` is off by default and opt-in, and the issue shows only the lists. Cost per issue is recorded from `usage_json` whatever the outcome.

## Results

**Defects found while generating the arms, fixed before any judge saw them** (and covered by tests):
- **Excerpts with no citations.** Three of the four excerpts held no citation marker at all. The summary-first excerpt filled its 1,200 words with long, uncited summary prose. Two sections then cited nothing and fell back. The excerpt is now the summary (300 words) plus the report's cited points.
- **Invented markers resolved.** One section cited three markers that were not in its excerpt, invented by the model. They resolved because every marker in the report was accepted. Only markers shown to the model are valid now.
- **Doubled timestamps.** The summary arm printed "0:00 ([0:00](…))"; a timestamp followed by its own marker now becomes the link itself.

The arms were then regenerated. All four model sections cite, with 7 to 23 links each, and run 257 to 306 words.

**Judging deviation:** `claude-opus-5` returned malformed JSON for report 4, which gave no verdict. That one judge call was re-run.

| Report | Judge | Prefers | Faithfulness model / summary | Usefulness model / summary | Flags on model |
|---|---|---|---|---|---|
| 1 | gpt-5.5 | model | 8 / 10 | 9 / 3 | 2 |
| 1 | claude-opus-5 | model | 7 / 9 | 8 / 3 | 3 |
| 1 | gemini-3.6-flash | model | 10 / 10 | 10 / 2 | 0 |
| 2 | gpt-5.5 | model | 8 / 10 | 9 / 2 | 0 |
| 2 | claude-opus-5 | model | 7 / 9 | 9 / 2 | 3 |
| 2 | gemini-3.6-flash | model | 10 / 10 | 10 / 2 | 0 |
| 3 | gpt-5.5 | model | 7 / 10 | 9 / 2 | 3 |
| 3 | claude-opus-5 | model | 8 / 9 | 9 / 3 | 3 |
| 3 | gemini-3.6-flash | model | 10 / 10 | 10 / 1 | 0 |
| 4 | gpt-5.5 | model | 8 / 8 | 9 / 2 | 1 |
| 4 | claude-opus-5 | model | 8 / 9 | 9 / 2 | 1 |
| 4 | gemini-3.6-flash | model | 10 / 10 | 10 / 1 | 0 |

- Rule 1: 12 of 12 verdicts prefer **model**. **Met.**
- Rule 2: the non-Anthropic judges prefer **model** in 8 of 8. **Met.**
- Rule 3: 16 unsupported claims attributed to **model**, against at most 4. **Not met.** All quote text from the model section, so none is discarded.

**Outcome: `featured` is off by default and opt-in** ([D-097](../decisions.md#d-097--newsletter-featured-section-ships-opt-in-the-rest-of-an-issue-is-listed-from-the-database-2026-10-19)).

What the flags are (not part of the rule):
- **A marker on the wrong moment.** For example, a claim the excerpt places at 5:49 was cited to 0:13. This is the most common real defect, and the most useful thing the judging found: the model copies real markers but attaches some to neighbouring points.
- **Conclusions the excerpt does not draw.** For example, "disagreement is about … which library to teach first" and "both push savings higher".
- **A plain timestamp copied without its marker**, for example "(15:14)".

Gemini 3.6 Flash flagged nothing in any section and scored every version 10 for faithfulness, so the flags come from the other two judges.

Cost per issue for the featured call: $0.015 to $0.017 (4,800 to 5,300 input tokens, 550 to 700 output) on claude-sonnet-5 at reasoning low.
