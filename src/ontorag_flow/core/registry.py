"""Action registry — the catalog of actions available to a process.

Built-in actions register themselves via :func:`default_registry`. External
plugin actions are loaded at runtime by the CLI (``action register``).
"""

from __future__ import annotations

from ontorag_flow.core.action import BaseAction


class ActionRegistry:
    """An in-memory map of action URI -> action instance.

    Typed against :class:`BaseAction` (not the structural :class:`Action`
    protocol) because concrete actions narrow ``execute(params: Params, ...)``
    to their own Params class — a Liskov violation against the Protocol that
    is harmless at runtime but rightly flagged by type checkers. BaseAction
    is what gets registered in practice.
    """

    def __init__(self) -> None:
        self._actions: dict[str, BaseAction] = {}

    def register(self, action: BaseAction) -> None:
        """Register an action, replacing any prior action with the same URI."""

        self._actions[action.uri] = action

    def get(self, uri: str) -> BaseAction | None:
        return self._actions.get(uri)

    def all(self) -> list[BaseAction]:
        return list(self._actions.values())

    def __contains__(self, uri: object) -> bool:
        return uri in self._actions

    def __len__(self) -> int:
        return len(self._actions)


def default_registry() -> ActionRegistry:
    """Return a registry pre-populated with the built-in action library."""

    from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty
    from ontorag_flow.actions.human import RequestHumanReview

    registry = ActionRegistry()
    registry.register(UpdateCaseProperty())
    registry.register(SetGoal())
    registry.register(RequestHumanReview())
    return registry


def with_triple_actions(registry: ActionRegistry, client: object) -> ActionRegistry:
    """Add the ABox write-back actions, bound to an ``OntoragClient``.

    Kept separate from :func:`default_registry` because
    :class:`AssertTriple` / :class:`RetractTriple` need a live MCP client
    injected — they have an ``ABOX_WRITE`` side effect, which is illegal
    to register if the client is absent. The composition root (CLI /
    API lifespan) calls this *after* successfully constructing the
    client, and only then.
    """

    from ontorag_flow.actions.triples import AssertTriple, RetractTriple

    if not hasattr(client, "call_tool"):
        raise TypeError(
            "with_triple_actions requires an OntoragClient-shaped client "
            "(must expose async call_tool)."
        )
    registry.register(AssertTriple(client))  # type: ignore[arg-type]
    registry.register(RetractTriple(client))  # type: ignore[arg-type]
    return registry
