# syntax=docker/dockerfile:1.7

# ontorag-flow runtime image. Multi-stage so the final layer carries only
# the venv + source (no uv, no build cache, no apt scratch).

# --- Stage 1: build the venv with uv ---------------------------------------
FROM python:3.12-slim AS build

# Bring the uv binary in from the official image (smaller than installing
# uv via pip and avoids pulling pip itself into the build context).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Resolve and install dependencies first (cacheable layer — only changes
# when manifests change). pyproject's [project.readme] points at README.md
# and [project.license] points at LICENSE — both must be present before
# uv sync touches the project (hatchling reads them during metadata).
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Then the source + install the project itself.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Optional extras are opt-in at build time:
#   docker build --build-arg INSTALL_EXTRAS="postgres llm" .
ARG INSTALL_EXTRAS=""
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$INSTALL_EXTRAS" ]; then \
        for extra in $INSTALL_EXTRAS; do \
            uv sync --frozen --no-dev --extra "$extra"; \
        done; \
    fi


# --- Stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim AS runtime

# Non-root user — never run a network service as root.
RUN groupadd --system app \
 && useradd --system --gid app --home /app --shell /sbin/nologin app

WORKDIR /app

# Copy the venv (and project source) built in stage 1.
COPY --from=build --chown=app:app /app /app

# Make the venv's binaries (including `ontorag-flow`) resolve.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    API_HOST=0.0.0.0 \
    API_PORT=8100 \
    DATABASE_PATH=/data/ontorag_flow.db

# SQLite default: persist across container restarts on a named volume.
RUN mkdir -p /data && chown app:app /data
VOLUME /data

USER app
EXPOSE 8100

# Liveness via the same /health route the UI/MCP routes rely on. urllib
# is in the standard library, so the image stays curl/wget-free.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import sys, urllib.request as r; sys.exit(0 if r.urlopen('http://localhost:8100/health', timeout=2).status == 200 else 1)"

CMD ["ontorag-flow", "serve"]
