# bid-change-validator

> Validates how changed public procurement notices affect existing bid qualifications, required documents, and submission readiness.

## Project

**나라장터 변경공고 대응형 입찰 제출 검증기**

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하고, 변경된 조건과 원문 근거를 바탕으로 영향을 받은 항목을 재검증하는 프로젝트입니다.

**Current Stage**  
`Topic Selected → MVP / User Flow / Architecture Design`

## Team

| Member | Initial Role |
| --- | --- |
| 김재현 | LLM / RAG |
| 이홍규 | LLM / RAG · Collaboration Infrastructure |
| 전진환 | Backend / Overall Structure |
| 정예린 | DB / Data Management |
| 황수빈 | Frontend / UI·UX |

> 역할은 2026-09-02 회의에서 정한 초기 역할 기준이며, 기능별 세부 책임은 Figma·프로토타입 검토 후 조정할 수 있습니다.

## Parallel Development Workspaces

주말 초기 병렬작업을 위해 Frontend / Backend / LLM·RAG workspace를 분리 운영합니다.

| Workspace | Owners | Repository |
| --- | --- | --- |
| Frontend | 황수빈 (Main), 이홍규 (Sub) | https://github.com/gyuniverse-hq/bid-change-validator-frontend |
| Backend / Data | 전진환 (Backend), 정예린 (DB / Data) | https://github.com/gyuniverse-hq/bid-change-validator-backend |
| LLM / RAG | 김재현, 이홍규 | https://github.com/gyuniverse-hq/bid-change-validator-llm-rag |

초기에는 빠른 구현과 실험을 우선하고, 영역 간 연결점은 아래 공통 문서에서 맞춥니다.

- 병렬 작업 가이드: `docs/parallel-development.md`
- Frontend ↔ Backend 계약 초안: `docs/contracts/frontend-backend.md`
- Backend ↔ LLM / RAG 계약 초안: `docs/contracts/backend-llm.md`

## Current Focus

- Figma 기반 핵심 User Flow 및 화면설계
- 초기 Backend / API / 데이터 흐름 프로토타입
- 나라장터 도메인 및 데이터 구조 검토
- LLM / RAG · Guardrail · Evaluation Harness 사전 검토
- Jira · GitHub · Notion 기반 협업 구조 적용

## Collaboration

기본 개발 흐름은 다음과 같이 운영합니다.

```text
Figma / Requirement
→ Jira Work Item
→ Branch
→ Pull Request
→ Review / Test
→ Merge
→ Jira Done
```

- `main`: 안정 버전 / 배포 기준
- `develop`: 통합 개발 브랜치
- 기능 브랜치: `feat/SKN34-XX-summary`, `fix/SKN34-XX-summary` 등
- 주요 변경은 Pull Request와 최소 1명 Review를 거칩니다.

## Documentation

세부 아키텍처, 기술 스택, 실행 방법, API·데이터 흐름, 평가 결과는 설계가 확정되는 순서대로 이 README와 `docs/`에 반영합니다.
