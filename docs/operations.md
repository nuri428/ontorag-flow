# Operations — backup, restore, disaster recovery

> **Audience.** Operators running ontorag-flow in production. Covers SQLite
> and PostgreSQL deployments. Read [operator-guide.md](operator-guide.md)
> first if you don't already know what a case is.
>
> *Korean translation is below. 한국어 번역은 아래에 있습니다.*

---

## English

### What needs backing up

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

### SQLite deployment

Default for dev and small single-node prod. The store is one file
(`DATABASE_PATH`, default `ontorag_flow.db`).

#### Snapshot while the server is running

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

#### Restore

Stop the server, replace the file, restart:

```bash
docker compose stop ontorag-flow             # or: systemctl stop ontorag-flow
cp /var/backups/ontorag-flow-2026-05-30.db ./ontorag_flow.db
docker compose start ontorag-flow
```

Verify with the smoke flow in **Restore verification** below.

### Postgres deployment

Use when concurrent writers, larger volumes, or your platform's
managed-Postgres backup integration is preferred.

#### Snapshot

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

#### Restore

```bash
# To an empty database:
pg_restore --create --dbname=postgres ontorag-flow-2026-05-30.dump

# In-place (drops existing tables — be sure):
pg_restore --clean --if-exists --dbname="$DATABASE_URL" ontorag-flow-2026-05-30.dump
```

### Audit-only backup

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

### Restore verification

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

### Backup operations checklist

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

### What this guide does *not* cover

- **High availability / failover.** Single-node assumption matches
  CLAUDE.md's anti-pattern stance (no multi-tenant, no cluster). If
  you need HA, place ontorag-flow behind a proxy that can fail over
  to a read-only standby; that's outside the scope of this repo.
- **ontorag side backups.** Only the ABox state ontorag-flow writes
  back (via `AssertTriple`) lives there. Backup of ontorag's own
  store is documented in ontorag's repo, not here.

---

## 한국어

### 무엇을 백업해야 하는가

ontorag-flow의 영속성은 단일 store (SQLite 파일 또는 Postgres 스키마)와
세 테이블 — `processes`, `cases`, `activities` — 로 구성됩니다. 세 개가
함께 시스템의 권위 있는 사본입니다:

- **`processes`** — 프로세스 정의. YAML / RDF 소스가 버전 관리된다면
  재로드가 쉽지만, 그래도 백업해두면 소스 저장소 없이도 stand-alone
  복원 가능.
- **`cases`** — 라이브 케이스 상태. 잃어버리면 가장 치명적. 재구성할
  상위 소스가 없습니다 — 이 테이블이 곧 현재의 진실.
- **`activities`** — PROV-O 감사 로그. P5 결정 (history bloat) 이후
  이 테이블이 케이스 history의 *권위*입니다 — 잃으면 케이스가 살아도
  detail의 "History" 뷰가 불완전해짐.

대시보드 캐시, in-memory 엔진 상태, YAML에서 로드된 프로세스 정의는
*파생물* — 직접 백업할 필요 없습니다.

### SQLite 배포

개발 + 소규모 single-node 운영 기본. store는 파일 하나 (`DATABASE_PATH`,
기본 `ontorag_flow.db`).

#### 서버 실행 중 snapshot

SQLite의 `.backup` API가 안전한 길 — 실행 중 서버와 같은 잠금을 사용해
write 중간에도 torn read가 안 됩니다:

```bash
sqlite3 ontorag_flow.db ".backup '/var/backups/ontorag-flow-$(date +%F).db'"
```

`sqlite3` 도구가 없어 plain 파일 복사를 해야 한다면, WAL을 먼저
checkpoint해서 snapshot이 self-contained가 되도록:

```bash
sqlite3 ontorag_flow.db "PRAGMA wal_checkpoint(TRUNCATE);"
cp ontorag_flow.db ontorag_flow-$(date +%F).db
# -wal / -shm sidecar도 있으면 함께 복사 (안전 차원):
cp ontorag_flow.db-wal ontorag_flow.db-shm /var/backups/ 2>/dev/null || true
```

cron, k8s CronJob, 또는 플랫폼의 snapshot (EBS / GCE PD 등) 으로 스케줄.
케이스 관리 워크로드는 *일 단위*가 기본; 개별 케이스가 매우 중요할 때만
*시간 단위*.

#### 복원

