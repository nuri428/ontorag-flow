# Tutorial: writing an action plugin

You will ship a domain action as a separate Python package that
`ontorag-flow` discovers automatically via Python entry points — no
touching this repo's source.

## Scenario

Your domain needs a `RecordSymptom` action: appends a symptom to the
case's `symptoms` list, with severity 1–10. Stateful but
self-contained, no external service. Compensation is straight-forward
(remove the most recent matching symptom).

## Project layout

```
my-symptom-action/
├── pyproject.toml
└── src/
    └── my_symptom_action/
        ├── __init__.py
        └── actions.py
```

## `pyproject.toml`

```toml
[project]
name = "my-symptom-action"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "ontorag-flow",
    "pydantic>=2.6",
]

[project.entry-points."ontorag_flow.actions"]
record_symptom = "my_symptom_action.actions:RecordSymptom"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

The `[project.entry-points."ontorag_flow.actions"]` block is the wiring
that makes `ontorag-flow`'s `default_registry()` find your class on
boot. The key (`record_symptom`) is the entry-point name; the value
is `<dotted.module>:<ClassName>`.

## `src/my_symptom_action/actions.py`

```python
"""RecordSymptom — plugin action over ontorag-flow."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field, conint

from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.state import CaseState


class RecordSymptom(BaseAction):
    """Append one (symptom, severity) entry to the case's symptoms list."""

    uri: ClassVar[str] = "urn:my-domain:action:RecordSymptom"
    name: ClassVar[str] = "Record symptom"
    description: ClassVar[str] = (
        "Append a symptom + severity to the case's symptoms list. "
        "Severity must be 1–10."
    )
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset(
        {SideEffectKind.CASE_STATE}
    )

    class Params(BaseModel):
        symptom: str = Field(min_length=1, description="The symptom name.")
        severity: int = Field(ge=1, le=10, description="Severity 1–10.")

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:
        existing = list(state.properties.get("symptoms", []))
        existing.append({"name": params.symptom, "severity": params.severity})
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"symptom": params.symptom, "severity": params.severity},
            state_changes={"symptoms": existing},
        )

    async def compensate(self, result: ActionResult) -> None:
        """Saga rollback: leave it to the executor's state_before restore.

        We don't make external calls, so the executor's automatic
        snapshot is enough — no extra work here.
        """
        return None
```

A few things to notice:

- **`ClassVar` everywhere** for class attributes. `BaseAction` checks
  these at register time; instance attributes would be skipped.
- **`Params` as a nested `BaseModel`**. Pydantic v2 validates *before*
  `execute` is called; bad input never reaches your code.
- **`side_effects = {CASE_STATE}`**. The executor takes a `state_before`
  snapshot for you; the default `compensate` (restore-from-snapshot)
  works for any `CASE_STATE`-only action.

## Install + verify

```bash
# In a fresh venv with ontorag-flow installed
pip install -e /path/to/my-symptom-action

# Restart any running server / CLI session so default_registry picks
# up the new entry point.
ontorag-flow action list
# … should now include urn:my-domain:action:RecordSymptom

ontorag-flow action run urn:my-domain:action:RecordSymptom \
    -p symptom=fever -p severity=8
# success: True
# outputs: {"symptom": "fever", "severity": 8}
# new state: {"properties": {"symptoms": [{"name": "fever", "severity": 8}]}}
```

## Use it in a process

```yaml
process_uri: urn:my-domain:process:symptom-tracking
name: Symptom tracking
allowed_actions:
  - urn:my-domain:action:RecordSymptom
goal:
  diagnosed: true
```

```bash
ontorag-flow process load symptom-tracking.yaml
ontorag-flow case create urn:my-domain:process:symptom-tracking
ontorag-flow case execute <case_uri> \
    urn:my-domain:action:RecordSymptom \
    -p symptom=cough -p severity=5
```

## Actions that need a client

If your action calls an external service (HTTP, MCP, etc.) you can't
use entry-points alone — the action needs a client injected at
construction time. Ship a helper modeled after
[`with_triple_actions`](../reference/python-api.md#coreregistry):

```python
def with_my_api_actions(registry, http_client):
    """Compose helper: call from your app's lifespan after building the client."""
    registry.register(MyApiAction(http_client))
    return registry
```

And declare the dependency in `pyproject.toml` (don't try to share via
entry-points — they execute no-arg).

## Failure modes (and how `default_registry` handles them)

- **Import fails** at registry boot → logged at WARN, plugin skipped,
  other plugins continue.
- **`MyAction()` raises** at instantiation → same: logged, skipped.
- **`isinstance(instance, BaseAction)` fails** → "not a BaseAction
  subclass" in the log; instance not registered.
- **URI collides** with a built-in → intentional override (last write
  wins). Lets a deployment swap an implementation without forking.

One bad plugin must not abort boot — that's the contract.

## Test the action

`pytest` works against a plain `CaseState`:

```python
import pytest
from my_symptom_action.actions import RecordSymptom
from ontorag_flow.core.state import CaseState


async def test_record_symptom_appends_to_list():
    action = RecordSymptom()
    state = CaseState(properties={"symptoms": [{"name": "ache", "severity": 3}]})
    result = await action.execute(
        action.Params(symptom="fever", severity=8), state
    )
    assert result.state_changes == {
        "symptoms": [
            {"name": "ache", "severity": 3},
            {"name": "fever", "severity": 8},
        ]
    }
```

Pydantic params validation happens automatically — pass a bad value
and your test gets a `ValidationError`.

## Where to next

- [Reference → Built-in actions](../reference/actions.md) — table + the
  side-effect kinds map
- [Reference → Python API](../reference/python-api.md#actionstriples) —
  full type signatures
- [Operator guide](../operator-guide.md) — your plugin action shows up
  in `/ui/actions` after a server restart
