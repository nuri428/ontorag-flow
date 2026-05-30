# Tutorial: authoring a process YAML

You will write a complete process YAML from scratch — allowed actions,
goal, initial state, rule engine table, ordering constraints, a timer
event — and use `process simulate` + `process test` to iterate.

## Scenario

A simplified onboarding process. The case has a `stage` property; the
goal is `onboarded: true`. The rule engine drives state transitions:

1. New case → propose `RequestDocuments`
2. Documents received → propose `VerifyIdentity`
3. Identity verified → propose `MarkOnboarded` (sets `onboarded: true`)

Two safety constraints:

- `VerifyIdentity` `requires` `RequestDocuments` to have fired first.
- A timer fires `RequestDocuments` automatically 60 minutes after the
  case opens, in case nobody triggers it manually.

## Step 1 — minimum viable YAML

Create `onboarding.yaml`:

```yaml
process_uri: urn:my-domain:process:onboarding
name: Customer onboarding
allowed_actions:
  - urn:ontorag-flow:action:UpdateCaseProperty
goal:
  onboarded: true
initial_state:
  stage: new
```

Smoke-load it:

```bash
ontorag-flow process simulate onboarding.yaml
# →  Engine returned no proposals.    (expected — no rules yet)
```

## Step 2 — add the rule table

```yaml
rules:
  - name: request-documents
    when: { stage: new }
    then:
      action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: stage, value: documents_requested }
    confidence: 1.0

  - name: verify-identity
    when: { stage: documents_received }
    then:
      action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: stage, value: identity_verified }
    confidence: 1.0

  - name: mark-onboarded
    when: { stage: identity_verified }
    then:
      action: urn:ontorag-flow:action:UpdateCaseProperty
      params: { key: onboarded, value: true }
    confidence: 1.0
```

Verify the first rule fires:

```bash
ontorag-flow process simulate onboarding.yaml --execute-top
# Engine returns "request-documents", executes, prints new state.
```

## Step 3 — encode `requires` constraint

The rule engine will *propose* `VerifyIdentity` based on `stage`, but
your domain wants extra safety: `VerifyIdentity` should never fire
*without* `RequestDocuments` having fired first, even if the state was
seeded manually.

Add a `constraints:` block:

```yaml
allowed_actions:
  - urn:ontorag-flow:action:UpdateCaseProperty
  - urn:my-domain:action:VerifyIdentity     # add the named action
  - urn:my-domain:action:RequestDocuments

constraints:
  requires:
    urn:my-domain:action:VerifyIdentity:
      - urn:my-domain:action:RequestDocuments
```

`CaseManager.execute_action` checks `constraints.requires` before
running and raises `ConstraintViolationError` if the prerequisite
isn't in the case history. The error surfaces in the UI as an inline
`?error=` callout.

## Step 4 — add a timer event

The CMMN-style timer fires `RequestDocuments` 60 minutes after the
case opens — a safety net so a forgotten case still progresses:

```yaml
timer_events:
  - after_minutes: 60
    action: urn:my-domain:action:RequestDocuments
    params: {}
```

`CaseManager.tick()` sweeps all open cases for elapsed timers and runs
the corresponding actions. Wire it to a cron (every 5 min) or hit the
UI's **Tick all timers** button from the dashboard.

## Step 5 — lock the contract with expectations

`process test` runs an inline regression block:

```yaml
expectations:
  - name: new-case proposes RequestDocuments
    given_state: { stage: new }
    proposes: urn:ontorag-flow:action:UpdateCaseProperty
    after_execute_top:
      state: { stage: documents_requested }

  - name: documents-received proposes VerifyIdentity-via-rule
    given_state: { stage: documents_received }
    proposes: urn:ontorag-flow:action:UpdateCaseProperty
    after_execute_top:
      state: { stage: identity_verified }

  - name: identity-verified closes the case
    given_state: { stage: identity_verified }
    after_execute_top:
      state: { onboarded: true }
```

```bash
ontorag-flow process test onboarding.yaml
# ✓ All 3 expectation(s) passed.
```

The process now ships its own regression suite. Future edits that
break the rule table fail loudly.

## Step 6 — visualise

Load the process into the persistent store and view the diagram:

```bash
ontorag-flow process load onboarding.yaml
ontorag-flow serve
# →  http://localhost:8100/ui/processes/urn:my-domain:process:onboarding/diagram
```

The CMMN-style SVG shows allowed actions as nodes, `requires` edges in
blue, the `RequestDocuments` timer ⏱ glyph above its target.

## What you skipped (on purpose)

- **`engine: stacked` or `cascade`** — keep it RuleEngine first; arbitration
  pays off when proposers disagree. See [How-to: engines](../how-to/engines.md).
- **`bayesian:` / `causal:` blocks** — need live ontorag MCP. See
  [How-to: ontorag](../how-to/ontorag.md).
- **Custom action implementations** — the YAML only references action
  *URIs*; the Python `BaseAction` subclasses come from the registry.
  See [Writing an action plugin](action-plugin.md).
