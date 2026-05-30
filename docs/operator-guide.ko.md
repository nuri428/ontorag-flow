# Operator guide

> **Audience.** People who run cases — not the people who define processes
> or wire decision engines. If you spend your day at
> `http://localhost:8100/ui/` reacting to what the engine recommends, this
> is for you.

---

## 케이스란

**케이스(case)** 는 **프로세스 정의(process definition)** 가 다스리는
하나의 장기 작업 단위입니다. "환자 한 명의 triage", "선적 한 건의
RCA", "온보딩 한 건" 이렇게 생각하면 됩니다. 프로세스는 *어떤 액션이
허용되는가* 를 정의하고, 케이스는 *그 한 번의 실행 상태* 입니다.

케이스가 수행하는 모든 액션은 **PROV-O activity** 로 기록됩니다 — 누가,
무엇을, 언제, 어떤 입력에 대해 실행해서 어떤 출력을 만들었는지. 감사
로그가 권위 있는 사본이고, 케이스의 history 뷰는 그것의 렌더링일
뿐입니다.

## 라이프사이클 상태

| Status      | 의미                                                     | 가능한 액션                                                              |
|-------------|----------------------------------------------------------|-----------------------------------------------------------------------|
| `open`      | 새 액션을 받음                                            | Execute, Suspend, Compensate, Spawn subcase, Execute top              |
| `suspended` | 정지 — 엔진 자동 실행 안 함, 사람도 액션 못 실행          | Resume, Compensate, Spawn subcase                                     |
| `closed`    | 목표 도달 (goal predicate이 true가 됨)                    | Compensate (닫힌 케이스도 되감음), Spawn subcase                       |
| `failed`    | 액션이 복구 불가능한 에러를 던짐                          | Compensate, Spawn subcase                                              |

## 세 가지 UI 페이지

## `/ui/` — 대시보드

- **케이스 표** — 상태(`all` / `open` / `suspended` / `closed` / `failed`)
  로 필터링. 각 행은 케이스 detail로 링크.
- **`Tick all timers` 버튼** — 열린 모든 케이스에서 만료된 `timer_events`
  를 휘둘러 해당 액션을 실행. cron이 죽었을 때 SLA-driven 액션이
  발화되지 않은 걸 발견하면 누르세요. redirect는 `Tick fired N timer
  event(s).` 메시지를 보여줍니다.
- **상태 필터** — 탭을 골라 뷰 범위 좁히기.

## `/ui/cases/<uri>` — 케이스 detail

운영 페이지입니다. 위에서 아래로:

- **헤더** — case URI, 현재 상태 badge, 생성/갱신 시각, 그리고 subcase인
  경우 **Parent** 링크.
- **Actions bar** — 현재 상태에서 의미 있는 버튼만 렌더링됩니다.
  mutating 버튼 네 개:
  - **`Suspend`** (open일 때만) — 케이스 일시정지. 사람이 조사하는
    동안 자동화를 멈추고 싶을 때.
  - **`Resume`** (suspended일 때만) — Suspend 취소; 케이스가 다시
    open.
  - **`Execute top proposal`** (open이면서 engine이 추천이 있을 때) —
    가장 confidence 높은 추천을 실행. rationale은 클릭 전에 proposals
    표에 보였습니다.
  - **`Compensate (undo all)`** (history가 비어있지 않을 때) — 모든
    액션의 compensation hook을 역순으로 실행해 `case.state` 를
    `initial_state` 로 되돌림. 닫힌 케이스도 compensate됩니다.
- **Spawn subcase** 폼 — 프로세스를 골라 자식 케이스를 만듬. 자식은
  `parent_uri` 로 부모와 연결되고, 자식이 닫히면 부모에 그 closure
  이벤트가 기록됩니다. "이 케이스에서 파생된 조사를 시작" 시 사용.
