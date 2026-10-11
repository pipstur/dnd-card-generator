"""
Renders SpellCard / ItemCard objects as standalone SVG markup.

SVG instead of raster: crisp at any zoom, editable in a vector editor
(Inkscape, Illustrator, Figma), and each card is a single self-contained
file (custom PNG icons are embedded as base64 data URIs, so nothing else
needs to ship alongside the .svg).

Text layout (wrapping / auto-shrink-to-fit) is computed with Pillow's
font metrics -- Pillow is only used to *measure* text here, nothing is
rasterized. The bundled DejaVu Serif fonts are referenced by name
("DejaVu Serif") so a browser with that font installed renders them
correctly; card_layout.py separately registers the same TTFs with
reportlab so the printable PDF always renders correctly regardless of
what's installed on the machine running this script.
"""

from __future__ import annotations

import base64
import io
import math
import sys
from pathlib import Path
from typing import List, Tuple, Callable, Optional

from PIL import Image, ImageFont, ImageOps

from .models import SpellCard, ItemCard

# ---------------------------------------------------------------------------
# Card geometry -- poker size (2.5in x 3.5in). Coordinates are in an
# arbitrary "unit" space (750 x 1050, i.e. 300 units/inch) purely so the
# numbers match the project's original raster version; the SVG's real
# physical size is declared in points via width/height, with this space
# mapped onto it by viewBox.
# ---------------------------------------------------------------------------
DPI = 300
CARD_W = int(2.5 * DPI)  # 750
CARD_H = int(3.5 * DPI)  # 1050

MARGIN = 30
BORDER_THICKNESS = 16
CORNER_RADIUS = 28

FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
SERIF = FONTS_DIR / "DejaVuSerif.ttf"
SERIF_BOLD = FONTS_DIR / "DejaVuSerif-Bold.ttf"
FONT_REGULAR = "DnDSerif"  # names deliberately avoid "DejaVu" -- svglib has a
FONT_BOLD = "DnDSerifBold"  # built-in substitution that silently swaps that
# string for Helvetica; see card_layout.py registration.
# (These are referenced by name, not embedded, to keep
# each .svg small -- card_layout.py registers the same
# TTFs with reportlab so the PDF always renders correctly
# regardless of what fonts are installed on the machine;
# a raw .svg opened in a browser without this font
# installed will fall back to the browser's default serif.)

ICONS_DIR = Path(__file__).resolve().parent.parent / "assets" / "icons"

BG_PARCHMENT = (247, 241, 224)
TEXT_DARK = (35, 30, 25)
TEXT_ON_HEADER = (255, 255, 255)
BLACK = (0, 0, 0)

SPELL_SCHOOL_COLORS = {
    "abjuration": (74, 144, 217),
    "conjuration": (245, 166, 35),
    "divination": (189, 16, 224),
    "enchantment": (233, 30, 140),
    "evocation": (208, 2, 27),
    "illusion": (86, 180, 190),
    "necromancy": (60, 55, 55),
    "transmutation": (122, 193, 66),
}
DEFAULT_SPELL_COLOR = (90, 90, 90)

RARITY_COLORS = {
    "common": (141, 141, 141),
    "uncommon": (61, 139, 55),
    "rare": (31, 111, 178),
    "very rare": (125, 60, 152),
    "legendary": (212, 136, 26),
    "artifact": (192, 57, 43),
}
DEFAULT_RARITY_COLOR = (110, 90, 60)

_ATTUNE_ROW_W = 122
_ATTUNE_H = 38


# ---------------------------------------------------------------------------
# Minimal SVG builder
# ---------------------------------------------------------------------------


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _col(c) -> str:
    if isinstance(c, str):
        return c
    return f"rgb({c[0]},{c[1]},{c[2]})"


