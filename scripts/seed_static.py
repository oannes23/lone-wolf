"""Static seed data script — idempotent loader for all reference data.

Populates: books, disciplines, combat_results, weapon_categories,
wizard_templates + steps, book_transition_rules, book_starting_equipment.

Usage:
    JWT_SECRET=dev-secret uv run python scripts/seed_static.py
"""

import sys
from pathlib import Path

# Ensure project root is on sys.path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, SessionLocal, engine
from app.models import (
    Book,
    BookStartingEquipment,
    BookTransitionRule,
    CombatResults,
    Discipline,
    WeaponCategory,
    WizardTemplate,
    WizardTemplateStep,
)

# ---------------------------------------------------------------------------
# Seed data definitions
# ---------------------------------------------------------------------------

BOOKS = [
    {
        "slug": "01fftd",
        "number": 1,
        "title": "Flight from the Dark",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 1,
    },
    {
        "slug": "02fotw",
        "number": 2,
        "title": "Fire on the Water",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 2,
    },
    {
        "slug": "03tcok",
        "number": 3,
        "title": "The Caverns of Kalte",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 2,
    },
    {
        "slug": "04tcod",
        "number": 4,
        "title": "The Chasm of Doom",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 6,
    },
    {
        "slug": "05sots",
        "number": 5,
        "title": "Shadow on the Sand",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 4,
    },
]

# Project Aon html_ids follow the abbreviated anchor convention from Book 1 XHTML.
DISCIPLINES = [
    {
        "era": "kai",
        "name": "Camouflage",
        "html_id": "camflage",
        "description": (
            "This Discipline enables Lone Wolf to blend in with his natural "
            "surroundings. In the countryside, he can hide undetected among trees and "
            "rocks; in towns, he can use his knowledge of light and shade to avoid "
            "being seen."
        ),
        "mechanical_effect": "Unlocks discipline-gated choices",
    },
    {
        "era": "kai",
        "name": "Hunting",
        "html_id": "hunting",
        "description": (
            "This Discipline ensures that Lone Wolf will never starve in the "
            "wild. He will always be able to hunt for food except in a town "
            "or city, or in a dungeon environment."
        ),
        "mechanical_effect": "No meal consumed when eating in the wild",
    },
    {
        "era": "kai",
        "name": "Sixth Sense",
        "html_id": "sixthsns",
        "description": (
            "This Discipline gives Lone Wolf a feeling of unease when danger "
            "is near. In some adventures, it may also reveal useful "
            "information about Lone Wolf's environment."
        ),
        "mechanical_effect": "Unlocks discipline-gated choices",
    },
    {
        "era": "kai",
        "name": "Tracking",
        "html_id": "tracking",
        "description": (
            "This Discipline allows Lone Wolf to track almost any creature "
            "across any type of terrain. It also means he will rarely lose "
            "his way in the wild."
        ),
        "mechanical_effect": "Unlocks discipline-gated choices",
    },
    {
        "era": "kai",
        "name": "Healing",
        "html_id": "healing",
        "description": (
            "This Discipline enables Lone Wolf to accelerate his own body's "
            "healing rate. At the start of each new adventure, or after "
            "any particularly traumatic experience, he may restore lost "
            "ENDURANCE points."
        ),
        "mechanical_effect": "+1 END per scene if no combat occurred (up to endurance_max)",
    },
    {
        "era": "kai",
        "name": "Weaponskill",
        "html_id": "wpnskll",
        "description": (
            "Upon entering the Kai Monastery, Lone Wolf chose to master one "
            "of the weapons listed below. With that weapon, he gains a +2 "
            "bonus to his COMBAT SKILL when it is used in combat."
        ),
        "mechanical_effect": "+2 CS when equipped weapon category matches chosen type",
    },
    {
        "era": "kai",
        "name": "Mindshield",
        "html_id": "mndshld",
        "description": (
            "The Darklords of Helgedad have developed the ability to attack "
            "and kill by use of their minds alone. The Kai Discipline of "
            "Mindshield prevents Lone Wolf from losing any COMBAT SKILL "
            "points when he is attacked in this way."
        ),
        "mechanical_effect": "Immune to -2 CS penalty from enemy Mindblast",
    },
    {
        "era": "kai",
        "name": "Mindblast",
        "html_id": "mndblst",
        "description": (
            "This Kai Discipline enables Lone Wolf to attack an enemy using "
            "the force of his mind. It adds +2 to his COMBAT SKILL when "
            "used in combat against an enemy who is not immune to Mindblast."
        ),
        "mechanical_effect": "+2 CS in combat unless enemy is mindblast_immune",
    },
    {
        "era": "kai",
        "name": "Animal Kinship",
        "html_id": "anmlknd",
        "description": (
            "This Discipline gives Lone Wolf the ability to communicate with "
            "animals. On several occasions, this skill may also prove useful "
            "in calming wild or hostile creatures."
        ),
        "mechanical_effect": "Unlocks discipline-gated choices",
    },
    {
        "era": "kai",
        "name": "Mind Over Matter",
        "html_id": "mndovmtr",
        "description": (
            "Mastery of this Discipline enables Lone Wolf to move small "
            "objects with the power of his mind alone."
        ),
        "mechanical_effect": "Unlocks discipline-gated choices",
    },
]

