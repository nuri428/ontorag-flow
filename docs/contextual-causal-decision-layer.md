# Contextual Causal Decision Layer v1

**Status:** Proposed design  
**Scope:** ontorag-flow orchestration layer and the MCP contract required from ontorag  
**Audience:** Codex implementation team, Claude review team

## 1. Purpose

The current causal path ranks configured actions by an interventional outcome probability:

P(Y | do(A))

This is a useful base, but it does not yet make a case-specific treatment decision. Two cases with different observed state can receive the same score, and an action's execution parameters can be mistaken for causal intervention variables.

This design upgrades the flow layer to recommend only actions with a sufficiently large, safe, and identifiable conditional incremental effect against a declared baseline:

Delta(X, A) = P(Y | X, do(A)) - P(Y | X, do(A_baseline))

The flow layer remains an orchestrator. It does not learn a causal graph or estimate an SCM itself; ontorag remains the source of causal identification and estimation.

## 2. Goals

1. Make causal recommendations depend on the current case's pre-treatment evidence and relevant action history.
2. Compare each candidate against a declared baseline rather than ranking absolute outcome probabilities alone.
3. Explicitly map executable action parameters to causal intervention variables.
4. Preserve identification, overlap, uncertainty, and model-version diagnostics through recommendation, human handoff, and audit.
5. Abstain safely when causal support is insufficient.
6. Keep counterfactual analyses separate from real-world execution in provenance.

## 3. Non-goals for v1

- Learn or alter DAGs/SCMs in ontorag-flow.
- Automatically infer a valid adjustment set in the flow layer.
- Optimise a multi-step policy, perform causal RL, or estimate off-policy value.
- Replace the existing do_query path immediately. It remains a compatibility fallback until the new MCP capability is available.

## 4. Process-definition contract

Add a typed causal configuration. The key design rule is that params and intervention are distinct: the former executes an action and the latter sets declared SCM treatment variables.

~~~yaml
engine: causal

causal:
  model_ref: "urn:ontorag:model:triage-v3"
  outcome: { diagnosed: true }
  horizon: case_close
  estimand: risk_difference  # risk_difference | relative_risk

  treatment:
    variable: triage_level
    baseline: { triage_level: standard }

  context:
    include: [severity, age_band, consent, prior_test_result]
    history:
      include_actions: true
      max_events: 10

  decision_policy:
    min_effect: 0.05
    min_lower_bound: 0.00
    require_identified: true
    require_overlap: true
    on_insufficient_evidence: human_review

  candidates:
    - action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: triage_level, value: urgent }
      intervention: { triage_level: urgent }
      utility: { cost: 0.2, risk: 0.1 }
~~~

### Validation rules

- treatment.variable and every candidate intervention key must be declared by the referenced causal model.
- A candidate action must be allowed by the process and its params must satisfy the action schema before it is proposed.
- Only keys in context.include may be sent as case evidence. Post-treatment variables must be rejected by ontorag or flagged as invalid configuration.
- baseline must be valid for the same treatment variable as each candidate.
- No implicit conversion from ActionProposal.params to an intervention is allowed. Stacked engines must use this declared mapping too.

## 5. MCP capability: estimate_effect

Add a first-class MCP tool rather than combining unstructured do_query responses in the UI layer.

### Request

~~~json
{
  "model_ref": "urn:ontorag:model:triage-v3",
  "outcome": {"diagnosed": true},
  "intervention": {"triage_level": "urgent"},
  "baseline": {"triage_level": "standard"},
  "evidence": {"severity": "high", "age_band": "adult"},
  "history": [{"action": "assessment", "at": "2026-09-20T10:00:00Z"}],
  "estimand": "risk_difference",
  "horizon": "case_close"
}
~~~

### Response

~~~json
{
  "effect": 0.12,
  "outcome_probability": 0.78,
  "baseline_probability": 0.66,
  "interval": {"lower": 0.04, "upper": 0.19},
  "identified": true,
  "overlap": true,
  "diagnostics": {
    "adjustment_set": ["severity", "age_band"],
    "warnings": [],
    "model_version": "triage-v3.2"
  }
}
~~~

