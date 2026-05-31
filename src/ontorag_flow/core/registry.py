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


_PLUGIN_GROUP = "ontorag_flow.actions"

# Reserved URI namespace for actions shipped by this repository. External
# plugins that try to register an action whose URI starts with this prefix
# are rejected at load time — protects built-in semantics from accidental
# or malicious override via a transitive dependency. Use a plugin-owned
# namespace instead (e.g. urn:my-domain:action:RecordSymptom).
_RESERVED_URI_PREFIX = "urn:ontorag-flow:"


def default_registry(*, load_plugins: bool = True) -> ActionRegistry:
    """Return a registry pre-populated with the built-in action library.

    When ``load_plugins`` is True (default), also discovers actions exposed
    by third-party packages via Python entry points under the
    ``ontorag_flow.actions`` group. Each entry point must resolve to a
    :class:`BaseAction` *class* (not an instance) — the registry instantiates
    it with no arguments. Plugins requiring injected clients (the way
    AssertTriple needs an OntoragClient) should expose a separate registration
    helper instead, modeled after :func:`with_triple_actions`.

    A misbehaving plugin (import error, instantiation error) is logged and
    skipped rather than aborting startup — one broken third-party action
    should not break the whole catalog.
    """

    from ontorag_flow.actions.case_state import SetGoal, UpdateCaseProperty
    from ontorag_flow.actions.human import RequestHumanReview

    registry = ActionRegistry()
    registry.register(UpdateCaseProperty())
    registry.register(SetGoal())
    registry.register(RequestHumanReview())
    if load_plugins:
        _load_plugin_actions(registry)
    return registry


def _load_plugin_actions(registry: ActionRegistry) -> None:
    """Discover and register actions exposed via the entry-point group.

    Each entry must resolve to a BaseAction subclass; we instantiate it
    no-arg. URI collisions are resolved by registry semantics (last wins),
    which lets users override a built-in action by shipping a plugin with
    the same URI — intentional, lets a deployment swap an implementation.

    Allowlist: when ``ONTORAG_FLOW_PLUGIN_ALLOWLIST`` is set to a
    comma-separated list of entry-point names, any plugin whose name is
    not in the list is skipped (WARN logged). Unset = all plugins load
    (backward-compatible default for dev / single-tenant).
    """

    from importlib.metadata import entry_points

    from ontorag_flow.config import get_settings
    from ontorag_flow.log import get_logger

    logger = get_logger(__name__)
    try:
        eps = entry_points(group=_PLUGIN_GROUP)
    except Exception as exc:  # noqa: BLE001 — entry_points failures shouldn't kill boot
        logger.warning("Could not enumerate %r entry points: %s", _PLUGIN_GROUP, exc)
        return

    raw_allow = get_settings().plugin_allowlist
    allowed: set[str] | None = None
    if raw_allow is not None:
        allowed = {name.strip() for name in raw_allow.split(",") if name.strip()}

    for entry in eps:
        if allowed is not None and entry.name not in allowed:
            logger.warning(
                "Plugin %r (entry-point %r) not in ONTORAG_FLOW_PLUGIN_ALLOWLIST; skipping.",
                entry.value,
                entry.name,
            )
            continue
        try:
            action_cls = entry.load()
            instance = action_cls()
            # Strict isinstance check rather than hasattr(..., "uri"). Hasattr
            # accepts any class with a `uri` class var (e.g. a half-finished
            # plugin missing execute()) and lets it register, then crashes at
            # action-run time with bad locality. Fail fast at register time so
            # the operator sees the offending entry-point name in the log.
            if not isinstance(instance, BaseAction):
                raise TypeError(
                    f"{entry.value!r} resolved to {type(instance).__name__}, "
                    f"which is not a BaseAction subclass."
                )
            if instance.uri.startswith(_RESERVED_URI_PREFIX):
                raise ValueError(
                    f"plugin action URI {instance.uri!r} uses the reserved "
                    f"{_RESERVED_URI_PREFIX!r} namespace (built-ins only). "
                    f"Use a plugin-owned namespace like urn:<your-domain>:action:Xxx."
                )
            registry.register(instance)
            logger.info("Registered plugin action %r from %s", instance.uri, entry.value)
        except Exception as exc:  # noqa: BLE001 — one bad plugin must not break the catalog
            logger.warning("Skipping plugin action %r: %s", entry.value, exc)


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