# 130 rows: 13 combat ratio brackets x 10 random numbers (0-9).
# NULL (None) represents an instant kill.
# Sentinel values: combat_ratio_min=-999 for bracket 1 (CR <= -11),
#                  combat_ratio_max=999 for bracket 13 (CR >= +11).
COMBAT_RESULTS = [
    # random_number 0
    ("kai", 0, -999, -11, 6, None),
    ("kai", 0, -10, -9, 7, None),
    ("kai", 0, -8, -7, 8, None),
    ("kai", 0, -6, -5, 9, None),
    ("kai", 0, -4, -3, 10, None),
    ("kai", 0, -2, -1, 11, None),
    ("kai", 0, 0, 0, 12, None),
    ("kai", 0, 1, 2, 14, None),
    ("kai", 0, 3, 4, 16, None),
    ("kai", 0, 5, 6, 18, None),
    ("kai", 0, 7, 8, None, None),
    ("kai", 0, 9, 10, None, None),
    ("kai", 0, 11, 999, None, None),
    # random_number 1
    ("kai", 1, -999, -11, 0, None),
    ("kai", 1, -10, -9, 0, 8),
    ("kai", 1, -8, -7, 0, 8),
    ("kai", 1, -6, -5, 1, 7),
    ("kai", 1, -4, -3, 2, 6),
    ("kai", 1, -2, -1, 3, 6),
    ("kai", 1, 0, 0, 4, 5),
    ("kai", 1, 1, 2, 5, 5),
    ("kai", 1, 3, 4, 6, 4),
    ("kai", 1, 5, 6, 7, 4),
    ("kai", 1, 7, 8, 8, 3),
    ("kai", 1, 9, 10, 9, 3),
    ("kai", 1, 11, 999, 10, 2),
    # random_number 2
    ("kai", 2, -999, -11, 0, None),
    ("kai", 2, -10, -9, 0, 8),
    ("kai", 2, -8, -7, 1, 7),
    ("kai", 2, -6, -5, 2, 6),
    ("kai", 2, -4, -3, 3, 6),
    ("kai", 2, -2, -1, 4, 5),
    ("kai", 2, 0, 0, 5, 5),
    ("kai", 2, 1, 2, 6, 4),
    ("kai", 2, 3, 4, 7, 4),
    ("kai", 2, 5, 6, 8, 3),
    ("kai", 2, 7, 8, 9, 3),
    ("kai", 2, 9, 10, 10, 2),
    ("kai", 2, 11, 999, 11, 2),
    # random_number 3
    ("kai", 3, -999, -11, 0, 6),
    ("kai", 3, -10, -9, 1, 6),
    ("kai", 3, -8, -7, 2, 5),
    ("kai", 3, -6, -5, 3, 5),
    ("kai", 3, -4, -3, 4, 5),
    ("kai", 3, -2, -1, 5, 4),
    ("kai", 3, 0, 0, 6, 4),
    ("kai", 3, 1, 2, 7, 4),
    ("kai", 3, 3, 4, 8, 3),
    ("kai", 3, 5, 6, 9, 3),
    ("kai", 3, 7, 8, 10, 2),
    ("kai", 3, 9, 10, 11, 2),
    ("kai", 3, 11, 999, 12, 1),
    # random_number 4
    ("kai", 4, -999, -11, 0, 6),
    ("kai", 4, -10, -9, 2, 5),
    ("kai", 4, -8, -7, 3, 5),
    ("kai", 4, -6, -5, 4, 4),
    ("kai", 4, -4, -3, 5, 4),
    ("kai", 4, -2, -1, 6, 4),
    ("kai", 4, 0, 0, 7, 3),
    ("kai", 4, 1, 2, 8, 3),
    ("kai", 4, 3, 4, 9, 3),
    ("kai", 4, 5, 6, 10, 2),
    ("kai", 4, 7, 8, 11, 2),
    ("kai", 4, 9, 10, 12, 1),
    ("kai", 4, 11, 999, 14, 1),
    # random_number 5
    ("kai", 5, -999, -11, 1, 6),
    ("kai", 5, -10, -9, 3, 5),
    ("kai", 5, -8, -7, 4, 4),
    ("kai", 5, -6, -5, 5, 4),
    ("kai", 5, -4, -3, 6, 3),
    ("kai", 5, -2, -1, 7, 3),
    ("kai", 5, 0, 0, 8, 3),
    ("kai", 5, 1, 2, 9, 2),
    ("kai", 5, 3, 4, 10, 2),
    ("kai", 5, 5, 6, 11, 2),
    ("kai", 5, 7, 8, 12, 1),
    ("kai", 5, 9, 10, 14, 1),
    ("kai", 5, 11, 999, 16, 0),
    # random_number 6
    ("kai", 6, -999, -11, 2, 5),
    ("kai", 6, -10, -9, 4, 4),
    ("kai", 6, -8, -7, 5, 4),
    ("kai", 6, -6, -5, 6, 3),
    ("kai", 6, -4, -3, 7, 3),
    ("kai", 6, -2, -1, 8, 2),
    ("kai", 6, 0, 0, 9, 2),
    ("kai", 6, 1, 2, 10, 2),
    ("kai", 6, 3, 4, 11, 1),
    ("kai", 6, 5, 6, 12, 1),
    ("kai", 6, 7, 8, 14, 0),
    ("kai", 6, 9, 10, 16, 0),
    ("kai", 6, 11, 999, 18, 0),
    # random_number 7
    ("kai", 7, -999, -11, 3, 5),
    ("kai", 7, -10, -9, 5, 4),
    ("kai", 7, -8, -7, 6, 3),
    ("kai", 7, -6, -5, 7, 3),
    ("kai", 7, -4, -3, 8, 2),
    ("kai", 7, -2, -1, 9, 2),
    ("kai", 7, 0, 0, 10, 2),
    ("kai", 7, 1, 2, 11, 1),
    ("kai", 7, 3, 4, 12, 1),
    ("kai", 7, 5, 6, 14, 0),
    ("kai", 7, 7, 8, 16, 0),
    ("kai", 7, 9, 10, 18, 0),
    ("kai", 7, 11, 999, None, 0),
    # random_number 8
    ("kai", 8, -999, -11, 4, 4),
    ("kai", 8, -10, -9, 6, 3),
    ("kai", 8, -8, -7, 7, 3),
    ("kai", 8, -6, -5, 8, 2),
    ("kai", 8, -4, -3, 9, 2),
    ("kai", 8, -2, -1, 10, 2),
    ("kai", 8, 0, 0, 11, 1),
    ("kai", 8, 1, 2, 12, 1),
    ("kai", 8, 3, 4, 14, 0),
    ("kai", 8, 5, 6, 16, 0),
    ("kai", 8, 7, 8, 18, 0),
    ("kai", 8, 9, 10, None, 0),
    ("kai", 8, 11, 999, None, 0),
    # random_number 9
    ("kai", 9, -999, -11, 5, 4),
    ("kai", 9, -10, -9, 7, 3),
    ("kai", 9, -8, -7, 8, 2),
    ("kai", 9, -6, -5, 9, 2),
    ("kai", 9, -4, -3, 10, 1),
    ("kai", 9, -2, -1, 11, 1),
    ("kai", 9, 0, 0, 12, 0),
    ("kai", 9, 1, 2, 14, 0),
    ("kai", 9, 3, 4, 16, 0),
    ("kai", 9, 5, 6, 18, 0),
    ("kai", 9, 7, 8, None, 0),
    ("kai", 9, 9, 10, None, 0),
    ("kai", 9, 11, 999, None, 0),
]

