"""
Arranges rendered card SVGs onto Letter-size pages and saves a single
vector (non-rasterized) PDF, ready to print and cut out.

Uses svglib to convert each card's SVG into a reportlab Drawing, then
reportlab's canvas to place them in a grid -- the whole PDF stays vector,
so it prints crisp at any size and the file stays small.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas as pdfcanvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics import renderPDF
from reportlab.graphics.shapes import String
from svglib.svglib import svg2rlg

from .renderer import CARD_W, CARD_H, DPI, FONTS_DIR, FONT_REGULAR, FONT_BOLD

PAGE_W_PT, PAGE_H_PT = letter  # 612 x 792 (8.5in x 11in)
CARD_W_PT = CARD_W / DPI * 72
CARD_H_PT = CARD_H / DPI * 72

COLS = 3
ROWS = 3
GAP_PT = 5

_FONTS_REGISTERED = False


def _ensure_fonts_registered() -> None:
    """
    Register the bundled DejaVu Serif TTFs with reportlab under names that
    don't contain the substring "DejaVu" -- svglib has a hardcoded font
    substitution table that silently rewrites any "DejaVu*" font-family to
    Helvetica, which would otherwise make every card render sans-serif in
    the PDF despite the correct font being registered and referenced.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONTS_DIR / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONTS_DIR / "DejaVuSerif-Bold.ttf")))
    _FONTS_REGISTERED = True


def _force_fonts(node) -> None:
    """
    svglib doesn't render our SVG's <text> tags directly -- it parses the
    SVG and guesses a reportlab font name for each text element from its
    font-family string, using its own internal substitution table. That
    guess has proven unreliable across svglib/reportlab versions (it's
    what silently turned "DejaVu*" into Helvetica, and can misfire in
    other ways depending on the installed version). Rather than depend on
    that guess being right, we walk the parsed drawing afterwards and
    force every text object onto our own registered font, keeping only
    the bold/non-bold distinction svglib did correctly infer (reportlab's
    own substitute names always keep "Bold" in the name for bold text,
    e.g. "Helvetica-Bold", "Times-Bold").
    """
    if isinstance(node, String):
        node.fontName = FONT_BOLD if (node.fontName and "Bold" in node.fontName) else FONT_REGULAR
    for child in getattr(node, "contents", []):
        _force_fonts(child)


def _grid_origin() -> tuple[float, float]:
    grid_w = COLS * CARD_W_PT + (COLS - 1) * GAP_PT
    grid_h = ROWS * CARD_H_PT + (ROWS - 1) * GAP_PT
    if grid_w > PAGE_W_PT or grid_h > PAGE_H_PT:
        raise ValueError("Card grid does not fit on the page at the configured size.")
    return (PAGE_W_PT - grid_w) / 2, (PAGE_H_PT - grid_h) / 2


def _draw_cut_guides(c: pdfcanvas.Canvas, ox: float, oy: float) -> None:
    c.setStrokeColorRGB(0.78, 0.78, 0.78)
    c.setLineWidth(0.5)
    for col in range(COLS + 1):
        x = ox + col * (CARD_W_PT + GAP_PT) - (GAP_PT / 2 if 0 < col < COLS else 0)
        c.line(x, 0, x, oy)
        c.line(x, PAGE_H_PT - oy, x, PAGE_H_PT)
    for row in range(ROWS + 1):
        yy = oy + row * (CARD_H_PT + GAP_PT) - (GAP_PT / 2 if 0 < row < ROWS else 0)
        c.line(0, yy, ox, yy)
        c.line(PAGE_W_PT - ox, yy, PAGE_W_PT, yy)


def build_pdf(card_svgs: List[str], output_path: str | Path, copies: int = 1) -> Path:
    """
    Lay `card_svgs` (each a full SVG document string, CARD_W x CARD_H
    units) into a grid across as many Letter pages as needed, and save
    as a single vector PDF at `output_path`.
    """
    _ensure_fonts_registered()

    expanded: List[str] = []
    for svg in card_svgs:
        expanded.extend([svg] * copies)
    if not expanded:
        raise ValueError("No cards to lay out.")

    ox, oy = _grid_origin()
    per_page = COLS * ROWS

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    c = pdfcanvas.Canvas(str(output_path), pagesize=letter)

    with tempfile.TemporaryDirectory() as tmpdir:
        for page_start in range(0, len(expanded), per_page):
            chunk = expanded[page_start : page_start + per_page]
            _draw_cut_guides(c, ox, oy)
            for idx, svg in enumerate(chunk):
                col = idx % COLS
                row = idx // COLS
                tmp_path = Path(tmpdir) / f"card_{idx}.svg"
                tmp_path.write_text(svg, encoding="utf-8")
                drawing = svg2rlg(str(tmp_path))
                _force_fonts(drawing)
                x = ox + col * (CARD_W_PT + GAP_PT)
                y = PAGE_H_PT - oy - (row + 1) * CARD_H_PT - row * GAP_PT
                renderPDF.draw(drawing, c, x, y)
            c.showPage()

    c.save()
    return output_path
