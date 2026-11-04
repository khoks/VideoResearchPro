#!/usr/bin/env python3
"""Write the logo lockups from public/logo-mark.svg (T-2.8.2, T-2.8.4).

The mark is the master (D-112): its three arcs are read from logo-mark.svg, so
a lockup cannot drift from it. The two wordmarks of docs/branding.md section 3
are outlined, so no logo depends on an installed font:

    Devanagari  प्रतिध्वनि   Tiro Devanagari Hindi Regular
    Latin       pratidhvani  Fraunces Italic, opsz 14, wght 500, -0.01em

The Devanagari goes through HarfBuzz because mapping characters to glyphs one
by one breaks it: प + ् + र must become one conjunct and the vowel sign ि must
move in front of the consonant it follows in the text.

The output is committed, so nothing runs this at build time and neither the
fonts nor the shaper belong in requirements. To regenerate, in a scratch
directory (both fonts are SIL OFL 1.1, which does not reach artwork made with
them):

    python -m venv venv
    venv/Scripts/pip install uharfbuzz==0.57.0 fonttools==4.68.0 brotli==1.2.1
    npm pack @fontsource/tiro-devanagari-hindi@5.3.0 --ignore-scripts
    npm pack @fontsource-variable/fraunces@5.3.0 --ignore-scripts
    mkdir tiro fraunces
    tar -xzf fontsource-tiro-devanagari-hindi-5.3.0.tgz -C tiro
    tar -xzf fontsource-variable-fraunces-5.3.0.tgz -C fraunces
    venv/Scripts/python -I <repo>/frontend/scripts/outline-logos.py \
        --tiro tiro/package/files/tiro-devanagari-hindi-devanagari-400-normal.woff2 \
        --fraunces fraunces/package/files/fraunces-latin-full-italic.woff2

A run that changes a wordmark fails backend/tests/test_ci/test_brand_assets.py
until someone has rendered the result, read it and updated WORDMARK_SHA256 there.

Re-rendering the PNG app icons from the mark is a separate step: npm run icons.
"""
import argparse
import io
import math
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parents[2]
MASTER = REPO / "frontend" / "public" / "logo-mark.svg"
FAVICON = REPO / "frontend" / "public" / "favicon.svg"

DEVANAGARI = "प्रतिध्वनि"
# Section 3: "Set lowercase". The app's pages set Pratidhvani in tracked capitals
# instead; this file follows the brand document, which says it is the source.
LATIN = "pratidhvani"

# The run a correct shaper gives for DEVANAGARI in this font. A pin rather than
# a heuristic: a new font version that changes the run should be looked at.
DEVANAGARI_RUN = ["dPRa", "dSignI", "dTa", "dDhVa", "dSignI", "dNa"]

# Every axis, always. This file's default instance is opsz 9, wght 900, WONK 1,
# so an axis left out arrives as Black instead of raising anything. WONK changes
# nothing at opsz 14 (the font swaps to its plain d, h and v at low optical sizes
# either way); it is pinned so that a new opsz cannot bring the wonky forms in.
FRAUNCES_AXES = {"opsz": 14, "wght": 500, "SOFT": 0, "WONK": 0}
LATIN_TRACKING_EM = -0.01

# Tokens of docs/branding.md section 4 (frontend/src/theme.ts). The wordmark
# colours are the app's lockups': Devanagari in the accent, Latin in textSecondary.
THEMES = {
    "": {"mark": "#7a2c1a", "devanagari": "#7a2c1a", "latin": "#5c5448"},
    "-dark": {"mark": "#b04a2f", "devanagari": "#b04a2f", "latin": "#a89f93"},
}

# Layout, in the mark's own 64-unit space: the lockup keeps the mark at its
# master size, so its stroke widths are the master's numbers too.
HEIGHT = 64.0
MARK_INK = (18.25, 45.75)  # the arcs' ink, x, with the round caps and strokes
MARGIN = 7.25              # what the mark leaves above and below its own ink
MARK_TO_TEXT = 11.0
DEVANAGARI_SIZE = 33.0
LATIN_SIZE = 15.5
# The text block is exactly as tall as the mark's ink: the hooks of the vowel
# signs reach its top edge and the descender of p its bottom edge.
BLOCK_TOP = MARGIN
BLOCK_BOTTOM = HEIGHT - MARGIN


