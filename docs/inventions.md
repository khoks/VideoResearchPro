# Pratidhvani — Inventions / Novel-Idea Log

**Status:** living doc (last refreshed 2026-10-24). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

This is the chronological record of **novel mechanisms, non-obvious combinations, and potentially-patentable concepts** surfaced in conversations between the user and Claude. The skill flags candidates and preserves the chronology + authorship. **The skill does not make legal patentability assessments** — that's a follow-up the user does, possibly with counsel.

The bias is toward **over-capture**: a false positive (filing something that turns out to be prior art) is cheap to mark `superseded by prior art`. A false negative (missing a genuine novel idea) is expensive because chronology can't be reconstructed later.

---

## Conventions

- **Numbering** is monotonic (`N-001`, `N-002`, …). Never renumber.
- **Status** values: `captured` / `under-investigation` / `disclosed-publicly` / `patent-considered` / `patent-filed` / `abandoned` / `superseded by prior art`.
- Status transitions are append-only — when status changes, update the field but leave the entry text intact; add a `Status-changed YYYY-MM-DD: <reason>` line at the bottom of the entry.
- Date format is ISO `YYYY-MM-DD`.
- The `Linked decisions / initiatives / PRs` field uses IDs from [`decisions.md`](decisions.md), [`initiatives.md`](initiatives.md), and PR numbers from GitHub.
- When an entry's seed is a single verbatim user message, save it under [`docs/notes/<YYYY-MM-DD-novel-<slug>.md`](notes/) with frontmatter `status: raw — do not edit`, and link from the entry's `Verbatim source` field.

---

## Entry shape (template)

```markdown
### N-NNN — <short title> (YYYY-MM-DD)

**Status:** captured

**Source.** <user / Claude / both>. Session 2026-MM-DD. <one-line context>.

**Summary.** <one paragraph in plain language>

**Mechanism.** <the specific *how* — algorithm, data flow, component arrangement, user-flow — concrete enough that an engineer could build from this description>

**Why this is potentially novel.** <the non-obviousness claim — what known approaches it differs from, and why the difference matters>

**Prior-art notes.** <adjacent work the user/Claude already knows about; how this differs>

**Commercial / strategic implications.** <what owning, defensively disclosing, or open-sourcing this means>

**Linked decisions / initiatives / PRs.** <D-NNN / I-N / E-N.M / PR #X — or `—` if none yet>

**Verbatim source.** <optional — link to `docs/notes/...` raw note>
```

---

## Log

### N-001 — Production-replay blind-delta harness for per-call-site model-tier selection (2026-07-29)

**Status:** captured

**Source.** Both. Session 2026-07-29. The user asked to re-run "the same functions/prompts on the same data" with a maximum-thinking model and quantify "how much intelligence are we losing" against the app's cheaper defaults; Claude designed the replay + blind-judging mechanism to answer it.

**Summary.** A method for deciding which model tier each LLM call site in a multi-step agentic pipeline actually needs, by replaying a *real completed job's* exact per-call-site inputs through a maximum-capability model and blind-judging the results against what production actually produced. Instead of asking "which model is better in general" (benchmarks) or "is the final output good" (end-to-end eval), it produces a **per-call-site quality delta** on the operator's own corpus, which maps directly onto a routing decision: keep the cheap model here, upgrade there.

**Mechanism.**

