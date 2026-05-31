# Operations — backup, restore, disaster recovery

> **Audience.** Operators running ontorag-flow in production. Covers SQLite
> and PostgreSQL deployments. Read [operator-guide.md](operator-guide.md)
> first if you don't already know what a case is.

---

## What needs backing up

ontorag-flow's persistence is a single store (SQLite file or Postgres
schema) with three tables — `processes`, `cases`, `activities`. All
three together form the system of record:

- **`processes`** — process definitions. Easy to re-load from YAML / RDF
  source files if those are version-controlled; back up anyway so a
  stand-alone restore is possible without the source repo.
- **`cases`** — live case state. The hardest to lose. There is no
  upstream source to reconstruct from; what's in this table is the
  current truth.
- **`activities`** — PROV-O audit log. P5 (history bloat decision)
  made this the *authority* for case history; losing it means the case
  detail's "History" view becomes incomplete even if cases survive.

The web UI dashboard, in-memory engine state, and process definitions
loaded from YAML are derived — none of them needs backing up directly.

## SQLite deployment

Default for dev and small single-node prod. The store is one file
(`DATABASE_PATH`, default `ontorag_flow.db`).

## Snapshot while the server is running

SQLite's `.backup` API is the safe path — it uses the same locking the
running server uses, so you never get a torn read even mid-write. From
a shell on the host:

```bash
sqlite3 ontorag_flow.db ".backup '/var/backups/ontorag-flow-$(date +%F).db'"
```

If you must use a plain file copy (no `sqlite3` available), checkpoint
the WAL first so the snapshot file is self-contained:

```bash
sqlite3 ontorag_flow.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp ontorag_flow.db ontorag_flow-$(date +%F).db
# Then also copy the -wal and -shm sidecars if they exist, just in case:
cp ontorag_flow.db-wal ontorag_flow.db-shm /var/backups/ 2>/dev/null || true
```

Schedule via cron, k8s CronJob, or your platform's snapshot facility
(EBS, GCE persistent disk, etc.). Daily is the right default for
case-management workloads; hourly only when individual cases are
high-stakes.

## Restore

Stop the server, replace the file, restart:

```bash
docker compose stop ontorag-flow             # or: systemctl stop ontorag-flow
cp /var/backups/ontorag-flow-2026-05-30.db ./ontorag_flow.db
docker compose start ontorag-flow
```

Verify with the smoke flow in **Restore verification** below.

## Postgres deployment

Use when concurrent writers, larger volumes, or your platform's
managed-Postgres backup integration is preferred.

## Snapshot

Either:

- **Managed backup** — RDS / Cloud SQL / Neon native snapshots. Trust
  the provider, but still re-run the smoke flow after a test restore.
- **`pg_dump`** for portable, plain-SQL backups:

  ```bash
  pg_dump --format=custom --file=ontorag-flow-$(date +%F).dump \
      "$DATABASE_URL"
  ```

  Use `--format=custom` (not plain `pg_dump > file.sql`) so `pg_restore`
  can parallelise and reorder.

## Restore

```bash
# To an empty database:
pg_restore --create --dbname=postgres ontorag-flow-2026-05-30.dump

# In-place (drops existing tables — be sure):
pg_restore --clean --if-exists --dbname="$DATABASE_URL" ontorag-flow-2026-05-30.dump
```

## Audit-only backup

If full backups are too expensive but you still want forensic
recoverability ("which actions ran, when, against which case"),
back up just the audit:

```bash
# SQLite — extract the activities table only:
sqlite3 ontorag_flow.db ".dump activities" | gzip > activities-$(date +%F).sql.gz

# Postgres — dump just one table:
pg_dump --table=activities --format=custom "$DATABASE_URL" \
    > activities-$(date +%F).dump
```

Cases are not recoverable from audit-only backups, but every action
that ever ran *is* — useful for compliance / post-incident reviews
where the case state is reproducible from other systems.

## Restore verification

After any restore, run this smoke flow before reopening to operators:

```bash
# 1. Service starts cleanly.
curl -fsS http://localhost:8100/health
# {"status": "ok", ...}

# 2. Processes are present.
ontorag-flow process list

# 3. At least one case round-trips through the API.
case_uri=$(ontorag-flow case status <a-known-case-uri> | jq -r .case_uri)
[ -n "$case_uri" ] && echo "case readable: $case_uri"

# 4. Audit aggregation surfaces non-zero counts.
curl -fsS 'http://localhost:8100/audit/aggregate?group_by=action_uri' | jq

# 5. Dashboard renders.
curl -fsS http://localhost:8100/ui/ > /dev/null
```

If any of the five fails, **don't** open the system to operators —
investigate first.

## Backup operations checklist

- [ ] Backups land off-host (different disk, different region) so a
  host-level disaster doesn't take them with it.
- [ ] Encryption at rest if the database may contain personally-
  identifiable case state.
- [ ] Retention policy explicit — case-management workloads grow
  linearly with activity, not just users.
