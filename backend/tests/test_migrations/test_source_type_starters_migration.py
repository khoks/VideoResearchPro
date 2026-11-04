"""S-8.6.3 / S-8.6.4 — `jobs.published_after_days` and the two source-type starters.

Against the real migration chain on a scratch SQLite file. The trap in a copied
starter migration is its downgrade, which walks `STARTERS`: a copy of the full
list would delete the five built-ins `f1a2b3c4d5e6` owns. So the tests here
compare those five row for row, on the way up and on the way down.
"""
from __future__ import annotations

import importlib.util
import json
import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from app.schemas.job_template import TemplateParameters
from app.services import job_source_types, job_template_service

BELOW = "5f8caf39b5b1"
COLUMN = "b84e405ab989"
STARTERS = "927718ee5b78"
ORIGINAL_FIVE = {"topic-scan", "deep-dive", "quick-brief", "channel-deep-dive", "subscription-follow"}
NEW_TWO = {"podcast-digest", "mixed-source-debate"}

_BACKEND = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
_PATH = os.path.join(_BACKEND, "alembic", "versions", "927718ee5b78_source_type_starters.py")


def load_migration():
    spec = importlib.util.spec_from_file_location("source_type_starters_migration", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'source_starters.db'}"
    cfg = Config(os.path.join(_BACKEND, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_BACKEND, "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    eng = create_engine(url)
    try:
        yield cfg, eng
    finally:
        eng.dispose()


@pytest.fixture
def no_credentials(monkeypatch):
    """A stock install: no search credential set up, the OpenAI key the defaults
    require (CLAUDE.md), and ffmpeg."""
    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "BRAVE_SEARCH_API_KEY", "TWITTER_BEARER_TOKEN"):
        monkeypatch.setattr(settings, name, "")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "WHISPER_MAX_PER_JOB", 50)
    monkeypatch.setattr(job_source_types.shutil, "which", lambda tool, **_: f"/usr/bin/{tool}")


def _snapshot(eng) -> dict[str, tuple]:
    """Every built-in with its whole version history, for exact comparison."""
    with eng.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT t.builtin_key, t.id, t.name, t.description, t.latest_version, t.updated_at, "
                "v.version, v.parameters_json "
                "FROM job_templates t JOIN job_template_versions v ON v.template_id = t.id "
                "WHERE t.tenant_id IS NULL ORDER BY t.builtin_key, v.version"
            )
        ).fetchall()
    out: dict[str, list] = {}
    for key, *rest in rows:
        out.setdefault(key, []).append(tuple(rest))
    return {key: tuple(value) for key, value in out.items()}


def _orphan_versions(eng) -> int:
    with eng.connect() as conn:
        return conn.execute(
            text(
                "SELECT COUNT(*) FROM job_template_versions v "
                "WHERE NOT EXISTS (SELECT 1 FROM job_templates t WHERE t.id = v.template_id)"
            )
        ).scalar()


def _columns(eng) -> set[str]:
    return {c["name"] for c in inspect(eng).get_columns("jobs")}


# --- the definitions ----------------------------------------------------------

def test_exactly_the_two_new_starters():
    assert {s["builtin_key"] for s in load_migration().STARTERS} == NEW_TWO


def test_each_starter_survives_a_readers_save_unchanged(no_credentials):
    """`validate_parameters` is what a save goes through, on a stock install.
    Stored unchanged means canonical: a reader's "save changes" adds no noise."""
    for s in load_migration().STARTERS:
        params = TemplateParameters(**s["parameters"])
        assert job_template_service.validate_parameters(params) == params
        assert params.job_type == s["job_type"] == "topic"
        assert params.visual_analysis is False, "a starter must not become R1's opt-in"


def test_each_starter_carries_every_field_of_a_template():
    """So a later migration can compare stored parameters with no key missing."""
    for s in load_migration().STARTERS:
        assert set(s["parameters"]) == set(TemplateParameters.model_fields)


