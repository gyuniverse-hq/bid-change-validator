# AI Copilot · Current Architecture

> **상태: Current**  
> 문서 기준일: 2026-09-17 KST  
> 기준 브랜치/커밋: `develop` / `f56d3484e9c3ca1b1badbeafcda9bd5f057c65d5` (PR #151 병합 후)  
> 실제 동작의 최종 Source of Truth는 코드와 테스트입니다.

## 1. 한 줄 정의

AI Copilot은 **새로운 입찰 자격 판정기**가 아니라, 이미 계산·저장된 Product 결과와 현재 공고문 근거를 사용자가 자연어로 안전하게 탐색하도록 연결하는 **업무 보조 인터페이스**입니다.

핵심 원칙은 다음 한 문장으로 요약합니다.

> **판정은 Product/Rule이 담당하고, Copilot은 검증된 사실과 근거를 조회·설명·연결한다.**

## 2. 왜 별도 Copilot이 필요한가

기존 Product 흐름은 회사 Profile, 공고 Version, Requirement, Judgment, Evidence, Ask-back, 변경공고 Revalidation이 여러 화면과 API에 나뉘어 있습니다.

사용자는 실제 업무에서 다음처럼 묻습니다.

- 이 공고에 우리 회사가 참여 가능한가?
- 왜 미달 또는 확인 필요인가?
- 그 조건의 원문은 어디인가?
- 변경공고에서 무엇이 바뀌었고 우리 회사에 어떤 영향이 있는가?
- 입찰 준비에 필요한 서류·기한·방법은 무엇인가?
- 아직 무엇을 확인하지 못했는가?

Copilot의 목적은 이 질문을 새로 판정하는 것이 아니라, **현재 Case에 연결된 판정·회사정보 snapshot·공고 원문·변경 결과를 한 대화 흐름으로 묶는 것**입니다.

## 3. 현재 제품 위치

```text
사용자
  ↓
Frontend Copilot Panel
  ↓
POST /api/v1/copilot/chat
GET  /api/v1/copilot/jobs
POST /api/v1/copilot/actions/confirm
  ↓
Conversation / Guided Job / Planner
  ↓
Product Tool Adapter
  ├─ READ_JUDGMENT
  ├─ READ_PROFILE
  ├─ READ_CHECKS
  ├─ READ_DOCUMENT
  └─ READ_CHANGES
  ↓
EvidenceBundle
  ├─ Fact
  ├─ Source
  ├─ Coverage
  ├─ Conflict
  └─ Limitation
  ↓
Claim 생성·검증
  ↓
AnswerEnvelope v3.1
  ↓
근거가 연결된 답변 / 제한 / 후속 대상 / Action Proposal
```

Copilot은 `apps/api/app/copilot/**`에 별도 레이어로 존재하며 AI Core의 Requirement Extraction이나 deterministic Qualification Rule을 대체하지 않습니다.

## 4. Current UI

현재 Product 화면에서는 Copilot Panel을 사용할 수 있으며 다음 두 방식이 함께 존재합니다.

### 4.1 검증된 추천 질문 6개

서버가 두 개의 업무 Job과 각 3개의 질문, 필요한 Tool, 완료 조건을 소유합니다.

#### Job A — 변경 공고 대응

1. `무엇이 바뀌었나요?`
2. `우리 회사에 어떤 영향이 있나요?`
3. `무엇을 확인해야 하나요?`

#### Job B — 입찰 참여 준비

1. `필요한 서류·기한·방법은?`
2. `준비 순서는?`
3. `아직 확인하지 못한 것은?`

UI는 `GET /api/v1/copilot/jobs`의 catalog를 렌더링하며 버튼 문구 자체가 임의의 Tool 실행 범위를 결정하지 않습니다. 각 질문의 `answer_scope`, `completion_criteria`, `required_tools`, 사용 가능 여부는 서버에서 정의합니다.

### 4.2 자유 입력

추천 질문과 별도로 현재 Panel에는 자유 입력창도 유지합니다.

```text
추천 질문 6개
      +
자유 입력
      ↓
response_version = 3.1
      ↓
현재 Case 범위 안에서 계획 → 조회 → 검증 → 응답
```

즉 PR #151 이후 Current는 **안내형 질문과 자유 입력의 통합 구조**입니다.

## 5. Conversation과 Context

Frontend는 현재 Copilot 요청을 `response_version='3.1'`로 전송합니다.

v3.1은 다음 정보를 분리해 관리합니다.

- `Scope`: case / company / notice / version / analysis / judgment
- `ConversationState`: conversation id, revision, messages, targets, facts, sources
- `Target`: `첫 번째`, `두 번째`, `그 조건`, `그 항목` 같은 후속 참조 대상
- `Fact`: 서버가 확인한 사실 또는 사용자 진술/가정
- `Source`: 문서·Product·대화 출처

중요한 안전 규칙:

- 과거 대화의 Fact를 현재 사실로 그대로 재사용하지 않습니다.
- 현재 Scope가 바뀌면 이전 target/fact/source를 해제합니다.
- 순번/대명사 대상이 모호하면 임의 선택하지 않고 clarification을 요구합니다.
- 이전 답변의 source ID가 현재 자료를 대신하지 않으며 필요한 Tool을 다시 조회합니다.

현재 서버 대화 저장은 **process-memory 기반**이며 서버 재시작 시 초기화됩니다. 단일 worker 전제를 포함하므로 durable conversation storage는 향후 과제입니다.

## 6. Guided Job과 자유 질문의 계획 방식

### Guided Job

검증된 6개 질문은 자유 텍스트 planner를 통하지 않고 서버가 고정한 `TaskPlan`을 사용합니다.

예를 들어 `우리 회사에 어떤 영향이 있나요?`는 다음 범위를 사용합니다.

```text
READ_CHANGES
+ READ_JUDGMENT
+ READ_PROFILE
```

이를 통해 사용자가 버튼 문구를 바꾸거나 모델이 과업 범위를 확대해도 회사 영향의 완료 조건이 흔들리지 않도록 합니다.

### 자유 질문

자유 입력은 질문을 최대 6개 Tool Task로 분해할 수 있습니다.

- 저장 판정
- 판정 당시 회사정보
- 남은 확인사항
- 현재 공고문
- 변경공고 비교
- 검토용 가정
- 실행이 필요한 경우에도 실제 실행이 아닌 Action Proposal

Planner가 실패해도 제한된 fallback plan을 사용하며, 자유 텍스트 계획이 직접 DB write를 실행하지 않습니다.

## 7. Fact / Source / Claim 분리

v3.1에서 가장 중요한 변화는 **모델이 작성한 문장과 서버가 확인한 사실을 분리**한 것입니다.

### Fact

```text
SERVER_RESULT
NOTICE_FACT
PROFILE_FACT
USER_ASSERTION
ASSUMPTION
```

### Source

```text
DOCUMENT
PRODUCT
TURN
```

### Claim Validation

생성 문장은 다음 상태 중 하나를 가집니다.

```text
SUPPORTED
CONTRADICTED
INSUFFICIENT
UNCHECKED
```

게시되는 `AnswerEnvelope.claims`는 실제 `fact_ids`와 `source_ids`에 연결됩니다. 검증에 실패한 주장을 전체 답변 성공으로 포장하지 않고 제외하거나 제한사항과 함께 PARTIAL로 반환합니다.

이 구조의 목적은 단순히 프롬프트에 `환각하지 마라`라고 쓰는 것이 아니라, **어떤 문장이 어떤 서버 사실과 원문을 근거로 하는지 구조적으로 추적하는 것**입니다.

## 8. 판정과 Document QA의 경계

Copilot에는 서로 다른 두 종류의 사실 경로가 있습니다.

### Product Judgment

회사 참가 가능 여부와 요건 상태는 기존 Product Judgment가 Source of Truth입니다.

```text
eligible | ineligible | insufficient_data
SATISFIED | UNSATISFIED | UNKNOWN
```

Copilot은 이를 새로 계산하지 않습니다.

### Public Document QA

공고문의 일반 내용·조항·제출조건을 묻는 질문은 현재 공고 Version의 공개 문서 조회를 사용할 수 있습니다.

현재 v3.1 `READ_DOCUMENT` 경로는 **Hybrid만 고정 사용하지 않습니다.** 현재 Version에서 검증된 Source snapshot과 index readiness를 먼저 확인한 뒤 질문 범위와 준비 상태에 따라 조회 전략을 선택합니다.

```text
현재 Notice Version의 검증된 Source snapshot
→ index readiness / fingerprint 확인
→ 일반 질문 + READY index
   → Hybrid Retrieval (Dense + BM25/RRF, k=4, fetch_k=12)
→ broad 질문
   → 검증된 current section을 넓게 조회
→ index/embedding 사용이 어려운 경우
   → lexical/current-section fallback
→ 질문 중심 exact excerpt
→ Fact / Source
→ Claim 생성·검증
→ AnswerEnvelope v3.1
```

채팅 요청 중 새 문서 index를 build하거나 문서 전체를 새로 embedding하지 않습니다. index 생성은 별도 사전 준비 작업이며, 현재 Source와 fingerprint가 맞지 않는 index를 묵시적으로 사용하지 않습니다.

회사 참가 가능 여부 질문이 Document QA로 들어오더라도 저장된 판정 경로를 우선합니다.

문서 조회에서 직접 뒷받침할 수 있는 Fact/Source를 확보하지 못하면 해당 문서 사실을 새로 만들어내지 않고 `NOT_FOUND` 또는 limitation으로 남깁니다. 최종 답변은 Product 사실을 포함한 전체 EvidenceBundle을 Claim 단위로 검증하므로, `검색 0건 = 모델 호출 자체를 항상 생략`으로 단순화하지 않습니다.

## 9. AI Core Retrieval과 Copilot RAG를 구분한다

프로젝트 안에는 서로 목적이 다른 Retrieval이 존재합니다.

| 영역 | 목적 | Current 접근 |
| --- | --- | --- |
| AI Core Requirement Extraction | 공고문에서 자격요건 후보 문맥 추출 | section-aware + keyword fallback baseline |
| Copilot v3.1 Document Read | 사용자 공고문 질문에 현재 Version 근거 조회 | READY narrow query는 Hybrid 우선, broad는 current sections, 필요 시 lexical fallback |

따라서 `프로젝트 전체 RAG = Hybrid` 또는 `AI Core가 Vector DB를 사용한다`고 표현하지 않습니다.

E3의 Dense/Hybrid/Rerank 비교는 **검색 전략 평가 결과**이며, Current v3.1의 모든 `READ_DOCUMENT` 호출이 항상 Hybrid만 사용한다는 의미가 아닙니다. 상세 평가는 [최종 평가 문서](../08_qa_reports/ai-copilot-final-evaluation.md)에서 별도로 설명합니다.

## 10. 외부 AI 처리 경계

현재 Panel에는 AI 처리 옵션을 분리해 표시합니다.

- **AI 상세 설명 사용**: 질문·관련 대화·현재 판정 결과·요건 상태와 필요한 회사정보를 설명용 AI 처리에 사용
- **공고문 근거 답변 사용**: 질문과 현재 공개 공고문을 외부 AI/Embedding 처리에 사용

두 옵션은 별도이며, Document QA 경로는 회사 Profile이나 저장 입력 전체를 문서 검색 입력으로 보내지 않습니다.

Copilot은 외부 AI 처리 여부와 관계없이 Product의 저장 판정 자체를 새로 생성하지 않습니다.

## 11. Write Safety

대화 API와 실제 실행 API를 분리합니다.

```text
/chat
→ 읽기 / 설명 / Action Proposal

/actions/confirm
→ 사용자의 명시 확인
→ 최신 case / company / version / analysis / judgment 재검증
→ 기존 Product Service 실행
```

핵심 규칙:

- 자연어 `응`만으로 저장하지 않습니다.
- Action Proposal은 실행 완료가 아닙니다.
- stale context를 성공으로 처리하지 않습니다.
- 저장 성공 여부가 불명확한 경우 자동 재실행하지 않습니다.
- Ask-back과 Revalidation은 기존 Product Service를 재사용합니다.

## 12. 개발 과정

Copilot은 한 번에 현재 구조로 만들어지지 않았습니다.

### Prototype — 판정과 서술 분리

초기 설계는 `판정은 코드, 서술은 모델` 원칙으로 시작했습니다. 화면과 모델이 같은 판정 브리핑을 보도록 하고, 모델이 판정기를 직접 호출하지 않도록 제한했습니다.

### v1 — Product Tool / Action 계약

기존 Judgment, Evidence, Ask-back, Revalidation을 Tool Adapter로 연결하고 Action Proposal과 Confirm을 분리했습니다.

### E1 — UX / bounded alias

자유입력의 단순 표현과 실패 UX를 보완했습니다. 의미 이해 문제를 키워드 추가만으로 끝내지 않고 다음 단계로 분리했습니다.

### E2 — Semantic Routing

Deterministic Router의 substring false positive를 측정하고, 모든 요청을 모델에 보내는 대신 **weak read만 Semantic Router가 재검토**하도록 했습니다.

### E3 — Document RAG / Prompt

Dense, Hybrid, Hybrid+LLM Rerank를 같은 평가셋에서 비교하고 **일반적인 준비된 index 검색의 기본 전략으로 Hybrid를 선택**했습니다. 이후 v3.1에서는 broad 질문과 index readiness까지 고려해 current-section/lexical fallback을 포함한 안전한 읽기 경계로 확장했습니다. Prompt는 무근거 Citation, 부분 근거 과잉결론, 문서 오류 임의 복원 문제를 v1→v4로 수정했습니다.

### v3.1 — Claim Validation

현재 구조는 Fact/Source/Claim을 분리하고 생성 문장을 검증한 뒤 지원되지 않는 주장을 제거하거나 PARTIAL로 반환합니다.

### Current — Guided Jobs + Free Input

최종적으로 변경공고 대응과 입찰 참여 준비라는 두 업무 Job의 6개 검증 질문을 추가하면서 자유 입력도 함께 유지했습니다.

## 13. Current 주요 코드

```text
apps/api/app/copilot/
├─ router.py                 # /jobs, /chat, /actions/confirm
├─ job_catalog.py            # 2 Job / 6 Question 서버 계약
├─ orchestration.py          # v3.1 조정자
├─ v31_contracts.py          # Scope / Fact / Source / TaskPlan / AnswerEnvelope
├─ tool_adapters.py          # Product read adapter
├─ answer_validation.py      # Claim validation / compose
├─ conversation_state.py     # process-memory conversation state
├─ document_qa.py            # 공개 공고문 Grounded QA
├─ semantic_router.py        # 의미 기반 intent 보조
├─ narration.py              # Product narration
├─ actions.py                # Proposal / confirm 연계
└─ change_impact.py          # 변경 영향 보조
```

Frontend 주요 연결:

```text
apps/web/components/copilot/
apps/web/lib/copilot-api.ts
apps/web/lib/copilot-conversation.ts
```

## 14. 알려진 한계

- process-memory 대화 상태는 서버 재시작 시 소멸하고 단일 worker를 전제로 합니다.
- 생성형 구조화 출력은 비결정적이므로 동일 질문도 COMPLETE/PARTIAL 사이에서 달라질 수 있습니다.
- 실제 모델 기반 안내 질문은 정확성·안전성 개선과 별개로 응답 지연이 큰 편입니다.
- Copilot 자동평가와 실제 사용자 업무 완료율은 동일한 지표가 아닙니다.
- 사람 사용자 테스트 계획은 존재하지만 최종 독립 사용자 결과는 아직 별도로 닫아야 합니다.
- AI Core Requirement Extraction 품질과 Copilot Document QA 품질은 별개로 평가해야 합니다.

## 15. 관련 문서

### Current / 평가

- [AI Copilot 최종 평가](../08_qa_reports/ai-copilot-final-evaluation.md)
- [AI Copilot v2 평가 원본](../08_qa_reports/ai-copilot-v2/README.md)
- [v3.1 구현·검증](../07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md)
- [Two-job 통합 결과](../07_handoff/ai-copilot-v3.1/52-two-job-integration-result.md)

### 설계 역사

- [Core → Copilot Contract](core-copilot-contract.md)
- [초기 챗봇 설계 노트](../llm-rag/08-chatbot-design-notes.md)
- [Stage 6-2 → 10](../08_qa_reports/ai-copilot-stage6-2-to10.md)
- [v3.1 현재 상태 감사](../07_handoff/ai-copilot-v3.1/01-current-state-audit.md)
- [v3.1 설계 결정](../07_handoff/ai-copilot-v3.1/02-audit-review-and-design-decisions.md)

## 16. 문서 갱신 규칙

Copilot 구조가 변경되는 PR에서는 최소한 다음을 함께 확인합니다.

- `GET /api/v1/copilot/jobs`의 Job/Question 계약
- `/chat` 및 `/actions/confirm` 계약
- Fact / Source / Claim / AnswerEnvelope 변경
- Conversation storage 방식
- Retrieval method / model / external-processing 범위
- Guided Job 완료 기준
- 평가셋·수치·회귀 결과
- 이 문서와 `ai-copilot-final-evaluation.md`의 Current 상태