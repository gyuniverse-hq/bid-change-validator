# Current Ownership / Handoff

> **상태: Proposed + Current 혼합**  
> 기준: `develop` 이후 병렬 고도화 단계

이 문서는 각 담당자가 어디를 주로 수정하고, 다른 파트와 어떤 Contract에서 만나는지 정리합니다. 역할은 소유권을 명확히 하기 위한 기준이며 Review나 의견 제시를 제한하지 않습니다.

## 현재 담당 기준

| 영역 | 주 담당 | 주요 경계 |
| --- | --- | --- |
| Frontend / UI·UX | 황수빈 | `apps/web/**`, Figma ↔ Product API |
| Backend / API | 전진환 | `apps/api/app/**` Product Service/API |
| DB / Data | 정예린 | Schema, Migration, data integrity |
| LLM/RAG Core + Evaluation | 김재현 | `apps/api/app/ai/**`, Core quality |
| AI Copilot + Integration | 이홍규 | 신규 `apps/api/app/copilot/**` 제안, Product API orchestration |

> AI Core / Copilot 세부 분리는 담당자 최종 합의 전 Proposed입니다.

## Handoff 원칙

- 담당자의 내부 구현보다 **Contract와 테스트 가능한 결과**를 넘깁니다.
- 다른 파트가 내부 파일을 직접 참조해야 한다면 먼저 공개 Contract/API 추가를 검토합니다.
- 작업 완료는 구현만이 아니라 Review/Test/문서 갱신까지 포함합니다.
- Breaking Change는 관련 담당자에게 먼저 영향 범위를 공유합니다.

## 주요 파트 간 Handoff

```text
DB/Data
  ↓ Schema / persisted state
Backend
  ↓ Product API / current context
Frontend

Backend extracted_blocks
  ↓
AI Core
  ↓ Requirement / Evidence
Backend Judgment / Revalidation
  ↓
Copilot / Frontend
```

## Branch 기준

모든 신규 작업은 최신 `develop`에서 Branch를 분기합니다.

예시:

```text
develop
├─ feat/... frontend
├─ feat/... backend
├─ feat/... data
├─ feature/llm-core-hardening
└─ feature/ai-copilot
```

정확한 Branch 명명은 팀의 현재 GitHub 운영 규칙을 따릅니다.

## Handoff 체크리스트

PR 전 다음을 남깁니다.

- 무엇을 변경했는가
- 공개 Contract/API가 바뀌었는가
- 다른 담당자가 이어서 해야 할 일
- 실행/테스트 방법
- Known limitation
- Migration / env 변경
- 문서 갱신 위치

## 현재 공통 다음 단계

- Frontend: Figma visual QA / Human Click E2E
- Backend: API 경계·오류·도메인 모듈 고도화
- DB: 실제 ERD / provenance / Evaluation 저장 구조 검토
- AI Core: 실제 데이터 Extraction/Retrieval Evaluation
- Copilot: Product API 기반 첫 ELIGIBILITY Vertical Slice
