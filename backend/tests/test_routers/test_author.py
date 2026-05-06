"""Tests for I-6 Author Studio foundation."""
from __future__ import annotations

import json
import uuid

import pytest

from app.models.job import Job
from app.models.qa_exchange import QAExchange
from app.services import auth_service
from app.services.output_service import (
    OutputError,
    OutputStatus,
    UnsupportedKindError,
    create_output,
    delete_output,
    get_output,
    get_outputter,
    list_outputs,
    list_outputters,
    run_generation,
    transition_to,
)


def _pro_headers(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _free_token(db, email: str = "free@x.com") -> str:
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    token, _ = auth_service.create_access_token(user.id)
    return token


# ---------------------------------------------------------------------------
# Service-layer CRUD
# ---------------------------------------------------------------------------


def test_create_output_unknown_kind_raises(db):
    user = auth_service.create_user(db, email="o1@x.com", password="pw" * 6)
    with pytest.raises(UnsupportedKindError):
        create_output(
            db, user_id=user.id, kind="not-a-kind", title="T", source_ids=[]
        )


def test_create_output_empty_title_raises(db):
    user = auth_service.create_user(db, email="o2@x.com", password="pw" * 6)
    with pytest.raises(OutputError):
        create_output(db, user_id=user.id, kind="book", title="   ", source_ids=[])


def test_create_output_persists(db):
    user = auth_service.create_user(db, email="o3@x.com", password="pw" * 6)
    row = create_output(
        db, user_id=user.id, kind="book", title="My Book",
        source_ids=["job-A", "job-B"], parameters={"include_qa": False},
    )
    assert row.id is not None
    assert row.status == OutputStatus.PENDING.value
    assert json.loads(row.source_ids_json) == ["job-A", "job-B"]
    assert json.loads(row.parameters_json) == {"include_qa": False}


def test_get_output_isolates_per_user(db):
    a = auth_service.create_user(db, email="oa@x.com", password="pw" * 6)
    b = auth_service.create_user(db, email="ob@x.com", password="pw" * 6)
    row_a = create_output(db, user_id=a.id, kind="book", title="A's", source_ids=[])
    # User B can't see user A's output.
    assert get_output(db, b.id, row_a.id) is None
    assert get_output(db, a.id, row_a.id) is not None


def test_list_outputs_filters_by_kind_and_status(db):
    user = auth_service.create_user(db, email="ol@x.com", password="pw" * 6)
    create_output(db, user_id=user.id, kind="book", title="B1", source_ids=[])
    row2 = create_output(db, user_id=user.id, kind="book", title="B2", source_ids=[])
    transition_to(db, row2, OutputStatus.COMPLETED)

    completed = list_outputs(db, user.id, status=OutputStatus.COMPLETED.value)
    pending = list_outputs(db, user.id, status=OutputStatus.PENDING.value)
    assert len(completed) == 1 and completed[0].title == "B2"
    assert len(pending) == 1 and pending[0].title == "B1"


def test_delete_output_returns_true_when_existing(db):
    user = auth_service.create_user(db, email="od@x.com", password="pw" * 6)
    row = create_output(db, user_id=user.id, kind="book", title="D", source_ids=[])
    assert delete_output(db, user.id, row.id) is True
    assert get_output(db, user.id, row.id) is None


def test_delete_output_other_users_returns_false(db):
    a = auth_service.create_user(db, email="oda@x.com", password="pw" * 6)
    b = auth_service.create_user(db, email="odb@x.com", password="pw" * 6)
    row = create_output(db, user_id=a.id, kind="book", title="X", source_ids=[])
    assert delete_output(db, b.id, row.id) is False


# ---------------------------------------------------------------------------
# Outputter registry
# ---------------------------------------------------------------------------


def test_book_outputter_registered_on_import():
    """Importing the outputters package registers the BookMarkdownOutputter."""
    import app.services.outputters  # noqa: F401
    assert "book" in list_outputters()
    outputter = get_outputter("book")
    assert outputter is not None
    assert outputter.kind == "book"


# ---------------------------------------------------------------------------
# BookMarkdownOutputter — content generation
# ---------------------------------------------------------------------------


def _make_job(db, user_id: str, topic: str) -> Job:
    job = Job(
        id=str(uuid.uuid4()),
        job_type="topic",
        status="completed",
        topic=topic,
        tenant_id=user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_run_generation_book_with_zero_sources_fails(db):
    user = auth_service.create_user(db, email="b0@x.com", password="pw" * 6)
    import app.services.outputters  # noqa: F401  ensure registered
    row = create_output(db, user_id=user.id, kind="book", title="Empty", source_ids=[])
    row = run_generation(db, user, row)
    assert row.status == OutputStatus.FAILED.value
    assert "zero source" in (row.error_message or "").lower()


def test_run_generation_book_with_one_job_succeeds(db, monkeypatch):
    """Stub the report fetch + skip Q&A so the test is deterministic
    without the real report HTML on disk."""
    user = auth_service.create_user(db, email="b1@x.com", password="pw" * 6)
    job = _make_job(db, user.id, "Tariffs")
    job.report_path = "/fake/report.html"
    db.commit()

    from app.services import report_service
    monkeypatch.setattr(
        report_service,
        "get_report_html",
        lambda path: "<h1>Tariffs Report</h1><p>Body content here.</p>",
    )

    import app.services.outputters  # noqa: F401  ensure registered
    row = create_output(
        db,
        user_id=user.id,
        kind="book",
        title="My Tariffs Book",
        source_ids=[job.id],
        parameters={"include_qa": False},
    )
    row = run_generation(db, user, row)
    assert row.status == OutputStatus.COMPLETED.value
    md = row.content_text
    assert "# My Tariffs Book" in md
    assert "Tariffs" in md
    assert "Body content here." in md


def test_run_generation_book_includes_qa_section(db, monkeypatch):
    user = auth_service.create_user(db, email="bqa@x.com", password="pw" * 6)
    job = _make_job(db, user.id, "Topic With QA")
    job.report_path = "/fake/report.html"
    db.commit()
    db.add(QAExchange(
        job_id=job.id, question="Q1?", answer="A1.", tenant_id=user.id
    ))
    db.commit()

    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>Body.</p>")

    import app.services.outputters  # noqa: F401
    row = create_output(
        db, user_id=user.id, kind="book", title="QA Book", source_ids=[job.id]
    )
    row = run_generation(db, user, row)
    assert row.status == OutputStatus.COMPLETED.value
    assert "Questions & Answers" in row.content_text
    assert "Q1?" in row.content_text


def test_run_generation_book_includes_toc(db, monkeypatch):
    user = auth_service.create_user(db, email="btoc@x.com", password="pw" * 6)
    j1 = _make_job(db, user.id, "First Topic")
    j2 = _make_job(db, user.id, "Second Topic")
    j1.report_path = "/r1.html"
    j2.report_path = "/r2.html"
    db.commit()

    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")

    import app.services.outputters  # noqa: F401
    row = create_output(
        db, user_id=user.id, kind="book", title="TOC Book",
        source_ids=[j1.id, j2.id], parameters={"include_qa": False},
    )
    row = run_generation(db, user, row)
    assert "## Table of Contents" in row.content_text
    assert "[First Topic](#first-topic)" in row.content_text
    assert "[Second Topic](#second-topic)" in row.content_text


def test_run_generation_failure_lands_status_failed(db):
    """A KeyError / runtime error in the outputter is caught and the
    status transitions to FAILED with the error captured."""
    user = auth_service.create_user(db, email="bf@x.com", password="pw" * 6)
    job = _make_job(db, user.id, "X")
    db.commit()

    import app.services.outputters  # noqa: F401  registered
    # Force a malformed source_ids_json so the outputter raises.
    row = create_output(
        db, user_id=user.id, kind="book", title="Broken", source_ids=[job.id]
    )
    row.source_ids_json = "not-valid-json"
    db.commit()

    row = run_generation(db, user, row)
    assert row.status == OutputStatus.FAILED.value
    assert row.error_message is not None


# ---------------------------------------------------------------------------
# Endpoint integration — auth + tier gating
# ---------------------------------------------------------------------------


def test_author_endpoints_require_auth(unauthenticated_client):
    r = unauthenticated_client.get("/api/v1/author/kinds")
    assert r.status_code == 401


def test_author_endpoints_require_pro_tier(unauthenticated_client, db):
    """Free tier gets 403 across the entire /author/* surface."""
    token = _free_token(db, "auth-free@x.com")
    headers = {"Authorization": f"Bearer {token}"}
    r1 = unauthenticated_client.get("/api/v1/author/kinds", headers=headers)
    r2 = unauthenticated_client.get("/api/v1/author/outputs", headers=headers)
    r3 = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "x", "source_ids": []},
        headers=headers,
    )
    assert r1.status_code == 403
    assert r2.status_code == 403
    assert r3.status_code == 403


