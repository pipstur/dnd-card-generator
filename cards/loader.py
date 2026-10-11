"""
Load card data from JSON or CSV files into model instances.

CSV support maps the column layout produced by common spell/item scrapes
(e.g. from dnd5e.wikidot.com-style exports) directly onto SpellCard /
ItemCard -- see _SPELL_CSV_COLUMNS / _ITEM_CSV_COLUMNS below for the
exact expected headers.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import List, Union

from .models import SpellCard, ItemCard, spell_from_dict, item_from_dict

Card = Union[SpellCard, ItemCard]


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def load_spells(path: str | Path) -> List[SpellCard]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [spell_from_dict(d) for d in data]


def load_items(path: str | Path) -> List[ItemCard]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [item_from_dict(d) for d in data]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------
# Expected headers (extra columns like URL/Source are read and ignored):
#   Spells: Level, Spell Name, School, Casting Time, Range, Duration,
#           Components, Description, At Higher Levels, Spell Lists
#   Items:  Item Name, Rarity, Type, Attuned, Description
#           (add a "Price" column for the hex price tag -- optional)


def _clean(s: str | None) -> str:
    return (s or "").strip()


def _parse_spell_level(raw: str) -> int:
    raw = _clean(raw)
    if raw.lower() == "cantrip":
        return 0
    m = re.search(r"\d+", raw)
    return int(m.group()) if m else 0


def _split_list(raw: str) -> List[str]:
    return [s.strip() for s in _clean(raw).split(",") if s.strip()]


def _parse_bool(raw: str) -> bool:
    return _clean(raw).lower() in ("true", "yes", "y", "1")


def load_spells_csv(path: str | Path) -> List[SpellCard]:
    spells = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            spells.append(
                SpellCard(
                    name=_clean(row.get("Spell Name")),
                    level=_parse_spell_level(row.get("Level")),
                    school=_clean(row.get("School")),
                    casting_time=_clean(row.get("Casting Time")),
                    range=_clean(row.get("Range")),
                    duration=_clean(row.get("Duration")),
                    components=_clean(row.get("Components")),
                    description=_clean(row.get("Description")),
                    at_higher_levels=_clean(row.get("At Higher Levels")),
                    classes=_split_list(row.get("Spell Lists")),
                )
            )
    return spells


def load_items_csv(path: str | Path) -> List[ItemCard]:
    items = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            items.append(
                ItemCard(
                    name=_clean(row.get("Item Name")),
                    item_type=_clean(row.get("Type")),
                    rarity=_clean(row.get("Rarity")),
                    description=_clean(row.get("Description")),
                    attunement=_parse_bool(row.get("Attuned")),
                    value=_clean(row.get("Price")),  # not in scraped data -- omitted if absent
                )
            )
    return items


# Extension-based dispatch, so the CLI doesn't need separate flags


def load_spells_any(path: str | Path) -> List[SpellCard]:
    return load_spells_csv(path) if str(path).lower().endswith(".csv") else load_spells(path)


def load_items_any(path: str | Path) -> List[ItemCard]:
    return load_items_csv(path) if str(path).lower().endswith(".csv") else load_items(path)