1. **Deterministic input reconstruction.** For a completed job, rebuild each call site's exact input by re-executing the app's own deterministic preprocessing (chunker + settings, prompt-formatting, model-window-derived batch budgeting, job-scoped vector retrieval) over the stored transcripts. This reproduces byte-comparable inputs without re-running acquisition, so corpus variance is eliminated as a confound. Crucially it works *retroactively* on jobs that never anticipated being audited, because the transcripts and chunking parameters are stored and the transforms are pure.
2. **Prompt-template fidelity.** The challenger reads the production prompt templates from source and applies them verbatim, and is instructed to behave as the raw model (emit only the contracted artifact, no meta-commentary), so outputs are drop-in comparable to stored ones.
3. **Substitute-model execution as agents.** The challenger is a fleet of subagents — one per batch / per question / per video — rather than API calls, which allows maximum reasoning effort and parallelism on an interactive subscription rather than a metered key.
4. **Restart-safe artifact protocol.** Each agent writes its artifact to disk immediately; on interruption, the harness inspects *disk state* rather than the orchestrator's completion log (they diverge — killed agents often finished their write) and parse-validates each artifact, treating truncated files as missing. Judging is ordered before expensive replication so an interrupted run still yields verdicts.
5. **Blind pairing.** A blinding step randomizes each (production, challenger) pair into `A`/`B` and withholds the mapping from judges, who are instructed not to infer provenance and to discount verbosity/polish.
6. **Ground-truth-anchored judging.** Judges are given the *same retrieval tool over the same corpus* the artifacts drew from, and are required to verify sampled claims (do cited sources actually support them?) against source transcripts, rather than scoring style. Fabrications are hunted explicitly.
7. **Loss attribution on unpersisted stages.** For pipeline stages whose intermediates production discards, the max-effort extraction of the same input becomes the reference: facts it captured are searched for in the final production artifact, and the misses are reported as **concrete content the cheap chain dropped** — converting an unobservable stage into a measurable one.

**Why this is potentially novel.** The non-obvious combination is (a) *retroactive* exact-input reconstruction from stored job state via the app's own pure transforms, (b) used to drive *per-call-site* rather than whole-system model routing, (c) with blind A/B judging anchored in the production retrieval index, and (d) a loss-attribution step that measures quality of stages whose outputs were never persisted, by diffing a max-effort replay against the surviving downstream artifact. Standard practice measures either general model capability (static benchmarks) or end-to-end output quality (A/B in production). Neither localizes the deficit to a specific prompt in a 20-call-site pipeline, and neither can audit a stage that leaves no trace. Point (d) in particular seems unusual: it recovers observability retroactively for a pipeline that was not instrumented for it.

**Prior-art notes.** Adjacent and well-known: LLM-as-judge and pairwise blind preference (Chatbot Arena, MT-Bench, AlpacaEval); harnesses like HELM / lm-eval-harness / OpenAI Evals; production shadow-mode and champion/challenger deployment; RAG evaluation suites (RAGAS, TruLens) that score groundedness/faithfulness. Differences: those judge a *model* or a *system*, on curated or synthetic inputs; this judges a *specific call site inside a pipeline* on replayed real inputs, and derives a routing/cost decision per site. Shadow-mode deployment is the closest operational analogue but requires instrumenting the pipeline *before* the run and re-executing live traffic; this works retroactively on already-completed jobs with no prior instrumentation. Not claimed novel: the individual pieces (deterministic chunking, blind judging, LLM-as-judge, retrieval-grounded verification).

**Commercial / strategic implications.** For the SaaS trajectory this is the engine behind a credible cost/quality product surface: it can justify per-tier model routing to customers with evidence ("Studio tier upgrades these three call sites because they measurably lose X"), and it turns the E-1.13 override panel from a raw knob into a *guided* one (recommendations backed by measured delta per use case). Defensive publication is probably the right posture unless the loss-attribution step proves distinctive on a proper prior-art search; open-sourcing the harness would also be a credible developer-marketing asset since any multi-call-site agentic app faces the same routing question.

