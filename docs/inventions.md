# Pratidhvani — Inventions / Novel-Idea Log

**Status:** living doc (last refreshed 2026-07-29). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

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

**Linked decisions / initiatives / PRs.** [D-055](decisions.md#d-055-intelligence-delta-evaluation-methodology-production-input-replay-blind-ab-judging-2026-07-29) (methodology), [E-1.14](initiatives.md#e-114-model-tier-quality-evaluation-harness). Consumes the model stack set by [D-052](decisions.md#d-052-measured-context-windows-three-tier-model-stack-e-112-model-re-audit-2026-07-29) / [D-053](decisions.md#d-053-claude-5-adoption-for-user-facing-synthesis-gpt-56-empirical-profile-2026-07-29) and feeds the override defaults from [D-054](decisions.md#d-054-per-user-llm-overrides-cost-calculator-gpt-56-adaptive-reasoning-findings-2026-07-29).

**Verbatim source.** [`notes/2026-07-29-novel-intelligence-delta-harness.md`](notes/2026-07-29-novel-intelligence-delta-harness.md)

---

## Cross-references

- [`decisions.md`](decisions.md) — decisions choose between known options; this log captures *new* mechanisms.
- [`vision.md`](vision.md) — vision describes goals; this log captures specific *means*.
- [`feature-roadmap.md`](feature-roadmap.md) — once an invention realizes as a feature, the roadmap entry should add `Realizes invention [N-NNN](inventions.md#n-NNN-...).`
- [`docs/notes/`](notes/) — verbatim user messages preserved as raw safekeeping artifacts.


### N-002 — Proportion-driven rendering policy for code-mixed speech (2026-07-31)

**Status:** captured

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
