"""regenerate_report.py (T-8.8.6.9): a job's documents are picked by
``document_id`` through its ``job_documents`` rows, so a PDF and a pasted page
reach the regenerated report beside the job's video (D-070).

Offline: the report agent and the HTML builder are stubbed, era extraction is
off (``--no-era``), and building any model client raises, so no request can
leave the process. The rest is real: the script's ``main``, its query, the
worker's ``_load_cached_segments`` reading the test database, and the chunker.
The one test that runs without ``--no-era`` stubs the era call and the Chroma
stamp instead, so the store is never opened.

What a run writes is said in ``--help``, which the owner reads before running
it: without ``--no-era``, eras go to the documents and their stored chunks, for
every source type (the review of #438). ``test_help_says_what_a_run_writes``
fails on the docstring that left that out; ``test_no_era_writes_no_era``
fails when ``--no-era`` is ignored.

Mutation checks (each failed the named tests when this shipped, and
``test_a_video_only_job_is_read_as_before`` passed through all three):
joining on ``JobVideo.video_id == Document.video_id`` again, as the script did
(``test_a_pdf_and_a_pasted_page_reach_the_report_beside_the_video``,
``test_the_job_documents_rows_decide`` and
``test_a_document_with_no_cached_text_is_counted_by_its_type``); reading the
cache by ``video_id`` alone, ``_load_cached_segments(doc.video_id)`` (the
first and the last of those); counting every missing document as one figure
again (``test_a_document_with_no_cached_text_is_counted_by_its_type``).
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.database
from app.agents import report_agent
from app.models.document import Document
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.transcript_cache import TranscriptCache
from app.services import llm_service
from app.tasks import job_tasks
from app.utils import html_builder
from tests import conftest as _conftest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import regenerate_report  # noqa: E402

JOB_ID = "regen-mixed-sources-job"
OTHER_JOB_ID = "regen-other-job"

TEXT = {
    "video": "The video says the river floods every spring.",
    "pdf": "The PDF says the levee was raised in 1952.",
    "article": "The pasted page says the town moved uphill.",
    "unapproved": "The unapproved video says nothing anyone asked for.",
    "other_job": "Another job's video says something else.",
}


def _segments(text: str) -> str:
    return json.dumps([{"text": text, "start": 0.0, "duration": 5.0}])


@pytest.fixture
def mixed_job(db, test_user):
    """A completed job holding a video, an uploaded PDF and a pasted page,
    with an unapproved video beside them and a video another job holds.

    The video's link row is written the legacy way, by ``video_id`` (its
    ``document_id`` is filled in at flush); the PDF's and the page's carry
    ``document_id`` alone, as the worker writes them, with ``video_id`` NULL.
    Each document's text is cached under its ``document_id``, as
    ``youtube_service`` and ``job_tasks._cache_document_text`` cache it."""
    now = datetime.now(timezone.utc)
    docs = {
        "video": Document(
            video_id="regenvideo1", title="River video", url="https://www.youtube.com/watch?v=regenvideo1",
            transcript_status="fetched", embedded_in_chroma=True, published_at=now,
        ),
        "pdf": Document(
            source_type="pdf", source_id="pdf:regen0001", title="Levee history",
            url="/api/v1/library/pdf/regen0001.pdf", source_url="/api/v1/library/pdf/regen0001.pdf",
            transcript_status="fetched", embedded_in_chroma=True,
        ),
        "article": Document(
            source_type="article", source_id="https://example.org/town-moved", title="The town moved",
            url="https://example.org/town-moved", source_url="https://example.org/town-moved",
            transcript_status="fetched", embedded_in_chroma=True,
        ),
        "unapproved": Document(
            video_id="regenvideo2", title="Unapproved video", url="https://www.youtube.com/watch?v=regenvideo2",
            transcript_status="fetched", embedded_in_chroma=True,
        ),
        "other_job": Document(
            video_id="regenvideo3", title="Other job's video", url="https://www.youtube.com/watch?v=regenvideo3",
            transcript_status="fetched", embedded_in_chroma=True,
        ),
    }
    db.add_all([
        *docs.values(),
        Job(id=JOB_ID, tenant_id=test_user.id, job_type="topic", topic="floods",
            status="completed", created_at=now),
        Job(id=OTHER_JOB_ID, tenant_id=test_user.id, job_type="topic", topic="other",
            status="completed", created_at=now),
    ])
    db.commit()
    assert docs["pdf"].video_id is None and docs["article"].video_id is None

    db.add_all([
        JobVideo(job_id=JOB_ID, video_id="regenvideo1", approved=True),
        JobVideo(job_id=JOB_ID, document_id=docs["pdf"].document_id, video_id=None, approved=True),
        JobVideo(job_id=JOB_ID, document_id=docs["article"].document_id, video_id=None, approved=True),
        JobVideo(job_id=JOB_ID, video_id="regenvideo2", approved=False),
        JobVideo(job_id=OTHER_JOB_ID, video_id="regenvideo3", approved=True),
    ])
    for key, doc in docs.items():
        db.add(TranscriptCache(
            document_id=doc.document_id, video_id=doc.video_id, language="en",
            segments_json=_segments(TEXT[key]),
        ))
    db.commit()
    return {key: doc.document_id for key, doc in docs.items()}


@pytest.fixture
def offline(monkeypatch, tmp_path):
    """Run ``main`` against the test database with no model reachable.

    Returns the list the stubbed report agent appends its chunks to, and the
    path the script writes."""
    reports: list[list[dict]] = []

    def report(**kwargs):
        reports.append(kwargs["transcript_chunks"])
        return {"video_count": len(kwargs["transcript_chunks"])}, "<p>Floods.</p>"

    def no_model(*args, **kwargs):
        raise AssertionError("regenerate_report built a model client in an offline test")

    monkeypatch.setattr(app.database, "SessionLocal", _conftest.TestingSessionLocal)
    # The worker's cache reader opens its own session from job_tasks' import.
    monkeypatch.setattr(job_tasks, "SessionLocal", _conftest.TestingSessionLocal)
    monkeypatch.setattr(report_agent, "run_report_agent", report)
    monkeypatch.setattr(html_builder, "build_report_html", lambda **kwargs: "<html>Floods.</html>")
    monkeypatch.setattr(llm_service, "_build_from_config", no_model)
    out = tmp_path / "after.html"
    monkeypatch.setattr(
        sys, "argv", ["regenerate_report.py", "--job", JOB_ID, "--out", str(out), "--no-era"],
    )
    return reports, out


def test_a_pdf_and_a_pasted_page_reach_the_report_beside_the_video(db, mixed_job, offline) -> None:
    reports, out = offline

    assert regenerate_report.main() == 0

    (chunks,) = reports
    by_document = {c["metadata"]["document_id"]: c for c in chunks}
    assert set(by_document) == {mixed_job["video"], mixed_job["pdf"], mixed_job["article"]}
    assert by_document[mixed_job["video"]]["text"] == TEXT["video"]
    assert by_document[mixed_job["pdf"]]["text"] == TEXT["pdf"]
    assert by_document[mixed_job["article"]]["text"] == TEXT["article"]
    # Each chunk names its own source, so the report cites each by its type.
    assert by_document[mixed_job["video"]]["metadata"]["source_type"] == "video"
    assert by_document[mixed_job["video"]]["metadata"]["video_id"] == "regenvideo1"
    assert by_document[mixed_job["pdf"]]["metadata"]["source_type"] == "pdf"
    assert by_document[mixed_job["article"]]["metadata"]["source_type"] == "article"
    assert out.read_text(encoding="utf-8") == "<html>Floods.</html>"


def test_the_job_documents_rows_decide(db, mixed_job) -> None:
    """Approved rows of this job only: not the unapproved video, not the
    video another job holds."""
    picked = {doc.document_id for doc in regenerate_report.approved_documents(db, JOB_ID)}

    assert picked == {mixed_job["video"], mixed_job["pdf"], mixed_job["article"]}


def test_a_video_only_job_is_read_as_before(db, test_user, offline) -> None:
    """The YouTube path keeps its behaviour: a job of videos alone, linked by
    ``video_id`` as the search phase links them, each cached under its
    ``document_id`` and its ``video_id``, reaches the report whole, every
    chunk carrying the video's id."""
    reports, _ = offline
    now = datetime.now(timezone.utc)
    videos = [
        Document(
            video_id=f"regenyt{n:04d}", title=f"Video {n}", url=f"https://www.youtube.com/watch?v=regenyt{n:04d}",
            transcript_status="fetched", embedded_in_chroma=True,
        )
        for n in (1, 2)
    ]
    db.add_all([*videos, Job(id=JOB_ID, tenant_id=test_user.id, job_type="topic", topic="floods",
                             status="completed", created_at=now)])
    db.commit()
    for n, video in enumerate(videos, 1):
        db.add_all([
            JobVideo(job_id=JOB_ID, video_id=video.video_id, approved=True),
            TranscriptCache(document_id=video.document_id, video_id=video.video_id, language="en",
                            segments_json=_segments(f"Video {n} says the river floods.")),
        ])
    db.commit()

    assert regenerate_report.main() == 0

    (chunks,) = reports
    assert sorted((c["metadata"]["video_id"], c["metadata"]["document_id"], c["text"]) for c in chunks) == [
        ("regenyt0001", videos[0].document_id, "Video 1 says the river floods."),
        ("regenyt0002", videos[1].document_id, "Video 2 says the river floods."),
    ]


