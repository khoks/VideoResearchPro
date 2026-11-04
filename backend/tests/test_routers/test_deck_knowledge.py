"""S-6.3.2 — a deck planned from a document's knowledge report, model patched.

Driven through ``POST /api/v1/author/outputs`` (the production caller) and,
for a source that stops qualifying after the row exists, through the worker
task ``generate_output``.

The acceptance is S-6.3.1's: the ``.pptx`` opens, every content slide cites
a linked source in its notes, a slide citing nothing is dropped and the deck
says so. Underneath that, for ``document:<id>`` sources:
- the knowledge report reaches ``author_deck_outline`` with its document's
  marker on every paragraph and list item, and no links or other markers;
- a document the caller cannot see is 404 and one with no knowledge report
  is 409, both before any row is written;
- the create modal's list (``GET /author/knowledge-sources``) offers exactly
  the visible documents with a report.
"""
from __future__ import annotations

import io
import json
import re
import uuid
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage
from pptx import Presentation

from app.agents.prompts import deck_prompts
from app.models.channel import Channel
from app.models.document import Document
from app.models.document_visibility import DocumentVisibility
from app.models.output import Output
from app.models.output_citation import OutputCitation
from app.services import auth_service, output_artifacts, output_service
from app.services.outputters import book_cohesion
from tests.test_services.test_book_endnotes import _smoke_run

MARKER = re.compile(r"\[S(\d+)\]")

# Shaped like the reports `knowledge_agent` writes (H1, Overview, bold-term
# concepts, bullets, Speculation, a three-form quote, References), plus the
# things the deck must strip: a link, a stray marker and a footnote.
KNOWLEDGE_MD = """# Blood Pressure Medication and Abrupt Discontinuation

## Overview

Antihypertensive medication lowers blood pressure for as long as it is taken. The source explains that stopping it abruptly can let pressure rebound above its earlier level within days.

The discussion is framed for patients who feel well and assume the condition has resolved.

## Key Concepts

**Rebound hypertension** — A rise in blood pressure above the treated baseline after a drug is withdrawn suddenly.

**Tapering** — Reducing a dose in steps under supervision rather than stopping at once.

## Facts and Claims

- As of the publication date, the source states that beta blockers carry the highest rebound risk [S9].
- Stopping medication without advice is described as a common cause of emergency admissions[^2].
- Speculation: home monitoring may reduce unsupervised discontinuation.
- A quote given in full: रक्तचाप एक मौन रोग है (raktachāp ek maun rog hai) — "blood pressure is a silent disease".

## References

- [World Health Organization hypertension fact sheet](https://www.who.int/news-room/fact-sheets/detail/hypertension)
"""

DOC_VIDEO_ID = "bpVideo0001"
DOC_URL = f"https://www.youtube.com/watch?v={DOC_VIDEO_ID}"


class FakeModel:
    """Stands in for the provider; the plan is built from the prompt it got."""

    def __init__(self, plan):
        self.plan = plan
        self.prompts: list[str] = []

    def __call__(self, use_case, system, user, max_tokens):
        assert use_case == "author_deck_outline"
        self.prompts.append(user)
        plan = self.plan(user) if callable(self.plan) else self.plan
        return AIMessage(content=json.dumps(plan), usage_metadata={"input_tokens": 4_000, "output_tokens": 2_000, "total_tokens": 6_000})


def _plan(prompt: str, *, uncited: int = 2) -> dict:
    """Nine content slides citing markers the prompt offered, highest first
    (a knowledge report placed after a run holds the highest), then
    ``uncited`` slides that cite nothing usable: one empty, one only a
    marker the prompt never showed."""
    markers = sorted({int(n) for n in MARKER.findall(prompt)}, reverse=True)
    assert markers, "the prompt offered at least one marker"
    slides: list[dict] = [{"type": "section", "heading": "What the sources say"}]
    for i in range(9):
        m = markers[i % len(markers)]
        slides.append({
            "type": "bullets", "heading": f"Point {i + 1} [S{m}]",
            "bullets": [f"A specific point {i} [S{m}] and a [link](https://x.example)", "A second detail[^4]"],
            "speaker_notes": f"Say this about point {i + 1}.",
            "citations": [m],
        })
    slides.append({"type": "quote", "quote": "Blood pressure is a silent disease", "attribution": "The source",
                   "speaker_notes": "The exact words matter.", "citations": [f"S{markers[0]}"]})
    for k in range(uncited):
        slides.append({"type": "bullets", "heading": f"Unsourced {k}", "bullets": ["A claim"], "speaker_notes": "x",
                       "citations": [] if k % 2 == 0 else [max(markers) + 500]})
    return {"title": "Stopping blood pressure pills", "subtitle": "What one video explains", "slides": slides}


