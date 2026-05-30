# 철학: BPM ↔ ACM, by design

ontorag-flow는 *LLM 시대를 위한 워크플로우 엔진*입니다. 이 페이지는
BPM 관점에서 *이상하게 보이는* 결정들의 long-form rationale입니다.

## 스펙트럼, 구체적으로

```
   BPM (prescriptive)           ←—— spectrum ——→        ACM (adaptive)
   ─────────────────                                    ────────────
   Camunda / Activiti                  ontorag-flow              CMMN / Palantir
                                          ↑
                                  default: ACM-leaning
```

같은 runtime — `CaseManager` + `ActionExecutor` + audit store — 가 양
끝을 모두 실행합니다. 다이얼은 프로세스 YAML에 있습니다:

| YAML이 다음을 가지면… | 케이스 동작 |
|---|---|
| `engine: rule`, 모든 규칙 `confidence: 1.0`, 모든 액션 `constraints.immediately_after` chain, 완전한 `skeleton` | PROV-O를 기록하는 *엄격한 state machine* |
| `engine: rule`, 일부 confidence < 1, 부분 `skeleton`, 안전용 `requires` | 추천-후-확인 워크플로우 (기본) |
| `engine: llm` / `causal`, `skeleton` 없음, `allowed_actions` + `goal`만 | 자유 형식 적응형 케이스, reasoning 기반 |

재구현하지 않고 *튜닝*합니다. ACM으로 시작해서 happy path가 검증된
케이스는 *constraints 추가*로 strict로 졸업할 수 있습니다 — 재작성 아닙니다.

## 세 가지 아키텍처적 통찰

### 1. LLM이 결정자이지 오케스트레이터가 아니다

전통적 BPMN은 *그래프*를 결정자로 취급 — gateway가 "if invoice > $X
then approval lane"을 인코딩. 이게 작동한 이유는 *어떤 소프트웨어도
case state + 액션 카탈로그를 읽고 옳은 다음 행동을 고를 수 없었기*
때문. 신뢰할 만한 LLM은 이제 정확히 그것을 합니다.

LLM이 결정자가 되면, pre-baked BPMN 그래프는 *결정자 부재의 대용품*
입니다. 녹습니다: 새 예외마다 새 gateway, 새 정책마다 재배포. ACM은
LLM이 가짜로 흉내내지 않고 *실제로* 결정자가 되게 합니다.

오케스트레이터의 일은 다음으로 좁혀집니다: LLM에 case state 제시,
coherent한 것 강제 (ontology + `constraints`), 선택된 액션 실행, 모든
것 감사. `CaseManager`가 정확히 그것을 합니다.

### 2. 온톨로지가 가드레일이지 spec이 아니다

BPMN gateway는 *온톨로지가 이미 아는 것*을 재선언합니다: "Order가
`paid` 상태면 PaymentConfirmed 이벤트 후에만 `shipped`로 transition
가능". 온톨로지는 TBox 클래스 + 관계 + DL 제약으로 한 번 말합니다;
BPMN은 다른 syntax로 다른 곳에 다시 말합니다.

ontorag-flow는 온톨로지가 가드레일이게 둡니다:

- **액션이 클래스에 앵커링** — `AssertTriple`은 ABox에 쓰고 스키마가
  검증; 자유 떠도는 액션 없음.
- **`allowed_actions`이 메뉴** — 엔진은 YAML이 허용한 것만 제안 가능;
  YAML은 도메인 온톨로지에서 의미 있는 것만 허용 가능.
- **`AssertTriple`은 ontorag 통해 씀** — ABox 일관성은 *거기서* 강제,
  여기서 중복 안 함.

결과: 프로세스 정의가 *얇아짐*. 어려운 의미론은 *그게 속한 곳*인
온톨로지에 있음.

### 3. Goal-driven이 LLM 사고와 일치

LLM에 목표를 — `diagnosed: true` — 와 액션 카탈로그를 주면 forward
reasoning. "현재 node 5에 있고 node 7과 9로의 transition이 enabled"라고
말하면 *의학적 reasoning과 무관한 부기*를 시키는 것.

