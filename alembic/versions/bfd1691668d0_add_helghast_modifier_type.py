"""add helghast modifier type

Revision ID: bfd1691668d0
Revises: bd185b7edf5d
Create Date: 2026-03-24 11:57:49.318994

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bfd1691668d0'
down_revision: Union[str, Sequence[str], None] = 'bd185b7edf5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add 'helghast' to the combat_modifiers modifier_type CHECK constraint."""
    with op.batch_alter_table('combat_modifiers', schema=None) as batch_op:
        batch_op.drop_constraint('ck_combat_modifiers_modifier_type', type_='check')
        batch_op.create_check_constraint(
            'ck_combat_modifiers_modifier_type',
            "modifier_type IN ('cs_bonus', 'cs_penalty', 'double_damage', 'undead', 'enemy_mindblast', 'helghast')",
        )


def downgrade() -> None:
    """Remove 'helghast' from the combat_modifiers modifier_type CHECK constraint."""
    with op.batch_alter_table('combat_modifiers', schema=None) as batch_op:
        batch_op.drop_constraint('ck_combat_modifiers_modifier_type', type_='check')
        batch_op.create_check_constraint(
            'ck_combat_modifiers_modifier_type',
            "modifier_type IN ('cs_bonus', 'cs_penalty', 'double_damage', 'undead', 'enemy_mindblast')",
        )