def _pro(db, email: str):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def _document(db, *, report: str | None = KNOWLEDGE_MD, visible_to: list[str] = (), **kw) -> Document:
    channel_id = ("UC" + uuid.uuid4().hex)[:24]
    db.add(Channel(channel_id=channel_id, name="Dr Raju Health"))
    db.commit()
    video_id = kw.pop("video_id", DOC_VIDEO_ID if kw.get("source_type", "video") == "video" else None)
    fields = dict(title="BP tablets: what happens if you stop?", url=DOC_URL, channel_id=channel_id,
                  published_at=datetime(2025, 3, 2), knowledge_report_md=report,
                  knowledge_extracted_at=datetime.now(timezone.utc) if report else None)
    fields.update(kw)
    doc = Document(video_id=video_id, **fields) if video_id else Document(**fields)
    db.add(doc)
    db.commit()
    for tenant in visible_to:
        db.add(DocumentVisibility(document_id=doc.document_id, tenant_id=tenant, source="job"))
    db.commit()
    return doc


@pytest.fixture
def outputs_dir(tmp_path, monkeypatch):
    import app.services.outputters  # noqa: F401

    monkeypatch.setattr("app.config.settings.OUTPUTS_DIR", str(tmp_path / "outputs"))
    return tmp_path


def _create(client, headers, source_ids, *, title="Pills deck"):
    return client.post("/api/v1/author/outputs?sync=true", headers=headers,
                       json={"kind": "deck", "title": title, "source_ids": source_ids})


def _slides(out: Output):
    prs = Presentation(io.BytesIO(output_artifacts.artifact_file(out, "pptx").read_bytes()))
    slides = list(prs.slides)
    texts = ["\n".join(sh.text_frame.text for sh in s.shapes if sh.has_text_frame) for s in slides]
    notes = [s.notes_slide.notes_text_frame.text if s.has_notes_slide else "" for s in slides]
    sources_at = [i for i, t in enumerate(texts) if t.startswith("Sources")]
    links = [r.hyperlink.address for i in sources_at for sh in slides[i].shapes if sh.has_text_frame
             for p in sh.text_frame.paragraphs for r in p.runs if r.hyperlink.address]
    return texts, notes, sources_at, links


