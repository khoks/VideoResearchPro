---
name: knowledge-curator
description: Extract future requirements, vision additions, architecture/tech-stack/scaling/optimization choices, crucial product/engineering decisions, and any novel/potentially-patentable ideas surfaced in the current conversation. Route everything into the canonical project docs, the decision log, and the inventions log. Commit on a branch and open a PR to master.
---

# `/knowledge-curator` — capture session knowledge into the docs

This skill is the project's **session-to-docs pump**. It runs at the end of any substantive working session and ensures that anything the user and Claude have agreed on (or that Claude has recommended and the user has accepted, even tacitly) lands in the right canonical document — never just in the chat transcript.

## When to invoke

**Auto-invoke** (per `.claude/settings.json` `Stop` hook) at the end of a session — but only do real work if the conversation contained one or more of:

- Future-looking requirements, features, vision shifts, or roadmap changes
- Architecture, tech-stack, scaling, optimization, infrastructure, data-model, or API design discussion
- Decisions that will shape future PRs (chosen approach, rejected alternative, trade-off accepted, scope deferral)
- Brand / product framing that updates `vision.md`, `branding.md`, or `personal-brain.md`
- **Novel ideas or potentially-patentable concepts** — see the dedicated section below for the detection heuristic and the [`inventions.md`](../../docs/inventions.md) log shape

If the session was purely tactical (a bug fix, a one-off command, a code question with no design content), **exit without changes**. The skill is allowed to be a no-op.

**Manual invoke**: any time the user types `/knowledge-curator` or asks to "capture this into docs".

## Doc structure this skill owns and updates

The canonical doc map (mirrors §4.3 of the original rebrand plan). The skill **never** invents new top-level docs; it routes content into the existing ownership matrix.

