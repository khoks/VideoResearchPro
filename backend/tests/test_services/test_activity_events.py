"""S-3.2.1 — `activity_events` storage, the share event, and the registries.

Storage is idempotent on (tenant, connector, external_id) and per tenant; a
processed share is one `shared_to_pratidhvani` event that goes with the
share; connectors and importers register through one contract.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.config import settings
from app.connectors import registry
from app.connectors.base import (
    ActivityConnector,
    ActivityEvent as EventIn,
    ArchiveImporter,
    ConnectorTokens,
    DerivedFact,
    ImportedShare,
    SyncContext,
)
from app.models.activity_event import ActivityEvent
from app.services import activity_event_service, auth_service, echo_intake_service, echo_processing_service

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)


def _events(n, *, prefix="ev", text=None):
    return [
        EventIn(external_id=f"{prefix}-{i}", event_type="pushed_commit", occurred_at=T0 + timedelta(hours=i),
                payload={"i": i}, text_content=text)
        for i in range(n)
    ]


@pytest.fixture
def two(db):
    a = auth_service.create_user(db, email="act-a@example.com", password="pw" * 6)
    b = auth_service.create_user(db, email="act-b@example.com", password="pw" * 6)
    return a, b


# ------------------------------------------------------------------ storage

def test_storing_the_same_events_twice_is_one_row_each(db, two):
    a, _ = two
    first = activity_event_service.store_events(db, a.id, "github", _events(3))
    assert first == {"added": 3, "updated": 0, "unchanged": 0}
    again = activity_event_service.store_events(db, a.id, "github", _events(3))
    assert again == {"added": 0, "updated": 0, "unchanged": 3}
    assert activity_event_service.count_events(db, a.id, "github") == 3

    changed = activity_event_service.store_events(db, a.id, "github", _events(1, text="edited message"))
    assert changed == {"added": 0, "updated": 1, "unchanged": 0}
    row = db.query(ActivityEvent).filter_by(tenant_id=a.id, external_id="ev-0").one()
    assert row.text_content == "edited message" and row.user_id == a.id
    assert row.occurred_at == T0.replace(tzinfo=None), "stored as naive UTC"


def test_duplicate_ids_in_one_sync_are_one_row(db, two):
    a, _ = two
    evs = [EventIn("dup", "starred", T0, {"v": 1}), EventIn("dup", "starred", T0, {"v": 2})]
    assert activity_event_service.store_events(db, a.id, "github", evs)["added"] == 1
    assert json.loads(db.query(ActivityEvent).filter_by(external_id="dup").one().payload_json) == {"v": 2}


def test_an_event_without_an_external_id_is_refused(db, two):
    with pytest.raises(ValueError):
        activity_event_service.store_events(db, two[0].id, "github", [EventIn("", "x", T0)])


def test_two_readers_with_the_same_external_ids_never_collide(db, two):
    a, b = two
    activity_event_service.store_events(db, a.id, "github", _events(2))
    assert activity_event_service.store_events(db, b.id, "github", _events(2))["added"] == 2
    assert activity_event_service.delete_connector_events(db, a.id, "github") == 2
    db.commit()
    assert activity_event_service.count_events(db, a.id) == 0
    assert activity_event_service.count_events(db, b.id, "github") == 2


def test_the_timeline_is_newest_first_and_per_reader(db, two):
    a, b = two
    activity_event_service.store_events(db, a.id, "github", _events(3))
    activity_event_service.store_events(db, b.id, "github", _events(1, prefix="theirs"))
    rows = activity_event_service.list_events(db, a.id)
    assert [r.external_id for r in rows] == ["ev-2", "ev-1", "ev-0"]
    older = activity_event_service.list_events(db, a.id, before=T0 + timedelta(hours=1), limit=5)
    assert [r.external_id for r in older] == ["ev-0"]


# ------------------------------------------------------------------ the share event

@pytest.fixture
def chroma(monkeypatch):
    import chromadb
    from chromadb.api.shared_system_client import SharedSystemClient

    from app.services import chroma_service

    SharedSystemClient._identifier_to_system = {}
    client = chromadb.EphemeralClient()
    monkeypatch.setattr(chroma_service, "_client", client)
    yield client
    monkeypatch.setattr(chroma_service, "_client", None)
    SharedSystemClient._identifier_to_system = {}


def test_a_processed_share_is_one_event_that_leaves_with_the_share(db, two, chroma, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, _ = two
    share = echo_intake_service.create_text_share(db, a.id, a.id, text="Someone else's words, context only.")
    assert echo_processing_service.process_share(db, share.id).state == "processed"
    echo_processing_service.process_share(db, share.id)  # re-processing: still one event

    rows = db.query(ActivityEvent).filter_by(tenant_id=a.id, connector="internal").all()
    assert len(rows) == 1
    ev = rows[0]
    assert ev.event_type == "shared_to_pratidhvani" and ev.external_id == f"share:{share.id}"
    assert ev.text_content is None, "the shared words stay in the inbox (D-089)"
    assert json.loads(ev.payload_json)["author_is_tenant"] is False
    assert "context only" not in ev.payload_json

    echo_intake_service.delete_share(db, a.id, share.id)
    assert db.query(ActivityEvent).filter_by(tenant_id=a.id).count() == 0


def test_a_failed_share_records_no_event(db, two, chroma, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, _ = two
    share = echo_intake_service.create_url_share(db, a.id, a.id, url="https://example.org/x")
    with patch("app.services.article_extraction.extractor.extract_text", side_effect=ValueError("boom")):
        assert echo_processing_service.process_share(db, share.id).state == "failed"
    assert db.query(ActivityEvent).filter_by(tenant_id=a.id).count() == 0


def test_the_share_event_never_breaks_processing(db, two, chroma, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, _ = two
    share = echo_intake_service.create_text_share(db, a.id, a.id, text="still processed")
    with patch.object(activity_event_service, "record_share_event", side_effect=RuntimeError("db hiccup")):
        assert echo_processing_service.process_share(db, share.id).state == "processed"


# ------------------------------------------------------------------ registries

class FakeConnector:
    name = "fake_activity"
    display_name = "Fake"
    privacy_weight = "low"
    consent_disclosure = "Reads fake things."
    consent_version = "1"
    schedule = {"cadence": "daily", "hour": 3}

    def event_types(self):
        return ["did_a_thing"]

    def is_configured(self):
        return True

    def authorize_url(self, *, redirect_uri, state, code_challenge):
        return f"https://fake/authorize?state={state}"

    def handle_callback(self, *, code, redirect_uri, code_verifier):
        return ConnectorTokens(access_token="t")

    def revoke(self, tokens):
        return None

    def initial_backfill(self, ctx: SyncContext):
        yield from _events(2)

    def incremental_sync(self, ctx, since):
        yield from _events(1)


class FakeImporter:
    name = "fake_export"
    display_name = "Fake export"
    privacy_weight = "medium"
    consent_disclosure = "Reads a file you exported."

    def accepts(self, filename):
        return filename.endswith(".fake.zip")

    def parse(self, stream, *, tenant_id):
        yield ImportedShare(external_id="m1", occurred_at=T0, text=stream.read().decode())
        yield DerivedFact(kind="interest", key="x", value="y", confidence=0.4)


def test_connectors_and_importers_register_against_one_contract():
    conn, imp = FakeConnector(), FakeImporter()
    assert isinstance(conn, ActivityConnector) and isinstance(imp, ArchiveImporter)
    registry.register_connector(conn)
    registry.register_importer(imp)
    try:
        assert "fake_activity" in registry.list_connectors()
        assert registry.get_connector("fake_activity") is conn
        assert registry.importer_for("mine.fake.zip") is imp
        assert registry.importer_for("mine.txt") is None
        items = list(imp.parse(io.BytesIO(b"hello"), tenant_id="t"))
        assert isinstance(items[0], ImportedShare) and items[0].text == "hello"
        # The old echo_service names point at the same registry.
        from app.services import echo_service
        assert echo_service.get_connector("fake_activity") is conn
    finally:
        registry.unregister_connector("fake_activity")
        registry.unregister_importer("fake_export")


def test_load_builtin_imports_every_connector_package():
    registry.load_builtin()  # no packages yet must not fail; S-3.2.4 adds github
