# How-to: wire a decision engine

Goal-oriented recipes for picking and configuring a `DecisionEngine`.
For the *type-level* catalog see [Reference → Decision engines](../reference/engines.md).

## Pick by data shape

| If your decision is best described as… | Use |
|---|---|
| a table of conditions → actions | **RuleEngine** |
| "what's most likely given the observed evidence" | **BayesianMpeEngine** |
| "what's most likely *if we intervened*" | **CausalSimulationEngine** |
| free-form reasoning over goal + actions | **LlmAgentEngine** |
| anything — defer to human review every time | **HumanReviewEngine** |
| LLM proposals, validated by causal posterior | **StackedEngine** |
| try LLM first, fall back to rules, then human | **CascadeEngine** |

## RuleEngine — operators

`when:` values are matched against `case.state.properties`:

```yaml
when:
  severity: { gte: 7 }            # numeric comparison
  triage_level: unknown           # equality (scalar)
  symptom: { in: [fever, cough] } # membership
  consent: { exists: true }       # property is present (non-None)
  patient_age: { lt: 18 }         # combine via multiple keys (AND)
```

Supported operators: `eq` / `ne` / `gt` / `gte` / `lt` / `lte` / `in` /
`exists`. An unknown operator (`gtt` etc.) fails the rule at parse time
— a typo never silently makes a rule never-fire.

## BayesianMpeEngine — `compute_posterior` shape

The engine expects ontorag's `compute_posterior` MCP tool to return a
JSON payload with a numeric `posterior` field (the exact extractor lives
in `engines/_posteriors.py` and handles a few common shapes).

```yaml
bayesian:
  target: { diagnosed: true }       # the goal proposition
  query_tool: compute_posterior     # optional (default)
  candidates:
    - action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: triage_level, value: urgent }
      evidence: { severity: high }  # extra evidence assumed if this candidate runs
```

## CausalSimulationEngine — interventions

Same shape as Bayesian, but the candidate carries an `intervention`
payload that becomes the `do(...)` argument to ontorag's `do_query` MCP
tool:

```yaml
causal:
  target: { diagnosed: true }
  query_tool: do_query                  # optional (default)
  candidates:
    - action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: triage_level, value: urgent }
      intervention: { triage_level: urgent }
```

## LlmAgentEngine — provider + prompt control

Set `LLM_PROVIDER` (and optionally `LLM_MODEL`):

```bash
LLM_PROVIDER=anthropic LLM_MODEL=claude-sonnet-4-6 ontorag-flow serve
```

YAML opt-in:

```yaml
engine: llm
allowed_actions:
  - urn:ontorag-flow:action:UpdateCaseProperty
  - urn:my-domain:action:OrderLabTest
```

The engine enriches its prompt with each allowed action's `description`
+ `input_schema` so the LLM proposes well-formed `params`. Proposals
parsing is tolerant — fenced ```json blocks, a top-level
`{"proposals": [...]}` object, or a bare array all work.

## StackedEngine — proposer + causal validator

The validator's `score_intervention` is called with the proposer's
params as the intervention payload, so each proposal gets a **same
intervention, different probability mass** rescoring.

```yaml
engine: stacked
arbitration:
  proposer: rule            # rule | bayesian | llm | human
  validator: causal         # only causal exposes score_intervention today
rules: [...]
causal:
  target: { diagnosed: true }
  candidates: [...]
```

## CascadeEngine — fallback chain

First engine that returns a non-empty proposal list wins. Engines after
the winner are *not* invoked, so a `[llm, rule, human]` cascade doesn't
incur an LLM call when the rule engine would have answered.

```yaml
engine: cascade
arbitration:
  sequence: [llm, rule, human]
rules: [...]
```

`explain()` records the *fallback tail* as `consulted: False`, so you
can see "would the rule engine have answered too?" without paying for
it.

## Inspect what the engine did

`/ui/cases/<uri>/explain` renders engine-specific cards (rules fired /
posterior breakdown / LLM prompt / proposer-vs-validator). Same data
from Python:

```python
explanation = await manager.explain_next(case_uri)
explanation.engine_kind        # e.g. "RuleEngine"
explanation.proposals          # list[ActionProposal]
explanation.trace              # engine-specific dict
```

See [Operator guide → Engine inspector](../operator-guide.md) for the
UI walkthrough.
