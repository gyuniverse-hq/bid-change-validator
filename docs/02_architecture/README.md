# Architecture 문서 안내

> **상태: Current**  
> 기준: `develop` · Copilot Current 기준 2026-09-17

이 문서는 전체 제품 구조의 현재 연결과 책임 경계를 설명합니다. 상세 기능 영향은 [Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability](feature-traceability.md)를 함께 봅니다.

## System Overview

```text
Frontend (apps/web)
        ↓ HTTP
FastAPI (apps/api/app)
        ↓
Product Services
├─ Notice / Document
├─ Company Profile
├─ Preflight Case
├─ Qualification Analysis
├─ Qualification Judgment
├─ Ask-back
├─ Revalidation
└─ Matching
        ↓
PostgreSQL + Document Storage
        ↕
AI Core (app/ai)
        ↑
AI Copilot (app/copilot)
├─ Conversation / Scope
├─ Guided Job / Free-text Planning
├─ Product Tool Adapter
├─ Document QA
├─ Fact / Source / Claim Validation
└─ Action Proposal / Explicit Confirm
        ↑
Frontend Copilot Panel
```

## 주요 경계

### Frontend

- `apps/web/app/**`의 7개 주요 Route가 제품 IA를 구성합니다.
- 02~06은 같은 `caseId`를 공유하는 Workspace입니다.
- Backend API를 소비하고 Product 상태를 표시합니다.
- Copilot은 기존 화면을 대체하지 않고 현재 Case를 사용하는 보조 Panel로 동작합니다.

### Backend / Product Service

- FastAPI `main.py`에서 Companies, Master Codes, Notices, Preflight Case, Qualification Analysis/Judgment/Ask-back/Revalidation/Matching Router를 등록합니다.
- DB 저장·조회, 현재 Case/Version, 상태 전이를 소유합니다.
- 전체 참가 가능 상태와 개별 Requirement 판정의 Source of Truth를 소유합니다.

### AI Core

- 비정형 공고문에서 Requirement/Evidence를 생성하고 deterministic Rule 판정에 필요한 구조를 제공합니다.
- DB PK, HTTP 상태, 현재 공고 Version의 Source of Truth를 소유하지 않습니다.
- Qualification Extraction의 Current Retrieval baseline은 section/keyword candidate selection입니다.

### AI Copilot

- 기존 Product/Core 결과와 현재 공고문 Source를 대화형으로 조합합니다.
- Guided Job 2종 / 질문 6개와 자유 입력을 지원합니다.
- `/api/v1/copilot/chat`의 Current Frontend 경로는 `response_version=3.1`을 사용합니다.
- Product read를 `Fact / Source`로 수집하고, 생성 문장은 `Claim` 단위로 검증합니다.
- Document QA는 공개 공고문용 Hybrid Retrieval을 사용하지만 회사 적격 판정을 독자 생성하지 않습니다.
- `/chat`은 write를 직접 실행하지 않으며 실제 실행은 명시적 `/actions/confirm` 경로로 분리합니다.

### Data

- PostgreSQL을 운영 데이터 저장소로 사용합니다.
- 원본 문서는 Local Volume 또는 설정에 따라 S3-compatible storage로 확장 가능한 인터페이스를 사용합니다.
- Version/Run lineage는 과거 판정 재현과 변경 재검증의 핵심입니다.
- Copilot ConversationState는 현재 process-memory이며 durable DB history와는 구분합니다.

## Dependency Direction

```text
Copilot Panel / Product UI
          ↓
FastAPI / Copilot Orchestration
          ↓
Product Service / Approved Read Tools
          ↓
Domain Rule / AI Core / Document Source
          ↓
Data / External Provider
```

Copilot이 Core 내부 Retriever나 Qualification Rule을 다시 구현해 별도 판정 경로를 만들지 않도록 유지합니다.

## Retrieval 경계

프로젝트 내부의 Retrieval은 목적별로 구분합니다.

| 영역 | 역할 | Current |
| --- | --- | --- |
| AI Core Qualification Extraction | Requirement 후보 문맥 선택 | section-aware + keyword fallback |
| Copilot Document QA | 사용자 공고문 질문 근거 검색 | Dense + BM25 Hybrid / RRF |

`AI Core Retrieval`과 `Copilot Document QA`의 평가 수치와 기술 선택을 서로 섞지 않습니다.

## 상세 Current 문서

- [Feature Traceability](feature-traceability.md)
- [AI Copilot · Current Architecture](../03_ai/ai-copilot.md)
- [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [DB ERD · Current](../04_contracts/db-erd-current.md)
- [Frontend Screen Contract](../05_ui_ux/frontend-screen-contract.md)
- [AI Retrieval Current State](../03_ai/retrieval-current-state.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## 현재 주요 실행 구성

`docker-compose.yml` 기준:

- `db`: PostgreSQL 16
- `migrate`: Alembic migration 실행
- `api`: FastAPI
- `notice-poller`: 나라장터 변경공고 수집 Worker
- `master-data-import`: 업종/품목/기관 기준정보 적재 도구
- volumes: `postgres_data`, `notice_documents_data`

## Known Gaps

- `infra/`는 현재 실질 구현이 없는 상태이며 배포 구조가 확정되면 별도 문서로 승격합니다.
- API 도메인 모듈이 `apps/api/app/` 최상위에 증가하고 있어, 기능 확장 시 패키지 재구조화 여부를 검토할 수 있습니다.
- Copilot Conversation은 process-memory 기반이라 재시작/다중 worker 지속성이 없습니다.
- Copilot 실제 모델 복합 응답 latency 개선이 필요합니다.
- Copilot 사람 사용자 평가 결과와 전체 Human Click E2E는 아직 완료 기준이 닫히지 않았습니다.

## 변경 체크리스트

Architecture 변경 PR은 다음을 확인합니다.

- Source of Truth가 어느 레이어인지
- 새로운 의존 방향이 역전되지 않는지
- Product Judgment와 Document QA 경계가 유지되는지
- API/DB Contract 변경 여부
- Copilot Fact/Source/Claim 또는 Guided Job Contract 영향
- Migration 필요 여부
- Frontend Route/Panel 영향
- Test / Golden / E2E 영향
- `feature-traceability.md` 갱신 필요 여부
- ADR 작성이 필요한 결정인지
