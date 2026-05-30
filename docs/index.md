# ontorag-flow

> **Ontology-grounded adaptive case management — the Kinetic layer over
> [ontorag](https://github.com/ontorag).**
> If ontorag is *"what is and what we believe"*, ontorag-flow is *"what we do
> about it"*.

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

**Where on the BPM ↔ ACM spectrum:** ontorag-flow defaults to
ACM-leaning (engine recommends, operator approves, no pre-baked
sequence) and reaches the BPM-rigid end by *tightening constraints +
skeleton + deterministic engine* in the same process YAML. The runtime
doesn't change; the data does. Provenance is non-optional throughout
so adaptive runs stay forensically replayable. See
[**Philosophy →**](philosophy.md) for the long-form rationale.

---

## 60-second quickstart

```bash
git clone https://github.com/nuri428/ontorag-flow.git
cd ontorag-flow
uv sync --extra dev

# Reference demo (a synthetic patient case that auto-closes)
uv run python examples/medical_triage/run_demo.py

# HTTP API + Web UI
uv run ontorag-flow serve
#   →  http://localhost:8100/ui/                     (dashboard, Tick all timers)
#   →  http://localhost:8100/ui/cases/<uri>          (lifecycle buttons, subcase tree)
#   →  http://localhost:8100/ui/cases/<uri>/explain  (engine inspector — "why?")
#   →  http://localhost:8100/ui/cases/<uri>/audit    (PROV-O + Counterfactual links)
#   →  http://localhost:8100/docs                    (OpenAPI)
#   →  http://localhost:8100/mcp                     (MCP transport)
```

The demo prints the rule engine's reasoning step-by-step, watches the case
auto-close on goal satisfaction, and exports a PROV-O Turtle audit trail.

---

## What you get

| Capability | Where |
|---|---|
| Action protocol with declared side effects | `core/action.py` |
| Immutable `Case` + state machine, parent/subcase linkage | `core/case.py` |
| CMMN-inspired `ProcessDefinition` (YAML or RDF/Turtle/JSON-LD) | `core/process.py`, `core/process_rdf.py` |
| `CaseManager` — execute → state apply → audit, saga compensation, suspend/resume/fork, subcase tree, timer events, ordering constraints, human handoff | `core/case_manager.py` |
| **Six pluggable decision engines** — including `StackedEngine` / `CascadeEngine` declarable from YAML | `engines/` |
| Optional **`engine.explain()`** with per-engine reasoning trace | `engines/base.py` + each engine |
| Persistence: SQLite (dev) and Postgres (prod), same Protocols, optimistic locking | `stores/` |
| Web UI — dashboard, mutating lifecycle buttons, engine inspector, counterfactual replay, audit | `ui/` |
| FastAPI REST + `fastapi-mcp` so every operation is also an MCP tool | `api/` |
| ABox write-back actions (`AssertTriple` / `RetractTriple`) via ontorag MCP | `actions/triples.py` |

---

## Screenshots

Captured against a live ontorag MCP server.

| Page | Preview |
|---|---|
| Dashboard | ![Dashboard](images/01-dashboard.png) |
| Case detail | ![Case detail](images/05-case-detail.png) |
| Engine inspector | ![Engine inspector](images/06-engine-inspector.png) |
| Process diagram | ![Process diagram](images/04-process-diagram.png) |
| Audit trail | ![Audit trail](images/07-audit-trail.png) |

---

## Where to next

- **[Operator guide](operator-guide.md)** — every UI surface annotated:
  what each lifecycle button does, how to read error callouts, the engine
  inspector, counterfactual replay, common scenarios.
- **[Operations (backup / DR)](operations.md)** — SQLite snapshot
  patterns, Postgres `pg_dump`, audit-only backups, the 5-step restore
  smoke flow.
- **[GitHub repository](https://github.com/nuri428/ontorag-flow)** —
  source, issues, releases.
- **[Architecture & milestones](https://github.com/nuri428/ontorag-flow/blob/main/CLAUDE.md)**
  — full project specification, anti-patterns, the running record of
  Open questions and decisions.