def test_kinds_lists_available_and_supported(unauthenticated_client, db):
    user, headers = _pro_headers(db, "kinds@x.com")
    r = unauthenticated_client.get("/api/v1/author/kinds", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "book" in body["available"]
    assert set(body["supported"]) == {"book", "site", "deck", "newsletter", "reel"}


def test_create_output_unsupported_kind_returns_400(unauthenticated_client, db):
    _, headers = _pro_headers(db, "uk@x.com")
    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "bogus", "title": "x", "source_ids": []},
        headers=headers,
    )
    assert r.status_code == 400


def test_create_output_no_outputter_returns_501(unauthenticated_client, db):
    """`site` is a supported kind but no outputter ships in v1 → 501."""
    _, headers = _pro_headers(db, "no-out@x.com")
    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "site", "title": "x", "source_ids": []},
        headers=headers,
    )
    assert r.status_code == 501


def test_create_book_returns_completed_output(
    unauthenticated_client, db, monkeypatch
):
    user, headers = _pro_headers(db, "cb@x.com")
    job = _make_job(db, user.id, "Sample Topic")
    job.report_path = "/r.html"
    db.commit()

    from app.services import report_service
    monkeypatch.setattr(
        report_service, "get_report_html", lambda p: "<p>Sample body.</p>"
    )

    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={
            "kind": "book", "title": "My Book",
            "source_ids": [job.id], "parameters": {"include_qa": False},
        },
        headers=headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == OutputStatus.COMPLETED.value
    assert body["has_content"] is True


