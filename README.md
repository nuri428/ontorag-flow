# ontorag-flow

> **English | [한국어](README.ko.md)**

> **Ontology-grounded adaptive case management — the Kinetic layer over [ontorag](https://github.com/ontorag).**
> If ontorag is *"what is and what we believe"*, ontorag-flow is *"what we do about it"*.

```
┌─────────────────────────────┐   ┌──────────────────────────────┐
│  ontorag                    │   │  ontorag-flow  (this repo)   │
│  ─────────                  │   │  ─────────────               │
│  Semantic  OWL/RDF          │   │  Kinetic   Actions           │
│  Dynamic   Bayesian / Causal│ ← │  Dynamic   Orchestration     │
│  Reasoning over the world   │ → │  Acting on the world         │
└─────────────────────────────┘   └──────────────────────────────┘
              ↑                                 ↑
              └────────────  MCP  ──────────────┘
```

Open-source **Palantir-style 3-layer ontology stack**: ontorag reasons,
ontorag-flow acts, both speak [MCP](https://modelcontextprotocol.io).

---

## Where on the BPM ↔ ACM spectrum

```
   BPM (prescriptive)           ←—— spectrum ——→        ACM (adaptive)
   ─────────────────                                    ────────────
   "do exactly this sequence"                           "these actions are allowed,
                                                         engine decides at runtime"
   Camunda / Activiti                  ontorag-flow            CMMN / Palantir
                                          ↑
                                  default: ACM-leaning
                                  turn the dial via:
                                  - DecisionEngine choice (7 pluggable)
                                  - constraints (requires / immediately_after / mutex / at_most_once)
                                  - skeleton (optional happy path)
                                  - rule confidence cutoffs
```

**Same case manager, same audit, same lifecycle. The dial is in the
process YAML.** Three positions for the same runtime:

- **Most BPM-like** — `engine: rule`, all rules `confidence: 1.0`,
  `constraints.immediately_after` chains every action, `skeleton:`
  lists the happy path. Looks like a state-machine that happens to log
  everything as PROV-O.
- **Default (ACM-leaning)** — engine recommends, operator clicks
  *Execute top proposal*; `constraints` prune illegal moves;
  `skeleton` is advisory (deviations are flagged in audit, not blocked).
- **Most ACM-like** — `engine: llm` / `engine: causal`, no `skeleton`,
  no `immediately_after`. The engine reasons over case state, picks
  from `allowed_actions`, operator approves.

ACM is the *default* not the *only* mode because:

1. **LLM is the decision-maker, not the orchestrator.** A pre-baked
   BPMN graph was a stand-in for the missing decision-maker; once a
   credible LLM is in the loop, the graph evaporates.
2. **Ontology is the guard-rail, not the spec.** TBox classes + DL
   constraints already say what's *coherent*; re-encoding that into
   BPMN gateways is double bookkeeping.
3. **Goal-driven matches how an LLM thinks.** "Diagnosed = true" is a
   target an LLM can hold across context; "advance to node 5" is
   bookkeeping it has to keep separately from the reasoning.

**Provenance is how we match BPM's strongest argument.** BPM wins on
"replay the diagram to see what should have happened". ACM matches
that and goes further: every action writes a PROV-O Activity with
agent / inputs / outputs / `wasInformedBy` chain; every engine that
opts into `explain()` records its reasoning trace (which rule fired,
posterior breakdown, exact LLM prompt + raw reply). Adaptive *with*
full forensic recall, no opt-out. See
[Philosophy →](https://nuri428.github.io/ontorag-flow/philosophy/).

---

## 60-second quickstart

```bash
git clone <this-repo>
cd ontorag-flow
uv sync --extra dev

# Reference demo (a synthetic patient case that auto-closes)
uv run python examples/medical_triage/run_demo.py

# HTTP API + Web UI (read + mutating: suspend/resume/compensate/subcase/tick + counterfactual + inspector)
uv run ontorag-flow serve
#   →  http://localhost:8100/ui/                     (dashboard, Tick all timers)
#   →  http://localhost:8100/ui/cases/<uri>          (lifecycle buttons, subcase tree)
#   →  http://localhost:8100/ui/cases/<uri>/explain  (engine inspector — "why?")
#   →  http://localhost:8100/ui/cases/<uri>/audit    (PROV-O + Counterfactual links)
#   →  http://localhost:8100/docs                    (OpenAPI)
#   →  http://localhost:8100/mcp                     (MCP transport)

# Or drive everything from the CLI
uv run ontorag-flow process load examples/medical_triage/process.yaml
uv run ontorag-flow case create urn:ontorag-flow:process:medical-triage \
    -s severity=8 -s age=42
uv run ontorag-flow case propose-next <case_uri>
```

The demo prints the rule engine's reasoning step-by-step, watches the case
auto-close on goal satisfaction, and exports a PROV-O Turtle audit trail.

---

## Screenshots

Captured against a live ontorag MCP server (`localhost:8011`) with the
two reference processes loaded and one case mid-execution.

### Dashboard — every case, status filter, "Tick all timers"

![Dashboard](docs/images/01-dashboard.png)

### Case detail — lifecycle buttons, state, proposals (with "why?" link), subcases, history

![Case detail](docs/images/05-case-detail.png)

### Decision engine inspector — rules fired vs unmatched, confidence bars, raw trace fold

![Engine inspector](docs/images/06-engine-inspector.png)

### Process diagram — CMMN-style inline SVG: actions, `requires` / `mutex` / `immediately_after` edges, ⏱ timer events

![Process diagram](docs/images/04-process-diagram.png)

### Process inspector — per-process status mix + hottest actions across all cases

![Process detail](docs/images/03-process-detail.png) ![Processes list](docs/images/02-processes.png)

### Audit trail — PROV-O activities with `Counterfactual` link per row

![Audit trail](docs/images/07-audit-trail.png)

---

## What you get

| Capability | Where |
|---|---|
| Action protocol (validate / execute / compensate / audit) with declared side effects | `core/action.py` |
| Immutable `Case` + state machine (open/suspended/closed/failed), parent/subcase linkage | `core/case.py` |
| CMMN-inspired `ProcessDefinition` (YAML or RDF/Turtle/JSON-LD) | `core/process.py`, `core/process_rdf.py` |
| `CaseManager` orchestrating execute → state apply → audit, with saga compensation, suspend/resume/fork, subcase tree, timer events, ordering constraints (mutex / requires / immediately_after / at_most_once), human handoff | `core/case_manager.py` |
| **Six pluggable decision engines** — including a `StackedEngine` declarable from YAML — see table below | `engines/` |
| Per-process engine selection via `EngineResolver` (incl. `engine: stacked` arbitration) | `engines/selection.py` |
| Optional **`engine.explain()`** with per-engine reasoning trace | `engines/base.py` + each engine |
| Persistence: SQLite (dev) and Postgres (prod), same Protocols, optimistic locking | `stores/sqlite.py`, `stores/postgres.py` |
| Web UI — case dashboard with `Tick all timers`, case-detail mutating buttons (Suspend / Resume / Compensate / Execute top proposal / Spawn subcase), engine inspector (`/explain`), counterfactual replay (`/counterfactual`), audit view | `ui/` |
| FastAPI REST + `fastapi-mcp` so every operation is also an MCP tool | `api/` |
| Built-in actions: case-state, human-review, and **ABox write-back** (`AssertTriple` / `RetractTriple`) via ontorag MCP | `actions/` |
| PROV-O / DCAT audit export to JSON-LD or Turtle | `core/provenance.py` |

## Decision engines

| Engine | Picks an action by… | Backing client | Process config field |
|---|---|---|---|
| `RuleEngine` | declarative decision table (operators: `eq/ne/gt/gte/lt/lte/in/exists`) | none | `rules:` |
| `BayesianMpeEngine` | `P(goal \| evidence ∪ candidate.evidence)` from ontorag | ontorag MCP (v0.7) | `bayesian:` |
| `CausalSimulationEngine` | `P(goal \| do(intervention))` — Pearl Rung 2 | ontorag MCP (v0.8) | `causal:` |
| `LlmAgentEngine` | LLM reasoning over case state + action catalog (Anthropic / OpenAI / Ollama) | LLM SDK | `engine: llm` |
| `HumanReviewEngine` | always defer to a human; the resulting `RequestHumanReview` action auto-suspends the case | none | `engine: human` |
| `StackedEngine` | composes a proposer (rule / bayesian / llm / human) with the causal engine as final validator | proposer's client + ontorag MCP (v0.8) | `engine: stacked` + `arbitration: {proposer, validator}` |

Pick explicitly with `engine: <kind>` in the process YAML, or let the
resolver infer (`causal:` present → causal, `bayesian:` → bayesian,
`rules:` → rule, else default).

---

## MCP surface — what cross-repo callers see

ontorag-flow mounts `fastapi-mcp` so every named REST operation is an MCP
tool. Sister repos (notably the umbrella `ontorag-aip-demo`) can drive the
whole stack over MCP without HTTP knowledge:

| Tool (`operation_id`) | What it does |
|---|---|
| `health_check` | service liveness |
| `list_actions` | registered action catalog |
| `load_process` / `list_processes` / `get_process` | process registry |
| `create_case` / `get_case_state` / `find_cases` | case lifecycle reads/creates |
| `execute_action` | run a chosen action against a case |
| `propose_next_action` | ranked decision-engine proposals (no execution) |
| `compensate_case` / `suspend_case` / `resume_case` / `fork_case` | adaptive case management |
| `create_subcase` | spawn a child case under a parent (subprocess linkage) |
| `tick_timers` | fire elapsed timer events across all open cases |
| `counterfactual_replay` | "what if at this step we'd done Y?" via ontorag causal |
| `get_audit_trail` | PROV-O activities for a case |

ontorag-flow is also an **MCP client** of ontorag itself — see
`ontorag_client/tools.py` for the typed wrappers (`find_entities`,
`describe_entity`, `get_schema`, `compute_posterior`, `do_query`,
`counterfactual`, `assert_triple`, `retract_triple`).

---

## Configuration

Copy `.env.example` to `.env` and edit. Key knobs:

| Variable | Default | Meaning |
|---|---|---|
| `ONTORAG_MCP_URL` | `http://localhost:8000/mcp` | sister ontorag server |
| `CONNECT_ONTORAG` | `false` | open ontorag connection at startup (enables Bayesian/Causal engines) |
| `LLM_PROVIDER` | unset | `anthropic` / `openai` / `ollama` — enables `LlmAgentEngine` |
| `LLM_MODEL` | provider default | model override |
| `DATABASE_PATH` | `ontorag_flow.db` | SQLite file (or use Postgres via the `postgres` extra) |
| `AGENT_ID` | `urn:ontorag-flow:agent:system` | `prov:wasAssociatedWith` on every audit activity |

## Optional extras

```bash
uv sync --extra dev                       # tests + ruff + pyright + bandit + testcontainers
uv sync --extra dev --extra llm           # + Anthropic / OpenAI SDKs
uv sync --extra postgres                  # + asyncpg (production)
```

## Docker

A multi-stage `Dockerfile` (Python 3.12-slim, `uv`-built venv, non-root
user, stdlib `/health` healthcheck) ships in the repo. Final image is
~230 MB with the core deps only.

```bash
# build + run with the in-container SQLite store
docker compose up

#   →  http://localhost:8100/ui/      (read-only inspector)
#   →  http://localhost:8100/docs     (OpenAPI)
#   →  http://localhost:8100/health   (liveness)

# Postgres profile instead of SQLite
docker compose --profile postgres up

# add optional extras at build time
docker build --build-arg INSTALL_EXTRAS="postgres llm" -t ontorag-flow:full .
```

Compose with the sister `ontorag` server's compose file so they share a
default network and `ONTORAG_MCP_URL` resolves by service name:

```bash
docker compose -f docker-compose.yml -f ../ontorag/docker-compose.yml up
# then set CONNECT_ONTORAG=true in docker-compose.yml to enable the
# Bayesian/Causal engines.
```

## Layout

```
src/ontorag_flow/
├── core/         Action / Case / Process (+ RDF) / Executor / Audit / CaseManager / Registry
├── engines/      DecisionEngine Protocol + EngineExplanation + 5 base + StackedEngine + Resolver
├── ontorag_client/  MCP client (single shared connection) + typed tool wrappers (incl. assert_triple)
├── stores/       SqliteStore + PostgresStore (same Protocols, swappable, optimistic locking)
├── actions/      Built-in actions — case-state, human, and ABox write-back (Assert/RetractTriple)
├── api/          FastAPI app + routes + fastapi-mcp mount
├── ui/           Jinja2 UI — dashboard (tick), case detail (mutating buttons + subcase tree), explain inspector, counterfactual, audit
└── cli.py        Typer CLI
examples/
├── medical_triage/      Reference end-to-end demo (RuleEngine, auto-closing case)
├── supply_chain_rca/    Second domain demo — RuleEngine + optional LLM variant
└── bayesian_demo/       Bayesian engine over a tiny fake ontorag MCP fixture
docs/operator-guide.md   Bilingual operator guide (EN + KO)
```

---

## Working with `ontorag`

ontorag-flow is the action side; ontorag is the reasoning side. Run the
two together for the full stack:

```bash
# ontorag (sister repo) — exposes MCP at e.g. http://localhost:8000/mcp
ontorag serve

# ontorag-flow — consume ontorag, expose its own MCP
CONNECT_ONTORAG=true ontorag-flow serve
```

With `CONNECT_ONTORAG=true` and ontorag v0.7+/v0.8+ reachable, the
Bayesian and Causal engines become available; without it, only the
local-only engines (rule, llm, human) work.

## Examples & tools

A condensed map of "what you can do with this repo and how". Detailed
behaviour is in `--help` for every CLI command and in the inline
docstrings; this section is the index.

#### Example use cases (runnable today)

| What | Where | What it demonstrates |
|---|---|---|
| Drive a decision-tree case to closure | `examples/medical_triage/run_demo.py` | `RuleEngine`, auto-close on goal, PROV-O Turtle export |
| Open-ended investigation with human handoff | `examples/supply_chain_rca/run_demo.py` | Custom domain actions, `EXTERNAL_API`/`HUMAN` side effects, `requires` constraints, auto-suspend → resume → close |
| Same process, LLM engine (fake or live) | `examples/supply_chain_rca/run_demo_llm.py` | `LlmAgentEngine`, in-code `engine: llm` override, allowed-action filter on hallucinated URIs |
| Compensate (saga rollback) | `ontorag-flow case compensate <case_uri>` | `action.compensate` hooks, state restored from `state_before`, audit retains every event |
| Counterfactual "what if Y instead?" | `ontorag-flow case counterfactual ...` | `CausalSimulationEngine` over ontorag MCP (requires ontorag v0.8) |
| Live PostgreSQL backend | `docker compose --profile postgres up` + `tests/test_postgres_store_integration.py` | `PostgresStore` round-trip via testcontainers |
| Browse cases / actions / audit in a UI | `ontorag-flow serve` → `http://localhost:8100/ui/` | Live dashboard with `Tick all timers`, status filter, case links |
| Drive lifecycle from the browser | `/ui/cases/<uri>` → Suspend / Resume / Execute top proposal / Compensate / Spawn subcase | Form POST + 303 redirect pattern, JS-free; conditional buttons per status |
| Diagnose "why did the engine recommend that?" | `/ui/cases/<uri>/explain` | `engine.explain()` rendered as engine-specific cards (rules-fired table / posterior bars / LLM prompts / proposer-vs-validator) |
| Replay a past activity under a swap | `/ui/cases/<uri>/audit` → "Counterfactual" row link | Read-only "what if Y instead?" form against the causal engine |
| Stack a proposer with a causal validator from YAML | `engine: stacked` + `arbitration: {proposer: rule\|bayesian\|llm\|human, validator: causal}` | Two-engine arbitration declared in the model, no Python wiring |
| Define a process as RDF instead of YAML | `ontorag-flow process load <process.ttl\|process.jsonld>` | `urn:ontorag-flow:process#` vocabulary, full field round-trip incl. engine / causal / constraints / timer_events / arbitration |
| Write back triples to ontorag's ABox | Use `AssertTriple` / `RetractTriple` in `allowed_actions` (live `OntoragClient` required) | `ABOX_WRITE` side effect with saga `compensate` to retract on rollback |
| Iterate on a process YAML without saving | `ontorag-flow process simulate <yaml> -s K=V [--execute-top] [--explain]` | In-memory case + engine call; optionally executes the top proposal and prints the explain trace |
| Ship an action as a Python plugin | declare `[project.entry-points."ontorag_flow.actions"]` in `pyproject.toml` of your package | `default_registry()` discovers it on boot; broken plugins are logged and skipped, not fatal |

#### CLI tools

| Command | Purpose |
|---|---|
| `ontorag-flow init` | Bootstrap `.env` from the example |
| `ontorag-flow status` | Show config + probe ontorag MCP connection |
| `ontorag-flow serve` | Run the FastAPI + MCP server (mounts `/ui`, `/mcp`, REST) |
| `ontorag-flow action list / register / run` | Inspect, plug in, and execute an action ad-hoc |
| `ontorag-flow process load / list` | Load a process from YAML (or Turtle) and inspect |
| `ontorag-flow process simulate <yaml> -s K=V` | Dry-run the engine against an in-memory case — author iterates without polluting the dev DB |
| `ontorag-flow case create / status` | Create a case + show its state, history, status |
| `ontorag-flow case propose-next` | Run the decision engine without executing |
| `ontorag-flow case execute` | Run a chosen action against a case |
| `ontorag-flow case compensate` | Roll back a tail of executed actions (saga) |
| `ontorag-flow case suspend / resume` | Pause / reopen a case |
| `ontorag-flow case fork` | New case copying state + history from a source |
| `ontorag-flow case subcase` | Spawn a child case under a parent (closes project onto parent state) |
| `ontorag-flow case tick` | Fire elapsed timer events across all open cases |
| `ontorag-flow case counterfactual` | "What if at this step we'd done Y?" via the causal engine |
| `ontorag-flow audit show / export` | Inspect or render the PROV-O audit trail (JSON-LD / Turtle) |

#### Decision engines (pick by `engine:` or let the resolver infer)

| Engine | When to pick it | Backing client |
|---|---|---|
| `RuleEngine` | Decision table fits the domain; no external services | none |
| `BayesianMpeEngine` | Need observational `P(goal \| evidence)` | ontorag MCP (v0.7) |
| `CausalSimulationEngine` | Need interventional `P(goal \| do(...))` — Pearl Rung 2 | ontorag MCP (v0.8) |
| `LlmAgentEngine` | Open-ended hypothesis space; free-form reasoning | Anthropic / OpenAI / Ollama |
| `HumanReviewEngine` | Always defer to a human reviewer | none |
| `StackedEngine` | Compose proposer + causal validator — declare in YAML with `engine: stacked` + `arbitration: {proposer: rule\|bayesian\|llm\|human, validator: causal}` | proposer's client + ontorag MCP |

#### Built-in actions

| Action URI | Side effects | What it does |
|---|---|---|
| `urn:ontorag-flow:action:UpdateCaseProperty` | CASE_STATE | Set one property on the case state |
| `urn:ontorag-flow:action:SetGoal` | CASE_STATE | Declare / replace the goal predicate |
| `urn:ontorag-flow:action:RequestHumanReview` | HUMAN + CASE_STATE | Mark the case for human review — auto-suspends |
| `urn:ontorag-flow:action:AssertTriple` | ABOX_WRITE | Write one (s, p, o) triple to ontorag's ABox (only registered when an OntoragClient is live) |
| `urn:ontorag-flow:action:RetractTriple` | ABOX_WRITE | Remove one (s, p, o) triple from ontorag's ABox (saga-compensates each other with AssertTriple) |

---

## Deep reading

- [`README.ko.md`](README.ko.md) — **Korean translation** of this README
  (한국어 번역). Same structure, kept in lockstep on docs updates.
- [`docs/operator-guide.md`](docs/operator-guide.md) — **operator
  guide** for the browser UI (EN + KO). What each lifecycle button does,
  how to read error callouts, common scenarios, counterfactual replay,
  the engine inspector, and what the UI deliberately does *not* do.
- [`docs/operations.md`](docs/operations.md) — **backup / restore /
  disaster recovery** for SQLite and Postgres deployments (EN + KO),
  plus the post-restore smoke flow operators should run before
  reopening the system.
- [`docs/security.md`](docs/security.md) — **threat model + seven
  hardening surfaces** (anti-injection, confidence cap, execute
  policy, transport trust, cascade health, audit redact, plugin
  allowlist), and what is *intentionally* not defended (auth, RBAC —
  reverse-proxy responsibility). EN + KO.
- [`CLAUDE.md`](CLAUDE.md) — project specification, architecture
  rationale, milestone plan, anti-patterns, **Known risks for v1.x**
  (history bloat, write-ahead audit), and the running record of which
  *Open questions* are **DECIDED** vs **PARTIAL**.
- [`examples/medical_triage/`](examples/medical_triage/) — reference
  end-to-end demo + the YAML process this README's quickstart uses.
- [`examples/supply_chain_rca/`](examples/supply_chain_rca/) — second
  domain demo with `EXTERNAL_API` / `HUMAN` side effects, plus an LLM
  variant (`run_demo_llm.py`).
- [`examples/bayesian_demo/`](examples/bayesian_demo/) — Bayesian
  engine running against an in-process fake ontorag MCP fixture.

## License

MIT. Same as ontorag.
