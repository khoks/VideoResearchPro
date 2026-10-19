"""Round-trip of ``3653e565c1fc`` (D-070) against the real migration chain
on a scratch SQLite file: upgrade re-keys live grants on ``document_id`` and
drops orphans; downgrade restores ``video_id`` and drops the grants the old
schema cannot represent; a second upgrade is clean.
"""
from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

PREVIOUS = "d8e9f0a1b2c3"  # shelves (S-8.1.1), the head this revision was rebased onto
THIS = "3653e565c1fc"

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'd070.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


def _exec(eng, sql, **params):
    with eng.begin() as conn:
        result = conn.execute(text(sql), params)
        return result.fetchall() if result.returns_rows else None


def _columns(eng, table):
    return {c["name"] for c in inspect(eng).get_columns(table)}


def _seed_pre_d070(eng):
    for doc_id, vid, st, sid in (
        ("doc-vid", "yt11111111a", "video", "yt11111111a"),
        ("doc-pdf", None, "pdf", "pdf:abc"),
    ):
        _exec(
            eng,
            "INSERT INTO documents (document_id, video_id, source_type, source_id, title, url, "
            "transcript_status, embedded_in_chroma, created_at, updated_at) "
            "VALUES (:d, :v, :st, :sid, 't', 'u', 'fetched', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            d=doc_id, v=vid, st=st, sid=sid,
        )
    for gid, vid, tenant in (
        ("g1", "yt11111111a", "tenant-a"),
        ("g2", "yt11111111a", "tenant-b"),
        ("g-orphan", "ytGONE00000", "tenant-a"),
    ):
        _exec(
            eng,
            "INSERT INTO document_visibility (id, video_id, tenant_id, source, created_at) "
            "VALUES (:g, :v, :t, 'job', CURRENT_TIMESTAMP)",
            g=gid, v=vid, t=tenant,
        )


def test_upgrade_rekeys_grants_and_downgrade_restores_them(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, PREVIOUS)
    assert "video_id" in _columns(eng, "document_visibility")
    _seed_pre_d070(eng)

    command.upgrade(cfg, THIS)
    cols = _columns(eng, "document_visibility")
    assert "document_id" in cols and "video_id" not in cols
    rows = _exec(eng, "SELECT id, document_id, tenant_id FROM document_visibility ORDER BY id")
    assert rows == [("g1", "doc-vid", "tenant-a"), ("g2", "doc-vid", "tenant-b")], (
        "video grants re-keyed; the orphan (no documents row) dropped"
    )
    insp = inspect(eng)
    assert any(
        set(u["column_names"]) == {"document_id", "tenant_id"}
        for u in insp.get_unique_constraints("document_visibility")
    )
    assert any(
        fk["referred_table"] == "documents" and fk["referred_columns"] == ["document_id"]
        for fk in insp.get_foreign_keys("document_visibility")
    )
    assert {"ix_document_visibility_document_id", "ix_document_visibility_tenant_document"} <= {
        i["name"] for i in insp.get_indexes("document_visibility")
    }

    # The thing the whole story is for: a grant over a PDF can now be stored.
    _exec(
        eng,
        "INSERT INTO document_visibility (id, document_id, tenant_id, source, created_at) "
        "VALUES ('g3', 'doc-pdf', 'tenant-a', 'pdf_upload', CURRENT_TIMESTAMP)",
    )
    with pytest.raises(Exception, match="UNIQUE"):
        _exec(
            eng,
            "INSERT INTO document_visibility (id, document_id, tenant_id, source, created_at) "
            "VALUES ('g3dup', 'doc-pdf', 'tenant-a', 'pdf_upload', CURRENT_TIMESTAMP)",
        )
    with pytest.raises(Exception, match="NOT NULL"):
        _exec(
            eng,
            "INSERT INTO document_visibility (id, document_id, tenant_id, source, created_at) "
            "VALUES ('g-null', NULL, 'tenant-a', 'job', CURRENT_TIMESTAMP)",
        )

    command.downgrade(cfg, PREVIOUS)
    cols = _columns(eng, "document_visibility")
    assert "video_id" in cols and "document_id" not in cols
    rows = _exec(eng, "SELECT id, video_id, tenant_id FROM document_visibility ORDER BY id")
    assert rows == [("g1", "yt11111111a", "tenant-a"), ("g2", "yt11111111a", "tenant-b")], (
        "video grants restored; the PDF grant cannot be represented and is dropped"
    )
    assert any(
        set(u["column_names"]) == {"video_id", "tenant_id"}
        for u in inspect(eng).get_unique_constraints("document_visibility")
    )

    command.upgrade(cfg, THIS)
    assert _exec(eng, "SELECT id, document_id FROM document_visibility ORDER BY id") == [
        ("g1", "doc-vid"), ("g2", "doc-vid"),
    ]


def test_migration_is_the_head_the_orm_expects(migrated):
    """Fresh install reaches this revision and the live table matches the
    ORM column set — the schema-init drift check would refuse to boot
    otherwise."""
    from app.database import Base
    import app.models  # noqa: F401

    cfg, eng = migrated
    command.upgrade(cfg, "head")
    # Later revisions (shelves, tags, ...) build on this one, so assert it is
    # in the applied lineage rather than that it is literally the head.
    from alembic.script import ScriptDirectory

    (current,) = _exec(eng, "SELECT version_num FROM alembic_version")[0]
    lineage = {
        rev.revision
        for rev in ScriptDirectory.from_config(cfg).walk_revisions(base="base", head=current)
    }
    assert THIS in lineage, "a fresh install must pass through the D-070 revision"
    orm = {c.name for c in Base.metadata.tables["document_visibility"].columns}
    assert _columns(eng, "document_visibility") == orm
