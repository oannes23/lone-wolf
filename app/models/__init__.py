"""ORM model registry — import all models here so SQLAlchemy metadata is complete."""

from app.models.admin import AdminUser, Report
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
from app.models.player import (
    Character,
    CharacterBookStart,
    CharacterDiscipline,
    CharacterEvent,
    CharacterItem,
    CombatRound,
    DecisionLog,
    User,
)
from app.models.taxonomy import (
    BookStartingEquipment,
    BookTransitionRule,
    GameObject,
    GameObjectRef,
)
from app.models.wizard import (
    CharacterWizardProgress,
    WizardTemplate,
    WizardTemplateStep,
)

__all__ = [
    "AdminUser",
    "Book",
    "BookStartingEquipment",
    "BookTransitionRule",
    "Character",
    "CharacterBookStart",
    "CharacterDiscipline",
    "CharacterEvent",
    "CharacterItem",
    "CharacterWizardProgress",
    "Choice",
    "ChoiceRandomOutcome",
    "CombatEncounter",
    "CombatModifier",
    "CombatResults",
    "CombatRound",
    "DecisionLog",
    "Discipline",
    "GameObject",
    "GameObjectRef",
    "RandomOutcome",
    "Report",
    "Scene",
    "SceneItem",
    "User",
    "WeaponCategory",
    "WizardTemplate",
    "WizardTemplateStep",
]
