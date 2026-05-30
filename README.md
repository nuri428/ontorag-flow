# ontorag-flow

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

## 60-second quickstart

```bash
git clone <this-repo>
cd ontorag-flow
uv sync --extra dev

# Reference demo (a synthetic patient case that auto-closes)
uv run python examples/medical_triage/run_demo.py

# HTTP API + read-only Web UI
uv run ontorag-flow serve
#   →  http://localhost:8100/ui/      (cases, actions, audit)
#   →  http://localhost:8100/docs     (OpenAPI)
#   →  http://localhost:8100/mcp      (MCP transport)

# Or drive everything from the CLI
uv run ontorag-flow process load examples/medical_triage/process.yaml
uv run ontorag-flow case create urn:ontorag-flow:process:medical-triage \
    -s severity=8 -s age=42
uv run ontorag-flow case propose-next <case_uri>
```

The demo prints the rule engine's reasoning step-by-step, watches the case
auto-close on goal satisfaction, and exports a PROV-O Turtle audit trail.

---

## What you get

| Capability | Where |
|---|---|
| Action protocol (validate / execute / compensate / audit) with declared side effects | `core/action.py` |
| Immutable `Case` + state machine (open/suspended/closed/failed) | `core/case.py` |
| CMMN-inspired `ProcessDefinition` (YAML or Turtle) | `core/process.py`, `core/process_rdf.py` |
| `CaseManager` orchestrating execute → state apply → audit, with saga compensation, suspend/resume/fork, mutex/requires constraints, human handoff | `core/case_manager.py` |
| **Five pluggable decision engines** — see table below | `engines/` |
| Per-process engine selection via `EngineResolver` | `engines/selection.py` |
| Persistence: SQLite (dev) and Postgres (prod), same Protocols | `stores/sqlite.py`, `stores/postgres.py` |
| Read-only Web UI (cases, actions, decision inspector, audit) | `ui/` |
| FastAPI REST + `fastapi-mcp` so every operation is also an MCP tool | `api/` |
| PROV-O / DCAT audit export to JSON-LD or Turtle | `core/provenance.py` |
| Optimistic locking on case updates | `stores/*.py` |

## Decision engines

| Engine | Picks an action by… | Backing client | Process config field |
|---|---|---|---|
| `RuleEngine` | declarative decision table (operators: `eq/ne/gt/gte/lt/lte/in/exists`) | none | `rules:` |
| `BayesianMpeEngine` | `P(goal \| evidence ∪ candidate.evidence)` from ontorag | ontorag MCP (v0.7) | `bayesian:` |
| `CausalSimulationEngine` | `P(goal \| do(intervention))` — Pearl Rung 2 | ontorag MCP (v0.8) | `causal:` |
| `LlmAgentEngine` | LLM reasoning over case state + action catalog (Anthropic / OpenAI / Ollama) | LLM SDK | `engine: llm` |
| `HumanReviewEngine` | always defer to a human; the resulting `RequestHumanReview` action auto-suspends the case | none | `engine: human` |
| `StackedEngine` | composes a proposer (LLM / Bayesian) with the causal engine as final validator | both | (programmatic) |

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
| `counterfactual_replay` | "what if at this step we'd done Y?" via ontorag causal |
| `get_audit_trail` | PROV-O activities for a case |

ontorag-flow is also an **MCP client** of ontorag itself — see
`ontorag_client/tools.py` for the typed wrappers
(`find_entities`, `compute_posterior`, `do_query`, `counterfactual`, …).

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
├── core/         Action / Case / Process / Executor / Audit / CaseManager
├── engines/      DecisionEngine Protocol + 5 implementations + Resolver + Stacked
├── ontorag_client/  MCP client (single shared connection) + typed tool wrappers
├── stores/       SqliteStore + PostgresStore (same Protocols, swappable)
├── actions/      Built-in action library (UpdateCaseProperty, SetGoal, RequestHumanReview)
├── api/          FastAPI app + routes + fastapi-mcp mount
├── ui/           Read-only Jinja2 inspector (dashboard / actions / case detail / audit)
└── cli.py        Typer CLI
examples/medical_triage/   Reference end-to-end demo
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

## Deep reading

- [`CLAUDE.md`](CLAUDE.md) — project specification, architecture
  rationale, milestone plan, anti-patterns, **Known risks for v1.x**
  (history bloat, write-ahead audit).
- [`examples/medical_triage/`](examples/medical_triage/) — reference
  end-to-end demo + the YAML process this README's quickstart uses.

## License

MIT. Same as ontorag.
