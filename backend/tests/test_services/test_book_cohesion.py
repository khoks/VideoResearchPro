"""S-6.1.3 — the book cohesion pass, with the model patched.

What a reader relies on: the chapters are the reports exactly as they were
(only their footnote numbers move with the order), every citation survives,
the framing the model wrote cites nothing and carries no links, every link in
the book lands on the heading it names, a failed call is disclosed rather
than hidden, and what the calls cost is recorded on the output.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.agents.prompts import author_prompts
from app.agents.prompts.shared import ENGLISH_OUTPUT_CONTRACT, VISUAL_ANNOTATION_CONTRACT
from app.models.output import Output
from app.models.output_citation import OutputCitation
from app.services import auth_service, output_artifacts, output_service
from app.services.output_service import OutputError
from app.services.outputters import book_cohesion, book_html
from tests.test_services.test_book_endnotes import _generate, _smoke_run
from tests.test_services.test_book_formats import _assert_valid_epub

GOLDEN = Path(__file__).resolve().parent.parent / "fixtures" / "books" / "cohesion_full_two_chapters.md"
REF = re.compile(r"\[\^(\d+)\](?!:)")
LINK = re.compile(r"(?<!!)\[([^\]\n]*)\]\(([^)\s]+)\)")


class FakeModel:
    """Stands in for both use cases; records what each call was sent."""

    def __init__(self, outline: dict | Exception, prose: dict | Exception | None = None):
        self.outline, self.prose = outline, prose
        self.calls: list[tuple[str, str, str, int]] = []

    def __call__(self, use_case, system, user, max_tokens):
        self.calls.append((use_case, system, user, max_tokens))
        answer = self.outline if use_case == book_cohesion.OUTLINE_USE_CASE else self.prose
        if isinstance(answer, Exception):
            raise answer
        tokens = {"author_book_outline": (4_100, 900), "author_book_prose": (8_200, 2_400)}[use_case]
        return AIMessage(
            content="Here is the plan:\n" + json.dumps(answer),
            usage_metadata={"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)},
        )


OUTLINE = {
    "order": [2, 1],
    "parts": [],
    "bridges": [{"chapter": 1, "text": "Having seen how [the second run](https://evil.example/x) frames the problem, the first run[^9] goes deeper."}],
    "introduction_brief": "A short brief that introduces both runs.",
    "conclusion_brief": "Draw the threads together.",
    "glossary_terms": ["Hypertension"],
}
PROSE = {
    "introduction": "## Welcome\n\nThis book gathers two research runs on health.\n\n<b>Read</b> them in order; see [this](https://x.example) too[^4].",
    "bridges": [{"chapter": 1, "text": "Where the previous chapter surveyed the field, this one narrows the focus."}],
    "conclusion": "Read together, these chapters suggest the same risks recur.\n\n| a | b |\n| --- | --- |",
    "glossary": [
        {"term": "Hypertension", "definition": "High blood pressure, as the chapters use it."},
        {"term": "hypertension", "definition": "Duplicate that must be dropped."},
        {"term": "Biopsy", "definition": "Taking tissue to examine, as described in the chapters."},
    ],
}


@pytest.fixture
def two_runs(db, tmp_path):
    user = auth_service.create_user(db, email=f"coh{os.urandom(3).hex()}@x.com", password="pw" * 6)
    a = _smoke_run(db, user.id, tmp_path, topic="First run")
    b = _smoke_run(db, user.id, tmp_path, topic="Second run")
    return user, a, b


def _sections(md: str) -> dict[str, str]:
    """Chapter title -> body, split at H2 headings ("## n. Title")."""
    out: dict[str, str] = {}
    for m in re.finditer(r"^## \d+\. ([^\n]+)\n(.*?)(?=^## |\Z)", md, flags=re.M | re.S):
        out[m.group(1).strip()] = m.group(2)
    return out


def _h2_section(md: str, heading: str) -> str:
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", md, flags=re.M | re.S)
    assert m, f"no '## {heading}' section"
    return m.group(1)


def _has_h2(md: str, heading: str) -> bool:
    return re.search(rf"^## {re.escape(heading)}$", md, flags=re.M) is not None


def _normalise_body(body: str) -> str:
    body = re.sub(r"^> .*\n\n", "", body.lstrip("\n"))  # the bridge, if any
    return REF.sub("[^n]", body).strip()


def _assert_links_land_on_their_headings(md: str) -> None:
    """Every in-page link resolves in the HTML the EPUB/PDF (and reader) build,
    and a contents link lands on a heading with its own label."""
    book = book_html.render_book_html(md, title="t")
    by_id = {h.id: h.text for h in book.headings}
    for label, href in LINK.findall(md):
        if href.startswith("#"):
            target = href[1:]
            assert target in by_id, f"link to a missing heading: [{label}]({href})"
            assert by_id[target].endswith(label), f"[{label}]({href}) lands on '{by_id[target]}'"
        else:
            assert href.startswith(("https://", "http://")), href


def test_full_cohesion_frames_the_book_without_touching_a_chapter(db, two_runs, monkeypatch):
    user, a, b = two_runs
    plain = _generate(db, user, [a.id, b.id], formats=[])
    model = FakeModel(OUTLINE, PROSE)
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)
    out = _generate(db, user, [a.id, b.id], formats=[], cohesion="full")
    md = out.content_text

    # The model saw digests, never a whole chapter, and was told the contracts.
    assert [c[0] for c in model.calls] == ["author_book_outline", "author_book_prose"]
    for use_case, system, user_prompt, _max in model.calls:
        assert VISUAL_ANNOTATION_CONTRACT in system and ENGLISH_OUTPUT_CONTRACT in system
        assert "[^" not in user_prompt and "](http" not in user_prompt, "digests carry no citation markup"
    assert len(model.calls[0][2]) < len(plain.content_text) / 2

    # Reading order follows the outline; chapter bodies are the reports.
    plain_sections, sections = _sections(plain.content_text), _sections(md)
    assert list(sections) == ["Second run", "First run"]
    for title in ("First run", "Second run"):
        assert _normalise_body(sections[title]) == _normalise_body(plain_sections[title]), title

    # Every citation survives, renumbered in the new reading order.
    body = md.split("\n## Endnotes\n")[0]
    assert [int(n) for n in REF.findall(body)] == list(range(1, 61))
    assert db.query(OutputCitation).filter(OutputCitation.output_id == out.id).count() == 60

    # The framing is cleaned: no links, footnotes, headings, HTML or tables.
    intro = _h2_section(md, "Introduction")
    conclusion = _h2_section(md, "Conclusion")
    bridge = re.search(r"^> (.*)$", sections["First run"], flags=re.M).group(1)
    for added in (intro, conclusion, bridge):
        assert "http" not in added and "[^" not in added and "<b>" not in added and "|" not in added
    assert "Welcome" in intro and "Read them in order; see this too." in intro
    assert "> Where the previous chapter surveyed the field, this one narrows the focus." in md
    glossary = _h2_section(md, "Glossary")
    assert glossary.count("**Hypertension**") == 1 and glossary.index("Biopsy") < glossary.index("Hypertension")

    # Disclosure, links, usage.
    assert "About this edition: the introduction, chapter bridges, conclusion and glossary were written by a model" in md
    assert "claude-sonnet-5" in md and "gpt-5.5" in md
    _assert_links_land_on_their_headings(md)
    usage = json.loads(out.usage_json)
    assert usage["cohesion"] == {"requested": "full", "applied": "full"}
    assert [c["use_case"] for c in usage["calls"]] == ["author_book_outline", "author_book_prose"]
    assert usage["input_tokens"] == 12_300 and usage["output_tokens"] == 3_300
    assert usage["cost_usd"] and usage["cost_usd"] > 0

    # Golden manuscript (T-6.1.3.6): the date line is the only moving part.
    normalised = re.sub(r"Author Studio — \d{4}-\d\d-\d\d", "Author Studio — <date>", md)
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(normalised, encoding="utf-8")
    assert normalised == GOLDEN.read_text(encoding="utf-8"), "regenerate with UPDATE_GOLDEN=1 if the change is intended"


def test_light_cohesion_is_one_call_with_order_bridges_and_a_short_introduction(db, two_runs, monkeypatch):
    user, a, b = two_runs
    model = FakeModel(OUTLINE)
    monkeypatch.setattr(book_cohesion, "_default_invoke", model)
    out = _generate(db, user, [a.id, b.id], formats=[], cohesion="light")
    md = out.content_text
    assert [c[0] for c in model.calls] == ["author_book_outline"]
    assert list(_sections(md)) == ["Second run", "First run"]
    assert "A short brief that introduces both runs." in _h2_section(md, "Introduction")
    assert not _has_h2(md, "Conclusion") and not _has_h2(md, "Glossary")
    # The outline's bridge, cleaned of its link and footnote marker.
    assert "> Having seen how the second run frames the problem, the first run goes deeper." in md
    assert "the chapter order and the chapter bridges were written by a model (gpt-5.5)" in md
    _assert_links_land_on_their_headings(md)


def test_a_failed_outline_leaves_the_users_order_and_says_so(db, two_runs, monkeypatch):
    user, a, b = two_runs
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(RuntimeError("provider down")))
    out = _generate(db, user, [a.id, b.id], formats=[], cohesion="full")
    md = out.content_text
    assert out.status == "completed"
    assert list(_sections(md)) == ["First run", "Second run"]
    assert "_Processing note: The book outline call failed (RuntimeError: provider down)" in md
    assert "About this edition" not in md and not _has_h2(md, "Introduction")
    usage = json.loads(out.usage_json)
    assert usage["cohesion"] == {"requested": "full", "applied": "none"}
    assert usage["calls"][0]["ok"] is False and usage["calls"][0]["error"].startswith("RuntimeError")


def test_a_failed_prose_call_keeps_the_outline_framing_and_says_so(db, two_runs, monkeypatch):
    user, a, b = two_runs
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(OUTLINE, ValueError("bad json")))
    out = _generate(db, user, [a.id, b.id], formats=[], cohesion="full")
    md = out.content_text
    assert "A short brief that introduces both runs." in md
    assert "Processing note: The call that writes the introduction, conclusion and glossary failed" in md
    assert json.loads(out.usage_json)["cohesion"]["applied"] == "light"


def test_an_invalid_order_and_broken_parts_are_refused_with_a_note(db, tmp_path, monkeypatch):
    user = auth_service.create_user(db, email="coh-parts@x.com", password="pw" * 6)
    jobs = [_smoke_run(db, user.id, tmp_path, topic=f"Run {i}") for i in range(1, 5)]
    outline = {**OUTLINE, "order": [2, 2, 1, 3], "parts": [{"title": "One", "chapters": [1, 3]}, {"title": "Two", "chapters": [2, 4]}],
               "bridges": []}
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(outline))
    md = _generate(db, user, [j.id for j in jobs], formats=[], cohesion="light").content_text
    assert list(_sections(md)) == ["Run 1", "Run 2", "Run 3", "Run 4"]
    assert "did not list every chapter exactly once, so your order was kept" in md
    assert "did not follow the reading order, so the book has no parts" in md
    assert "## Part " not in md


def test_parts_group_four_chapters_and_every_link_and_the_epub_hold(db, tmp_path, monkeypatch):
    user = auth_service.create_user(db, email="coh-parts2@x.com", password="pw" * 6)
    jobs = [_smoke_run(db, user.id, tmp_path, topic=f"Run {i}") for i in range(1, 5)]
    outline = {**OUTLINE, "order": [3, 4, 1, 2],
               "parts": [{"title": "Later work", "chapters": [3, 4]}, {"title": "Earlier work", "chapters": [1, 2]}],
               "bridges": [{"chapter": 4, "text": "Next, run four."}, {"chapter": 3, "text": "Must be dropped: first chapter."}]}
    monkeypatch.setattr(book_cohesion, "_default_invoke", FakeModel(outline))
    out = _generate(db, user, [j.id for j in jobs], formats=["epub"], cohesion="light")
    md = out.content_text
    assert list(_sections(md)) == ["Run 3", "Run 4", "Run 1", "Run 2"]
    assert md.index("## Part I: Later work") < md.index("## 1. Run 3") < md.index("## Part II: Earlier work") < md.index("## 3. Run 1")
    assert "**[Part I: Later work](#part-i-later-work)**" in md and "3. [Run 1](#3-run-1)" in md
    assert "Must be dropped" not in md and "> Next, run four." in md
    _assert_links_land_on_their_headings(md)
    docs = _assert_valid_epub(output_artifacts.artifact_file(out, "epub").read_bytes())
    nav = next(d for n, d in docs.items() if n.endswith("/nav.xhtml"))
    assert "Part I: Later work" in "".join(nav.itertext())


def test_clean_prose_strips_markup_and_caps_length():
    text = "# Head\n\nSee [x](https://a.b)[^3] <i>now</i>.\n\n> quoted\n\n```\ncode\n```\n\n" + "word " * 50
    cleaned = book_cohesion.clean_prose(text, 20)
    assert cleaned.startswith("Head\n\nSee x now.\n\nquoted")
    assert "code" not in cleaned and len(cleaned.split()) <= 21
    assert book_cohesion.clean_prose(None, 10) == "" and book_cohesion.clean_prose(42, 10) == ""


def test_cohesion_level_is_validated():
    assert book_cohesion.level_from({}) == "none"
    assert book_cohesion.level_from({"cohesion": "FULL"}) == "full"
    with pytest.raises(OutputError, match="cohesion"):
        book_cohesion.level_from({"cohesion": "max"})


def test_prompts_carry_the_grounding_and_shared_contracts():
    for system in (author_prompts.OUTLINE_SYSTEM, author_prompts.PROSE_SYSTEM):
        assert VISUAL_ANNOTATION_CONTRACT in system and ENGLISH_OUTPUT_CONTRACT in system
        assert "Never add a fact" in system and "no links, no footnote markers" in system


# ---------------------------------------------------------------------------
# Router: estimate and validation
# ---------------------------------------------------------------------------


@pytest.fixture
def pro(db):
    user = auth_service.create_user(db, email="coh-router@x.com", password="pw" * 6)
    user.tier = "pro"
    db.commit()
    token, _ = auth_service.create_access_token(user.id)
    return user, {"Authorization": f"Bearer {token}"}


def test_estimate_prices_the_calls_before_anything_runs(unauthenticated_client, db, pro, tmp_path, monkeypatch):
    user, headers = pro
    jobs = [_smoke_run(db, user.id, tmp_path, topic=f"Run {i}") for i in (1, 2)]
    monkeypatch.setattr(book_cohesion, "_default_invoke", lambda *a: pytest.fail("estimate must not call a model"))
    before = db.query(Output).count()
    body = {"kind": "book", "title": "Est", "source_ids": [j.id for j in jobs]}
    full = unauthenticated_client.post("/api/v1/author/outputs/estimate", headers=headers,
                                       json={**body, "parameters": {"cohesion": "full"}}).json()
    assert [c["use_case"] for c in full["calls"]] == ["author_book_outline", "author_book_prose"]
    assert full["calls"][0]["model"] == "gpt-5.5" and full["calls"][1]["model"] == "claude-sonnet-5"
    assert all(c["input_tokens"] > 1_000 for c in full["calls"]) and full["cost_usd"] > 0
    none = unauthenticated_client.post("/api/v1/author/outputs/estimate", headers=headers, json=body).json()
    assert none["calls"] == [] and none["cost_usd"] == 0
    bad = unauthenticated_client.post("/api/v1/author/outputs/estimate", headers=headers,
                                      json={**body, "parameters": {"cohesion": "max"}})
    assert bad.status_code == 400
    assert db.query(Output).count() == before


def test_create_records_the_level_and_refuses_an_unknown_one(unauthenticated_client, db, pro, tmp_path):
    user, headers = pro
    job = _smoke_run(db, user.id, tmp_path)
    r = unauthenticated_client.post("/api/v1/author/outputs?sync=true", headers=headers,
                                    json={"kind": "book", "title": "B", "source_ids": [job.id]})
    assert r.json()["parameters"]["cohesion"] == "none" and r.json()["usage"] is None
    r = unauthenticated_client.post("/api/v1/author/outputs", headers=headers,
                                    json={"kind": "book", "title": "B", "source_ids": [job.id], "parameters": {"cohesion": "max"}})
    assert r.status_code == 400

