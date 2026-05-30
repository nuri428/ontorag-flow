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

## Examples & tools

A condensed map of "what you can do with this repo and how". Detailed
behaviour is in `--help` for every CLI command and in the inline
docstrings; this section is the index.

### English

#### Example use cases (runnable today)

| What | Where | What it demonstrates |
|---|---|---|
| Drive a decision-tree case to closure | `examples/medical_triage/run_demo.py` | `RuleEngine`, auto-close on goal, PROV-O Turtle export |
| Open-ended investigation with human handoff | `examples/supply_chain_rca/run_demo.py` | Custom domain actions, `EXTERNAL_API`/`HUMAN` side effects, `requires` constraints, auto-suspend → resume → close |
| Same process, LLM engine (fake or live) | `examples/supply_chain_rca/run_demo_llm.py` | `LlmAgentEngine`, in-code `engine: llm` override, allowed-action filter on hallucinated URIs |
| Compensate (saga rollback) | `ontorag-flow case compensate <case_uri>` | `action.compensate` hooks, state restored from `state_before`, audit retains every event |
| Counterfactual "what if Y instead?" | `ontorag-flow case counterfactual ...` | `CausalSimulationEngine` over ontorag MCP (requires ontorag v0.8) |
| Live PostgreSQL backend | `docker compose --profile postgres up` + `tests/test_postgres_store_integration.py` | `PostgresStore` round-trip via testcontainers |
| Browse cases / actions / audit in a UI | `ontorag-flow serve` → `http://localhost:8100/ui/` | Read-only inspector with live engine proposals |

#### CLI tools

| Command | Purpose |
|---|---|
| `ontorag-flow init` | Bootstrap `.env` from the example |
| `ontorag-flow status` | Show config + probe ontorag MCP connection |
| `ontorag-flow serve` | Run the FastAPI + MCP server (mounts `/ui`, `/mcp`, REST) |
| `ontorag-flow action list / register / run` | Inspect, plug in, and execute an action ad-hoc |
| `ontorag-flow process load / list` | Load a process from YAML (or Turtle) and inspect |
| `ontorag-flow case create / status` | Create a case + show its state, history, status |
| `ontorag-flow case propose-next` | Run the decision engine without executing |
| `ontorag-flow case execute` | Run a chosen action against a case |
| `ontorag-flow case compensate` | Roll back a tail of executed actions (saga) |
| `ontorag-flow case suspend / resume` | Pause / reopen a case |
| `ontorag-flow case fork` | New case copying state + history from a source |
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
| `StackedEngine` | Compose proposer + causal validator (causal overrides confidence with do-effect) | both |

#### Built-in actions

| Action URI | Side effects | What it does |
|---|---|---|
| `urn:ontorag-flow:action:UpdateCaseProperty` | CASE_STATE | Set one property on the case state |
| `urn:ontorag-flow:action:SetGoal` | CASE_STATE | Declare / replace the goal predicate |
| `urn:ontorag-flow:action:RequestHumanReview` | HUMAN + CASE_STATE | Mark the case for human review — auto-suspends |

---

### 한국어

#### 실행 가능한 예제 (use case)

| 하고 싶은 것 | 위치 | 보여주는 것 |
|---|---|---|
| 결정 트리로 케이스 자동 종료 | `examples/medical_triage/run_demo.py` | `RuleEngine`, 목표 도달 시 자동 close, PROV-O Turtle 내보내기 |
| 사람 개입이 있는 개방형 조사 | `examples/supply_chain_rca/run_demo.py` | 커스텀 도메인 액션, `EXTERNAL_API`/`HUMAN` 부수효과, `requires` 제약, 자동 suspend → resume → close |
| 같은 프로세스를 LLM 엔진으로 (fake 또는 live) | `examples/supply_chain_rca/run_demo_llm.py` | `LlmAgentEngine`, 코드 안에서 `engine: llm` override, hallucinated URI는 allowed 필터로 차단 |
| 보상(saga 롤백) | `ontorag-flow case compensate <case_uri>` | `action.compensate` 훅, `state_before`로 상태 복원, audit는 모든 이벤트 보존 |
| 반사실 "Y였다면?" 시뮬레이션 | `ontorag-flow case counterfactual ...` | `CausalSimulationEngine` via ontorag MCP (ontorag v0.8 필요) |
| 라이브 PostgreSQL 백엔드 | `docker compose --profile postgres up` + `tests/test_postgres_store_integration.py` | `PostgresStore` round-trip via testcontainers |
| UI에서 케이스/액션/감사 둘러보기 | `ontorag-flow serve` → `http://localhost:8100/ui/` | 라이브 엔진 제안이 보이는 읽기 전용 inspector |

