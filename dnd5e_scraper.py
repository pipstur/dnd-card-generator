#!/usr/bin/env python3
"""
Combined scraper for dnd5e.wikidot.com: spells and wondrous items.

Usage:
    pip install requests beautifulsoup4

    python dnd5e_scraper.py            # scrape both spells and items
    python dnd5e_scraper.py spells     # only spells
    python dnd5e_scraper.py items      # only wondrous items

Output (created automatically):
    output/dnd5e_spells.csv
    output/dnd5e_wondrous_items.csv
"""

import argparse
import csv
import os
import sys
import time

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------
# Shared config
# --------------------------------------------------------------------------

SITE_ROOT = "https://dnd5e.wikidot.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; DnDScraper/1.0; +https://example.com/contact)"}
# Be polite to the wiki's server
REQUEST_DELAY_SECONDS = 0.75
OUTPUT_DIR = "output"

# --------------------------------------------------------------------------
# Spell config
# --------------------------------------------------------------------------

SPELLS_URL = f"{SITE_ROOT}/spells"
SPELLS_CSV = os.path.join(OUTPUT_DIR, "dnd5e_spells.csv")

SPELL_TABS = {
    "wiki-tab-0-0": "Cantrip",
    "wiki-tab-0-1": "1st Level",
    "wiki-tab-0-2": "2nd Level",
    "wiki-tab-0-3": "3rd Level",
    "wiki-tab-0-4": "4th Level",
    "wiki-tab-0-5": "5th Level",
    "wiki-tab-0-6": "6th Level",
    "wiki-tab-0-7": "7th Level",
    "wiki-tab-0-8": "8th Level",
    "wiki-tab-0-9": "9th Level",
}

SPELL_FIELDS = [
    "Level",
    "Spell Name",
    "School",
    "Casting Time",
    "Range",
    "Duration",
    "Components",
    "Description",
    "At Higher Levels",
    "Spell Lists",
    "URL",
]

# --------------------------------------------------------------------------
# Item config
# --------------------------------------------------------------------------

ITEMS_URL = f"{SITE_ROOT}/wondrous-items"
ITEMS_CSV = os.path.join(OUTPUT_DIR, "dnd5e_wondrous_items.csv")

ITEM_TABS = {
    "wiki-tab-0-0": "Common",
    "wiki-tab-0-1": "Uncommon",
    "wiki-tab-0-2": "Rare",
    "wiki-tab-0-3": "Very Rare",
    "wiki-tab-0-4": "Legendary",
    "wiki-tab-0-5": "Artifact",
    "wiki-tab-0-6": "Unique",
    "wiki-tab-0-7": "???",
}

ITEM_FIELDS = [
    "Item Name",
    "Rarity",
    "Type",
    "Attuned",
    "Source",
    "Description",
    "URL",
]

RARITY_KEYWORDS = (
    "common",
    "uncommon",
    "rare",
    "legendary",
    "artifact",
    "unique",
    "very rare",
)

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def get_soup(session, url):
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def absolute_url(href):
    return href if href.startswith("http") else SITE_ROOT + href


def table_rows(tab_div):
    """Return the data rows (header row skipped) of the table in a tab, or None."""
    table = tab_div.find("table")
    if table is None:
        return None
    body = table.find("tbody")
    trs = body.find_all("tr") if body else table.find_all("tr")
    return trs[1:]


def collect_rows(soup, tabs, min_cols, build_row):
    """
    Walk each tab, and build a row dict from every table row.

    build_row(label, tds, name, url) -> dict
    Returns a flat list of row dicts.
    """
    all_rows = []
    for tab_id, label in tabs.items():
        tab_div = soup.find(id=tab_id)
        if tab_div is None:
            print(f"  ! Could not find tab {tab_id} ({label}) - skipping")
            continue

        trs = table_rows(tab_div)
        if trs is None:
            print(f"  ! No table found inside {tab_id} ({label}) - skipping")
            continue

        rows = []
        for tr in trs:
            tds = tr.find_all("td")
            if len(tds) < min_cols:
                continue
            link = tds[0].find("a")
            if link is None:
                continue
            name = link.get_text(strip=True)
            url = absolute_url(link.get("href", ""))
            rows.append(build_row(label, tds, name, url))

        print(f"  Found {len(rows)} entries for {label}")
        all_rows.extend(rows)
    return all_rows


def ul_to_text(ul):
    """Turn a <ul> into '- item' lines."""
    bullets = [li.get_text(" ", strip=True) for li in ul.find_all("li", recursive=False)]
    return "\n".join(f"- {b}" for b in bullets if b)


def label_of(p):
    """Text of the leading <strong> label in a paragraph, if any."""
    strong = p.find("strong")
    return strong.get_text(strip=True) if strong else ""


def skip_source_line(elements, idx):
    if (
        idx < len(elements)
        and elements[idx].name == "p"
        and elements[idx].get_text(strip=True).lower().startswith("source")
    ):
        return idx + 1
    return idx


# --------------------------------------------------------------------------
# Spells
# --------------------------------------------------------------------------


def build_spell_row(level, tds, name, url):
    return {
        "Level": level,
        "Spell Name": name,
        "School": tds[1].get_text(strip=True),
        "Casting Time": tds[2].get_text(strip=True),
        "Range": tds[3].get_text(strip=True),
        "Duration": tds[4].get_text(strip=True),
        "Components": tds[5].get_text(strip=True),
        "URL": url,
    }