**Linked decisions / initiatives / PRs.** [D-055](decisions.md#d-055--intelligence-delta-evaluation-methodology-production-input-replay--blind-ab-judging-2026-07-29) (methodology), [E-1.14](initiatives.md#e-114--model-tier-quality-evaluation-harness). Consumes the model stack set by [D-052](decisions.md#d-052--measured-context-windows--three-tier-model-stack-e-112-model-re-audit-2026-07-29) / [D-053](decisions.md#d-053--claude-5-adoption-for-user-facing-synthesis--gpt-56-empirical-profile-2026-07-29) and feeds the override defaults from [D-054](decisions.md#d-054--per-user-llm-overrides--cost-calculator-gpt-56-adaptive-reasoning-findings-2026-07-29).

**Verbatim source.** [`notes/2026-07-29-novel-intelligence-delta-harness.md`](notes/2026-07-29-novel-intelligence-delta-harness.md)

---

## Cross-references

- [`decisions.md`](decisions.md) — decisions choose between known options; this log captures *new* mechanisms.
- [`vision.md`](vision.md) — vision describes goals; this log captures specific *means*.
- [`feature-roadmap.md`](feature-roadmap.md) — once an invention realizes as a feature, the roadmap entry should add `Realizes invention [N-NNN](inventions.md#n-NNN-...).`
- [`docs/notes/`](notes/) — verbatim user messages preserved as raw safekeeping artifacts.


### N-002 — Proportion-driven rendering policy for code-mixed speech (2026-07-31)

**Status:** implemented and measured (2026-10-19). Built as S-1.16.2 in seven PRs ([#258](https://github.com/khoks/VideoResearchPro/pull/258), [#260](https://github.com/khoks/VideoResearchPro/pull/260), [#262](https://github.com/khoks/VideoResearchPro/pull/262), [#264](https://github.com/khoks/VideoResearchPro/pull/264), [#268](https://github.com/khoks/VideoResearchPro/pull/268), [#271](https://github.com/khoks/VideoResearchPro/pull/271), [#276](https://github.com/khoks/VideoResearchPro/pull/276)); decisions [D-080](decisions.md#d-080--code-mixing-detection-a-lexicon-tagger-not-an-llm-pass-2026-10-19) and [D-084](decisions.md#d-084--code-mixed-retrieval-embed-an-english-rendering-keep-the-original-as-the-stored-text-2026-10-19); method and every number in [the detection note](notes/2026-10-19-code-mixing-detection.md).

**What the measurements say about each part of the mechanism.**

- *Measure the balance, not the label.* A lexicon, n-gram and Viterbi tagger
  finds romanised Hindi at token precision 0.93 and recall 0.89 on held-out
  labelled text (0.99 and 0.85 on 80 unseen comments), free and in about
  1 ms per segment. A small LLM was less precise (0.80).
- *Matrix vs embedded is real and distinct from proportion.* 11% of mixed
  spans have mostly English words in Hindi grammar, and a word-count rule
  calls every one of them English. A system-morpheme vote (Matrix Language
  Frame) names the grammar's language correctly 0.95 of the time, against
  0.86 for word majority.
- *Proportion as a rendering policy.* It works, and its thresholds are best
  chosen by decision stability on detector output: decisions agree with gold
  for 0.97 of Latin units. At the default thresholds the matrix gate rarely
  changes a decision (0 of 90 gold decisions). The matrix earns its keep in
  telling the analysis path which grammar to read in.
- *Transcript-level resolution.* Quote-by-quote decisions would switch script
  25 times across seven Hindi lectures and 128 times across eleven comment
  threads. Resolved per source, they switch zero times.
- *Bidirectional split.* Analysis stays English (no Hinglish passed through
  in six end-to-end runs). Quotation keeps the original: 25 Devanagari
  originals kept on a held-out lecture against 0 before, and every quote
  the composer chose was in the three-part form. Retrieval on an English
  rendering lifts MRR from 0.40 (romanised) and 0.57 (Devanagari) to 0.81.

**What did not hold, or is still open.** The predicted failure (Hinglish
silently passed through as English) did not occur at extraction even before
this work. It occurred at the fetch layer, where 2 of 13 Hindi videos
arrived as machine-dubbed tracks that no text-level mechanism can detect
(S-1.11.11). Other open items: the labels are one model's, not a native
speaker's; English nouns written in Devanagari remain invisible to the
tagger; what the 60% threshold should rest on is the user's call; and **a
proper prior-art search has still not been done**.

**Refined 2026-10-19 (T-1.16.2.11).** "Keep the whole sentence in that
language's script" now applies only to speech already in that script. A
Hindi-dominant source typed in Latin letters is quoted in Latin letters,
because re-scripting it puts words in the speaker's mouth that they never
wrote. Every native-script passage in a composed report is now checked
against the sources' speech in code, and any that fails is removed.

**Originally captured:** 2026-07-31

**Source.** User, session 2026-07-31, while reviewing R5. Introduced unprompted and explicitly flagged: *"R5 seems to be a candidate for novel invention if we carefully detect and handle the balance of words from different scripts and grammar used and syntax used in different portions of the speech."* Verbatim message preserved at [docs/notes/2026-07-31-novel-code-mixing-rendering.md](notes/2026-07-31-novel-code-mixing-rendering.md).

**Summary.** Speakers across the Middle East, South Asia and East Asia routinely mix languages *inside a single clause* — one language supplying grammar and syntax, another supplying vocabulary. Existing language identification answers "what language is this document/segment?" with one label, which is the wrong question for such speech: the honest answer is "two, structurally interleaved". The proposal is to treat measured **proportion** not as a classification output but as a **rendering policy**, and to decouple the language used for *analysis* from the language used for *quotation*.

**Mechanism.**

1. **Measure the balance, not the label.** For a span of speech, measure the proportion of words attributable to each language, and — the distinguishing part — which language supplies the *matrix* (grammar/syntax) versus which supplies *embedded* vocabulary. The worked example is English-matrix with Hindi-embedded clauses:

   > "and this is how we were preparing *taaki baadme koi kasar koi zarra na reh jaye* and so we kept on you know adding *hum jodte rahe cheezein*"

2. **Bidirectional handling.** Analysis, extraction, ranking and reporting run on an **English** rendering, so every downstream stage sees one language. Quotation retains the **original**, with transliteration and translation alongside — so authenticity survives without contaminating the analysis path.

3. **Proportion thresholds select the quoting form**, rather than one global rule:
   - dominant single language (user's suggestion: >60%) → keep the whole sentence in that language's script;
   - heavy interleaving → Roman transliteration throughout, so a reader can follow one script;
   - light borrowing → simplify to English entirely.

4. **Transcript-level "spirit" resolution.** Optionally resolve the *primary language of communication* for the whole transcript and let that set the script policy, rather than deciding sentence by sentence — avoiding a report that flickers between scripts paragraph to paragraph.

**Why this is potentially novel.**

- **Language ID returns a label; this returns a policy.** Standard detectors (lingua, CLD3, fastText, langdetect) emit `{lang: confidence}` per document or per segment. None of them prescribe *how to render* the text downstream, and none model matrix-vs-embedded structure — which is the linguistically meaningful distinction in code-switching (cf. Myers-Scotton's Matrix Language Frame model, which is descriptive linguistics rather than a rendering system).
- **The analysis/quotation split is unusual.** Translation pipelines normally pick one target and convert wholesale; RAG systems normally embed the source as-is. Doing both deliberately — normalise for machine reasoning, preserve for human citation — is a system-design choice we have not seen packaged as a policy.
- **Thresholds as product behaviour.** Treating "60% one language" as a *rendering* decision rather than a *classification* decision inverts the usual use of confidence scores.

**Prior-art notes.** Adjacent work we already know of: Myers-Scotton's Matrix Language Frame (linguistic theory of code-switching, not an engineering system); romanisation standards (IAST, ISO 15919, ALA-LC) which define *how* to transliterate but not *when*; multilingual embeddings such as `paraphrase-multilingual-MiniLM-L12-v2` which place mixed text in shared vector space without addressing rendering; LID benchmarks for code-switched text (e.g. LinCE) which measure token-level tagging accuracy rather than downstream presentation. None of these combine proportion measurement, matrix/embedded structure, and a bidirectional analyse-in-English / quote-in-original policy. **A proper prior-art search has NOT been done** — this entry is captured on the inclusive-capture principle, and may later be marked superseded.

**The gap it targets is real and currently unsolved in this codebase.** `app/services/language_service.py` (D-066) profiles Unicode scripts and is exact for Devanagari/Arabic mixed with Latin — but the user's own example is *entirely Latin script*, so the service reads it as English. `test_romanised_code_mixing_is_NOT_detected_by_design` pins that limitation deliberately. This invention is what would close it.

**Commercial / strategic implications.** The addressable content this unlocks is large: Hindi/Urdu, Arabic/Persian and Southeast Asian creator ecosystems are enormous and poorly served by English-first research tooling. A system that ingests code-mixed speech and produces clean English analysis *with citable original-language quotes* is a differentiator for a research product aimed at those markets — and, per [vision.md](vision.md), for a personal brain that learns a multilingual user's actual voice. Whether to pursue disclosure, patent, or deliberate open publication is the user's call with counsel.

**Linked decisions / initiatives / PRs.** [D-066](decisions.md#d-066--language-contract-temporal-awareness-and-corpus-aware-qa-length-2026-07-31), E-1.16 (R5), S-1.16.2 (implementation of this mechanism).

**Verbatim source.** [docs/notes/2026-07-31-novel-code-mixing-rendering.md](notes/2026-07-31-novel-code-mixing-rendering.md)

### N-003 — True-by-construction modality marks for reports written from speech plus machine-described screens (2026-10-24)

**Status:** captured. Implemented and measured as S-1.18.9 ([PR #363](https://github.com/khoks/VideoResearchPro/pull/363), [D-106](decisions.md#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24)). Its first pre-registered run did not clear the product's bar; see [the protocol note](notes/2026-10-18-r1-visual-measurement.md), "Run 9: results".

**Source.** Claude, 2026-10-24, designing S-1.18.9 to the user's requirement in D-105: show visual analysis again only when a deterministic guard removes the residual error. The parent session's brief specified a guard at the item level and a rewrite after compose. The mechanism below is what came out of building and measuring it.

**Summary.** A report written by a language model from video transcripts with interleaved machine descriptions of what was on screen must keep two evidence channels apart: what a speaker *said* and what the screen *showed*. Prompt rules and model-assigned labels moved this error around rather than removing it. The mechanism removes it in code, in a way that cannot introduce a false statement of its own. It only ever writes a claim it has verified by construction, and it writes the stronger claim only where its own evidence can support that claim.

**Mechanism.**

1. **Evidence per source and moment.** From the report's own chunks, build each source's speech with the screen descriptions removed (chunk-level time ranges), and its screen descriptions with their timestamps.
2. **Specific details, not prose.** Extract checkable tokens from a sentence: numbers (native digits normalised), code identifiers, quoted strings, visual descriptor pairs, and lists of names. Mask the citation apparatus first (titles, channel names, timestamp links).
3. **Screen-only relative to the cited moment.** A detail counts as screen-only when it is found in a screen description of the cited source near the moment the sentence cites (the nearest following link first). It must also be absent from the speech *around that moment*, not just absent from the whole video. That is how it catches a detail the speaker said elsewhere but that this sentence took from the screen.
4. **Speaker credit at sentence scope, screen exemption at clause scope.** A detail counts as credited when the nearest marker before it is a speech verb with a speaker before it, or when its clause ends in "— Name (mm:ss)". It is exempt when the nearest marker before it is an explicit on-screen phrase. "Also visible on screen" never exempts, because it implies the detail was said.
5. **Asymmetric claims.** The mark "(on screen at mm:ss)" uses the matching description's own timestamp, so it is true whenever it is written. The stronger "not spoken" is added only when absence is trustworthy: figures and multi-word quotes, Latin-script speech, absent from the whole speech, with caption habits read as numbers ("15 000", "one two two", "point nine two"). Identifiers and descriptor pairs never get it, because captions misspell them ("carrot" for carat).
6. **Move, never delete.** The detail stays where it is; only provenance is added. A parenthetical holding only screen-only figures becomes "(on screen at mm:ss, not spoken: …)". Substance is preserved by construction.
7. **The converse, under the same discipline.** "Also visible on screen" with no description of the cited source behind it is removed. "The video displays X", where only the speech has X, is marked "(said at mm:ss; no captured frame shows it)".
8. **Upstream first.** The same test runs on the extraction stage's items before composition. An item whose details are all screen-only is relabelled; mixed items name their screen-only details in the tag the composer attributes from. The output-level pass catches what still gets through, including summaries condensed from already-written sections.

**Why this is potentially novel.**
- **Modality attribution, not source attribution.** Attribution and factual-consistency work asks whether a claim is supported by *some* evidence. Here every detail *is* supported. The defect is crediting it to the wrong channel of the same source, speech versus screen, at the right moment.
- **Edits that cannot be wrong.** Post-hoc revision systems rewrite text with a model, and the rewrite can itself be wrong. This mechanism writes only claims that are true by construction, and gates the one stronger claim on whether its evidence is readable (script and token type). A false "not spoken" is itself the error class being prevented: run 4 confirmed one.
- **Moment-locality as the decisive test.** Whole-document presence checks miss the case where a speaker said a detail at minute 9 and the sentence about minute 22 took it from the screen.

**Prior-art notes.** Adjacent work already known:
- Factual-consistency checkers for summarisation (SummaC, QAGS, FactCC). They score support against a source; they do not separate channels within a source.
- Attribution evaluation (AIS, ALCE) and model-based post-hoc revision (RARR). They attribute to retrieved documents and revise with a model rather than deterministically.
- Multimodal grounding and video captioning research, which grounds text in frames but does not police speaker credit in prose.
- This project's own quote scrub (#309) and S-1.18.8 labels, of which this is the deterministic successor.

**A proper prior-art search has NOT been done.** This entry is captured on the inclusive-capture principle.

**Commercial / strategic implications.** Any product that writes from video, meetings or lectures, with screen shares, slides or code on screen, faces the same said-versus-shown boundary. In legal, compliance and research settings, crediting a person with words they never spoke is a correctness failure, not a style issue. A guard that never writes a false statement is a trust feature that can be disclosed openly. Whether to publish, keep internal, or pursue protection is the user's call with counsel.

**Measured so far.** On the stored reports of eight earlier runs it catches 8 of 10 confirmed errors, against 2 of 5 for a token checker. This is in-sample. In its first pre-registered run (run 9), all 7 of its own changes held up under three-lens verification. One error still got through: a lone two-digit figure, below its action threshold.

Run 10 (2026-10-25) contradicts the "edits that cannot be wrong" claim for every mark that implies a detail was not said. Four of the guard's eleven changes were confirmed attribution errors, and each one inferred absence from a transcript the guard could not fully read:
- The "not spoken" gate misfired twice: on a caption homophone ("one to one" for `121`) and on an inflected form ("get started" was spoken; "getting started" was marked "not spoken").
- Two words were spoken in Bengali. One got an on-screen mark that verifiers read as screen-only, given the processing note's "could not be matched to the speech"; the other lost an "also".

What holds by construction is narrower than claimed: the bare "(on screen at mm:ss)" presence claim. T-1.18.9.11 proposes dropping every absence inference. See the protocol note, "Run 10: results".

**Linked decisions / initiatives / PRs.** [D-075](decisions.md#d-075--r1-after-three-runs-the-modality-boundary-needs-provenance-not-prompt-rules-2026-10-19), [D-105](decisions.md#d-105--visual-analysis-hidden-in-the-ui-until-a-deterministic-attribution-guard-removes-the-residual-error-2026-10-20), [D-106](decisions.md#d-106--the-deterministic-attribution-guard-ships-in-the-report-pipeline-r1-stays-hidden-after-run-9-2026-10-24); E-1.18, S-1.18.8, S-1.18.9; PR [#363](https://github.com/khoks/VideoResearchPro/pull/363).

**Verbatim source.** —