def test_a_knowledge_report_deck_cites_its_document_on_every_content_slide(unauthenticated_client, db, outputs_dir, monkeypatch):
    user, headers = _pro(db, "kdeck@x.com")
    doc = _document(db, visible_to=[user.id])
    model = FakeModel(_plan)
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)

    r = _create(unauthenticated_client, headers, [f"document:{doc.document_id}"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "completed", body["error_message"]
    assert body["source_ids"] == [f"document:{doc.document_id}"]

    # What the model saw: the knowledge report, headed as one, with its one
    # source's marker on every paragraph and list item, and nothing else
    # that looks like a source.
    prompt = model.prompts[0]
    assert deck_prompts.KNOWLEDGE_REPORT_NOTE in prompt
    assert "===== KNOWLEDGE REPORT 1: BP tablets: what happens if you stop? (a YouTube video, published 2025-03-02) =====" in prompt
    assert set(MARKER.findall(prompt)) == {"1"}, "the stray [S9] in the report is gone; only the document's marker is offered"
    assert "](http" not in prompt and "[^" not in prompt and "who.int" not in prompt
    report = prompt.split("=====\n", 1)[1]
    for line in report.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            assert line.rstrip().endswith("[S1]"), f"every paragraph and list item cites the document: {line!r}"
    assert "रक्तचाप एक मौन रोग है" in prompt, "the quote's original script reaches the model"

    out = db.get(Output, body["id"])
    assert output_artifacts.available_formats(out) == ["md", "pptx"]
    texts, notes, sources_at, links = _slides(out)
    assert "from 1 knowledge report" in texts[0] and "research run" not in texts[0], "the byline names what the deck was made from"
    assert sources_at == [len(texts) - 1]
    content = [i for i in range(1, sources_at[0]) if "What the sources say" not in texts[i]]
    assert len(content) == 10, "nine bullet slides and the quote; both uncited slides dropped"
    for i in content:
        assert "Sources:" in notes[i] and DOC_URL in notes[i], f"slide {i + 1} notes link its source"
        assert "[S" not in texts[i] and "http" not in texts[i] and "[^" not in texts[i], f"slide {i + 1} text is clean"
    assert links == [DOC_URL], "the sources slide links the document once"
    assert "2 planned slides cited no source and were left out." in texts[-1]

    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).all()
    assert [(r.document_id, r.url, r.seconds, r.resolved_by) for r in rows] == [(doc.document_id, DOC_URL, None, "document")]
    assert body["citation_count"] == 1
    md = out.content_text
    assert md.startswith("# Stopping blood pressure pills") and "## Sources" in md
    assert re.findall(r"^\[\^\d+\]: .*$", md, flags=re.M) == [f"[^1]: *{doc.title}* — Dr Raju Health: <{DOC_URL}>."]


def test_another_tenants_document_is_404_and_writes_nothing(unauthenticated_client, db, outputs_dir, monkeypatch):
    user, headers = _pro(db, "kdeck-mine@x.com")
    other, _ = _pro(db, "kdeck-theirs@x.com")
    theirs = _document(db, visible_to=[other.id])
    monkeypatch.setattr(book_cohesion, "_default_invoke", lambda *a: pytest.fail("no model call for a refused source"))

    r = _create(unauthenticated_client, headers, [f"document:{theirs.document_id}"])
    assert r.status_code == 404
    assert "not in your library" in r.json()["detail"] and theirs.title not in r.json()["detail"]
    est = unauthenticated_client.post("/api/v1/author/outputs/estimate", headers=headers,
                                      json={"kind": "deck", "title": "D", "source_ids": [f"document:{theirs.document_id}"]})
    assert est.status_code == 404
    # Reads exactly like a document that does not exist.
    ghost = _create(unauthenticated_client, headers, [f"document:{uuid.uuid4()}"])
    assert ghost.status_code == 404
    # A legacy YouTube id is not a document id (D-070), even for the owner.
    mine = _document(db, visible_to=[user.id], video_id="bpVideo0007", url="https://www.youtube.com/watch?v=bpVideo0007")
    assert _create(unauthenticated_client, headers, ["document:bpVideo0007"]).status_code == 404
    assert _create(unauthenticated_client, headers, ["document:"]).status_code == 404
    assert db.query(Output).count() == 0
    # The same document by its id is accepted: the 404s above were about
    # the reference, not the caller.
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(lambda p: _plan(p, uncited=0)))
    assert _create(unauthenticated_client, headers, [f"document:{mine.document_id}"]).json()["status"] == "completed"


def test_a_document_with_no_knowledge_report_is_409_and_writes_nothing(unauthenticated_client, db, outputs_dir, monkeypatch):
    user, headers = _pro(db, "kdeck-none@x.com")
    bare = _document(db, report=None, visible_to=[user.id])
    blank = _document(db, report="  \n", visible_to=[user.id], video_id="bpVideo0002", url="https://www.youtube.com/watch?v=bpVideo0002")
    monkeypatch.setattr(book_cohesion, "_default_invoke", lambda *a: pytest.fail("no model call for a refused source"))

    for doc in (bare, blank):
        r = _create(unauthenticated_client, headers, [f"document:{doc.document_id}"])
        assert r.status_code == 409, r.text
        assert "has no knowledge report yet" in r.json()["detail"]
    # One bad source refuses the whole deck, even beside a good one.
    good = _document(db, visible_to=[user.id], video_id="bpVideo0003", url="https://www.youtube.com/watch?v=bpVideo0003")
    r = _create(unauthenticated_client, headers, [f"document:{good.document_id}", f"document:{bare.document_id}"])
    assert r.status_code == 409
    assert db.query(Output).count() == 0


