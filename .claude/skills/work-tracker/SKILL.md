---
name: work-tracker
description: Maintain the Initiative → Epic → Story → Task hierarchy in docs/initiatives.md. After each session, update the status, scope, and content of existing items, create new ones for newly-discussed work, and link them to PRs and decisions. Commit on a branch and open a PR to master.
---

# `/work-tracker` — keep `docs/initiatives.md` honest

This skill is the project's **Jira-in-the-repo**. It owns `docs/initiatives.md` exclusively. Every piece of work this project does — shipped, in-progress, accepted, proposed, or deferred — has a home there, traceable from the largest north-star initiative all the way down to a single task.

## When to invoke

**Auto-invoke** (per `.claude/settings.json` `Stop` hook) at the end of a session — but only do real work if the session contained one or more of:

- New work the user agreed to do (a future PR, a connector, a feature, an investigation)
- Status change on existing work (a PR merged, a story accepted, a task completed, an epic deferred)
- Scope changes (story split, epic narrowed, initiative expanded)
- Newly-surfaced open questions tied to a story
- Newly-spotted dependencies between items

If the session was purely tactical with no work-state implications, **exit without changes**. The skill is allowed to be a no-op.

**Manual invoke**: any time the user types `/work-tracker` or asks "what's the state of <X>", "what's next", "create a story for …", "mark <X> done".

## The hierarchy (Initiative → Epic → Story → Task)

| Level | Prefix | Scope | Lifespan |
|---|---|---|---|
| **Initiative** | `I-N` | Multi-quarter north-star (e.g. *Multi-source ingest*, *Author Studio*, *Personal Brain*, *SaaS readiness*) | Months → year+ |
| **Epic** | `E-N.M` | Multi-PR slice of an initiative (e.g. *Schema additive PR*, *Connector abstraction*, *Reddit + HN connectors*) | 1–4 weeks |
| **Story** | `S-N.M.K` | Single PR's worth of work (e.g. *Add `social_classify_stance` use case*) | 1–5 days |
| **Task** | `T-N.M.K.J` | Atomic action inside a story (e.g. *Write Alembic migration*, *Add fixture*) | Hours |

Numbering is monotonic per parent. **Never renumber** — closed items keep their ID forever, even if other items are reordered.

## Status legend (mirrors `feature-roadmap.md`)

| Marker | Status | Meaning |
|---|---|---|
| 🟢 | shipped | merged to master, live |
| 🟡 | in-progress | branch / PR open, or actively coded |
| 🔵 | accepted | scoped + agreed, not yet started |
| ⚪ | proposed | idea filed; awaiting approval |
| 🔴 | deferred | approved earlier, deprioritized |
| ⚫ | blocked | waiting on external dependency or decision |
| ✖ | cancelled | abandoned (kept for history) |

## File shape — `docs/initiatives.md`

A single file with every initiative inline. Each Initiative is an `##` heading, Epic is `###`, Story is `####`, Task is `-` bullet. Status emoji always **first** in the heading after the ID.

```markdown
## I-1 🟡 Multi-source ingest

**Why it exists.** <one paragraph — the motivation>
**North-star doc:** [feature-roadmap.md L1](feature-roadmap.md#l1--multi-source-ingest), [source-types.md](source-types.md)
**Decision links:** [D-001](decisions.md#d-001-...), [D-007](decisions.md#d-007-...)

### E-1.1 🟢 Schema additive (PR #63)
**Scope.** Add `source_type`, `source_url`, `source_metadata` columns alongside existing `videos` shape. No call-site changes.
**Shipped:** 2026-04-22 — PR [#63](https://github.com/khoks/VideoResearchPro/pull/63)

### E-1.2 🟢 Connector abstraction (PR #65)
...

### E-1.5 🟡 Social-media connectors

**Scope.** Reddit + HN first; Mastodon + Bluesky next; manual-paste mode for FB/IG/LI/X; defer Discord and TikTok.
**Linked decision:** [D-NNN — Social-media platform staging](decisions.md#d-NNN-...)

#### S-1.5.1 🔵 Reddit search connector
**PR:** TBD
**Acceptance.** A topic job with `source_types=["reddit_post"]` searches Reddit, presents threads at approval, ingests into the global library. Q&A returns Reddit citations with permalink + comment-id deep-links.
**Tasks**
- [ ] T-1.5.1.1 Implement `RedditConnector(BaseConnector)` with `search()` against `/search.json`
- [ ] T-1.5.1.2 Flatten post + top-50 comments into a single transcript-equivalent text
- [ ] T-1.5.1.3 Store new `source_type='reddit_post'` rows; PK column = `f"reddit:{post_id}"`
- [ ] T-1.5.1.4 Approval-UI card variant for Reddit (handle, score, comment count, snippet)
- [ ] T-1.5.1.5 Citation rendering: permalink with `#comment-<id>`
- [ ] T-1.5.1.6 Tests: connector unit tests + end-to-end pipeline test

