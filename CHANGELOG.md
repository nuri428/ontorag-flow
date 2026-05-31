# Changelog

All notable changes to ontorag-flow are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Operational safety

- `GET /health/ready` — Kubernetes-style readiness probe distinct
  from the liveness `GET /health`. Touches the store + verifies
  case-manager wiring; returns 503 with per-check breakdown when
  not ready or shutting down.
- Graceful shutdown — on SIGTERM the lifespan flips
  `app.state.shutting_down` so `/health/ready` starts returning 503
  *before* the store closes, letting a load balancer drain traffic.
  `ontorag-flow serve --graceful-timeout N` (default 30s) forwards
  to uvicorn's `timeout_graceful_shutdown` so in-flight saga
  executions finish.
- Audit retention — `ontorag-flow audit prune --older-than N
  [--dry-run]` CLI command and `POST /audit/prune` MCP-exposed
  endpoint delete terminal (`closed` / `failed`) cases + activities
  past the configured window. Open / suspended cases are never
  touched. `AUDIT_RETENTION_DAYS` setting acts as a default;
  refuses `--older-than 0` outright.
- `SqliteStore` + `PostgresStore` gain `delete_by_case` and
  `delete_case` (FK-safe order); `CaseStore` Protocol unchanged so
  in-memory test stores keep working unchanged.

### Added — Documentation

- `docs/operations.md` (+ Korean mirror) gains Retention, Rate
  limiting (nginx + Caddy reverse-proxy snippets), and Structured
  logs (python-json-logger recipe) sections. Authentication added
  to the not-covered list — it's a proxy concern by design.
- `CONTRIBUTING.md` — dev setup, five-gate CI overview,
  Conventional Commits convention, plugin authoring rules (Z5/Z6/S7
  references), explicit out-of-scope list from `CLAUDE.md`.