WEAPON_CATEGORIES = [
    ("Sword", "Sword"),
    ("Broadsword", "Sword"),
    ("Short Sword", "Sword"),
    ("Sommerswerd", "Sword"),
    ("Axe", "Axe"),
    ("Mace", "Mace"),
    ("Spear", "Spear"),
    ("Magic Spear", "Spear"),
    ("Dagger", "Dagger"),
    ("Quarterstaff", "Quarterstaff"),
    ("Warhammer", "Warhammer"),
]

WIZARD_TEMPLATES = [
    {
        "name": "character_creation",
        "description": "Wizard for new character equipment selection at the start of Book 1.",
        "steps": [
            {"step_type": "pick_equipment", "ordinal": 0, "config": None},
            {"step_type": "confirm", "ordinal": 1, "config": None},
        ],
    },
    {
        "name": "book_advance",
        "description": "Wizard for advancing a character to the next book.",
        "steps": [
            {"step_type": "pick_disciplines", "ordinal": 0, "config": '{"count": 1}'},
            {"step_type": "pick_equipment", "ordinal": 1, "config": None},
            {"step_type": "inventory_adjust", "ordinal": 2, "config": None},
            {"step_type": "confirm", "ordinal": 3, "config": None},
        ],
    },
]

# (from_book_number, to_book_number, max_weapons, max_backpack_items,
#  special_items_carry, gold_carries, new_disciplines_count, notes)
TRANSITION_RULES = [
    (1, 2, 2, 8, True, True, 1, "Player may exchange carried weapons during equipment selection"),
    (2, 3, 2, 8, True, True, 1, "Player may exchange carried weapons during equipment selection"),
    (3, 4, 2, 8, True, True, 1, "Player may exchange carried weapons during equipment selection"),
    (4, 5, 2, 8, True, True, 1, "Player may exchange carried weapons during equipment selection"),
]