def fmt(value):
    return f"{value:.2f}".rstrip("0").rstrip(".")


def load_font(path):
    """A HarfBuzz font plus its glyph names. woff2 must become plain sfnt first."""
    source = TTFont(path)
    names = source.getGlyphOrder()
    source.flavor = None
    plain = io.BytesIO()
    source.save(plain)
    return hb.Font(hb.Face(plain.getvalue())), source, names


def shape(font, text, language=None):
    buffer = hb.Buffer()
    buffer.add_str(text)
    buffer.guess_segment_properties()
    if language:
        buffer.language = language
    hb.shape(font, buffer)
    return buffer


def placed_glyphs(font, buffer, size, tracking_em=0.0):
    """(glyph id, x, y) in em-scaled units, pen starting at 0, last gap dropped."""
    upem = font.face.upem
    scale = size / upem
    tracking = tracking_em * size
    pen_x = 0.0
    placed = []
    for info, position in zip(buffer.glyph_infos, buffer.glyph_positions):
        placed.append(
            (info.codepoint, pen_x + position.x_offset * scale, position.y_offset * scale)
        )
        pen_x += position.x_advance * scale + tracking
    return placed, scale


def ink_bounds(font, placed, scale):
    """Tight ink box of a run, y up. The glyphs are drawn at the shaped location."""
    box = None
    for gid, x, y in placed:
        pen = BoundsPen(None)
        font.draw_glyph_with_pen(gid, TransformPen(pen, (scale, 0, 0, scale, x, y)))
        if pen.bounds is None:
            continue
        left, bottom, right, top = pen.bounds
        box = (left, bottom, right, top) if box is None else (
            min(box[0], left), min(box[1], bottom), max(box[2], right), max(box[3], top)
        )
    return box


def outline(font, placed, scale, origin_x, baseline_y):
    """One path for a whole run: adjacent glyphs of the headline cannot seam."""
    pen = SVGPathPen(None, ntos=fmt)
    for gid, x, y in placed:
        font.draw_glyph_with_pen(
            gid,
            TransformPen(pen, (scale, 0, 0, -scale, origin_x + x, baseline_y - y)),
        )
    return pen.getCommands()


def check_devanagari(buffer, names):
    run = [names[info.codepoint] for info in buffer.glyph_infos]
    if run != DEVANAGARI_RUN:
        sys.exit(
            f"Devanagari shaped to {run}, expected {DEVANAGARI_RUN}. Refusing to "
            "write it: a wrong run is a wrong word. Look at it before updating the pin."
        )


def check_axes(source):
    """Fail on an axis the pin does not name: it would arrive at the file default."""
    axes = {axis.axisTag for axis in source["fvar"].axes}
    if axes != set(FRAUNCES_AXES):
        sys.exit(f"Fraunces has axes {sorted(axes)}, pinned {sorted(FRAUNCES_AXES)}.")


def read_mark():
    """The arcs of the master: path data, stroke width and opacity, in order."""
    root = ET.parse(MASTER).getroot()
    arcs = []
    for path in root.iter("{http://www.w3.org/2000/svg}path"):
        arcs.append(
            {
                "d": path.attrib["d"],
                "width": path.attrib["stroke-width"],
                "opacity": path.attrib.get("stroke-opacity"),
            }
        )
    if len(arcs) != 3:
        sys.exit(f"{MASTER} has {len(arcs)} paths, the echo mark has three.")
    return arcs


def arc_lines(arcs):
    lines = []
    for arc in arcs:
        opacity = f' stroke-opacity="{arc["opacity"]}"' if arc["opacity"] else ""
        lines.append(f'    <path d="{arc["d"]}" stroke-width="{arc["width"]}"{opacity}/>')
    return "\n".join(lines)


def mark_svg(arcs, colour):
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" '
        'aria-label="Pratidhvani">\n'
        "  <!-- The echo mark for dark backgrounds: logo-mark.svg's arcs in the\n"
        "       dark accent. Generated by frontend/scripts/outline-logos.py. -->\n"
        f'  <g fill="none" stroke="{colour}" stroke-linecap="round">\n'
        f"{arc_lines(arcs)}\n"
        "  </g>\n"
        "</svg>\n"
    )


