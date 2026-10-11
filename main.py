#!/usr/bin/env python3
"""
Generate printable DnD cards (spells and/or items) from JSON or CSV data:
individual SVG files (crisp, scalable, editable) plus one print-ready
PDF laying them out on Letter pages.

Examples:
    python main.py
    python main.py --spells spells_custom.json --items items_custom.json --output output/cards.pdf
    python main.py --spells output/dnd5e_spells.csv --items output/dnd5e_wondrous_items.csv
    python main.py --items config/items_custom.json --copies 2
    python main.py --no-svg   # skip individual .svg files, just build the PDF

    # Use generated art (from generate_item_images_comfyui.py) on wondrous-item cards:
    python main.py --items output/dnd5e_wondrous_items.csv --item-images output/item_images
    python main.py --items output/dnd5e_wondrous_items.csv --variant 2
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from cards import load_spells_any, load_items_any, render_card, build_pdf


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name).strip("_").lower()


IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
_VARIANT_RE = re.compile(r"^(?P<slug>.+)_(?P<v>\d+)$")


def _image_slug(name: str) -> str:
    """Must match slugify() in generate_item_images_comfyui.py exactly,
    since that's what the image files were named from."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _url_slug(url: str) -> str:
    """https://dnd5e.wikidot.com/wondrous-items:armblade -> 'armblade'"""
    tail = url.strip().rstrip("/").rsplit(":", 1)[-1].rsplit("/", 1)[-1]
    return _image_slug(tail)


def _is_wondrous_csv(path: Path) -> bool:
    """True for a .csv with the scraped wondrous-items columns."""
    if path.suffix.lower() != ".csv" or not path.is_file():
        return False
    with path.open(newline="", encoding="utf-8-sig") as f:
        header = next(csv.reader(f), [])
    return {"Item Name", "URL"} <= {h.strip() for h in header}


def _index_images(img_dir: Path) -> dict[str, dict[int, Path]]:
    """slug -> {variant_number: path}. Variant 0 = plain 'slug.png' (a
    single-variant run, or a winner you renamed by hand)."""
    index: dict[str, dict[int, Path]] = {}
    for p in img_dir.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        m = _VARIANT_RE.match(p.stem)
        slug, v = (m.group("slug"), int(m.group("v"))) if m else (p.stem, 0)
        index.setdefault(slug, {})[v] = p
    return index


def _pick_variant(variants: dict[int, Path], wanted: int | None) -> tuple[Path, bool]:
    """Returns (path, fell_back). Order: requested variant -> plain name ->
    lowest-numbered variant."""
    if wanted is not None and wanted in variants:
        return variants[wanted], False
    if 0 in variants:
        return variants[0], False
    return variants[min(variants)], wanted is not None