def test_a_run_and_a_knowledge_report_share_one_deck(unauthenticated_client, db, outputs_dir, monkeypatch):
    user, headers = _pro(db, "kdeck-mixed@x.com")
    run = _smoke_run(db, user.id, outputs_dir, topic="Smoke run")
    # The knowledge report is about a video the run also cites, so the
    # sources slide lists that video once with the run's moments.
    smoking = db.get(Document, "ecd639a6-0883-4c93-8022-e258cde4afba")
    smoking.knowledge_report_md = KNOWLEDGE_MD
    smoking.knowledge_extracted_at = datetime.now(timezone.utc)
    db.commit()
    model = FakeModel(lambda p: _plan(p, uncited=0))
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)

    r = _create(unauthenticated_client, headers, [run.id, f"document:{smoking.document_id}"])
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    prompt = model.prompts[0]
    assert "===== REPORT 1: Smoke run =====" in prompt and "===== KNOWLEDGE REPORT 2: Smoking: The Leading Cause" in prompt
    knowledge_marker = max(int(n) for n in MARKER.findall(prompt.split("KNOWLEDGE REPORT 2")[1]))
    assert set(MARKER.findall(prompt.split("KNOWLEDGE REPORT 2")[1])) == {str(knowledge_marker)}
    assert knowledge_marker > max(int(n) for n in MARKER.findall(prompt.split("KNOWLEDGE REPORT 2")[0])), "numbered after the run's"

    out = db.get(Output, r.json()["id"])
    texts, notes, sources_at, links = _slides(out)
    assert "from 1 research run and 1 knowledge report" in texts[0]
    rows = db.query(OutputCitation).filter(OutputCitation.output_id == out.id).all()
    assert any(r.resolved_by == "document" and r.document_id == smoking.document_id for r in rows)
    prs = Presentation(io.BytesIO(output_artifacts.artifact_file(out, "pptx").read_bytes()))
    entries = [p.text for i in sources_at for sh in list(prs.slides)[i].shapes if sh.has_text_frame
               for p in sh.text_frame.paragraphs if re.match(r"^\d+\.", p.text)]
    assert len(entries) == len({r.document_id for r in rows}), "one entry per document, however it was cited"
    assert sum("Smoking: The Leading Cause" in e for e in entries) == 1


def test_a_run_only_deck_prompt_is_unchanged(db, outputs_dir, monkeypatch):
    """S-6.3.1's trialled prompt: no knowledge note, the same report header."""
    user = auth_service.create_user(db, email="kdeck-runs@x.com", password="pw" * 6)
    run = _smoke_run(db, user.id, outputs_dir, topic="Smoke run")
    model = FakeModel(lambda p: _plan(p, uncited=0))
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)
    row = output_service.create_output(db, user_id=user.id, kind="deck", title="Runs", source_ids=[run.id])
    out = output_service.run_generation(db, user, row)
    assert out.status == "completed", out.error_message
    assert model.prompts[0].startswith('DECK TITLE (the user\'s): "Runs"\n\n===== REPORT 1: Smoke run =====\n')
    assert "KNOWLEDGE" not in model.prompts[0]
    texts, *_ = _slides(out)
    assert "from 1 research run ·" in texts[0]


def test_an_uploaded_pdf_links_to_its_knowledge_report_in_the_app(unauthenticated_client, db, outputs_dir, monkeypatch):
    user, headers = _pro(db, "kdeck-pdf@x.com")
    monkeypatch.setattr("app.config.settings.APP_BASE_URL", "https://pratidhvani.test/")
    pdf = _document(db, visible_to=[user.id], source_type="pdf", source_id="d1g3st", title="Hypertension guideline",
                    url="/api/v1/library/pdf/d1g3st.pdf", source_url="/api/v1/library/pdf/d1g3st.pdf", channel_id=None)
    model = FakeModel(lambda p: _plan(p, uncited=0))
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)

    r = _create(unauthenticated_client, headers, [f"document:{pdf.document_id}"])
    assert r.status_code == 200 and r.json()["status"] == "completed", r.text
    assert "===== KNOWLEDGE REPORT 1: Hypertension guideline (a PDF document, published 2025-03-02) =====" in model.prompts[0]
    expected = f"https://pratidhvani.test/knowledge/{pdf.document_id}"
    out = db.get(Output, r.json()["id"])
    _texts, notes, _at, links = _slides(out)
    assert links == [expected] and expected in notes[2]
    assert [c.url for c in db.query(OutputCitation).filter(OutputCitation.output_id == out.id)] == [expected]