def test_every_source_needs_no_search_credential(no_credentials):
    """A migration cannot vary by install, so a gated source would be a problem
    on every stock install. What reading a podcast needs is
    `transcription_gap`, tested with the starters below."""
    for s in load_migration().STARTERS:
        for source_type in s["parameters"]["source_types"]:
            assert job_source_types.missing_setting(source_type) is None


def test_a_starter_that_reads_podcasts_says_transcription_comes_after_approval():
    """Whisper is a cost to the install, and the digest's reader was told while
    the debate's, with up to 6 episodes, was not. Revising this copy later takes
    another data migration."""
    for s in load_migration().STARTERS:
        assert "podcast_episode" in s["parameters"]["source_types"]
        assert "transcribed after you approve them" in s["description"], s["builtin_key"]


def test_sources_the_live_check_found_empty_are_left_out():
    """Checked on 2026-11-04, and see the migration's docstring: both would
    take a fixed share of the budget and return nothing. Lift this only with a
    new live check."""
    named = {st for s in load_migration().STARTERS for st in s["parameters"]["source_types"]}
    assert not named & {"bluesky_post", "mastodon_post"}


def test_no_starter_sets_a_publish_window():
    """Only YouTube results are ranked (S-8.6.3)."""
    assert all(s["parameters"]["published_after_days"] is None for s in load_migration().STARTERS)


def test_instructions_are_only_written_where_something_reads_them():
    by_key = {s["builtin_key"]: s["parameters"] for s in load_migration().STARTERS}
    # A podcast-only run never reaches the search agent; connectors ignore them.
    assert by_key["podcast-digest"]["search_instructions"] is None
    assert "{{topic}}" in by_key["mixed-source-debate"]["search_instructions"]


def test_the_budget_gives_every_source_a_share():
    for s in load_migration().STARTERS:
        shares = job_source_types.share_limits(s["parameters"]["num_videos"], s["parameters"]["source_types"])
        assert all(n >= 1 for n in shares.values())


# --- the chain ----------------------------------------------------------------

def test_column_upgrade_and_downgrade(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, BELOW)
    assert "published_after_days" not in _columns(eng)
    command.upgrade(cfg, COLUMN)
    assert "published_after_days" in _columns(eng)
    command.downgrade(cfg, BELOW)
    assert "published_after_days" not in _columns(eng)


def test_column_downgrade_keeps_the_jobs(migrated):
    """Not a table rebuild: a dropped column must not cost a row, and SQLite
    would cascade a DROP TABLE into the join tables if it ever became one."""
    cfg, eng = migrated
    command.upgrade(cfg, COLUMN)
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (id, tenant_id, job_type, status, created_at, updated_at, num_videos, "
                "progress_pct, published_after_days) "
                "VALUES ('j1', 't1', 'topic', 'completed', '2026-01-01', '2026-01-01', 10, 100, 30)"
            )
        )
    command.downgrade(cfg, BELOW)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM jobs")).scalar() == 1


def _store_template(eng, parameters_json: str) -> None:
    """A reader's template as the app stores it."""
    with eng.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO job_templates (id, tenant_id, name, job_type, latest_version, created_at, updated_at) "
                "VALUES ('tpl-1', 't1', 'Weekly scan', 'topic', 1, '2026-01-01', '2026-01-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO job_template_versions (template_id, version, parameters_json, created_at) "
                "VALUES ('tpl-1', 1, :p, '2026-01-01')"
            ),
            {"p": parameters_json},
        )


def _stored_version(eng) -> tuple:
    with eng.connect() as conn:
        return tuple(
            conn.execute(
                text("SELECT parameters_json, created_at FROM job_template_versions WHERE template_id = 'tpl-1'")
            ).one()
        )


