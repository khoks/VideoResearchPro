# Pratidhvani — Inventions / Novel-Idea Log

**Status:** living doc (last refreshed 2026-04-25). Owner: [`/knowledge-curator`](../.claude/skills/knowledge-curator/SKILL.md) skill.

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

*No invention entries yet. The first `N-001` will be filed when a candidate idea surfaces in conversation matching the [detection heuristic](../.claude/skills/knowledge-curator/SKILL.md#detection-heuristic--when-to-file-an-n-nnn) in the curator skill.*

---

## Cross-references

- [`decisions.md`](decisions.md) — decisions choose between known options; this log captures *new* mechanisms.
- [`vision.md`](vision.md) — vision describes goals; this log captures specific *means*.
- [`feature-roadmap.md`](feature-roadmap.md) — once an invention realizes as a feature, the roadmap entry should add `Realizes invention [N-NNN](inventions.md#n-NNN-...).`
- [`docs/notes/`](notes/) — verbatim user messages preserved as raw safekeeping artifacts.
