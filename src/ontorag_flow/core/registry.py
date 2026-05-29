"""Action registry — the catalog of actions available to a process.

Built-in actions register themselves via :func:`default_registry`. External
plugin actions are loaded at runtime by the CLI (``action register``).
"""

from __future__ import annotations

from ontorag_flow.core.action import Action


class ActionRegistry:
    """An in-memory map of action URI -> action instance."""

    def __init__(self) -> None:
        self._actions: dict[str, Action] = {}

    def register(self, action: Action) -> None:
        """Register an action, replacing any prior action with the same URI."""

        self._actions[action.uri] = action

    def get(self, uri: str) -> Action | None:
        return self._actions.get(uri)

    def all(self) -> list[Action]:
        return list(self._actions.values())

    def __contains__(self, uri: object) -> bool:
        return uri in self._actions

    def __len__(self) -> int:
        return len(self._actions)


def default_registry() -> ActionRegistry:
    """Return a registry pre-populated with the built-in action library."""

    from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty

    registry = ActionRegistry()
    registry.register(UpdateCaseProperty())
    registry.register(SetGoal())
    return registry
