# Newsletter featured section: blind judging (S-6.4.1)

**Status:** protocol fixed before any featured section was generated or judged (2026-10-19). Results are appended below; the protocol is not edited after the run.

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

_(appended after the run)_
