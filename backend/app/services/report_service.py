import html as html_lib
import logging
import os
import re
from html.parser import HTMLParser

logger = logging.getLogger(__name__)


def get_report_html(report_path: str) -> str | None:
    """Read an HTML report from disk."""
    if not report_path or not os.path.exists(report_path):
        return None
    with open(report_path, "r", encoding="utf-8") as f:
        return f.read()


def delete_report(report_path: str) -> bool:
    """Delete a report file from disk."""
    if report_path and os.path.exists(report_path):
        os.remove(report_path)
        return True
    return False


# ---------------------------------------------------------------------------
# S-8.8.1: report body extraction for the native reader.
#
# A stored report is one self-contained HTML document written by
# ``utils/html_builder.REPORT_TEMPLATE``: a ``<style>`` block, a
# ``.report-header`` (title + "Generated on …" line), a ``.section`` holding the
# statistics grid and per-channel table, then the LLM-written sections. The
# reader renders the chrome natively from ``title`` / ``statistics`` and needs
# only the written sections as HTML, so this module splits the document back
# into those parts. It is a reader of OUR template, not a general HTML
# parser: when the markers are missing (a hand-edited or future-format file)
# it falls back to the whole ``<body>`` so every stored report still opens.
# ---------------------------------------------------------------------------

# Label text in the statistics grid → key in the statistics dict passed to
# ``build_report_html``. Keep in sync with REPORT_TEMPLATE.
_STAT_LABELS = {
    "Videos Analyzed": "video_count",
    "Transcripts Fetched": "transcript_count",
    "Total Words": "total_words",
    "Total Minutes": "total_minutes",
}

_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_GENERATED_RE = re.compile(r"Generated on\s+(.*?)\s*\|", re.S)
_STAT_CARD_RE = re.compile(
    r'<div class="value">\s*(.*?)\s*</div>\s*<div class="label">\s*(.*?)\s*</div>', re.S
)
_CHANNEL_ROW_RE = re.compile(
    r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>", re.S
)
_BODY_RE = re.compile(r"<body[^>]*>(.*)</body>", re.S)


class _BlockLocator(HTMLParser):
    """Record the source span of the first element matching ``(tag, class)``.

    ``HTMLParser`` only reports (line, column) positions, so the spans are
    resolved back to absolute offsets through the line-start table.
    """

    def __init__(self, tag: str, css_class: str, source: str):
        super().__init__(convert_charrefs=False)
        self._tag = tag
        self._class = css_class
        self._depth: int | None = None
        self._stack = 0
        self.start: int | None = None
        self.end: int | None = None
        self._line_starts = [0]
        for m in re.finditer("\n", source):
            self._line_starts.append(m.end())

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def handle_starttag(self, tag, attrs):
        if tag != self._tag:
            return
        self._stack += 1
        if self.start is None and self._depth is None:
            classes = (dict(attrs).get("class") or "").split()
            if self._class in classes:
                self.start = self._offset()
                self._depth = self._stack

    def handle_endtag(self, tag):
        if tag != self._tag:
            return
        if self._depth is not None and self._stack == self._depth and self.end is None:
            self.end = self._offset() + len(f"</{tag}>")
        self._stack -= 1


def _locate(source: str, tag: str, css_class: str) -> tuple[int, int] | None:
    locator = _BlockLocator(tag, css_class, source)
    locator.feed(source)
    if locator.start is None or locator.end is None:
        return None
    return locator.start, locator.end


def _strip_tags(fragment: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()


def _as_int(text: str) -> int | None:
    digits = re.sub(r"[^\d-]", "", _strip_tags(text))
    try:
        return int(digits)
    except ValueError:
        return None


def _parse_statistics(section: str) -> dict | None:
    stats: dict = {}
    for value, label in _STAT_CARD_RE.findall(section):
        key = _STAT_LABELS.get(_strip_tags(label))
        if key:
            stats[key] = _as_int(value)
    if not stats:
        return None
    breakdown = []
    for name, videos, words, minutes in _CHANNEL_ROW_RE.findall(section):
        breakdown.append(
            {
                "channel_name": _strip_tags(name),
                "video_count": _as_int(videos),
                "word_count": _as_int(words),
                "minutes": _as_int(minutes),
            }
        )
    stats["channel_breakdown"] = breakdown
    return stats


def extract_report_body(document: str) -> dict:
    """Split a stored report into ``{title, html, statistics, generated_at}``.

    ``html`` is the LLM-written section markup with the template's header,
    statistics block and stylesheet removed — the reader sanitises it again
    client-side before rendering, so this function makes no safety promise.
    ``statistics`` is ``None`` when the grid is absent or unreadable.
    """
    title_m = _TITLE_RE.search(document) or _H1_RE.search(document)
    title = _strip_tags(title_m.group(1)) if title_m else "Report"

    generated_m = _GENERATED_RE.search(document)
    generated_at = generated_m.group(1).strip() if generated_m else None

    body_m = _BODY_RE.search(document)
    body = body_m.group(1) if body_m else document

    # Work inside the `.report` wrapper when present so the trailing
    # `</div>` of the wrapper does not end up in the output.
    report_span = _locate(body, "div", "report")
    if report_span:
        inner_start = body.index(">", report_span[0]) + 1
        inner_end = report_span[1] - len("</div>")
        content = body[inner_start:inner_end]
    else:
        content = body

    statistics = None
    header_span = _locate(content, "div", "report-header")
    if header_span:
        content = content[: header_span[0]] + content[header_span[1] :]

    section_span = _locate(content, "div", "section")
    if section_span:
        section = content[section_span[0] : section_span[1]]
        if "<h2>Statistics</h2>" in section:
            statistics = _parse_statistics(section)
            content = content[: section_span[0]] + content[section_span[1] :]

    return {
        "title": title,
        "html": content.strip(),
        "statistics": statistics,
        "generated_at": generated_at,
    }
