# Code-mixing labelled set (S-1.16.2)

`labelled_units.json` — 300 units labelled per token for language
(Hindi/Urdu, English, neither) and per unit for matrix language. Built
2026-10-19 from three Hinglish topic jobs on the dev backend: YouTube comments
on their videos (romanised Hindi as people type it), their Latin and
Devanagari auto-captions, and 20 English library transcripts. Comments are
stored as text only, with no author names or IDs; URLs, handles and
timestamps were stripped.

`llm_predictions.json` — the `code_mixing_detect` model's raw answers for every
unit (`gpt-5.6-luna`, reasoning off), so the test suite scores the LLM detector
without calling a provider. `scripts/eval_code_mixing.py --llm` regenerates it.

Annotation markup, labelling conventions, sampling, the DEV/TEST split, who
labelled it and the results:
[docs/notes/2026-10-19-code-mixing-detection.md](../../../../docs/notes/2026-10-19-code-mixing-detection.md).
Do not tune anything against the `test` split.