CMMN도 우연히 같은 방식 — goal-driven + allowed actions + sentries.
우연이 아닙니다; 두 아키텍처 모두 *작업이 적응형인 것*을 최적화하지
*다이어그램이 예쁜 것*을 최적화하지 않습니다.

## Provenance, BPM의 강한 주장에 대한 답

BPM의 가장 강한 주장은 *replayability* — "BPMN 다이어그램을 열면
무엇이 일어났는지, 무엇이 일어났어야 하는지, 어디서 이탈했는지 정확히
볼 수 있다". ACM의 전통적 약점은 정확히 이것: "적응형"이 때로 "모든
이벤트를 읽지 않으면 케이스가 뭘 했는지 알 수 없다"를 의미.

ontorag-flow는 provenance를 **non-optional**로 만들어 그 주장을
무력화합니다:

- **실행 액션당 PROV-O activity** — agent / inputs / outputs /
  `wasInformedBy` chain / `state_before` snapshot. 모든 액션, 항상.
- **Write-ahead audit (premortem P7)** — externally-visible 부수효과의
  경우 `pending` 행이 액션 실행 *전에* 기록; status는 실행 후
  `completed` / `failed`로 flip. 실행 중 crash해도 forensic 기록 남음.
- **`engine.explain()` trace** — RuleEngine은 어느 규칙 발화 기록;
  BayesianMpe는 posterior breakdown 기록; LlmAgent는 정확한 prompt +
  raw reply 기록; Causal은 intervention payload 기록. "왜"가 "무엇"과
  함께 살아있음.
- **Skeleton deviation 태그** — 프로세스가 happy-path `skeleton`을
  선언하면, path 이탈 실행은 activity metadata에
  `deviated_from_skeleton: true` + `skeleton_expected: <uri>` 받음.
  적응형 *과 함께* tail length를 셀 수 있음.
- **Counterfactual replay** (causal 엔진 + ontorag v0.8+) — Pearl
  Rung 3: 실제 case state-before snapshot에 대해 "Y였다면 step X에서?"

거래: 적응형 *과 함께* 완전한 forensic recall. "무엇이 일어났는지
재구성 못함" 변명 없음. 이건 design principle이지 open question 아님.

## 여전히 배제하는 것

- **BPMN 2.0 XML interchange** — Camunda 있음; 그 modeller나 token
  execution을 재구축 안 함. 도메인이 *실제로* 시퀀스 기반이고 이미
  BPMN 엔진이 있다면, `EXTERNAL_API` 액션으로 래핑하고 ontorag-flow가
  그 주위에서 ground/audit/orchestrate.
- **Token 기반 실행** — runtime authority는 `DecisionEngine`이지,
  그래프를 행진하는 token이 아님.
- **시각적 그래프 에디터** — 프로세스는 텍스트 (YAML 또는 RDF).
  다이어그램은 데이터에서 *생성됨* (`/ui/processes/<uri>/diagram` 참조);
  데이터는 다이어그램에서 생성되지 *않음*.

## 이게 열어주는 것

- v0 프로세스가 *ACM-leaning으로 시작*. 팀이 어느 시퀀스가 stable,
  어느 게 예외인지 학습. Stable한 시퀀스가 `skeleton` +
  `constraints.immediately_after`를 *얻음*; audit log가 *추정 아닌
  획득*임을 증명.
- LLM proposer 추가가 프로세스 재작성 필요 없음 — `engine:`을 `rule`
  에서 `cascade` `[llm, rule, human]` 로 전환. 같은 프로세스 YAML, 새
  결정 전략.
- 도메인 전문가가 YAML에 `expectations:` 블록 추가하고 `process test`
  를 회귀 suite로 실행. 프로세스가 자체 테스트를 ship.

아키텍처는 *하나의 runtime, 스펙트럼의 여러 위치, 전체적으로
provenance*. 그게 설계입니다.
