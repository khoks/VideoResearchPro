"""The logos, read against what they are made from (T-2.8.2, T-2.8.4, D-112).

The artwork is generated once by frontend/scripts/outline-logos.py and committed,
and CI builds neither the marketing site nor the logos, so nothing else would
notice a hand edit, or a regeneration that lost the font outlines, the shaping or
the word itself. The fonts and the shaper are in no requirements file, so everything
here reads the committed SVG alone. A failure is artwork to regenerate, not a test
to relax.
"""
from __future__ import annotations

import hashlib
import re
import statistics
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "frontend" / "public"
SITE = ROOT / "marketing" / "public"
MASTER = APP / "logo-mark.svg"
NS = "{http://www.w3.org/2000/svg}"

LOCKUPS = ["logo-full.svg", "logo-full-dark.svg"]
LOGOS = [*LOCKUPS, "logo-mark.svg", "logo-mark-dark.svg"]
EVERY_LOGO = [APP / name for name in LOGOS] + [SITE / name for name in LOGOS]

# Anything that reaches outside the file or asks for a font at render time. The
# favicon's <style> is its dark branch (the media query), so it is not in this list.
NOT_SELF_CONTAINED = {
    "text", "tspan", "textPath", "font", "font-face", "style", "image", "use",
    "foreignObject", "script",
}
PATH_TOKEN = re.compile(r"[MLHVQCZ]|-?\d*\.?\d+")
PATH_ARGUMENTS = {"M": 2, "L": 2, "H": 1, "V": 1, "Q": 4, "C": 6, "Z": 0}
THEME_TOKEN = r"^\s*{name}:\s*\{{ light: '(#\w+)', dark: '(#\w+)' \}}"

# The outlines as generated and read by eye. Everything else here counts contours or
# measures boxes, which cannot tell a wrong consonant from the right one (प्रतिध्वति has
# the same 8 contours, and an ink box 0.1 wider) and do not look at the Latin's word,
# weight or size at all. After a deliberate regeneration, render the file and look at
# it (the shaper and the fonts are not here to check it), then update the pin.
WORDMARK_SHA256 = {
    "devanagari": "80f34651a2c089168823f5b30f697021952f1bc0aa911fd893238a0b5c30d8a7",
    "latin": "3ca3afb79875e8fc8de9dfb77ac1ff8c2bfb30b8911867eab522ee1f00387e44",
}


def _root(path: Path) -> ET.Element:
    return ET.parse(path).getroot()


def _token(name: str, mode: str) -> str:
    theme = (ROOT / "frontend" / "src" / "theme.ts").read_text(encoding="utf-8")
    match = re.search(THEME_TOKEN.format(name=name), theme, re.M)
    assert match, f"{name} is not in theme.ts"
    return match.group(1 if mode == "light" else 2)


def _arcs(path: Path) -> list[tuple[str, str, str | None]]:
    group = next(_root(path).iter(f"{NS}g"))
    return [
        (arc.attrib["d"], arc.attrib["stroke-width"], arc.attrib.get("stroke-opacity"))
        for arc in group.iter(f"{NS}path")
    ]


def _wordmark(path: Path, name: str) -> ET.Element:
    found = [el for el in _root(path).iter(f"{NS}path") if el.get("data-wordmark") == name]
    assert len(found) == 1, f"{path.name} should have one {name} wordmark path"
    return found[0]


def _contours(d: str) -> list[list[tuple[float, float]]]:
    """Each subpath's on-curve points. A wordmark is M, L, H, V, Q, C and Z only."""
    tokens = PATH_TOKEN.findall(d)
    contours: list[list[tuple[float, float]]] = []
    points: list[tuple[float, float]] = []
    x = y = 0.0
    index = 0
    command = ""
    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command == "Z":
                contours.append(points)
                points = []
                continue
        count = PATH_ARGUMENTS[command]
        values = [float(value) for value in tokens[index:index + count]]
        index += count
        if command == "H":
            x = values[0]
        elif command == "V":
            y = values[0]
        else:
            x, y = values[-2], values[-1]
        points.append((x, y))
    assert not points, "every contour of a glyph closes"
    return contours


