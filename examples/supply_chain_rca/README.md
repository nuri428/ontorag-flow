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

### What changes between fake and live

| | fake mode (deterministic) | live mode (real LLM) |
|---|---|---|
| Reasoning shape | Hand-written `if/elif` against the parsed prompt | Free-form generation conditioned on the action catalog |
| Output stability | Identical bytes every run | Non-deterministic by default (temperature, sampling) |
| Rationale text | Static LLM-ish prose per branch | Genuinely written per call, may surface unexpected angles |
| When the engine picks a wrong action | Won't — the fake is hard-coded | Possible — the agent might confabulate |
| Cost / latency | 0 ms, $0 | network round-trip + token charges |
| Use it for | CI, local development, demos | benchmarking, real engagements |

### What's still enforced regardless of mode

Three pieces of the framework are *not* the engine's responsibility, and
they catch the most common LLM failure modes for free:

- **Unknown `action_uri`** — the LLM occasionally hallucinates an action
  outside the process's allowed set. `LlmAgentEngine._parse` filters them
  out before the proposal even reaches the case manager.
- **Malformed JSON** — code fences, prose preamble, trailing
  commentary. `_extract_json_array` strips fences and walks the prose
  looking for a bracketed array, then tolerantly parses each entry.
- **Prerequisite violations** — even if the LLM proposes
  `RouteThroughBackup` before `QuerySupplier`, `CaseManager.execute_action`
  refuses with `ConstraintViolationError` because of the `requires`
  block in `process.yaml`. The engine is policy; constraints are law.

The combination means a *worst-case* LLM session just fails actions
that violate contracts — it can't push the case into an invalid state.

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