#### CLI 도구

| 명령 | 용도 |
|---|---|
| `ontorag-flow init` | `.env.example`에서 `.env` 부트스트랩 |
| `ontorag-flow status` | 설정 + ontorag MCP 연결 점검 표시 |
| `ontorag-flow serve` | FastAPI + MCP 서버 실행 (`/ui`, `/mcp`, REST 마운트) |
| `ontorag-flow action list / register / run` | 액션 카탈로그 보기, 플러그인 등록, ad-hoc 실행 |
| `ontorag-flow process load / list` | YAML(또는 Turtle) 프로세스 로드 및 조회 |
| `ontorag-flow case create / status` | 케이스 생성 + 상태/히스토리/상태값 표시 |
| `ontorag-flow case propose-next` | 실행하지 않고 결정 엔진 추천만 받기 |
| `ontorag-flow case execute` | 선택한 액션을 케이스에 실행 |
| `ontorag-flow case compensate` | 실행된 액션 꼬리를 saga 방식으로 롤백 |
| `ontorag-flow case suspend / resume` | 케이스 일시 정지 / 재개 |
| `ontorag-flow case fork` | 소스 케이스의 상태+히스토리를 복사한 새 케이스 |
| `ontorag-flow case counterfactual` | "이 단계에서 Y였다면?"을 causal 엔진으로 |
| `ontorag-flow audit show / export` | PROV-O 감사 trail 조회 / 렌더링 (JSON-LD · Turtle) |

#### 결정 엔진 (프로세스의 `engine:`로 선택, 미지정 시 resolver 추론)

| 엔진 | 언제 쓰는가 | 백킹 클라이언트 |
|---|---|---|
| `RuleEngine` | 도메인이 결정 테이블로 표현 가능, 외부 서비스 불필요 | 없음 |
| `BayesianMpeEngine` | 관측적 `P(goal \| evidence)` 필요 | ontorag MCP (v0.7) |
| `CausalSimulationEngine` | 개입적 `P(goal \| do(...))` 필요 — Pearl Rung 2 | ontorag MCP (v0.8) |
| `LlmAgentEngine` | 개방형 가설 공간, 자유로운 추론 | Anthropic / OpenAI / Ollama |
| `HumanReviewEngine` | 항상 사람 검토자에게 위임 | 없음 |
| `StackedEngine` | 제안 엔진 + causal 검증자 합성 (causal이 do-effect로 confidence 덮어쓰기) | 양쪽 모두 |

#### 내장 액션

| 액션 URI | 부수효과 | 동작 |
|---|---|---|
| `urn:ontorag-flow:action:UpdateCaseProperty` | CASE_STATE | 케이스 상태에 속성 하나를 설정 |
| `urn:ontorag-flow:action:SetGoal` | CASE_STATE | 목표 술어를 선언 / 교체 |
| `urn:ontorag-flow:action:RequestHumanReview` | HUMAN + CASE_STATE | 사람 검토 대상으로 표시 — 자동 suspend |

---

## Deep reading

- [`CLAUDE.md`](CLAUDE.md) — project specification, architecture
  rationale, milestone plan, anti-patterns, **Known risks for v1.x**
  (history bloat, write-ahead audit).
- [`examples/medical_triage/`](examples/medical_triage/) — reference
  end-to-end demo + the YAML process this README's quickstart uses.

## License

MIT. Same as ontorag.