def _box(contours: list[list[tuple[float, float]]]) -> tuple[float, float, float, float]:
    xs = [x for contour in contours for x, _ in contour]
    ys = [y for contour in contours for _, y in contour]
    return min(xs), min(ys), max(xs), max(ys)


def _public_files(page: str) -> list[str]:
    """The root-relative URLs that name a file. /pricing/ is a route, not a file."""
    urls = re.findall(r'\b(?:href|src)="/([^"/][^"]*)"', page)
    paths = [re.split(r"[?#]", url)[0] for url in urls]
    return [path for path in paths if "." in path.rsplit("/", 1)[-1]]


def test_a_url_counts_as_a_public_file_only_when_it_names_one() -> None:
    page = """
        <a href="/pricing/">Pricing</a> <a href="/about">About</a> <a href="/v1.2/">Old</a>
        <link href="/favicon.svg?v=2" /> <img src="/shots/app.png#top" />
    """
    assert _public_files(page) == ["favicon.svg", "shots/app.png"]


def test_the_marketing_layout_links_the_favicon_the_site_ships() -> None:
    linked = [
        path
        for page in (ROOT / "marketing" / "src").rglob("*.astro")
        for path in _public_files(page.read_text(encoding="utf-8"))
    ]
    assert "favicon.svg" in linked
    missing = [path for path in linked if not (SITE / path).is_file()]
    assert not missing, f"linked by a page, not in marketing/public: {missing}"


def test_the_site_and_the_app_ship_the_same_artwork() -> None:
    for name in [*LOGOS, "favicon.svg"]:
        site = (SITE / name).read_text(encoding="utf-8")
        assert site == (APP / name).read_text(encoding="utf-8"), name


@pytest.mark.parametrize("path", EVERY_LOGO, ids=lambda p: f"{p.parent.parent.name}-{p.name}")
def test_a_logo_needs_no_font_and_no_other_file(path: Path) -> None:
    root = _root(path)
    assert root.get("viewBox")
    elements = list(root.iter())
    assert not {el.tag.removeprefix(NS) for el in elements} & NOT_SELF_CONTAINED
    attributes = {name.rsplit("}", 1)[-1] for el in elements for name in el.attrib}
    assert not {name for name in attributes if name.startswith("font") or name == "href"}


@pytest.mark.parametrize(
    "path",
    [*EVERY_LOGO, APP / "favicon.svg", SITE / "favicon.svg"],
    ids=lambda p: f"{p.parent.parent.name}-{p.name}",
)
def test_every_logo_carries_the_masters_arcs(path: Path) -> None:
    assert len(_arcs(MASTER)) == 3
    assert _arcs(path) == _arcs(MASTER)


@pytest.mark.parametrize("name", LOCKUPS)
def test_a_lockup_keeps_the_mark_at_its_master_size(name: str) -> None:
    group = next(_root(APP / name).iter(f"{NS}g"))
    assert re.fullmatch(r"translate\(-?[\d.]+ 0\)", group.get("transform", ""))
    assert _root(APP / name).get("viewBox").split()[3] == _root(MASTER).get("viewBox").split()[3]


@pytest.mark.parametrize(
    ("name", "mode"), [("logo-full.svg", "light"), ("logo-full-dark.svg", "dark")]
)
def test_a_lockup_wears_the_brand_tokens(name: str, mode: str) -> None:
    group = next(_root(APP / name).iter(f"{NS}g"))
    assert group.get("stroke") == _token("accent", mode)
    assert _wordmark(APP / name, "devanagari").get("fill") == _token("accent", mode)
    assert _wordmark(APP / name, "latin").get("fill") == _token("textSecondary", mode)


