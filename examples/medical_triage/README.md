# Medical triage — reference end-to-end demo

A self-contained one-shot run that exercises the whole v0.1–v0.9 stack:

- a YAML `ProcessDefinition` (this folder's `process.yaml`),
- the `CaseManager` over an in-process `SqliteStore`,
- the rule-engine resolver picking the next action based on case state,
- automatic case closing when the goal is reached,
- the PROV-O audit trail rendered as Turtle.

## Run

```bash
uv run python examples/medical_triage/run_demo.py
```

## What you should see

A synthetic 42-year-old patient enters with `severity: 8`. The rule engine
first proposes `triage_level=urgent` (high-severity escalation, confidence
0.95 — outranks the routine "assess unknown" rule at 0.70), then proposes
`diagnosed=true` (assessment complete). Executing that satisfies the
process goal `{diagnosed: true}` so the case auto-closes.

The script ends with the audit trail table and the first lines of the
PROV-O Turtle export so you can see real `prov:Activity` triples coming
out the other end.

## Pieces this exercises

| Layer | What |
|---|---|
| Process model | `process.yaml` — allowed actions, goal, 3-rule decision table |
| Persistence | `SqliteStore` (in-memory tempdir for the demo) |
| Decision engine | `RuleEngine` resolved from `process.rules` |
| Execution + audit | `ActionExecutor` with `state_before` snapshots |
| Goal closing | `CaseManager.execute_action` auto-suspends/closes |
| Provenance export | `core.provenance.render(activities, "ttl")` |

For the same flow through the **HTTP API**, run `ontorag-flow serve` and
hit `POST /cases` then `POST /cases/{uri}/propose` etc., or open the
read-only inspector at `http://localhost:8100/ui/`.
