# Backend / API Baseline

> **상태: Current**  
> 기준: `develop` · Copilot Current 기준 2026-09-17

이 문서는 현재 Backend/API의 책임과 주요 진입점을 정리합니다. 실제 Endpoint 목록과 주요 경계는 [Backend API Catalog](backend-api-catalog.md)를 함께 봅니다. 정확한 Request/Response 스키마는 코드와 Swagger가 최종 Source of Truth입니다.

## Backend 책임

- 회사 Profile 저장/조회
- 나라장터 Notice / Version / Document 저장 및 조회
- Preflight Case 관리
- Qualification Analysis 실행/조회
- Qualification Judgment 실행/조회
- Ask-back 질문/답변 및 부분 재판정
- 변경공고 Revalidation
- Profile → Notice Matching
- AI Copilot Case 접근권한·Product Tool 연계·Action confirm 경계
- 공통 오류 응답 및 상태 관리

## Router 등록 기준

`apps/api/app/main.py`에서 Product Router와 보호된 Copilot Router를 등록합니다.

주요 영역:

- Companies
- Master Codes
- Notices
- Preflight Cases
- Qualification Analysis
- Qualification Judgment
- Qualification Ask-back
- Qualification Revalidation
- Qualification Matching
- AI Copilot

## 공통 API 원칙

- API prefix는 `/api/v1`을 사용합니다.
- 공통 오류는 `ApiError` 형식으로 `{ error: { code, message, details } }`를 반환합니다.
- 요청 Validation 오류는 `422 INVALID_REQUEST` 형식으로 정규화합니다.
- 현재 Case / Company / Notice Version과 맞지 않는 오래된 Run을 그대로 재사용하지 않습니다.
- Analysis/Judgment/Answer/Revalidation의 Run lineage를 보존합니다.
- Copilot이 Product 결과를 조회할 때도 authorized Case Scope와 provenance를 다시 확인합니다.

## Qualification 관련 주요 흐름

```text
Preflight Case
  ↓
Qualification Analysis
  ↓
Qualification Judgment
  ↓
UNKNOWN
  ↓
Askability
  ↓
Answer + Partial Re-judgment
  ↓
Changed Notice
  ↓
Qualification Revalidation
```

상세 Endpoint: [backend-api-catalog.md](backend-api-catalog.md)

## Copilot 연계 원칙 · Current

AI Copilot은 Product Service와 승인된 read adapter를 우선 소비합니다. 다음 기능을 별도 구현하지 않습니다.

- 자격판정 재구현
- Ask-back Rule 재구현
- 변경공고 재판정 재구현
- DB 상태를 근거 없이 조합한 비공식 참가 판정

현재 Copilot API:

```text
GET  /api/v1/copilot/jobs
POST /api/v1/copilot/chat
POST /api/v1/copilot/actions/confirm
```

### Read / Explain

`/chat`의 Current Frontend 경로는 `response_version=3.1`을 사용합니다.

- 현재 authorized Case Scope를 기준으로 Product read를 수행합니다.
- Guided Job은 서버가 고정한 TaskPlan을 사용합니다.
- 자유 입력은 읽기 중심 계획을 구성하되 write를 직접 실행하지 않습니다.
- 서버 Fact/Source와 생성 Claim을 분리하고 검증된 범위만 AnswerEnvelope로 게시합니다.

### Document QA

공개 공고문 질문은 Product Judgment와 별도 경로입니다.

- 현재 Notice Version만 사용
- 명시적 외부처리 동의
- Hybrid Retrieval
- no-hit / no-citation fail-closed
- 회사 참가 가능 여부는 저장 Product Judgment 우선

### Write

실제 write는 `/chat`과 분리합니다.

```text
/chat → Action Proposal
/actions/confirm → 명시 확인 + 최신 provenance 검증 → 기존 Product Service
```

자연어 `응`만으로 저장·재검증하지 않습니다.

## Conversation State

v3.1 ConversationState는 현재 server process-memory 기반입니다.

- conversation id / context revision
- current Scope
- recent messages
- follow-up targets
- Fact / Source

이 구조는 durable Copilot session/history persistence API가 완성됐다는 의미가 아닙니다. 서버 재시작/다중 worker 지속성은 별도 과제입니다.

## Known Gaps / 고도화 후보

- API 도메인 파일이 `apps/api/app/` 최상위에 증가하고 있어 패키지 분리 여부 검토 가능
- Evaluation 전용 API 범위 미확정
- Copilot durable conversation persistence / multi-worker 전략 미확정
- 실제 모델 latency/observability 개선
- 운영 환경 인증/권한·배포 정책 별도 확정 필요

## 변경 체크리스트

- Response Schema 변경 여부
- 기존 Frontend 호환성
- Migration 필요 여부
- stale Run / Version 검증 유지 여부
- Error Code 변경 여부
- AI/Core Contract 영향
- Copilot Guided Job / Fact / Source / Claim / AnswerEnvelope 영향
- [Backend API Catalog](backend-api-catalog.md) 갱신 필요 여부
- [AI Copilot Current](../03_ai/ai-copilot.md) 갱신 필요 여부
- Swagger와 docs 동기화 여부