@pytest.mark.parametrize("window", [30, None])
def test_downgrade_leaves_stored_templates_readable_by_the_previous_code(migrated, window):
    """The app writes every field on save, so a null window is stored too. The
    previous `TemplateParameters` forbids extras and `_parse` builds it straight
    from the stored JSON, so a left-over key would be a 500 on GET /job-templates."""
    cfg, eng = migrated
    command.upgrade(cfg, COLUMN)
    params = TemplateParameters(job_type="topic", num_videos=12, published_after_days=window).model_dump()
    _store_template(eng, json.dumps(params, sort_keys=True))

    command.downgrade(cfg, BELOW)

    stored, created_at = _stored_version(eng)
    expected = {k: v for k, v in params.items() if k != "published_after_days"}
    previous_fields = set(TemplateParameters.model_fields) - {"published_after_days"}
    assert json.loads(stored) == expected, "every other parameter survives"
    assert set(json.loads(stored)) <= previous_fields
    assert created_at == "2026-01-01"


def test_downgrade_skips_a_version_it_cannot_read(migrated):
    """Parsing is what a template read does; a bad row must not stop a rollback."""
    cfg, eng = migrated
    command.upgrade(cfg, COLUMN)
    _store_template(eng, "not json")

    command.downgrade(cfg, BELOW)

    assert _stored_version(eng)[0] == "not json"
    assert "published_after_days" not in _columns(eng)


def test_upgrade_adds_the_two_and_leaves_the_five_alone(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, COLUMN)
    before = _snapshot(eng)
    assert set(before) == ORIGINAL_FIVE

    command.upgrade(cfg, STARTERS)
    after = _snapshot(eng)
    assert set(after) == ORIGINAL_FIVE | NEW_TWO
    assert {k: after[k] for k in ORIGINAL_FIVE} == before
    assert all(len(after[k]) == 1 and after[k][0][3] == 1 for k in NEW_TWO), "each starts at version 1"


def test_downgrade_removes_only_the_two(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, STARTERS)
    before = _snapshot(eng)

    command.downgrade(cfg, COLUMN)
    after = _snapshot(eng)
    assert set(after) == ORIGINAL_FIVE
    assert after == {k: before[k] for k in ORIGINAL_FIVE}
    assert _orphan_versions(eng) == 0, "their versions went with them"

    command.upgrade(cfg, STARTERS)
    assert set(_snapshot(eng)) == ORIGINAL_FIVE | NEW_TWO


def test_a_run_keeps_its_provenance_when_its_starter_is_removed(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, STARTERS)
    with eng.begin() as conn:
        template_id = conn.execute(
            text("SELECT id FROM job_templates WHERE builtin_key = 'podcast-digest'")
        ).scalar()
        conn.execute(
            text(
                "INSERT INTO jobs (id, tenant_id, job_type, status, created_at, updated_at, num_videos, "
                "progress_pct, template_id, template_version) "
                "VALUES ('j1', 't1', 'topic', 'completed', '2026-01-01', '2026-01-01', 8, 100, :t, 1)"
            ),
            {"t": template_id},
        )
    command.downgrade(cfg, COLUMN)
    with eng.connect() as conn:
        assert conn.execute(text("SELECT template_id FROM jobs WHERE id = 'j1'")).scalar() == template_id


def test_upsert_is_idempotent_and_versions_a_revision(migrated):
    cfg, eng = migrated
    command.upgrade(cfg, STARTERS)
    module = load_migration()
    before = _snapshot(eng)

    with eng.begin() as conn:
        for s in module.STARTERS:
            module._upsert(conn, s)
    assert _snapshot(eng) == before, "a re-run changes nothing"

    revised = json.loads(json.dumps(module.STARTERS[0]))
    revised["parameters"]["num_videos"] = 12
    with eng.begin() as conn:
        module._upsert(conn, revised)
    versions = [json.loads(row[-1])["num_videos"] for row in _snapshot(eng)["podcast-digest"]]
    assert versions == [8, 12]


# --- what a reader gets -------------------------------------------------------

@pytest.fixture
def starters(db):
    """Seeded the way the migration seeds them, on the test database."""
    module = load_migration()
    conn = db.connection()
    for s in module.STARTERS:
        module._upsert(conn, s)
    db.commit()
    return module.STARTERS


@pytest.fixture
def other_reader(db):
    from app.services import auth_service

    return auth_service.create_user(db, email="reader2@example.com", password="otherpass123")


