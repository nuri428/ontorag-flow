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

## What this guide does *not* cover

- **High availability / failover.** Single-node assumption matches
  CLAUDE.md's anti-pattern stance (no multi-tenant, no cluster). If
  you need HA, place ontorag-flow behind a proxy that can fail over
  to a read-only standby; that's outside the scope of this repo.
- **ontorag side backups.** Only the ABox state ontorag-flow writes
  back (via `AssertTriple`) lives there. Backup of ontorag's own
  store is documented in ontorag's repo, not here.
