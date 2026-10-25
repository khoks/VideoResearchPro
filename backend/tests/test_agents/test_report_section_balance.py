"""S-1.14.17 — a composed section that stops mid-markup is retried, then closed.

Job 419e691d's stored report has one section ending inside
``<a href="https://www.youtube.com/watch?v=5``; every parser then reads the
next section's headings as part of that attribute and two of them vanish.
Compose now checks each section's HTML, composes an unfinished one once more,
and if it is still unfinished closes it and names it in the processing note.
"""
import re
from html.parser import HTMLParser
from unittest.mock import MagicMock, patch

import pytest

from app.agents import report_agent as ra
from app.utils import html_balance

_SUMMARY = "Executive Summary"
_CUT = (
    "<h2>Key Facts</h2>\n<ul>\n  <li><strong>Charts are instruments.</strong> As the plot list "
    "shows (<a href=\"https://www.youtube.com/watch?v=5"
)
_CUT_LONGER = (
    "<h2>Key Facts</h2>\n<ul>\n  <li><strong>Charts are instruments.</strong> A longer second "
    "attempt</li>\n  <li>Another fact (<a href=\"https://www.youtube.com/watch?v=5"
)
_FINISHED = "<h2>Key Facts</h2>\n<ul>\n  <li><strong>Charts are instruments.</strong> Finished.</li>\n</ul>"
_CONCLUSIONS = "<h2>Conclusions</h2>\n<p>Seaborn and Matplotlib are complements.</p>"


def _item(video: str, content: str) -> dict:
    return {
        "content": content,
        "video_title": f"title-{video}",
        "video_url": f"https://www.youtube.com/watch?v={video}",
        "channel_name": f"chan-{video}",
        "timestamp_seconds": 5,
    }


def _state(**over) -> dict:
    return {
        "chunk_summaries": [{"facts": [_item("v1", "f")], "conclusions": [_item("v2", "c")]}],
        "statistics": {},
        "job_type": "topic",
        "topic": "plotting",
        **over,
    }


class _Composer:
    """A fake ``get_llm_for``: each compose prompt is answered from a script.

    ``answers[title]`` is consumed in order (the last answer repeats); an
    Exception in it is raised instead. Map calls answer ``map_answer``.
    """

    def __init__(self, answers: dict[str, list], map_answer: str = "{}"):
        self.answers = {k: list(v) for k, v in answers.items()}
        self.map_answer = map_answer
        self.calls: list[tuple[str, int]] = []

    def __call__(self, use_case, **kw):
        llm = MagicMock()

        def invoke(messages):
            prompt = messages[0].content
            if use_case == "report_map_chunks":
                return MagicMock(content=self.map_answer, response_metadata={})
            if prompt.startswith("You are writing the Executive Summary"):
                title = _SUMMARY
            else:
                title = re.search(r"SECTION: (.+)", prompt).group(1).strip()
            self.calls.append((title, kw.get("max_tokens")))
            queue = self.answers.get(title) or [f"<h2>{title}</h2><p>ok</p>"]
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(answer, Exception):
                raise answer
            return MagicMock(content=answer)

        llm.invoke.side_effect = invoke
        return llm

    def tokens_for(self, title: str) -> list[int]:
        return [t for name, t in self.calls if name == title]


def _compose(composer: _Composer, **state) -> dict:
    with patch.object(ra, "get_llm_for", side_effect=composer):
        return ra.compose_report(_state(**state))


def _h2s(html: str) -> list[str]:
    class _Headings(HTMLParser):
        def __init__(self):
            super().__init__()
            self.inside = False
            self.found: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "h2":
                self.inside = True
                self.found.append("")

        def handle_endtag(self, tag):
            if tag == "h2":
                self.inside = False

        def handle_data(self, data):
            if self.inside:
                self.found[-1] += data

    parser = _Headings()
    parser.feed(html)
    parser.close()
    return parser.found


