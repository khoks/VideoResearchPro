"""S-6.1.4 — endnote citations in books.

The invariants a reader relies on: every citation in a chapter is a working
link (or, if nothing matched, plain text) followed by a footnote reference;
footnote ``n`` has exactly one definition and is ``output_citations`` row
``n``; the definition names title, channel, timestamp and URL; Q&A answers
cite through their stored references; every link in the manuscript resolves
(the S-1.14.9 class of defect), including the table of contents (T-6.1.4.4).
"""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.output_citation import OutputCitation
from app.models.qa_exchange import QAExchange
from app.services import auth_service, output_service
from app.services.output_citation_service import heading_slug

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "reports"
LINK = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\s]+)\)")
REF = re.compile(r"\[\^(\d+)\](?!:)")
DEF = re.compile(r"^\[\^(\d+)\]: (.*)$", re.M)
HEADING = re.compile(r"^(#{1,6}) (.+)$", re.M)


@pytest.fixture(autouse=True)
def quiet_progress():
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


def _smoke_run(db, user_id: str, tmp_path: Path, *, topic="pratidhvani smoke test", visible=True) -> Job:
    sources = json.loads((FIXTURES / "topic_three_videos.sources.json").read_text(encoding="utf-8"))
    report = tmp_path / f"report-{uuid.uuid4().hex[:6]}.html"
    report.write_text((FIXTURES / "topic_three_videos.html").read_text(encoding="utf-8"), encoding="utf-8")
    job = Job(id=str(uuid.uuid4()), tenant_id=user_id, job_type="topic", status="completed", topic=topic,
              report_path=str(report))
    db.add(job)
    db.commit()
    for s in sources:
        doc = db.get(Document, s["document_id"])
        if doc is None:
            channel_id = ("UC" + uuid.uuid4().hex)[:24]
            db.add(Channel(channel_id=channel_id, name=s["channel_name"]))
            db.commit()
            doc = Document(document_id=s["document_id"], video_id=s["video_id"], title=s["title"], url=s["url"],
                           channel_id=channel_id)
            db.add(doc)
            db.commit()
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
        if visible and db.query(DocumentVisibility).filter_by(document_id=doc.document_id, tenant_id=user_id).first() is None:
            db.add(DocumentVisibility(document_id=doc.document_id, tenant_id=user_id, source="job"))
        db.commit()
    return job


def _generate(db, user, job_ids, **params):
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="The Smoke Book", source_ids=job_ids,
                                       parameters={"include_qa": True, **params})
    out = output_service.run_generation(db, user, row)
    assert out.status == "completed", out.error_message
    return out


def _assert_no_dead_links(md: str) -> None:
    ids = {heading_slug(text.strip()) for _hashes, text in HEADING.findall(md)}
    for label, href in LINK.findall(md):
        if href.startswith("#"):
            assert href[1:] in ids, f"in-page link to a missing heading: [{label}]({href})"
        else:
            assert href.startswith(("https://", "http://")), f"dead or relative link: [{label}]({href})"


def test_two_chapter_book_numbers_endnotes_in_order_and_matches_rows(db, tmp_path):
    user = auth_service.create_user(db, email="en1@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="First run")
    b = _smoke_run(db, user.id, tmp_path, topic="Second run")
    out = _generate(db, user, [a.id, b.id])
    md = out.content_text
    body, endnotes = md.split("\n## Endnotes\n")

    refs = [int(n) for n in REF.findall(body)]
    defs = {int(n): text for n, text in DEF.findall(endnotes)}
    assert refs == list(range(1, 61)), "references run 1..n in reading order across chapters"
    assert sorted(defs) == list(range(1, 61)), "one definition per reference"

    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).order_by(OutputCitation.position).all()
    assert [r.position for r in rows] == refs, "endnote n is output_citations position n"
    for r in rows:
        text = defs[r.position]
        assert f"<{r.url}>" in text
        assert " — " in text, "title and channel"
        if r.seconds:
            assert re.search(rf", {r.seconds // 60}:{r.seconds % 60:02d}\. <", text), text

    _assert_no_dead_links(md)
    # T-6.1.4.4: the TOC entries point at the chapter headings themselves.
    assert "1. [First run](#1-first-run)" in md and "2. [Second run](#2-second-run)" in md


