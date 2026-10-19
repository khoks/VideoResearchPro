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
    """Delete a report file from disk, and its cached Markdown source (S-6.1.2)."""
    deleted = False
    if report_path and os.path.exists(report_path):
        os.remove(report_path)
        deleted = True
    md_path = markdown_path_for(report_path) if report_path else ""
    if md_path and os.path.exists(md_path):
        try:
            os.remove(md_path)
        except OSError:
            logger.warning("report_service: could not remove cached Markdown %s", md_path)
    return deleted


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


# ---------------------------------------------------------------------------
# S-6.1.2: the report's Markdown source.
#
# Until 2026-10-19 a report existed only as the HTML file above; the book
# outputter stripped tags with a regex, losing heading levels, tables and
# every `&t=` citation link. `report_markdown(job)` converts the stored HTML
# with a small `markdownify` subclass and caches the result beside it at
# `<report_path>.md`. The book (E-6.1), the site's text index (E-6.2), the
# newsletter's plain-text part (E-6.4) and `GET /jobs/{id}/report.md` read it.
#
# markdownify (MIT) consumes the HTML we already store, keeps hrefs verbatim
# (so `&t=SECONDS` deep links survive), converts tables and exposes per-tag
# hooks. html2text is GPL-3.0; trafilatura's Markdown mode is a boilerplate
# stripper and drops report content (docs/plans/l2-author-studio.md).
#
# Beyond markdownify's defaults the converter drops <head>/<style>/<script>
# (its `strip` option keeps a stripped tag's TEXT, so the stylesheet would
# lead the file), uses ATX headings and hyphen bullets, escapes no `*`/`_`
# (the text is prose), never autolinks (a citation whose text equals its
# href must stay `[text](href)`), and turns the statistics grid into a
# one-row table. `[VISUAL @ mm:ss - …]` spans (D-067) are plain text and pass
# through verbatim. This is independent of `extract_report_body` above on
# purpose: the reader needs the template's parts, the Markdown needs the
# whole document, and only the grid is template-specific here.
# ---------------------------------------------------------------------------

from bs4 import BeautifulSoup  # noqa: E402  (markdownify's own dependency)
from markdownify import MarkdownConverter  # noqa: E402

MARKDOWN_SUFFIX = ".md"


def markdown_path_for(report_path: str) -> str:
    """Where the Markdown source of ``report_path`` is cached."""
    return report_path + MARKDOWN_SUFFIX

class ReportMarkdownConverter(MarkdownConverter):
    """markdownify tuned for the report template (``utils/html_builder``)."""

    _DEFAULTS = {
        "heading_style": "atx",
        "bullets": "-",
        "autolinks": False,
        "escape_asterisks": False,
        "escape_underscores": False,
        "escape_misc": False,
    }

    def __init__(self, **options):
        super().__init__(**{**self._DEFAULTS, **options})

    def convert_div(self, el, text, parent_tags):
        classes = el.get("class") or []
        if "stat-grid" in classes:
            cards = []
            for card in el.select(".stat-card"):
                label = card.select_one(".label")
                value = card.select_one(".value")
                if label is not None and value is not None:
                    cards.append((label.get_text(strip=True), value.get_text(strip=True)))
            if cards:
                head = "| " + " | ".join(_cell(label) for label, _ in cards) + " |"
                sep = "|" + " --- |" * len(cards)
                row = "| " + " | ".join(_cell(value) for _, value in cards) + " |"
                return "\n\n" + "\n".join([head, sep, row]) + "\n\n"
        return super().convert_div(el, text, parent_tags)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


_DROP_TAGS = ("head", "title", "meta", "link", "style", "script")


def html_to_markdown(html: str) -> str:
    """Convert a stored report (or any HTML fragment) to Markdown.

    Deterministic: the same HTML always yields the same text. The report
    chrome (stylesheet, document head) is removed before conversion; the
    content root is ``div.report`` when present, else ``<body>``, else the
    whole fragment.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup.find_all(list(_DROP_TAGS)):
        tag.decompose()
    root = soup.select_one("div.report") or soup.body or soup
    md = ReportMarkdownConverter().convert_soup(root)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md + "\n" if md else ""


def _cache_is_fresh(md_path: str, html_path: str) -> bool:
    try:
        return os.path.getmtime(md_path) >= os.path.getmtime(html_path)
    except OSError:
        return False


def report_markdown(job, *, force: bool = False) -> str | None:
    """The Markdown source of ``job``'s report, cached at ``<report_path>.md``.

    Returns ``None`` when the job has no report or its HTML file is missing
    (the same two 404 cases the HTML route distinguishes). The cache is
    rewritten when absent, older than the HTML, or ``force`` is set. A cache
    write that fails is logged and the Markdown is still returned, so a
    read-only reports directory degrades to "convert every time", never to
    an error.
    """
    report_path = getattr(job, "report_path", None)
    if not report_path:
        return None
    html = get_report_html(report_path)
    if html is None:
        return None

    md_path = markdown_path_for(report_path)
    if not force and _cache_is_fresh(md_path, report_path):
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                return f.read()
        except OSError:
            logger.warning("report_service: cached Markdown %s unreadable; regenerating", md_path)

    md = html_to_markdown(html)
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
    except OSError as e:
        logger.warning("report_service: could not cache Markdown at %s (%s)", md_path, e)
    return md
