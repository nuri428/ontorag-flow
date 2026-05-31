# Changelog

All notable changes to ontorag-flow are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

(Nothing here yet — open a PR to land the next change.)

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
