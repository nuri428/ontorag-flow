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

The same process, the same custom actions, the same constraints — only
the engine changes:

```bash
# fake mode (deterministic, no API key) — what CI runs
uv run python examples/supply_chain_rca/run_demo_llm.py

# live mode against a real model
LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-4-6 \
    uv run python examples/supply_chain_rca/run_demo_llm.py
```

In **fake mode** a small `FakeReasoningLlm` parses the prompt for current
case state and returns deterministic LLM-ish proposals so you can read
the framework's wiring (prompt → JSON → ranked proposals) without paying
for tokens. Visible in the output as a `FAKE` mode label and notably
richer rationales than the rule engine's terse one-liners.

In **live mode** the real Anthropic / OpenAI / Ollama SDK is called.

In both modes the CMMN constraints (`requires`) are still enforced by
the case manager, so the LLM can't skip steps even if it tries.

`run_demo_llm.py` demonstrates the key claim of the framework: *process
definition is data, engine is policy.* The same `process.yaml` runs
under either `RuleEngine` (`run_demo.py`) or `LlmAgentEngine`
(`run_demo_llm.py`); the engine override happens in code with
`process.model_copy(update={"engine": "llm"})`.

## Files

```
examples/supply_chain_rca/
├── actions.py          # RecordEvidence / QuerySupplier / RouteThroughBackup / ApproveCompensation
├── process.yaml        # allowed_actions + goal + requires + 4 RuleEngine rules
├── run_demo.py         # RuleEngine-driven (the rule-engine path)
├── run_demo_llm.py     # LlmAgentEngine-driven; fake reasoning by default, live with LLM_PROVIDER
└── README.md           # this file
```
