# HTTP & MCP API

`fastapi-mcp` mounts every named REST `operation_id` as an MCP tool, so
the table below is *both* the HTTP surface and the MCP tool catalog.
The full OpenAPI spec is live at `/docs` and `/openapi.json` when the
server is running; MCP transport is at `/mcp`.

## Endpoints

| Method · Path | `operation_id` (= MCP tool) | What |
|---|---|---|
| `GET /health` | `health_check` | Service liveness |
| `GET /actions` | `list_actions` | Registered action catalog |
| `POST /processes` | `load_process` | Persist a process definition |
| `GET /processes` | `list_processes` | List loaded processes |
| `GET /processes/{uri}` | `get_process` | Single process |
| `POST /cases` | `create_case` | Create a case from a process |
| `GET /cases/{uri}` | `get_case_state` | Current state + history |
| `POST /cases/find` | `find_cases` | Filter by status / process |
| `POST /cases/{uri}/execute` | `execute_action` | Run a chosen action |
| `POST /cases/{uri}/propose` | `propose_next_action` | Engine proposals (no execution) |
| `POST /cases/{uri}/compensate` | `compensate_case` | Saga rollback |
| `POST /cases/{uri}/suspend` | `suspend_case` | Pause |
| `POST /cases/{uri}/resume` | `resume_case` | Reopen |
| `POST /cases/{uri}/fork` | `fork_case` | New case copying state + history |
| `POST /cases/{uri}/subcase` | `create_subcase` | Spawn child case |
| `POST /cases/tick` | `tick_timers` | Fire elapsed timer events globally |
| `POST /cases/{uri}/counterfactual` | `counterfactual_replay` | "What if Y at step X?" |
| `GET /cases/{uri}/audit` | `get_audit_trail` | PROV-O activities for one case |
| `GET /audit/aggregate` | `aggregate_audit` | Cross-case bucket counts (group_by + optional process filter + limit) |

## Web UI routes (not MCP-exposed)

| Path | What |
|---|---|
| `/ui/` | Dashboard — Tick all timers, status filter, case table |
| `/ui/processes` | Loaded processes table |
| `/ui/processes/{uri}` | Per-process analytics — status mix, top fired actions |
| `/ui/processes/{uri}/diagram` | CMMN-style inline SVG diagram |
| `/ui/cases/{uri}` | Case detail with lifecycle buttons, subcases, history |
| `/ui/cases/{uri}/explain` | Decision engine inspector — per-engine trace cards |
| `/ui/cases/{uri}/audit` | Audit table with `Counterfactual` link per row |
| `/ui/cases/{uri}/counterfactual?swap=<activity_uri>` | Counterfactual replay form |
| `POST /ui/cases/{uri}/{suspend,resume,compensate,execute-top,subcase}` | Mutating form-POST surfaces (303 redirect) |
| `POST /ui/tick` | Global tick from dashboard |
| `GET /ui/static/app.css` | The single stylesheet |

## MCP from a sister repo

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession

async with streamablehttp_client("http://localhost:8100/mcp") as (read, write, _):
    async with ClientSession(read, write) as session:
        await session.initialize()
        # List exposed tools (one per operation_id above)
        tools = await session.list_tools()
        # Call any tool by name
        result = await session.call_tool(
            "propose_next_action",
            {"case_uri": "urn:ontorag-flow:case:..."},
        )
```

## Response envelopes

All POST routes return the Pydantic model directly (e.g. `Case`,
`ActionProposal`, `ProvOActivity`). Error responses use FastAPI's
default `{"detail": "..."}` shape with appropriate status codes:

| Status | When |
|---|---|
| `404` | Case / process / action URI unknown |
| `409` | Case lifecycle transition invalid (e.g. resume an open case), or counterfactual engine unavailable |
| `422` | Pydantic validation (bad body shape, unknown `group_by` literal, etc.) |
| `500` | Unexpected — file an issue with the activity URI from the response |
