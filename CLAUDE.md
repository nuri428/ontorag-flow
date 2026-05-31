# ontorag-flow

Ontology-aware orchestration & Adaptive Case Management framework. Companion repo to **ontorag** — fills the **Kinetic layer** that ontorag intentionally leaves empty.

## What this is

A workflow / case-management engine that grounds its actions in a formal OWL ontology. ontorag-flow is the **hands and feet**: it executes Kinetic actions (state changes, external calls, ABox updates) that ontorag's Semantic + Dynamic layer recommends.

Together with ontorag, this repo realizes a two-repo decomposition of Palantir's 3-layer ontology frame:

```
┌────────────────────────────┐  ┌──────────────────────────────┐
│  ontorag                   │  │  ontorag-flow (this repo)    │
│                            │  │                              │
│  Semantic ✅ OWL/RDF       │  │  Kinetic  ✅ Actions          │
│  Dynamic  ✅ Bayesian      │←─│  Dynamic  △ Orchestration    │
│           ✅ Causal        │─→│           (decision engines) │
│           ✅ LLMs4OL       │  │                              │
│  Kinetic  ✗ (intentional)  │  │  Semantic ✗ (delegated)      │
└────────────────────────────┘  └──────────────────────────────┘
            ↑                                 ↑
            └──────────── MCP ────────────────┘
       (ontorag-flow is a client of ontorag's MCP;
        ontorag-flow also exposes its own MCP)
```

One-line: *"Adaptive Case Management grounded in formal ontology — ontology-aware actions, pluggable decision engines (rule / Bayesian MPE / LLM agent), MCP-native."*

## Target user

Same developer audience as ontorag: evaluating ontology-based LLM application frameworks. ontorag-flow specifically targets devs who need **closed-loop automation** — not just Q&A over a graph, but actually *taking action* with audit-quality provenance.

## Positioning

### Where on the BPM ↔ ACM spectrum

```
   BPM (prescriptive)              ←—— spectrum ——→            ACM (adaptive)
   ─────────────────                                            ────────────
   "do exactly this sequence"                                   "these actions are allowed,
                                                                 engine decides at runtime"

   Camunda / Activiti                          ontorag-flow                CMMN / pure ACM
   Flowable / Temporal                       (configurable)             Palantir Workshop
                                                  ↑
                                          default: ACM-leaning
                                          turn the dial via:
                                          - DecisionEngine choice
                                          - constraints (requires, immediately_after,
                                            mutex, at_most_once)
                                          - skeleton (optional happy path)
                                          - confidence cutoffs on rules
```

**ontorag-flow covers the spectrum by *changing the DecisionEngine and
tightening constraints*, not by rewriting the runtime.** Same case
manager, same audit log, same lifecycle — what differs is *how much
the next action is predetermined*.

- **Most BPM-like end** — `engine: rule`, all rules `confidence: 1.0`,
  `constraints.immediately_after` chains every action, `skeleton:` lists
  the happy path explicitly, deviations raise `ConstraintViolationError`.
  Looks like a state-machine that happens to log everything as PROV-O.
- **Default** — ACM-leaning: engine *recommends*, operator clicks
  `Execute top proposal` (or `auto_execute_top_proposal: true` for
  scripts), constraints prune the illegal moves, skeleton is *advisory*.
- **Most ACM-like end** — `engine: llm` / `engine: causal`, no `skeleton`,
  no `immediately_after`, just `allowed_actions` + `goal`. The engine
  reasons over the case state and picks an action from the menu;
  operator approves.

Same code path; same operator UI. The dial is in the *process YAML*.

### Why ACM-leaning by default — three architectural insights

1. **LLM is the decision-maker, not the orchestrator.** Once a credible
   LLM can read a case state + an action catalog and propose the right
   next action with rationale, *the case for a hand-drawn BPMN graph
   evaporates* — that graph was a stand-in for the missing decision-maker.
   ACM lets the LLM be the decision-maker without faking it through a
   pre-baked sequence.

2. **Ontology is the guard-rail, not the spec.** TBox classes + named
   relations + DL constraints already say what's *coherent* in the
   domain. Re-encoding that into BPMN gateways is double bookkeeping;
   re-encoding it into CMMN sentries is a thinner version of the same
   problem. ontorag-flow lets the ontology *be the guard-rail* — actions
   are anchored in classes, the engine's proposals are filtered through
   `allowed_actions`, and ontorag itself enforces ABox consistency
   when actions write back via `AssertTriple`.

