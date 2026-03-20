"""Initial schema - all tables

Revision ID: 8056784435d8
Revises:
Create Date: 2026-03-20 00:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8056784435d8'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Creation order respects FK dependencies:
      001 books
      002 game_objects, game_object_refs
      003 static lookups: weapon_categories, disciplines, combat_results
      004 scenes
      005 choices, choice_random_outcomes, combat_encounters, combat_modifiers,
          scene_items, random_outcomes
      006 book_transition_rules, book_starting_equipment
      007 wizard_templates, wizard_template_steps
      008 admin_users
      009 users
      010 characters (WITHOUT active_wizard_id; FKs to scenes/choices/combat_encounters
          are valid now that those tables exist)
      011 character_disciplines, character_items, character_book_starts,
          decision_log, combat_rounds, character_events
      012 character_wizard_progress (references characters)
      013 ALTER TABLE characters ADD active_wizard_id (resolves circular FK)
      014 reports
    """
    # --- 001: books ---
    op.create_table(
        'books',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('slug', sa.String(length=20), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('era', sa.String(length=20), nullable=False),
        sa.Column('series', sa.String(length=20), nullable=False),
        sa.Column('start_scene_number', sa.Integer(), nullable=False),
        sa.Column('max_total_picks', sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "era IN ('kai', 'magnakai', 'grand_master', 'new_order')",
            name='ck_books_era',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )

    # --- 002: game_objects, game_object_refs ---
    op.create_table(
        'game_objects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('aliases', sa.Text(), server_default='[]', nullable=False),
        sa.Column('properties', sa.Text(), server_default='{}', nullable=False),
        sa.Column('first_book_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "kind IN ('character', 'location', 'creature', 'organization', 'item', 'foe', 'scene')",
            name='ck_game_objects_kind',
        ),
        sa.CheckConstraint(
            "source IN ('auto', 'manual')",
            name='ck_game_objects_source',
        ),
        sa.ForeignKeyConstraint(['first_book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', 'kind', name='uq_game_objects_name_kind'),
    )
    op.create_index('ix_game_objects_kind', 'game_objects', ['kind'], unique=False)
    op.create_index('ix_game_objects_kind_name', 'game_objects', ['kind', 'name'], unique=False)

    op.create_table(
        'game_object_refs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=False),
        sa.Column('tags', sa.Text(), nullable=False),
        sa.Column('metadata', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "source IN ('auto', 'manual')",
            name='ck_game_object_refs_source',
        ),
        sa.ForeignKeyConstraint(['source_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['target_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_game_object_refs_source_id', 'game_object_refs', ['source_id'], unique=False)
    op.create_index('ix_game_object_refs_target_id', 'game_object_refs', ['target_id'], unique=False)

    # --- 003: static lookups ---
    op.create_table(
        'weapon_categories',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('weapon_name', sa.String(length=100), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('weapon_name'),
    )
    op.create_index('ix_weapon_categories_category', 'weapon_categories', ['category'], unique=False)

    op.create_table(
        'disciplines',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('era', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('html_id', sa.String(length=30), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('mechanical_effect', sa.String(length=200), nullable=True),
        sa.CheckConstraint(
            "era IN ('kai', 'magnakai', 'grand_master', 'new_order')",
            name='ck_disciplines_era',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('era', 'name', name='uq_disciplines_era_name'),
    )

    op.create_table(
        'combat_results',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('era', sa.String(length=20), nullable=False),
        sa.Column('random_number', sa.Integer(), nullable=False),
        sa.Column('combat_ratio_min', sa.Integer(), nullable=False),
        sa.Column('combat_ratio_max', sa.Integer(), nullable=False),
        sa.Column('enemy_loss', sa.Integer(), nullable=True),
        sa.Column('hero_loss', sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "era IN ('kai', 'magnakai', 'grand_master', 'new_order')",
            name='ck_combat_results_era',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_combat_results_lookup',
        'combat_results',
        ['era', 'random_number', 'combat_ratio_min'],
        unique=False,
    )

    # --- 004: scenes ---
    op.create_table(
        'scenes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('game_object_id', sa.Integer(), nullable=True),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('html_id', sa.String(length=20), nullable=False),
        sa.Column('narrative', sa.Text(), nullable=False),
        sa.Column('is_death', sa.Boolean(), nullable=False),
        sa.Column('is_victory', sa.Boolean(), nullable=False),
        sa.Column('must_eat', sa.Boolean(), nullable=False),
        sa.Column('loses_backpack', sa.Boolean(), nullable=False),
        sa.Column('illustration_path', sa.String(length=255), nullable=True),
        sa.Column('phase_sequence_override', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_scenes_source'),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['game_object_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('book_id', 'number', name='uq_scenes_book_number'),
    )
    op.create_index('ix_scenes_book_number', 'scenes', ['book_id', 'number'], unique=False)

    # --- 005: content sub-tables ---
    op.create_table(
        'choices',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('target_scene_id', sa.Integer(), nullable=True),
        sa.Column('target_scene_number', sa.Integer(), nullable=False),
        sa.Column('raw_text', sa.Text(), nullable=False),
        sa.Column('display_text', sa.Text(), nullable=False),
        sa.Column('condition_type', sa.String(length=30), nullable=True),
        sa.Column('condition_value', sa.Text(), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "condition_type IS NULL OR condition_type IN ('discipline', 'item', 'gold', 'random', 'none')",
            name='ck_choices_condition_type',
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_choices_source'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['target_scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_choices_scene_id', 'choices', ['scene_id'], unique=False)

    op.create_table(
        'choice_random_outcomes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('choice_id', sa.Integer(), nullable=False),
        sa.Column('range_min', sa.Integer(), nullable=False),
        sa.Column('range_max', sa.Integer(), nullable=False),
        sa.Column('target_scene_id', sa.Integer(), nullable=False),
        sa.Column('target_scene_number', sa.Integer(), nullable=False),
        sa.Column('narrative_text', sa.Text(), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_cro_source'),
        sa.ForeignKeyConstraint(['choice_id'], ['choices.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['target_scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('choice_id', 'range_min', 'range_max', name='uq_cro_choice_range'),
    )
    op.create_index(
        'ix_choice_random_outcomes_choice_id',
        'choice_random_outcomes',
        ['choice_id'],
        unique=False,
    )

    op.create_table(
        'combat_encounters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('foe_game_object_id', sa.Integer(), nullable=True),
        sa.Column('enemy_name', sa.String(length=100), nullable=False),
        sa.Column('enemy_cs', sa.Integer(), nullable=False),
        sa.Column('enemy_end', sa.Integer(), nullable=False),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('mindblast_immune', sa.Boolean(), nullable=False),
        sa.Column('evasion_after_rounds', sa.Integer(), nullable=True),
        sa.Column('evasion_target', sa.Integer(), nullable=True),
        sa.Column('evasion_damage', sa.Integer(), nullable=False),
        sa.Column('condition_type', sa.String(length=30), nullable=True),
        sa.Column('condition_value', sa.String(length=100), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "condition_type IS NULL OR condition_type IN ('discipline', 'item', 'none')",
            name='ck_combat_encounters_condition_type',
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_combat_encounters_source'),
        sa.ForeignKeyConstraint(['foe_game_object_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_combat_encounters_scene_id',
        'combat_encounters',
        ['scene_id'],
        unique=False,
    )

    op.create_table(
        'combat_modifiers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('combat_encounter_id', sa.Integer(), nullable=False),
        sa.Column('modifier_type', sa.String(length=30), nullable=False),
        sa.Column('modifier_value', sa.String(length=100), nullable=True),
        sa.Column('condition', sa.String(length=200), nullable=True),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "modifier_type IN ('cs_bonus', 'cs_penalty', 'double_damage', 'undead', 'enemy_mindblast')",
            name='ck_combat_modifiers_modifier_type',
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_combat_modifiers_source'),
        sa.ForeignKeyConstraint(
            ['combat_encounter_id'],
            ['combat_encounters.id'],
            ondelete='RESTRICT',
        ),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'scene_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('game_object_id', sa.Integer(), nullable=True),
        sa.Column('item_name', sa.String(length=100), nullable=False),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('quantity', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=False),
        sa.Column('is_mandatory', sa.Boolean(), nullable=False),
        sa.Column('phase_ordinal', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint("action IN ('gain', 'lose')", name='ck_scene_items_action'),
        sa.CheckConstraint(
            "item_type IN ('weapon', 'backpack', 'special', 'gold', 'meal')",
            name='ck_scene_items_item_type',
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_scene_items_source'),
        sa.ForeignKeyConstraint(['game_object_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'random_outcomes',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('roll_group', sa.Integer(), nullable=False),
        sa.Column('range_min', sa.Integer(), nullable=False),
        sa.Column('range_max', sa.Integer(), nullable=False),
        sa.Column('effect_type', sa.String(length=30), nullable=False),
        sa.Column('effect_value', sa.String(length=200), nullable=False),
        sa.Column('narrative_text', sa.Text(), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "effect_type IN ("
            "'gold_change', 'endurance_change', 'item_gain', 'item_loss', 'meal_change', 'scene_redirect'"
            ")",
            name='ck_random_outcomes_effect_type',
        ),
        sa.CheckConstraint("source IN ('auto', 'manual')", name='ck_random_outcomes_source'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'scene_id', 'roll_group', 'range_min', 'range_max',
            name='uq_random_outcomes_scene_roll_range',
        ),
    )
    op.create_index(
        'ix_random_outcomes_scene_roll_group',
        'random_outcomes',
        ['scene_id', 'roll_group'],
        unique=False,
    )

    # --- 006: taxonomy ---
    op.create_table(
        'book_transition_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('from_book_id', sa.Integer(), nullable=False),
        sa.Column('to_book_id', sa.Integer(), nullable=False),
        sa.Column('max_weapons', sa.Integer(), nullable=False),
        sa.Column('max_backpack_items', sa.Integer(), nullable=False),
        sa.Column('special_items_carry', sa.Boolean(), nullable=False),
        sa.Column('gold_carries', sa.Boolean(), nullable=False),
        sa.Column('new_disciplines_count', sa.Integer(), nullable=False),
        sa.Column('base_cs_override', sa.Integer(), nullable=True),
        sa.Column('base_end_override', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['from_book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['to_book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('from_book_id', 'to_book_id', name='uq_book_transition_rules_from_to'),
    )

    op.create_table(
        'book_starting_equipment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('game_object_id', sa.Integer(), nullable=True),
        sa.Column('item_name', sa.String(length=100), nullable=False),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('source', sa.String(length=10), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('weapon', 'backpack', 'special', 'gold', 'meal')",
            name='ck_book_starting_equipment_item_type',
        ),
        sa.CheckConstraint(
            "source IN ('auto', 'manual')",
            name='ck_book_starting_equipment_source',
        ),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['game_object_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_book_starting_equipment_book_id',
        'book_starting_equipment',
        ['book_id'],
        unique=False,
    )

    # --- 007: wizard templates ---
    op.create_table(
        'wizard_templates',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    op.create_table(
        'wizard_template_steps',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('step_type', sa.String(length=30), nullable=False),
        sa.Column('config', sa.Text(), nullable=True),
        sa.Column('ordinal', sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "step_type IN ("
            "'stat_roll', 'pick_disciplines', 'pick_equipment', "
            "'pick_weapon_skill', 'inventory_adjust', 'confirm'"
            ")",
            name='ck_wizard_template_steps_step_type',
        ),
        sa.ForeignKeyConstraint(['template_id'], ['wizard_templates.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_wizard_template_steps_template_id',
        'wizard_template_steps',
        ['template_id'],
        unique=False,
    )

    # --- 008: admin_users ---
    op.create_table(
        'admin_users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
    )

    # --- 009: users ---
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('username', sa.String(length=50), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('max_characters', sa.Integer(), nullable=False),
        sa.Column('password_changed_at', sa.DateTime(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username'),
    )

    # --- 010: characters (WITHOUT active_wizard_id — circular FK resolved below)
    #          FKs to scenes, choices, combat_encounters are safe now (tables exist) ---
    op.create_table(
        'characters',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('current_scene_id', sa.Integer(), nullable=True),
        sa.Column('scene_phase', sa.String(length=20), nullable=True),
        sa.Column('scene_phase_index', sa.Integer(), nullable=True),
        sa.Column('active_combat_encounter_id', sa.Integer(), nullable=True),
        sa.Column('pending_choice_id', sa.Integer(), nullable=True),
        sa.Column('combat_skill_base', sa.Integer(), nullable=False),
        sa.Column('endurance_base', sa.Integer(), nullable=False),
        sa.Column('endurance_max', sa.Integer(), nullable=False),
        sa.Column('endurance_current', sa.Integer(), nullable=False),
        sa.Column('gold', sa.Integer(), nullable=False),
        sa.Column('meals', sa.Integer(), nullable=False),
        sa.Column('is_alive', sa.Boolean(), nullable=False),
        sa.Column('is_deleted', sa.Boolean(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('death_count', sa.Integer(), nullable=False),
        sa.Column('current_run', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('rule_overrides', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "scene_phase IS NULL OR scene_phase IN ('items', 'combat', 'random', 'choices')",
            name='ck_characters_scene_phase',
        ),
        sa.CheckConstraint(
            "gold >= 0 AND gold <= 50",
            name='ck_characters_gold',
        ),
        sa.CheckConstraint(
            "meals >= 0 AND meals <= 8",
            name='ck_characters_meals',
        ),
        sa.CheckConstraint(
            "endurance_current >= 0",
            name='ck_characters_endurance_current',
        ),
        sa.CheckConstraint(
            "(scene_phase IS NULL AND scene_phase_index IS NULL) OR "
            "(scene_phase IS NOT NULL AND scene_phase_index IS NOT NULL)",
            name='ck_characters_phase_consistency',
        ),
        sa.ForeignKeyConstraint(
            ['active_combat_encounter_id'], ['combat_encounters.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['current_scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['pending_choice_id'], ['choices.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_characters_user_id', 'characters', ['user_id'], unique=False)
    op.create_index(
        'ix_characters_user_id_is_deleted',
        'characters',
        ['user_id', 'is_deleted'],
        unique=False,
    )

    # --- 011: character child tables ---
    op.create_table(
        'character_disciplines',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('discipline_id', sa.Integer(), nullable=False),
        sa.Column('weapon_category', sa.String(length=30), nullable=True),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['discipline_id'], ['disciplines.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'character_id', 'discipline_id', name='uq_character_disciplines_char_disc'
        ),
    )
    op.create_index(
        'ix_character_disciplines_char_disc',
        'character_disciplines',
        ['character_id', 'discipline_id'],
        unique=False,
    )

    op.create_table(
        'character_items',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('game_object_id', sa.Integer(), nullable=True),
        sa.Column('item_name', sa.String(length=100), nullable=False),
        sa.Column('item_type', sa.String(length=20), nullable=False),
        sa.Column('is_equipped', sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "item_type IN ('weapon', 'backpack', 'special')",
            name='ck_character_items_item_type',
        ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['game_object_id'], ['game_objects.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_character_items_char_type',
        'character_items',
        ['character_id', 'item_type'],
        unique=False,
    )

    op.create_table(
        'character_book_starts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('book_id', sa.Integer(), nullable=False),
        sa.Column('combat_skill_base', sa.Integer(), nullable=False),
        sa.Column('endurance_base', sa.Integer(), nullable=False),
        sa.Column('endurance_max', sa.Integer(), nullable=False),
        sa.Column('endurance_current', sa.Integer(), nullable=False),
        sa.Column('gold', sa.Integer(), nullable=False),
        sa.Column('meals', sa.Integer(), nullable=False),
        sa.Column('items_json', sa.Text(), nullable=False),
        sa.Column('disciplines_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['book_id'], ['books.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'character_id', 'book_id', name='uq_character_book_starts_char_book'
        ),
    )

    op.create_table(
        'decision_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('from_scene_id', sa.Integer(), nullable=False),
        sa.Column('to_scene_id', sa.Integer(), nullable=False),
        sa.Column('choice_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=20), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "action_type IN ("
            "'choice', 'combat_win', 'combat_evasion', 'random', 'death', 'restart', 'replay'"
            ")",
            name='ck_decision_log_action_type',
        ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['choice_id'], ['choices.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['from_scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['to_scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_decision_log_char_run',
        'decision_log',
        ['character_id', 'run_number'],
        unique=False,
    )
    op.create_index(
        'ix_decision_log_char_run_created',
        'decision_log',
        ['character_id', 'run_number', 'created_at'],
        unique=False,
    )

    op.create_table(
        'combat_rounds',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('combat_encounter_id', sa.Integer(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('round_number', sa.Integer(), nullable=False),
        sa.Column('random_number', sa.Integer(), nullable=False),
        sa.Column('combat_ratio', sa.Integer(), nullable=False),
        sa.Column('enemy_loss', sa.Integer(), nullable=True),
        sa.Column('hero_loss', sa.Integer(), nullable=True),
        sa.Column('enemy_end_remaining', sa.Integer(), nullable=False),
        sa.Column('hero_end_remaining', sa.Integer(), nullable=False),
        sa.Column('psi_surge_used', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['combat_encounter_id'], ['combat_encounters.id'], ondelete='RESTRICT'
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'character_id', 'combat_encounter_id', 'run_number', 'round_number',
            name='uq_combat_rounds_char_enc_run_round',
        ),
    )
    op.create_index(
        'ix_combat_rounds_char_enc_run_round',
        'combat_rounds',
        ['character_id', 'combat_encounter_id', 'run_number', 'round_number'],
        unique=False,
    )

    op.create_table(
        'character_events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('scene_id', sa.Integer(), nullable=False),
        sa.Column('run_number', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=30), nullable=False),
        sa.Column('phase', sa.String(length=20), nullable=True),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('seq', sa.Integer(), nullable=False),
        sa.Column('operations', sa.Text(), nullable=True),
        sa.Column('parent_event_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "event_type IN ("
            "'item_pickup', 'item_decline', 'item_loss', 'item_loss_skip', 'item_consumed', "
            "'meal_consumed', 'meal_penalty', 'gold_change', 'endurance_change', 'healing', "
            "'combat_start', 'combat_end', 'combat_skipped', 'evasion', 'death', 'restart', "
            "'replay', 'discipline_gained', 'book_advance', 'random_roll', 'backpack_loss'"
            ")",
            name='ck_character_events_event_type',
        ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(
            ['parent_event_id'], ['character_events.id'], ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_character_events_char_event_type',
        'character_events',
        ['character_id', 'event_type'],
        unique=False,
    )
    op.create_index(
        'ix_character_events_char_scene_created',
        'character_events',
        ['character_id', 'scene_id', 'created_at'],
        unique=False,
    )
    op.create_index(
        'ix_character_events_char_seq',
        'character_events',
        ['character_id', 'seq'],
        unique=False,
    )
    op.create_index(
        'ix_character_events_parent_event_id',
        'character_events',
        ['parent_event_id'],
        unique=False,
    )

    # --- 012: character_wizard_progress (references characters — now safe) ---
    op.create_table(
        'character_wizard_progress',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=False),
        sa.Column('wizard_template_id', sa.Integer(), nullable=False),
        sa.Column('current_step_index', sa.Integer(), nullable=False),
        sa.Column('state', sa.Text(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['wizard_template_id'], ['wizard_templates.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_character_wizard_progress_char_completed',
        'character_wizard_progress',
        ['character_id', 'completed_at'],
        unique=False,
    )

    # --- 013: ALTER TABLE characters ADD active_wizard_id ---
    # SQLite does not support ADD COLUMN with FK constraints via ALTER TABLE.
    # We add the column as a plain nullable Integer; the FK relationship is
    # declared in the ORM model (CharacterWizardProgress) and enforced at the
    # application layer. SQLite FK enforcement only applies to tables created
    # with FK declarations in the original CREATE TABLE statement.
    op.add_column('characters', sa.Column('active_wizard_id', sa.Integer(), nullable=True))

    # --- 014: reports ---
    op.create_table(
        'reports',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('scene_id', sa.Integer(), nullable=True),
        sa.Column('tags', sa.Text(), nullable=False),
        sa.Column('free_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "status IN ('open', 'triaging', 'resolved', 'wont_fix')",
            name='ck_reports_status',
        ),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['resolved_by'], ['admin_users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['scene_id'], ['scenes.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_reports_status_created_at',
        'reports',
        ['status', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema — reverse of upgrade in strict reverse dependency order."""
    # --- 014: reports ---
    op.drop_index('ix_reports_status_created_at', table_name='reports')
    op.drop_table('reports')

    # --- 013: remove active_wizard_id from characters ---
    op.drop_column('characters', 'active_wizard_id')

    # --- 012: character_wizard_progress ---
    op.drop_index(
        'ix_character_wizard_progress_char_completed',
        table_name='character_wizard_progress',
    )
    op.drop_table('character_wizard_progress')

    # --- 011: character child tables ---
    op.drop_index('ix_character_events_parent_event_id', table_name='character_events')
    op.drop_index('ix_character_events_char_seq', table_name='character_events')
    op.drop_index('ix_character_events_char_scene_created', table_name='character_events')
    op.drop_index('ix_character_events_char_event_type', table_name='character_events')
    op.drop_table('character_events')
    op.drop_index('ix_combat_rounds_char_enc_run_round', table_name='combat_rounds')
    op.drop_table('combat_rounds')
    op.drop_index('ix_decision_log_char_run_created', table_name='decision_log')
    op.drop_index('ix_decision_log_char_run', table_name='decision_log')
    op.drop_table('decision_log')
    op.drop_table('character_book_starts')
    op.drop_index('ix_character_items_char_type', table_name='character_items')
    op.drop_table('character_items')
    op.drop_index('ix_character_disciplines_char_disc', table_name='character_disciplines')
    op.drop_table('character_disciplines')

    # --- 010: characters ---
    op.drop_index('ix_characters_user_id_is_deleted', table_name='characters')
    op.drop_index('ix_characters_user_id', table_name='characters')
    op.drop_table('characters')

    # --- 009: users ---
    op.drop_table('users')

    # --- 008: admin_users ---
    op.drop_table('admin_users')

    # --- 007: wizard templates ---
    op.drop_index('ix_wizard_template_steps_template_id', table_name='wizard_template_steps')
    op.drop_table('wizard_template_steps')
    op.drop_table('wizard_templates')

    # --- 006: taxonomy ---
    op.drop_index('ix_book_starting_equipment_book_id', table_name='book_starting_equipment')
    op.drop_table('book_starting_equipment')
    op.drop_table('book_transition_rules')

    # --- 005: content sub-tables ---
    op.drop_index('ix_random_outcomes_scene_roll_group', table_name='random_outcomes')
    op.drop_table('random_outcomes')
    op.drop_table('scene_items')
    op.drop_table('combat_modifiers')
    op.drop_index('ix_combat_encounters_scene_id', table_name='combat_encounters')
    op.drop_table('combat_encounters')
    op.drop_index('ix_choice_random_outcomes_choice_id', table_name='choice_random_outcomes')
    op.drop_table('choice_random_outcomes')
    op.drop_index('ix_choices_scene_id', table_name='choices')
    op.drop_table('choices')

    # --- 004: scenes ---
    op.drop_index('ix_scenes_book_number', table_name='scenes')
    op.drop_table('scenes')

    # --- 003: static lookups ---
    op.drop_index('ix_combat_results_lookup', table_name='combat_results')
    op.drop_table('combat_results')
    op.drop_table('disciplines')
    op.drop_index('ix_weapon_categories_category', table_name='weapon_categories')
    op.drop_table('weapon_categories')

    # --- 002: game_objects ---
    op.drop_index('ix_game_object_refs_target_id', table_name='game_object_refs')
    op.drop_index('ix_game_object_refs_source_id', table_name='game_object_refs')
    op.drop_table('game_object_refs')
    op.drop_index('ix_game_objects_kind_name', table_name='game_objects')
    op.drop_index('ix_game_objects_kind', table_name='game_objects')
    op.drop_table('game_objects')

    # --- 001: books ---
    op.drop_table('books')