def test_a_document_with_no_cached_text_is_counted_by_its_type(db, mixed_job, offline, monkeypatch) -> None:
    """A PDF whose text was never cached is left out, and the log says which
    kind of source went missing rather than one bare figure."""
    reports, _ = offline
    db.query(TranscriptCache).filter(TranscriptCache.document_id == mixed_job["pdf"]).delete()
    db.commit()
    lines: list[str] = []
    log = logging.getLogger("regenerate_report")
    monkeypatch.setattr(log, "info", lambda msg, *args: lines.append(msg % args))

    assert regenerate_report.main() == 0

    (chunks,) = reports
    assert {c["metadata"]["document_id"] for c in chunks} == {mixed_job["video"], mixed_job["article"]}
    (summary,) = [line for line in lines if "without cached text" in line]
    assert summary.startswith("2 chunks from 2 documents (1 without cached text, 1 pdf)")


ERA = {"era_start": 1950, "era_end": 1955, "era_confidence": 0.8, "is_retrospective": True}


@pytest.fixture
def era_calls(monkeypatch):
    """Record each era extraction (by the document's title) and each Chroma
    stamp (by ``document_id``) instead of making them."""
    from app.config import settings
    from app.services import metadata_backfill_service, temporal_service

    calls: dict[str, list[str]] = {"extracted": [], "stamped": []}

    def extract(title, description, published_at, segments_or_text, llm=None):
        calls["extracted"].append(title)
        return dict(ERA)

    def stamp(document, **kwargs):
        calls["stamped"].append(document.document_id)
        return 1

    monkeypatch.setattr(settings, "TEMPORAL_SCOPE_ENABLED", True)
    monkeypatch.setattr(temporal_service, "extract_discussed_era", extract)
    monkeypatch.setattr(metadata_backfill_service, "stamp_chunk_temporal_fields", stamp)
    return calls


