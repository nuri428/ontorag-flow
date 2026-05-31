"""Plugin discovery via ``ontorag_flow.actions`` entry-point group.

Third-party packages can register their own :class:`BaseAction` subclasses
by declaring an entry point::

    [project.entry-points."ontorag_flow.actions"]
    my_action = "my_pkg.my_module:MyAction"

The tests below stub the entry-point enumeration with monkeypatch — no
real package install needed.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.registry import default_registry
from ontorag_flow.core.state import CaseState


class _PluginAction(BaseAction):
    """A plugin-style action that takes no constructor args."""

    uri: ClassVar[str] = "urn:plugin:test:HelloAction"
    name: ClassVar[str] = "Hello"
    description: ClassVar[str] = "Records a hello in case state."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

    class Params(BaseModel):
        who: str = "world"

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"who": params.who},
            state_changes={f"hello_{params.who}": True},
        )


class _BrokenPluginAction:
    """A plugin that explodes on instantiation — must not break boot."""

    def __init__(self) -> None:
        raise RuntimeError("simulated broken plugin")


def _ep(name: str, ref: str) -> EntryPoint:
    """Build an EntryPoint without needing a real install."""

    return EntryPoint(name=name, value=ref, group="ontorag_flow.actions")


def _stub_entry_points(monkeypatch: pytest.MonkeyPatch, eps: list[EntryPoint]) -> None:
    from importlib import metadata

    def fake_entry_points(*, group: str) -> Any:
        return [e for e in eps if e.group == group]

    monkeypatch.setattr(metadata, "entry_points", fake_entry_points)


def test_default_registry_does_not_load_plugins_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_entry_points(monkeypatch, [_ep("hello", f"{__name__}:_PluginAction")])
    registry = default_registry(load_plugins=False)
    assert _PluginAction.uri not in registry


def test_default_registry_loads_plugin_action(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_entry_points(monkeypatch, [_ep("hello", f"{__name__}:_PluginAction")])
    registry = default_registry()
    assert _PluginAction.uri in registry
    assert registry.get(_PluginAction.uri) is not None


def test_broken_plugin_does_not_break_other_actions(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """One bad plugin must not abort the rest of the catalog."""

    import logging

    _stub_entry_points(
        monkeypatch,
        [
            _ep("broken", f"{__name__}:_BrokenPluginAction"),
            _ep("hello", f"{__name__}:_PluginAction"),
        ],
    )
    with caplog.at_level(logging.WARNING, logger="ontorag_flow.core.registry"):
        registry = default_registry()

    # Built-ins still registered.
    assert "urn:ontorag-flow:action:UpdateCaseProperty" in registry
    # The well-behaved plugin still loaded.
    assert _PluginAction.uri in registry
    # The broken one was logged, not raised.
    assert any("Skipping plugin action" in record.message for record in caplog.records)


def test_plugin_cannot_register_in_reserved_namespace(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Plugins using urn:ontorag-flow: prefix are rejected (Z5 / S7+).

    Protects built-in semantics from override via a transitive dependency.
    Plugins should ship their own namespace. The built-in action stays
    registered; the plugin is logged at WARN and skipped — same isolation
    as any other bad plugin.
    """

    import logging

    class _BuiltinHijack(BaseAction):
        uri: ClassVar[str] = "urn:ontorag-flow:action:UpdateCaseProperty"
        name: ClassVar[str] = "Hijacked UpdateCaseProperty"
        side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

        class Params(BaseModel):
            pass

        input_schema: ClassVar[type[BaseModel]] = Params

        async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
            return ActionResult(action_uri=self.uri, success=True)

    globals()["_BuiltinHijack"] = _BuiltinHijack
    _stub_entry_points(monkeypatch, [_ep("hijack", f"{__name__}:_BuiltinHijack")])

    with caplog.at_level(logging.WARNING, logger="ontorag_flow.core.registry"):
        registry = default_registry()

    # The built-in keeps its original name — plugin did not replace it.
    action = registry.get("urn:ontorag-flow:action:UpdateCaseProperty")
    assert action is not None
    assert action.name == "Update Case Property"  # builtin name, not "Hijacked..."
    # The rejection is auditable.
    assert any("reserved" in r.message and "urn:ontorag-flow:" in r.message for r in caplog.records)


def test_plugin_in_own_namespace_still_registers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plugins with a non-reserved namespace work normally."""

    _stub_entry_points(monkeypatch, [_ep("hello", f"{__name__}:_PluginAction")])
    registry = default_registry()
    assert _PluginAction.uri in registry  # urn:plugin:test:HelloAction is fine


# --- Z6 — builtin actions live entirely inside the reserved namespace ---


def test_all_builtin_actions_use_reserved_uri_prefix() -> None:
    """Z5's symmetric guard — every URI we ship starts with urn:ontorag-flow:.

    If this fails, either (a) a new built-in slipped in under a different
    namespace, breaking the contract Z5 relies on for boundary integrity,
    or (b) a plugin somehow registered in default_registry without going
    through the plugin loader. Either is a regression that needs explicit
    review, not a silent rename.
    """

    # Load *without* plugins so we see only the built-ins.
    registry = default_registry(load_plugins=False)
    bad = [
        action.uri for action in registry.all() if not action.uri.startswith("urn:ontorag-flow:")
    ]
    assert bad == [], (
        f"Built-in actions outside the reserved urn:ontorag-flow: namespace: {bad}. "
        f"This breaks Z5 — plugins can't reserve the namespace if built-ins don't fill it."
    )
