"""S-1.14.17: the deterministic check that a composed section is finished."""

from html.parser import HTMLParser

import pytest

from app.utils import html_balance as hb

# The real defect, shortened: job 419e691d's "Cross-Video Conclusions"
# section stopped inside an href, and the next section followed it.
_CUT = (
    "<h2>Cross-Video Conclusions</h2>\n<ul>\n  <li><strong>Charts are instruments.</strong> "
    "CodeWithMunnaX's purpose-indexed plot list (<a href=\"https://www.youtube.com/watch?v=5"
)
_NEXT = (
    "\n<h2>Historical &amp; External References</h2>\n"
    "<p>Creators name a \"Kaggle dataset\" as the source.</p>\n<h3>External datasets</h3>"
)


class _StartTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def _start_tags(html: str) -> list[str]:
    parser = _StartTags()
    parser.feed(html)
    parser.close()
    return parser.tags


# --- truncated -------------------------------------------------------------

def test_a_section_cut_inside_an_attribute_value_is_truncated():
    found = hb.check(_CUT)
    assert not found.balanced
    assert found.truncated_tag and found.in_attribute
    assert _CUT[found.tail_start:].startswith("<a href=")
    assert found.open_tags == ("ul", "li")


@pytest.mark.parametrize("html", [
    "<h2>T</h2><p>The list continues <a",           # inside a tag name
    "<h2>T</h2><p>The list continues <a href=x",    # unquoted value, no ">"
    "<h2>T</h2><ul><li>last</li></ul",               # inside an end tag
    "<h2>T</h2><p>last</p><",                        # a lone "<" at the end
    "<h2>T</h2><p>last</p><!-- note",                # an unterminated comment
])
def test_text_ending_inside_any_tag_is_truncated(html):
    found = hb.check(html)
    assert found.truncated_tag and not found.balanced


def test_an_element_left_open_at_the_end_is_unbalanced():
    found = hb.check("<h2>T</h2><p>A paragraph cut mid sentence")
    assert not found.truncated_tag
    assert found.open_tags == ("p",)
    assert not found.balanced
    assert "open: p" in found.describe()


# --- balanced --------------------------------------------------------------

@pytest.mark.parametrize("html", [
    "",
    "plain text, no markup",
    "<h2>Key Facts</h2><h3>Theme</h3><p>One <strong>two</strong> (<a href=\"https://x/watch?v=a&t=5\" "
    "target=\"_blank\">0:05</a>).</p><ul><li>a</li><li>b</li></ul>",
    "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>",
    "<p>The ratio a < b holds; 3 <= 4.</p>",                  # "<" as text
    "<p title='it&#39;s'>don't</p>",                             # apostrophes
    "<!-- a comment --><p>x</p>",
])
def test_finished_html_is_balanced(html):
    assert hb.check(html).balanced
    assert hb.repair(html) == html


def test_optional_end_tags_are_closed_where_a_parser_closes_them():
    # A writer may omit </li>, </p> or </td>; that is finished HTML.
    assert hb.check("<ul><li>a<li>b</ul>").balanced
    assert hb.check("<p>a<p>b</p>").balanced
    assert hb.check("<p>a<ul><li>b</ul>").balanced
    assert hb.check("<table><tr><td>a<td>b<tr><td>c</table>").balanced
    assert hb.check("<dl><dt>a<dd>b<dt>c<dd>d</dl>").balanced


def test_void_and_self_closing_tags_open_nothing():
    assert hb.check("<p>line<br>line<br/>line<br /></p>").balanced
    assert hb.check("<p><img src=\"a.png\" alt=\"a\"><hr></p>").balanced
    assert hb.check("<p>x<wbr>y</p><col><input type=\"text\">").balanced
    assert hb.check("<div><span class=\"dot\"/></div>").balanced


def test_a_stray_end_tag_is_ignored_as_browsers_ignore_it():
    assert hb.check("<p>a</b></p></section>").balanced


def test_a_mis_nested_end_tag_closes_what_it_encloses():
    assert hb.check("<p><strong><em>x</strong></p>").balanced


# --- repair ----------------------------------------------------------------

def test_repair_cuts_the_unfinished_tag_and_closes_what_is_open():
    repaired = hb.repair(_CUT)
    assert repaired.endswith("purpose-indexed plot list (</li></ul>")
    assert "watch?v=5" not in repaired
    assert hb.check(repaired).balanced


def test_repair_closes_open_elements_innermost_first():
    assert hb.repair("<div><ul><li><a href=\"u\">x") == "<div><ul><li><a href=\"u\">x</a></li></ul></div>"
    assert hb.repair("<h2>T</h2><p>cut</p></ul") == "<h2>T</h2><p>cut</p>"


def test_after_repair_the_next_sections_headings_survive():
    """The point of the repair: the following section parses as markup."""
    tags = _start_tags(hb.repair(_CUT) + _NEXT)
    assert tags.count("h2") == 2
    assert "h3" in tags and "p" in tags
    assert hb.check(hb.repair(_CUT) + _NEXT).balanced
