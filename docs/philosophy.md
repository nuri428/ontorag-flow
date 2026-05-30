# Philosophy: BPM ↔ ACM, by design

ontorag-flow is the *workflow engine for the LLM era*. This page is
the long-form rationale for the choices that look unusual from a BPM
perspective.

## The spectrum, made concrete

```
   BPM (prescriptive)           ←—— spectrum ——→        ACM (adaptive)
   ─────────────────                                    ────────────
   Camunda / Activiti                  ontorag-flow            CMMN / Palantir
                                          ↑
                                  default: ACM-leaning
```

The same runtime — `CaseManager` + `ActionExecutor` + audit store — runs
both ends. The dial is in the process YAML:

| If the YAML has… | The case behaves like… |
|---|---|
| `engine: rule`, all rules `confidence: 1.0`, `constraints.immediately_after` chains every action, full `skeleton` | a strict state machine that logs PROV-O |
| `engine: rule`, some confidence < 1, partial `skeleton`, `requires` for safety | a recommend-and-confirm workflow (default) |
| `engine: llm` / `causal`, no `skeleton`, only `allowed_actions` + `goal` | a free-form adaptive case driven by reasoning |

You don't reimplement; you tune. A case that started ACM and earned a
proven happy path can graduate to strict by *adding constraints*, not
by rewriting.

## Three architectural insights

### 1. LLM is the decision-maker, not the orchestrator

Classic BPMN treats the *graph* as the decision-maker — gateways encode
"if invoice > $X then approval lane". That worked when no software
could read a case state + a catalog of actions and pick the right next
one. A credible LLM can do exactly that now.

Once the LLM is the decision-maker, a pre-baked BPMN graph is a
*stand-in for missing intelligence*. It rusts: every new exception
becomes a new gateway, every new policy needs a re-deploy. ACM lets the
LLM be the decision-maker without faking it.

The orchestrator's job becomes: present the LLM with case state,
enforce what's coherent (ontology + `constraints`), execute the chosen
action, audit everything. That's what `CaseManager` does.

### 2. Ontology is the guard-rail, not the spec

A BPMN gateway *redeclares* what the ontology already knows: "an Order
in state `paid` can transition to `shipped` only after a
PaymentConfirmed event". The ontology says it once via TBox classes +
relations + DL constraints; the BPMN says it again with different
syntax in a different place.

ontorag-flow lets the ontology be the guard-rail:

- **Actions are anchored in classes** — `AssertTriple` writes into the
  ABox, the schema validates; no free-floating actions.
- **`allowed_actions` is the menu** — the engine can only propose what
  the YAML lets it; the YAML can only allow what makes sense in the
  domain ontology.
- **`AssertTriple` writes through ontorag** — ABox consistency is
  enforced *there*, not duplicated here.

The result: process definitions are *thinner*. The hard semantics live
in the ontology where they belong.

### 3. Goal-driven matches how an LLM thinks

Give an LLM a goal — `diagnosed: true` — and a catalog of actions, and
it reasons forward. Give it "you are currently at node 5, the
transitions to nodes 7 and 9 are enabled" and you're asking it to do
bookkeeping that has nothing to do with the medical reasoning.

CMMN happens to also describe cases this way — goal-driven with allowed
actions and sentries. That's not a coincidence; both architectures are
optimising for *the work being adaptive*, not for the diagram being
pretty.

## Provenance as the BPM response

BPM's strongest argument is *replayability* — "open the BPMN diagram
and you can see exactly what happened, what should have happened, and
where it deviated". ACM's traditional weakness is precisely this:
"adaptive" sometimes meant "you can't tell what the case did unless
you read every event".

ontorag-flow takes that argument away by making provenance
**non-optional**:

- **PROV-O activity per executed action** — agent / inputs / outputs /
  `wasInformedBy` chain / `state_before` snapshot. Every action,
  always.
- **Write-ahead audit (premortem P7)** — for externally-visible side
  effects, a `pending` row is written *before* the action runs; the
  status flips to `completed` / `failed` after. A crash mid-execute
  still leaves a forensic record.
- **`engine.explain()` trace** — RuleEngine records which rule fired;
  BayesianMpe records the posterior breakdown; LlmAgent records the
  exact prompt + raw reply; Causal records the intervention payloads.
  The "why" lives alongside the "what".
- **Skeleton deviation tags** — when the process declares a happy-path
  `skeleton`, executions off the path get
  `deviated_from_skeleton: true` + `skeleton_expected: <uri>` in
  activity metadata. Adaptive *and* you can count tail length.
- **Counterfactual replay** (causal engine + ontorag v0.8+) — Pearl
  Rung 3: "what if Y at step X instead?" against the actual case
  state-before snapshot.

The deal: adaptive *with* full forensic recall. No "we couldn't
reconstruct what happened" excuse. This is the design principle, not
an open question.

## What this rules out (still)

- **BPMN 2.0 XML interchange** — Camunda exists; we're not rebuilding
  its modeller or token execution. If a domain *is* sequence-driven and
  you already have a BPMN engine, wrap it as an `EXTERNAL_API` action
  and let ontorag-flow ground/audit/orchestrate around it.
- **Token-based execution** — the runtime authority is `DecisionEngine`,
  not a token marching through a graph.
- **Visual graph editor** — process is text (YAML or RDF). Diagrams are
  *generated* from the data (see `/ui/processes/<uri>/diagram`); the
  data is not generated from a diagram.

## What this opens up

- A v0 process *starts ACM-leaning*. The team learns which sequences
  are stable, which are exceptional. Stable sequences earn `skeleton`
  + `constraints.immediately_after`; the audit log proves they were
  earned, not assumed.
- Adding an LLM proposer doesn't require a process rewrite — switch
  `engine:` from `rule` to `cascade` with `[llm, rule, human]`. Same
  process YAML, new decision strategy.
- Domain experts add `expectations:` blocks to the YAML and run
  `process test` as a regression suite. The process ships its own
  tests.

The architecture is *one runtime, multiple positions on the spectrum,
provenance throughout*. That's the design.