class SVGDoc:
    def __init__(self, w: int, h: int):
        self.w = w
        self.h = h
        self.body: List[str] = []
        self.defs: List[str] = []
        self._n = 0

    def uid(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"

    def add(self, s: str) -> None:
        self.body.append(s)

    def add_def(self, s: str) -> None:
        self.defs.append(s)

    # -- shape helpers -------------------------------------------------
    def rect(self, x, y, w, h, rx=0, fill="none", stroke="none", sw=0):
        self.add(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx:.2f}" '
            f'fill="{_col(fill)}" stroke="{_col(stroke)}" stroke-width="{sw}"/>'
        )

    def circle(self, cx, cy, r, fill="none", stroke="none", sw=0):
        self.add(
            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
            f'fill="{_col(fill)}" stroke="{_col(stroke)}" stroke-width="{sw}"/>'
        )

    def line(self, x1, y1, x2, y2, stroke, sw):
        self.add(
            f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
            f'stroke="{_col(stroke)}" stroke-width="{sw}" stroke-linecap="round"/>'
        )

    def polygon(self, pts, fill="none", stroke="none", sw=0):
        p = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        self.add(
            f'<polygon points="{p}" fill="{_col(fill)}" stroke="{_col(stroke)}" stroke-width="{sw}"/>'
        )

    def text(self, x, y, s, size, fill, anchor="start", bold=False):
        fam = FONT_BOLD if bold else FONT_REGULAR
        self.add(
            f'<text x="{x:.2f}" y="{y:.2f}" font-family="{fam}" font-size="{size}" '
            f'fill="{_col(fill)}" text-anchor="{anchor}">{_esc(s)}</text>'
        )

    def image(self, x, y, w, h, href, clip_id=None):
        clip = f' clip-path="url(#{clip_id})"' if clip_id else ""
        self.add(
            f'<image x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" href="{href}"{clip}/>'
        )

    def rounded_clip(self, x, y, w, h, rx) -> str:
        cid = self.uid("clip")
        self.add_def(
            f'<clipPath id="{cid}"><rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" rx="{rx:.2f}"/></clipPath>'
        )
        return cid

    def render(self) -> str:
        w_pt = self.w / DPI * 72
        h_pt = self.h / DPI * 72
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'width="{w_pt:.2f}pt" height="{h_pt:.2f}pt" viewBox="0 0 {self.w} {self.h}">'
            f'{defs}{"".join(self.body)}</svg>'
        )


# ---------------------------------------------------------------------------
# Text measurement (Pillow font metrics only -- nothing is rasterized)
# ---------------------------------------------------------------------------
_FONT_CACHE: dict = {}


def _pil_font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    key = (bold, size)
    if key not in _FONT_CACHE:
        _FONT_CACHE[key] = ImageFont.truetype(str(SERIF_BOLD if bold else SERIF), size)
    return _FONT_CACHE[key]


def _text_width(s: str, bold: bool, size: int) -> float:
    return _pil_font(bold, size).getlength(s)


def _baseline_for_center(cy: float, bold: bool, size: int) -> float:
    """Approximate y so text vertically centers on cy (SVG has no built-in middle baseline we can rely on cross-renderer)."""
    ascent, descent = _pil_font(bold, size).getmetrics()
    return cy + (ascent - descent) / 2