If this capability is absent, the flow layer may issue paired do_query calls and calculate a point risk difference. Such a fallback must be labelled diagnostics_available=false and may not bypass a policy requiring uncertainty or identification checks.

## 6. Runtime decision flow

1. Build DecisionContext from the case state, using only allowed pre-treatment evidence keys.
2. Extract a bounded, ordered action history from the audit chain.
3. Validate candidate action params, resolve its explicit intervention, and request estimate_effect versus baseline.
4. Gate every result:
   - identified == true when required;
   - overlap == true when required;
   - effect >= min_effect;
   - interval.lower >= min_lower_bound when intervals are available.
5. Rank surviving candidates by robust utility:

~~~text
score = interval.lower - cost_weight * cost - risk_weight * risk
~~~

6. If no candidate passes, emit a human-review proposal with machine-readable rejection reasons. Do not silently select the highest raw posterior.

## 7. Suggested domain types

- DecisionContext: evidence, history, as_of, model_ref.
- CausalEffectEstimate: point effect, two outcome probabilities, interval, identification/overlap flags, diagnostics, model version.
- CausalDecisionRecord: context fingerprint, baseline, all candidate estimates, gates, policy, selected candidate or abstention reason.

The existing ActionProposal.confidence can remain for UI compatibility. For causal proposals it should carry the ranking score, while the full CausalEffectEstimate is retained in the explanation trace and audit record. The UI must label this value as a decision score, not as a calibrated probability.

## 8. Provenance and counterfactuals

Every causal recommendation must record:

- causal model URI and resolved model version;
- evidence key set and a redaction-safe evidence fingerprint;
- requested baseline, intervention, estimand, and horizon;
- full effect estimate and diagnostics;
- candidates rejected by gates and the reason;
- whether a human accepted, modified, or rejected the recommendation.

Counterfactual analyses must be persisted as a separate CausalAnalysisActivity, linked to but not conflated with the executed activity. The analysis context includes the pre-action state, bounded preceding history, alternative intervention, target, model version, and result. It must never be represented as an actual state transition.

## 9. Delivery slices

### Slice A: Contextual effect MVP

- Typed CausalConfig and schema validation.
- Evidence/history extraction and explicit intervention mapping.
- estimate_effect client contract plus compatible do_query fallback.
- Baseline-relative risk-difference ranking.

### Slice B: Safety and abstention

- Identification, overlap, interval, and policy gates.
- Human-review fallback and explanation/UI diagnostics.
- Tests for invalid mappings, forbidden evidence, and no-decision outcomes.

### Slice C: Provenance and counterfactuals

- Causal decision records in audit export.
- Model-version pinning and redaction-safe evidence fingerprints.
- Separate counterfactual-analysis activities with case-history context.

## 10. Acceptance criteria

1. Two cases with different permitted evidence can receive different candidate rankings.
2. Action params and causal interventions can differ; only the declared intervention is sent to ontorag.
3. A candidate with high absolute success probability but lower incremental effect than baseline is not preferred solely for its raw probability.
4. When required diagnostics report non-identification, failed overlap, or an interval lower bound below policy, the engine abstains and requests human review.
5. Every causal proposal and abstention carries model version, context fingerprint, effect estimate, diagnostics, and gate outcomes in its explanation/audit trace.
6. A counterfactual query creates no case-state mutation and is exported as an analysis activity distinct from real execution.
7. Integration tests use a deterministic synthetic SCM where the chosen treatment matches the known conditional treatment effect.

## 11. Team handoff

- **Codex implementation team:** Process schema, engine/runtime behavior, MCP client integration, persistence/API/UI changes, and tests.
- **Claude review team:** Check treatment/intervention separation, temporal validity of evidence, safe fallback behavior, policy gates, provenance completeness, and public API compatibility.
- **Design owner:** Approve any change that weakens abstention conditions, permits implicit intervention mapping, or changes estimand semantics.
