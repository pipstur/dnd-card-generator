"""
Data models for DnD cards.

Two card types to start: SpellCard and ItemCard. Both are plain
dataclasses so they're trivial to load from JSON and easy to extend
with new fields or new card types later (e.g. MonsterCard, NPCCard).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class SpellCard:
    name: str
    level: int  # 0 = cantrip
    school: str  # e.g. "Evocation", "Abjuration"
    casting_time: str  # e.g. "1 action"
    range: str  # e.g. "60 feet"
    duration: str  # e.g. "Instantaneous", "1 minute (concentration)"
    components: str  # e.g. "V, S, M (a pinch of sulfur)"
    description: str
    at_higher_levels: str = ""  # optional "At Higher Levels" text, shown appended
    # to the description if present
    classes: List[str] = field(default_factory=list)  # e.g. ["Wizard", "Sorcerer"]
    card_type: str = "spell"


@dataclass
class ItemCard:
    name: str
    item_type: str  # e.g. "Weapon", "Wondrous Item", "Potion"
    rarity: str  # common | uncommon | rare | very rare | legendary | artifact
    description: str
    attunement: bool = False
    value: str = ""  # e.g. "50 gp" (optional, blank to omit)
    icon: str = ""  # optional corner badge: weapon, potion, ring,
    # wand, armor, scroll, wondrous -- or any other
    # string, which falls back to a monogram letter.
    # Leave blank to omit the badge. Items only.
    icon_image: str = ""  # optional path to a PNG to use as the badge
    # instead of a built-in vector icon (looked up
    # as given, then under assets/icons/). Takes
    # priority over `icon` when both are set.
    card_type: str = "item"


def spell_from_dict(d: dict) -> SpellCard:
    d = dict(d)
    d.pop("card_type", None)
    return SpellCard(**d)


def item_from_dict(d: dict) -> ItemCard:
    d = dict(d)
    d.pop("card_type", None)
    return ItemCard(**d)
