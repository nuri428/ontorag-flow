"""Built-in action behaviour and the Action contract."""

from __future__ import annotations

import pytest

from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty
from ontorag_flow.core.action import Action, SideEffectKind
from ontorag_flow.core.state import EMPTY_STATE, CaseState


def test_actions_satisfy_protocol(update_property: UpdateCaseProperty) -> None:
    assert isinstance(update_property, Action)


def test_update_property_declares_case_state_side_effect(
    update_property: UpdateCaseProperty,
) -> None:
    assert update_property.side_effects == frozenset({SideEffectKind.CASE_STATE})


async def test_update_property_returns_state_change(
    update_property: UpdateCaseProperty,
) -> None:
    params = update_property.input_schema.model_validate({"key": "severity", "value": 3})
    result = await update_property.execute(params, EMPTY_STATE)

    assert result.success is True
    assert result.state_changes == {"severity": 3}


async def test_set_goal_returns_goal_change(set_goal: SetGoal) -> None:
    params = set_goal.input_schema.model_validate({"predicate": "diagnosed"})
    result = await set_goal.execute(params, EMPTY_STATE)

    assert result.goal_change == {"diagnosed": True}


def test_update_property_rejects_empty_key(update_property: UpdateCaseProperty) -> None:
    with pytest.raises(ValueError):
        update_property.input_schema.model_validate({"key": "", "value": 1})


def test_case_state_apply_is_immutable() -> None:
    state = CaseState(properties={"a": 1})
    new_state = state.with_property("b", 2)

    assert state.properties == {"a": 1}
    assert new_state.properties == {"a": 1, "b": 2}