def test_get_output_content_returns_markdown(
    unauthenticated_client, db, monkeypatch
):
    user, headers = _pro_headers(db, "gc@x.com")
    job = _make_job(db, user.id, "T")
    job.report_path = "/r.html"
    db.commit()
    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>Body.</p>")

    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "T", "source_ids": [job.id]},
        headers=headers,
    )
    output_id = r.json()["id"]

    r = unauthenticated_client.get(
        f"/api/v1/author/outputs/{output_id}/content", headers=headers
    )
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "# T" in r.text


def test_get_output_404_for_other_user(unauthenticated_client, db, monkeypatch):
    a, headers_a = _pro_headers(db, "iso-a@x.com")
    b, headers_b = _pro_headers(db, "iso-b@x.com")
    job = _make_job(db, a.id, "T")
    job.report_path = "/r.html"
    db.commit()
    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")

    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "T", "source_ids": [job.id]},
        headers=headers_a,
    )
    output_id = r.json()["id"]

    # User B cannot see user A's output.
    r = unauthenticated_client.get(
        f"/api/v1/author/outputs/{output_id}", headers=headers_b
    )
    assert r.status_code == 404


def test_delete_output_round_trip(unauthenticated_client, db, monkeypatch):
    user, headers = _pro_headers(db, "del@x.com")
    job = _make_job(db, user.id, "T")
    job.report_path = "/r.html"
    db.commit()
    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")

    r = unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "T", "source_ids": [job.id]},
        headers=headers,
    )
    output_id = r.json()["id"]

    r = unauthenticated_client.delete(
        f"/api/v1/author/outputs/{output_id}", headers=headers
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": True}

    r = unauthenticated_client.get(
        f"/api/v1/author/outputs/{output_id}", headers=headers
    )
    assert r.status_code == 404


def test_list_outputs_returns_only_current_user(unauthenticated_client, db, monkeypatch):
    a, headers_a = _pro_headers(db, "list-a@x.com")
    b, headers_b = _pro_headers(db, "list-b@x.com")
    job_a = _make_job(db, a.id, "A topic")
    job_b = _make_job(db, b.id, "B topic")
    job_a.report_path = "/a.html"
    job_b.report_path = "/b.html"
    db.commit()
    from app.services import report_service
    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<p>X</p>")

    unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "A book", "source_ids": [job_a.id]},
        headers=headers_a,
    )
    unauthenticated_client.post(
        "/api/v1/author/outputs",
        json={"kind": "book", "title": "B book", "source_ids": [job_b.id]},
        headers=headers_b,
    )

    r = unauthenticated_client.get("/api/v1/author/outputs", headers=headers_a)
    titles = {x["title"] for x in r.json()}
    assert titles == {"A book"}