def test_a_finished_section_is_composed_once_and_not_disclosed():
    composer = _Composer({"Key Facts": [_FINISHED], "Conclusions": [_CONCLUSIONS]})
    out = _compose(composer)
    assert len(composer.tokens_for("Key Facts")) == 1
    assert out["processing_notes"]["report_sections_retried"] == 0
    assert out["processing_notes"]["report_sections_repaired"] == []
    assert "Processing note" not in out["final_html"]


def test_a_cut_section_is_composed_again_and_the_finished_retry_is_kept():
    composer = _Composer({"Key Facts": [_CUT, _FINISHED], "Conclusions": [_CONCLUSIONS]})
    out = _compose(composer)
    html = out["final_html"]

    first, retry = composer.tokens_for("Key Facts")
    ceiling = ra.max_output_for(ra.resolve_config("report_compose").model)
    assert retry == min(first * 2, ceiling)   # the likely cause is the budget
    assert "Finished." in html and "watch?v=5" not in html
    assert out["processing_notes"]["report_sections_retried"] == 1
    assert out["processing_notes"]["report_sections_repaired"] == []
    # A retry that worked needs no disclosure: the section is complete.
    assert "Processing note" not in html
    assert html_balance.check(html).balanced


def test_a_section_cut_twice_is_closed_and_named_in_the_processing_note():
    composer = _Composer({"Key Facts": [_CUT, _CUT_LONGER], "Conclusions": [_CONCLUSIONS]})
    out = _compose(composer)
    html = out["final_html"]

    assert len(composer.tokens_for("Key Facts")) == 2   # retried once, not more
    # The longer attempt is kept, cut before its unfinished tag and closed.
    assert "A longer second attempt" in html
    assert "watch?v=5" not in html
    assert html_balance.check(html).balanced
    # The defect itself: the NEXT section's heading survives as a heading.
    assert "Conclusions" in _h2s(html)

    note = re.search(r'<p class="processing-note"[^>]*>(.*?)</p>', html, re.S)
    assert note, "the repair must be disclosed in the processing note"
    assert '"Key Facts" section was cut off mid-markup' in note.group(1)
    assert out["processing_notes"]["report_sections_retried"] == 1
    assert out["processing_notes"]["report_sections_repaired"] == ["Key Facts"]


def _note(html: str) -> str:
    found = re.search(r'<p class="processing-note"[^>]*>(.*?)</p>', html, re.S)
    assert found, "the repair must be disclosed in the processing note"
    return found.group(1)


def test_a_failed_retry_keeps_the_first_attempt_closed():
    composer = _Composer(
        {"Key Facts": [_CUT, RuntimeError("bad request")], "Conclusions": [_CONCLUSIONS]}
    )
    out = _compose(composer)
    html = out["final_html"]
    assert "As the plot list shows (" in html
    assert html_balance.check(html).balanced
    assert out["processing_notes"]["report_sections_repaired"] == ["Key Facts"]
    # The section exists, so it is repaired, not failed.
    assert "failed to compose" not in html
    # The retry wrote nothing: the note must not claim a second cut-off attempt.
    note = _note(html)
    assert '"Key Facts" section was cut off mid-markup and could not be composed again' in note
    assert "both attempts" not in note


@pytest.mark.parametrize("empty", ["", "  \n"])
def test_an_empty_retry_keeps_the_first_attempt_closed(empty):
    """An empty answer is balanced, but it is not the section: keeping it
    would drop the section's text without a word."""
    composer = _Composer({"Key Facts": [_CUT, empty], "Conclusions": [_CONCLUSIONS]})
    out = _compose(composer)
    html = out["final_html"]
    assert len(composer.tokens_for("Key Facts")) == 2
    assert "As the plot list shows (" in html
    assert html_balance.check(html).balanced
    assert out["processing_notes"]["report_sections_repaired"] == ["Key Facts"]
    note = _note(html)
    assert '"Key Facts" section was cut off mid-markup and could not be composed again' in note
    assert "both attempts" not in note


