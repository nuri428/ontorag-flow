# How-to: connect to `ontorag`

ontorag-flow is the action side; ontorag is the reasoning side. Run
the two together for the full stack.

## What requires ontorag

| Capability | Needs live ontorag MCP |
|---|---|
| `RuleEngine` / `HumanReviewEngine` / `LlmAgentEngine` | no |
| `BayesianMpeEngine` | yes (ontorag v0.7+) |
| `CausalSimulationEngine` | yes (ontorag v0.8+) |
| `StackedEngine` with `validator: causal` | yes (v0.8+) |
| `AssertTriple` / `RetractTriple` actions | yes (ontorag v0.7.x with `assert_triple` MCP tool) |
| Counterfactual replay (`/ui/cases/<uri>/counterfactual`) | yes (v0.8+) |

When ontorag isn't reachable, the relevant engines / actions raise
`EngineUnavailableError` / `OntoragClientError` with the exact env var
to set; the rest of the stack runs fine.

## Set it up

```bash
# 1. ontorag (sister repo) — exposes MCP at e.g. http://localhost:8000/mcp
ontorag serve

# 2. ontorag-flow — consume ontorag + expose its own MCP
export ONTORAG_MCP_URL=http://localhost:8000/mcp   # default value
export CONNECT_ONTORAG=true                        # default is false
ontorag-flow serve
```

`ontorag-flow status` runs a `find_entities` smoke test and prints
"ontorag MCP: reachable / unreachable" with the underlying error if
any.

## Custom URL / port

```bash
export ONTORAG_MCP_URL=http://my-ontorag:8011/mcp
export CONNECT_ONTORAG=true
ontorag-flow serve
```

## Auto-wired ABox write-back

`api/main.py`'s FastAPI lifespan calls `with_triple_actions(registry,
client)` *only when* `maybe_connect_ontorag` succeeded. So
`AssertTriple` / `RetractTriple` show up in `GET /actions` exactly
when ontorag is live.

Until ontorag exposes `assert_triple` / `retract_triple` MCP tools,
executing one raises `OntoragClientError("ontorag tool 'assert_triple'
returned an error.")` and the write-ahead PROV-O row stays `failed` —
no silent skip.

## docker-compose composition

Compose with ontorag's compose file to share the default network so
`ONTORAG_MCP_URL` resolves by service name:

```bash
docker compose -f docker-compose.yml -f ../ontorag/docker-compose.yml up
```

Then in `docker-compose.yml`:

```yaml
services:
  ontorag-flow:
    environment:
      ONTORAG_MCP_URL: http://ontorag:8000/mcp
      CONNECT_ONTORAG: "true"
```

## ontorag tools we consume

Catalog (typed wrappers in `ontorag_client/tools.py`):

| Tool | Used by |
|---|---|
| `find_entities` | smoke test + `OntoragClient.smoke_test` |
| `describe_entity`, `get_schema` | for plugin actions that need ABox lookups |
| `compute_posterior` | `BayesianMpeEngine` |
| `do_query` | `CausalSimulationEngine`, `StackedEngine.validator` |
| `counterfactual` | `manager.counterfactual` (Pearl Rung 3 replay) |
| `assert_triple`, `retract_triple` | `AssertTriple` / `RetractTriple` actions |

The MCP client is a single shared connection (background-task-owned to
satisfy anyio TaskGroup invariants — see `client.py` module docstring).
