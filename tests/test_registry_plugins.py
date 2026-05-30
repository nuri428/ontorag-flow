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


def test_plugin_can_override_builtin_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plugin with the same URI as a built-in wins — intentional override path."""

    class _Override(BaseAction):
        uri: ClassVar[str] = "urn:ontorag-flow:action:UpdateCaseProperty"
        name: ClassVar[str] = "Custom UpdateCaseProperty"
        side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

        class Params(BaseModel):
            pass

        input_schema: ClassVar[type[BaseModel]] = Params

        async def execute(self, params: Params, state: CaseState) -> ActionResult:  # type: ignore[override]
            return ActionResult(action_uri=self.uri, success=True)

    # Make the override discoverable as a module attribute the EntryPoint can find.
    globals()["_Override"] = _Override
    _stub_entry_points(monkeypatch, [_ep("override", f"{__name__}:_Override")])

    registry = default_registry()
    action = registry.get("urn:ontorag-flow:action:UpdateCaseProperty")
    assert action is not None
    assert action.name == "Custom UpdateCaseProperty"