- `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1 (official
  EthicalSource release, contact `greennuri@gmail.com`).

### Added — GitHub repository hygiene

- `.github/ISSUE_TEMPLATE/` — structured bug + feature forms with
  `config.yml` directing questions to Discussions and security
  reports to private advisories.
- `.github/PULL_REQUEST_TEMPLATE.md` — five-gate checklist,
  layer-touched taxonomy, anti-pattern self-check.
- `.github/workflows/publish.yml` — PyPI publish via OIDC
  trusted-publisher on `v*` tags. Two-job split (build / publish)
  with the `pypi` environment as the OIDC trust boundary; no
  long-lived API token stored in repo secrets.

### Fixed

- Docker build — `uv sync` now uses `--no-editable` so hatchling
  resolves the LICENSE file referenced by PEP 639
  `license = { file = "LICENSE" }`. Editable builds run hatchling
  in an isolated temp dir that lost the LICENSE reference, failing
  with `OSError: License file does not exist: LICENSE`.

## [0.1.0] — 2026-05-31

First public release. Everything below ships under MIT.

### Added — Core orchestration

- Action protocol (`validate` / `execute` / `compensate` / `audit_record`)
  with declared `SideEffectKind` (`CASE_STATE` / `EXTERNAL_API` / `HUMAN`
  / `ABOX_WRITE` / `NONE`).
- Immutable `Case` model with state machine
  (`open` / `suspended` / `closed` / `failed`), parent/subcase
  linkage, optimistic locking on update.
- CMMN-inspired `ProcessDefinition` — YAML *and* RDF (Turtle / JSON-LD)
  round-trip via `core/process_rdf.py`.
- `CaseManager` orchestrating `execute → state apply → audit` with
  saga compensation, suspend/resume/fork, subcase tree, timer events,
  ordering constraints (`mutex` / `requires` / `immediately_after` /
  `at_most_once`), human handoff.
- `skeleton` field — optional happy-path sequence, advisory by default,
  deviations flagged in PROV-O metadata.

### Added — Decision engines (six pluggable + two arbitration modes)

- `RuleEngine` (declarative decision table)
- `BayesianMpeEngine` (`P(goal | evidence)` via ontorag MCP)
- `CausalSimulationEngine` (`P(goal | do(intervention))` — Pearl Rung 2)
- `LlmAgentEngine` (Anthropic / OpenAI / Ollama)
- `HumanReviewEngine`
- `StackedEngine` — proposer + causal validator, declarable from YAML
- `CascadeEngine` — fallback chain `[llm, rule, human]`, declarable
  from YAML, with optional `health_check`
- Optional `engine.explain()` contract returning `EngineExplanation`
  with per-engine reasoning trace.
- Counterfactual replay (Pearl Rung 3) via causal engine + ontorag
  v0.8+.

### Added — Persistence

- `SqliteStore` (development default)
- `PostgresStore` (production, `--extra postgres`) — tested live via
  testcontainers.
- Same Protocols both ways; optimistic locking; audit-as-authority
  for case history.

### Added — API + MCP + UI

- FastAPI REST with `fastapi-mcp` mount — every named operation is
  both an HTTP endpoint *and* an MCP tool.
- `GET /audit/aggregate` — cross-case forensic surface.
- `POST /cases/auto-run-all` — gated batch auto-run (cron-friendly).
- Web UI: dashboard, case detail with mutating lifecycle buttons
  (Suspend / Resume / Compensate / Execute top / Spawn subcase),
  decision engine inspector (`/explain`) with engine-specific cards,
  counterfactual replay form, audit trail with `Counterfactual` link
  per row, process inspector + CMMN-style inline SVG diagram.

### Added — Built-in actions

- `UpdateCaseProperty`, `SetGoal` (CASE_STATE)
- `RequestHumanReview` (HUMAN + CASE_STATE, auto_execute_disabled)
- `AssertTriple`, `RetractTriple` (ABOX_WRITE, auto_execute_disabled,
  saga-compensating, registered only when an `OntoragClient` is live)

### Added — Plugin discovery (S7 + Z5)

- Python entry-points group `ontorag_flow.actions`.
- `ONTORAG_FLOW_PLUGIN_ALLOWLIST` env var (S7).
- Reserved URI namespace `urn:ontorag-flow:` for built-ins; plugins in
  that namespace are rejected at load (Z5).
- Mirror sanity test: every built-in must live in the reserved
  namespace (Z6).

### Added — Security hardening (S1..S7 + Z1, Z5..Z8 — 12 layers)

- S1 anti-injection system prompt for `LlmAgentEngine`, with
  rejected-proposals audit.
- S1+ prompt-echo detection (raw reply containing system-prompt
  sentinels drops every proposal).
- S2 `process.max_llm_confidence` cap.
- S3 `process.execute_policy` + `Action.auto_execute_disabled` (model).
- S3-runtime `auto-run-all` 4-gate.
- S4 `ONTORAG_MCP_HTTPS_ONLY` + `ONTORAG_EXPECTED_VERSION` env vars.
- S5 `CascadeEngine.health_check` (sanity-filter compromised proposers).
- S6 `process.audit_redact` (fnmatch globs mask values in audit + UI).
- S7 `ONTORAG_FLOW_PLUGIN_ALLOWLIST`.
- Z1 `pip-audit` CI job.
- Z5 plugin URI namespace reserved.
- Z6 built-in URI namespace symmetric guard.
- Z7 `ProcessDefinition` validator rejects typos in `execute_policy` /
  `audit_redact` / `arbitration`.
- Z8 threat → defense matrix in `docs/security.md` (EN + KO).

### Added — Documentation site

- MkDocs Material at <https://nuri428.github.io/ontorag-flow/>.
- Bilingual EN + KO via `mkdocs-static-i18n`.
- Diátaxis structure: Tutorials / How-to / Reference / Architecture +
  dedicated Philosophy and Security pages.
- Python API reference auto-rendered from in-source Google-style
  docstrings via `mkdocstrings`.

### Added — CI

- Lint (ruff format + check), typecheck (pyright), security
  (bandit), test matrix Python 3.12 + 3.13 (pytest + coverage,
  84%+ floor), live Postgres integration via testcontainers,
  reference-demo smoke job, Docker build + `/health` smoke,
  dependency vulnerability scan (`pip-audit`), CodeQL, Dependabot.

### Decided — `CLAUDE.md` Open questions resolved this cycle

- Process model serialization → YAML + RDF, both first-class.
- Action atomicity → sagas (v0.7).
- Write-back to ontorag → `assert_triple` / `retract_triple` MCP
  tools.
- Cross-repo testing → in-process fake MCP fixture
  (`tests/_mcp_fixture.py`) + live Postgres testcontainers.
- Versioning ontorag compatibility → compatibility matrix in README.
- External action registration → Python entry-points + reserved
  namespace + allowlist.
- Decision engine arbitration → `engine: stacked` + `engine:
  cascade` declarable in YAML (partial — voting / LLM tie-breaker
  remain open).

### Known limitations

- Bayesian / Causal engines require ontorag v0.7+ / v0.8+; until
  available, `engine: bayesian` / `engine: causal` surfaces
  `EngineUnavailableError` with the exact `--extra` / env var to
  set.
- `AssertTriple` requires ontorag-side `assert_triple` MCP tool
  (planned ontorag v0.7.x). Until then, calls return
  `OntoragClientError` and the write-ahead PROV-O row stays
  `failed` — no silent skip.
- Single-tenant assumption: no built-in auth / RBAC / multi-tenant
  isolation. Public deployments must put a reverse-proxy with auth
  in front. See `docs/security.md` for what is intentionally not
  defended.

[Unreleased]: https://github.com/nuri428/ontorag-flow/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/nuri428/ontorag-flow/releases/tag/v0.1.0
