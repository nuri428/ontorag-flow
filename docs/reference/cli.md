# CLI

Every command supports `--help` for flags + defaults. This page is the
*flat catalog*; for end-to-end use see [Tutorials](../tutorials/first-case.md).

## Top-level

| Command | What |
|---|---|
| `ontorag-flow init` | Bootstrap `.env` from `.env.example` if absent |
| `ontorag-flow status` | Show config + probe ontorag MCP connection |
| `ontorag-flow serve [--host H --port P] [--graceful-timeout N]` | Run FastAPI + MCP + UI. `--graceful-timeout` (default 30s) is uvicorn's SIGTERM grace window; the lifespan also flips `/health/ready` to 503 immediately so a load balancer drains traffic during the window. |
| `ontorag-flow --version` | Print version |

## `action`

| Command | What |
|---|---|
| `ontorag-flow action list` | Print every registered action + declared side effects |
| `ontorag-flow action register <file.py>` | Dry-load a plugin file; report what it would contribute |
| `ontorag-flow action run <action_uri> [-p k=v ...]` | Validate + execute one action against an empty state |

## `process`

| Command | What |
|---|---|
| `ontorag-flow process load <path>` | Persist a process from YAML (or RDF: `.ttl` / `.rdf` / `.n3` / `.jsonld` / `.nt`) |
| `ontorag-flow process list` | List persisted process definitions |
| `ontorag-flow process simulate <path> [-s K=V] [--execute-top] [--explain]` | Dry-run a process YAML against the engine in an in-memory store. Nothing persists |
| `ontorag-flow process test <path>` | Run the YAML's `expectations:` block as engine regression tests; exit 1 on first failure |

## `case`

| Command | What |
|---|---|
| `ontorag-flow case create <process_uri> [-s K=V ...]` | Create a case from a process; optional initial state |
| `ontorag-flow case status <case_uri>` | Print state, history, status |
| `ontorag-flow case propose-next <case_uri>` | Ask the engine for proposals (no execution) |
| `ontorag-flow case execute <case_uri> <action_uri> [-p k=v ...]` | Run a chosen action against the case |
| `ontorag-flow case compensate <case_uri> [--target-activity URI]` | Saga rollback; selective tail with `--target-activity` |
| `ontorag-flow case suspend / resume <case_uri>` | Pause / reopen the case |
| `ontorag-flow case fork <case_uri> [--new-uri URI]` | New case copying state + history from a source |
| `ontorag-flow case subcase <parent_uri> <process_uri> [-s K=V]` | Spawn a child case under a parent |
| `ontorag-flow case tick` | Fire elapsed timer events across all open cases |
| `ontorag-flow case auto-run-all` | Auto-execute the top proposal on every open case that passes the [execute_policy gate](../security.md#s3-runtime-auto-run-all) |
| `ontorag-flow case counterfactual ...` | "What if Y at step X?" via the causal engine |

## `audit`

| Command | What |
|---|---|
| `ontorag-flow audit show <case_uri>` | Render the PROV-O activities table |
| `ontorag-flow audit export <case_uri> --format <jsonld\|turtle\|nt>` | Render the trail as RDF |
| `ontorag-flow audit prune --older-than N [--dry-run]` | Delete terminal (closed/failed) cases + activities older than N days. Open / suspended cases are never touched. Falls back to `AUDIT_RETENTION_DAYS` when `--older-than` is omitted. See [Operations — Retention](../operations.md#retention--pruning-the-audit-table). |

## Environment / extras

Most commands implicitly use:

- `ONTORAG_MCP_URL` (default `http://localhost:8000/mcp`)
- `CONNECT_ONTORAG` (default `false`)
- `LLM_PROVIDER` (`anthropic` / `openai` / `ollama`)
- `DATABASE_PATH` (SQLite file path)
- `AGENT_ID` (PROV-O `wasAssociatedWith`)

See [Configuration](configuration.md) for the full list.
