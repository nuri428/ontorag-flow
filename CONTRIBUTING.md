# Contributing to ontorag-flow

Thanks for considering a contribution. ontorag-flow is the Kinetic
layer companion to [ontorag](https://github.com/nuri428/ontorag);
together they explore an open-source take on Palantir's three-layer
ontology frame. Please read the project's
[`CLAUDE.md`](./CLAUDE.md) first — it captures the design philosophy
and the explicit list of anti-patterns we will not adopt.

By participating you agree to abide by the
[Code of Conduct](./CODE_OF_CONDUCT.md).

---

## Ways to contribute

| Kind | Where to start |
|---|---|
| **Bug report** | Open a [bug issue](https://github.com/nuri428/ontorag-flow/issues/new?template=bug.md). |
| **Feature idea** | Open a [feature issue](https://github.com/nuri428/ontorag-flow/issues/new?template=feature.md) **before** sending a PR — scope discussion first saves rework. |
| **Security vulnerability** | **Do not open a public issue.** See [SECURITY.md](./SECURITY.md) for the private reporting path. |
| **Documentation** | PRs welcome directly. Bilingual changes (EN + KO) preferred but not required — open an issue if you need help with the other language. |
| **New decision engine / action / store backend** | Open an issue first; the engine and action protocols are stable but the *registration* path (entry-points, reserved namespaces) has hard rules — see [Plugin authoring](#plugin-authoring). |

---

## Development setup

Requirements:

- Python 3.12 or 3.13
- [`uv`](https://docs.astral.sh/uv/) (preferred package manager)
- Docker (optional — needed only for the Postgres integration suite)

```bash
git clone https://github.com/nuri428/ontorag-flow.git
cd ontorag-flow

# Resolve and install dev + all optional extras in one shot.
uv sync --all-extras --dev

# Run the test suite (asyncio mode auto, coverage with an 80% floor).
uv run pytest

# Lint, typecheck, security scan — the same commands CI runs.
uv run ruff check src tests
uv run ruff format --check src tests
uv run pyright src
uv run bandit -q -r src
uv run pip-audit
```

The default store is SQLite in-memory; no external service is required
for the standard suite. The Postgres integration suite uses
[`testcontainers`](https://testcontainers.com) — running it locally
needs a Docker daemon, otherwise it is skipped.

---

## The five gates

Every PR is held to the same nine CI jobs that protect `main`. The
*five* gates that most often catch contributors:

1. **Lint** — `ruff check` and `ruff format --check`. Run
   `uv run ruff format src tests` to auto-fix style.
2. **Type check** — `pyright`. Add type annotations on every public
   function (`from __future__ import annotations` is on every module).
3. **Tests** — `pytest` with an **80% coverage floor**. Land tests in
   the same PR as the change; tests are how we move from "looks
   right" to "behaves right". See
   [`docs/operator-guide.md`](docs/operator-guide.md) for the
   developer flow.
4. **Security** — `bandit -r src` (static) and `pip-audit`
   (vulnerable deps). A failing `pip-audit` blocks the PR — bump
   the dependency in the same PR or pin a known-safe version.
5. **Docker smoke** — the image builds and the new `/health` route
   returns 200. If your change touches the runtime (Dockerfile,
   lifespan, store wiring), run `docker build -t flow . && docker run --rm -p 8100:8100 flow` locally.

The remaining four (codeql, docs build, postgres-integration,
reference-demo) usually pass when the five above do.

---

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>: <short imperative summary>

<optional body — wrap at 72 chars, explain *why* not just what>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`,
`ci`. Examples from `git log`:

```
feat: graceful shutdown flips readiness to 503 before tearing down
fix: include LICENSE in Docker build context so hatchling resolves
docs: add reverse-proxy rate-limit recipes for nginx + caddy
```

One concern per commit. A PR may contain several commits, but each
commit should compile, type-check, and pass its own tests.

---

## Pull request flow

1. Fork → branch (`git checkout -b feat/my-thing`).
2. Make the change with tests in the same commit / PR.
3. Run the five gates locally before pushing.
4. Open a PR using the [pull-request template](./.github/PULL_REQUEST_TEMPLATE.md).
5. Reference the issue you discussed (`Closes #123`); if there is no
   issue and the change is non-trivial, open one first.
6. CI must be green before review. A maintainer will review for
   design fit + the [anti-pattern list](./CLAUDE.md#what-not-to-do-anti-patterns)
   in `CLAUDE.md`.

Squash-merge is the default. Your commit history is preserved in the
PR view, not on `main`.

---

## Plugin authoring

Custom actions ship as Python packages exposing the
`ontorag_flow.actions` entry-point group. Hard rules — these are
enforced at load time and CI will catch violations:

- **Reserved URI namespace.** `urn:ontorag-flow:` is reserved for
  built-ins. Plugin actions must use a different prefix
  (`urn:my-team:action:...`, etc.). The plugin loader rejects any
  entry-point that registers a built-in-namespace URI.
- **Declared side effects.** Every action declares its
  `SideEffectKind` (`CASE_STATE` / `EXTERNAL_API` / `HUMAN` /
  `ABOX_WRITE` / `NONE`) up-front. Hidden mutation is a
  reviewer-blocker (see anti-patterns).
- **`ONTORAG_FLOW_PLUGIN_ALLOWLIST`.** When set, only listed entry
  points load. Document this in your plugin README so operators can
  opt your plugin in.

See [`docs/security.md`](docs/security.md) for the full plugin
trust model (Z5 / Z6 / S7 layers).

---

## Out of scope

The following are explicit non-goals — please don't open issues
proposing them as additions to core. They are listed verbatim in
[`CLAUDE.md`](./CLAUDE.md#what-not-to-do-anti-patterns):

- BPMN 2.0 compliance, visual BPMN editor, sequence flow + gateways
- Multi-tenant isolation, built-in auth/RBAC, email infrastructure
- LangChain / LlamaIndex / LangGraph / LangServe dependencies
- ML model training infrastructure (training-free through v0.9)
- Domain ontology storage (TBox + ABox live in ontorag)
- Auto-execute proposals without an explicit per-process policy

A *plugin* implementing one of these is welcome to live in its own
repo and register via entry-points; core stays focused.

---

## Questions

- **General**: open a [discussion](https://github.com/nuri428/ontorag-flow/discussions).
- **Security**: see [SECURITY.md](./SECURITY.md).
- **Maintainer contact**: <greennuri@gmail.com>.

Thanks for helping make ontorag-flow better.