def test_starters_are_listed_for_every_reader_ready_to_use(client, starters, other_reader, no_credentials):
    from app.services import auth_service

    listed = {t["builtin_key"]: t for t in client.get("/api/v1/job-templates").json()}
    assert NEW_TWO <= set(listed)
    for key in NEW_TWO:
        assert listed[key]["builtin"] is True
        assert listed[key]["problems"] == [], "usable as it comes on a stock install"
    assert listed["podcast-digest"]["parameters"]["source_types"] == ["podcast_episode"]
    assert listed["mixed-source-debate"]["parameters"]["source_types"] == ["video", "hn_story", "podcast_episode"]

    token, _ = auth_service.create_access_token(other_reader.id)
    second = client.get("/api/v1/job-templates", headers={"Authorization": f"Bearer {token}"})
    assert NEW_TWO <= {t["builtin_key"] for t in second.json()}


def _problems(client) -> dict[str, list[str]]:
    return {t["builtin_key"]: t["problems"] for t in client.get("/api/v1/job-templates").json()}


@pytest.mark.parametrize(
    "setting, value",
    [("OPENAI_API_KEY", ""), ("OPENAI_API_KEY", None), ("WHISPER_MAX_PER_JOB", 0), ("WHISPER_MAX_PER_JOB", -1)],
)
def test_a_starter_says_when_this_install_has_no_whisper(client, starters, no_credentials, monkeypatch, setting, value):
    """Search needs no credential, so nothing else speaks up: the run is accepted,
    and the episodes are lost after approval. CLAUDE.md allows an install with no
    OpenAI key, and the budget at 0 is how an operator stops the spend."""
    monkeypatch.setattr(settings, setting, value)
    problems = _problems(client)
    for key in NEW_TWO:
        assert len(problems[key]) == 1 and "need Whisper" in problems[key][0], key


def test_a_starter_says_when_long_episodes_cannot_be_split(client, starters, no_credentials, monkeypatch):
    monkeypatch.setattr(job_source_types.shutil, "which", lambda tool, **_: None if tool == "ffprobe" else tool)
    problems = _problems(client)
    for key in NEW_TWO:
        assert len(problems[key]) == 1 and "need ffmpeg" in problems[key][0], key


def test_the_gap_is_reported_for_a_readers_own_template_and_only_for_podcasts(client, no_credentials, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")

    def problems_of(source_types):
        params = {"job_type": "topic", "num_videos": 10, "source_types": source_types}
        r = client.post("/api/v1/job-templates", json={"name": str(source_types), "parameters": params})
        assert r.status_code == 201, r.text
        return r.json()["problems"]

    assert len(problems_of(["hn_story", "podcast_episode"])) == 1
    assert problems_of(["video", "hn_story"]) == []
    assert problems_of(None) == []


def test_starters_are_read_only(client, starters):
    listed = {t["builtin_key"]: t for t in client.get("/api/v1/job-templates").json()}
    for key in NEW_TWO:
        template_id = listed[key]["id"]
        assert client.put(f"/api/v1/job-templates/{template_id}", json={"name": "Mine"}).status_code == 403
        assert client.delete(f"/api/v1/job-templates/{template_id}").status_code == 403


def test_a_run_from_each_starter_searches_what_it_says(client, db, starters, no_credentials):
    """Use a starter the way the submit form does: its parameters plus a topic."""
    from app.models.job import Job
    from app.services import job_source_types as jst

    listed = {t["builtin_key"]: t for t in client.get("/api/v1/job-templates").json()}
    for key in NEW_TWO:
        t = listed[key]
        body = {k: v for k, v in t["parameters"].items() if v is not None}
        r = client.post(f"/api/v1/jobs?template_id={t['id']}", json={**body, "topic": "nuclear power"})
        assert r.status_code == 201, r.text
        job = db.get(Job, r.json()["id"])
        assert jst.from_column(job.source_types_json) == t["parameters"]["source_types"]
        assert job.template_id == t["id"]

    debate = client.get("/api/v1/jobs").json()
    filled = [j for j in debate if "nuclear power" in (j.get("search_instructions") or "")]
    assert len(filled) == 1, "{{topic}} filled for the debate; the digest has no instructions"