def test_help_says_what_a_run_writes(monkeypatch, capsys) -> None:
    """``--help`` tells the owner that a run without ``--no-era`` writes eras
    to the documents and their stored Chroma chunks, and what ``--no-era``
    spares."""
    monkeypatch.setattr(sys, "argv", ["regenerate_report.py", "--help"])

    with pytest.raises(SystemExit) as exited:
        regenerate_report.main()

    assert exited.value.code == 0
    text = " ".join(capsys.readouterr().out.split())
    assert "Writes to live data unless `--no-era` is passed" in text
    assert "for every source type" in text
    assert "written to the document's `discussed_era_json`" in text
    assert "stamped on its stored Chroma chunks" in text
    assert "no era written to the documents or their stored Chroma chunks" in text


def test_a_run_without_no_era_writes_eras_for_every_source_type(
    db, mixed_job, offline, era_calls, monkeypatch, tmp_path,
) -> None:
    """What ``--help`` says, done: each undated document of the job, the PDF
    and the pasted page beside the video, gets an era persisted and stamped on
    its stored chunks."""
    reports, _ = offline
    monkeypatch.setattr(
        sys, "argv", ["regenerate_report.py", "--job", JOB_ID, "--out", str(tmp_path / "era.html")],
    )

    assert regenerate_report.main() == 0

    assert sorted(era_calls["extracted"]) == ["Levee history", "River video", "The town moved"]
    assert sorted(era_calls["stamped"]) == sorted([mixed_job["video"], mixed_job["pdf"], mixed_job["article"]])
    db.expire_all()
    pdf = db.query(Document).filter(Document.document_id == mixed_job["pdf"]).one()
    assert json.loads(pdf.discussed_era_json) == ERA
    (chunks,) = reports
    assert len(chunks) == 3


def test_no_era_writes_no_era(db, mixed_job, offline, era_calls) -> None:
    """``--no-era`` makes no era call and writes no era anywhere."""
    reports, _ = offline

    assert regenerate_report.main() == 0

    assert era_calls == {"extracted": [], "stamped": []}
    db.expire_all()
    assert all(
        doc.discussed_era_json is None
        for doc in db.query(Document).filter(Document.document_id.in_(mixed_job.values()))
    )
    (chunks,) = reports
    assert len(chunks) == 3
