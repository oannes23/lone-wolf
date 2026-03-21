"""Minimal reference data for test sessions.

Call ``load_test_fixtures(db)`` in a test or fixture to populate:
- 10 Kai-era disciplines
- Sample CRT rows (bracket CR=0, all 10 random numbers)
- 11 weapon categories
- 2 wizard templates with steps
- Book 1 stub
"""

from sqlalchemy.orm import Session

from app.models.content import Book, CombatResults, Discipline, WeaponCategory
from app.models.wizard import WizardTemplate, WizardTemplateStep

# ---------------------------------------------------------------------------
# Kai disciplines (10 canonical rows)
# ---------------------------------------------------------------------------

_KAI_DISCIPLINES = [
    ("Camouflage", "camouflage", "The art of concealment and disguise in the wild."),
    ("Hunting", "hunting", "The ability to find game and live off the land."),
    ("Sixth Sense", "sixth-sense", "An intuition for danger and hidden truths."),
    ("Tracking", "tracking", "The skill of following trails through any terrain."),
    ("Healing", "healing", "The power to accelerate the body's natural recovery."),
    ("Weaponskill", "weaponskill", "Mastery with one chosen weapon type."),
    ("Mindshield", "mindshield", "Mental defence against psychic attacks."),
    ("Mindblast", "mindblast", "A psychic attack that drains an enemy's willpower."),
    ("Animal Kinship", "animal-kinship", "Empathy with animals of all kinds."),
    ("Mind Over Matter", "mind-over-matter", "Telekinetic manipulation of objects."),
]

# ---------------------------------------------------------------------------
# Sample CRT data — bracket CR=0 (combat_ratio_min=-999, combat_ratio_max=0)
# for all 10 Lone Wolf random numbers (0-9).
# Values taken from the Kai-era CRT for the CR <= 0 column.
# ---------------------------------------------------------------------------

_SAMPLE_CRT = [
    # (random_number, cr_min, cr_max, enemy_loss, hero_loss)
    (0, -999, 0, 0, 6),
    (1, -999, 0, 0, 7),
    (2, -999, 0, 0, 8),
    (3, -999, 0, 1, 8),
    (4, -999, 0, 1, 7),
    (5, -999, 0, 2, 8),
    (6, -999, 0, 2, 7),
    (7, -999, 0, 3, 8),
    (8, -999, 0, 3, 7),
    (9, -999, 0, 4, 8),
]

# ---------------------------------------------------------------------------
# Weapon categories — matches production seed_static.py
# ---------------------------------------------------------------------------

_WEAPON_CATEGORIES = [
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

# ---------------------------------------------------------------------------
# Wizard templates
# ---------------------------------------------------------------------------

_WIZARD_TEMPLATES = [
    {
        "name": "character_creation",
        "description": "Two-step wizard for creating a new character.",
        "steps": [
            {"step_type": "pick_equipment", "ordinal": 0},
            {"step_type": "confirm", "ordinal": 1},
        ],
    },
    {
        "name": "book_advance",
        "description": "Four-step wizard for advancing a character to the next book.",
        "steps": [
            {"step_type": "pick_disciplines", "ordinal": 0},
            {"step_type": "pick_equipment", "ordinal": 1},
            {"step_type": "inventory_adjust", "ordinal": 2},
            {"step_type": "confirm", "ordinal": 3},
        ],
    },
]


def load_test_fixtures(db: Session) -> dict[str, object]:
    """Populate minimal Kai-era reference data into the given session.

    Returns a dict of the created top-level objects keyed by descriptive name
    so callers can reference them:
        {
            "book1": Book,
            "disciplines": list[Discipline],
            "crt_rows": list[CombatResults],
            "weapon_categories": list[WeaponCategory],
            "wizard_templates": dict[str, WizardTemplate],
        }
    """
    # --- Book 1 stub ---
    book1 = Book(
        slug="01fftd",
        number=1,
        title="Flight from the Dark",
        era="kai",
        series="lone_wolf",
        start_scene_number=1,
        max_total_picks=1,
    )
    db.add(book1)
    db.flush()

    # --- Kai disciplines ---
    disciplines = []
    for name, html_id, description in _KAI_DISCIPLINES:
        disc = Discipline(
            era="kai",
            name=name,
            html_id=html_id,
            description=description,
        )
        db.add(disc)
        disciplines.append(disc)
    db.flush()

    # --- Sample CRT rows ---
    crt_rows = []
    for rn, cr_min, cr_max, enemy_loss, hero_loss in _SAMPLE_CRT:
        row = CombatResults(
            era="kai",
            random_number=rn,
            combat_ratio_min=cr_min,
            combat_ratio_max=cr_max,
            enemy_loss=enemy_loss,
            hero_loss=hero_loss,
        )
        db.add(row)
        crt_rows.append(row)
    db.flush()

    # --- Weapon categories ---
    weapon_categories = []
    for weapon_name, category in _WEAPON_CATEGORIES:
        wc = WeaponCategory(weapon_name=weapon_name, category=category)
        db.add(wc)
        weapon_categories.append(wc)
    db.flush()

    # --- Wizard templates ---
    wizard_templates: dict[str, WizardTemplate] = {}
    for tmpl_data in _WIZARD_TEMPLATES:
        tmpl = WizardTemplate(
            name=tmpl_data["name"],
            description=tmpl_data["description"],
        )
        db.add(tmpl)
        db.flush()
        for step_data in tmpl_data["steps"]:
            step = WizardTemplateStep(
                template_id=tmpl.id,
                step_type=step_data["step_type"],
                ordinal=step_data["ordinal"],
            )
            db.add(step)
        db.flush()
        wizard_templates[tmpl_data["name"]] = tmpl

    return {
        "book1": book1,
        "disciplines": disciplines,
        "crt_rows": crt_rows,
        "weapon_categories": weapon_categories,
        "wizard_templates": wizard_templates,
    }