def _wrap_text(text: str, bold: bool, size: int, max_width: int) -> List[str]:
    lines: List[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split(" ")
        current = ""
        for word in words:
            trial = f"{current} {word}".strip()
            if _text_width(trial, bold, size) <= max_width or not current:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def _fit_body_text(
    text: str, max_width: int, max_height: int, start_size: int = 30, min_size: int = 14
) -> Tuple[List[str], int, int]:
    size = start_size
    while size >= min_size:
        lines = _wrap_text(text, False, size, max_width)
        line_height = int(size * 1.32)
        if line_height * len(lines) <= max_height:
            return lines, size, line_height
        size -= 1
    lines = _wrap_text(text, False, min_size, max_width)
    return lines, min_size, int(min_size * 1.32)


def _fit_stat_value(
    text: str, max_width: int, start_size: int = 17, min_size: int = 12, max_lines: int = 2
) -> Tuple[List[str], int]:
    size = start_size
    while size >= min_size:
        lines = _wrap_text(text, False, size, max_width)
        if len(lines) <= max_lines:
            return lines, size
        size -= 1
    lines = _wrap_text(text, False, min_size, max_width)
    return lines[:max_lines], min_size


def _fit_centered(
    text: str, bold: bool, start_size: int, max_width: int, min_size: int = 14
) -> int:
    size = start_size
    while _text_width(text, bold, size) > max_width and size > min_size:
        size -= 2
    return size


def _draw_centered_text(
    doc: SVGDoc,
    text: str,
    bold: bool,
    size: int,
    x0: float,
    x1: float,
    y_center: float,
    fill,
    max_width: float,
) -> None:
    fitted_size = _fit_centered(text, bold, size, max_width)
    y = _baseline_for_center(y_center, bold, fitted_size)
    doc.text((x0 + x1) / 2, y, text, fitted_size, fill, anchor="middle", bold=bold)


def _draw_justified_line(
    doc: SVGDoc, words: List[str], x0: float, width: float, y: float, size: int, fill
) -> None:
    """Stretches word spacing so the line's words span exactly `width`."""
    if len(words) <= 1:
        doc.text(x0, y, " ".join(words), size, fill)
        return
    word_widths = [_text_width(w, False, size) for w in words]
    space_w = _text_width(" ", False, size)
    natural = sum(word_widths) + space_w * (len(words) - 1)
    extra = max(0.0, width - natural)
    gap = space_w + extra / (len(words) - 1)
    cx = x0
    for i, w in enumerate(words):
        doc.text(cx, y, w, size, fill)
        cx += word_widths[i] + gap


def _draw_body_paragraph(
    doc: SVGDoc,
    text: str,
    x0: float,
    width: float,
    y: float,
    max_height: int,
    start_size: int = 30,
    min_size: int = 14,
    justify: bool = True,
) -> float:
    """
    Wraps+auto-shrinks `text` to fit, then draws it. Every line except the
    last is justified (word spacing stretched to fill `width`) when
    `justify` is True, matching normal printed-paragraph style.
    """
    lines, size, line_h = _fit_body_text(text, int(width), max_height, start_size, min_size)
    for i, line in enumerate(lines):
        baseline_y = y + size
        words = line.split(" ")
        is_last = i == len(lines) - 1
        if justify and not is_last and len(words) > 1:
            _draw_justified_line(doc, words, x0, width, baseline_y, size, TEXT_DARK)
        else:
            doc.text(x0, baseline_y, line, size, TEXT_DARK)
        y += line_h
    return y


# ---------------------------------------------------------------------------
# Item card widgets -- icon box, field boxes, hex price tag, attunement
# checkboxes, decorative bottom border.
# ---------------------------------------------------------------------------


def _star_points(cx, cy, r, points=5) -> List[Tuple[float, float]]:
    angle = -math.pi / 2
    pts = []
    for i in range(points * 2):
        rad = r if i % 2 == 0 else r * 0.45
        a = angle + i * math.pi / points
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    return pts


def _icon_weapon(doc, cx, cy, r, color):
    w = max(2, int(r * 0.13))
    x1, y1 = cx - r * 0.62, cy + r * 0.62
    x2, y2 = cx + r * 0.62, cy - r * 0.62
    doc.line(x1, y1, x2, y2, color, w)
    t = 0.22
    px, py = x1 + (x2 - x1) * t, y1 + (y2 - y1) * t
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    ux, uy = -dy / length, dx / length
    guard = r * 0.3
    doc.line(
        px - ux * guard,
        py - uy * guard,
        px + ux * guard,
        py + uy * guard,
        color,
        max(2, int(r * 0.14)),
    )
    doc.circle(x1, y1, r * 0.11, fill=color)


def _icon_potion(doc, cx, cy, r, color):
    w = max(2, int(r * 0.16))
    neck_w, neck_h = r * 0.32, r * 0.32
    body_w, body_h = r * 1.1, r * 0.85
    top_y = cy - r * 0.55
    doc.rect(cx - neck_w / 2, top_y, neck_w, neck_h, stroke=color, sw=w)
    body_top = top_y + neck_h - 2
    doc.rect(cx - body_w / 2, body_top, body_w, body_h, rx=r * 0.25, stroke=color, sw=w)


def _icon_ring(doc, cx, cy, r, color):
    w = max(2, int(r * 0.26))
    doc.circle(cx, cy, r * 0.6, stroke=color, sw=w)


def _icon_wand(doc, cx, cy, r, color):
    w = max(2, int(r * 0.18))
    x1, y1 = cx - r * 0.55, cy + r * 0.55
    x2, y2 = cx + r * 0.55, cy - r * 0.55
    doc.line(x1, y1, x2, y2, color, w)
    doc.polygon(_star_points(x2, y2, r * 0.3), stroke=color, sw=max(2, int(r * 0.12)))


def _icon_armor(doc, cx, cy, r, color):
    w = max(2, int(r * 0.16))
    pts = [
        (cx - r * 0.55, cy - r * 0.5),
        (cx + r * 0.55, cy - r * 0.5),
        (cx + r * 0.55, cy + r * 0.05),
        (cx, cy + r * 0.65),
        (cx - r * 0.55, cy + r * 0.05),
    ]
    doc.polygon(pts, stroke=color, sw=w)


def _icon_scroll(doc, cx, cy, r, color):
    w = max(2, int(r * 0.15))
    rect_w, rect_h = r * 1.2, r * 0.6
    doc.rect(cx - rect_w / 2, cy - rect_h / 2, rect_w, rect_h, stroke=color, sw=w)
    roll_r = rect_h * 0.55
    doc.circle(cx - rect_w / 2, cy, roll_r, stroke=color, sw=w)
    doc.circle(cx + rect_w / 2, cy, roll_r, stroke=color, sw=w)


def _icon_wondrous(doc, cx, cy, r, color):
    doc.polygon(_star_points(cx, cy, r * 0.62), stroke=color, sw=max(2, int(r * 0.13)))


ICON_DRAWERS: dict[str, Callable] = {
    "weapon": _icon_weapon,
    "sword": _icon_weapon,
    "potion": _icon_potion,
    "ring": _icon_ring,
    "wand": _icon_wand,
    "staff": _icon_wand,
    "armor": _icon_armor,
    "shield": _icon_armor,
    "scroll": _icon_scroll,
    "wondrous": _icon_wondrous,
}


def _resolve_icon_path(icon_image: str, card_name: str = "") -> Optional[Path]:
    candidates = [Path(icon_image), ICONS_DIR / icon_image, Path.cwd() / icon_image]
    for c in candidates:
        if c.is_file():
            return c
    tried = ", ".join(str(c) for c in candidates)
    print(
        f"[icon_image] '{icon_image}' for '{card_name}' not found -- tried: {tried}",
        file=sys.stderr,
    )
    return None


def _icon_image_data_uri(path: Path, size: int, bg=BG_PARCHMENT) -> str:
    """
    Center-crop/fit the PNG to a size x size square and flatten any
    transparency onto `bg` (some SVG-to-PDF renderers render alpha as
    solid black instead of see-through, so we flatten ourselves rather
    than relying on the renderer to composite correctly), then return a
    base64 data: URI -- keeps the SVG a single self-contained file.
    """
    im = Image.open(path).convert("RGBA")
    im = ImageOps.fit(im, (size, size), method=Image.LANCZOS)
    flat = Image.new("RGBA", im.size, (*bg, 255))
    flat = Image.alpha_composite(flat, im).convert("RGB")
    buf = io.BytesIO()
    flat.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _draw_icon_box(
    doc: SVGDoc, box, icon_key: str, icon_image_path: str, color, card_name: str = ""
) -> None:
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    radius = 16
    doc.rect(x0, y0, w, h, rx=radius, fill=BG_PARCHMENT, stroke=color, sw=6)
    inset = 9
    doc.rect(
        x0 + inset,
        y0 + inset,
        w - 2 * inset,
        h - 2 * inset,
        rx=max(2, radius - 6),
        stroke=color,
        sw=2,
    )

    pad = 15
    ix0, iy0 = x0 + pad, y0 + pad
    iw, ih = w - 2 * pad, h - 2 * pad

    if icon_image_path:
        resolved = _resolve_icon_path(icon_image_path, card_name)
        if resolved is not None:
            try:
                size = int(min(iw, ih))
                href = _icon_image_data_uri(resolved, size, bg=BG_PARCHMENT)
                clip_id = doc.rounded_clip(ix0, iy0, size, size, max(2, radius - 10))
                doc.image(ix0, iy0, size, size, href, clip_id=clip_id)
                return
            except Exception as e:
                print(
                    f"[icon_image] '{icon_image_path}' for '{card_name}' failed to load ({e!r}) -- "
                    f"falling back to vector icon/monogram.",
                    file=sys.stderr,
                )

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    drawer = ICON_DRAWERS.get(icon_key)
    if drawer:
        drawer(doc, cx, cy, min(iw, ih) * 0.42, color)
    elif icon_key:
        stem = icon_key.rsplit(".", 1)[0] if "." in icon_key else icon_key
        if "." in icon_key and (
            stem in ICON_DRAWERS
            or icon_key.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg"))
        ):
            print(
                f"[icon] '{icon_key}' for '{card_name}' looks like a filename, but 'icon' only accepts "
                f"built-in keys ({', '.join(sorted(ICON_DRAWERS))}). Did you mean icon_image instead?",
                file=sys.stderr,
            )
        letter = icon_key[0].upper()
        size = int(min(iw, ih) * 0.5)
        y = _baseline_for_center(cy, True, size)
        doc.text(cx, y, letter, size, color, anchor="middle", bold=True)
    # else: leave the box empty -- a placeholder to fill in later.


def _draw_field_label_box(doc: SVGDoc, x0, x1, y, label, value, color) -> int:
    doc.text(x0, y + 14, label.upper(), 14, color, bold=True)
    y += 20
    box_h = 42
    doc.rect(x0, y, x1 - x0, box_h, rx=8, fill=(238, 232, 216), stroke=color, sw=2)
    _draw_centered_text(
        doc, value, True, 20, x0 + 6, x1 - 6, y + box_h / 2, TEXT_DARK, max_width=(x1 - x0 - 16)
    )
    return y + box_h


def _draw_stat_grid(doc: SVGDoc, x0: float, x1: float, y: float, stats, color) -> float:
    """
    Draws `stats` (a list of exactly 4 (label, value) pairs) as a 2x2 grid
    of labeled, bordered field boxes -- Casting Time / Range on top,
    Duration / Components below. Each row's box height adapts to whichever
    of its two values needs to wrap onto a second line, so both boxes in
    a row always line up.
    """
    col_gap = 14
    col_w = (x1 - x0 - col_gap) / 2
    row_gap = 10
    label_h = 18
    pad = 8
    col_x = [x0, x0 + col_w + col_gap]

    for row in range(2):
        pair = stats[row * 2 : row * 2 + 2]
        measured = [
            _fit_stat_value(v, col_w - 14, start_size=19, min_size=13, max_lines=2)
            for _, v in pair
        ]
        sizes = [m[1] for m in measured]
        line_h = int(max(sizes) * 1.22)
        max_lines = max(len(m[0]) for m in measured)
        box_h = max_lines * line_h + pad * 2
        box_y = y + label_h

        for col in range(2):
            label, _ = pair[col]
            lines, size = measured[col]
            cx0 = col_x[col]
            doc.text(cx0, y + 13, label.upper(), 14, color, bold=True)
            doc.rect(cx0, box_y, col_w, box_h, rx=7, fill=(238, 232, 216), stroke=color, sw=2)
            total_h = len(lines) * line_h
            start_y = box_y + (box_h - total_h) / 2 + size * 0.78
            for i, line in enumerate(lines):
                doc.text(
                    cx0 + col_w / 2, start_y + i * line_h, line, size, TEXT_DARK, anchor="middle"
                )

        y = box_y + box_h + row_gap

    return y


def _draw_hex_price(doc: SVGDoc, cx, cy, r, value: str, color) -> None:
    pts = [
        (cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
        for a in range(0, 360, 60)
    ]
    doc.polygon(pts, fill=BG_PARCHMENT, stroke=color, sw=4)
    parts = value.strip().split(None, 1)
    num = parts[0] if parts else value
    unit = parts[1].upper() if len(parts) > 1 else ""
    num_size = 25 if len(num) <= 3 else 19
    if unit:
        doc.text(
            cx,
            _baseline_for_center(cy - 10, True, num_size),
            num,
            num_size,
            TEXT_DARK,
            anchor="middle",
            bold=True,
        )
        doc.text(cx, _baseline_for_center(cy + 19, False, 13), unit, 13, color, anchor="middle")
    else:
        doc.text(
            cx,
            _baseline_for_center(cy, True, num_size),
            num,
            num_size,
            TEXT_DARK,
            anchor="middle",
            bold=True,
        )


def _draw_attunement(doc: SVGDoc, x, y, attuned: bool, color) -> None:
    """Draws the attunement block with its top-left corner at (x, y)."""
    doc.text(
        x + _ATTUNE_ROW_W / 2,
        y + 11,
        "Attunement?",
        13,
        TEXT_DARK,
        bold=True,
        anchor="middle",
    )
    row_y = y + 23
    box = 15

    doc.text(x, row_y + 12, "YES", 13, TEXT_DARK)
    yes_x = x + 38
    doc.rect(yes_x, row_y, box, box, stroke=color, sw=2, fill=(color if attuned else BG_PARCHMENT))

    no_x = yes_x + box + 26
    doc.text(no_x, row_y + 12, "NO", 13, TEXT_DARK)
    no_box_x = no_x + 28
    doc.rect(
        no_box_x,
        row_y,
        box,
        box,
        stroke=color,
        sw=2,
        fill=(color if not attuned else BG_PARCHMENT),
    )


def _draw_bottom_decoration(doc: SVGDoc, x0, x1, y, color) -> None:
    r = 5
    spacing = 22
    cx = (x0 + x1) / 2
    tab_half_w = 42
    left = x0 + 14
    while left < cx - tab_half_w - 8:
        doc.circle(left, y, r, fill=BG_PARCHMENT, stroke=color, sw=2)
        left += spacing
    right = x1 - 14
    while right > cx + tab_half_w + 8:
        doc.circle(right, y, r, fill=BG_PARCHMENT, stroke=color, sw=2)
        right -= spacing
    top_half = tab_half_w * 0.55
    doc.polygon(
        [
            (cx - top_half, y - 12),
            (cx + top_half, y - 12),
            (cx + tab_half_w, y + 12),
            (cx - tab_half_w, y + 12),
        ],
        fill=BG_PARCHMENT,
        stroke=color,
        sw=3,
    )


# ---------------------------------------------------------------------------
# Card renderers
# ---------------------------------------------------------------------------


def render_spell_card(card: SpellCard, bw: bool = False) -> str:
    color = BLACK if bw else SPELL_SCHOOL_COLORS.get(card.school.lower(), DEFAULT_SPELL_COLOR)
    doc = SVGDoc(CARD_W, CARD_H)
    doc.rect(
        0,
        0,
        CARD_W,
        CARD_H,
        rx=CORNER_RADIUS,
        fill=BG_PARCHMENT,
        stroke=color,
        sw=BORDER_THICKNESS,
    )

    x0, x1 = MARGIN + BORDER_THICKNESS, CARD_W - MARGIN - BORDER_THICKNESS
    y = MARGIN + BORDER_THICKNESS

    header_h = 92
    doc.rect(x0, y, x1 - x0, header_h, rx=14, fill=color)
    _draw_centered_text(
        doc,
        card.name,
        True,
        34,
        x0 + 10,
        x1 - 10,
        y + header_h / 2,
        TEXT_ON_HEADER,
        max_width=x1 - x0 - 20,
    )
    y += header_h + 14

    level_txt = "Cantrip" if card.level == 0 else f"Level {card.level}"
    sub_text = f"{level_txt} — {card.school}"
    doc.text((x0 + x1) / 2, y + 22, sub_text, 22, TEXT_DARK, anchor="middle")
    y += 34

    doc.line(x0 + 10, y, x1 - 10, y, color, 3)
    y += 14

    stats = [
        ("Casting Time", card.casting_time),
        ("Range", card.range),
        ("Duration", card.duration),
        ("Components", card.components),
    ]
    y = _draw_stat_grid(doc, x0, x1, y, stats, color)

    doc.line(x0 + 10, y, x1 - 10, y, color, 2)
    y += 14

    footer_reserved = 40 if card.classes else 10
    max_body_h = CARD_H - MARGIN - BORDER_THICKNESS - footer_reserved - y
    full_description = card.description
    if card.at_higher_levels:
        full_description += f"\n\nAt Higher Levels. {card.at_higher_levels}"
    y = _draw_body_paragraph(doc, full_description, x0 + 6, x1 - x0 - 12, y, max_body_h)

    if card.classes:
        classes_txt = ", ".join(card.classes)
        doc.text(
            (x0 + x1) / 2,
            CARD_H - MARGIN - BORDER_THICKNESS - 22,
            classes_txt,
            15,
            color,
            anchor="middle",
        )

    return doc.render()


def render_item_card(card: ItemCard, bw: bool = False) -> str:
    """
    Item card layout: title plate, a bordered icon box sized to match the
    height of the TYPE/RARITY/price/attunement field column beside it,
    a description below, and a decorative rivet-and-tab bottom border.
    """
    color = BLACK if bw else RARITY_COLORS.get(card.rarity.lower(), DEFAULT_RARITY_COLOR)
    doc = SVGDoc(CARD_W, CARD_H)
    doc.rect(
        0,
        0,
        CARD_W,
        CARD_H,
        rx=CORNER_RADIUS,
        stroke=color,
        sw=BORDER_THICKNESS,
        fill=BG_PARCHMENT,
    )
    inset = MARGIN
    doc.rect(
        inset,
        inset,
        CARD_W - 2 * inset,
        CARD_H - 2 * inset,
        rx=CORNER_RADIUS - 12,
        stroke=color,
        sw=2,
    )

    x0, x1 = MARGIN + BORDER_THICKNESS + 10, CARD_W - MARGIN - BORDER_THICKNESS - 10
    y = MARGIN + BORDER_THICKNESS + 12

    # Title plate
    title_h = 60
    doc.rect(x0, y, x1 - x0, title_h, rx=10, fill=(236, 231, 216), stroke=color, sw=3)
    _draw_centered_text(
        doc,
        card.name,
        True,
        28,
        x0 + 10,
        x1 - 10,
        y + title_h / 2,
        TEXT_DARK,
        max_width=x1 - x0 - 24,
    )
    y += title_h + 16

    icon_key = (getattr(card, "icon", "") or "").strip().lower()
    icon_image_path = (getattr(card, "icon_image", "") or "").strip()

    # Field column geometry, computed first so the icon box can be sized
    # to match its total height exactly.
    field_row_h = 20 + 42  # label + value box
    gap1, gap2 = 16, 20
    hex_r = 46
    hex_row_h = hex_r * 2 + 10
    icon_size = field_row_h * 2 + gap1 + gap2 + hex_row_h

    icon_box = (x0, y, x0 + icon_size, y + icon_size)
    _draw_icon_box(doc, icon_box, icon_key, icon_image_path, color, card_name=card.name)

    fx0, fx1 = x0 + icon_size + 18, x1
    fy = y
    fy = _draw_field_label_box(doc, fx0, fx1, fy, "Type", card.item_type, color)
    fy += gap1
    fy = _draw_field_label_box(doc, fx0, fx1, fy, "Rarity", card.rarity.title(), color)
    fy += gap2

    row_y = fy + hex_r
    has_value = bool(card.value)
    if has_value:
        _draw_hex_price(doc, fx0 + hex_r, row_y, hex_r, card.value, color)
        attune_x = fx0 + hex_r * 2 + 22
        attune_y = fy
    else:
        # No price: centre the attunement block in the field column
        attune_x = fx0 + ((fx1 - fx0) - _ATTUNE_ROW_W) / 2
        attune_y = row_y - _ATTUNE_H / 2
    _draw_attunement(doc, attune_x, attune_y, card.attunement, color)

    y = y + icon_size + 18

    doc.line(x0 + 6, y, x1 - 6, y, color, 3)
    y += 16

    footer_reserved = 46
    max_body_h = CARD_H - MARGIN - BORDER_THICKNESS - footer_reserved - y
    y = _draw_body_paragraph(
        doc, card.description, x0 + 6, x1 - x0 - 12, y, max_body_h, start_size=26
    )

    _draw_bottom_decoration(doc, x0, x1, CARD_H - MARGIN - BORDER_THICKNESS - 20, color)

    return doc.render()


def render_card(card, bw: bool = False) -> str:
    if isinstance(card, SpellCard):
        return render_spell_card(card, bw=bw)
    if isinstance(card, ItemCard):
        return render_item_card(card, bw=bw)
    raise TypeError(f"Unsupported card type: {type(card)!r}")
