"""Integration tests for app.parser.load — parser load phase.

These tests exercise the full DB write path for load_book and
upsert_with_source, verifying FK integrity, source preservation, and
two-pass choice resolution.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.content import (
    Book,
    Choice,
    ChoiceRandomOutcome,
    CombatEncounter,
    CombatModifier,
    CombatResults,
    Discipline,
    RandomOutcome,
    Scene,
    SceneItem,
    WeaponCategory,
)
from app.models.taxonomy import BookStartingEquipment, GameObject
from app.parser.load import load_book, upsert_with_source

# ---------------------------------------------------------------------------
# Minimal sample data helpers
# ---------------------------------------------------------------------------

def _book_data(**overrides: object) -> dict:
    """Return a minimal valid book_data dict."""
    defaults: dict = {
        "slug": "flight-from-the-dark",
        "number": 1,
        "title": "Flight from the Dark",
        "era": "kai",
        "series": "lone_wolf",
        "start_scene_number": 1,
        "max_total_picks": 5,
    }
    defaults.update(overrides)
    return defaults


def _minimal_scenes() -> list[dict]:
    return [
        {
            "number": 1,
            "html_id": "sect1",
            "narrative": "You stand at the gates of Holmgard.",
            "is_death": False,
            "is_victory": False,
            "must_eat": False,
            "loses_backpack": False,
            "source": "auto",
        },
        {
            "number": 2,
            "html_id": "sect2",
            "narrative": "You enter the city.",
            "is_death": False,
            "is_victory": False,
            "must_eat": False,
            "loses_backpack": False,
            "source": "auto",
        },
        {
            "number": 350,
            "html_id": "sect350",
            "narrative": "Your quest is complete. Congratulations.",
            "is_death": False,
            "is_victory": True,
            "must_eat": False,
            "loses_backpack": False,
            "source": "auto",
        },
    ]


def _minimal_choices() -> list[dict]:
    return [
        {
            "scene_number": 1,
            "target_scene_number": 2,
            "raw_text": "If you wish to enter the city, turn to 2.",
            "display_text": "Enter the city.",
            "condition_type": None,
            "condition_value": None,
            "ordinal": 1,
            "source": "auto",
        },
        {
            "scene_number": 1,
            "target_scene_number": 350,
            "raw_text": "If your quest is done, turn to 350.",
            "display_text": "Complete quest.",
            "condition_type": None,
            "condition_value": None,
            "ordinal": 2,
            "source": "auto",
        },
    ]


# ---------------------------------------------------------------------------
# Tests: upsert_with_source
# ---------------------------------------------------------------------------


class TestUpsertWithSource:
    def test_insert_new_row(self, db: Session) -> None:
        """A missing row should be inserted."""
        data = {
            "slug": "test-book-upsert",
            "number": 99,
            "title": "Test Upsert Book",
            "era": "kai",
            "series": "lone_wolf",
            "start_scene_number": 1,
            "max_total_picks": 5,
        }
        obj = upsert_with_source(db, Book, data, ["slug"])
        db.flush()
        assert obj is not None
        book = db.query(Book).filter_by(slug="test-book-upsert").one()
        assert book.title == "Test Upsert Book"

    def test_auto_row_is_updated(self, db: Session) -> None:
        """An existing auto-source row should be updated with new field values."""
        data = {
            "slug": "auto-update-book",
            "number": 98,
            "title": "Original Title",
            "era": "kai",
            "series": "lone_wolf",
            "start_scene_number": 1,
            "max_total_picks": 3,
        }
        upsert_with_source(db, Book, data, ["slug"])
        db.flush()

        # Update with new title
        updated = dict(data, title="Updated Title")
        upsert_with_source(db, Book, updated, ["slug"])
        db.flush()

        book = db.query(Book).filter_by(slug="auto-update-book").one()
        assert book.title == "Updated Title"
        assert db.query(Book).filter_by(slug="auto-update-book").count() == 1

    def test_manual_row_is_preserved(self, db: Session) -> None:
        """An existing manual-source row should NOT be overwritten."""
        # Insert a manual book directly
        manual_book = Book(
            slug="manual-preserve-book",
            number=97,
            title="Manual Title",
            era="kai",
            series="lone_wolf",
            start_scene_number=1,
            max_total_picks=5,
        )
        db.add(manual_book)
        db.flush()

        # Attempt upsert — should be skipped because source is missing (defaults to None)
        # but the book has no source column; let's use a model that has source
        go_data = {
            "kind": "item",
            "name": "Manual Sword",
            "description": "Original description",
            "aliases": "[]",
            "properties": "{}",
            "source": "manual",
        }
        upsert_with_source(db, GameObject, go_data, ["kind", "name"])
        db.flush()

        # Attempt to overwrite with auto
        go_update = dict(go_data, description="New description", source="auto")
        upsert_with_source(db, GameObject, go_update, ["kind", "name"])
        db.flush()

        go = db.query(GameObject).filter_by(kind="item", name="Manual Sword").one()
        assert go.description == "Original description"
        assert go.source == "manual"

    def test_auto_game_object_is_updated(self, db: Session) -> None:
        """An auto game object should be updated on re-upsert."""
        go_data = {
            "kind": "item",
            "name": "Auto Sword",
            "description": "Original",
            "aliases": "[]",
            "properties": "{}",
            "source": "auto",
        }
        upsert_with_source(db, GameObject, go_data, ["kind", "name"])
        db.flush()

        go_update = dict(go_data, description="Updated description")
        upsert_with_source(db, GameObject, go_update, ["kind", "name"])
        db.flush()

        go = db.query(GameObject).filter_by(kind="item", name="Auto Sword").one()
        assert go.description == "Updated description"


# ---------------------------------------------------------------------------
# Tests: load_book
# ---------------------------------------------------------------------------


class TestLoadBookBasic:
    def test_load_book_inserts_book_row(self, db: Session) -> None:
        """load_book should insert a Book row for the given book_data."""
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["books"] == 1
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        assert book.title == "Flight from the Dark"

    def test_load_book_inserts_scenes(self, db: Session) -> None:
        """load_book should insert one Scene row per scene dict."""
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["scenes"] == 3
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scenes = db.query(Scene).filter_by(book_id=book.id).all()
        assert len(scenes) == 3

    def test_load_book_inserts_disciplines(self, db: Session) -> None:
        """load_book should insert Discipline rows."""
        disciplines = [
            {
                "era": "kai",
                "name": "Camouflage",
                "html_id": "camouflage",
                "description": "The ability to blend into surroundings.",
                "mechanical_effect": None,
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=disciplines,
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["disciplines"] == 1
        disc = db.query(Discipline).filter_by(era="kai", name="Camouflage").one()
        assert disc.html_id == "camouflage"

    def test_load_book_inserts_crt_rows(self, db: Session) -> None:
        """load_book should insert CombatResults rows."""
        crt_rows = [
            {
                "era": "kai",
                "random_number": 0,
                "combat_ratio_min": -11,
                "combat_ratio_max": -11,
                "enemy_loss": 0,
                "hero_loss": 6,
            },
            {
                "era": "kai",
                "random_number": 1,
                "combat_ratio_min": -11,
                "combat_ratio_max": -11,
                "enemy_loss": 0,
                "hero_loss": 5,
            },
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=crt_rows,
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["crt_rows"] == 2
        rows = db.query(CombatResults).filter_by(era="kai").all()
        assert len(rows) == 2

    def test_load_book_inserts_weapon_categories(self, db: Session) -> None:
        """load_book should insert WeaponCategory rows."""
        wc = [{"weapon_name": "Broadsword", "category": "sword"}]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=wc,
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["weapon_categories"] == 1
        wc_row = db.query(WeaponCategory).filter_by(weapon_name="Broadsword").one()
        assert wc_row.category == "sword"

    def test_load_book_returns_summary_dict(self, db: Session) -> None:
        """load_book should return a summary dict with expected keys."""
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        expected_keys = {
            "books",
            "disciplines",
            "scenes",
            "scene_game_objects",
            "item_game_objects",
            "foe_game_objects",
            "other_game_objects",
            "choices",
            "choice_random_outcomes",
            "encounters",
            "combat_modifiers",
            "scene_items",
            "random_outcomes",
            "crt_rows",
            "refs",
            "weapon_categories",
            "starting_equipment",
            "transition_rules",
        }
        assert expected_keys.issubset(result.keys())


# ---------------------------------------------------------------------------
# Tests: FK integrity
# ---------------------------------------------------------------------------


class TestFKIntegrity:
    def test_choices_reference_valid_scenes(self, db: Session) -> None:
        """Every loaded choice should reference a scene that exists in the DB."""
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scene_ids = {s.id for s in db.query(Scene).filter_by(book_id=book.id).all()}
        choices = db.query(Choice).all()

        for choice in choices:
            assert choice.scene_id in scene_ids, (
                f"Choice {choice.id} has scene_id {choice.scene_id} not in {scene_ids}"
            )

    def test_scene_items_reference_valid_scenes(self, db: Session) -> None:
        """Loaded scene items should reference scenes that exist."""
        items = [
            {
                "scene_number": 1,
                "item_name": "Gold Crowns",
                "item_type": "gold",
                "quantity": 10,
                "action": "gain",
                "is_mandatory": True,
                "phase_ordinal": 1,
                "source": "auto",
            }
        ]
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=items,
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scene_ids = {s.id for s in db.query(Scene).filter_by(book_id=book.id).all()}
        scene_items = db.query(SceneItem).all()

        for si in scene_items:
            assert si.scene_id in scene_ids

    def test_encounters_reference_valid_scenes(self, db: Session) -> None:
        """Loaded combat encounters should reference scenes that exist."""
        encounters = [
            {
                "scene_number": 1,
                "enemy_name": "Gourgaz",
                "enemy_cs": 20,
                "enemy_end": 30,
                "ordinal": 1,
                "mindblast_immune": True,
                "evasion_damage": 0,
                "source": "auto",
            }
        ]
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=encounters,
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scene_ids = {s.id for s in db.query(Scene).filter_by(book_id=book.id).all()}
        enc_rows = db.query(CombatEncounter).all()

        for enc in enc_rows:
            assert enc.scene_id in scene_ids


# ---------------------------------------------------------------------------
# Tests: source preservation
# ---------------------------------------------------------------------------


class TestSourcePreservation:
    def test_manual_scene_not_overwritten_on_rerun(self, db: Session) -> None:
        """A scene with source='manual' should not be updated on re-run."""
        # First load — inserts auto scene
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()

        # Manually flip scene 1 to source='manual' and change its narrative
        scene1 = db.query(Scene).filter_by(book_id=book.id, number=1).one()
        scene1.source = "manual"
        scene1.narrative = "Manually edited narrative."
        db.flush()

        # Second load — should NOT overwrite the manual scene
        modified_scenes = list(_minimal_scenes())
        modified_scenes[0] = dict(
            modified_scenes[0], narrative="Parser narrative — should not win."
        )

        load_book(
            db,
            book_data=_book_data(),
            scenes=modified_scenes,
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )

        scene1_after = db.query(Scene).filter_by(book_id=book.id, number=1).one()
        assert scene1_after.narrative == "Manually edited narrative."
        assert scene1_after.source == "manual"

    def test_auto_scene_updated_on_rerun(self, db: Session) -> None:
        """A scene with source='auto' should be updated on re-run."""
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scene1 = db.query(Scene).filter_by(book_id=book.id, number=1).one()
        assert scene1.source == "auto"

        # Second load with updated narrative
        modified_scenes = list(_minimal_scenes())
        modified_scenes[0] = dict(modified_scenes[0], narrative="Updated auto narrative.")

        load_book(
            db,
            book_data=_book_data(),
            scenes=modified_scenes,
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )

        scene1_after = db.query(Scene).filter_by(book_id=book.id, number=1).one()
        assert scene1_after.narrative == "Updated auto narrative."

    def test_manual_discipline_not_overwritten(self, db: Session) -> None:
        """A discipline with source='manual' should not be updated on re-run."""
        disciplines = [
            {
                "era": "kai",
                "name": "Healing",
                "html_id": "healing",
                "description": "Auto description.",
                "mechanical_effect": None,
            }
        ]
        # Insert as auto first via upsert
        upsert_with_source(
            db,
            Discipline,
            disciplines[0],
            ["era", "name"],
        )
        db.flush()

        # Manually set source to manual and change description
        disc = db.query(Discipline).filter_by(era="kai", name="Healing").one()
        disc.source = "manual"  # type: ignore[attr-defined]
        disc.description = "Manual description."
        db.flush()

        # Re-run load — should preserve manual row
        load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=disciplines,
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )

        disc_after = db.query(Discipline).filter_by(era="kai", name="Healing").one()
        assert disc_after.description == "Manual description."


# ---------------------------------------------------------------------------
# Tests: two-pass choice resolution
# ---------------------------------------------------------------------------


class TestTwoPassChoiceResolution:
    def test_target_scene_id_resolved_after_load(self, db: Session) -> None:
        """Choices must have target_scene_id set to the correct scene's PK."""
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()

        scene2 = db.query(Scene).filter_by(book_id=book.id, number=2).one()
        scene350 = db.query(Scene).filter_by(book_id=book.id, number=350).one()

        choices = db.query(Choice).all()
        # Sort by ordinal
        choices.sort(key=lambda c: c.ordinal)

        assert choices[0].target_scene_number == 2
        assert choices[0].target_scene_id == scene2.id

        assert choices[1].target_scene_number == 350
        assert choices[1].target_scene_id == scene350.id

    def test_choice_target_none_when_target_scene_missing(self, db: Session) -> None:
        """If the target scene doesn't exist, target_scene_id should remain None."""
        # Only scene 1 exists — choice points to scene 999 which isn't loaded
        scenes = [_minimal_scenes()[0]]  # only scene 1
        choices = [
            {
                "scene_number": 1,
                "target_scene_number": 999,
                "raw_text": "Turn to 999.",
                "display_text": "Turn to 999.",
                "ordinal": 1,
                "source": "auto",
            }
        ]
        load_book(
            db,
            book_data=_book_data(),
            scenes=scenes,
            choices=choices,
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        choice = db.query(Choice).filter_by(target_scene_number=999).one()
        assert choice.target_scene_id is None

    def test_choice_random_outcomes_resolved(self, db: Session) -> None:
        """ChoiceRandomOutcome.target_scene_id should be resolved."""
        # Use random_outcomes list to carry choice random outcome data
        choice_ro = [
            {
                "choice_scene_number": 1,
                "choice_ordinal": 1,
                "range_min": 0,
                "range_max": 4,
                "target_scene_number": 2,
                "narrative_text": "Low roll — you stumble.",
                "source": "auto",
            },
            {
                "choice_scene_number": 1,
                "choice_ordinal": 1,
                "range_min": 5,
                "range_max": 9,
                "target_scene_number": 350,
                "narrative_text": "High roll — you succeed.",
                "source": "auto",
            },
        ]
        load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=choice_ro,
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        scene2 = db.query(Scene).filter_by(book_id=book.id, number=2).one()
        scene350 = db.query(Scene).filter_by(book_id=book.id, number=350).one()

        cros = db.query(ChoiceRandomOutcome).all()
        assert len(cros) == 2

        low = next(c for c in cros if c.range_min == 0)
        high = next(c for c in cros if c.range_min == 5)
        assert low.target_scene_id == scene2.id
        assert high.target_scene_id == scene350.id

    def test_choices_count_correct(self, db: Session) -> None:
        """Summary dict should report the correct number of choices loaded."""
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["choices"] == 2
        assert db.query(Choice).count() == 2


# ---------------------------------------------------------------------------
# Tests: combat encounters and modifiers
# ---------------------------------------------------------------------------


class TestCombatEncounters:
    def test_combat_encounter_loaded(self, db: Session) -> None:
        """A combat encounter dict should produce a CombatEncounter row."""
        encounters = [
            {
                "scene_number": 1,
                "enemy_name": "Gourgaz",
                "enemy_cs": 20,
                "enemy_end": 30,
                "ordinal": 1,
                "mindblast_immune": True,
                "evasion_damage": 0,
                "source": "auto",
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=encounters,
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["encounters"] == 1
        enc = db.query(CombatEncounter).filter_by(enemy_name="Gourgaz").one()
        assert enc.enemy_cs == 20
        assert enc.mindblast_immune is True

    def test_combat_modifiers_loaded_from_encounter_dict(self, db: Session) -> None:
        """Modifiers embedded in encounter dicts should become CombatModifier rows."""
        encounters = [
            {
                "scene_number": 1,
                "enemy_name": "Vordak",
                "enemy_cs": 18,
                "enemy_end": 25,
                "ordinal": 1,
                "mindblast_immune": False,
                "evasion_damage": 0,
                "source": "auto",
                "modifiers": [
                    {"modifier_type": "undead", "modifier_value": None, "condition": None,
                     "source": "auto"},
                ],
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=encounters,
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["combat_modifiers"] == 1
        mod = db.query(CombatModifier).filter_by(modifier_type="undead").one()
        assert mod is not None


# ---------------------------------------------------------------------------
# Tests: scene items and random outcomes
# ---------------------------------------------------------------------------


class TestSceneItems:
    def test_scene_item_gain_loaded(self, db: Session) -> None:
        """A scene-item dict with action='gain' should produce a SceneItem row."""
        items = [
            {
                "scene_number": 1,
                "item_name": "Sword",
                "item_type": "weapon",
                "quantity": 1,
                "action": "gain",
                "is_mandatory": True,
                "phase_ordinal": 1,
                "source": "auto",
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=items,
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["scene_items"] == 1
        si = db.query(SceneItem).filter_by(item_name="Sword").one()
        assert si.action == "gain"


class TestRandomOutcomes:
    def test_scene_random_outcome_loaded(self, db: Session) -> None:
        """A scene-level random outcome should produce a RandomOutcome row."""
        ro_list = [
            {
                "scene_number": 1,
                "roll_group": 0,
                "range_min": 0,
                "range_max": 4,
                "effect_type": "endurance_change",
                "effect_value": "-3",
                "narrative_text": "0-4: lose 3 ENDURANCE",
                "ordinal": 1,
                "source": "auto",
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=ro_list,
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["random_outcomes"] == 1
        ro = db.query(RandomOutcome).filter_by(effect_type="endurance_change").one()
        assert ro.range_min == 0
        assert ro.range_max == 4


# ---------------------------------------------------------------------------
# Tests: game objects and refs
# ---------------------------------------------------------------------------


class TestGameObjects:
    def test_game_objects_loaded_by_kind(self, db: Session) -> None:
        """game_objects of different kinds should be inserted into game_objects table."""
        game_objects = [
            {
                "kind": "item",
                "name": "Sommerswerd",
                "description": "The Sun-Sword.",
                "aliases": "[]",
                "properties": "{}",
                "source": "auto",
            },
            {
                "kind": "foe",
                "name": "Darklord Zagarna",
                "description": "A powerful Darklord.",
                "aliases": "[]",
                "properties": "{}",
                "source": "auto",
            },
            {
                "kind": "location",
                "name": "Holmgard",
                "description": "Capital of Sommerlund.",
                "aliases": "[]",
                "properties": "{}",
                "source": "auto",
            },
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=game_objects,
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        assert result["item_game_objects"] == 1
        assert result["foe_game_objects"] == 1
        assert result["other_game_objects"] == 1

        assert db.query(GameObject).filter_by(name="Sommerswerd").count() == 1
        assert db.query(GameObject).filter_by(name="Darklord Zagarna").count() == 1
        assert db.query(GameObject).filter_by(name="Holmgard").count() == 1

    def test_starting_equipment_loaded(self, db: Session) -> None:
        """starting_equipment dicts should produce BookStartingEquipment rows."""
        se = [
            {
                "item_name": "Broadsword",
                "item_type": "weapon",
                "category": "weapon_choice",
                "is_default": False,
                "source": "auto",
            }
        ]
        result = load_book(
            db,
            book_data=_book_data(),
            scenes=[],
            choices=[],
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=se,
            transition_rules=[],
        )
        assert result["starting_equipment"] == 1
        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        bse = db.query(BookStartingEquipment).filter_by(book_id=book.id).one()
        assert bse.item_name == "Broadsword"


# ---------------------------------------------------------------------------
# Tests: idempotency (re-run produces no duplicates)
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_double_load_no_duplicate_scenes(self, db: Session) -> None:
        """Running load_book twice should not create duplicate scene rows."""
        kwargs = dict(
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        load_book(db, **kwargs)  # type: ignore[arg-type]
        load_book(db, **kwargs)  # type: ignore[arg-type]

        book = db.query(Book).filter_by(slug="flight-from-the-dark").one()
        assert db.query(Scene).filter_by(book_id=book.id).count() == 3

    def test_double_load_no_duplicate_choices(self, db: Session) -> None:
        """Running load_book twice should not create duplicate choice rows."""
        kwargs = dict(
            book_data=_book_data(),
            scenes=_minimal_scenes(),
            choices=_minimal_choices(),
            encounters=[],
            items=[],
            random_outcomes=[],
            disciplines=[],
            crt_rows=[],
            game_objects=[],
            refs=[],
            weapon_categories=[],
            starting_equipment=[],
            transition_rules=[],
        )
        load_book(db, **kwargs)  # type: ignore[arg-type]
        load_book(db, **kwargs)  # type: ignore[arg-type]

        assert db.query(Choice).count() == 2