서버 중지 → 파일 교체 → 재시작:

```bash
docker compose stop ontorag-flow             # 또는: systemctl stop ontorag-flow
cp /var/backups/ontorag-flow-2026-05-30.db ./ontorag_flow.db
docker compose start ontorag-flow
```

아래 **복원 검증** 의 smoke flow로 확인.

### Postgres 배포

동시 writer가 많거나, 더 큰 볼륨, 또는 플랫폼의 managed-Postgres 백업
통합을 쓸 때.

#### Snapshot

둘 중 하나:

- **Managed backup** — RDS / Cloud SQL / Neon 네이티브 snapshot.
  제공자를 신뢰하되, 시험 복원 후엔 항상 smoke flow를 다시 돌리세요.
- **`pg_dump`** — 휴대 가능한 plain-SQL 백업:

  ```bash
  pg_dump --format=custom --file=ontorag-flow-$(date +%F).dump \
      "$DATABASE_URL"
  ```

  `--format=custom` 권장 — `pg_restore`가 병렬화 + 재정렬 가능.

#### 복원

```bash
# 빈 DB로:
pg_restore --create --dbname=postgres ontorag-flow-2026-05-30.dump

# 제자리 (기존 테이블 drop — 확실히 하기):
pg_restore --clean --if-exists --dbname="$DATABASE_URL" ontorag-flow-2026-05-30.dump
```

### 감사-only 백업

전체 백업이 너무 비싸지만 법의학적 복원성 ("어떤 action이 언제 어느
케이스에 실행됐는지")은 유지하고 싶다면, 감사만 백업:

```bash
# SQLite — activities 테이블만:
sqlite3 ontorag_flow.db ".dump activities" | gzip > activities-$(date +%F).sql.gz

# Postgres — 한 테이블만 dump:
pg_dump --table=activities --format=custom "$DATABASE_URL" \
    > activities-$(date +%F).dump
```

감사-only 백업에서 케이스는 복원되지 않지만, 실행된 모든 action은 복원
됩니다 — compliance / 사후 검토에 유용 (케이스 상태가 다른 시스템에서
재구성 가능할 때).

### 복원 검증

복원 후 운영자에게 다시 열기 *전에* 이 smoke flow를 실행:

```bash
# 1. 서비스가 깨끗이 시작
curl -fsS http://localhost:8100/health
# {"status": "ok", ...}

# 2. Processes가 존재
ontorag-flow process list

# 3. 적어도 하나의 케이스가 API round-trip
case_uri=$(ontorag-flow case status <known-case-uri> | jq -r .case_uri)
[ -n "$case_uri" ] && echo "case readable: $case_uri"

# 4. 감사 집계가 non-zero count 반환
curl -fsS 'http://localhost:8100/audit/aggregate?group_by=action_uri' | jq

# 5. 대시보드 렌더링
curl -fsS http://localhost:8100/ui/ > /dev/null
```

5개 중 하나라도 실패하면 **운영자에게 열지 마세요** — 먼저 조사.

### 백업 운영 체크리스트

- [ ] 백업이 host 외부 (다른 디스크, 다른 region)에 저장되어 host
  단위 재해가 함께 가져가지 못함.
- [ ] 케이스 상태에 개인 식별 정보가 있을 수 있다면 at-rest 암호화.
- [ ] 보존 정책 명시 — 케이스 관리 워크로드는 사용자가 아닌 *액션*에
  선형 비례해 자람.
- [ ] 분기에 한 번 *staging*에 전체 복원 drill 후 위 smoke flow.
  테스트되지 않은 백업은 미신이지 보호가 아닙니다.
- [ ] 백업 로그 / output 어딘가에 캡처 — silent 백업 실패가 데이터
  손실의 흔한 원인.

### 이 가이드가 *다루지 않는* 것

- **고가용성 / failover.** Single-node 가정은 CLAUDE.md anti-pattern
  (multi-tenant 없음, cluster 없음)과 일치. HA가 필요하면 ontorag-flow
  를 read-only standby로 failover 가능한 proxy 뒤에 두세요 — 이 저장소
  범위 밖.
- **ontorag 측 백업.** ontorag-flow가 `AssertTriple`로 write-back한
  ABox 상태만 그쪽에 있습니다. ontorag 자체 store 백업은 ontorag 저장소
  문서를 참조하세요.
