"""Extract phase: parse Project Aon XHTML files into plain dataclasses.

This module is standalone — it is never imported by the API at runtime.
All return types are plain dataclasses from app.parser.types; no ORM
dependencies exist in this file.

Usage:
    from app.parser.extract import extract_book_metadata, extract_scenes, ...
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path

from bs4 import BeautifulSoup, Tag

from app.parser.types import (
    BookData,
    ChoiceData,
    CombatData,
    CRTRow,
    DisciplineData,
    EquipmentData,
    SceneData,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Era determination
# ---------------------------------------------------------------------------

def _era_for_book_number(number: int) -> str:
    """Return the era string for a given book number.

    Ranges: 1–5 = kai, 6–12 = magnakai, 13–20 = grand_master, 21+ = new_order.
    """
    if 1 <= number <= 5:
        return "kai"
    if 6 <= number <= 12:
        return "magnakai"
    if 13 <= number <= 20:
        return "grand_master"
    return "new_order"


# ---------------------------------------------------------------------------
# Book metadata
# ---------------------------------------------------------------------------

def extract_book_metadata(xhtml_path: str | Path) -> BookData:
    """Extract book metadata from the path and XHTML content.

    The slug is the filename stem (e.g. ``01fftd``).  The book number is parsed
    from the leading two digits of the slug.  Era is determined from the book
    number using Project Aon ranges.  The title is read from the ``<title>``
    element, falling back to the first ``<h1>`` if absent.

    Args:
        xhtml_path: Absolute or relative path to the XHTML source file.

    Returns:
        A populated :class:`~app.parser.types.BookData` instance.
    """
    path = Path(xhtml_path)
    slug = path.stem

    # Parse book number from slug prefix (e.g. "01fftd" → 1)
    number_match = re.match(r"^(\d+)", slug)
    if number_match:
        number = int(number_match.group(1))
    else:
        logger.warning("Could not parse book number from slug %r; defaulting to 0", slug)
        number = 0

    era = _era_for_book_number(number)

    soup = _parse_xhtml(path)

    title = ""
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        title = title_tag.get_text(strip=True)
    else:
        h1_tag = soup.find("h1")
        if h1_tag:
            title = h1_tag.get_text(strip=True)

    if not title:
        logger.warning("No title found in %s; using slug as fallback", path.name)
        title = slug

    return BookData(slug=slug, number=number, era=era, title=title, xhtml_path=path)


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------

def extract_scenes(soup: BeautifulSoup) -> list[SceneData]:
    """Extract all numbered scenes from an already-parsed BeautifulSoup tree.

    Each scene corresponds to a ``<div class="numbered">`` or
    ``<section class="numbered">`` block.  The scene number and ``html_id``
    are read from the inner anchor (``<a name="sect{N}">`` or
    ``id="sect{N}"``).  Narrative HTML is assembled from non-choice,
    non-combat ``<p>`` elements.  Choices and combat encounters are
    extracted via their respective helpers and attached to the scene.

    Args:
        soup: A parsed BeautifulSoup document.

    Returns:
        A list of :class:`~app.parser.types.SceneData` instances, one per
        numbered section found.  Returns an empty list when no sections are
        present.
    """
    scenes: list[SceneData] = []

    blocks = soup.find_all(["div", "section"], class_="numbered")
    if not blocks:
        logger.debug("No numbered blocks found in document")
        return scenes

    for block in blocks:
        if not isinstance(block, Tag):
            continue

        # Locate the scene anchor: <a name="sect{N}"> or element with id="sect{N}"
        number, html_id = _extract_scene_number(block)
        if number is None:
            logger.warning("Could not determine scene number for a numbered block; skipping")
            continue

        illustration_path = _extract_illustration(block)
        narrative = _extract_narrative(block)
        choices = extract_choices(block)
        combat = extract_combat_encounters(block)

        scenes.append(
            SceneData(
                number=number,
                html_id=html_id,
                narrative=narrative,
                illustration_path=illustration_path,
                choices=choices,
                combat_encounters=combat,
            )
        )

    return scenes


def _extract_scene_number(block: Tag) -> tuple[int | None, str]:
    """Return ``(scene_number, html_id)`` from a numbered block.

    Tries three strategies in order:
    1. ``<a name="sect{N}">`` anywhere inside the block.
    2. Any element with ``id="sect{N}"``.
    3. ``<h3>`` text that is a plain integer.
    """
    # Strategy 1: <a name="sect{N}">
    for a_tag in block.find_all("a"):
        if not isinstance(a_tag, Tag):
            continue
        name_attr = a_tag.get("name", "")
        if isinstance(name_attr, list):
            name_attr = name_attr[0] if name_attr else ""
        if name_attr and str(name_attr).startswith("sect"):
            raw = str(name_attr)[4:]
            if raw.isdigit():
                return int(raw), str(name_attr)

    # Strategy 2: id="sect{N}"
    for tag in block.find_all(True):
        if not isinstance(tag, Tag):
            continue
        id_attr = tag.get("id", "")
        if isinstance(id_attr, list):
            id_attr = id_attr[0] if id_attr else ""
        if id_attr and str(id_attr).startswith("sect"):
            raw = str(id_attr)[4:]
            if raw.isdigit():
                return int(raw), str(id_attr)

    # Strategy 3: plain integer text in <h3>
    h3 = block.find("h3")
    if h3:
        text = h3.get_text(strip=True)
        if text.isdigit():
            number = int(text)
            return number, f"sect{number}"

    return None, ""


def _extract_illustration(block: Tag) -> str | None:
    """Return the src attribute of the first ``<img>`` in the block, or None."""
    img = block.find("img")
    if img and isinstance(img, Tag):
        src = img.get("src")
        if src:
            return str(src) if not isinstance(src, list) else str(src[0])
    return None


def _extract_narrative(block: Tag) -> str:
    """Assemble narrative text from non-choice, non-combat ``<p>`` elements.

    Returns inner HTML of each qualifying ``<p>`` joined with newlines.
    Strips leading/trailing whitespace from the result.
    """
    parts: list[str] = []
    for p in block.find_all("p"):
        if not isinstance(p, Tag):
            continue
        p_class = p.get("class", [])
        if isinstance(p_class, str):
            p_class = [p_class]
        if "choice" in p_class or "combat" in p_class:
            continue
        parts.append(p.decode_contents().strip())
    return "\n".join(parts).strip()


# ---------------------------------------------------------------------------
# Choices
# ---------------------------------------------------------------------------

_TURN_TO_HREF_RE = re.compile(r"#sect(\d+)")
_TURN_TO_TEXT_RE = re.compile(r"turn to (\d+)", re.IGNORECASE)


def extract_choices(scene_soup: Tag) -> list[ChoiceData]:
    """Extract player choices from ``<p class="choice">`` elements.

    The target scene number is read from the ``href`` attribute of the link
    inside the choice (``#sect{N}``).  When no link is present the text is
    searched for a "turn to {N}" pattern as a fallback.  Choices whose target
    cannot be determined are skipped with a warning.

    Args:
        scene_soup: The BeautifulSoup Tag representing a single scene block.

    Returns:
        A list of :class:`~app.parser.types.ChoiceData` instances in document
        order.  Returns an empty list when no valid choices are found.
    """
    choices: list[ChoiceData] = []

    for ordinal, p in enumerate(scene_soup.find_all("p", class_="choice"), start=1):
        if not isinstance(p, Tag):
            continue
        raw_text = p.get_text(" ", strip=True)
        target = _resolve_choice_target(p, raw_text)
        if target is None:
            logger.warning("Could not resolve target scene for choice: %r", raw_text[:80])
            continue
        choices.append(ChoiceData(raw_text=raw_text, target_scene_number=target, ordinal=ordinal))

    return choices


def _resolve_choice_target(p: Tag, raw_text: str) -> int | None:
    """Return the target scene number from a choice ``<p>`` element."""
    # Prefer href="#sect{N}" on any child anchor
    for a_tag in p.find_all("a"):
        if not isinstance(a_tag, Tag):
            continue
        href = a_tag.get("href", "")
        if isinstance(href, list):
            href = href[0] if href else ""
        m = _TURN_TO_HREF_RE.search(str(href))
        if m:
            return int(m.group(1))

    # Fallback: "turn to N" in text
    m = _TURN_TO_TEXT_RE.search(raw_text)
    if m:
        return int(m.group(1))

    return None


# ---------------------------------------------------------------------------
# Combat encounters
# ---------------------------------------------------------------------------

_COMBAT_RE = re.compile(
    r"(.+?):\s*COMBAT SKILL\s*(\d+)\s+ENDURANCE\s*(\d+)",
    re.IGNORECASE,
)


def extract_combat_encounters(scene_soup: Tag) -> list[CombatData]:
    """Extract combat encounters from ``<p class="combat">`` elements.

    Each combat paragraph is expected to follow the format::

        Enemy Name: COMBAT SKILL {cs}   ENDURANCE {end}

    Paragraphs that do not match the pattern are skipped with a warning.

    Args:
        scene_soup: The BeautifulSoup Tag representing a single scene block.

    Returns:
        A list of :class:`~app.parser.types.CombatData` instances in document
        order.  Returns an empty list when no combat paragraphs are found.
    """
    encounters: list[CombatData] = []

    for ordinal, p in enumerate(scene_soup.find_all("p", class_="combat"), start=1):
        if not isinstance(p, Tag):
            continue
        text = p.get_text(" ", strip=True)
        m = _COMBAT_RE.match(text)
        if not m:
            logger.warning("Could not parse combat element: %r", text[:120])
            continue
        encounters.append(
            CombatData(
                enemy_name=m.group(1).strip(),
                enemy_cs=int(m.group(2)),
                enemy_end=int(m.group(3)),
                ordinal=ordinal,
            )
        )

    return encounters


# ---------------------------------------------------------------------------
# Combat Results Table (CRT)
# ---------------------------------------------------------------------------

_KILL_RE = re.compile(r"^k$", re.IGNORECASE)
_RATIO_HEADER_RE = re.compile(r"^([+-]?\d+)\s+to\s+([+-]?\d+)$", re.IGNORECASE)


def extract_crt(soup: BeautifulSoup) -> list[CRTRow]:
    """Parse the Combat Results Table from the book's rules section.

    Locates the table via ``<a name="crtable">`` and parses header columns
    (combat ratio brackets) together with data rows (random number 0–9 and
    enemy/hero loss pairs).

    Cell values follow the pattern ``{enemy_loss}/{hero_loss}``.  A value of
    ``k`` represents a kill (stored as ``None``).

    Args:
        soup: A parsed BeautifulSoup document.

    Returns:
        A list of :class:`~app.parser.types.CRTRow` instances, one per
        (random_number × ratio_bracket) combination.  Returns an empty list
        when the CRT section cannot be located.
    """
    anchor = soup.find("a", attrs={"name": "crtable"})
    if not anchor:
        logger.debug("CRT anchor not found in document")
        return []

    table: Tag | None = None

    # Strategy 1: the anchor is inside a <table> already
    node = anchor.parent
    while node and node.name not in ("body", "html", "[document]"):
        if isinstance(node, Tag) and node.name == "table":
            table = node
            break
        node = node.parent  # type: ignore[assignment]

    # Strategy 2: search forward from the anchor through siblings for a <table>
    if table is None:
        for sibling in anchor.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name == "table":
                    table = sibling
                    break
                # Table may be nested in a sibling container
                t = sibling.find("table")
                if t and isinstance(t, Tag):
                    table = t
                    break

    # Strategy 3: search from anchor's parent element downward
    if table is None and anchor.parent and isinstance(anchor.parent, Tag):
        t = anchor.parent.find("table")
        if t and isinstance(t, Tag):
            table = t

    if table is None:
        logger.warning("CRT table not found near <a name='crtable'>")
        return []

    return _parse_crt_table(table)


def _parse_crt_table(table: Tag) -> list[CRTRow]:
    """Parse a CRT ``<table>`` element into a flat list of :class:`CRTRow`."""
    rows_tags = table.find_all("tr")
    if not rows_tags:
        return []

    # First row is the header — extract ratio bracket columns
    header_cells = rows_tags[0].find_all(["th", "td"])
    brackets: list[tuple[int, int]] = []

    for cell in header_cells[1:]:  # skip first cell ("Random Number" label)
        text = cell.get_text(strip=True)
        m = _RATIO_HEADER_RE.match(text)
        if m:
            brackets.append((int(m.group(1)), int(m.group(2))))
        else:
            # Try simpler single-number column (some editions)
            if text.lstrip("+-").isdigit():
                n = int(text)
                brackets.append((n, n))

    if not brackets:
        logger.warning("Could not parse CRT header columns")
        return []

    rows: list[CRTRow] = []

    for tr in rows_tags[1:]:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue
        rn_text = cells[0].get_text(strip=True)
        if not rn_text.isdigit():
            continue
        random_number = int(rn_text)

        for col_idx, (ratio_min, ratio_max) in enumerate(brackets):
            if col_idx + 1 >= len(cells):
                break
            cell_text = cells[col_idx + 1].get_text(strip=True)
            enemy_loss, hero_loss = _parse_crt_cell(cell_text)
            rows.append(
                CRTRow(
                    random_number=random_number,
                    combat_ratio_min=ratio_min,
                    combat_ratio_max=ratio_max,
                    enemy_loss=enemy_loss,
                    hero_loss=hero_loss,
                )
            )

    return rows


def _parse_crt_cell(text: str) -> tuple[int | None, int | None]:
    """Parse a CRT cell value like ``"4/6"``, ``"k/0"``, or ``"0/k"``."""
    if "/" not in text:
        return None, None
    parts = text.split("/", 1)
    enemy_raw = parts[0].strip()
    hero_raw = parts[1].strip()
    enemy_loss = None if _KILL_RE.match(enemy_raw) else (int(enemy_raw) if enemy_raw.isdigit() else None)
    hero_loss = None if _KILL_RE.match(hero_raw) else (int(hero_raw) if hero_raw.isdigit() else None)
    return enemy_loss, hero_loss


# ---------------------------------------------------------------------------
# Disciplines
# ---------------------------------------------------------------------------

def extract_disciplines(soup: BeautifulSoup) -> list[DisciplineData]:
    """Extract discipline definitions from the book's front matter.

    Locates the disciplines section via ``<a name="discplnz">`` and then reads
    each ``<h4>`` (discipline name) together with the ``<p>`` elements that
    follow it up to the next ``<h4>``.

    Args:
        soup: A parsed BeautifulSoup document.

    Returns:
        A list of :class:`~app.parser.types.DisciplineData` instances.
        Returns an empty list when the disciplines section cannot be found.
    """
    anchor = soup.find("a", attrs={"name": "discplnz"})
    if not anchor:
        logger.debug("Disciplines anchor not found in document")
        return []

    # Navigate to a container element that holds the discipline list
    container = anchor.parent
    if container is None:
        return []

    # Collect sibling elements from the anchor's parent level
    disciplines: list[DisciplineData] = []

    # Walk siblings of the anchor's parent to find h4 + p groups
    _collect_disciplines_from_container(container, disciplines)

    # If nothing found from direct container, try the grandparent
    if not disciplines and container.parent:
        _collect_disciplines_from_container(container.parent, disciplines)

    return disciplines


def _collect_disciplines_from_container(container: Tag, out: list[DisciplineData]) -> None:
    """Scan container children for h4/p discipline groups and append to out."""
    h4_tags = container.find_all("h4")
    for h4 in h4_tags:
        if not isinstance(h4, Tag):
            continue
        # Extract html_id from inner anchor
        inner_a = h4.find("a")
        html_id = ""
        if inner_a and isinstance(inner_a, Tag):
            name_attr = inner_a.get("name", "")
            if isinstance(name_attr, list):
                name_attr = name_attr[0] if name_attr else ""
            html_id = str(name_attr)

        name = h4.get_text(strip=True)

        # Collect <p> siblings until the next <h4>
        desc_parts: list[str] = []
        for sibling in h4.next_siblings:
            if isinstance(sibling, Tag):
                if sibling.name == "h4":
                    break
                if sibling.name == "p":
                    desc_parts.append(sibling.get_text(" ", strip=True))

        description = " ".join(desc_parts).strip()
        if name:
            out.append(DisciplineData(name=name, html_id=html_id, description=description))


# ---------------------------------------------------------------------------
# Starting equipment
# ---------------------------------------------------------------------------

def extract_starting_equipment(soup: BeautifulSoup) -> list[EquipmentData]:
    """Parse the starting equipment list from the book's rules section.

    Locates an equipment-related anchor (e.g. ``<a name="equipmnt">``) and
    extracts ``<li>`` items from the nearest list element.  Item types are
    inferred from item name keywords.

    Args:
        soup: A parsed BeautifulSoup document.

    Returns:
        A list of :class:`~app.parser.types.EquipmentData` instances.
        Returns an empty list when the equipment section cannot be found or
        contains no list items.
    """
    # Try several anchor names used across books
    anchor = None
    for name in ("equipmnt", "equipment", "equip"):
        anchor = soup.find("a", attrs={"name": name})
        if anchor:
            break

    if not anchor:
        logger.debug("Equipment anchor not found in document")
        return []

    container = anchor.parent
    if container is None:
        return []

    # Find the nearest list (ul or ol) in the container or its siblings
    ul = container.find(["ul", "ol"])
    if not ul:
        # Try next siblings of container
        for sibling in container.next_siblings:
            if isinstance(sibling, Tag) and sibling.name in ("ul", "ol"):
                ul = sibling
                break
            if isinstance(sibling, Tag) and sibling.name in ("h2", "h3", "h4"):
                break  # new section started

    if ul is None or not isinstance(ul, Tag):
        logger.debug("Equipment list not found near equipment anchor")
        return []

    equipment: list[EquipmentData] = []
    for li in ul.find_all("li"):
        if not isinstance(li, Tag):
            continue
        item_name = li.get_text(" ", strip=True)
        if not item_name:
            continue
        item_type = _classify_equipment_type(item_name)
        equipment.append(EquipmentData(item_name=item_name, item_type=item_type, quantity=1))

    return equipment


_WEAPON_KEYWORDS = frozenset(
    ["sword", "dagger", "spear", "mace", "axe", "bow", "quiver", "arrow", "knife", "warhammer"]
)
_MEAL_KEYWORDS = frozenset(["meal", "food", "ration"])
_GOLD_KEYWORDS = frozenset(["gold", "crown", "coin"])


def _classify_equipment_type(item_name: str) -> str:
    """Heuristically classify an equipment item name into an item type."""
    lower = item_name.lower()
    if any(k in lower for k in _WEAPON_KEYWORDS):
        return "weapon"
    if any(k in lower for k in _MEAL_KEYWORDS):
        return "meal"
    if any(k in lower for k in _GOLD_KEYWORDS):
        return "gold"
    return "backpack"


# ---------------------------------------------------------------------------
# Illustration copying
# ---------------------------------------------------------------------------

def copy_illustrations(xhtml_dir: Path, book_slug: str, dest_dir: Path) -> list[Path]:
    """Copy illustration images from the XHTML source directory to dest_dir.

    Scans for ``*.png``, ``*.jpg``, ``*.jpeg``, and ``*.gif`` files under
    *xhtml_dir* and copies them to ``dest_dir / book_slug /``.  The
    destination directory is created if it does not exist.

    Args:
        xhtml_dir: Directory containing the unpacked XHTML source files.
        book_slug: The book slug used to name the destination sub-directory.
        dest_dir: Root destination directory (e.g. ``static/images``).

    Returns:
        A list of destination paths for all copied files.
    """
    book_dest = dest_dir / book_slug
    book_dest.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.gif"):
        for src in xhtml_dir.glob(pattern):
            dst = book_dest / src.name
            shutil.copy2(src, dst)
            copied.append(dst)
            logger.debug("Copied illustration %s → %s", src.name, dst)

    return copied


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_xhtml(path: Path) -> BeautifulSoup:
    """Read *path* and return a parsed BeautifulSoup tree."""
    content = path.read_text(encoding="utf-8", errors="replace")
    return BeautifulSoup(content, "html.parser")
