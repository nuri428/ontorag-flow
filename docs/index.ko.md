# ontorag-flow

> **온톨로지 기반 적응형 케이스 관리(Adaptive Case Management) — [ontorag](https://github.com/ontorag) 위의 Kinetic 레이어.**
> ontorag가 *"무엇이 있고 우리가 무엇을 믿는가"* 라면, ontorag-flow는 *"그것에 대해 무엇을 할 것인가"* 입니다.

```
┌─────────────────────────────┐   ┌──────────────────────────────┐
│  ontorag                    │   │  ontorag-flow  (이 저장소)    │
│  ─────────                  │   │  ─────────────                │
│  Semantic  OWL/RDF          │   │  Kinetic   Actions            │
│  Dynamic   Bayesian / Causal│ ← │  Dynamic   Orchestration      │
│  세상에 대한 추론             │ → │  세상에 대한 행동             │
└─────────────────────────────┘   └──────────────────────────────┘
              ↑                                 ↑
              └────────────  MCP  ──────────────┘
```

오픈소스 **Palantir 스타일 3-레이어 온톨로지 스택**: ontorag가 추론하고,
ontorag-flow가 행동하며, 둘은 [MCP](https://modelcontextprotocol.io)로
대화합니다.

**BPM ↔ ACM 스펙트럼 어디인가:** ontorag-flow는 ACM-leaning (엔진이
추천, 운영자가 승인, pre-baked 시퀀스 없음)을 기본으로 하고, 같은
프로세스 YAML에서 *constraints + skeleton + 결정적 엔진을 조여서* BPM
rigid 끝까지 도달합니다. Runtime은 바뀌지 않고 데이터가 바뀝니다.
Provenance는 전체적으로 non-optional이라 적응형 실행도 forensically
replayable. long-form rationale은 [**Philosophy →**](philosophy.md).

---

## 60초 퀵스타트

```bash
git clone https://github.com/nuri428/ontorag-flow.git
cd ontorag-flow
uv sync --extra dev

# 참조 데모 (합성 환자 케이스가 자동 종료됨)
uv run python examples/medical_triage/run_demo.py

# HTTP API + Web UI
uv run ontorag-flow serve
#   →  http://localhost:8100/ui/                     (대시보드, Tick all timers)
#   →  http://localhost:8100/ui/cases/<uri>          (lifecycle 버튼, subcase 트리)
#   →  http://localhost:8100/ui/cases/<uri>/explain  (엔진 inspector — "왜?")
#   →  http://localhost:8100/ui/cases/<uri>/audit    (PROV-O + Counterfactual 링크)
#   →  http://localhost:8100/docs                    (OpenAPI)
#   →  http://localhost:8100/mcp                     (MCP transport)
```

데모는 rule engine의 추론을 단계별로 출력하고, 케이스가 목표 도달 시 자동
종료되는 것을 보여주며, PROV-O Turtle 감사 trail을 내보냅니다.

---

## 무엇을 얻는가

| 기능 | 위치 |
|---|---|
| 부수효과 선언이 포함된 Action 프로토콜 | `core/action.py` |
| 불변 `Case` + 상태 머신, parent/subcase 연결 | `core/case.py` |
| CMMN 기반 `ProcessDefinition` (YAML 또는 RDF/Turtle/JSON-LD) | `core/process.py`, `core/process_rdf.py` |
| `CaseManager` — execute → state apply → audit 오케스트레이션, saga compensation, suspend/resume/fork, subcase 트리, timer events, 순서 제약, human handoff | `core/case_manager.py` |
| **6개의 플러그형 결정 엔진** — YAML에서 선언 가능한 `StackedEngine` / `CascadeEngine` 포함 | `engines/` |
| 선택적 **`engine.explain()`** — 엔진별 reasoning trace | `engines/base.py` + 각 엔진 |
| 영속성: SQLite (개발) 및 Postgres (운영), 동일 Protocol, optimistic locking | `stores/` |
| Web UI — 대시보드, mutating lifecycle 버튼, 엔진 inspector, counterfactual replay, audit | `ui/` |
| FastAPI REST + `fastapi-mcp` — 모든 operation이 MCP tool이기도 함 | `api/` |
| ABox write-back 액션 (`AssertTriple` / `RetractTriple`) — ontorag MCP 통과 | `actions/triples.py` |

---

## 스크린샷

라이브 ontorag MCP 서버에 연결한 상태에서 캡쳐.

| 페이지 | 미리보기 |
|---|---|
| 대시보드 | ![Dashboard](images/01-dashboard.png) |
| 케이스 detail | ![Case detail](images/05-case-detail.png) |
| 엔진 inspector | ![Engine inspector](images/06-engine-inspector.png) |
| 프로세스 다이어그램 | ![Process diagram](images/04-process-diagram.png) |
| 감사 추적 | ![Audit trail](images/07-audit-trail.png) |

---

## 다음 읽을 곳

- **[운영자 가이드](operator-guide.md)** — 모든 UI 표면 주석: 각
  lifecycle 버튼이 무엇을 하는지, error callout 해석 방법, 엔진
  inspector, counterfactual replay, 자주 만나는 시나리오.
- **[운영 (백업 / DR)](operations.md)** — SQLite snapshot 패턴,
  Postgres `pg_dump`, audit-only 백업, 5단계 복원 smoke flow.
- **[GitHub 저장소](https://github.com/nuri428/ontorag-flow)** —
  소스, 이슈, 릴리스.
- **[아키텍처 & 마일스톤](https://github.com/nuri428/ontorag-flow/blob/main/CLAUDE.md)**
  — 전체 프로젝트 사양, anti-pattern, Open question과 결정의 진행
  기록.
