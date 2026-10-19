"""S-8.8.1: splitting a stored report back into reader parts.

The fixture is built by the real template so the test breaks if the template
and the extractor drift apart.
"""

from app.services.report_service import extract_report_body
from app.utils.html_builder import build_report_html

_BODY = """<section class="report">
  <h2>Executive Summary</h2>
  <p>First paragraph with a <a href="https://www.youtube.com/watch?v=abc123&t=42" target="_blank">0:42</a> citation.</p>
</section>
<section class="key-facts">
  <h2>Key Facts</h2>
  <div class="section"><h3>A nested section div</h3><p>Must survive.</p></div>
  <table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>
</section>"""

_STATS = {
    "video_count": 3,
    "transcript_count": 2,
    "total_words": 12345,
    "total_minutes": 67,
    "channel_breakdown": [
        {"channel_name": "Fish & Chips <TV>", "video_count": 2, "word_count": 10000, "minutes": 50},
        {"channel_name": "Other", "video_count": 1, "word_count": 2345, "minutes": 17},
    ],
}


def _document(title="Research Report: <scripts> & things", stats=_STATS, body=_BODY):
    return build_report_html(title=title, job_type="topic", statistics=stats, report_body=body)


def test_title_is_unescaped_text():
    parts = extract_report_body(_document())
    assert parts["title"] == "Research Report: <scripts> & things"


def test_generated_at_is_read_from_the_meta_line():
    parts = extract_report_body(_document())
    assert parts["generated_at"]
    assert parts["generated_at"].endswith("UTC")


def test_statistics_grid_and_channel_table_are_parsed():
    parts = extract_report_body(_document())
    stats = parts["statistics"]
    assert stats["video_count"] == 3
    assert stats["transcript_count"] == 2
    assert stats["total_words"] == 12345  # "12,345" in the HTML
    assert stats["total_minutes"] == 67
    assert stats["channel_breakdown"] == [
        {"channel_name": "Fish & Chips <TV>", "video_count": 2, "word_count": 10000, "minutes": 50},
        {"channel_name": "Other", "video_count": 1, "word_count": 2345, "minutes": 17},
    ]


def test_html_is_the_written_sections_only():
    parts = extract_report_body(_document())
    html = parts["html"]
    assert html.startswith('<section class="report">')
    assert html.endswith("</section>")
    assert "<style" not in html
    assert "report-header" not in html
    assert "<h2>Statistics</h2>" not in html
    assert "Videos Analyzed" not in html
    # The body's own `.section` div is not mistaken for the statistics block.
    assert "A nested section div" in html
    assert "Must survive." in html
    # Citations and tables pass through untouched for the client pipeline.
    assert 'href="https://www.youtube.com/watch?v=abc123&t=42"' in html
    assert "<table>" in html


def test_no_channel_breakdown_gives_empty_list():
    stats = dict(_STATS, channel_breakdown=[])
    parts = extract_report_body(_document(stats=stats))
    assert parts["statistics"]["channel_breakdown"] == []
    assert parts["html"].startswith('<section class="report">')


def test_unrecognised_document_falls_back_to_the_whole_body():
    doc = "<html><head><title>Loose</title></head><body><h2>Only this</h2><p>x</p></body></html>"
    parts = extract_report_body(doc)
    assert parts["title"] == "Loose"
    assert parts["html"] == "<h2>Only this</h2><p>x</p>"
    assert parts["statistics"] is None
    assert parts["generated_at"] is None


def test_bare_fragment_without_body_is_returned_as_is():
    parts = extract_report_body("<h2>Fragment</h2>")
    assert parts["title"] == "Report"
    assert parts["html"] == "<h2>Fragment</h2>"
