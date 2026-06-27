# patent_board SRE — Incident RCA Example

patent_board는 B2B 특허 플랫폼으로 24h 운영, 매일 배포가 이루어지는 도메인이다.
이 예제는 인시던트 발생 시 ontorag-flow로 RCA 프로세스를 안내하고,
결과를 **ontorag-memory**에 기록하는 end-to-end 시나리오를 보여준다.

## 시스템 구성

```
patent_board 인시던트
        │
        ▼
ontorag-flow (RCA 프로세스 안내)
 ├── RuleEngine → 다음 단계 제안
 ├── LlmAgentEngine → ontorag MCP 호출로 컨텍스트 보강
 └── AssertTriple → ontorag-memory에 결과 기록
        │
        ▼
ontorag-memory (urn:ag:incident:YYYY-MM-DD:slug)
 ├── rationale: 근본 원인
 ├── content: 수정 조치
 └── involves: urn:ag:proj:patent-board
        │
        ▼
미래 인시던트 시 search_by_rationale / summarize 로 유사 사례 조회
```

## 프로세스 단계

| 단계 | stage 값 | 설명 |
|------|----------|------|
| 1 | `detected` | 인시던트 감지 (모니터링 알림) |
| 2 | `triaged` | severity 평가 + on-call 지정 |
| 3 | `impact_assessed` | 영향 범위(사용자, 서비스) 파악 |
| 4 | `rca_done` | 근본 원인 식별 |
| 5 | `fix_deployed` | 수정 조치 배포 확인 |
| 6 | `postmortem_complete` | 포스트모템 완성 → 케이스 종료 |

## 빠른 시작

```bash
# 1. ontorag + Fuseki 실행
cd ../../  # ontorag-flow 루트
docker compose up -d

# 2. 프로세스 로드
uv run ontorag-flow process load examples/patent_board_sre/process.yaml

# 3. 인시던트 케이스 생성
uv run ontorag-flow case create urn:ontorag-flow:process:patent-board-sre-rca \
  --initial-state severity=P2 \
  --initial-state incident_uri=urn:ag:incident:2026-06-27:api-timeout

# 4. 다음 단계 제안 조회
uv run ontorag-flow case propose-next <case_uri>

# 5. RCA 결과를 ontorag-memory에 직접 기록
uv run python examples/patent_board_sre/record_incident.py
```

## ontorag-memory 쿼리 예제

```python
from ontorag_memory.client import MemoryClient
from ontorag_memory.registry import P

async with await MemoryClient.create() as mem:
    # 최근 인시던트 목록
    recent = await mem.recall_recent(n=10)
    incidents = [r for r in recent if "incident" in r["uri"]]

    # Fuseki 관련 과거 인시던트
    similar = await mem.search_by_rationale("Fuseki", limit=5)

    # 인시던트 요약
    summary = await mem.summarize("urn:ag:incident:2026-06-27:api-timeout")

    # patent-board 관련 인시던트 전체 (전이적)
    all_related = await mem.find_path_transitive(
        "urn:ag:proj:patent-board",
        P.INVOLVES,
        direction="in",
    )
```

## 학습 포인트

1. **ontorag-memory의 why-first 패턴**: 인시던트 `rationale`에 근본 원인을 저장하면
   `search_by_rationale("타임아웃")`으로 유사 패턴을 즉시 발견할 수 있다.

2. **find_path_transitive**: `urn:ag:proj:patent-board`에서
   `urn:ag:rel:involves` 술어를 따라가면 모든 관련 인시던트 URI를 한 번에 가져온다.

3. **summarize()**: LLM 컨텍스트 주입 시 `why() + recall()` 조합 대신
   단일 호출로 마크다운 요약을 얻을 수 있다.

4. **AssertTriple saga compensation**: 인시던트 기록이 실패해도
   `CaseManager.compensate()`가 이전 state로 돌아간다 — 온톨로지 오염 없음.
