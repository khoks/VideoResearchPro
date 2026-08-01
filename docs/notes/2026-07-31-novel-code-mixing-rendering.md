---
status: raw — do not edit
captured: 2026-07-31
source: user message, verbatim
relates_to: docs/inventions.md N-001, docs/decisions.md D-066, requirement R5
---

# Verbatim user message — code-mixing rendering proposal

Preserved unedited for prior-art chronology. The user explicitly flagged this
as *"a candidate for novel invention"*, which is why the exact wording and date
are kept rather than only the synthesis.

> Do you remember what I originally said about R3, about the time of recording
> and time period being discussed in the video, and its impact on our knowledge
> extraction search ranking qna reporting etc. Also, R5 seems to be a candidate
> for novel invention if we carefully detect and handle the balance of words
> from different scripts and grammar used and syntax used in different portions
> of the speech. Because this is how the middle eastern, south asian and asian
> country people speak. They would say something like "and this is how we were
> preparing taaki baadme koi kasar koi zarra na reh jaye and so we kept on you
> know adding hum jodte rahe cheezein". Our agentic harness should be able to
> understand this in its true spirit, maybe translate everything in English for
> parsing analysis extraction etc and keep as it is for quoting i.e. with the
> English words in Roman script and Hindi/Urdu words in their scripts but also
> having their transliterated and english translated version in paranthesis
> (just a proposal). And probably you are right that we should have a
> percentage mechanism where instead of overcomplicating things we might decide
> to simplify statements and convert/translate to English entirely but in some
> other cases where discussionis happening mainly e.g. in Hindi but with mixed
> words and phrases of other languages here and there then its best to keep it
> in Roman Transliterated manner, and in some other cases where the percentage
> of a single language is very high like beyonfd 60% then we can keep the
> entire sentence in that script. Or maybe we should have a way of chcking the
> spirit of the entire transcript like what is the primary language of
> communication in it, and keeping the script of that language . but ultimately
> in our results everywhere and in the intermediate steps we have to make sure
> that English prevails with important quotes retaining original scripts and
> grammar with translation+transliteration alongside the original mixed script
> . Start the work on R1 as well now. Its a big task. Compact the memory so
> far, preserve inputs, document, etc and then proceed.

## Note on the worked example

The sentence the user supplies is **entirely in Latin script**:

> "and this is how we were preparing *taaki baadme koi kasar koi zarra na reh
> jaye* and so we kept on you know adding *hum jodte rahe cheezein*"

English matrix clause, Hindi embedded clauses, romanised throughout. The
script-profiling service shipped in D-066 reads this as 100% Latin and
therefore as English — it is precisely the case that module's docstring and
`test_romanised_code_mixing_is_NOT_detected_by_design` declare out of scope.
The proposal is therefore not a refinement of what exists; it targets the gap.
