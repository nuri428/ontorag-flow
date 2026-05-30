# Configuration

Settings are read from environment variables (or `.env` in the project
root). Defaults are safe for local development.

## Variables

| Variable | Default | Used by |
|---|---|---|
| `ONTORAG_MCP_URL` | `http://localhost:8000/mcp` | ontorag MCP client URL |
| `CONNECT_ONTORAG` | `false` | Open the ontorag connection at startup (enables Bayesian / Causal / ABox write-back) |
| `LLM_PROVIDER` | *(unset)* | `anthropic` / `openai` / `ollama`; enables `LlmAgentEngine` |
| `LLM_MODEL` | provider default | Model override (e.g. `claude-sonnet-4-6`, `gpt-4o`, `llama3.1`) |
| `DATABASE_PATH` | `ontorag_flow.db` | SQLite file path (ignored when using Postgres) |
| `DATABASE_URL` | *(unset)* | Postgres DSN (overrides `DATABASE_PATH`); requires `--extra postgres` |
| `AGENT_ID` | `urn:ontorag-flow:agent:system` | `prov:wasAssociatedWith` on every PROV-O activity |
| `API_HOST` | `127.0.0.1` | `ontorag-flow serve` bind host |
| `API_PORT` | `8100` | `ontorag-flow serve` bind port |
| `LOG_LEVEL` | `INFO` | Standard Python logging level |
| `ONTORAG_MCP_HTTPS_ONLY` | `false` | Refuse to connect when the ontorag URL is not `https://`. Defense against env-var hijack. See [Security S4](../security.md#s4-transport-trust). |
| `ONTORAG_EXPECTED_VERSION` | unset | Pinned ontorag version; WARN-log on drift after connect. Detection, not enforcement. |
| `ONTORAG_FLOW_PLUGIN_ALLOWLIST` | unset | Comma-separated entry-point names from `[project.entry-points."ontorag_flow.actions"]`; unlisted plugins are skipped. See [Security S7](../security.md#s7-ontorag_flow_plugin_allowlist). |

## Bootstrap

```bash
ontorag-flow init        # copy .env.example → .env
$EDITOR .env             # adjust ONTORAG_MCP_URL, CONNECT_ONTORAG, ...
ontorag-flow status      # probe ontorag MCP connection + show config
```

## Optional extras

```bash
uv sync --extra dev                # tests + ruff + pyright + bandit + testcontainers
uv sync --extra dev --extra llm    # + Anthropic / OpenAI SDKs
uv sync --extra postgres           # + asyncpg (production persistence)
uv sync --extra docs               # + mkdocs-material (this site's build deps)
```

## Engine availability matrix

| `engine:` choice | Needs `CONNECT_ONTORAG=true` | Needs `LLM_PROVIDER=...` | Notes |
|---|---|---|---|
| `rule` | no | no | Local only |
| `human` | no | no | Local only |
| `llm` | no | **yes** | Provider SDK + (optionally) `LLM_MODEL` |
| `bayesian` | **yes** (v0.7+) | no | `bayesian:` block in process YAML |
| `causal` | **yes** (v0.8+) | no | `causal:` block in process YAML |
| `stacked` | proposer + validator's deps | proposer-dependent | declared via `arbitration:` |
| `cascade` | union of sub-engine deps | union | declared via `arbitration: {sequence:}` |

If a process requests an engine whose backing client is missing,
`EngineUnavailableError` surfaces with an actionable message naming
exactly which env var / `--extra` is missing.

## Built-in action availability

| Action | Conditional |
|---|---|
| `UpdateCaseProperty`, `SetGoal`, `RequestHumanReview` | Always |
| `AssertTriple`, `RetractTriple` | Only when `CONNECT_ONTORAG=true` *and* the connection succeeds (registered by `with_triple_actions` in the FastAPI lifespan) |

## See also

- [How-to → Connect to ontorag](../how-to/ontorag.md)
- [How-to → Deploy with Docker](../how-to/docker.md)
- [Operations → backup / DR](../operations.md)