3. **Goal-driven matches how an LLM thinks.** "Diagnosed = true" is a
   target an LLM can hold across context; "advance to node 5 in the
   diagram" is bookkeeping the LLM has to keep separately from the
   reasoning. Goal-driven cases are the *native* representation for an
   LLM-in-the-loop architecture, and they happen to also be how CMMN
   describes a case.

The spectrum stays — when the domain *is* a strict pipeline (compliance
gates, financial close), you tighten the constraints and the engine
behaves BPM-like. The default isn't "ACM forever"; it's "*start
adaptive, prove the rigid parts later*", which is the inverse of how
classic BPM projects start ("draw the diagram first, discover the
exceptions in production").

### Adjacent tools — what we are and aren't

- **Camunda / Activiti / Flowable**: BPMN engines. No ontology, no
  LLM-native interface, no probabilistic decisioning. Heavy XML
  schemas, designer-tool-centric. We compose with these when a domain
  *is* sequence-driven — wrap them as an external `EXTERNAL_API`
  action, don't reimplement them.
- **Temporal / Cadence**: durable execution. Powerful for distributed
  workflows but no ontology, no decision intelligence, code-only DSL.
- **LangGraph / CrewAI / AutoGen**: LLM agent orchestration. No formal
  action model, no ontology, no audit/provenance discipline.
- **Palantir AIP Workshop**: proprietary, full Kinetic story but
  closed.
- **ontorag-flow**: ontology-grounded action model + pluggable decision
  engines + MCP-native + composes with ontorag for reasoning + saga
  compensation + write-ahead PROV-O audit. ACM-leaning by default,
  spectrum-spanning by engine choice.

## Why a separate repo (not inside ontorag)

ontorag's `.claude/CLAUDE.md` is explicit: *"Don't add BPM, notifications, or multi-tenant — separate repo."* This repo *is* that separate repo. The separation buys:

1. **Responsibility clarity** — ontorag = "what is and what we believe", ontorag-flow = "what we do about it"
2. **Each repo answers one question cleanly** in its README
3. **Smaller blast radius** — each can evolve at its own cadence
4. **Architectural maturity signal** — composition over monorepo conflation
5. **MCP is the contract** — already designed, no new interface required

The two repos together (plus a future `ontorag-aip-demo` umbrella) tell the *"open-source Palantir 3-layer"* portfolio story.

## Core concepts

### Action

A **first-class object** with:
- `input_schema` (pydantic) — what parameters it takes
- `side_effects` (declared upfront) — what it changes (ABox writes? external API? human notification?)
- `validate(params, case_state) -> bool` — pre-execution check
- `execute(params, case_state) -> ActionResult` — actual side effect
- `compensate(result) -> None` — rollback hook (saga-pattern)
- `audit_record(result) -> ProvOActivity` — provenance trace

Examples (domain-agnostic): `AssertTriple`, `CallExternalAPI`, `NotifyHuman`, `UpdateCaseProperty`, `RevokeAccess`, `ScheduleFollowup`.

Domain examples (medical reference scenario): `OrderLabTest`, `RecordSymptom`, `PrescribeMedication`, `RequestSpecialistConsult`.

### Case

A long-running unit of work with:
- `case_uri` — URI in ontorag's ABox
- `process_uri` — which process definition governs it
- `state` — current properties (key-value or RDF triples)
- `history` — sequence of executed actions with timestamps
- `goal` — target outcome predicate (e.g., `:diagnosed = true`)
- `status` — `open | suspended | closed | failed`

Cases are *not* sequential scripts. They're contexts in which the next action is *decided* at runtime by a `DecisionEngine`.

### Process Definition (CMMN-inspired, spectrum-spanning)

Not BPMN — but the YAML can describe anything from *strict sequence* to
*free-form ACM* by which fields are populated. We define:

- **Allowed action set** for this case type
- **Preconditions** per action (when is it permissible?)
- **Goal conditions** (when is the case complete?)
- **Constraints** — which combinations are forbidden / required /
  ordered: `mutex`, `requires`, `immediately_after`, `at_most_once`
- **`skeleton: [action_uri, ...]`** *(optional)* — a declared "happy
  path" sequence. **Advisory by default**: the engine still proposes
  freely, the operator still picks; but deviations are *flagged* in the
  PROV-O activity (`deviated_from_skeleton: true`,
  `skeleton_expected: <uri>`) so an auditor can see *where the case
  left the rails*. To make the skeleton *strict*, add
  `constraints.immediately_after` edges that mirror its sequence — same
  data, different teeth. Skeleton without those edges is "this is what
  we expect when nothing goes weird", *not* "this is what must happen".
- **Decision engine** to drive next-action selection

Stored as YAML (v0.1) or RDF using a process vocabulary (later).

### Decision Engine

```python
class DecisionEngine(Protocol):
    """Given current case state, propose next action(s)."""
    async def propose_next(
        self,
        case: Case,
        process: ProcessDefinition,
    ) -> list[ActionProposal]: ...
```

Pluggable implementations:
- **RuleEngine** — decision-table style, DMN-inspired (v0.3)
- **BayesianMpeEngine** — calls ontorag's `compute_posterior` + `mpe`, picks action maximizing P(goal | action). Requires ontorag v0.7. (v0.4)
- **LlmAgentEngine** — LLM with ontorag's MCP tools as its tool surface, chooses action by reasoning. (v0.5)
- **CausalSimulationEngine** — before recommending, calls ontorag's `do_query` to simulate intervention. "Pre-flight check" pattern. Requires ontorag v0.8. (v0.8)
- **HumanReviewEngine** — queues for human approval; always available as fallback.

Multiple engines can be stacked (e.g., LLM proposes, rule engine validates against constraints).

### Provenance / Audit Log

Every action records a **PROV-O Activity**:
- `prov:wasAssociatedWith` agent (user / engine / system)
- `prov:startedAtTime` / `prov:endedAtTime`
- `prov:used` inputs
- `prov:wasGeneratedBy` outputs
- `prov:wasInformedBy` previous activity (causal chain inside the case)

This is where ontorag's deferred `docs/design/layered-ontology-plan.md` Phase 4 (Provenance) finds its natural home — *in this repo, not ontorag*.

## Architecture

```
                    External callers (CLI / HTTP / other agents)
                              │
                              ▼ MCP / REST
                ┌──────────────────────────────┐
                │   ontorag-flow API           │
                │                              │
                │   /cases  /actions  /audit   │
                │   /mcp                       │
                │                              │
                │   ┌──────────────────────┐   │
                │   │  Case Manager        │   │
                │   │  - state machine     │   │
                │   │  - history           │   │
                │   └──────┬───────────────┘   │
                │          │                   │
                │          ▼                   │
                │   ┌──────────────────────┐   │
                │   │  Decision Engine     │   │
                │   │  (pluggable)         │   │
                │   └──────┬───────────────┘   │
                │          │                   │
                │          ▼                   │
                │   ┌──────────────────────┐   │
                │   │  Action Executor     │   │
                │   │  - validate          │   │
                │   │  - execute           │   │
                │   │  - audit (PROV-O)    │   │
                │   └──────┬───────────────┘   │
                └──────────┼───────────────────┘
                           │
              ┌────────────┼─────────────────┐
              ▼            ▼                 ▼
       ┌──────────┐  ┌──────────┐    ┌───────────┐
       │ ontorag  │  │ External │    │ Case DB   │
       │ (MCP)    │  │ APIs     │    │ (state +  │
       │          │  │ (HTTP)   │    │  audit)   │
       └──────────┘  └──────────┘    └───────────┘
```

**Key flow** (one cycle):
1. `Case Manager` loads current case state
2. `Decision Engine` proposes next action(s) — may call ontorag MCP (`find_entities`, `compute_posterior`, `do_query`)
3. Human / auto-policy selects one proposal
4. `Action Executor` validates against current state + process constraints
5. Execute → side effects (write to case DB, call external, post triples back to ontorag's ABox)
6. PROV-O activity recorded in audit log
7. Case state updated, cycle repeats until goal reached or case closed

## MCP tools

### Exposed by ontorag-flow (others can call)

| operation_id | endpoint | description |
|---|---|---|
| `create_case` | POST /cases | Create new case from process definition |
| `get_case_state` | GET /cases/{uri} | Current state + history |
| `propose_next_action` | POST /cases/{uri}/propose | Run decision engine, return proposals (no execution) |
| `execute_action` | POST /cases/{uri}/execute | Execute a chosen action |
| `find_cases` | POST /cases/find | Filter by status / process / property |
| `get_audit_trail` | GET /cases/{uri}/audit | PROV-O activity log for a case |
| `list_actions` | GET /actions | Registered actions catalog |
| `validate_action` | POST /actions/{uri}/validate | Dry-run validation |

### Consumed from ontorag (ontorag-flow as MCP client)

| ontorag tool | Used by | When |
|---|---|---|
| `find_entities`, `describe_entity` | Case Manager | Hydrate case state from ABox |
| `get_schema`, `get_class_detail` | Process validator | Verify action references valid classes |
| `compute_posterior`, `mpe` | BayesianMpeEngine | Decision making (v0.4) |
| `do_query`, `counterfactual` | CausalSimulationEngine | Pre-flight simulation (v0.8) |
| `type_term`, `extract_triples` | Action `IngestUnstructuredInput` | Parse free-text inputs |
| `search_text`, `find_similar` | Case Manager | Find related precedent cases |

The MCP client is a single shared connection — ontorag-flow doesn't reimplement any reasoning, only orchestrates.

## CLI design

```bash
# Project init
ontorag-flow init                                # create config + sample process

# Process definition (YAML for v0.1, RDF later)
ontorag-flow process load ./medical_triage.yaml
ontorag-flow process list
ontorag-flow process show <process_uri>

# Action registry
ontorag-flow action register ./actions/lab_test.py
ontorag-flow action list

# Case lifecycle
ontorag-flow case create <process_uri> [--initial-state K=V ...]
ontorag-flow case status <case_uri>
ontorag-flow case propose-next <case_uri>        # show recommendations, no execution
ontorag-flow case execute <case_uri> <action_uri> --params ...
ontorag-flow case run <case_uri>                 # auto-loop until goal / suspension

# Audit
ontorag-flow audit show <case_uri>
ontorag-flow audit export <case_uri> --format prov

# Server
ontorag-flow serve [--host 0.0.0.0] [--port 8100]

# Status
ontorag-flow status                              # ontorag MCP connection + DB + counts
```

## Tech stack

- **Language**: Python 3.12 (same as ontorag)
- **Package manager**: uv (preferred)
- **Web framework**: FastAPI
- **MCP**: `fastapi-mcp` (expose) + MCP Python client (consume ontorag)
- **Schemas**: Pydantic v2 (action input/output, case state, process definition)
- **Persistence**:
  - Dev: SQLite (case state + audit log)
  - Prod: PostgreSQL (same schema via SQLAlchemy 2.0 async)
- **Process model**: YAML (v0.1) → optional RDF process vocabulary (v0.5+)
- **External actions**: httpx for HTTP, simple plugin interface for custom
- **CLI**: Typer + Rich
- **LLM SDKs** (for `LlmAgentEngine`): anthropic, openai, ollama (consistent with ontorag)
- **Deployment**: Docker + docker-compose (composable with ontorag's compose)
- **Tests**: pytest, fixtures for fake ontorag MCP server

## Repo layout

```
ontorag-flow/
├── .claude/CLAUDE.md          # this file
├── README.md
├── pyproject.toml
├── docker-compose.yml         # ontorag-flow + ontorag composition for local dev
├── .env.example
├── docker/
│   └── api/Dockerfile
├── src/ontorag_flow/
│   ├── __init__.py
│   ├── cli.py                 # Typer entry point
│   ├── api/
│   │   ├── main.py            # FastAPI + fastapi-mcp mount
│   │   └── routes/
│   │       ├── health.py
│   │       ├── cases.py
│   │       ├── actions.py
│   │       ├── audit.py
│   │       └── processes.py
│   ├── core/
│   │   ├── action.py          # Action Protocol + ActionResult + ActionProposal
│   │   ├── case.py            # Case model + state machine
│   │   ├── process.py         # ProcessDefinition + YAML loader
│   │   ├── executor.py        # Action validation + execution + side-effect handling
│   │   ├── audit.py           # PROV-O activity recording
│   │   └── compensation.py    # Saga-pattern rollback (v0.7+)
│   ├── engines/               # DecisionEngine implementations
│   │   ├── base.py            # DecisionEngine Protocol + ActionProposal types
│   │   ├── rule.py            # v0.3 — decision-table rule engine
│   │   ├── bayesian.py        # v0.4 — calls ontorag MPE (requires ontorag v0.7)
│   │   ├── llm_agent.py       # v0.5 — LLM with ontorag MCP tools
│   │   ├── causal.py          # v0.8 — pre-flight do_query (requires ontorag v0.8)
│   │   └── human.py           # human-in-the-loop fallback
│   ├── ontorag_client/        # MCP client wrapper for ontorag
│   │   ├── client.py          # connection management
│   │   └── tools.py           # typed wrappers for ontorag MCP tools
│   ├── stores/
│   │   ├── base.py            # CaseStore + AuditStore Protocols
│   │   ├── sqlite.py          # v0.1 default
│   │   └── postgres.py        # v0.5+
│   └── actions/               # built-in action library (domain-agnostic)
│       ├── triples.py         # AssertTriple, RetractTriple (writes back to ontorag)
│       ├── http.py            # CallExternalAPI
│       ├── case_state.py      # UpdateCaseProperty, SetGoal
│       └── human.py           # NotifyHuman, RequestApproval
├── examples/
│   ├── medical_triage/        # reference domain (also ties to ontorag v0.8 over-claim story)
│   │   ├── process.yaml
│   │   ├── actions/
│   │   └── README.md
│   └── supply_chain_rca/
└── tests/
```

## Coding conventions

Mirror ontorag's conventions exactly:
- Defensive programming, DRY, guard clauses, explicit type hints
- `from __future__ import annotations` on every module
- Google-style docstrings on all public functions
- Async for all I/O (MCP calls, HTTP, DB, FastAPI routes)
- No `print` — use `logging`
- Keep modules under 300 lines; split when growing
- One test file per module, fixture-driven

## Design principles

- **Ontology-grounded actions.** Every action's domain and range are anchored in ontorag's TBox classes. No "free-floating" actions.
- **MCP is the contract.** Both consume (call ontorag) and expose (be called by external agents) via MCP. No REST-only or RPC interfaces.
- **Pluggable decision engines.** No hard-coded "next" logic. Decision engines are first-class swappable components.
- **Adaptive over rigid — but on a *spectrum*.** Cases are *contexts*,
  not *scripts*. The default leans ACM (engine recommends, operator
  approves, no pre-baked sequence) because LLM-in-the-loop and
  goal-driven cases want it that way. Strict-sequence behaviour stays
  available by *tightening* `constraints` and `skeleton`; the runtime
  doesn't change, the data does.
- **Provenance over replayability.** BPM wins on "replay the BPMN to
  see what should have happened". ACM matches that and goes further by
  recording *why*, not just *what*: every action writes a PROV-O
  `Activity` with agent / inputs / outputs / `wasInformedBy` chain,
  and every decision engine that opts into `explain()` records the
  reasoning trace (which rule fired, posterior breakdown, exact LLM
  prompt + raw reply, etc.). Adaptive *with* full forensic recall is
  the deal — there is no opt-out path that skips audit, even on
  failures (write-ahead audit via P7 means a pending row exists
  *before* an externally-visible side effect runs). This is the
  *response to BPM's strongest argument*, baked into the design.
- **Composable with ontorag.** ontorag is the brain (reasoning), ontorag-flow is the hands (execution). Neither owns both responsibilities.
- **Training-free** (through v0.9). Same posture as ontorag — no ML model training infrastructure. v1.0+ may revisit.
- **Explicit side effects.** Every action declares its side effects upfront in its schema. No hidden state mutation.
- **Saga over 2PC.** Cross-system consistency via compensating actions, not distributed transactions.
- **Defense in depth — assume case state is hostile.** ACM/LLM
  architectures pay a permanent prompt-injection cost; ontorag-flow
  ships seven hardening surfaces *by default*, each behind a YAML
  field or env var so opt-in is free:
  S1 anti-injection system prompt + rejected-proposals audit;
  S2 `process.max_llm_confidence` cap;
  S3 `process.execute_policy` + `Action.auto_execute_disabled`
  (ABox write-back / human handoff actions can never be auto-run);
  S4 `ONTORAG_MCP_HTTPS_ONLY` + `ONTORAG_EXPECTED_VERSION` for the
  cross-repo trust boundary;
  S5 `CascadeEngine.health_check` (compromised proposer falls through);
  S6 `process.audit_redact` (fnmatch globs mask values before
  persistence + UI display);
  S7 `ONTORAG_FLOW_PLUGIN_ALLOWLIST` (entry-point name allowlist) +
  Z5 reserved-namespace enforcement (plugins can't register URIs under
  `urn:ontorag-flow:`, blocking accidental built-in override).
  See `docs/security.md` for the threat model + what's *intentionally*
  not defended (auth, RBAC, multi-tenant — all anti-patterns).

## Milestone plan

### v0.1 — Action execution engine MVP

| Step | Deliverable |
|---|---|
| 1 | `core/action.py` — Action Protocol, ActionResult, side-effect declaration |
| 2 | `core/executor.py` — validation + execution + basic audit (in-memory) |
| 3 | `ontorag_client/client.py` — MCP client wrapper (read-only at this stage) |
| 4 | `actions/case_state.py` — `UpdateCaseProperty`, `SetGoal` (no external side effects) |
| 5 | CLI: `init`, `action register`, `action run` (single action, no case yet) |
| 6 | FastAPI skeleton + `/health` + `/actions` |

**Quality bar**: Can register an action, validate it, execute it, see audit record. ontorag MCP connection verified via `find_entities` smoke test.

### v0.2 — Cases and process definitions

| Step | Deliverable |
|---|---|
| 1 | `core/case.py` — Case model + state machine (open/suspended/closed/failed) |
| 2 | `core/process.py` — YAML process loader, allowed-action set, goal conditions |
| 3 | `stores/sqlite.py` — case + audit persistence |
| 4 | `api/routes/cases.py` + `actions.py` — `create_case`, `execute_action`, `get_case_state` (MCP-exposed) |
| 5 | CLI: `case create/run/status`, `process load/list` |

**Quality bar**: Can define a process in YAML, create a case, execute actions against it manually, see state evolve and audit accumulate.

### v0.3 — RuleEngine + decision-table semantics

| Step | Deliverable |
|---|---|
| 1 | `engines/base.py` — `DecisionEngine` Protocol + `ActionProposal` types |
| 2 | `engines/rule.py` — decision-table style (DMN-inspired, JSON/YAML rules) |
| 3 | `api/routes/cases.py` — `propose_next_action` MCP tool |
| 4 | CLI: `case propose-next` |
| 5 | Example: simple triage process with rule-driven decisions |

**Quality bar**: Decision engine recommends next action based on current case state via declared rules. Multiple proposals possible, ranked.

### v0.4 — BayesianMpeEngine (requires ontorag v0.7)

| Step | Deliverable |
|---|---|
| 1 | `engines/bayesian.py` — calls ontorag's `compute_posterior` + `mpe` |
| 2 | Action utility model: P(goal achieved \| action) estimated via BN |
| 3 | Integration test: synthetic case → BN MPE picks correct action |
| 4 | Documentation: how a domain user wires their BN (in ontorag) to ontorag-flow actions |

**Quality bar**: A Bayesian-driven decision engine works end-to-end against a live ontorag v0.7 instance.

### v0.5 — LlmAgentEngine + Postgres + RDF process model

| Step | Deliverable |
|---|---|
| 1 | `engines/llm_agent.py` — LLM with ontorag MCP tools, chooses action by reasoning |
| 2 | Provider parity: anthropic/openai/ollama (consistent with ontorag) |
| 3 | `stores/postgres.py` — production persistence backend |
| 4 | RDF process vocabulary (optional, alongside YAML) — process model as ABox |

**Quality bar**: LLM picks actions sensibly on the reference domain; can be benchmarked against rule + Bayesian engines.

### v0.6 — Audit log expansion + PROV-O export

| Step | Deliverable |
|---|---|
| 1 | Full PROV-O coverage: Agent, Activity, Entity, Used, WasGeneratedBy, WasInformedBy |
| 2 | DCAT dataset metadata for action inputs/outputs |
| 3 | MCP tool: `get_audit_trail` |
| 4 | CLI: `audit export --format prov/jsonld/ttl` |
| 5 | Optional: write audit back to ontorag's `urn:ontorag:provenance` named graph |

**Quality bar**: Audit trail satisfies "who changed what when why" forensic queries.

### v0.7 — Adaptive Case Management (compensation + suspend/resume)

| Step | Deliverable |
|---|---|
| 1 | Saga-pattern compensation: action rollback hooks + composite undo |
| 2 | Case suspend / resume / fork |
| 3 | Constraint enforcement: mutual exclusions, prerequisite chains |
| 4 | Human-in-the-loop handoff (engine yields, awaits human input) |

**Quality bar**: Case can recover gracefully from failed actions; humans can intervene mid-case.

### v0.8 — CausalSimulationEngine (requires ontorag v0.8)

| Step | Deliverable |
|---|---|
| 1 | `engines/causal.py` — pre-flight `do_query` before recommending action |
| 2 | "What if we had taken action X instead?" counterfactual replay |
| 3 | Decision engine arbitration: causal sim acts as final validator over BN/LLM proposals |

**Quality bar**: Pearl Rung 2 fully wired — recommendations come with simulated interventional expected utility, not just observational correlation.

### v0.9 — Web UI (optional)

| Step | Deliverable |
|---|---|
| 1 | Case dashboard (open cases, recent activity) |
| 2 | Action library browser |
| 3 | Decision engine inspector (why was this action recommended?) |
| 4 | Audit trail visualizer |

### v1.0 — Reference demo + ontorag-aip-demo integration

| Step | Deliverable |
|---|---|
| 1 | Polished medical triage end-to-end example with synthetic data |
| 2 | Cross-repo wiring with `ontorag-aip-demo` (the umbrella repo) |
| 3 | Blog post: "Open-source Palantir 3-layer with ontorag + ontorag-flow" |
| 4 | README: "this is the OSS Kinetic layer over formal ontology" positioning |

## What NOT to do (anti-patterns)

- **Don't store domain ontology data.** TBox + ABox live in ontorag. ontorag-flow only stores process definitions, case state, and audit log. Domain queries go through MCP.
- **Don't implement OWL reasoning, Bayesian, or causal inference.** Call ontorag's MCP tools.
- **Don't be BPMN 2.0 compliant — but *do* let the YAML reach the
  rigid end of the spectrum.** Camunda exists; we're not rebuilding
  its modeller, XML format, token-based execution, or BPMN-XML
  interchange. ACM-leaning is the default. *However*, the same YAML
  can describe a strict sequence by populating `constraints.requires`
  / `constraints.immediately_after` / `skeleton` and choosing a
  deterministic engine (`engine: rule` with `confidence: 1.0`
  everywhere). That's *intentional* and matches the "Positioning"
  spectrum section — it's the dial, not an anti-pattern.
  *Still out of scope*: BPMN visual editor, BPMN XML import/export,
  parallel multi-instance, swimlanes, gateways as runtime authority.
  These conflict with `DecisionEngine` as the runtime authority.
  Borrowable CMMN-adjacent concepts already in: timer events,
  subprocess, ordering constraints, `skeleton`.
- **Don't pull in LangChain, LlamaIndex, LangGraph, or LangServe.** Direct MCP and SDK calls only — consistent with ontorag's posture.
- **Don't hard-code decision logic in Python.** DecisionEngine is pluggable; new strategies arrive as new engine implementations.
- **Don't allow actions with undeclared side effects.** Every action declares what it touches upfront. Hidden mutation is a reviewer-blocker.
- **Don't add notifications, multi-tenant, or email infrastructure as core.** These are domain-specific actions, not framework concerns. Provide hooks, not built-ins.
- **Don't add ML model training infrastructure.** Stay training-free through v0.9, matching ontorag's posture.
- **Don't auto-execute proposals without an explicit policy.** Recommendation ≠ execution. The default policy is "propose only"; auto-run requires opt-in per process.
- **Don't conflate "Dynamic" senses.** In ontorag-flow's docs, "Dynamic" means *runtime orchestration intelligence*. ontorag's `urn:ontorag:state` named graph (the renamed-from-Dynamic layer of `layered-ontology-plan.md`) is something else — time-series ABox. Use the precise terms.
- **Don't reimplement provenance.** PROV-O + DCAT are the standards. Use them.

## Open questions (decide when reached)

- **Process model serialization format** — **DECIDED: both**. YAML is the day-1 default for fast iteration; RDF (Turtle by default, JSON-LD also) is offered side-by-side via `core/process_rdf.py` for users who want the process model to live in ontorag's ABox. CLI `ontorag-flow process load <path>` dispatches on suffix (`.ttl`/`.rdf`/`.n3`/`.jsonld`/`.nt` → RDF; anything else → YAML). Every `ProcessDefinition` field round-trips through Turtle and JSON-LD, including `engine` / `causal` / `constraints` / `timer_events` added in v0.7–v0.9. Vocabulary is `urn:ontorag-flow:process#`; structured dicts/lists carried as JSON-string literals (`of:goalJson`, `of:rulesJson`, etc.) until a fully modelled rule vocabulary lands.
- **Case state representation**: tabular key-value (relational-friendly) vs RDF triples (ontology-friendly) vs hybrid (state as key-value with optional triple projection)? Hybrid likely.
- **Decision engine arbitration** — **PARTIAL**: a two-engine stack is now declarable directly in the process model (`engine: stacked` with `arbitration: {proposer: rule|bayesian|llm|human, validator: causal}`); the validator rescores the proposer's proposals via `score_intervention` and reorders best-first. Only causal can be the validator (it's the only engine that exposes `score_intervention` today). Multi-engine policies beyond two-stage (voting, priority cascades, LLM tie-breaker) remain open — they should arrive as new `EngineResolver` cases, not as new Protocol methods, to keep the decoupling.
- **Action atomicity**: single-action transactions only (simple), or multi-action sagas (powerful)? Sagas in v0.7.
- **External action registration** — **DECIDED**: Python entry-points group `ontorag_flow.actions` is the *primary* path. Any installed package can declare `[project.entry-points."ontorag_flow.actions"]` mapping a name to a `BaseAction` subclass; `default_registry()` discovers and instantiates them no-arg. A misbehaving plugin (import/instantiation failure) is logged and skipped — one bad plugin must not abort boot. **URI namespace `urn:ontorag-flow:` is reserved for built-ins**; plugins using it are rejected at load (Z5 — protects built-in semantics from override via a transitive dependency, intentional or otherwise). Plugins must use their own namespace (`urn:my-domain:action:Xxx`); collisions *within* plugin namespaces are last-write wins (plugin authors' coordination problem, not ours). Webhooks remain available for *external systems calling in* but are not the registration path. Actions that need injected clients (the way AssertTriple needs an OntoragClient) still ship a separate registration helper (see `with_triple_actions`) — entry-point loading is for no-arg actions only.
- **Write-back to ontorag** — **DECIDED**: the client-side wrapper and the `AssertTriple` / `RetractTriple` actions both target `assert_triple` / `retract_triple` MCP tools, not `load_rdf`. Single triple per call, no RDF serialisation, typed at the tool boundary, with the saga `compensate` hook wired to the symmetric pair. Actions are registered *only when* an `OntoragClient` is live (composition root in `api/main.py` calls `with_triple_actions(...)` after a successful `maybe_connect_ontorag`). The ontorag side still needs to expose these tools — until v0.7.x, executing one raises `OntoragClientError("ontorag tool 'assert_triple' returned an error.")` and the executor's write-ahead PROV-O row stays at `failed`. No silent skip.
- **Cross-repo testing**: how do we CI-test ontorag-flow against ontorag without coupling repos? Fake MCP server fixture in tests/; live integration test in a separate suite.
- **Versioning ontorag compatibility**: pin to specific ontorag MCP tool versions? Use a compatibility matrix in README.

## How to work with Claude Code on this repo

When starting a session, Claude Code should:
1. Read this CLAUDE.md
2. Read ontorag's `.claude/CLAUDE.md` (sister repo, both repos are part of the same architectural story)
3. Check current state with `git status` and `git log --oneline -10`
4. Confirm which milestone is the current focus
5. Verify ontorag MCP connection if working on engines or client code

When proposing changes:
- Honor the action / case / engine / store separation
- Decision logic goes in engines/, never in routes or executor
- All ontorag access through `ontorag_client/`, not direct SPARQL or Cypher
- Add or update tests in the same change
- Keep changes scoped to one concern per commit

When unsure about scope:
- Default smaller. v0.1 is intentionally minimal.
- If something feels like "ontorag should handle this" — it probably should. Push it there.

## Compatibility matrix

| ontorag-flow version | required ontorag version | new capability |
|---|---|---|
| v0.1 – v0.3 | v0.6.1+ | basic ontology lookup |
| v0.4 | v0.7 (Bayesian) | BayesianMpeEngine |
| v0.5 | v0.7 | LlmAgentEngine (Anthropic/OpenAI/Ollama) |
| v0.6 | v0.7 | PROV-O writeback to `urn:ontorag:provenance` |
| v0.8 | v0.8 (Causal) | CausalSimulationEngine, do-calculus pre-flight |
| v1.0 | v0.9+ | demo on all three backends (Fuseki/Neo4j/FalkorDB) |

## Known risks (decisions)

Carried over from a premortem after the v0.1–v0.9 build. P2/P3/P6 were
addressed directly; P5 and P7 were parked for a design decision and have
since been **implemented** — recorded below for the next reader.

### P5 — Case history bloat for long-running cases — **DECIDED: Mitigation A**

> A case that runs for weeks accumulates 10⁴+ events. The original design
> serialised `Case.history` into the single `cases.data` column, so each
> `update_case` rewrote the whole row — quadratic write cost over the
> lifetime of the case.

**Implementation (non-breaking)**: the `activities` table is now the
authority. `Case.history` stays on the in-memory model so callers
(compensation, UI, demos, API responses) read it naturally, but stores
exclude it when persisting via `Case.persistable_json()`.
`CaseManager.get_case` / `find_cases` rehydrate history from
`audit_store.list_by_case(case_uri)` on load — and old rows whose
`cases.data` JSON still has history get refreshed from audit on the next
load, then re-saved without it. No migration needed.

Side effect (intended): the history now shows *every* recorded activity,
including compensation markers, instead of being trimmed by
`CaseManager.compensate`. Operators wanted the full trail anyway.

### P7 — Audit recording failure can orphan external side effects — **DECIDED: write-ahead, side-effect-aware**

> The executor used to run the action and *then* record the activity. An
> audit failure between the external effect and the record would leave a
> permanent side effect with no provenance.

**Implementation**: `ProvOActivity.status: Literal["pending","completed","failed"]`
with default `"completed"` (so existing rows deserialize as completed —
matches their meaning). The executor records a `"pending"` row *before*
calling `action.execute` only when the action declares an
**externally-visible** side effect (`EXTERNAL_API`, `ABOX_WRITE`, or
`HUMAN`). On completion it upserts the same `activity_uri` to
`"completed"` or `"failed"`. `CASE_STATE`-only actions keep the single
write path — for them the "external effect" is just our own state, and
the extra write isn't worth the cost.

A pending activity that never reaches a final state is left for an
operator (or a future reaper job) to reconcile — explicitly visible
rather than silently lost.

## License

MIT (same as ontorag).
