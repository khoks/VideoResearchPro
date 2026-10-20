"""S-6.4.1 — the newsletter outputter.

What an issue promises: only material new to this reader in ``(since,
until]``; nothing new means no issue (``skipped``, with the reason); the
featured section cites only sources it was given, as working links, or falls
back to the source's own summary and says so; the email carries no external
CSS, images or scripts; the row records the window it covered.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from lxml import html as lxml_html

from app.config import settings
from app.models.document_visibility import DocumentVisibility
from app.models.job import Job
from app.models.library_qa_exchange import LibraryQAExchange
from app.models.output import Output
from app.models.output_citation import OutputCitation
from app.models.qa_exchange import QAExchange
from app.models.saved_search import SavedSearch
from app.models.saved_search_run import SavedSearchRun
from app.services import auth_service, output_artifacts, output_service
from app.services.outputters import book_cohesion
from tests.test_services.test_book_endnotes import _smoke_run

NOW = datetime(2026, 10, 19, 12, 0, 0)
SINCE, UNTIL = NOW - timedelta(days=7), NOW


@pytest.fixture(autouse=True)
def _quiet(tmp_path, monkeypatch):
    import app.services.outputters  # noqa: F401

    monkeypatch.setattr(settings, "OUTPUTS_DIR", str(tmp_path / "outputs"))
    monkeypatch.setattr(settings, "APP_BASE_URL", "https://pratidhvani.example")
    with patch("app.services.progress_service.publish_progress"), patch("app.services.progress_service.publish_status_change"):
        yield


class FakeModel:
    def __init__(self, text: str | Exception):
        self.text = text
        self.prompts: list[str] = []

    def __call__(self, use_case, system, user, max_tokens):
        assert use_case == "author_newsletter_compose"
        self.prompts.append(user)
        if isinstance(self.text, Exception):
            raise self.text
        return AIMessage(content=self.text, usage_metadata={"input_tokens": 3_000, "output_tokens": 500, "total_tokens": 3_500})


def _markers(prompt: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\[S(\d+)\]", prompt)})


def _setup(db, tmp_path, email="nl@x.com"):
    user = auth_service.create_user(db, email=email, password="pw" * 6)
    job = _smoke_run(db, user.id, tmp_path, topic="Smoking and lungs")
    db.query(Job).filter(Job.id == job.id).update({"completed_at": NOW - timedelta(days=2), "created_at": NOW - timedelta(days=3)})
    rows = db.query(DocumentVisibility).filter(DocumentVisibility.tenant_id == user.id).all()
    # One grant exactly at `since` (excluded), one inside, one at `until` (included).
    for row, at in zip(rows, (SINCE, NOW - timedelta(days=1), UNTIL)):
        row.created_at = at
    db.add(QAExchange(job_id=job.id, tenant_id=user.id, question="Does smoking cause most lung cancer?",
                      answer="Yes, per the pulmonologist, it is the leading cause.", references="[]",
                      created_at=NOW - timedelta(days=1)))
    db.add(QAExchange(job_id=job.id, tenant_id=user.id, question="An old question", answer="Old.", references="[]",
                      created_at=SINCE - timedelta(days=1)))
    db.add(LibraryQAExchange(tenant_id=user.id, question="What do my sources say about BP tablets?",
                             answer="Keep taking them unless a doctor says otherwise.", created_at=NOW - timedelta(hours=5)))
    ss = SavedSearch(tenant_id=user.id, question="Is vaping safer?")
    db.add(ss)
    db.commit()
    db.add(SavedSearchRun(saved_search_id=ss.id, tenant_id=user.id, ran_at=NOW - timedelta(days=2), status="changed",
                          changed=True, diff_summary="Two new sources disagree about long-term risk."))
    db.add(SavedSearchRun(saved_search_id=ss.id, tenant_id=user.id, ran_at=NOW - timedelta(days=3), status="unchanged", changed=False))
    db.commit()
    return user, job


def _issue(db, user, *, invoke=None, **params):
    row = output_service.create_output(db, user_id=user.id, kind="newsletter", title="Weekly digest", source_ids=[],
                                       parameters={"since": SINCE.isoformat(), "until": UNTIL.isoformat(), **params})
    with patch.object(book_cohesion, "_default_invoke", invoke or FakeModel(RuntimeError("no model in this test"))):
        return output_service.run_generation(db, user, row)


def test_an_issue_lists_only_what_is_new_in_the_window(db, tmp_path):
    user, job = _setup(db, tmp_path)
    out = _issue(db, user, sections={"featured": False})
    assert out.status == "completed", out.error_message
    md = out.content_text
    assert "## New in your library (2)" in md, "the grant at `since` is excluded, the one at `until` included"
    assert "## Questions you asked (2)" in md and "An old question" not in md
    assert "Does smoking cause most lung cancer?" in md and "What do my sources say about BP tablets?" in md
    assert "## Saved searches with new answers (1)" in md and "Two new sources disagree" in md
    assert "## Featured" not in md
    assert "https://pratidhvani.example/jobs/" in md and "https://pratidhvani.example/library?document=" in md
    params = json.loads(out.parameters_json)
    assert params["since"].startswith("2026-10-12T12:00:00") and params["until"].startswith("2026-10-19T12:00:00")
    assert params["counts"] == {"library": 2, "knowledge": 0, "questions": 2, "saved_searches": 1, "outputs": 0}
    assert output_artifacts.available_formats(out) == ["md", "html"]


def test_nothing_new_skips_the_issue_and_says_why(db, tmp_path):
    user = auth_service.create_user(db, email="nl-empty@x.com", password="pw" * 6)
    out = _issue(db, user)
    assert out.status == "skipped"
    assert out.progress_message.startswith("Nothing new from 12 Oct to 19 Oct 2026")
    assert out.content_text is None and output_artifacts.available_formats(out) == []


def test_sections_can_be_turned_off_and_unknown_ones_are_refused(db, tmp_path):
    user, _ = _setup(db, tmp_path)
    out = _issue(db, user, sections={"featured": False, "library": False, "saved_searches": False})
    assert "New in your library" not in out.content_text and "Saved searches" not in out.content_text
    assert "Questions you asked" in out.content_text
    # Only disabled sections had material: no issue.
    out = _issue(db, user, sections={"featured": False, "questions": False, "library": False, "saved_searches": False})
    assert out.status == "skipped"
    with pytest.raises(Exception, match="Unknown newsletter sections"):
        from app.services.outputters.newsletter import NewsletterOutputter
        NewsletterOutputter().prepare_parameters({"sections": {"gossip": True}})


def test_featured_section_links_its_markers_and_drops_unknown_ones(db, tmp_path):
    user, job = _setup(db, tmp_path)
    model = FakeModel("")
    model.text = None  # set after we see the markers

    def answer(use_case, system, user_prompt, max_tokens):
        n = _markers(user_prompt)
        assert n, "the source reaches the model with markers"
        return AIMessage(
            content=f"# Smoking is the leading cause\n\nSmoking is the leading cause of lung cancer [S{n[0]}]. "
                    f"Silica exposure also matters [S{n[1]}] [S999]. See [this](https://evil.example).\n\n"
                    f"Revisit the BP advice next.",
            usage_metadata={"input_tokens": 3_100, "output_tokens": 480, "total_tokens": 3_580})

    out = _issue(db, user, invoke=answer, sections={"featured": True})
    md = out.content_text
    assert "## Featured: Smoking is the leading cause" in md
    featured = md.split("## Featured:")[1].split("\n## ")[0]
    links = re.findall(r"\]\((https?://[^)]+)\)", featured)
    assert links and all("youtube.com/watch" in u for u in links[:-1]), "markers became links to the moments"
    assert not re.search(r"\[S\d+\]", featured) and "evil.example" not in featured
    assert "written by a model (claude-sonnet-5)" in featured
    assert db.query(OutputCitation).filter(OutputCitation.output_id == out.id).count() == 2
    params = json.loads(out.parameters_json)
    assert params["featured_ref"] == f"job:{job.id}"
    assert json.loads(out.usage_json)["calls"][0]["use_case"] == "author_newsletter_compose"


@pytest.mark.parametrize("reply, note", [
    ("# Headline\n\nA sentence with no marker at all.", "cited nothing"),
    (RuntimeError("provider down"), "could not be written"),
])
def test_an_unusable_featured_section_falls_back_to_the_sources_summary(db, tmp_path, reply, note):
    user, _ = _setup(db, tmp_path, email=f"nl-{abs(hash(note))}@x.com")
    out = _issue(db, user, invoke=FakeModel(reply), sections={"featured": True})
    assert out.status == "completed"
    md = out.content_text
    assert f"Processing note: The " in md and note in md
    assert "the report's own summary" in md
    featured = md.split("## Featured:")[1].split("\n## ")[0]
    assert "youtube.com/watch" in featured, "the summary keeps its source links"


def test_a_quiet_week_resurfaces_the_least_recently_featured_source(db, tmp_path):
    user, job = _setup(db, tmp_path)
    db.query(Job).filter(Job.id == job.id).update({"completed_at": SINCE - timedelta(days=30)})
    db.commit()
    answer = lambda u, s, p, m: AIMessage(content=f"# Back again\n\nA point [S{_markers(p)[0]}].",
                                          usage_metadata={"input_tokens": 1, "output_tokens": 1, "total_tokens": 2})
    out = _issue(db, user, invoke=answer, sections={"featured": True})
    assert "## From your library: Back again" in out.content_text
    assert json.loads(out.parameters_json)["featured_ref"] == f"job:{job.id}"


def test_the_email_is_self_contained_with_inline_styles(db, tmp_path):
    user, _ = _setup(db, tmp_path)
    out = _issue(db, user, sections={"featured": False})
    html = output_artifacts.artifact_file(out, "html").read_text(encoding="utf-8")
    doc = lxml_html.fromstring(html)
    assert not doc.xpath("//style | //link | //script | //img")
    assert all(el.get("style") for el in doc.xpath("//h2 | //p | //li | //a"))
    hrefs = doc.xpath("//a/@href")
    assert hrefs and all(h.startswith(("https://pratidhvani.example/", "https://www.youtube.com/")) for h in hrefs)


def test_since_defaults_to_the_last_issue(db, tmp_path):
    user, _ = _setup(db, tmp_path)
    last = Output(user_id=user.id, kind="newsletter", title="Last", status="completed", content_text="x",
                  created_at=NOW - timedelta(days=2))
    db.add(last)
    db.commit()
    row = output_service.create_output(db, user_id=user.id, kind="newsletter", title="Weekly digest", source_ids=[],
                                       parameters={"until": UNTIL.isoformat(), "sections": {"featured": False}})
    out = output_service.run_generation(db, user, row)
    assert json.loads(out.parameters_json)["since"].startswith("2026-10-17T12:00:00")
    assert "## New in your library (2)" in out.content_text


def test_router_validates_and_estimates(unauthenticated_client, db, tmp_path):
    user, _ = _setup(db, tmp_path)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    h = {"Authorization": f"Bearer {token}"}
    assert "newsletter" in unauthenticated_client.get("/api/v1/author/kinds", headers=h).json()["available"]
    bad = unauthenticated_client.post("/api/v1/author/outputs", headers=h,
                                      json={"kind": "newsletter", "title": "D", "parameters": {"sections": {"gossip": True}}})
    assert bad.status_code == 400
    bad = unauthenticated_client.post("/api/v1/author/outputs", headers=h,
                                      json={"kind": "newsletter", "title": "D", "parameters": {"since": "last tuesday"}})
    assert bad.status_code == 400
    with patch.object(book_cohesion, "_default_invoke", lambda *a: pytest.fail("estimate must not call a model")):
        est = unauthenticated_client.post("/api/v1/author/outputs/estimate", headers=h,
                                          json={"kind": "newsletter", "title": "D", "parameters": {"sections": {"featured": True}}}).json()
    assert [c["use_case"] for c in est["calls"]] == ["author_newsletter_compose"] and est["cost_usd"] > 0


def test_by_default_an_issue_has_no_featured_section_and_calls_no_model(db, tmp_path):
    # D-097: the featured section is opt-in.
    user, _ = _setup(db, tmp_path, email="nl-default@x.com")
    out = _issue(db, user, invoke=lambda *a: pytest.fail("no model call by default"))
    assert out.status == "completed" and "## Featured" not in out.content_text and out.usage_json is None
    assert json.loads(out.parameters_json)["sections"]["featured"] is False


def test_only_markers_shown_to_the_model_can_become_links(db, tmp_path):
    # The S-6.4.1 trial: with every report marker valid, an invented "[S2]"
    # linked a claim to an unrelated moment.
    from app.services.outputters import newsletter

    user, job = _setup(db, tmp_path, email="nl-shown@x.com")
    featured = newsletter._featured_source(db, user, "job", db.get(Job, job.id), False)
    shown = {int(n) for n in re.findall(r"\[S(\d+)\]", featured.text)}
    assert shown and set(featured.links) == shown
    assert "CITED POINTS" in featured.text