# Starting equipment by book number.
# Format: (book_number, item_name, item_type, category, is_default)
STARTING_EQUIPMENT = [
    # Book 1 — Flight from the Dark
    # Fixed items (is_default=True)
    (1, "Axe", "weapon", "weapons", True),
    (1, "Map of Sommerlund", "special", "special", True),
    # Chooseable items (is_default=False)
    (1, "Broadsword", "weapon", "weapons", False),
    (1, "Sword", "weapon", "weapons", False),
    (1, "Helmet", "special", "special", False),
    (1, "Meal", "meal", "meals", False),
    (1, "Chainmail Waistcoat", "special", "special", False),
    (1, "Mace", "weapon", "weapons", False),
    (1, "Healing Potion", "backpack", "backpack", False),
    (1, "Quarterstaff", "weapon", "weapons", False),
    (1, "Spear", "weapon", "weapons", False),
    (1, "Gold Crowns", "gold", "gold", False),
    # Book 2 — Fire on the Water
    # Fixed items
    (2, "Seal of Hammerdal", "special", "special", True),
    # Chooseable items
    (2, "Sword", "weapon", "weapons", False),
    (2, "Short Sword", "weapon", "weapons", False),
    (2, "Meal", "meal", "meals", False),
    (2, "Chainmail Waistcoat", "special", "special", False),
    (2, "Mace", "weapon", "weapons", False),
    (2, "Healing Potion", "backpack", "backpack", False),
    (2, "Quarterstaff", "weapon", "weapons", False),
    (2, "Spear", "weapon", "weapons", False),
    (2, "Shield", "special", "special", False),
    (2, "Broadsword", "weapon", "weapons", False),
    # Book 3 — The Caverns of Kalte
    # Fixed items
    (3, "Map of Kalte", "special", "special", True),
    # Chooseable items
    (3, "Sword", "weapon", "weapons", False),
    (3, "Short Sword", "weapon", "weapons", False),
    (3, "Padded Leather Waistcoat", "special", "special", False),
    (3, "Spear", "weapon", "weapons", False),
    (3, "Mace", "weapon", "weapons", False),
    (3, "Warhammer", "weapon", "weapons", False),
    (3, "Axe", "weapon", "weapons", False),
    (3, "Potion of Laumspur", "backpack", "backpack", False),
    (3, "Quarterstaff", "weapon", "weapons", False),
    (3, "Meal", "meal", "meals", False),
    (3, "Broadsword", "weapon", "weapons", False),
    # Book 4 — The Chasm of Doom
    # Fixed items
    (4, "Map of the Southlands", "special", "special", True),
    # Chooseable items
    (4, "Warhammer", "weapon", "weapons", False),
    (4, "Dagger", "weapon", "weapons", False),
    (4, "Potion of Laumspur", "backpack", "backpack", False),
    (4, "Sword", "weapon", "weapons", False),
    (4, "Spear", "weapon", "weapons", False),
    (4, "Meal", "meal", "meals", False),
    (4, "Mace", "weapon", "weapons", False),
    (4, "Chainmail Waistcoat", "special", "special", False),
    (4, "Shield", "special", "special", False),
    # Book 5 — Shadow on the Sand
    # Fixed items
    (5, "Map of the Desert Empire", "special", "special", True),
    # Chooseable items
    (5, "Dagger", "weapon", "weapons", False),
    (5, "Potion of Laumspur", "backpack", "backpack", False),
    (5, "Sword", "weapon", "weapons", False),
    (5, "Spear", "weapon", "weapons", False),
    (5, "Meal", "meal", "meals", False),
    (5, "Mace", "weapon", "weapons", False),
    (5, "Shield", "special", "special", False),
]


