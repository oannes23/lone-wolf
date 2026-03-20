"""Integration tests for scripts/seed_static.py — idempotent seed verification."""

import pytest

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
from scripts.seed_static import seed_all


@pytest.fixture
def seeded_db(db):
    """Run the seed script against the test session."""
    seed_all(db)
    db.flush()
    return db


def _row_counts(db) -> dict[str, int]:
    """Return a dict of table name -> row count for all seeded tables."""
    return {
        "books": db.query(Book).count(),
        "disciplines": db.query(Discipline).count(),
        "combat_results": db.query(CombatResults).count(),
        "weapon_categories": db.query(WeaponCategory).count(),
        "wizard_templates": db.query(WizardTemplate).count(),
        "wizard_template_steps": db.query(WizardTemplateStep).count(),
        "book_transition_rules": db.query(BookTransitionRule).count(),
        "book_starting_equipment": db.query(BookStartingEquipment).count(),
    }


class TestSeedPopulatesAllTables:
    def test_books(self, seeded_db):
        assert seeded_db.query(Book).count() == 5

    def test_disciplines(self, seeded_db):
        assert seeded_db.query(Discipline).count() == 10

    def test_combat_results(self, seeded_db):
        assert seeded_db.query(CombatResults).count() == 130

    def test_weapon_categories(self, seeded_db):
        assert seeded_db.query(WeaponCategory).count() == 11

    def test_wizard_templates(self, seeded_db):
        assert seeded_db.query(WizardTemplate).count() == 2

    def test_wizard_template_steps(self, seeded_db):
        # character_creation: 2 steps, book_advance: 4 steps (removed pick_disciplines)
        # Actually from the data: 2 + 4 = 6
        assert seeded_db.query(WizardTemplateStep).count() == 6

    def test_transition_rules(self, seeded_db):
        assert seeded_db.query(BookTransitionRule).count() == 4

    def test_starting_equipment(self, seeded_db):
        count = seeded_db.query(BookStartingEquipment).count()
        assert count == len(
            [row for row in __import__("scripts.seed_static", fromlist=["STARTING_EQUIPMENT"]).STARTING_EQUIPMENT]
        )


class TestSeedIsIdempotent:
    def test_row_counts_unchanged_after_second_run(self, seeded_db):
        counts_first = _row_counts(seeded_db)
        # Run seed again on the same session
        seed_all(seeded_db)
        seeded_db.flush()
        counts_second = _row_counts(seeded_db)
        assert counts_first == counts_second


class TestCrtSentinelValues:
    def test_min_sentinel(self, seeded_db):
        rows = seeded_db.query(CombatResults).filter_by(combat_ratio_min=-999).all()
        assert len(rows) == 10  # one per random_number 0-9

    def test_max_sentinel(self, seeded_db):
        rows = seeded_db.query(CombatResults).filter_by(combat_ratio_max=999).all()
        assert len(rows) == 10  # one per random_number 0-9


class TestWizardStepsStable:
    def test_steps_not_duplicated_on_rerun(self, seeded_db):
        count_before = seeded_db.query(WizardTemplateStep).count()
        seed_all(seeded_db)
        seeded_db.flush()
        count_after = seeded_db.query(WizardTemplateStep).count()
        assert count_before == count_after