- [ ] At least one full restore drill per quarter against a *staging*
  environment, then run the smoke flow above. Untested backups are
  superstition, not protection.
- [ ] Backup logs / output captured somewhere — silent backup
  failures are how data loss happens.

## Retention — pruning the audit table

The audit log is append-only; without a purge it grows linearly with
case activity and eventually presses on disk + backup time. The
``ontorag-flow audit prune`` command + ``POST /audit/prune`` endpoint
delete *terminal* cases (``closed`` / ``failed``) whose ``updated_at``
is older than the configured window. Open and suspended cases are
never touched.

CLI:

```bash
# One-off prune — 90 days is a reasonable default for most teams.
ontorag-flow audit prune --older-than 90

# Dry run first when introducing retention to an existing system.
ontorag-flow audit prune --older-than 90 --dry-run
```

Set the default window once via ``AUDIT_RETENTION_DAYS`` and the CLI /
API both honour it when no explicit ``--older-than`` is passed.

Schedule from cron / k8s CronJob — never from inside the server
process, so a slow purge can't block request handling:

```cron
# 03:10 daily — prune anything terminal that's older than 90 days.
10 3 * * *  /usr/local/bin/ontorag-flow audit prune --older-than 90 >> /var/log/ontorag-flow-prune.log 2>&1
```

For a remote operator without shell access, drive it via the API
(combine with auth at the reverse proxy):

```bash
curl -fsS -X POST http://localhost:8100/audit/prune \
  -H 'content-type: application/json' \
  -d '{"older_than_days": 90}'
```

Always pair the first prune run with a backup taken **just before** —
prune is intentionally destructive (cases + activities both go).

## Rate limiting in front of the API

ontorag-flow has no built-in rate limiter (single-tenant assumption).
Public deployments must put a reverse proxy in front that authenticates
*and* limits. Two minimal examples below — both are starting points,
not turn-key configs.

### Nginx

```nginx
http {
    # 10 requests/second average, burst 20, no delay on burst.
    limit_req_zone $binary_remote_addr zone=flow_api:10m rate=10r/s;

    upstream ontorag_flow {
        server 127.0.0.1:8100;
    }

    server {
        listen 443 ssl http2;
        server_name flow.example.com;

        location / {
            limit_req zone=flow_api burst=20 nodelay;
            proxy_pass http://ontorag_flow;
            proxy_set_header Host              $host;
            proxy_set_header X-Real-IP         $remote_addr;
            proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # Health probes bypass the rate limit so a flapping deploy
        # never starves k8s liveness.
        location = /health {
            proxy_pass http://ontorag_flow/health;
        }
    }
}
```

### Caddy

```caddyfile
flow.example.com {
    # Caddy's rate_limit plugin is third-party — install with xcaddy.
    rate_limit {
        zone flow_api {
            key {remote_host}
            events 600
            window 1m
        }
    }

    handle /health* {
        reverse_proxy 127.0.0.1:8100
    }

    handle {
        rate_limit flow_api
        reverse_proxy 127.0.0.1:8100
    }
}
```

Tune limits per workload. A human-operator console rarely exceeds
10 req/min; an automation tool calling ``execute_action`` in a loop
may need 100 req/s. Start strict, observe, loosen.

## Structured logs (JSON)

The default formatter is human-readable for local development. In
production, ship JSON so a log collector (Loki, CloudWatch, Datadog)
can index by field rather than regex against a free-text line.

ontorag-flow emits to the standard ``logging`` module; configure a
JSON formatter at process start. Minimal recipe using ``python-json-logger``:

```bash
pip install python-json-logger
```

```python
# logging_config.py — load once, before ontorag_flow imports anything.
import logging
from pythonjsonlogger import jsonlogger

handler = logging.StreamHandler()
handler.setFormatter(
    jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
    )
)
root = logging.getLogger()
root.handlers[:] = [handler]
root.setLevel(logging.INFO)
```

Drive it with an env-var switch so dev keeps the human formatter:

```bash
# In the systemd unit / Docker entrypoint:
PYTHONSTARTUP=/etc/ontorag-flow/logging_config.py \
    ontorag-flow serve --port 8100
```

What to index: ``logger``, ``level``, ``case_uri``, ``action_uri``,
``activity_uri`` — the case manager and executor already include
these in their log records via positional args, so the JSON formatter
captures them automatically.

## What this guide does *not* cover

- **High availability / failover.** Single-node assumption matches
  CLAUDE.md's anti-pattern stance (no multi-tenant, no cluster). If
  you need HA, place ontorag-flow behind a proxy that can fail over
  to a read-only standby; that's outside the scope of this repo.
- **ontorag side backups.** Only the ABox state ontorag-flow writes
  back (via `AssertTriple`) lives there. Backup of ontorag's own
  store is documented in ontorag's repo, not here.
- **Authentication.** Same single-tenant posture — terminate
  auth at the reverse proxy (basic auth, OIDC, mTLS, your platform's
  IAP). The rate-limit snippets above are the spot to add it.
