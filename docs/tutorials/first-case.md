# Tutorial: your first case, end-to-end

You will load a process, create a case, watch the rule engine reason
about it, execute the recommendation, and inspect the audit trail —
all in under ten minutes. No ontorag needed for this walkthrough; the
rule engine is local-only.

## Prerequisites

```bash
git clone https://github.com/nuri428/ontorag-flow.git
cd ontorag-flow
uv sync --extra dev
```

That's it. SQLite is the default store, the rule engine has no backing
client, and `examples/medical_triage/` ships a ready-to-use process.

## 1. Run the bundled demo

The fastest "did it work?" check:

```bash
uv run python examples/medical_triage/run_demo.py
```

The script prints the rule engine's reasoning step-by-step, watches the
case auto-close on goal satisfaction, and exports a PROV-O Turtle audit
trail to stdout. **You're done in 30 seconds.**

What you just ran:

- Loaded `examples/medical_triage/process.yaml`
- Created a synthetic patient case with `severity=8, age=42`
- Asked `RuleEngine` for proposals — got `triage_level=urgent` (rule
  fired because `severity >= 7`)
- Executed the top proposal, the case auto-closed (goal:
  `diagnosed: true` met by a follow-up rule)
- Rendered the audit trail as PROV-O Turtle

## 2. The same thing, step-by-step, in the CLI

Now you'll drive the same flow manually so you see each surface.

```bash
# 2a. Load the process into the persistent SQLite store
uv run ontorag-flow process load examples/medical_triage/process.yaml

# 2b. List loaded processes
uv run ontorag-flow process list

# 2c. Create a case with initial state
uv run ontorag-flow case create urn:ontorag-flow:process:medical-triage \
    -s severity=8 -s age=42
#   →  prints the new case URI; save it
CASE=urn:ontorag-flow:case:...

# 2d. Ask the engine what it would do — no execution
uv run ontorag-flow case propose-next $CASE

# 2e. Execute the top proposal (or any proposal of your choice)
uv run ontorag-flow case execute $CASE \
    urn:ontorag-flow:action:UpdateCaseProperty \
    -p key=triage_level -p value=urgent

# 2f. Inspect the new state
uv run ontorag-flow case status $CASE

# 2g. Render the audit trail
uv run ontorag-flow audit show $CASE
uv run ontorag-flow audit export $CASE --format turtle
```

## 3. The same thing, in the browser

```bash
uv run ontorag-flow serve
# →  http://localhost:8100/ui/
```

What to click:

- **`/ui/`** — your case appears in the dashboard. Click it.
- **`/ui/cases/<uri>`** — state JSON, proposals table, lifecycle
  buttons. Click **`Execute top proposal`** to run the recommendation
  via the UI.
- **"Decision engine proposals — why? →"** link → **`/ui/cases/<uri>/explain`**
  — see *which rule fired*, with confidence bar and rationale.
- **"full audit trail →"** → **`/ui/cases/<uri>/audit`** — every
  PROV-O activity row with a **`Counterfactual`** link to ask "what if
  Y instead at this step?".

See the [Operator guide](../operator-guide.md) for the per-button walkthrough.

## 4. Dry-run while editing the YAML

When authoring a process, you don't want every test run to leave cases
in the dev DB. `process simulate` builds an in-memory case + manager,
runs the engine, optionally executes the top proposal, and exits — no
persistence:

```bash
uv run ontorag-flow process simulate \
    examples/medical_triage/process.yaml \
    -s severity=8 -s age=42 \
    --execute-top \
    --explain
```

`--explain` prints the same `engine.explain()` trace the `/explain`
page renders.

## 5. Lock in regressions in the YAML itself

Add an `expectations:` block to your process YAML and run
`process test` as a regression check:

```yaml
# in examples/medical_triage/process.yaml
expectations:
  - name: high-severity routes to urgent
    given_state: { severity: 8, age: 42 }
    proposes: urn:ontorag-flow:action:UpdateCaseProperty
    after_execute_top:
      state: { triage_level: urgent }
```

```bash
uv run ontorag-flow process test examples/medical_triage/process.yaml
# ✓ All 1 expectation(s) passed.
```

The YAML now ships its own regression test — author the process, ship
the test alongside it, never lose the invariant.

## Next steps

- [Tutorial: authoring a process YAML](authoring-process.md) — write
  your own from scratch with constraints + timer events.
- [Tutorial: writing an action plugin](action-plugin.md) — ship a
  domain-specific action as a Python package.
- [How-to: wire a decision engine](../how-to/engines.md) — pick the
  right engine for your decision shape.
