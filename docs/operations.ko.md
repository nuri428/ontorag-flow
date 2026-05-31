# Operations — backup, restore, disaster recovery

> **Audience.** Operators running ontorag-flow in production. Covers SQLite
> and PostgreSQL deployments. Read [operator-guide.md](operator-guide.md)
> first if you don't already know what a case is.

---

## 무엇을 백업해야 하는가

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

## SQLite 배포

개발 + 소규모 single-node 운영 기본. store는 파일 하나 (`DATABASE_PATH`,
기본 `ontorag_flow.db`).

## 서버 실행 중 snapshot

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

## 복원

서버 중지 → 파일 교체 → 재시작:

```bash
docker compose stop ontorag-flow             # 또는: systemctl stop ontorag-flow
cp /var/backups/ontorag-flow-2026-05-30.db ./ontorag_flow.db
docker compose start ontorag-flow
```

아래 **복원 검증** 의 smoke flow로 확인.

## Postgres 배포

동시 writer가 많거나, 더 큰 볼륨, 또는 플랫폼의 managed-Postgres 백업
통합을 쓸 때.

## Snapshot

둘 중 하나:

- **Managed backup** — RDS / Cloud SQL / Neon 네이티브 snapshot.
  제공자를 신뢰하되, 시험 복원 후엔 항상 smoke flow를 다시 돌리세요.
- **`pg_dump`** — 휴대 가능한 plain-SQL 백업:

  ```bash
  pg_dump --format=custom --file=ontorag-flow-$(date +%F).dump \
      "$DATABASE_URL"
  ```

  `--format=custom` 권장 — `pg_restore`가 병렬화 + 재정렬 가능.

## 복원

```bash
# 빈 DB로:
pg_restore --create --dbname=postgres ontorag-flow-2026-05-30.dump

# 제자리 (기존 테이블 drop — 확실히 하기):
pg_restore --clean --if-exists --dbname="$DATABASE_URL" ontorag-flow-2026-05-30.dump
```

## 감사-only 백업

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

## 복원 검증

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

## 백업 운영 체크리스트

- [ ] 백업이 host 외부 (다른 디스크, 다른 region)에 저장되어 host
  단위 재해가 함께 가져가지 못함.
- [ ] 케이스 상태에 개인 식별 정보가 있을 수 있다면 at-rest 암호화.
- [ ] 보존 정책 명시 — 케이스 관리 워크로드는 사용자가 아닌 *액션*에
  선형 비례해 자람.
- [ ] 분기에 한 번 *staging*에 전체 복원 drill 후 위 smoke flow.
  테스트되지 않은 백업은 미신이지 보호가 아닙니다.
- [ ] 백업 로그 / output 어딘가에 캡처 — silent 백업 실패가 데이터
  손실의 흔한 원인.

## 보존 — audit 테이블 정리

Audit log는 append-only입니다. 정리하지 않으면 케이스 활동에 선형
비례해 자라며 결국 디스크와 백업 시간을 압박합니다.
``ontorag-flow audit prune`` 명령과 ``POST /audit/prune`` 엔드포인트는
``updated_at``이 설정된 윈도우보다 오래된 *종료* 케이스 (``closed`` /
``failed``)를 삭제합니다. ``open``과 ``suspended`` 케이스는 절대 손대지
않습니다.

CLI:

```bash
# 일회성 prune — 90일이 대부분의 팀에 합리적인 기본값.
ontorag-flow audit prune --older-than 90

# 기존 시스템에 retention을 도입할 때는 먼저 dry-run.
ontorag-flow audit prune --older-than 90 --dry-run
```

기본 윈도우를 한 번 ``AUDIT_RETENTION_DAYS``로 설정하면, CLI와 API 모두
``--older-than``이 명시되지 않을 때 이 값을 따릅니다.

cron / k8s CronJob에서 스케줄하세요 — 서버 프로세스 *내부*에서 돌리지
않아야 느린 purge가 요청 처리를 막지 않습니다:

```cron
# 매일 03:10 — 90일 이상 종료된 모든 것을 prune.
10 3 * * *  /usr/local/bin/ontorag-flow audit prune --older-than 90 >> /var/log/ontorag-flow-prune.log 2>&1
```

shell 접근이 없는 원격 운영자라면 API로 (auth는 reverse proxy에서):

```bash
curl -fsS -X POST http://localhost:8100/audit/prune \
  -H 'content-type: application/json' \
  -d '{"older_than_days": 90}'
```

첫 prune 실행 직전에는 반드시 백업과 짝지으세요 — prune은 의도적으로
파괴적입니다 (케이스 + 활동 모두 삭제).

## API 앞단 rate limiting

ontorag-flow에는 빌트인 rate limiter가 없습니다 (single-tenant 가정).
공개 배포는 인증과 제한을 모두 수행하는 reverse proxy를 앞에 두어야
합니다. 아래 두 예제는 출발점이지 turn-key 설정이 아닙니다.

### Nginx

```nginx
http {
    # 평균 10 req/s, burst 20, burst에 delay 없음.
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

        # Health probe는 rate limit 우회 — 배포 중 flapping이 k8s
        # liveness를 굶기지 않도록.
        location = /health {
            proxy_pass http://ontorag_flow/health;
        }
    }
}
```

### Caddy

```caddyfile
flow.example.com {
    # Caddy rate_limit 플러그인은 third-party — xcaddy로 설치.
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

워크로드 별로 limit을 튜닝하세요. 사람 운영자 콘솔은 보통 10 req/min
초과하지 않습니다. ``execute_action``을 루프로 호출하는 자동화 도구는
100 req/s가 필요할 수 있습니다. 엄격하게 시작해 관측 후 완화하세요.

## 구조화된 로그 (JSON)

기본 formatter는 로컬 개발용 사람-가독 포맷입니다. 프로덕션에서는
JSON을 출력해 로그 수집기 (Loki, CloudWatch, Datadog)가 필드 단위로
인덱싱하게 하세요. 자유 텍스트 라인을 regex로 잡지 마세요.

ontorag-flow는 표준 ``logging`` 모듈로 출력합니다. 프로세스 시작 시
JSON formatter를 설정하면 됩니다. ``python-json-logger`` 사용 최소 레시피:

```bash
pip install python-json-logger
```

```python
# logging_config.py — ontorag_flow import 전에 한 번 load.
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

env-var 스위치로 dev는 사람 포맷 유지:

```bash
# systemd unit / Docker entrypoint에서:
PYTHONSTARTUP=/etc/ontorag-flow/logging_config.py \
    ontorag-flow serve --port 8100
```

인덱싱할 필드: ``logger``, ``level``, ``case_uri``, ``action_uri``,
``activity_uri`` — case manager와 executor가 이미 positional args로
log record에 포함하므로 JSON formatter가 자동으로 캡처합니다.

## 이 가이드가 *다루지 않는* 것

- **고가용성 / failover.** Single-node 가정은 CLAUDE.md anti-pattern
  (multi-tenant 없음, cluster 없음)과 일치. HA가 필요하면 ontorag-flow
  를 read-only standby로 failover 가능한 proxy 뒤에 두세요 — 이 저장소
  범위 밖.
- **ontorag 측 백업.** ontorag-flow가 `AssertTriple`로 write-back한
  ABox 상태만 그쪽에 있습니다. ontorag 자체 store 백업은 ontorag 저장소
  문서를 참조하세요.
- **인증.** 같은 single-tenant 자세 — auth는 reverse proxy에서 종료
  (basic auth, OIDC, mTLS, 플랫폼 IAP). 위 rate-limit 스니펫이 auth를
  추가할 위치입니다.