| Topic the conversation touched | Canonical doc to update |
|---|---|
| App vision / why / north-star framing | [`docs/vision.md`](../../docs/vision.md) |
| Personal-brain / Echo north-star refinement | [`docs/personal-brain.md`](../../docs/personal-brain.md) |
| Feature roadmap (L1-L5 large; M1-M12 medium) | [`docs/feature-roadmap.md`](../../docs/feature-roadmap.md) |
| Multi-source ingest specifics (connectors, source types) | [`docs/source-types.md`](../../docs/source-types.md) |
| SaaS readiness / tenancy / billing / abuse | [`docs/saas-roadmap.md`](../../docs/saas-roadmap.md) |
| Brand identity / typography / colour tokens / voice | [`docs/branding.md`](../../docs/branding.md) |
| Running-system architecture (process topology, data model, agents, lifecycles) | [`docs/architecture.md`](../../docs/architecture.md) |
| Functional + non-functional requirements of what ships today | [`docs/requirements.md`](../../docs/requirements.md) |
| REST + WS API contract | [`docs/api-reference.md`](../../docs/api-reference.md) |
| Page-level UI surfaces | [`docs/ui-pages.md`](../../docs/ui-pages.md) |
| UI design tokens / page wireframes / states | [`docs/ui-design.md`](../../docs/ui-design.md) |
| Setup, dev workflow, conventions | [`docs/contributing.md`](../../docs/contributing.md) |
| Test strategy | [`docs/testing.md`](../../docs/testing.md) |
| Fine-tune dataset shape | [`docs/finetune_design.md`](../../docs/finetune_design.md) |
| **Decision log (this skill's home)** | [`docs/decisions.md`](../../docs/decisions.md) |
| **Inventions / novel-idea log (this skill's home)** | [`docs/inventions.md`](../../docs/inventions.md) |
| Recently shipped changes | [`CHANGELOG.md`](../../CHANGELOG.md) |
| Verbatim user vision dumps (safekeeping) | [`docs/notes/<YYYY-MM-DD-slug>.md`](../../docs/notes/) |

If the user delivers a long verbatim vision message, save it raw in `docs/notes/` (frontmatter `status: raw — do not edit`) **in addition to** synthesizing it into the canonical docs. Pattern is established by `docs/notes/2026-04-24-echo-feature-vision.md`.

## The decision log

`docs/decisions.md` is the single chronological record of **decisions** — choices made between two or more viable options. Each entry follows a lightweight ADR shape:

```markdown
### D-NNN — <short title> (YYYY-MM-DD)

**Status:** accepted | proposed | superseded by D-MMM | rejected

**Context.** What was being decided and why it came up. One short paragraph.

**Decision.** What we chose. One sentence.

**Alternatives considered.** Bullet list — option + why it lost.

**Consequences.** What this commits us to. What it forecloses. Any follow-ups required.

**Linked initiatives / PRs.** I-N / E-N.M / PR #X.
```

Number monotonically (D-001, D-002, …). Never renumber. If a decision is reversed, add a new entry that supersedes the old one and update the old one's `Status:` line.

## The inventions log

`docs/inventions.md` is the project's **novel-ideas / potentially-patentable-concepts log**. Decisions are about *which* path we take among known options; inventions are *new mechanisms* — non-obvious combinations, novel algorithms, unusual system architectures, or product shapes that may not exist in the public literature. The skill's job is to flag them and preserve the chronology and authorship; **the skill does not assess patentability legally** (that's a follow-up the user does, possibly with counsel).

### Detection heuristic — when to file an `N-NNN`

Treat an idea as a candidate invention when **any** of the following hold:

1. The user explicitly says some variant of: *"is this novel?"*, *"could this be patented?"*, *"I haven't seen this before"*, *"this might be unique"*, *"this is a new way of …"*.
2. The user describes a mechanism that is **specific** (not just a goal) and you do not recognize it from the public literature you've seen — e.g., a particular ranking pipeline, a particular way of combining models, a particular UI affordance, a particular data structure.
3. The user describes a **non-obvious combination** of known techniques whose joint use produces a measurable advantage (efficiency, accuracy, UX, cost) and that combination isn't a standard textbook recipe.
4. The user articulates a **product shape** (interaction model, business model, agency surface) that is unusual relative to comparable products in the same space.

If only the *goal* is described ("an app that learns my taste") without a specific mechanism, that's vision content, not an invention — route to `vision.md` / `feature-roadmap.md` instead.

If the idea is clearly part of standard prior art (e.g., "use embeddings for semantic search", "RAG", "fine-tuning"), do **not** file it.

Be **inclusive** at capture time. A false positive (filing an idea that turns out to be prior art) costs nothing — just update `Status:` to `superseded by prior art: <citation>`. A false negative (failing to capture a real novel idea) is the expensive failure mode because chronology can't be reconstructed later.

### Entry shape

```markdown
### N-NNN — <short title> (YYYY-MM-DD)

**Status:** captured | under-investigation | disclosed-publicly | patent-considered | patent-filed | abandoned | superseded by prior art

**Source.** Who introduced it (user / Claude / both). Session date. One-line context of how it came up.

**Summary.** One paragraph in plain language describing the idea — what it does, what problem it solves.

**Mechanism.** The specific *how* — the algorithm, data flow, component arrangement, or user-flow that makes the idea concrete. This is the part that distinguishes an invention from a vision: a mechanism can be implemented from this description.

**Why this is potentially novel.** The non-obviousness claim — what known approaches it differs from, and why the difference matters. List adjacent prior art the author already knows about, with how this differs from each.

**Prior-art notes.** Anything Claude or the user already remembers that's adjacent. Often empty initially; updated over time as a search is done.

**Commercial / strategic implications.** What does owning, defensively disclosing, or open-sourcing this mean for the project / future SaaS.

**Linked decisions / initiatives / PRs.** D-NNN, I-N / E-N.M, PR #X. Use `—` if none yet.

**Verbatim source (optional).** If the idea came from a single user message, preserve it here verbatim as an indented blockquote so future prior-art chronology has the original wording. This mirrors the safekeeping pattern in [`docs/notes/`](../../docs/notes/).
```

Number monotonically (`N-001`, `N-002`, …). Never renumber. **Status transitions** are append-only — if status changes, update the field but leave the entry text intact; add a `Status-changed YYYY-MM-DD: <reason>` line at the bottom.

### What to add when the user signals "this is novel"

When the user explicitly flags an idea as novel/patentable in a message:

1. File the `N-NNN` entry as described above.
2. Save the originating message verbatim to a `docs/notes/<YYYY-MM-DD-novel-<slug>.md` file with frontmatter `status: raw — do not edit` (mirrors the existing pattern at `docs/notes/2026-04-24-echo-feature-vision.md`). The `inventions.md` entry's `Verbatim source` field links to this note.
3. Cross-reference: if the idea has an architectural / roadmap implication, add a paragraph in the relevant doc that says `Realizes invention [N-NNN](inventions.md#n-NNN-...).`

The chronology + verbatim record is the part that matters most legally — that's the part to bias towards over-capturing.

## Style rules when editing existing docs

1. **Match the existing voice and Markdown shape** of the doc you're editing. `feature-roadmap.md` uses status emoji + structured sections (Motivation / Sketch / Schema impact / API impact / Open questions / Status). `architecture.md` is descriptive prose with diagrams. `requirements.md` is FR-N / NFR-N bullets. Don't import a different skeleton.
2. **Prefer in-place updates over append-only logs.** When a feature graduates from `⚪ proposed` to `🔵 accepted` to `🟡 in-progress` to `🟢 shipped`, update the existing entry's status; don't add a new one beside it.
3. **Cross-link.** Every new doc section that references another doc should link to it.
4. **Keep status legends and dates current.** If you bump a doc's content, bump its `Status: current as of <date>` header to today.
5. **Don't duplicate ownership.** Per the matrix above. If a topic already lives in another doc, link, don't restate.
6. **Don't invent acronyms or rename things mid-flight.** If the codebase uses `JobVideo`, the doc says `JobVideo`. Renames belong in a deliberate PR with code + doc together.
7. **Default-no-comments** policy applies to code blocks inside docs too — keep them tight.
8. **Date format.** ISO `YYYY-MM-DD`, never relative ("Thursday").

## Step-by-step procedure

Treat this as the runbook the skill follows when invoked. Skip steps the conversation makes irrelevant.

### 1. Scan the transcript

Read the conversation in this session (the active turn's history). Classify each substantive exchange into one of:

- **No-op** (purely tactical / debugging / answered question) — skip
- **Vision / framing** → `vision.md`, `personal-brain.md`, `branding.md`, optional `docs/notes/`
- **Roadmap / feature** → `feature-roadmap.md` (and `source-types.md` if multi-source)
- **Architecture / tech-stack / data-model / API / scaling** → `architecture.md` (and `saas-roadmap.md` if forward-looking)
- **Requirements (what currently ships)** → `requirements.md`
- **UI / page / token** → `ui-design.md` or `ui-pages.md`
- **Decision** → `decisions.md` (and add `Linked decision: D-NNN` cross-references in the other docs you touched)
- **Novel idea / potentially-patentable concept** → `inventions.md` (apply the detection heuristic above; if the idea was a single verbatim user message, also save it to `docs/notes/<YYYY-MM-DD-novel-<slug>.md`)

### 2. Open every doc you intend to modify

Read the existing structure. Find the right insertion point. Match the heading depth and tone.

### 3. Make minimal, surgical edits

For each doc, apply the smallest edit that captures the new content correctly. Prefer `Edit` over `Write`. If a brand-new section is genuinely needed, give it a stable anchor heading so future edits can update in place.

### 4. Add to the decision log

For each *decision* the conversation produced, append a `D-NNN` entry to `docs/decisions.md`. Include the `Linked initiatives / PRs` field even if empty (write `—`); this prevents the log from drifting away from the work-tracker.

### 5. Cross-link

Wherever a doc edit is driven by a decision, add an inline `(see [D-NNN](decisions.md#d-NNN-...))` reference. Wherever an open question was named in the conversation, file it under the right doc's `Open questions` section.

### 6. Touch the changelog (only for shipped work)

`CHANGELOG.md` is for things that have **landed**. Future plans go in `feature-roadmap.md`. If the conversation actually shipped code (PR merged), add a `## [Unreleased]`-section bullet under the right category (Added / Changed / Fixed / Deprecated / Removed / Security).

### 7. Verify links

Run a quick mental link-check on the docs you edited. Every `[text](path)` should resolve.

### 8. Branch, commit, push, open PR

Workflow:

```bash
# Make sure we're on master and clean
git checkout master && git pull --ff-only

# Branch name: docs/<concise-topic>-<YYYY-MM-DD>
git checkout -b docs/<topic>-<YYYY-MM-DD>

# Stage only the docs we edited (never `git add -A`)
git add docs/<files> CHANGELOG.md  # explicit list

# Commit using the project's HEREDOC convention
git commit -m "$(cat <<'EOF'
docs: <one-line summary of what changed>

<2-4 sentences on what was extracted from the session>
- bullet of doc 1 changes
- bullet of doc 2 changes
- new decisions: D-NNN, D-MMM

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"

git push -u origin HEAD

gh pr create --title "docs: <topic>" --body "$(cat <<'EOF'
## Summary
- <1-3 bullets on what landed>
- New decisions: D-NNN, D-MMM
- Touched docs: <list>

## Why
<paragraph: what session produced this and why these docs are the right home>

## Test plan
- [ ] `markdown-link-check` (or manual click-through) on edited docs — no broken internal links
- [ ] Each new `D-NNN` entry has Status / Context / Decision / Alternatives / Consequences populated
- [ ] Cross-links from feature/architecture docs back to decision log present where applicable

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**Never** force-push, never `git add -A`, never amend a previous commit. If a hook fails, fix it and create a new commit.

### 9. Report back

After opening the PR, post a short summary in chat:

```
Curated this session into:
- docs/<file>: <what changed>
- docs/decisions.md: D-NNN <title>
PR: <url>
```

That's it. Don't over-narrate.

## What this skill does NOT do

- ❌ Refactor or restructure existing docs beyond what's needed for the current update
- ❌ Translate / rephrase existing prose for "consistency"
- ❌ Run code, ship features, or modify anything outside `docs/` and `CHANGELOG.md`
- ❌ Merge the PR — opening is the skill's job, merging is the user's
- ❌ Delete `docs/notes/*` raw vision dumps (those are immutable safekeeping)
- ❌ Touch `MEMORY.md` (auto-memory is a separate system; the skill never writes to it)

## Failure mode

If `gh` is unavailable, no remote is configured, or auth fails, the skill should:

1. Still complete the local commits on the branch.
2. Print the exact `git push` and `gh pr create` commands the user can run.
3. Not roll back the commits.

If a doc's structure is so different from what the skill expected that surgical insertion is unsafe, the skill should write its findings into a new file under `docs/notes/<YYYY-MM-DD>-curator-pending-<topic>.md` and flag it in the report so a human can route it manually. Better to defer than to scribble in the wrong place.
