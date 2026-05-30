# How-to: deploy with Docker

A multi-stage `Dockerfile` ships in the repo: `python:3.12-slim`,
`uv`-built venv, non-root user, stdlib `urllib`-based `/health`
healthcheck. Final image is ~230 MB with the core deps only.

## Build & run (SQLite)

```bash
docker compose up
#   →  http://localhost:8100/ui/      (dashboard, lifecycle UI)
#   →  http://localhost:8100/docs     (OpenAPI)
#   →  http://localhost:8100/health   (liveness)
```

The compose default mounts a host volume so SQLite data persists across
restarts. The image runs as a non-root user; the volume mount needs
matching ownership if you customize the path.

## Postgres profile

```bash
docker compose --profile postgres up
```

Brings up a `postgres:16-alpine` sidecar; ontorag-flow's `DATABASE_URL`
points at it via the compose network.

## Build with optional extras

The base image installs core + dev. To bake LLM / Postgres SDKs into
the image:

```bash
docker build --build-arg INSTALL_EXTRAS="postgres llm" -t ontorag-flow:full .
```

`INSTALL_EXTRAS` is a space-separated list passed through to
`uv sync --extra ...`.

## Compose with ontorag

```bash
docker compose -f docker-compose.yml -f ../ontorag/docker-compose.yml up
```

The two compose files share the default network so `ONTORAG_MCP_URL`
can use the ontorag service name:

```yaml
# docker-compose.yml additions
services:
  ontorag-flow:
    environment:
      ONTORAG_MCP_URL: http://ontorag:8000/mcp
      CONNECT_ONTORAG: "true"
```

## Health-check semantics

The container's healthcheck (`HEALTHCHECK CMD python /health.py` —
stdlib `urllib`, no curl needed) hits `GET /health` and expects
`200 OK`. compose marks the container `healthy` once the FastAPI
lifespan has finished opening SQLite/Postgres.

## Image size budget

| Layer | Size |
|---|---|
| `python:3.12-slim` base | ~125 MB |
| Application venv (core deps only) | ~95 MB |
| Source + UI templates + static | ~5 MB |
| **Final (no extras)** | **~230 MB** |
| + `llm` extra (anthropic + openai SDKs) | +~80 MB |
| + `postgres` extra (asyncpg) | +~10 MB |

## CI smoke

The Docker CI job builds the image, starts the container, polls
`/health` until 200 (max 20 seconds), then stops the container. So
broken Dockerfiles fail CI before they hit a registry.

## Backup / restore

See [Operations → backup & restore](../operations.md) for the
SQLite snapshot pattern, Postgres `pg_dump`, audit-only backup, and
the post-restore smoke flow.
