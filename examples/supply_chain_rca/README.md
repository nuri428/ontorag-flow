# Supply-chain RCA — open-ended investigation with a human handoff

A second reference example that shows what `examples/medical_triage/`
deliberately doesn't: a domain where a clean decision tree alone isn't
enough.

## Run

```bash
uv run python examples/supply_chain_rca/run_demo.py
```

## The scenario

A shipment is 2 hours overdue. The case manager runs the investigation:

1. **RecordEvidence** — log the observation that started the case.
2. **QuerySupplier** — call the supplier's status endpoint (simulated as
   non-responsive so the demo flow continues to the fallback).
3. **RouteThroughBackup** — switch to the contracted backup carrier.
4. **ApproveCompensation** — declares `SideEffectKind.HUMAN`; the case
   manager auto-suspends so a person can sign off.
5. **(after `manager.resume`)** **UpdateCaseProperty** — the reviewer's
   wrap-up sets `rca_complete=true`, satisfying the process goal, so the
   case auto-closes.

The audit trail captures all 5 activities with full PROV-O provenance
(exported as Turtle at the end of the run).

## What this demo showcases that `medical_triage` doesn't

| | medical_triage | **supply_chain_rca** |
|---|---|---|
| Action library | built-in only (`UpdateCaseProperty`, `SetGoal`) | **4 custom `BaseAction` subclasses** in `actions.py` |
| Side effects | CASE_STATE | CASE_STATE + EXTERNAL_API + **HUMAN** |
| Constraints | none | **`requires` prerequisite chain** (no QuerySupplier without RecordEvidence, no RouteThroughBackup without QuerySupplier) |
| Case lifecycle | open → closed | open → suspended → open → closed |
| Why a stronger engine helps | rule engine is plenty | open-ended hypothesis space — a great fit for `LlmAgentEngine` once configured |

## Switching to the LLM engine

The same process can be driven by `LlmAgentEngine` without changing the
actions or the rules:

```bash
export LLM_PROVIDER=anthropic          # or openai / ollama
export LLM_MODEL=claude-sonnet-4-6
# In process.yaml: add `engine: llm` (or remove the rules: section).
uv run python examples/supply_chain_rca/run_demo.py
```

The agent reads the allowed-action catalog (with each action's
description and input schema) and proposes the next investigation step in
free reasoning. The CMMN constraints (`requires`) still get enforced by the
case manager, so the LLM can't skip steps even if it tries.

## Files

```
examples/supply_chain_rca/
├── actions.py        # RecordEvidence / QuerySupplier / RouteThroughBackup / ApproveCompensation
├── process.yaml      # allowed_actions + goal + requires + 4 RuleEngine rules
├── run_demo.py       # the end-to-end script you ran above
└── README.md         # this file
```
