"""S-8.6.2 — the starter templates migration (`f1a2b3c4d5e6`).

Against the real migration chain on a scratch SQLite file: upgrade seeds the
five built-ins with valid recipes; re-running the upsert is a no-op;
revising a starter adds a version instead of rewriting history; downgrade
removes them; a second upgrade restores them.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.schemas.job_template import TemplateParameters
from app.services import job_template_service

THIS = "f1a2b3c4d5e6"
PREVIOUS = "f0a1b2c3d4e5"
_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PATH = os.path.join(_BACKEND, "alembic", "versions", "f1a2b3c4d5e6_starter_templates.py")


def load_migration():
    spec = importlib.util.spec_from_file_location("starter_templates_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'starters.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


def _builtins(eng):
    with eng.connect() as conn:
        return {
            key: (latest, name)
            for key, latest, name in conn.execute(
                text("SELECT builtin_key, latest_version, name FROM job_templates WHERE tenant_id IS NULL")
            )
        }


def test_every_starter_is_a_valid_recipe():
    """Each starter must survive the same validation a reader's save does,
    and none may switch on visual analysis (its opt-in is deferred)."""
    starters = load_migration().STARTERS
    assert len(starters) == 5
    assert len({s["builtin_key"] for s in starters}) == 5
    for s in starters:
        params = TemplateParameters(**s["parameters"])
        job_template_service.validate_parameters(params)
        assert params.job_type == s["job_type"]
        assert params.visual_analysis is False
        if params.job_type == "topic":
            assert "{{topic}}" in (params.search_instructions or "")


def test_upgrade_seeds_downgrade_removes_upgrade_restores(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, THIS)
    seeded = _builtins(eng)
    assert set(seeded) == {s["builtin_key"] for s in load_migration().STARTERS}
    assert all(latest == 1 for latest, _ in seeded.values())

    command.downgrade(cfg, PREVIOUS)
    assert _builtins(eng) == {}

    command.upgrade(cfg, THIS)
    assert set(_builtins(eng)) == set(seeded)


def test_upsert_is_idempotent_and_versions_a_revision(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, THIS)
    module = load_migration()

    with eng.begin() as conn:
        for s in module.STARTERS:
            module._upsert(conn, s)
    assert all(latest == 1 for latest, _ in _builtins(eng).values()), "a re-run changes nothing"

    revised = json.loads(json.dumps(module.STARTERS[0]))
    revised["parameters"]["num_videos"] = 25
    revised["name"] = "Topic scan (revised)"
    with eng.begin() as conn:
        module._upsert(conn, revised)
    latest, name = _builtins(eng)["topic-scan"]
    assert (latest, name) == (2, "Topic scan (revised)")
    with eng.connect() as conn:
        versions = conn.execute(
            text(
                "SELECT v.version, v.parameters_json FROM job_template_versions v "
                "JOIN job_templates t ON t.id = v.template_id WHERE t.builtin_key = 'topic-scan' "
                "ORDER BY v.version"
            )
        ).fetchall()
    assert [(v, json.loads(p)["num_videos"]) for v, p in versions] == [(1, 20), (2, 25)]