def test_unresolved_citations_are_disclosed_not_linked(db, tmp_path):
    user = auth_service.create_user(db, email="en2@x.com", password="pw" * 6)
    job = _smoke_run(db, user.id, tmp_path, visible=False)
    out = _generate(db, user, [job.id])
    endnotes = out.content_text.split("\n## Endnotes\n")[1]
    assert len(DEF.findall(endnotes)) == 30
    assert all("Source not identified" in text for _n, text in DEF.findall(endnotes))
    _assert_no_dead_links(out.content_text)


def test_qa_cites_through_stored_references_not_its_prose(db, tmp_path):
    user = auth_service.create_user(db, email="en3@x.com", password="pw" * 6)
    job = _smoke_run(db, user.id, tmp_path)
    sources = json.loads((FIXTURES / "topic_three_videos.sources.json").read_text(encoding="utf-8"))
    ref = {
        "video_url": sources[1]["url"], "video_title": sources[1]["title"], "channel_name": sources[1]["channel_name"],
        "timestamp_seconds": 95.0, "timestamp_display": "1:35", "youtube_link": sources[1]["url"] + "&t=95",
    }
    db.add(QAExchange(job_id=job.id, tenant_id=user.id, question="Does smoking cause lung cancer?",
                      answer="Yes, it is the leading cause ([see](&t=12)) per the talk.", references=json.dumps([ref])))
    db.commit()
    out = _generate(db, user, [job.id])
    md = out.content_text
    qa = md.split("### Questions & Answers")[1].split("## Endnotes")[0]

    assert "([see](&t=12))" not in qa and "(see)" in qa, "links in the answer prose are reduced to text"
    assert "Sources: [1:35](" + ref["youtube_link"] + ")[^31]" in qa
    defs = dict(DEF.findall(md))
    assert defs["31"].startswith("*Smoking: The Leading Cause of Lung Cancer | Medicover Nellore* — Medicover Hospitals Nellore, 1:35.")
    row = db.query(OutputCitation).filter_by(output_id=out.id, position=31).one()
    assert (row.document_id, row.resolved_by, row.seconds) == (sources[1]["document_id"], "video_id", 95)
    _assert_no_dead_links(md)


def test_qa_reference_to_a_document_the_user_cannot_see_keeps_its_own_link_only(db, tmp_path):
    user = auth_service.create_user(db, email="en4@x.com", password="pw" * 6)
    job = _smoke_run(db, user.id, tmp_path, visible=False)
    ref = {"video_url": "https://www.youtube.com/watch?v=VbMKPDQK5Tw", "video_title": "From my own exchange",
           "channel_name": "Some Channel", "timestamp_seconds": 5, "timestamp_display": "0:05",
           "youtube_link": "https://www.youtube.com/watch?v=VbMKPDQK5Tw&t=5"}
    db.add(QAExchange(job_id=job.id, tenant_id=user.id, question="Q?", answer="A.", references=json.dumps([ref])))
    db.commit()
    out = _generate(db, user, [job.id])
    row = db.query(OutputCitation).filter_by(output_id=out.id, position=31).one()
    assert row.document_id is None and row.resolved_by is None and row.url == ref["youtube_link"]
    assert "*From my own exchange* — Some Channel, 0:05. <" in out.content_text


def test_toc_links_resolve_for_devanagari_and_punctuated_titles(db, tmp_path):
    user = auth_service.create_user(db, email="en5@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="हिंदी पुस्तक — भाग १")
    b = _smoke_run(db, user.id, tmp_path, topic="Café: déjà vu?")
    out = _generate(db, user, [a.id, b.id], include_qa=False)
    assert "](#1-हिंदी-पुस्तक-भाग-१)" in out.content_text
    assert "](#2-cafe-deja-vu)" in out.content_text
    _assert_no_dead_links(out.content_text)


def test_a_book_without_citations_has_no_endnotes_section(db, monkeypatch):
    from app.services import report_service

    monkeypatch.setattr(report_service, "get_report_html", lambda p: "<h1>T</h1><p>No citations here.</p>")
    user = auth_service.create_user(db, email="en6@x.com", password="pw" * 6)
    job = Job(id=str(uuid.uuid4()), tenant_id=user.id, job_type="topic", status="completed", topic="Plain",
              report_path="/r.html")
    db.add(job)
    db.commit()
    out = _generate(db, user, [job.id])
    assert "## Endnotes" not in out.content_text
    assert db.query(OutputCitation).filter_by(output_id=out.id).count() == 0