#### S-1.5.2 🔵 HN search connector
...
```

## Conventions

- **One source of truth.** `docs/initiatives.md` is canonical. Status of a feature can be **mirrored** to `feature-roadmap.md` (legend matches) but the source-of-truth for any tactical work item is here.
- **Links over duplication.** Tie each Initiative to a roadmap section, vision section, or design doc. Tie each Epic / Story to a decision in `docs/decisions.md` if one exists.
- **Closed work stays.** Don't delete shipped Epics or cancelled Stories — the audit trail matters. Strike through cancelled tasks (`~~T-1.2.3.4 …~~`) and append a one-sentence reason.
- **Tasks default to checkboxes.** `- [ ]` while open, `- [x]` when done.
- **Scope changes get a `Scope-changed YYYY-MM-DD:` line** appended to the entry, briefly noting what changed and why.
- **PR back-links.** When a Story or Epic ships, put `**Shipped:** YYYY-MM-DD — PR [#N](...)` in its block.
- **Date format.** ISO `YYYY-MM-DD`, never relative.

## Step-by-step procedure

### 1. Read current state

`Read` `docs/initiatives.md`. Locate every initiative + epic + story whose state may be affected by the session.

### 2. Update existing items

For each affected item:

- Status changed? Update the emoji and (if shipped) add `Shipped: YYYY-MM-DD — PR #N`.
- Scope changed? Append a `Scope-changed YYYY-MM-DD:` line.
- New tasks under an existing story? Append numbered `T-N.M.K.J` checkboxes.
- New blockers? Add `**Blocked-on:** D-NNN` or a free-text note.
- A decision was just made that ties to this item? Add `Linked decision: D-NNN`.

### 3. Create new items

For each new piece of work the session introduced:

- Pick the right level. New initiative? Probably no — initiatives are coarse and rare. Almost everything is a new Story under an existing Epic, or a new Epic under an existing Initiative.
- Allocate the next monotonic ID under the parent.
- Fill in: Scope, Acceptance, Tasks (initial checklist if obvious), Linked decision (if any), PR (TBD).
- Default new items to `🔵 accepted` if the user has agreed, `⚪ proposed` if it's still a recommendation.

### 4. Sanity check the hierarchy

- No orphaned Stories without an Epic
- No orphaned Tasks without a Story
- No duplicate IDs
- Status of parent is the loosest of children (any 🟡 child → parent at least 🟡; any ⚫ blocker → parent at least 🟡 with an explicit Blocked note)

### 5. Cross-link

Every newly created item that has a corresponding decision in `docs/decisions.md` gets a `Linked decision: D-NNN` line. Every Story that has an open PR gets a `PR: #N` line.

### 6. Branch, commit, push, open PR

```bash
git checkout master && git pull --ff-only
git checkout -b work/<concise-topic>-<YYYY-MM-DD>
git add docs/initiatives.md
git commit -m "$(cat <<'EOF'
work: <one-line summary of state changes>

- Created: I-N / E-N.M / S-N.M.K (with one-line each)
- Updated: <items> — <state transitions>
- Linked decisions: D-NNN, D-MMM

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
git push -u origin HEAD
gh pr create --title "work: <topic>" --body "$(cat <<'EOF'
## Summary
- <items created>
- <items advanced>

## Test plan
- [ ] All IDs are monotonic and unique
- [ ] All `Linked decision: D-NNN` references resolve
- [ ] All `PR: #N` links resolve

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

If the *same* session also produced doc changes routed through `/knowledge-curator`, the two skills should **share a single PR** when both fire in sequence — see the coordination section below.

### 7. Report back

```
Work tracker updated:
- New: S-1.5.1 Reddit search connector (3 tasks)
- Advanced: E-1.4 → 🟢 shipped (PR #67)
PR: <url>
```

## Coordination with `/knowledge-curator`

Both skills run after a session and both open PRs. To avoid two PRs for the same session:

- The skill that runs **second** detects that a sibling branch from the same session exists (`docs/...-<date>` or `work/...-<date>` already pushed within the last hour by Claude) and:
  1. Does its edits on a *new* branch
  2. After committing, opens its PR independently
  3. Mentions the sibling PR in its body (`Companion PR: #N`)
- Alternatively (preferred when both fire close together): the second skill checks out the first skill's branch, applies its edits there, amends nothing — adds a new commit, pushes, and updates the existing PR's body. This requires the first skill's branch to still exist locally.

For now, default to **separate PRs with cross-references in bodies**. Combining is a v2 enhancement.

## What this skill does NOT do

- ❌ Edit `docs/feature-roadmap.md`, `docs/architecture.md`, or any non-initiatives doc — that's `/knowledge-curator`'s job
- ❌ Make decisions — only record/link to decisions made in conversation
- ❌ Renumber existing IDs
- ❌ Delete history (cancelled / shipped items stay)
- ❌ Run code or modify anything outside `docs/initiatives.md`
- ❌ Merge PRs — the user merges
- ❌ Touch `MEMORY.md`

## Failure mode

Same as `/knowledge-curator`: if `gh` / push fails, complete local commits, print the manual commands, don't roll back.
