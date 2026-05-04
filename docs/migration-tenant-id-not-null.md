# Migration runbook — `tenant_id` NOT NULL constraint (E-5.1 phase 2c / T-5.1.2c)

**Status:** Operator-driven migration guide. Owns the safe-execution story for the final phase of the [E-5.1 tenancy retrofit](initiatives.md#e-51--tenant_id-audit--retrofit) — promoting `tenant_id` from NULLABLE (today) to `NOT NULL` (after this runbook).

**Audience.** Self-hosters whose backfill from [PR #151](https://github.com/khoks/VideoResearchPro/pull/151) (E-5.1 phase 2a) has run successfully and who want to lock in the schema-level guarantee that no row can be created without a tenant attribution. Fresh installs that came up after PR #151 already have every row populated; they just haven't tightened the constraint yet.

**Key promise.** Same as the sibling runbooks ([`docs/migration-channels-to-creators.md`](migration-channels-to-creators.md), [`docs/migration-code-identifiers.md`](migration-code-identifiers.md)): this runbook never destroys data. Every step is reversible up to the point the operator deletes the legacy backup. The promise rests on the [D-032](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) precedent and [D-038](decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04) phase split.

**Why operator-coordinated.** The application logic since PR #151 always populates `tenant_id` on insert; the read-side filter from PR #152 hides any (theoretical) row where the column is NULL. So in steady-state operation, `tenant_id IS NULL` should never appear. **But** — the operator is the only party who can prove that:

1. Their phase-2a backfill ran cleanly (no errors, no skipped rows).
2. No third-party scripts or admin SQL have inserted rows since phase 2a without populating `tenant_id`.
3. No legacy rows were re-introduced from a backup/restore cycle that pre-dated phase 2a.

A bad NOT NULL flip on a SQLite database with even one NULL row crashes the migration mid-batch and leaves the schema in a half-migrated state. Self-hosters who have followed the standard upgrade path will be fine; operators who have done unusual things (custom scripts, multi-restore cycles, manual SQL inserts) won't be — and only they know which group they're in.

So phase 2c ships as this runbook + the migration file (already written in `backend/alembic/versions/`, never auto-applied at startup). The operator runs `alembic upgrade head` on their own schedule, after running the pre-flight verification.

---

## What's changing

| Surface | Today | After this runbook |
|---|---|---|
| `jobs.tenant_id` | `NULL` allowed | `NOT NULL` enforced at DB |
| `qa_exchanges.tenant_id` | `NULL` allowed | `NOT NULL` enforced at DB |
| `library_qa_exchanges.tenant_id` | `NULL` allowed | `NOT NULL` enforced at DB |
| `qa_history_exchanges.tenant_id` | `NULL` allowed | `NOT NULL` enforced at DB |
| ORM `tenant_id: Mapped[str \| None]` | `\| None` | `Mapped[str]` (no `\| None`) |
| Application logic | always populates | unchanged |
| Read-side filter | `WHERE tenant_id = current_user.id` | unchanged |

After this runbook:
- The schema rejects any `INSERT … (tenant_id) VALUES (NULL)`. The application already never sends one.
- The ORM signals to type checkers that `job.tenant_id` is a guaranteed `str`, not `str | None`. Eliminates a class of `None`-handling defensive code in future PRs.
- Cross-tenant isolation has both belt (router filter) and suspenders (schema constraint).

---

## Pre-flight checklist

This is the **critical** part. Run all four checks before applying the migration. Any non-zero result aborts the runbook.

### 1. Stop all writers

```bash
# Stop the FastAPI server
# (whatever your process manager / supervisord / systemd unit is)

# Stop the Celery worker
# Ctrl-C the worker shell, or stop the systemd unit
```

The migration is fast (a single `ALTER COLUMN` per table on SQLite, batched), but having writers active during the flip can cause a "database is locked" error and an aborted migration.

### 2. Backup the database

```bash
cp data/pratidhvani.db data/pratidhvani.db.bak.pre-tenant-not-null
```

The migration is reversible by SQL (rollback steps below) but a file backup is cheap insurance and lets you A/B-test the post-migration smoke test against pre-migration behaviour.

### 3. Verify zero NULL rows on every target table

This is the **make-or-break** check. Any NULL row will crash the migration. Run this exact SQL via your favourite client (`sqlite3`, DBeaver, or the inline Python below):

```bash
./venv/Scripts/python -c "
from app.database import SessionLocal
from sqlalchemy import text

EXPECT_ZERO = [
    ('jobs', 'tenant_id'),
    ('qa_exchanges', 'tenant_id'),
    ('library_qa_exchanges', 'tenant_id'),
    ('qa_history_exchanges', 'tenant_id'),
]

with SessionLocal() as s:
    fail = False
    for table, col in EXPECT_ZERO:
        n = s.execute(text(f'SELECT COUNT(*) FROM {table} WHERE {col} IS NULL')).scalar()
        marker = 'OK   ' if n == 0 else 'FAIL '
        if n != 0:
            fail = True
        print(f'{marker} {table}.{col} IS NULL count: {n}')
    if fail:
        print()
        print('STOP. Resolve the NULL rows before applying the migration.')
        print('See \"Resolving NULL rows\" below.')
        raise SystemExit(1)
    else:
        print()
        print('All clear. Safe to proceed with `alembic upgrade head`.')
"
```

**If every line reads `OK`, proceed to step 5. If any line reads `FAIL`, jump to "Resolving NULL rows" below before continuing.**

### 4. Verify row counts (for post-migration comparison)

Record the row counts so the post-migration check confirms nothing was lost:

```bash
./venv/Scripts/python -c "
from app.database import SessionLocal
from sqlalchemy import text

TABLES = ['jobs', 'qa_exchanges', 'library_qa_exchanges', 'qa_history_exchanges']

with SessionLocal() as s:
    for t in TABLES:
        n = s.execute(text(f'SELECT COUNT(*) FROM {t}')).scalar()
        print(f'{t}: {n}')
"
```

Save the output somewhere; you will compare against it after `alembic upgrade head`.

---

## Resolving NULL rows

If step 3 reported any NULL rows, your phase-2a backfill from PR #151 didn't fully cover the table — typically because rows were inserted between the migration's `WHERE tenant_id IS NULL` filter and the next `INSERT`, or because rows were restored from a pre-PR-#151 backup.

### Option A — Re-run the phase-2a backfill

The phase-2a migration is **idempotent**: `UPDATE … SET tenant_id = (first user's id) WHERE tenant_id IS NULL`. Re-running it against the current state will pick up any NULL rows added since the original run.

```bash
cd backend
./venv/Scripts/alembic upgrade b2c3d4e5f6a7   # phase 2a backfill
```

(If you're already at or past `b2c3d4e5f6a7`, this is a no-op — Alembic only applies pending migrations. To force it, downgrade first to `d5e6f7a8b9c0` then back up.)

After re-running, repeat step 3 of the pre-flight check.

### Option B — Manual attribution

For multi-user installs where some legacy rows belong to a non-first-user, attribute each NULL row to its correct user manually:

```bash
./venv/Scripts/python -c "
from app.database import SessionLocal
from sqlalchemy import text

# Inspect the orphaned rows first to figure out who they belong to.
# 'jobs' is the easiest: it has 'topic' / 'channel_list' / 'created_at' that
# usually identify the originating user.
with SessionLocal() as s:
    rows = s.execute(text('''
        SELECT id, job_type, topic, created_at
        FROM jobs WHERE tenant_id IS NULL
        ORDER BY created_at LIMIT 50
    ''')).all()
    for row in rows:
        print(row)
"
```

Once you have the mapping (job_id → tenant_id), update each row:

```bash
./venv/Scripts/python -c "
from app.database import SessionLocal
from sqlalchemy import text

# Replace the dict with your mapping.
MAPPING = {
    'job-uuid-1': 'user-uuid-A',
    'job-uuid-2': 'user-uuid-B',
}

with SessionLocal() as s:
    for job_id, user_id in MAPPING.items():
        s.execute(
            text('UPDATE jobs SET tenant_id = :u WHERE id = :j'),
            {'u': user_id, 'j': job_id},
        )
    s.commit()
    print(f'Updated {len(MAPPING)} rows.')
"
```

Repeat the same shape for `qa_exchanges`, `library_qa_exchanges`, `qa_history_exchanges` if those tables had NULL rows.

After all NULL rows are attributed, repeat step 3 of the pre-flight check. **Do not proceed until every line reads `OK`.**

---

## Migration script

The Alembic migration file ships at:

```
backend/alembic/versions/e6f7a8b9c0d1_tenant_id_not_null.py
```

It uses `op.batch_alter_table()` for each of the four tables to flip `nullable=False`. SQLite emulates `ALTER COLUMN` by recreating the table; the batch operation is atomic per-table and rolls back cleanly if a NULL row is encountered (which is why the pre-flight check matters — it's much cheaper to discover NULL rows in a SELECT than mid-batch).

**To apply:**

```bash
cd backend
./venv/Scripts/alembic upgrade head
```

Expected output:

```
INFO  [alembic.runtime.migration] Running upgrade b2c3d4e5f6a7 -> e6f7a8b9c0d1, tenant_id_not_null
```

(One line per migration applied; on a fresh-from-PR-#152 install only the tenant-not-null migration applies. On an older install you may see other intermediate migrations.)

If the migration crashes mid-flight with a NULL constraint violation, **rollback the database file** (see Rollback below) and re-run the pre-flight check. Do not retry the migration on the half-migrated database.

---

## Post-migration smoke test

### 1. Restart writers

```bash
# Restart FastAPI
cd backend && ./venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Restart Celery (separate shell)
cd backend && ./venv/Scripts/celery -A app.tasks.celery_app worker --loglevel=info --pool=solo
```

### 2. Verify row counts haven't changed

Re-run the row-count snippet from pre-flight step 4. Each table should show the same count as before.

### 3. Verify schema reflects the constraint

```bash
./venv/Scripts/python -c "
from app.database import SessionLocal
from sqlalchemy import text

with SessionLocal() as s:
    for table in ['jobs', 'qa_exchanges', 'library_qa_exchanges', 'qa_history_exchanges']:
        info = s.execute(text(f'PRAGMA table_info({table})')).all()
        for col in info:
            if col[1] == 'tenant_id':
                # SQLite PRAGMA: cid, name, type, notnull, dflt_value, pk
                notnull = bool(col[3])
                marker = 'OK   ' if notnull else 'FAIL '
                print(f'{marker} {table}.tenant_id NOT NULL = {notnull}')
"
```

All four lines should read `OK   ... NOT NULL = True`.

### 4. End-to-end smoke

Hit the app:

- Log in. The dashboard / Jobs list loads — same rows as before.
- Open any existing job. Q&A history is still visible.
- Create a new topic job. It succeeds (proves the write path stamps `tenant_id` correctly under the new constraint).
- Ask a Q&A question on the new job. It succeeds.

### 5. Optional ORM tightening (small follow-up PR)

In a future PR, the ORM models can drop the `| None` from the typed mapping:

```python
# backend/app/models/job.py
- tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
+ tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
```

Same for `qa_exchange.py`, `library_qa_exchange.py`, `qa_history_exchange.py`. This is purely a typing hint upgrade; the schema-level constraint is what enforces correctness. Defer until a calm PR — the application works correctly with or without it.

---

## Rollback

If anything looks wrong post-migration:

### Option A — Restore from backup (fast, lossless)

```bash
# Stop writers (FastAPI + Celery)
cp data/pratidhvani.db.bak.pre-tenant-not-null data/pratidhvani.db
# Restart writers
```

The legacy NULLABLE schema is back. Application logic works unchanged because the read-side filter and write-side stamping (PRs #151 / #152) tolerate `tenant_id` being either `NULL` or set.

### Option B — Alembic downgrade (slower, no backup needed)

```bash
cd backend
./venv/Scripts/alembic downgrade -1
```

This re-introduces nullability via the same `batch_alter_table` mechanism. Functionally equivalent to restoring the backup but takes a minute or two to recreate the four tables.

After either rollback path, file an issue describing what went wrong; the most-likely cause is a row that NULLed between the pre-flight check and the migration (some external process running). Identify the source of the NULL row, stop it, then re-run the runbook from pre-flight step 1.

---

## Future-proofing for SaaS

When the Pratidhvani SaaS deployment ships ([I-5](initiatives.md#i-5--saas-readiness-long-horizon)), the NOT NULL constraint becomes part of the **fresh-install schema**. The runbook then exists only as a historical artifact for self-hosters who started before SaaS launch and never tightened their constraint. SaaS-internal multi-tenant infrastructure runs the same Alembic migration once, in a coordinated maintenance window — operationally it's the same SQL, the audience is just "the SaaS infra team" rather than "self-host operators".

For multi-workspace-per-user (T-5.1.3, deferred to team SaaS tier), the column will be split: `tenant_id` (the workspace) + `owner_id` (the user). Both will be NOT NULL once that work lands. The four-phase pattern from D-038 will be re-used: audit → additive → backfill+writes → reads → NOT NULL.

---

## Cross-references

- [E-5.1 in `initiatives.md`](initiatives.md#e-51--tenant_id-audit--retrofit) — the work item.
- [D-038 — Tenancy retrofit ships in four phases](decisions.md#d-038--tenancy-retrofit-ships-in-four-phases-audit--additive--backfillwrites--reads--not-null-2026-05-04) — the phase-split rationale.
- [D-032 — Operator-coordinated runbook vs auto migration](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) — the precedent.
- [`docs/saas-tenant-id-audit.md`](saas-tenant-id-audit.md) — the phase-0 audit.
- [`docs/migration-code-identifiers.md`](migration-code-identifiers.md) — the sibling runbook for brand-identifier renames.
- [`docs/migration-channels-to-creators.md`](migration-channels-to-creators.md) — the sibling runbook for the channels→creators rename.
- PRs [#149](https://github.com/khoks/VideoResearchPro/pull/149) (audit), [#150](https://github.com/khoks/VideoResearchPro/pull/150) (additive), [#151](https://github.com/khoks/VideoResearchPro/pull/151) (backfill+writes), [#152](https://github.com/khoks/VideoResearchPro/pull/152) (reads).