# ---------------------------------------------------------------------------
# Upsert helpers
# ---------------------------------------------------------------------------


def upsert_book(db, data: dict) -> Book:
    """Insert or update a Book row keyed on slug."""
    existing = db.query(Book).filter_by(slug=data["slug"]).first()
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        return existing
    book = Book(**data)
    db.add(book)
    return book


def upsert_discipline(db, data: dict) -> Discipline:
    """Insert or update a Discipline row keyed on (era, name)."""
    existing = db.query(Discipline).filter_by(era=data["era"], name=data["name"]).first()
    if existing:
        for k, v in data.items():
            setattr(existing, k, v)
        return existing
    disc = Discipline(**data)
    db.add(disc)
    return disc


def upsert_combat_result(
    db,
    era: str,
    random_number: int,
    combat_ratio_min: int,
    combat_ratio_max: int,
    enemy_loss: int | None,
    hero_loss: int | None,
) -> CombatResults:
    """Insert or update a CombatResults row keyed on (era, random_number, combat_ratio_min)."""
    existing = (
        db.query(CombatResults)
        .filter_by(era=era, random_number=random_number, combat_ratio_min=combat_ratio_min)
        .first()
    )
    if existing:
        existing.combat_ratio_max = combat_ratio_max
        existing.enemy_loss = enemy_loss
        existing.hero_loss = hero_loss
        return existing
    row = CombatResults(
        era=era,
        random_number=random_number,
        combat_ratio_min=combat_ratio_min,
        combat_ratio_max=combat_ratio_max,
        enemy_loss=enemy_loss,
        hero_loss=hero_loss,
    )
    db.add(row)
    return row


def upsert_weapon_category(db, weapon_name: str, category: str) -> WeaponCategory:
    """Insert or update a WeaponCategory row keyed on weapon_name."""
    existing = db.query(WeaponCategory).filter_by(weapon_name=weapon_name).first()
    if existing:
        existing.category = category
        return existing
    wc = WeaponCategory(weapon_name=weapon_name, category=category)
    db.add(wc)
    return wc


def upsert_wizard_template(db, data: dict) -> WizardTemplate:
    """Insert or update a WizardTemplate and its steps, keyed on name."""
    existing = db.query(WizardTemplate).filter_by(name=data["name"]).first()
    if existing:
        existing.description = data.get("description")
        template = existing
        # Remove old steps and re-insert to keep them consistent.
        for step in list(template.steps):
            db.delete(step)
        db.flush()
    else:
        template = WizardTemplate(name=data["name"], description=data.get("description"))
        db.add(template)
        db.flush()

    for step_data in data["steps"]:
        step = WizardTemplateStep(
            template_id=template.id,
            step_type=step_data["step_type"],
            ordinal=step_data["ordinal"],
            config=step_data.get("config"),
        )
        db.add(step)

    return template