def test_cut_twice_and_cut_once_are_disclosed_apart():
    cut_conclusions = "<h2>Conclusions</h2><p>Cut <a"
    composer = _Composer({
        "Key Facts": [_CUT, _CUT_LONGER],
        "Conclusions": [cut_conclusions, RuntimeError("bad request")],
    })
    out = _compose(composer)
    note = _note(out["final_html"])
    assert '"Key Facts" section was cut off mid-markup on both attempts' in note
    assert '"Conclusions" section was cut off mid-markup and could not be composed again' in note
    assert out["processing_notes"]["report_sections_repaired"] == ["Key Facts", "Conclusions"]


def test_the_executive_summary_is_checked_too():
    cut_summary = "<h2>Executive Summary</h2><p>The corpus agrees (<a href=\"https://www.youtube.com/watch?v=5"
    composer = _Composer({
        _SUMMARY: [cut_summary, cut_summary],
        "Key Facts": [_FINISHED],
        "Conclusions": [_CONCLUSIONS],
    })
    out = _compose(composer)
    html = out["final_html"]
    # The summary comes first: unrepaired, it would swallow every section.
    assert _h2s(html)[:3] == ["Executive Summary", "Key Facts", "Conclusions"]
    assert '"Executive Summary" section was cut off mid-markup' in html
    assert out["processing_notes"]["report_sections_repaired"] == [_SUMMARY]


def test_two_repaired_sections_are_named_together():
    cut_conclusions = "<h2>Conclusions</h2><p>Cut <a"
    composer = _Composer({
        "Key Facts": [_CUT, _CUT],
        "Conclusions": [cut_conclusions, cut_conclusions],
    })
    html = _compose(composer)["final_html"]
    assert '2 sections ("Key Facts", "Conclusions") were cut off mid-markup' in html


def test_section_titles_are_escaped_in_the_note():
    # "Historical & External References" is a real section title.
    composer = _Composer({"Historical & External References": ["<h2>Historical</h2><p>cut <a"]})
    out = _compose(composer, chunk_summaries=[{"references": [_item("v1", "r")]}])
    assert '"Historical &amp; External References" section was cut off' in out["final_html"]


# --- at the production caller ----------------------------------------------

def run_topic_report_cut_twice() -> tuple[dict, str, _Composer]:
    """``run_report_agent`` on one topic chunk, its "Key Facts" section cut
    off on both attempts. Shared with the body-route test (T-8.8.4.4)."""
    chunk = {
        "text": "Seaborn makes statistical plots with minimal code.",
        "metadata": {
            "video_id": "abcdefghijk", "video_title": "Seaborn basics", "channel_name": "Chan",
            "video_url": "https://www.youtube.com/watch?v=abcdefghijk", "timestamp_start": 0.0,
            "timestamp_end": 30.0, "chunk_index": 0, "document_id": "doc-1",
        },
    }
    map_answer = (
        '{"facts": [{"content": "Seaborn needs minimal code", "video_title": "Seaborn basics", '
        '"video_url": "https://www.youtube.com/watch?v=abcdefghijk", "channel_name": "Chan", '
        '"timestamp_seconds": 3}]}'
    )
    composer = _Composer({"Key Facts": [_CUT, _CUT_LONGER]}, map_answer=map_answer)
    with patch.object(ra, "get_llm_for", side_effect=composer):
        stats, body = ra.run_report_agent(
            job_type="topic", topic="plotting", transcript_chunks=[chunk],
        )
    return stats, body, composer


def test_run_report_agent_discloses_a_repaired_section_in_the_report_body():
    """The job's entry point: map, reduce and compose with a mocked model."""
    stats, body, composer = run_topic_report_cut_twice()
    assert stats["video_count"] == 1
    assert len(composer.tokens_for("Key Facts")) == 2
    assert html_balance.check(body).balanced
    assert re.search(
        r'<p class="processing-note"[^>]*><strong>Processing note:</strong>[^<]*'
        r'"Key Facts" section was cut off mid-markup', body,
    )


# --- channel jobs -----------------------------------------------------------
# A channel job's report is one narrative call, and the template's closing
# tags follow it: unfinished, it swallows them with nothing to tell the user.

