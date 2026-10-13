# Current Ownership / Handoff

> **상태: Current Ownership**  
> 기준: `develop` · 2026-09-17 Current Copilot 반영

이 문서는 각 담당자가 어디를 주로 수정하고, 다른 파트와 어떤 Contract에서 만나는지 정리합니다. 역할은 소유권을 명확히 하기 위한 기준이며 Review나 의견 제시를 제한하지 않습니다.

## 현재 담당 기준

| 영역 | 주 담당 | 주요 경계 |
| --- | --- | --- |
| Frontend / UI·UX | 황수빈 | `apps/web/**`, Figma ↔ Product API |
| Backend / API | 전진환 | `apps/api/app/**` Product Service/API |
| DB / Data | 정예린 | Schema, Migration, Supabase 공유 DB, data integrity |
| LLM/RAG Core + Evaluation | 김재현 | `apps/api/app/ai/**`, Core quality, 위험조항 9종 |
| AI Copilot + Integration | 이홍규 | `apps/api/app/copilot/**`, Product orchestration, Copilot evaluation/docs/integration |

AI Core / Copilot 역할 분리는 합의 완료 상태이며, 현재 `app/copilot/**`에는 실제 v3.1 Conversation·Orchestration·Document QA·Claim Validation·Guided Job 구현이 존재합니다.

## Handoff 원칙

- 담당자의 내부 구현보다 **Contract와 테스트 가능한 결과**를 넘깁니다.
- 다른 파트가 내부 파일을 직접 참조해야 한다면 먼저 공개 Contract/API 추가를 검토합니다.
- 작업 완료는 구현만이 아니라 Test/문서 갱신까지 포함합니다.
- 영향이 큰 변경은 관련 담당자 Review를 요청합니다.
- Breaking Change는 관련 담당자에게 먼저 영향 범위를 공유합니다.

## 주요 파트 간 Handoff

```text
DB/Data
  ↓ Schema / persisted state
Backend Product Service
  ↓ current case / version / judgment / profile snapshot
Frontend Product Workspace

Backend extracted_blocks
  ↓
AI Core
  ↓ Requirement / Evidence / Risk Clause category
Backend Judgment / Revalidation / persistence
  ↓
AI Copilot Product Tool Adapter
  ↓ Fact / Source / Claim validation
Frontend Copilot Panel
```

### AI Core → Product → Copilot 경계

- AI Core는 Requirement/Evidence/위험조항 구조화를 담당합니다.
- Backend/Product는 현재 Case/Version과 저장 Judgment/Revalidation을 소유합니다.
- Copilot은 이 결과를 읽어 설명하고 별도 Qualification Rule을 만들지 않습니다.
- Copilot Document QA의 Hybrid Retrieval은 공개 공고문 질문용이며 Core Requirement Extraction Retrieval과 별도입니다.

### 위험조항 Contract

```text
김재현 AI Core
→ 위험조항 9종 category + 근거
→ Backend는 category를 재분류하지 않고 저장
→ Frontend는 사용자용 Label로 표현
```

### Copilot ↔ Frontend Contract

Current 주요 연결:

```text
GET  /api/v1/copilot/jobs
POST /api/v1/copilot/chat
POST /api/v1/copilot/actions/confirm
```

- Guided Job 2종 / 질문 6개의 범위·순서·완료기준은 서버가 소유합니다.
- Current Frontend는 자유 입력과 Guided Job을 함께 제공합니다.
- `response_version=3.1` 경로의 AnswerEnvelope/Source를 Frontend가 렌더링합니다.
- Action Proposal과 실제 Confirm을 구분하며 자연어 동의만으로 write하지 않습니다.

## 05 평가 대응

`/evaluation` Route는 존재하지만 EvaluationCriterion 전용 Product pipeline은 별도 완성 범위로 남아 있습니다.

- 점수 예측은 현재 범위 제외
- 자격 Requirement와 평가기준을 같은 데이터로 오표기하지 않음
- 기존 Proposal 업로드·Parsing·누락검사 자산은 재사용 가능성을 보존

## Branch 기준

모든 신규 작업은 최신 `develop`에서 Branch를 분기합니다.

예시:

```text
develop
├─ feat/... frontend
├─ feat/... backend
├─ feat/... data
├─ feature/... llm-core
├─ feature/... ai-copilot
└─ docs/... documentation
```

기능·문서 변경은 Pull Request를 통해 `develop`에 반영하고, `main` 반영은 별도 통합 판단으로 관리합니다.

## Handoff 체크리스트

PR 전 다음을 남깁니다.

- 무엇을 변경했는가
- 공개 Contract/API가 바뀌었는가
- 다른 담당자가 이어서 해야 할 일
- 실행/테스트 방법
- Known limitation
- Migration / env 변경
- 문서 갱신 위치
- 평가 수치라면 분모·fixture·범위·독립성 여부

## 현재 공통 다음 단계

- Frontend: 전체 Human Click E2E / 접근성 / 실제 사용자 피드백 반영
- Backend: API 경계·오류·도메인 모듈 고도화 / 배포·권한 정책
- DB: 공유 DB Migration 정합성 / provenance / Golden data 확대
- AI Core: 실제 데이터 Requirement Extraction/Retrieval/Evidence Evaluation + 위험조항 9종
- Copilot: 새 independent blind set / Stage 11 사람 사용자 평가 / 실제 모델 latency 개선 / durable Conversation 필요성 검토
- Integration: 실제 운영 데이터 전체 E2E와 Production Smoke, 최종 발표·제출 문서 고정

상세 Copilot Current는 [`../03_ai/ai-copilot.md`](../03_ai/ai-copilot.md), 평가 결과는 [`../08_qa_reports/ai-copilot-final-evaluation.md`](../08_qa_reports/ai-copilot-final-evaluation.md)를 참고합니다.