def upsert_transition_rule(
    db,
    from_book: Book,
    to_book: Book,
    max_weapons: int,
    max_backpack_items: int,
    special_items_carry: bool,
    gold_carries: bool,
    new_disciplines_count: int,
    notes: str | None,
) -> BookTransitionRule:
    """Insert or update a BookTransitionRule keyed on (from_book_id, to_book_id)."""
    existing = (
        db.query(BookTransitionRule)
        .filter_by(from_book_id=from_book.id, to_book_id=to_book.id)
        .first()
    )
    if existing:
        existing.max_weapons = max_weapons
        existing.max_backpack_items = max_backpack_items
        existing.special_items_carry = special_items_carry
        existing.gold_carries = gold_carries
        existing.new_disciplines_count = new_disciplines_count
        existing.notes = notes
        return existing
    rule = BookTransitionRule(
        from_book_id=from_book.id,
        to_book_id=to_book.id,
        max_weapons=max_weapons,
        max_backpack_items=max_backpack_items,
        special_items_carry=special_items_carry,
        gold_carries=gold_carries,
        new_disciplines_count=new_disciplines_count,
        base_cs_override=None,
        base_end_override=None,
        notes=notes,
    )
    db.add(rule)
    return rule


def seed_starting_equipment(db, book_number_map: dict[int, Book]) -> int:
    """Replace all BookStartingEquipment rows for all seeded books.

    Uses a delete-then-reinsert strategy per book since there is no natural
    unique key on this table other than (book_id, item_name, is_default).
    """
    total = 0
    for book_number, items in _group_equipment_by_book():
        book = book_number_map[book_number]
        # Delete existing rows for this book before reinserting.
        db.query(BookStartingEquipment).filter_by(book_id=book.id).delete()
        db.flush()
        for item_name, item_type, category, is_default in items:
            row = BookStartingEquipment(
                book_id=book.id,
                game_object_id=None,
                item_name=item_name,
                item_type=item_type,
                category=category,
                is_default=is_default,
                source="manual",
            )
            db.add(row)
            total += 1
    return total


def _group_equipment_by_book() -> list[tuple[int, list[tuple]]]:
    """Return STARTING_EQUIPMENT grouped by book number, preserving order."""
    groups: dict[int, list] = {}
    for book_num, item_name, item_type, category, is_default in STARTING_EQUIPMENT:
        groups.setdefault(book_num, []).append((item_name, item_type, category, is_default))
    return sorted(groups.items())


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def seed_all(db) -> None:
    """Seed all static reference data into the given session (no commit)."""
    # 1. Books
    book_number_map: dict[int, Book] = {}
    for book_data in BOOKS:
        book = upsert_book(db, book_data)
        db.flush()
        book_number_map[book_data["number"]] = book
    db.flush()

    # 2. Disciplines
    for disc_data in DISCIPLINES:
        upsert_discipline(db, disc_data)
    db.flush()

    # 3. CRT
    for row in COMBAT_RESULTS:
        upsert_combat_result(db, *row)
    db.flush()

    # 4. Weapon categories
    for weapon_name, category in WEAPON_CATEGORIES:
        upsert_weapon_category(db, weapon_name, category)
    db.flush()

    # 5. Wizard templates
    for tmpl_data in WIZARD_TEMPLATES:
        upsert_wizard_template(db, tmpl_data)
    db.flush()

    # 6. Book transition rules
    for rule in TRANSITION_RULES:
        from_num, to_num, max_w, max_bp, sp_carry, gold_carry, new_disc, notes = rule
        from_book = book_number_map[from_num]
        to_book = book_number_map[to_num]
        upsert_transition_rule(
            db, from_book, to_book, max_w, max_bp, sp_carry, gold_carry, new_disc, notes
        )
    db.flush()

    # 7. Starting equipment
    seed_starting_equipment(db, book_number_map)


def run_seed() -> None:
    """Run all seed operations and print a summary."""
    # Ensure all tables exist (safe no-op if already present).
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_all(db)
        db.commit()

        # Verification counts from DB
        print("Seeded static reference data:")
        print(f"  books:                    {db.query(Book).count()}")
        print(f"  disciplines:              {db.query(Discipline).count()}")
        print(f"  combat_results:           {db.query(CombatResults).count()}")
        print(f"  weapon_categories:        {db.query(WeaponCategory).count()}")
        print(f"  wizard_templates:         {db.query(WizardTemplate).count()}")
        print(f"  wizard_template_steps:    {db.query(WizardTemplateStep).count()}")
        print(f"  book_transition_rules:    {db.query(BookTransitionRule).count()}")
        print(f"  book_starting_equipment:  {db.query(BookStartingEquipment).count()}")

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    print("Seeding static reference data...")
    run_seed()
    print("\nDone.")
