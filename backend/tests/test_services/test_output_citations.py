"""S-6.7.3 — `output_citations`: every link an output cites becomes a row.

The resolver is a port of the reading room's (S-8.8.2), so the unit cases
mirror `frontend/src/components/reader/__tests__/citations.test.ts`. The
book test runs the stored smoke-test report (30 bare `&t=` anchors, written
before S-1.14.9) against its three real sources, which the reader resolves
30 of 30.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.job_video import JobVideo
from app.models.output_citation import OutputCitation
from app.services import auth_service, output_service
from app.services.output_citation_service import extract_markdown_citations, timestamp_href, url_key

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "reports"


def _doc(**kw) -> SimpleNamespace:
    base = dict(document_id=str(uuid.uuid4()), video_id=None, title="", channel_name="", url=None,
                source_url=None, source_type="video", source_id=None)
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Resolver (mirrors the reader's cases)
# ---------------------------------------------------------------------------


def test_youtube_id_in_the_href_wins():
    d = _doc(video_id="abcdefghijk", title="Some video title", source_id="abcdefghijk")
    [c] = extract_markdown_citations("See [0:42](https://www.youtube.com/watch?v=abcdefghijk&t=42).", [d])
    assert (c.resolved_by, c.document_id, c.seconds, c.label) == ("video_id", d.document_id, 42, "0:42")
    assert c.url == "https://www.youtube.com/watch?v=abcdefghijk&t=42"


def test_non_youtube_href_matches_a_document_url_ignoring_t_and_www():
    d = _doc(source_type="podcast_episode", url="https://pods.example/ep/7", source_id="ep7")
    [c] = extract_markdown_citations("[12:00](https://www.pods.example/ep/7/?t=720)", [d])
    assert c.resolved_by == "url" and c.url == "https://www.pods.example/ep/7/?t=720"


def test_bare_anchor_resolves_by_title_in_the_surrounding_text_and_gets_a_url():
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    md = "- **Fact:** prices rose.\n\n  **Source:** Channel — *Inflation and the long run*, [1:15](&t=75)\n"
    [c] = extract_markdown_citations(md, [d])
    assert c.resolved_by == "title"
    assert c.url == "https://www.youtube.com/watch?v=abcdefghijk&t=75"


def test_title_found_earlier_in_the_same_list_item():
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    md = "- **Fact:** Inflation and the long run says prices rose.\n\n  **Source:** [1:15](&t=75)\n\n- **Fact:** other\n"
    assert extract_markdown_citations(md, [d])[0].resolved_by == "title"


def test_tight_list_items_do_not_borrow_an_earlier_items_title():
    """Items without blank lines share one block; each anchor reads only its
    own item, as the reader reads only its own `<li>`."""
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    md = "- *Inflation and the long run*, [1:15](&t=75)\n- someone else, [0:09](&t=9)\n"
    first, second = extract_markdown_citations(md, [d])
    assert first.resolved_by == "title"
    assert second.resolved_by is None and second.url is None


def test_loose_item_continuation_reaches_back_to_its_own_marker_only():
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    md = (
        "- *Inflation and the long run* first item\n\n"
        "- **Fact:** other item\n\n"
        "  **Source:** [0:09](&t=9)\n"
    )
    [c] = extract_markdown_citations(md, [d])
    assert c.resolved_by is None, "the title belongs to the previous item, not this one"


def test_loose_item_continuation_finds_its_own_title():
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    md = "- **Fact:** prices rose in *Inflation and the long run*.\n\n  **Source:** [0:09](&t=9)\n"
    [c] = extract_markdown_citations(md, [d])
    assert c.resolved_by == "title"


def test_longest_title_wins_over_its_prefix():
    one = _doc(video_id="aaaaaaaaaaa", title="Rate cuts explained")
    two = _doc(video_id="bbbbbbbbbbb", title="Rate cuts explained part 2")
    [c] = extract_markdown_citations("*Rate cuts explained part 2*, [0:10](&t=10)", [one, two])
    assert c.document_id == two.document_id


def test_title_stem_before_hashtags_matches():
    d = _doc(video_id="abcdefghijk", title="Health care basics #bp #doctor")
    assert extract_markdown_citations("*Health care basics*, [0:05](&t=5)", [d])[0].resolved_by == "title"


def test_sole_channel_resolves_when_no_title_is_present():
    d = _doc(video_id="abcdefghijk", title="A long video title here", channel_name="NewsFirst Kannada")
    other = _doc(video_id="ccccccccccc", title="Another long title here", channel_name="Other Channel")
    [c] = extract_markdown_citations("NewsFirst Kannada said so, [2:00](&t=120)", [d, other])
    assert c.resolved_by == "channel" and c.document_id == d.document_id


def test_a_shared_channel_is_not_enough():
    a = _doc(video_id="aaaaaaaaaaa", title="First long title", channel_name="Same Channel")
    b = _doc(video_id="bbbbbbbbbbb", title="Second long title", channel_name="Same Channel")
    [c] = extract_markdown_citations("Same Channel said so, [2:00](&t=120)", [a, b])
    assert c.resolved_by is None and c.url is None and c.document_id is None


def test_unresolved_bare_anchor_is_recorded_without_inventing_a_url():
    [c] = extract_markdown_citations("Someone said, [2:00](&t=120)", [])
    assert (c.url, c.document_id, c.resolved_by, c.seconds, c.href) == (None, None, None, 120, "&t=120")


def test_unmatched_absolute_link_keeps_its_url():
    [c] = extract_markdown_citations("[thread](https://news.example/item?id=9)", [])
    assert c.url == "https://news.example/item?id=9" and c.resolved_by is None and c.source_type == "url"


def test_anchors_images_and_relative_links_are_not_citations():
    md = "1. [Chapter](#chapter)\n\n![logo](https://x.example/l.png)\n\n[about](/about)\n\n[0:01](&t=1)"
    assert [c.label for c in extract_markdown_citations(md, [])] == ["0:01"]


def test_garbage_href_falls_back_to_context():
    d = _doc(video_id="abcdefghijk", title="Inflation and the long run")
    # Report writers cut mid-tag sometimes; never link to such an href.
    md = "*Inflation and the long run*, [0:09](https://youtu.be/x<b>&t=9)"
    [c] = extract_markdown_citations(md, [d])
    assert c.resolved_by == "title" and c.url == "https://www.youtube.com/watch?v=abcdefghijk&t=9"


def test_timestamp_href_per_source_kind():
    assert timestamp_href(_doc(video_id="abcdefghijk"), 0) == "https://www.youtube.com/watch?v=abcdefghijk"
    assert timestamp_href(_doc(source_type="podcast_episode", source_url="https://p.example/e"), 30) == "https://p.example/e#t=30"
    assert timestamp_href(_doc(source_type="reddit_post", url="https://reddit.com/r/x/1"), 30) == "https://reddit.com/r/x/1"
    assert url_key("not a url") is None


# ---------------------------------------------------------------------------
# The book writes rows: the real smoke-test report against its real sources
# ---------------------------------------------------------------------------


@pytest.fixture
def quiet_progress():
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


def _seed_smoke_run(db, owner_id: str, *, visible_to: str | None, report_dir: Path) -> Job:
    sources = json.loads((FIXTURES / "topic_three_videos.sources.json").read_text(encoding="utf-8"))
    report = report_dir / f"report-{uuid.uuid4().hex[:6]}.html"
    report.write_text((FIXTURES / "topic_three_videos.html").read_text(encoding="utf-8"), encoding="utf-8")
    job = Job(id=str(uuid.uuid4()), tenant_id=owner_id, job_type="topic", status="completed",
              topic="pratidhvani smoke test", report_path=str(report))
    db.add(job)
    db.commit()
    for s in sources:
        channel_id = ("UC" + uuid.uuid4().hex)[:24]
        db.add(Channel(channel_id=channel_id, name=s["channel_name"]))
        db.commit()
        doc = db.get(Document, s["document_id"]) or Document(
            document_id=s["document_id"], video_id=s["video_id"], title=s["title"], url=s["url"], channel_id=channel_id)
        db.add(doc)
        db.commit()
        db.add(JobVideo(job_id=job.id, document_id=doc.document_id, video_id=doc.video_id, approved=True))
        if visible_to:
            db.add(DocumentVisibility(document_id=doc.document_id, tenant_id=visible_to, source="job"))
        db.commit()
    return job


def _book(db, user, job_ids):
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="Smoke", source_ids=job_ids,
                                       parameters={"include_qa": False})
    return output_service.run_generation(db, user, row)


def test_every_citation_in_the_real_report_becomes_a_resolved_row(db, tmp_path, quiet_progress):
    sources = {s["video_id"]: s for s in json.loads((FIXTURES / "topic_three_videos.sources.json").read_text(encoding="utf-8"))}
    user = auth_service.create_user(db, email="cite@x.com", password="pw" * 6)
    job = _seed_smoke_run(db, user.id, visible_to=user.id, report_dir=tmp_path)
    out = _book(db, user, [job.id])
    assert out.status == "completed"

    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).order_by(OutputCitation.position).all()
    assert len(rows) == 30
    # S-6.1.4: every bare anchor became its resolved link plus endnote n.
    assert "](&t=" not in out.content_text
    assert out.content_text.count("](https://www.youtube.com/watch?v=") == 30  # endnotes use <autolinks>
    for n in range(1, 31):
        assert f"[^{n}]:" in out.content_text and f"[^{n}]" in out.content_text.split("## Endnotes")[0]
    assert [r.position for r in rows] == list(range(1, 31))
    assert all(r.resolved_by in ("title", "channel") for r in rows), {r.resolved_by for r in rows}
    for r in rows:
        assert r.document_id is not None and r.source_type == "video"
        vid = r.url.split("v=")[1].split("&")[0]
        assert vid in sources
        assert r.url == f"https://www.youtube.com/watch?v={vid}" + (f"&t={r.seconds}" if r.seconds else "")
    assert {r.document_id for r in rows} == {s["document_id"] for s in sources.values()}


def test_a_document_the_user_cannot_see_is_never_cited(db, tmp_path, quiet_progress):
    """Same run, but the documents carry no visibility grant for this user."""
    user = auth_service.create_user(db, email="cite2@x.com", password="pw" * 6)
    job = _seed_smoke_run(db, user.id, visible_to=None, report_dir=tmp_path)
    out = _book(db, user, [job.id])
    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).all()
    assert len(rows) == 30
    assert all(r.document_id is None and r.url is None and r.resolved_by is None for r in rows)


def test_a_failed_or_cancelled_run_writes_no_rows(db, tmp_path, quiet_progress):
    user = auth_service.create_user(db, email="cite3@x.com", password="pw" * 6)
    job = _seed_smoke_run(db, user.id, visible_to=user.id, report_dir=tmp_path)
    import app.services.outputters  # noqa: F401

    row = output_service.create_output(db, user_id=user.id, kind="book", title="X", source_ids=[job.id])
    with patch("app.services.outputters.book_markdown._job_qa_markdown", side_effect=RuntimeError("boom")):
        out = output_service.run_generation(db, user, row)
    assert out.status == "failed"
    assert db.query(OutputCitation).filter(OutputCitation.output_id == out.id).count() == 0


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


def _pro(db, email):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def test_citations_endpoint_counts_and_isolation(unauthenticated_client, db, tmp_path, quiet_progress):
    user, headers = _pro(db, "api-cite@x.com")
    _, other_headers = _pro(db, "api-other@x.com")
    job = _seed_smoke_run(db, user.id, visible_to=user.id, report_dir=tmp_path)
    created = unauthenticated_client.post("/api/v1/author/outputs?sync=true", headers=headers,
                                          json={"kind": "book", "title": "Cited", "source_ids": [job.id],
                                                "parameters": {"include_qa": False}}).json()
    assert created["citation_count"] == 30

    r = unauthenticated_client.get(f"/api/v1/author/outputs/{created['id']}/citations", headers=headers)
    assert r.status_code == 200
    items = r.json()
    assert [i["position"] for i in items] == list(range(1, 31))
    first = items[0]
    assert first["label"] == "0:00" and first["channel_name"] == "Pratidhvani"
    assert first["title"].startswith("Health Care:")

    assert unauthenticated_client.get("/api/v1/author/outputs", headers=headers).json()[0]["citation_count"] == 30
    assert unauthenticated_client.get(f"/api/v1/author/outputs/{created['id']}", headers=headers).json()["citation_count"] == 30
    assert unauthenticated_client.get(f"/api/v1/author/outputs/{created['id']}/citations", headers=other_headers).status_code == 404

    assert unauthenticated_client.delete(f"/api/v1/author/outputs/{created['id']}", headers=headers).status_code == 200
    assert db.query(OutputCitation).filter(OutputCitation.output_id == created["id"]).count() == 0