def lockup_svg(arcs, theme, width, mark_shift, devanagari_d, latin_d):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {fmt(width)} {fmt(HEIGHT)}" '
        'role="img" aria-label="Pratidhvani">\n'
        "  <!-- Full lockup (docs/branding.md section 3): the echo mark, the\n"
        "       Devanagari wordmark, the Latin wordmark. The text is outlines, so\n"
        "       it needs no font. Generated by frontend/scripts/outline-logos.py\n"
        "       from logo-mark.svg; regenerate it rather than editing it. -->\n"
        f'  <g transform="translate({fmt(mark_shift)} 0)" fill="none" '
        f'stroke="{theme["mark"]}" stroke-linecap="round">\n'
        f"{arc_lines(arcs)}\n"
        "  </g>\n"
        f'  <path data-wordmark="devanagari" fill="{theme["devanagari"]}" d="{devanagari_d}"/>\n'
        f'  <path data-wordmark="latin" fill="{theme["latin"]}" d="{latin_d}"/>\n'
        "</svg>\n"
    )


def build(tiro_path, fraunces_path, out_root):
    tiro, _, tiro_names = load_font(tiro_path)
    fraunces, fraunces_source, _ = load_font(fraunces_path)
    check_axes(fraunces_source)
    fraunces.set_variations(FRAUNCES_AXES)

    shaped = shape(tiro, DEVANAGARI, language="hi")
    check_devanagari(shaped, tiro_names)
    dev_placed, dev_scale = placed_glyphs(tiro, shaped, DEVANAGARI_SIZE)
    lat_placed, lat_scale = placed_glyphs(
        fraunces, shape(fraunces, LATIN), LATIN_SIZE, LATIN_TRACKING_EM
    )
    dev_box = ink_bounds(tiro, dev_placed, dev_scale)
    lat_box = ink_bounds(fraunces, lat_placed, lat_scale)

    mark_shift = MARGIN - MARK_INK[0]
    text_x = MARK_INK[1] + mark_shift + MARK_TO_TEXT
    # Both wordmarks start on the same ink edge, whatever their side bearings.
    dev_origin = text_x - dev_box[0]
    lat_origin = text_x - lat_box[0]
    dev_baseline = BLOCK_TOP + dev_box[3]
    lat_baseline = BLOCK_BOTTOM + lat_box[1]
    width = math.ceil(text_x + max(dev_box[2] - dev_box[0], lat_box[2] - lat_box[0]) + MARGIN)

    devanagari_d = outline(tiro, dev_placed, dev_scale, dev_origin, dev_baseline)
    latin_d = outline(fraunces, lat_placed, lat_scale, lat_origin, lat_baseline)

    arcs = read_mark()
    frontend = out_root / "frontend" / "public"
    marketing = out_root / "marketing" / "public"
    frontend.mkdir(parents=True, exist_ok=True)
    marketing.mkdir(parents=True, exist_ok=True)

    for suffix, theme in THEMES.items():
        lockup = lockup_svg(arcs, theme, width, mark_shift, devanagari_d, latin_d)
        (frontend / f"logo-full{suffix}.svg").write_text(lockup, encoding="utf-8")
        (marketing / f"logo-full{suffix}.svg").write_text(lockup, encoding="utf-8")

    dark_mark = mark_svg(arcs, THEMES["-dark"]["mark"])
    (frontend / "logo-mark-dark.svg").write_text(dark_mark, encoding="utf-8")
    (marketing / "logo-mark-dark.svg").write_text(dark_mark, encoding="utf-8")
    shutil.copyfile(MASTER, marketing / "logo-mark.svg")
    shutil.copyfile(FAVICON, marketing / "favicon.svg")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--tiro", required=True, help="Tiro Devanagari Hindi Regular")
    parser.add_argument("--fraunces", required=True, help="Fraunces italic, all four axes")
    parser.add_argument("--out-root", type=Path, default=REPO, help="default: this repo")
    args = parser.parse_args()
    build(args.tiro, args.fraunces, args.out_root)


if __name__ == "__main__":
    main()
