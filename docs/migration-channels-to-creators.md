# Migration runbook — `channels` → `creators` (E-1.9)

**Status:** Operator-driven migration guide. Owns the safe-execution story for the SQL-level rename of the `channels` table to `creators` plus the FK column rename `documents.channel_id` → `documents.creator_id`.

**Audience.** Self-hosters who want to bring their schema in line with the going-forward naming. Fresh installations don't need this runbook — when E-1.9 phase 2 ships (a future PR that flips the default `__tablename__` to `creators`), new installs will start with `creators` directly.

**Key promise.** Same as `docs/migration-code-identifiers.md`: this runbook never destroys data. Every step is reversible up to the point the operator deletes the legacy backup. The promise rests on the same precedent established by [D-032](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03).

**Why operator-coordinated.** Renaming a table + column with an FK chain on a production SQLite database is risky if done at startup automatically:

1. SQLite doesn't natively support `RENAME COLUMN` for columns referenced by foreign keys; Alembic's `batch_alter_table` works but a crash mid-batch leaves the schema in a half-renamed state.
2. The default-keep-old-name policy matches operator expectations on `git pull master`.
3. Operators who want to evaluate side-by-side instances of old + new schemas need the freedom to opt in on their own schedule.

So the rename ships as a Python-level alias today (already in master) and the SQL-level rename runs via this runbook.

---

## What's renaming and what's NOT

| Surface | Today | After this runbook | Mode |
|---------|-------|---------------------|------|
| Python class name | `Channel` (with `Creator` alias) | both still resolve | already shipped |
| Python module | `app.models.channel` (with `app.models.creator` re-export) | both still resolve | already shipped |
| **`channels` table** | `channels` | `creators` | ⚠️ this runbook §A |
| **`documents.channel_id` FK column** | `channel_id` | `creator_id` | ⚠️ this runbook §B |
| `channel_id` PK column on creators | `channel_id` | `channel_id` (kept for back-compat) | unchanged |
| `Channel.channel_name` field | `name` (the actual column is `name`) | unchanged | unchanged |
| `/api/v1/channels/...` REST endpoints | `/channels/...` | `/channels/...` (kept; aliases `/creators/...` may be added in future) | unchanged |

After this runbook, the schema reads:

```
creators
  channel_id PK            -- legacy column name preserved
  name
  source_type
  creator_external_id
  source_weight
  ... etc

documents
  document_id PK
  ...
  creator_id FK -> creators.channel_id   -- FK column renamed; target column unchanged
```

The Python `Channel` and `Creator` aliases continue to work against the renamed schema because SQLAlchemy's class-to-table mapping is set in the model's `__tablename__`, which Phase 2 of E-1.9 (a small follow-up PR) flips to `"creators"` after the runbook has executed in the field.

---

## §A — Renaming the `channels` table

### Pre-migration checklist

1. **Stop all writers**:
   - `uvicorn` (FastAPI)
   - The Celery worker
   - Any cron / scheduled-task that hits the API
2. **Backup the database**:
   ```bash
   cp data/pratidhvani.db data/pratidhvani.db.bak.pre-creators
   ```
   The migration is reversible by SQL but a file backup is cheap insurance.
3. **Verify row counts**:
   ```bash
   ./venv/Scripts/python -c "
   from app.database import SessionLocal
   from app.models import Channel
   from sqlalchemy import func
   with SessionLocal() as s:
       print('Channels:', s.query(func.count(Channel.channel_id)).scalar())
   "
   ```
   Record the count. The post-migration check verifies the same number on the renamed table.

### Migration script

The migration is a single Alembic revision that:
1. Renames `channels` → `creators` via `op.rename_table`.
2. Renames `documents.channel_id` → `documents.creator_id` via `batch_alter_table`.
3. Drops + recreates the `documents.channel_id` index as `documents.creator_id`.

The actual Alembic file ships in **E-1.9 Phase 2** (a future PR). For now, when an operator wants to execute, they generate it themselves with:

```bash
cd backend
./venv/Scripts/alembic revision --autogenerate -m "rename_channels_to_creators"
```

…and inspect the generated migration carefully before running. Or wait for Phase 2 to land (planned in the I-1 closure trajectory).

### Post-migration

1. Update `app/models/channel.py`'s `__tablename__` to `"creators"` (and the `Channel.channel_id` field's FK targets, though there are none today).
2. Update `app/models/document.py`'s `channel_id` field name → `creator_id` and FK target string.
3. Restart `uvicorn` + the Celery worker.
4. **Smoke test**: `GET /api/v1/channels` returns the same rows; `GET /api/v1/library/videos` shows correct channel names.

### Rollback

If anything looks wrong:
1. Stop writers.
2. Restore the SQLite backup: `cp data/pratidhvani.db.bak.pre-creators data/pratidhvani.db`.
3. Restart writers. The legacy `channels` schema is back; the Python `Channel` / `Creator` aliases continue to resolve correctly.

---

## §B — Future-proofing for SaaS-tier operators

When the Pratidhvani SaaS deployment ships, this runbook becomes a SaaS-internal operations task: the SaaS team controls the data layer end-to-end and runs the rename across all tenants in a coordinated maintenance window. The same Alembic migration applies — only the audience changes (operators-of-self-host vs. SaaS-team-with-many-tenants).

For multi-tenant SaaS specifically, when E-5.1 (`tenant_id` retrofit) lands, the rename happens once per migration step rather than per-tenant — table-level renames are global in SQL.

---

## Cross-references

- [E-1.9 in `initiatives.md`](initiatives.md#e-19--rename-channels--creators-db--orm) — the work item.
- [D-032 — Operator-coordinated runbook vs auto migration](decisions.md#d-032--operator-coordinated-runbook-vs-automatic-startup-migration-for-data-bearing-identifier-renames-2026-05-03) — the precedent.
- [`docs/migration-code-identifiers.md`](migration-code-identifiers.md) — the sibling runbook for brand-identifier renames.
- [`app/models/creator.py`](../backend/app/models/creator.py) — the Python-level alias module.
- [`app/models/channel.py`](../backend/app/models/channel.py) — the canonical class definition (until Phase 2 flips `__tablename__`).
