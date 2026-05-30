# Built-in actions

## Catalog

| Action URI | Side effects | What it does |
|---|---|---|
| `urn:ontorag-flow:action:UpdateCaseProperty` | CASE_STATE | Set one key/value on the case state |
| `urn:ontorag-flow:action:SetGoal` | CASE_STATE | Declare / replace the goal predicate |
| `urn:ontorag-flow:action:RequestHumanReview` | HUMAN + CASE_STATE | Mark the case for human review — auto-suspends |
| `urn:ontorag-flow:action:AssertTriple` | ABOX_WRITE | Write one `(s, p, o)` triple to ontorag's ABox (only registered when an `OntoragClient` is live) |
| `urn:ontorag-flow:action:RetractTriple` | ABOX_WRITE | Remove one `(s, p, o)` triple from ontorag's ABox (saga-compensates each other with `AssertTriple`) |

## Side-effect kinds

| `SideEffectKind` | What it triggers |
|---|---|
| `NONE` | Pure proposal/render action; no audit, no state change |
| `CASE_STATE` | Changes the case's properties or goal; audit is written-after-execute |
| `EXTERNAL_API` | Makes a call to an external service; **write-ahead audit** — pending row before, completed/failed after |
| `HUMAN` | Surfaces a human-review need; auto-suspends the case; write-ahead audit |
| `ABOX_WRITE` | Writes triples to ontorag's ABox; write-ahead audit; saga `compensate` MUST be implemented |

The executor inspects `action.side_effects` to decide:

- Whether to write a **pending** activity row *before* `execute()` runs
  (so a crash mid-execute still leaves a forensic record — premortem P7).
- Whether `compensate()` is callable on rollback (a sane default exists
  for `CASE_STATE` via the `state_before` snapshot; ABOX_WRITE / EXTERNAL_API
  must implement it themselves).

## Plugin discovery

External packages can register actions via Python entry points:

```toml
# my_package's pyproject.toml
[project.entry-points."ontorag_flow.actions"]
my_action = "my_package.actions:MyAction"
```

`default_registry()` discovers and instantiates them no-arg on boot.
Plugin URIs colliding with built-ins are *intentional override path*
(last-write wins). A misbehaving plugin (import error, instantiation
error) is logged and skipped — one bad plugin must not abort boot.

For actions that need injected clients (the way `AssertTriple` needs an
`OntoragClient`), ship a separate registration helper modeled after
[`with_triple_actions`](python-api.md#coreregistry).

## Writing a custom action

Subclass `BaseAction`, declare `uri` / `name` / `description` /
`side_effects` / `input_schema`, implement `execute`:

```python
from typing import ClassVar
from pydantic import BaseModel, Field
from ontorag_flow.core.action import ActionResult, BaseAction, SideEffectKind
from ontorag_flow.core.state import CaseState


class RecordSymptom(BaseAction):
    uri: ClassVar[str] = "urn:my-domain:action:RecordSymptom"
    name: ClassVar[str] = "Record Symptom"
    description: ClassVar[str] = "Record a symptom on the case."
    side_effects: ClassVar[frozenset[SideEffectKind]] = frozenset({SideEffectKind.CASE_STATE})

    class Params(BaseModel):
        symptom: str = Field(min_length=1)
        severity: int = Field(ge=1, le=10)

    input_schema: ClassVar[type[BaseModel]] = Params

    async def execute(self, params: Params, state: CaseState) -> ActionResult:
        existing = state.properties.get("symptoms", [])
        return ActionResult(
            action_uri=self.uri,
            success=True,
            outputs={"symptom": params.symptom, "severity": params.severity},
            state_changes={"symptoms": [*existing, {"name": params.symptom, "severity": params.severity}]},
        )
```

For full tutorial including saga compensation see
[Tutorials → Writing an action plugin](../tutorials/action-plugin.md).