def parse_spell_page(soup):
    """Return (description, at_higher_levels, spell_lists) from a spell page."""
    content = soup.find(id="page-content")
    if content is None:
        return "", "", ""

    # <p> and <ul> in document order, so bulleted lists in descriptions are kept
    elements = content.find_all(["p", "ul"], recursive=False)

    description_parts = []
    higher_levels = ""
    spell_lists = ""

    idx = skip_source_line(elements, 0)

    # Italic school/level line, e.g. "Conjuration cantrip"
    if (
        idx < len(elements)
        and elements[idx].name == "p"
        and elements[idx].find("em")
        and not elements[idx].find("strong")
    ):
        idx += 1

    # Casting Time / Range / Components / Duration block
    if (
        idx < len(elements)
        and elements[idx].name == "p"
        and "casting time" in elements[idx].get_text(strip=True).lower()
    ):
        idx += 1

    for el in elements[idx:]:
        if el.name == "ul":
            text = ul_to_text(el)
            if text:
                description_parts.append(text)
            continue

        label = label_of(el).lower()
        text = el.get_text(" ", strip=True)

        if "at higher levels" in label:
            higher_levels = text.replace(label_of(el), "", 1).strip()
        elif "spell lists" in label:
            links = el.find_all("a")
            spell_lists = ", ".join(a.get_text(strip=True) for a in links) or text
        elif text:
            description_parts.append(text)

    return "\n\n".join(description_parts), higher_levels, spell_lists


def scrape_spells(session):
    print(f"\n=== SPELLS: fetching {SPELLS_URL} ===")
    soup = get_soup(session, SPELLS_URL)

    print("Collecting spell rows per level tab...")
    spells = collect_rows(soup, SPELL_TABS, 6, build_spell_row)
    total = len(spells)
    print(f"\nTotal spells found: {total}")
    print("Fetching individual spell pages...\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SPELLS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SPELL_FIELDS)
        writer.writeheader()

        for i, spell in enumerate(spells, start=1):
            print(f"[{i}/{total}] {spell['Spell Name']} ({spell['Level']}) -> {spell['URL']}")
            try:
                page = get_soup(session, spell["URL"])
                description, higher, lists = parse_spell_page(page)
            except requests.RequestException as e:
                print(f"    ! Failed to fetch {spell['URL']}: {e}")
                description, higher, lists = "", "", ""

            spell["Description"] = description
            spell["At Higher Levels"] = higher
            spell["Spell Lists"] = lists
            writer.writerow(spell)
            f.flush()
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone! Wrote {total} spells to {SPELLS_CSV}")


# --------------------------------------------------------------------------
# Wondrous items
# --------------------------------------------------------------------------


def build_item_row(rarity, tds, name, url):
    return {
        "Item Name": name,
        "Rarity": rarity,
        "Type": tds[1].get_text(strip=True),
        "Attuned": tds[2].get_text(strip=True).lower().startswith("attun"),
        "Source": tds[3].get_text(strip=True),
        "URL": url,
    }


def parse_item_page(soup):
    """Return the item's description text from an item page."""
    content = soup.find(id="page-content")
    if content is None:
        return ""

    elements = content.find_all(["p", "ul"], recursive=False)

    idx = skip_source_line(elements, 0)

    # Italic type/rarity line, e.g. "Weapon (...), common (requires attunement ...)"
    if (
        idx < len(elements)
        and elements[idx].name == "p"
        and elements[idx].find("em")
        and not elements[idx].find("strong")
    ):
        if any(k in elements[idx].get_text(strip=True).lower() for k in RARITY_KEYWORDS):
            idx += 1

    parts = []
    for el in elements[idx:]:
        if el.name == "ul":
            text = ul_to_text(el)
        else:
            text = el.get_text(" ", strip=True)
        if text:
            parts.append(text)

    return "\n\n".join(parts)


def scrape_items(session):
    print(f"\n=== ITEMS: fetching {ITEMS_URL} ===")
    soup = get_soup(session, ITEMS_URL)

    print("Collecting item rows per rarity tab...")
    items = collect_rows(soup, ITEM_TABS, 4, build_item_row)
    total = len(items)
    print(f"\nTotal items found: {total}")
    print("Fetching individual item pages...\n")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(ITEMS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ITEM_FIELDS)
        writer.writeheader()

        for i, item in enumerate(items, start=1):
            print(f"[{i}/{total}] {item['Item Name']} ({item['Rarity']}) -> {item['URL']}")
            try:
                page = get_soup(session, item["URL"])
                description = parse_item_page(page)
            except requests.RequestException as e:
                print(f"    ! Failed to fetch {item['URL']}: {e}")
                description = ""

            item["Description"] = description
            writer.writerow(item)
            f.flush()
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone! Wrote {total} items to {ITEMS_CSV}")


def main():
    parser = argparse.ArgumentParser(
        description="Scrape D&D 5e spells and wondrous items from dnd5e.wikidot.com"
    )
    parser.add_argument(
        "what",
        nargs="?",
        default="all",
        choices=["all", "spells", "items"],
        help="what to scrape (default: all)",
    )
    args = parser.parse_args()

    session = requests.Session()
    if args.what in ("all", "spells"):
        scrape_spells(session)
    if args.what in ("all", "items"):
        scrape_items(session)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        sys.exit(1)
