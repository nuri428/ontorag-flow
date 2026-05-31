<!--
Thanks for the contribution. Please fill in the sections below.
For non-trivial changes, open an issue first to align on scope —
see CONTRIBUTING.md.
-->

## Summary

<!-- One paragraph: what does this change do, and why? -->

Closes #

## Type of change

<!-- Tick all that apply. -->

- [ ] Bug fix (no behavior change for callers who weren't hitting the bug)
- [ ] New feature
- [ ] Refactor (no functional change)
- [ ] Documentation only
- [ ] CI / packaging / release plumbing
- [ ] Security fix

## Layer touched

- [ ] Core (action / case / executor / process)
- [ ] Decision engines
- [ ] Persistence (SQLite / Postgres / store Protocol)
- [ ] API / MCP / UI
- [ ] CLI
- [ ] Plugin system
- [ ] Documentation
- [ ] CI / packaging

## Test plan

<!-- How did you verify this? Reviewers should be able to reproduce the
     check from this list. -->

- [ ] `uv run pytest` passes locally (80% coverage floor still met).
- [ ] `uv run ruff check src tests` clean.
- [ ] `uv run pyright src` clean.
- [ ] `uv run bandit -q -r src` clean.
- [ ] `uv run pip-audit` clean locally (or vulnerable dep bumped in this PR). Note: pip-audit no longer runs on every PR — it's on a weekly schedule + manual trigger.
- [ ] If runtime / Dockerfile / lifespan touched: container builds and
      `/health` returns 200.

## Anti-pattern check

<!-- Confirm the change doesn't violate the explicit non-goals in
     CLAUDE.md (BPMN visual editor, multi-tenant isolation, built-in
     auth, training infra, LangChain dependency, etc.). -->

- [ ] I read the [anti-patterns in CLAUDE.md](../CLAUDE.md#what-not-to-do-anti-patterns)
      and this PR does not conflict with any of them.

## Notes for the reviewer

<!-- Anything that doesn't fit above: trade-offs you made, follow-ups
     you're punting, edges you tested manually, etc. -->
