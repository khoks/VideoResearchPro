# Migration runbook — code-identifier rename (legacy `videoresearchpro` → `pratidhvani`)

**Status:** Operator-driven migration guide. Owns the safe-execution story for [E-2.6 T-2.6.1](initiatives.md#e-26--code-identifier-rename-pass) (Chroma collection rename) and [T-2.6.2](initiatives.md#e-26--code-identifier-rename-pass) (DB filename rename). Rationale for the operator-coordinated approach (vs an automatic startup migration) is in [D-032](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03).

**Audience.** Self-hosters running Pratidhvani against a non-trivial library (more than a handful of jobs). Fresh installations don't need this runbook — set the new env vars in `.env` and skip everything below.

**Key promise.** This runbook never destroys data. Every step is reversible by re-pointing env vars at the legacy names. The risk pattern is *misconfiguration* (wrong env var → app sees no data and shows an empty library), not *data loss*.

---

## What's renaming and what's NOT

| Surface | Legacy default | New default | Rename mode |
|---------|---------------|-------------|-------------|
| Brand copy in pages, docs, README, CLAUDE.md | `VideoResearchPro` | `Pratidhvani` | ✅ already migrated (PRs #97, brand work) |
| `APP_NAME` env default | `VideoResearchPro` | `Pratidhvani` | ✅ already migrated |
| Health endpoint banner / startup log | `VideoResearchPro` | `Pratidhvani` | ✅ already migrated |
| **`CHROMA_GLOBAL_COLLECTION_NAME`** | `videoresearchpro_global` | `pratidhvani_global` | ⚠️ **operator-coordinated** (this runbook, §A) |
| **`DATABASE_URL`** | `sqlite:///./data/videoresearchpro.db` | `sqlite:///./data/pratidhvani.db` | ⚠️ **operator-coordinated** (this runbook, §B) |
| GitHub repo URL | `khoks/VideoResearchPro` | `khoks/pratidhvani` (or similar) | 🔵 outside-codebase, optional (§C) |

The non-renamed identifiers above are the **only** legacy strings carried in the running system today. Everything else (Python package paths, docstrings, test fixtures, internal symbol names) was either already neutral (e.g. `app.*` package names) or migrated in PR [#97](https://github.com/khoks/VideoResearchPro/pull/97).

---

## Why these two are operator-coordinated

Both `CHROMA_GLOBAL_COLLECTION_NAME` and `DATABASE_URL` are **production data-mutating** when changed naively:

- Changing `CHROMA_GLOBAL_COLLECTION_NAME` without a backfill would orphan every embedding the system has ever computed. The new collection starts empty; existing chunks live under the old collection name and become unreachable to retrieval. Q&A would silently return "no results" against a library the user spent days building.
- Changing `DATABASE_URL` without copying the SQLite file similarly orphans every job, channel, Q&A exchange, and knowledge artifact. The app comes up with empty tables.

We could ship an automatic startup migration that detects the old name + transparently moves data. We don't, because:

- Embedding-collection rename in ChromaDB is not atomic. A crash mid-rename would leave half the chunks under each name.
- The default is a deliberate non-rename so existing self-hosters can pull master without surprise data motion.
- Some operators may want to run both old and new instances side-by-side during evaluation.

So the migration is operator-driven, with this runbook as the safe-execution checklist.

---

## §A — Migrating the Chroma collection

### Scope

`CHROMA_GLOBAL_COLLECTION_NAME` defaults to `videoresearchpro_global`. To rename to `pratidhvani_global`:

### Pre-migration checklist

1. **Stop all writers**:
   - `uvicorn` (the FastAPI process)
   - The Celery worker
   - Any cron / scheduled-task that hits the API
2. **Verify the data exists** in the legacy collection. From the backend dir:
   ```bash
   ./venv/Scripts/python -c "
   import chromadb
   from app.config import settings
   c = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
   coll = c.get_or_create_collection('videoresearchpro_global')
   print(f'Legacy collection: {coll.count()} chunks')
   "
   ```
   Record the count. The post-migration check verifies the same number lands in the new collection.

### Backfill procedure

Run this script from the backend dir (you'll save it as `scripts/migrate_chroma_collection_name.py`; the script is short and one-shot, not committed to the repo because it's a one-time operation):

```python
"""One-time Chroma collection rename: videoresearchpro_global → pratidhvani_global.

Read every chunk from the legacy collection (in pages of N=500 to bound
memory), upsert into the new collection, then verify counts match before
deleting the legacy collection.

Run from `backend/` with the venv activated. Idempotent — safe to re-run
if it crashes mid-way."""
from __future__ import annotations
import chromadb
from app.config import settings

OLD = "videoresearchpro_global"
NEW = "pratidhvani_global"
PAGE = 500

client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
old = client.get_collection(OLD)
total = old.count()
print(f"Legacy {OLD}: {total} chunks")

new = client.get_or_create_collection(
    NEW, metadata={"scope": "global"}
)

# Walk in pages — Chroma doesn't expose an iterator so we slice via
# `.get(limit=PAGE, offset=...)`.
moved = 0
offset = 0
while offset < total:
    page = old.get(limit=PAGE, offset=offset, include=["embeddings", "metadatas", "documents"])
    if not page["ids"]:
        break
    new.upsert(
        ids=page["ids"],
        embeddings=page["embeddings"],
        metadatas=page["metadatas"],
        documents=page["documents"],
    )
    moved += len(page["ids"])
    print(f"  upserted {moved}/{total}")
    offset += PAGE

assert new.count() >= moved, "post-migration count mismatch — STOP, investigate"
print(f"New {NEW}: {new.count()} chunks ✓")
```

Run:
```bash
./venv/Scripts/python scripts/migrate_chroma_collection_name.py
```

### Post-migration

1. **Update `.env`**:
   ```
   CHROMA_GLOBAL_COLLECTION_NAME=pratidhvani_global
   ```
2. **Restart** uvicorn + the Celery worker.
3. **Smoke test** Q&A — submit a question against a job whose chunks were in the legacy collection. Confirm the answer cites real sources (not "no relevant context").
4. **Once verified**, delete the legacy collection:
   ```python
   client.delete_collection("videoresearchpro_global")
   ```
   Don't do this until step 3 is green. Once deleted, recovery is restoring from a `data/chroma/` backup.

### Rollback

If anything looks wrong post-migration (Q&A returns nothing, chunk count mismatch, etc.):
1. Set `CHROMA_GLOBAL_COLLECTION_NAME=videoresearchpro_global` in `.env`.
2. Restart.
3. The system uses the legacy collection again; the new collection sits unused (delete it later if you don't want it).

---

## §B — Migrating the SQLite database file

### Scope

`DATABASE_URL` defaults to `sqlite:///./data/videoresearchpro.db`. To rename to `sqlite:///./data/pratidhvani.db`:

### Pre-migration checklist

1. **Stop all writers** (uvicorn + Celery worker).
2. **Confirm a backup exists** of `data/videoresearchpro.db`. The migration is a file rename, but a copy is cheap insurance.

### Migration procedure

```bash
cp data/videoresearchpro.db data/videoresearchpro.db.bak  # safety copy
mv data/videoresearchpro.db data/pratidhvani.db
```

Update `.env`:
```
DATABASE_URL=sqlite:///./data/pratidhvani.db
```

### Post-migration

1. Start uvicorn. The first startup will run any pending Alembic migrations against the renamed file — no schema change, just a path change.
2. Hit `GET /api/v1/health` to confirm the API is up.
3. Open the Jobs page in the frontend; confirm your existing jobs are listed.

### Rollback

```bash
mv data/pratidhvani.db data/videoresearchpro.db
# restore .env to DATABASE_URL=sqlite:///./data/videoresearchpro.db
```

The `.bak` file is your final fallback — restore from it only if the rename caused corruption (it shouldn't; SQLite files are file-rename-safe).

---

## §C — Optional: GitHub repo rename

If you want to rename the GitHub repo from `khoks/VideoResearchPro` to `khoks/pratidhvani`:

1. **GitHub auto-redirects** old URLs (issues, PRs, clone URLs) for an indefinite period — no broken links.
2. **Local clones** keep working but `git remote -v` will still show the old URL until you re-point it:
   ```bash
   git remote set-url origin https://github.com/khoks/pratidhvani.git
   ```
3. **CI configs** (GitHub Actions, badges in READMEs, Dependabot, etc.) that reference the old repo name need a one-time update. There are none today besides what's in `.github/`.

This is genuinely outside the codebase, so it's listed here for completeness but not a runbook step the user needs to walk through inside the repo.

---

## Verification checklist

After §A + §B are complete, verify the system holistically:

- [ ] `GET /api/v1/health` returns 200 with `app_name == "Pratidhvani"`.
- [ ] Jobs page lists your existing jobs.
- [ ] Library page lists your existing documents (chunk count > 0 for at least one).
- [ ] Submit a fresh Q&A question scoped to one of those jobs; confirm the answer cites real sources.
- [ ] Submit a fresh Q&A question scoped to the entire library; confirm same.
- [ ] `data/pratidhvani.db` exists; `data/videoresearchpro.db.bak` exists (don't delete the backup until you've used the system for a few days).
- [ ] ChromaDB has only `pratidhvani_global` and `qa_library_global` collections (the legacy `videoresearchpro_global` is gone).

If any check fails, follow the relevant rollback section. The migration is fully reversible up to the point you delete the legacy backup.

---

## Cross-references

- Decision context: [E-2.6 in `initiatives.md`](initiatives.md#e-26--code-identifier-rename-pass) — the rationale for splitting brand-copy migration (immediate, PR #97) from data-bearing-identifier migration (operator-coordinated, this runbook).
- Brand identity source-of-truth: [`branding.md`](branding.md) and [`vision.md`](vision.md).
- For new self-hosters who don't have a legacy library: just set the new env vars in `.env` from the start. No migration needed.
