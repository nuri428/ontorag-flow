# Decision engines

Six pluggable engines. Pick explicitly with `engine: <kind>` in the
process YAML, or let the resolver infer from the config present.

## Catalog

| Engine | Picks an action by… | Backing client | Process config |
|---|---|---|---|
| `RuleEngine` | declarative decision table (operators: `eq/ne/gt/gte/lt/lte/in/exists`) | none | `rules:` |
| `BayesianMpeEngine` | `P(goal \| evidence ∪ candidate.evidence)` from ontorag | ontorag MCP (v0.7) | `bayesian:` |
| `CausalSimulationEngine` | `P(goal \| do(intervention))` — Pearl Rung 2 | ontorag MCP (v0.8) | `causal:` |
| `LlmAgentEngine` | LLM reasoning over case state + action catalog | Anthropic / OpenAI / Ollama | `engine: llm` |
| `HumanReviewEngine` | always defer; resulting `RequestHumanReview` auto-suspends | none | `engine: human` |
| `StackedEngine` | proposer (rule / bayesian / llm / human) + causal validator | proposer's client + ontorag MCP | `engine: stacked` + `arbitration: {proposer, validator}` |
| `CascadeEngine` | sequence; first non-empty result wins | union of sub-engine clients | `engine: cascade` + `arbitration: {sequence: [llm, rule, human]}` |

(Stacked and Cascade are the two arbitration modes that compose the
single-engine kinds.)

## Inference order

When `engine:` is not set explicitly, `EngineResolver.kind_for` infers:

1. `causal:` block present → causal
2. `bayesian:` block present → bayesian
3. non-empty `rules:` list → rule
4. otherwise → the resolver's `default` (`"rule"` by default)

## YAML examples

```yaml
# Rule engine — declarative decision table
process_uri: urn:p:triage
name: Triage
allowed_actions: [urn:ontorag-flow:action:UpdateCaseProperty]
goal: { diagnosed: true }
rules:
  - name: high-severity-urgent
    when: { severity: { gte: 7 } }
    then: { action: urn:ontorag-flow:action:UpdateCaseProperty,
            params: { key: triage_level, value: urgent } }
    confidence: 0.95
```

```yaml
# Stacked — proposer + causal validator
engine: stacked
arbitration:
  proposer: rule          # rule | bayesian | llm | human
  validator: causal       # defaults to 'causal' (only engine exposing score_intervention)
rules: [...]
causal:
  target: { diagnosed: true }
  candidates:
    - action: urn:ontorag-flow:action:UpdateCaseProperty
      intervention: { triage_level: urgent }
```

```yaml
# Cascade — fallback chain, first non-empty wins
engine: cascade
arbitration:
  sequence: [llm, rule, human]
rules: [...]
```

## `engine.explain()` — opt-in reasoning trace

Every built-in engine implements `explain(case, process) → EngineExplanation`:

| Engine | What the trace exposes |
|---|---|
| `RuleEngine` | Every rule classified as fired / unmatched / skipped-because-disallowed |
| `BayesianMpeEngine` | `target` + `base_evidence` + per-action posterior map |
| `CausalSimulationEngine` | Interventions per candidate + per-action interventional posteriors |
| `LlmAgentEngine` | System + user prompt verbatim, raw reply, parsed vs returned count |
| `StackedEngine` | Proposer's original confidences alongside the validator's rescored ones, with intervention payload + Δ |
| `CascadeEngine` | Sequence + per-engine attempt count + which engine won; *engines after the winner are not invoked* |
| `HumanReviewEngine` | Single-line policy ("always defer") |

The Web UI inspector at `/ui/cases/<uri>/explain` renders these as
engine-specific cards. From Python: `await manager.explain_next(case_uri)`.

See [Python API → `engines.base.EngineExplanation`](python-api.md#enginesbase).

## Side-effect declaration

Engines never run actions; they only *propose*. The action carries its
own `side_effects` (`CASE_STATE` / `HUMAN` / `ABOX_WRITE` /
`EXTERNAL_API` / `NONE`) which the executor uses to decide whether to
write a *pending* audit row first (the write-ahead audit pattern P7).

See [`actions/` reference →](actions.md) for the built-in action catalog.