def attach_item_images(
    items: list, csv_path: Path, img_dir: Path, variant: int | None, report_dir: Path
) -> None:
    """Sets card.icon_image (the existing PNG-badge field, which takes priority
    over the vector `icon`) on every item card that has a matching image.
    Cards without one are left untouched and keep their normal icon/monogram."""
    if not _is_wondrous_csv(csv_path):
        print(
            f"--item-images ignored: {csv_path} isn't a wondrous-items CSV "
            "(needs a .csv with 'Item Name' and 'URL' columns)."
        )
        return
    if not img_dir.is_dir():
        print(f"--item-images ignored: {img_dir} is not a directory.")
        return

    index = _index_images(img_dir)

    # Item name -> candidate slugs (name slug first, URL slug as fallback)
    slugs_by_name: dict[str, list[str]] = {}
    with csv_path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = (row.get("Item Name") or "").strip()
            candidates = [_image_slug(name), _url_slug(row.get("URL") or "")]
            slugs_by_name[name] = [s for s in dict.fromkeys(candidates) if s]

    matched = fell_back = 0
    missing: list[str] = []
    for card in items:
        name = card.name.strip()
        slugs = slugs_by_name.get(name) or [_image_slug(name)]
        variants = next((index[s] for s in slugs if s in index), None)
        if variants is None:
            missing.append(name)
            continue
        path, fell = _pick_variant(variants, variant)
        card.icon_image = str(path.resolve())
        matched += 1
        fell_back += fell

    print(f"Item images: matched {matched}/{len(items)} from {img_dir}")
    if fell_back:
        print(f"  {fell_back} item(s) had no variant {variant}; used another variant.")
    if missing:
        print(f"  {len(missing)} item(s) have no image:")
        for n in missing[:30]:
            print(f"    - {n}")
        if len(missing) > 30:
            print(f"    ... and {len(missing) - 30} more")
        report_dir.mkdir(parents=True, exist_ok=True)
        report = report_dir / "missing_item_images.txt"
        report.write_text("\n".join(missing) + "\n", encoding="utf-8")
        print(f"  Full list written to {report}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--spells",
        type=str,
        default="config/spells_custom.json",
        help="Path to spells JSON or CSV file (or omit with --no-spells)",
    )
    parser.add_argument(
        "--items",
        type=str,
        default="config/items_custom.json",
        help="Path to items JSON or CSV file (or omit with --no-items)",
    )
    parser.add_argument("--no-spells", action="store_true", help="Skip spell cards")
    parser.add_argument("--no-items", action="store_true", help="Skip item cards")
    parser.add_argument("--output", type=str, default="output/cards.pdf", help="Output PDF path")
    parser.add_argument(
        "--svg-dir",
        type=str,
        default="output/svg",
        help="Directory to write individual card .svg files into",
    )
    parser.add_argument(
        "--no-svg",
        action="store_true",
        help="Skip writing individual .svg files, just build the PDF",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Skip building the PDF, just write individual .svg files",
    )
    parser.add_argument(
        "--copies", type=int, default=1, help="How many copies of each card to print (PDF only)"
    )
    parser.add_argument(
        "--bw",
        action="store_true",
        help="Render borders/headers/icons in black instead of color (for black-and-white printing)",
    )
    parser.add_argument(
        "--item-images",
        type=str,
        default=None,
        help="Directory of generated item images. Only used when --items is a "
        "wondrous-items CSV (with 'Item Name' and 'URL' columns).",
    )
    parser.add_argument(
        "--variant",
        type=int,
        default=None,
        help="Which image variant to use (e.g. 2 -> item-name_2.png). Falls back to "
        "the plain item-name.png, then the lowest-numbered variant.",
    )
    args = parser.parse_args()
    if args.variant is not None and args.variant < 1:
        parser.error("--variant must be 1 or greater")
    return args


def main() -> None:
    args = parse_args()

    all_cards = []

    if not args.no_spells and Path(args.spells).exists():
        spells = load_spells_any(args.spells)
        print(f"Loaded {len(spells)} spell card(s) from {args.spells}")
        all_cards.extend(spells)

    if not args.no_items and Path(args.items).exists():
        items = load_items_any(args.items)
        print(f"Loaded {len(items)} item card(s) from {args.items}")
        if args.item_images:
            attach_item_images(
                items,
                Path(args.items),
                Path(args.item_images),
                args.variant,
                Path(args.output).parent,
            )
        all_cards.extend(items)

    if not all_cards:
        print("No cards loaded -- nothing to do. Check your --spells/--items paths.")
        return

    print(f"Rendering {len(all_cards)} card(s){' (black & white)' if args.bw else ''}...")
    svgs = [render_card(c, bw=args.bw) for c in all_cards]

    if not args.no_svg:
        svg_dir = Path(args.svg_dir)
        svg_dir.mkdir(parents=True, exist_ok=True)
        seen: dict[str, int] = {}
        for card, svg in zip(all_cards, svgs):
            slug = _slug(card.name) or "card"
            seen[slug] = seen.get(slug, 0) + 1
            if seen[slug] > 1:
                slug = f"{slug}_{seen[slug]}"
            (svg_dir / f"{slug}.svg").write_text(svg, encoding="utf-8")
        print(f"Wrote {len(svgs)} SVG file(s) to {svg_dir}/")

    if not args.no_pdf:
        output_path = build_pdf(svgs, args.output, copies=args.copies)
        print(f"Wrote {output_path} ({len(svgs) * args.copies} card instance(s)).")


if __name__ == "__main__":
    main()
