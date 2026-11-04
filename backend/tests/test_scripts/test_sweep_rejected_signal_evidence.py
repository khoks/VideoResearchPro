"""scripts/sweep_rejected_signal_evidence.py (T-3.3.1.7), run through its ``main``.

A rejection made before PR #392 kept citing what the user deleted while it was
rejected. The dry run counts and writes nothing, and cannot; ``--write`` clears
the stale evidence and only that; a rejection stays a rejection; a second run
finds nothing; and a later restore comes to the same signal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.models.note import Note
from app.models.voice_signal import VoiceSignal
from app.services import auth_service, echo_signal_service

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import sweep_rejected_signal_evidence as sweep  # noqa: E402

LIVE = "start from the base rates"
GONE = "words from a share I deleted"
EDITED = "chess is my whole life"


@pytest.fixture
def rejections(db, monkeypatch):
    from tests import conftest as _conftest

    monkeypatch.setattr(sweep, "SessionLocal", _conftest.TestingSessionLocal)
    a = auth_service.create_user(db, email="sweep-a@example.com", password="pw" * 6)
    b = auth_service.create_user(db, email="sweep-b@example.com", password="pw" * 6)
    db.add(Note(id="n-live", tenant_id=a.id, target_type="job", target_id="job-1", body_md=f"I always {LIVE}."))
    db.add(Note(id="n-edited", tenant_id=a.id, target_type="job", target_id="job-1", body_md="These days I play go."))
    db.commit()

    def signal(tenant, value, examples, reject=True, weight=3.0):
        row = echo_signal_service.create(
            db, tenant_id=tenant, user_id=tenant, signal_type="methodology", value=value,
            origin="llm", weight=weight, examples=examples,
        )
        if reject:
            echo_signal_service.suppress(db, tenant, row.id)
        return row.id

    mixed = signal(a.id, "Argues from base rates", [
        {"text": LIVE, "source": "note:n-live"},
        {"text": GONE, "source": "share:gone"},
        {"text": EDITED, "source": "note:n-edited"},
    ])
    orphan = signal(a.id, "Ends on a confession", [{"text": GONE, "source": "share:gone"}], weight=1.0)
    clean = signal(a.id, "Opens with a number", [{"text": LIVE, "source": "note:n-live"}])
    typed = signal(a.id, "Likes semicolons", [{"text": "typed by me", "source": "user"}])
    live = signal(a.id, "Quotes proverbs", [{"text": LIVE, "source": "note:n-live"}, {"text": GONE, "source": "share:gone"}], reject=False)
    other = signal(b.id, "Writes in threes", [{"text": GONE, "source": "share:gone"}])
    return dict(a=a, b=b, mixed=mixed, orphan=orphan, clean=clean, typed=typed, live=live, other=other)


def _row(db, signal_id):
    db.expire_all()
    return db.get(VoiceSignal, signal_id)


def _state(db):
    db.expire_all()
    return sorted(
        (r.id, r.derived_from, r.examples_json, r.weight, r.suppressed_reason)
        for r in db.query(VoiceSignal)
    )


def test_the_dry_run_counts_and_writes_nothing(db, rejections, capsys):
    before = _state(db)

    assert sweep.main([]) == 0

    out = capsys.readouterr().out
    assert "dry run" in out
    assert "2 tenants with rejections, 5 rejections, 3 stale: would clear 4 examples and 4 refs" in out
    assert _state(db) == before
    assert GONE not in out and LIVE not in out, "counts, never the words"


def test_without_write_the_sweep_changes_no_row(db, rejections):
    """Not only uncommitted: a caller's later commit must have nothing to save."""
    found = echo_signal_service.sweep_rejected_evidence(db, rejections["a"].id, write=False)
    assert found.stale == 2
    assert not db.dirty


def test_the_dry_run_cannot_write_and_leaves_the_connection_as_it_found_it(db, rejections, monkeypatch):
    """``PRAGMA query_only``: a bug in the dry run fails rather than writes."""

    def tries_to_write(session, tenant_id, *, write):
        session.execute(text("UPDATE voice_signals SET weight = 0"))
        return echo_signal_service.RejectedSweep()

    monkeypatch.setattr(sweep.echo_signal_service, "sweep_rejected_evidence", tries_to_write)
    with pytest.raises(OperationalError, match="readonly"):
        sweep.main([])
    db.execute(text("UPDATE voice_signals SET weight = weight"))


def test_write_clears_what_is_stale_and_only_that(db, rejections, capsys):
    clean_before = _row(db, rejections["clean"]).examples_json
    typed_before = _row(db, rejections["typed"]).examples_json
    live_before = _row(db, rejections["live"]).examples_json

    assert sweep.main(["--write"]) == 0
    assert "cleared 4 examples and 4 refs" in capsys.readouterr().out

    mixed = _row(db, rejections["mixed"])
    assert GONE not in mixed.examples_json and EDITED not in mixed.examples_json
    assert LIVE in mixed.examples_json
    assert mixed.derived_from == '["note:n-live"]'
    assert mixed.weight == 1.0, "one less per ref that left, as a withdrawal counts it"

    orphan = _row(db, rejections["orphan"])
    assert orphan.examples_json == "[]" and orphan.derived_from == "[]"
    for sid in ("mixed", "orphan", "other"):
        row = _row(db, rejections[sid])
        assert row.suppressed_reason == "user" and row.suppressed_at is not None, "a rejection stays one"
    assert GONE not in _row(db, rejections["other"]).examples_json, "every tenant"

    assert _row(db, rejections["clean"]).examples_json == clean_before
    assert _row(db, rejections["typed"]).examples_json == typed_before
    live = _row(db, rejections["live"])
    assert live.examples_json == live_before and live.suppressed_at is None, "live signals are not this sweep's"


def test_a_second_run_changes_nothing(db, rejections, capsys):
    sweep.main(["--write"])
    after = _state(db)
    capsys.readouterr()

    assert sweep.main(["--write"]) == 0
    assert "0 stale: cleared 0 examples and 0 refs" in capsys.readouterr().out
    assert _state(db) == after


def test_tenant_narrows_the_sweep(db, rejections, capsys):
    assert sweep.main(["--write", "--tenant", rejections["b"].id]) == 0
    assert GONE not in _row(db, rejections["other"]).examples_json
    assert GONE in _row(db, rejections["mixed"]).examples_json


def test_a_swept_rejection_restores_to_the_same_signal(db, rejections):
    """The sweep moves restore's clean-up earlier; it does not change the result."""
    untouched = echo_signal_service.restore(db, rejections["a"].id, rejections["mixed"]).signal
    expected = (untouched.derived_from, untouched.examples_json, untouched.weight)
    echo_signal_service.suppress(db, rejections["a"].id, rejections["mixed"])

    other = echo_signal_service.create(
        db, tenant_id=rejections["a"].id, user_id=rejections["a"].id, signal_type="methodology", value="Argues from priors",
        origin="llm", weight=3.0, examples=[
            {"text": LIVE, "source": "note:n-live"},
            {"text": GONE, "source": "share:gone"},
            {"text": EDITED, "source": "note:n-edited"},
        ],
    )
    echo_signal_service.suppress(db, rejections["a"].id, other.id)
    sweep.main(["--write"])
    db.expire_all()  # the script used its own session
    assert _row(db, other.id).derived_from == '["note:n-live"]', "swept before the restore"
    restored = echo_signal_service.restore(db, rejections["a"].id, other.id).signal
    assert (restored.derived_from, restored.examples_json, restored.weight) == expected
