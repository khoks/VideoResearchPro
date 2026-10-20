"""Echo export importers, part 2 (S-3.7.5): Google Takeout (Keep notes and
YouTube history), Spotify, Goodreads, Letterboxd, Strava and Apple Health.

Events go through S-3.2.1's writer under the importer's name; facts go to
``personal_context`` with ``source = import:<id>``. Fixtures are in
``tests/fixtures/echo_imports/`` (see its README); the folder-shaped ones are
zipped here the way each service ships them. Nothing calls out.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.connectors import registry
from app.connectors.apple_health import importer as health
from app.connectors.archive import ImportSource
from app.connectors.base import ArchiveImporter
from app.models.activity_event import ActivityEvent
from app.models.echo_import import EchoImport
from app.models.personal_context import PersonalContext
from app.models.share import Share
from app.services import auth_service, echo_import_service

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "echo_imports"
IMPORT = "/api/v1/echo/import"
PREVIEW = "/api/v1/echo/import/preview"
IMPORTS = "/api/v1/echo/imports"


def _studio(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "studio"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


@pytest.fixture
def two(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ECHO_SHARES_DIR", str(tmp_path / "shares"))
    a, ha = _studio(db, "events-a@example.com")
    b, hb = _studio(db, "events-b@example.com")
    return {"a": a, "ha": ha, "b": b, "hb": hb}


def _zip(members: dict[str, Path | bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(name, data if isinstance(data, bytes) else Path(data).read_bytes())
    return buf.getvalue()


def takeout() -> tuple[str, bytes]:
    yt = "Takeout/YouTube and YouTube Music/history"
    members: dict[str, Path | bytes] = {
        f"{yt}/watch-history.json": FIX / "takeout_youtube/watch-history.json",
        f"{yt}/search-history.json": FIX / "takeout_youtube/search-history.json",
    }
    members.update({f"Takeout/Keep/{p.name}": p for p in (FIX / "keep").glob("*.json")})
    return "takeout-20240211T101010Z-001.zip", _zip(members)


def spotify() -> tuple[str, bytes]:
    return "my_spotify_data.zip", _zip({
        "Spotify Extended Streaming History/Streaming_History_Audio_2024.json": FIX / "spotify/Streaming_History_Audio_2024.json",
    })


def letterboxd() -> tuple[str, bytes]:
    return "letterboxd-me-2024-02-11-utc.zip", _zip({p.name: p for p in (FIX / "letterboxd").glob("*.csv")})


def strava() -> tuple[str, bytes]:
    return "export_123456.zip", _zip({
        "activities.csv": FIX / "strava/activities.csv",
        "activities/9001.gpx": FIX / "strava/9001.gpx",
    })


def apple_health(xml: bytes | None = None) -> tuple[str, bytes]:
    return "export.zip", _zip({"apple_health_export/export.xml": xml or (FIX / "apple_health/export.xml").read_bytes()})


def _run(client, headers, name, data, options=None):
    fields = {"options": json.dumps(options)} if options else {}
    r = client.post(IMPORT, headers=headers, files={"file": (name, data, "application/octet-stream")}, data=fields)
    assert r.status_code == 201, r.text
    return r.json()


def _events(db, tenant_id, connector):
    return (
        db.query(ActivityEvent)
        .filter(ActivityEvent.tenant_id == tenant_id, ActivityEvent.connector == connector)
        .order_by(ActivityEvent.occurred_at)
        .all()
    )


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_every_importer_meets_the_contract_and_claims_only_its_own_files():
    registry.load_builtin()
    names = {"whatsapp", "google_keep", "google_takeout", "spotify_export", "goodreads_export",
             "letterboxd_export", "strava_export", "apple_health_export"}
    assert names <= set(registry.list_importers())
    for name in names:
        imp = registry.get_importer(name)
        assert isinstance(imp, ArchiveImporter), name
        assert imp.consent_disclosure.strip() and imp.privacy_weight in ("low", "medium", "high", "very_high")
    expected = {
        "takeout-20240211T101010Z-001.zip": "google_takeout", "my_spotify_data.zip": "spotify_export",
        "StreamingHistory_music_0.json": "spotify_export", "goodreads_library_export.csv": "goodreads_export",
        "letterboxd-me-2024-02-11-utc.zip": "letterboxd_export", "export_123456.zip": "strava_export",
        "export.zip": "apple_health_export", "export.xml": "apple_health_export",
    }
    for filename, name in expected.items():
        assert registry.importer_for(filename).name == name, filename
    for other in ("mine.txt", "notes.json", "data.csv", "export_final.zip", "photos.zip"):
        assert registry.importer_for(other) is None, other


@pytest.mark.parametrize("make,importer", [
    (takeout, "google_takeout"), (spotify, "spotify_export"), (letterboxd, "letterboxd_export"),
    (strava, "strava_export"), (apple_health, "apple_health_export"),
])
def test_a_renamed_export_is_recognised_by_its_content(make, importer):
    _, data = make()
    assert echo_import_service.preview(io.BytesIO(data), "download (3).zip").importer == importer


# ---------------------------------------------------------------------------
# Google Takeout
# ---------------------------------------------------------------------------


def test_takeout_reads_keep_notes_and_youtube_history(unauthenticated_client, db, two):
    name, data = takeout()
    pv = unauthenticated_client.post(PREVIEW, headers=two["ha"], files={"file": (name, data)}).json()
    assert pv["importer"] == "google_takeout"
    s = pv["summary"]
    assert (s["notes"], s["watched"], s["searches"], s["ads_skipped"]) == (2, 3, 2, 1)
    assert s["top_channels"] == {"Econ Channel": 2}

    item = _run(unauthenticated_client, two["ha"], name, data)
    assert item["counts"]["shares"] == 2 and item["counts"]["events"] == 5
    assert item["counts"]["removed_videos_skipped"] == 1
    events = _events(db, two["a"].id, "google_takeout")
    watched = [e for e in events if e.event_type == "watched_video"]
    searched = [e for e in events if e.event_type == "searched_youtube"]
    assert [json.loads(e.payload_json)["title"] for e in watched][:2] == ["Why tariffs raise prices", "The China shock, revisited"]
    assert json.loads(watched[0].payload_json)["channel"] == "Econ Channel" and watched[0].text_content is None
    # Recognised by URL, so a search in any account language reads the same.
    assert [e.text_content for e in searched] == ["tariffs explained", "smoot hawley"]
    assert not any("adadadadada" in e.payload_json for e in events), "ads are left out"
    assert db.query(Share).filter(Share.import_id == item["id"]).count() == 2


def test_takeout_parts_can_be_left_out(unauthenticated_client, db, two):
    name, data = takeout()
    item = _run(unauthenticated_client, two["ha"], name, data, {"include_keep": False})
    assert item["counts"]["shares"] == 0 and item["counts"]["events"] == 5
    name, data = takeout()
    item = _run(unauthenticated_client, two["hb"], name, data, {"include_youtube": False})
    assert item["counts"]["shares"] == 2 and item["counts"].get("events", 0) == 0


# ---------------------------------------------------------------------------
# Spotify, Goodreads, Letterboxd, Strava
# ---------------------------------------------------------------------------


def test_spotify_history_skips_private_sessions_and_never_stores_the_ip(unauthenticated_client, db, two):
    name, data = spotify()
    item = _run(unauthenticated_client, two["ha"], name, data)
    assert item["counts"]["events"] == 3 and item["counts"]["private_session_skipped"] == 1
    events = _events(db, two["a"].id, "spotify_export")
    assert [e.event_type for e in events] == ["played_track", "played_track", "played_episode"]
    first = json.loads(events[0].payload_json)
    assert first["title"] == "Kun Faya Kun — A. R. Rahman" and first["ms_played"] == 213000
    assert json.loads(events[1].payload_json)["skipped"] is True
    blob = " ".join(e.payload_json for e in events)
    for never in ("203.0.113.7", "ip_addr", "conn_country", "Private listening"):
        assert never not in blob

    account = _run(unauthenticated_client, two["ha"], "StreamingHistory_music_0.json",
                   (FIX / "StreamingHistory_music_0.json").read_bytes())
    assert account["counts"]["events"] == 2


def test_goodreads_shelves_ratings_and_reviews(unauthenticated_client, db, two):
    item = _run(unauthenticated_client, two["ha"], "goodreads_library_export.csv",
                (FIX / "goodreads_library_export.csv").read_bytes())
    assert item["counts"]["events"] == 3
    by_type = {e.event_type: e for e in _events(db, two["a"].id, "goodreads_export")}
    read = by_type["read_book"]
    assert read.occurred_at.date().isoformat() == "2024-01-20"
    p = json.loads(read.payload_json)
    assert p["title"] == "The Choice by Russ Roberts" and p["rating"] == 5 and p["isbn13"] == "9780132544047"
    assert p["shelves"] == ["economics", "favourites"]
    assert read.text_content == "Clearest case I know that \ntariffs tax your own consumers.\n\nPrivate notes: Use in the essay"
    assert json.loads(by_type["want_to_read"].payload_json)["rating"] is None
    assert "reading_book" in by_type


def test_letterboxd_diary_reviews_watched_and_watchlist(unauthenticated_client, db, two):
    name, data = letterboxd()
    item = _run(unauthenticated_client, two["ha"], name, data)
    events = _events(db, two["a"].id, "letterboxd_export")
    kinds = sorted(e.event_type for e in events)
    assert kinds == ["reviewed_film", "want_to_watch", "watched_film", "watched_film", "watched_film"]
    titles = {json.loads(e.payload_json)["title"]: e for e in events if e.event_type == "watched_film"}
    assert set(titles) == {"Lagaan (2001)", "Oppenheimer (2023)", "Swades (2004)"}, "Lagaan is not counted twice"
    swades = json.loads(titles["Swades (2004)"].payload_json)
    assert swades["undated_viewing"] is True and swades["rating"] == 5.0
    assert json.loads(titles["Lagaan (2001)"].payload_json)["rewatch"] is True
    review = next(e for e in events if e.event_type == "reviewed_film")
    assert review.text_content == "Long, loud, and about the right things."
    assert item["counts"]["events"] == 5


def test_strava_activities_without_ever_reading_a_route(unauthenticated_client, db, two, monkeypatch):
    opened: list[str | None] = []
    real = ImportSource.open_binary

    def spy(self, member=None):
        opened.append(member)
        return real(self, member)

    monkeypatch.setattr(ImportSource, "open_binary", spy)
    name, data = strava()
    item = _run(unauthenticated_client, two["ha"], name, data)
    assert item["counts"]["events"] == 2
    assert not any(m and (m.endswith(".gpx") or ".fit" in m) for m in opened)
    run, ride = _events(db, two["a"].id, "strava_export")
    p = json.loads(run.payload_json)
    assert p["title"] == "Morning Run (Run)" and p["distance"] == 5.02 and p["elapsed_s"] == 1800.0
    assert run.text_content == "Easy 5k before work, knee felt fine" and ride.text_content is None
    assert run.occurred_at.isoformat().startswith("2024-01-31T01:05")


# ---------------------------------------------------------------------------
# Apple Health
# ---------------------------------------------------------------------------


def test_apple_health_becomes_three_routine_facts(unauthenticated_client, db, two):
    name, data = apple_health()
    item = _run(unauthenticated_client, two["ha"], name, data)
    assert item["counts"]["facts"] == 3 and item["counts"]["shares"] == 0 and item["status"] == "done"
    facts = {
        f.key: f for f in db.query(PersonalContext).filter(PersonalContext.tenant_id == two["a"].id)
    }
    assert set(facts) == {"sleep", "steps", "workouts"}
    assert all(f.kind == "daily_routine" and f.source == f"import:{item['id']}" and f.confidence < 1 for f in facts.values())
    sleep = json.loads(facts["sleep"].value)
    assert sleep["median_hours_asleep"] == 7.5 and sleep["nights"] == 3
    assert (sleep["typical_bedtime"], sleep["typical_wake_time"]) == ("23:40", "07:10")
    steps = json.loads(facts["steps"].value)
    # Watch and phone counted the same walking: the larger wins, not the sum.
    assert steps["median_daily_steps"] == 8000 and steps["mean_daily_steps"] == 8166
    workouts = json.loads(facts["workouts"].value)
    assert workouts["per_week"] == 3.0 and workouts["by_type"]["Running"]["median_minutes"] == 31
    assert workouts["by_type"]["Yoga"]["median_minutes"] == 45


def _at(hhmm: str, day: int) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime(2024, 1, day, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def test_sleep_stages_join_into_one_night_and_a_long_gap_splits_it():
    stages = [  # one night as a watch records it: stages with short awake gaps
        (_at("23:00", 10), _at("00:00", 10) + timedelta(days=1)),
        (_at("00:05", 11), _at("02:00", 11)),
        (_at("02:10", 11), _at("06:30", 11)),
    ]
    nights = health.nights(stages)
    assert len(nights) == 1
    minutes, onset, wake = nights[0]
    assert onset == _at("23:00", 10) and wake == _at("06:30", 11) and round(minutes) == 60 + 115 + 260
    split = health.nights([(_at("22:00", 12), _at("02:00", 13)), (_at("05:00", 13), _at("06:00", 13))])
    assert len(split) == 1 and split[0][2] == _at("02:00", 13), "a three-hour gap starts a new session; one hour is no night"


def _health_export(days: int) -> bytes:
    """``days`` nights, step days and blood-pressure correlations (whose
    nested records are not steps or sleep)."""
    rows = []
    for d in range(days):
        day = datetime(2023, 1, 1) + timedelta(days=d)
        bed, wake = day.replace(hour=23), day.replace(hour=23) + timedelta(hours=7)
        rows.append(
            f'<Record type="HKCategoryTypeIdentifierSleepAnalysis" sourceName="Watch" startDate="{bed:%Y-%m-%d %H:%M:%S} +0530" '
            f'endDate="{wake:%Y-%m-%d %H:%M:%S} +0530" value="HKCategoryValueSleepAnalysisAsleepCore"/>'
        )
        rows.append(
            f'<Record type="HKQuantityTypeIdentifierStepCount" sourceName="Watch" startDate="{day:%Y-%m-%d} 09:00:00 +0530" '
            f'endDate="{day:%Y-%m-%d} 10:00:00 +0530" value="5000"><MetadataEntry key="k" value="v"/></Record>'
        )
        rows.append(
            f'<Correlation type="HKCorrelationTypeIdentifierBloodPressure" startDate="{day:%Y-%m-%d} 08:00:00 +0530">'
            '<Record type="HKQuantityTypeIdentifierBloodPressureSystolic" value="120"/></Correlation>'
        )
    return ('<?xml version="1.0"?><HealthData><ExportDate value="x"/>' + "".join(rows) + "</HealthData>").encode()


def test_the_window_counts_exactly_its_days_and_the_parse_keeps_no_records(monkeypatch):
    real = health.ET.iterparse
    roots = []

    def watched(*args, **kwargs):
        for event, elem in real(*args, **kwargs):
            if not roots:
                roots.append(elem)
            yield event, elem

    monkeypatch.setattr(health.ET, "iterparse", watched)
    source = ImportSource(io.BytesIO(_health_export(40)), "export.xml", max_uncompressed=10**9)
    facts = {f.key: f.value for f in health.IMPORTER.parse(source, tenant_id="t", options={"window_days": 30})}
    # The window ends on the last wake-up, the morning after the last step day.
    assert facts["sleep"]["nights"] == 30 and facts["steps"]["days"] == 29
    # Cleared records stay in the root's child list unless the root is
    # cleared too; that grew memory by about 95 bytes a record.
    assert len(roots[0]) == 0


# ---------------------------------------------------------------------------
# Re-imports, undo, tenants
# ---------------------------------------------------------------------------


def test_a_reimport_adds_only_new_events_and_undo_removes_only_its_own(unauthenticated_client, db, two):
    name, data = spotify()
    first = _run(unauthenticated_client, two["ha"], name, data)
    again = _run(unauthenticated_client, two["ha"], name, data)
    assert again["counts"].get("events", 0) == 0 and again["counts"]["events_already_held"] == 3
    account = _run(unauthenticated_client, two["ha"], "StreamingHistory_music_0.json",
                   (FIX / "StreamingHistory_music_0.json").read_bytes())
    assert len(_events(db, two["a"].id, "spotify_export")) == 5

    r = unauthenticated_client.delete(f"{IMPORTS}/{first['id']}", headers=two["ha"]).json()
    assert r["events"] == 3
    assert unauthenticated_client.delete(f"{IMPORTS}/{again['id']}", headers=two["ha"]).json()["events"] == 0
    db.expire_all()
    left = _events(db, two["a"].id, "spotify_export")
    assert len(left) == 2 and all(account["id"] in e.payload_json for e in left)


def test_undo_removes_the_facts_an_import_still_owns(unauthenticated_client, db, two):
    name, data = apple_health()
    older = _run(unauthenticated_client, two["ha"], name, data)
    newer = _run(unauthenticated_client, two["ha"], name, data)
    # The newer import restated the same three facts, so it owns them now.
    assert unauthenticated_client.delete(f"{IMPORTS}/{older['id']}", headers=two["ha"]).json()["facts"] == 0
    assert unauthenticated_client.delete(f"{IMPORTS}/{newer['id']}", headers=two["ha"]).json()["facts"] == 3
    assert db.query(PersonalContext).filter(PersonalContext.tenant_id == two["a"].id).count() == 0


def test_imported_events_belong_to_their_tenant_and_reach_the_timeline(unauthenticated_client, db, two):
    name, data = letterboxd()
    _run(unauthenticated_client, two["ha"], name, data)
    mine = unauthenticated_client.get("/api/v1/echo/activity", headers=two["ha"]).json()["items"]
    assert {i["connector"] for i in mine} == {"letterboxd_export"} and len(mine) == 5
    assert any(i["payload"]["title"] == "Lagaan (2001)" for i in mine)
    assert unauthenticated_client.get("/api/v1/echo/activity", headers=two["hb"]).json()["items"] == []
    assert _events(db, two["b"].id, "letterboxd_export") == []


def test_the_brain_delete_takes_imported_events_and_facts(unauthenticated_client, db, two):
    _run(unauthenticated_client, two["ha"], *strava())
    _run(unauthenticated_client, two["ha"], *apple_health())
    r = unauthenticated_client.delete("/api/v1/echo/brain", params={"confirm": "delete-everything"}, headers=two["ha"])
    assert r.status_code == 200
    db.expire_all()
    assert _events(db, two["a"].id, "strava_export") == []
    assert db.query(PersonalContext).filter(PersonalContext.tenant_id == two["a"].id).count() == 0
    assert db.query(EchoImport).filter(EchoImport.tenant_id == two["a"].id).count() == 0


def test_history_files_stream_rather_than_load_whole():
    class NoSlurp(io.BytesIO):
        def read(self, size=-1):
            if size is None or size < 0:
                raise AssertionError("read() without a size loads the whole export")
            return super().read(size)

        def readall(self):
            raise AssertionError("readall() loads the whole export")

    raw = json.loads((FIX / "spotify/Streaming_History_Audio_2024.json").read_text(encoding="utf-8"))
    big = json.dumps(raw * 500).encode()
    pv = echo_import_service.preview(NoSlurp(big), "Streaming_History_Audio_2019.json")
    assert pv.summary["plays"] == 3 * 500


def test_the_command_line_importer_runs_the_same_flow(db, two, tmp_path, monkeypatch, capsys):
    """scripts/echo_import.py, for exports past the upload cap."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("echo_import_cli", Path(__file__).resolve().parents[2] / "scripts" / "echo_import.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(settings, "ECHO_SHARE_PROCESSING", "off")
    name, data = apple_health()
    path = tmp_path / name
    path.write_bytes(data)

    class Shared:
        """The test session, which the CLI must not close."""
        def __call__(self):
            return self

        def __getattr__(self, attr):
            return getattr(db, attr)

        def close(self):
            pass

    assert cli.main(["--email", "events-a@example.com", "--file", str(path), "--preview"], session_factory=Shared()) == 0
    assert json.loads(capsys.readouterr().out)["importer"] == "apple_health_export"
    assert db.query(EchoImport).count() == 0, "a preview writes nothing"
    assert cli.main(["--email", "events-a@example.com", "--file", str(path)], session_factory=Shared()) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["counts"]["facts"] == 3 and db.query(EchoImport).filter(EchoImport.id == out["import_id"]).count() == 1
    assert cli.main(["--email", "nobody@example.com", "--file", str(path)], session_factory=Shared()) == 2