@pytest.mark.parametrize(
    ("name", "mode"), [("logo-mark.svg", "light"), ("logo-mark-dark.svg", "dark")]
)
def test_a_mark_wears_the_accent_token(name: str, mode: str) -> None:
    assert next(_root(APP / name).iter(f"{NS}g")).get("stroke") == _token("accent", mode)


def test_the_dark_lockup_is_the_same_drawing() -> None:
    light, dark = (APP / "logo-full.svg"), (APP / "logo-full-dark.svg")
    assert _root(light).get("viewBox") == _root(dark).get("viewBox")
    for word in ("devanagari", "latin"):
        assert _wordmark(light, word).get("d") == _wordmark(dark, word).get("d")


@pytest.mark.parametrize("word", WORDMARK_SHA256)
def test_a_wordmark_is_the_outline_that_was_read(word: str) -> None:
    """One lockup is enough: the dark one and the site's copies are held to it above."""
    outline = _wordmark(APP / "logo-full.svg", word).get("d")
    assert hashlib.sha256(outline.encode()).hexdigest() == WORDMARK_SHA256[word]


@pytest.mark.parametrize("name", LOCKUPS)
def test_the_lockup_fits_its_box_and_the_wordmarks_share_a_left_edge(name: str) -> None:
    _, _, width, height = (float(value) for value in _root(APP / name).get("viewBox").split())
    devanagari = _box(_contours(_wordmark(APP / name, "devanagari").get("d")))
    latin = _box(_contours(_wordmark(APP / name, "latin").get("d")))
    for left, top, right, bottom in (devanagari, latin):
        assert 0 < left and right < width and 0 < top and bottom < height
    assert abs(devanagari[0] - latin[0]) < 0.1
    assert devanagari[3] < latin[1], "the Latin line sits under the Devanagari"
    mark_right = 21 + 22 + 5.5 / 2 + float(
        re.search(r"-?[\d.]+", next(_root(APP / name).iter(f"{NS}g")).get("transform")).group()
    )
    assert mark_right < devanagari[0], "the wordmarks clear the mark"


@pytest.mark.parametrize("name", LOCKUPS)
def test_the_devanagari_is_shaped_not_mapped_character_by_character(name: str) -> None:
    """The word's signature, in outlines. Mapped one by one it has 12 contours, with
    two halants floating under the word and a vowel sign as its last contour."""
    contours = _contours(_wordmark(APP / name, "devanagari").get("d"))
    boxes = sorted(_box([contour]) for contour in contours)
    _, top, _, bottom = _box(contours)

    # Six glyphs (प्र ि त ध्व ि न) plus the counters of प्र and ध्व.
    assert len(contours) == 8

    # A vowel sign is the only contour rising above the headline, so its place in
    # left-to-right order is where it landed. Both stand BEFORE their consonant.
    rises = [i for i, box in enumerate(boxes) if box[1] - top < 0.2 * (bottom - top)]
    assert rises == [2, 6]

    # प्र and ध्व are conjuncts: no halant left hanging under the word. Measured
    # from the line the glyph bodies stand on, not from the word's own bottom,
    # which a hanging mark moves down and so hides itself from.
    baseline = statistics.median(box[3] for box in boxes)
    assert not [box for box in boxes if box[1] - top > 0.9 * (baseline - top)]


def test_the_inventory_names_every_file_it_lists() -> None:
    text = (ROOT / "docs" / "branding.md").read_text(encoding="utf-8")
    inventory = text[text.index("## 8. Asset inventory"):text.index("## 9. Cross-references")]
    listed = re.findall(r"`((?:frontend|marketing)/public/[\w.-]+)`", inventory)
    for name in LOGOS:
        assert f"frontend/public/{name}" in listed
        assert f"marketing/public/{name}" in listed
    assert "marketing/public/favicon.svg" in listed
    missing = [path for path in listed if not (ROOT / path).is_file()]
    # og.png waits for M11 (T-2.8.3, D-112); it is the only row with no file yet.
    assert missing == ["frontend/public/og.png"]