- **State** — 현재 `properties` dict과 `goal` predicate.
- **Decision engine proposals** — 엔진이 *지금 이 순간* 추천하는 것.
  confidence bar, params, rationale 포함 (또는 엔진이 필요한 backend
  — 예: ontorag MCP — 에 닿을 수 없으면 `Decision engine unavailable`
  callout).
- **Subcases** — 이 케이스에서 파생된 자식들. 각자 detail로 링크.
- **History** — 최근 activities. `full audit trail →` 링크로 감사
  페이지 이동.

## `/ui/cases/<uri>/audit` — 감사 추적

법의학(forensic) 페이지. 모든 PROV-O activity를 timestamp, agent,
입력(`used`), 출력(`generated`), 같은 케이스의 이전 activity
(`informed by`) 와 함께 보여줍니다. 각 행에 `Counterfactual` 링크.

## `/ui/cases/<uri>/explain` — Decision engine inspector

"왜?" 페이지. case detail의 `Decision engine proposals — why? →`
링크에서 도달. case detail에서 보는 동일한 proposals + 엔진의
`trace` dict를 보여줍니다:

- **RuleEngine** — 모든 규칙이 fired / unmatched / skipped-because-disallowed
  로 분류. *어떤* 규칙이 발화됐고 *왜 다른 규칙은 발화 안 됐는지*
  확인 가능.
- **BayesianMpeEngine** — target proposition + action → posterior
  map + 사용된 base evidence.
- **CausalSimulationEngine** — candidate별 intervention + posterior
  map (interventional, observational 아님).
- **LlmAgentEngine** — system + user prompt 전체, raw LLM 답변,
  파싱된 proposals 수 vs 반환된 수 (`max_proposals` cap). LLM
  출력이 잘못됐을 때 *파서가 뭘 빠뜨렸는지 vs LLM이 애초에 생성을
  안 했는지* 가 여기서 드러납니다.
- **StackedEngine** — proposer의 원래 confidence와 validator가
  rescored한 confidence를 나란히.
- **HumanReviewEngine** — "항상 사람에게 위임" 한 줄 policy.

엔진이 `explain()` 을 구현하지 않으면 proposals만 보이고 trace가
없다는 안내가 표시됩니다.

Trace는 엔진별 카드(규칙-발화 표, posterior breakdown 막대, prompt
collapsible, proposer-vs-validator 비교)로 렌더링되며, 원본 JSON은
항상 `Raw trace (JSON)` fold로 함께 제공됩니다 — 카드는 흔한 경우를
*읽기 쉽게* 할 뿐, 정보를 숨기지 않습니다.

## Counterfactual replay (Pearl Rung 3)

audit row의 **Counterfactual** 링크는
`/ui/cases/<uri>/counterfactual?swap=<activity>` 폼을 엽니다 — "그
액션이 다른 액션이었다면 목표에 대한 posterior가 어떻게 달라졌을까?"
를 묻는 폼입니다.

채워야 할 것:

- **Action** — 어떤 액션으로 바꿔 끼울지 (등록된 모든 액션 중; 기본은
  원래 액션).
- **Params (JSON)** — 바꾼 액션의 파라미터.

submit 시 일어나는 일:

- 케이스의 decision engine이 causal이면 (`engines/causal.py`),
  `manager.counterfactual(...)` 를 호출해 ontorag의 counterfactual MCP
  툴을 거쳐 posterior를 반환. 결과 표가 페이지 아래에 보임.
- 엔진이 rule/Bayesian/LLM/human이면 `CounterfactualError:
  counterfactual replay (need a CausalSimulationEngine)` callout. 상태
  변경 없음.
- JSON이 잘못됐으면 결과 자리에 `Invalid params JSON: ...`. 상태 변경
  없음.

Counterfactual은 **읽기-전용 작업** 입니다 — 재생해도 케이스나 감사
로그가 바뀌지 않습니다. 안심하고 실험하세요.

## Error callout 읽는 법