_CHANNEL_CUT = (
    "<h2>Channel Overview</h2><p>Both channels teach plotting (see "
    "<a href=\"https://www.youtube.com/watch?v=x"
)
_CHANNEL_CUT_LONGER = (
    "<h2>Channel Overview</h2><p>Both channels teach plotting.</p><p>The longer attempt "
    "<a href=\"https://www.youtube.com/watch?v=x"
)
_CHANNEL_FINISHED = "<h2>Channel Overview</h2><p>Both channels teach plotting.</p>"


def _channel_chunk() -> dict:
    return {
        "text": "Seaborn makes statistical plots with minimal code.",
        "metadata": {
            "video_id": "abcdefghijk", "video_title": "Seaborn basics", "channel_name": "Chan",
            "timestamp_start": 0.0, "timestamp_end": 30.0, "chunk_index": 0, "document_id": "doc-1",
        },
    }


class _ChannelComposer:
    """A fake ``get_llm_for`` for channel jobs: map calls get a summary, and
    narrative calls are answered from ``answers`` in order (the last repeats)."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.budgets: list[int] = []

    def __call__(self, use_case, **kw):
        llm = MagicMock()

        def invoke(messages):
            if use_case == "report_channel":
                return MagicMock(content='{"channel_name": "Chan", "themes": ["plots"], "highlights": []}')
            assert use_case == "report_compose_channel_section"
            self.budgets.append(kw.get("max_tokens"))
            answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
            if isinstance(answer, Exception):
                raise answer
            return MagicMock(content=answer)

        llm.invoke.side_effect = invoke
        return llm


def _compose_channel(composer: _ChannelComposer) -> dict:
    with patch.object(ra, "get_llm_for", side_effect=composer):
        return ra.compose_channel_report(
            {"job_type": "channel", "transcript_chunks": [_channel_chunk()], "statistics": {}}
        )


def test_a_finished_channel_narrative_is_composed_once():
    composer = _ChannelComposer([_CHANNEL_FINISHED])
    out = _compose_channel(composer)
    assert out["final_html"] == _CHANNEL_FINISHED
    assert len(composer.budgets) == 1
    assert out["processing_notes"]["report_sections_retried"] == 0


def test_a_cut_channel_narrative_is_composed_again():
    composer = _ChannelComposer([_CHANNEL_CUT, _CHANNEL_FINISHED])
    out = _compose_channel(composer)
    first, retry = composer.budgets
    ceiling = ra.max_output_for(ra.resolve_config("report_compose_channel_section").model)
    assert retry == min(first * 2, ceiling)
    assert out["final_html"] == _CHANNEL_FINISHED
    assert out["processing_notes"] == {"report_sections_retried": 1, "report_sections_repaired": []}


def test_a_channel_narrative_cut_twice_is_closed_and_disclosed():
    composer = _ChannelComposer([_CHANNEL_CUT, _CHANNEL_CUT_LONGER])
    out = _compose_channel(composer)
    html = out["final_html"]
    assert "The longer attempt" in html and "watch?v=x" not in html
    assert html_balance.check(html).balanced
    assert '"Channel narrative" section was cut off mid-markup on both attempts' in _note(html)
    assert out["processing_notes"]["report_sections_repaired"] == ["Channel narrative"]


def test_a_channel_narrative_whose_first_call_fails_still_says_so():
    composer = _ChannelComposer([RuntimeError("bad request")])
    out = _compose_channel(composer)
    assert out["final_html"].startswith("<p>Channel narrative generation failed:")


def test_run_report_agent_closes_a_cut_channel_narrative_in_the_body():
    """The channel job's entry point, through the graph's channel route."""
    composer = _ChannelComposer([_CHANNEL_CUT, RuntimeError("bad request")])
    with patch.object(ra, "get_llm_for", side_effect=composer):
        stats, body = ra.run_report_agent(
            job_type="channel", topic="channels", transcript_chunks=[_channel_chunk()],
        )
    assert stats["video_count"] == 1
    assert html_balance.check(body).balanced
    assert "Both channels teach plotting (see" in body
    assert re.search(
        r'<p class="processing-note"[^>]*><strong>Processing note:</strong>[^<]*'
        r'"Channel narrative" section was cut off mid-markup and could not be composed again', body,
    )