def test_a_document_that_leaves_the_library_before_the_worker_runs_is_left_out(db, outputs_dir, monkeypatch):
    """The router checked it; the worker finds it gone. Beside a usable
    source it is left out and disclosed; alone, the output fails."""
    from app.tasks import output_tasks
    from tests.conftest import TestingSessionLocal

    monkeypatch.setattr(output_tasks, "SessionLocal", TestingSessionLocal)
    user = auth_service.create_user(db, email="kdeck-gone@x.com", password="pw" * 6)
    kept = _document(db, visible_to=[user.id])
    gone = _document(db, visible_to=[user.id], video_id="bpVideo0004", url="https://www.youtube.com/watch?v=bpVideo0004",
                     title="A video since removed from the library")
    model = FakeModel(lambda p: _plan(p, uncited=0))
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)
    both = output_service.create_output(db, user_id=user.id, kind="deck", title="Both",
                                        source_ids=[f"document:{kept.document_id}", f"document:{gone.document_id}"])
    alone = output_service.create_output(db, user_id=user.id, kind="deck", title="Alone",
                                         source_ids=[f"document:{gone.document_id}"])
    db.query(DocumentVisibility).filter_by(document_id=gone.document_id, tenant_id=user.id).delete()
    db.commit()

    assert output_tasks.generate_output.run(both.id) == "completed"
    assert output_tasks.generate_output.run(alone.id) == "failed"
    db.expire_all()
    both, alone = db.get(Output, both.id), db.get(Output, alone.id)
    assert len(model.prompts) == 1, "no model call for the deck with nothing left"
    assert "since removed" not in model.prompts[0] and "KNOWLEDGE REPORT 2" not in model.prompts[0]
    texts, *_ = _slides(both)
    assert "1 chosen document had no knowledge report in your library and was left out." in texts[-1]
    assert alone.error_message == "None of the chosen runs or documents has a report this deck can be built from."


def test_the_prompt_header_names_what_the_source_is():
    from app.services.outputters.deck import _about

    def doc(source_type, **kw):
        return Document(source_type=source_type, source_id="x", title="t", url="u", **kw)

    assert _about(doc("article")) == "a web article"
    assert _about(doc("tweet")) == "an X / Twitter post"
    assert _about(doc("video", published_at=datetime(2025, 3, 2))) == "a YouTube video, published 2025-03-02"


def test_knowledge_sources_lists_the_callers_documents_with_a_report(unauthenticated_client, db):
    user, headers = _pro(db, "kdeck-list@x.com")
    other, _ = _pro(db, "kdeck-list-other@x.com")
    mine = _document(db, visible_to=[user.id])
    _document(db, report=None, visible_to=[user.id], video_id="bpVideo0005", url="https://www.youtube.com/watch?v=bpVideo0005")
    _document(db, visible_to=[other.id], video_id="bpVideo0006", url="https://www.youtube.com/watch?v=bpVideo0006",
              title="Someone else's video")

    r = unauthenticated_client.get("/api/v1/author/knowledge-sources", headers=headers)
    assert r.status_code == 200
    assert [(d["document_id"], d["title"], d["source_type"], d["channel_name"]) for d in r.json()] == [
        (mine.document_id, mine.title, "video", "Dr Raju Health")
    ]
    assert "knowledge_report_md" not in r.json()[0]
    free = auth_service.create_user(db, email="kdeck-free@x.com", password="pw" * 6)
    token, _ = auth_service.create_access_token(free.id)
    assert unauthenticated_client.get("/api/v1/author/knowledge-sources",
                                      headers={"Authorization": f"Bearer {token}"}).status_code == 403
