# Security policy

## Reporting a vulnerability

**Do not file a public GitHub issue for security reports.**

Open a private advisory at
<https://github.com/nuri428/ontorag-flow/security/advisories/new>.
We will respond within 7 days with a triage decision (accept /
need-more-info / decline) and a target patch window.

If you do not have a GitHub account or prefer email, contact
<greennuri@gmail.com> with the subject line
`[ontorag-flow security] <one-line summary>`.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✅ active |
| < 0.1 | ❌ pre-release; please upgrade |

We patch the latest minor on a best-effort basis. Older minors are
not maintained; the project predates a 1.0 stability promise.

## What is *in scope* for security reports

- Prompt injection bypassing
  [`LlmAgentEngine` defenses](https://nuri428.github.io/ontorag-flow/security/)
  (S1, S1+, S2, S5).
- An installed `ontorag_flow.actions` entry-point plugin successfully
  registering a URI under the reserved `urn:ontorag-flow:` namespace
  (bypassing Z5).
- The audit log losing or silently mutating a recorded activity.
- The `auto-run-all` gate firing an action marked
  `auto_execute_disabled`.
- The `audit_redact` mask leaking a configured key to disk, the
  inspector UI, or PROV-O export.
- An MCP client connecting over plain HTTP when
  `ONTORAG_MCP_HTTPS_ONLY=true` is set.

## What is *out of scope* (by design — see `docs/security.md`)

- No built-in authentication / RBAC / multi-tenant isolation. Public
  deployments are expected behind an auth reverse-proxy.
- Actions are arbitrary Python — review the action's source before
  registering it. The framework is not a sandbox.
- Backup encryption-at-rest is delegated to the storage layer
  (filesystem / database).

## Full security model

The 12-layer defense model is documented at
[docs/security.md](docs/security.md) (also bilingual EN/KO on the
[docs site](https://nuri428.github.io/ontorag-flow/security/)),
including the threat → defense matrix that maps attacker actions to
the layer(s) that catch them.