Mutating 버튼은 `POST → 303 redirect` 패턴입니다. 실패 시 redirect는
같은 페이지로 돌아오면서 query string에 `?error=ExceptionType: message`
가 붙어 빨간 callout으로 렌더링됩니다. 자주 보는 것들:

| Callout 메시지                          | 의미                                                       | 해결                                                                     |
|----------------------------------------|------------------------------------------------------------|--------------------------------------------------------------------------|
| `CaseStateTransitionError: ...`        | 누른 버튼이 현재 상태에 유효하지 않음                       | 새로고침 — 그 버튼이 더 이상 보이지 않을 것                              |
| `CaseNotFoundError: <uri>`             | URI 오타거나 케이스가 삭제됨                                | 대시보드로 돌아가 링크로 이동                                            |
| `ProcessNotFoundError: <uri>`          | Subcase 폼이 존재하지 않는 프로세스를 참조                  | 먼저 그 프로세스를 등록                                                  |
| `Engine returned no proposals.`        | 엔진이 지금 추천할 게 없음                                  | 상태가 이미 모든 규칙을 만족했을 수도; CLI/API로 액션을 직접 선택        |
| `Decision engine unavailable: ...`     | 엔진이 ontorag MCP나 LLM 클라이언트가 필요한데 연결 안 됨    | `connect_ontorag=true` 로 재시작하거나 `LLM_PROVIDER` 설정                |
| `CounterfactualError: ...`             | 이 케이스에 대해 counterfactual replay는 causal engine 필요 | 프로세스의 `engine:` 을 `causal` 로 (config-time 수정)                    |

## 자주 만나는 시나리오

## "실수로 실행된 액션을 되돌리고 싶다"

`Compensate (undo all)`. *마지막* 액션만 되돌리고 싶다면 그건 CLI
기능입니다 (`ontorag-flow case compensate <uri> --target-activity <uri>`);
UI의 Compensate 버튼은 항상 전부를 되돌립니다.

## "엔진이 위험한 걸 추천 — 자동 실행 전에 멈추고 싶다"

프로세스에 `auto_execute_top_proposal: true` 가 설정돼 있다면, 다음
tick 전에 `Suspend` 하거나, 프로세스를 `auto_execute_top_proposal:
false` 로 바꿔 사람이 매번 `Execute top proposal` 클릭하게 하세요.
(추천 기본값: 명시적 클릭)

## "timer-driven 액션이 발화 안 됨"

대시보드의 `Tick all timers`. `/cases/tick` 을 호출하는 cron이 살아있든
죽었든 작동. redirect가 몇 개 발화됐는지 알려줍니다.

## "이 케이스에서 파생된 조사를 따로 돌리고 싶다"

`Spawn subcase` 폼. 조사용 프로세스를 고르세요. 새 케이스는
`parent_uri` 로 이 케이스에 연결되고, 닫힐 때까지 이 케이스의
"Subcases" 섹션에 보입니다.

## "지난 주, X-ray 말고 lab을 먼저 했다면 어땠을까?"

케이스 감사를 열어 X-ray activity 행을 찾고 `Counterfactual` 클릭. lab
액션과 그 params를 선택. submit. posterior가 목표 확률이 얼마나
달라졌을지 알려줍니다.

## UI가 의도적으로 *하지 않는* 것

- **Activity 단위 Compensate.** UI 버튼은 항상 전부를 되돌립니다;
  선택적 undo는 CLI 전용.
- **프로세스 정의 편집.** 프로세스는 YAML/RDF 파일에서 로드됩니다;
  UI는 read-only. `ontorag-flow process load` 나 JSON API 사용.
- **Bulk operations.** "open된 모든 케이스 suspend" 같은 버튼 없음 —
  CLI/script 관심사.
- **버튼에 CSRF 토큰.** UI는 single-tenant 운영자 워크스테이션
  (`bind: 127.0.0.1` 이 기본) 용입니다. API를 public URL에 노출한다면
  auth를 강제하는 reverse-proxy 뒤에 두세요 — *그 단계를 빼지
  마세요*.
