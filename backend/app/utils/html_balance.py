"""Is a composed HTML fragment finished? (S-1.14.17)

Each report section is one LLM call whose HTML is concatenated with the
others. A section the writer stopped in the middle of a tag poisons the ones
after it: the stored report for job ``419e691d`` ended a section inside
``<a href="https://www.youtube.com/watch?v=5``, so every parser read the next
section's ``<h2>`` and ``<h3>`` as part of that attribute value and two
headings vanished from the outline, the iframe and the reader alike.

``check`` answers one question deterministically: does the fragment end
inside a tag, attribute value or comment, and which elements does it leave
open? ``repair`` cuts the unfinished tag and closes what is open, so nothing
leaks into the next section. Neither is an HTML5 conformance checker:

- Elements whose end tag HTML makes optional (``p``, ``li``, ``td`` ...) are
  closed implicitly where a parser would close them (``<li>a<li>b</ul>`` is
  balanced), but one still open when the fragment ENDS counts as open: a
  section cut mid-paragraph is exactly the truncation being looked for.
- Void elements never open, and ``<x/>`` is treated as self-contained.
- A stray end tag is ignored, as browsers ignore it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "param", "source", "track", "wbr",
})

# Contents are text up to the matching end tag. The compose prompt forbids
# script and style; they are handled so a stray one cannot derail the scan.
_RAW_TEXT_ELEMENTS = frozenset({"script", "style", "textarea", "title"})

# A start tag of any of these closes an open <p> (WHATWG "close a p element").
_CLOSES_P = frozenset({
    "address", "article", "aside", "blockquote", "details", "dialog", "div", "dl",
    "dd", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hgroup", "hr", "li", "main", "menu", "nav",
    "ol", "p", "pre", "section", "summary", "table", "ul",
})

# Start tag -> open elements it implicitly ends (optional end tags).
_IMPLIED_END = {
    "li": frozenset({"li"}),
    "dt": frozenset({"dt", "dd"}),
    "dd": frozenset({"dt", "dd"}),
    "tr": frozenset({"tr", "td", "th"}),
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "thead": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    "tbody": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    "tfoot": frozenset({"thead", "tbody", "tfoot", "tr", "td", "th"}),
    "option": frozenset({"option"}),
    # A heading start tag ends a heading that is the current node.
    **{h: frozenset({"h1", "h2", "h3", "h4", "h5", "h6"}) for h in ("h1", "h2", "h3", "h4", "h5", "h6")},
}

_TAG_OPEN = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")
_WHITESPACE = " \t\n\r\f"


@dataclass(frozen=True)
class Balance:
    """What ``check`` found.

    ``tail_start`` is the offset of the unfinished tag when ``truncated_tag``;
    ``open_tags`` lists the elements still open, outermost first.
    """

    truncated_tag: bool = False
    in_attribute: bool = False
    tail_start: int | None = None
    open_tags: tuple[str, ...] = ()

    @property
    def balanced(self) -> bool:
        return not self.truncated_tag and not self.open_tags

    def describe(self) -> str:
        if self.balanced:
            return "balanced"
        parts = []
        if self.truncated_tag:
            parts.append(
                "ends inside an attribute value" if self.in_attribute else "ends inside a tag"
            )
        if self.open_tags:
            parts.append(f"leaves {len(self.open_tags)} element(s) open: {', '.join(self.open_tags)}")
        return "; ".join(parts)


def _end_of_tag(html: str, pos: int) -> tuple[int | None, bool]:
    """Index of the ``>`` ending the tag whose name ends at ``pos``.

    ``(None, in_attribute)`` when the text runs out first. A quote only opens
    an attribute value right after ``=`` (as in the HTML tokenizer), so a
    stray apostrophe elsewhere in a tag cannot swallow the rest of the text.
    """
    n = len(html)
    j = pos
    while j < n:
        ch = html[j]
        if ch == ">":
            return j, False
        if ch == "=":
            j += 1
            while j < n and html[j] in _WHITESPACE:
                j += 1
            if j < n and html[j] in "\"'":
                close = html.find(html[j], j + 1)
                if close == -1:
                    return None, True
                j = close + 1
            continue
        j += 1
    return None, False


def _open(stack: list[str], name: str) -> None:
    while stack:
        top = stack[-1]
        if (top == "p" and name in _CLOSES_P) or top in _IMPLIED_END.get(name, ()):
            stack.pop()
            continue
        break
    stack.append(name)


def check(html: str) -> Balance:
    """Scan ``html`` once and report how it ends (see the module docstring)."""
    text = html or ""
    stack: list[str] = []
    i = 0
    while True:
        lt = text.find("<", i)
        if lt == -1:
            break
        if text.startswith("<!--", lt):
            end = text.find("-->", lt + 4)
            if end == -1:
                return Balance(truncated_tag=True, tail_start=lt, open_tags=tuple(stack))
            i = end + 3
            continue
        nxt = text[lt + 1:lt + 2]
        if nxt in ("!", "?"):
            end = text.find(">", lt + 2)
            if end == -1:
                return Balance(truncated_tag=True, tail_start=lt, open_tags=tuple(stack))
            i = end + 1
            continue
        m = _TAG_OPEN.match(text, lt)
        if not m:
            # "<" or "</" with nothing after it is a tag the writer never
            # finished; "a < b" is just text.
            if text[lt:].rstrip() in ("<", "</"):
                return Balance(truncated_tag=True, tail_start=lt, open_tags=tuple(stack))
            i = lt + 1
            continue
        end, in_attribute = _end_of_tag(text, m.end())
        if end is None:
            return Balance(
                truncated_tag=True, in_attribute=in_attribute, tail_start=lt, open_tags=tuple(stack),
            )
        closing, name = m.group(1) == "/", m.group(2).lower()
        i = end + 1
        if closing:
            if name in stack:
                while stack.pop() != name:
                    pass
            continue
        if name in VOID_ELEMENTS or text[end - 1] == "/":
            continue
        _open(stack, name)
        if name in _RAW_TEXT_ELEMENTS:
            close = re.compile(rf"</{name}\s*>", re.I).search(text, i)
            if close is None:
                break
            stack.pop()
            i = close.end()
    return Balance(open_tags=tuple(stack))


def repair(html: str) -> str:
    """``html`` cut before any unfinished tag, with every open element closed.

    Balanced input is returned unchanged. The cut drops the half-written tag
    (and so a half-written link); text before it is kept.
    """
    found = check(html)
    if found.balanced:
        return html
    body = html[: found.tail_start] if found.truncated_tag else html
    return body.rstrip() + "".join(f"</{name}>" for name in reversed(found.open_tags))
