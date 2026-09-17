# 프로젝트 문서 안내

> **문서 상태: Current**  
> 기준 브랜치: `develop` · Product Integration Baseline 이후 Copilot Current 문서까지 반영

이 문서는 `docs/`의 탐색 순서와 문서 상태를 안내하는 색인입니다. 과거 Baseline 문서와 현재 운영 문서를 구분해, 계획 문구를 현재 구현 사실처럼 읽지 않도록 합니다.

## 문서 상태

| 상태 | 의미 |
| --- | --- |
| **Current** | 현재 `develop` 코드·제품 운영에 적용되는 기준 |
| **Proposed** | 담당자/팀 합의 또는 코드 검증 전 설계안 |
| **Baseline Snapshot** | 특정 통합 시점의 재현·비교·인수인계 기준 |
| **Historical** | 당시 작업·초기 설계·과거 운영 기록 |
| **Superseded** | 후속 결정이나 최신 문서로 대체됨 |

## Source of Truth

| 대상 | 기준 |
| --- | --- |
| 실제 동작·Schema·상태 | **Code / Test** |
| 현재 기술 구조·실행·Contract | **GitHub `docs/`** |
| Copilot Current 구조 | **`docs/03_ai/ai-copilot.md`** |
| Copilot 개선·평가 요약 | **`docs/08_qa_reports/ai-copilot-final-evaluation.md`** |
| 기획 배경·논의·회의 맥락 | **Notion** |
| 현재 작업·담당·진행 상태 | **GitHub Projects / Issue** |
| 중요한 기술 결정 | Notion Decision Log → 안정화 후 ADR |

> Notion 문서를 그대로 복사해 Current 문서로 사용하지 않습니다. 현재 `develop`의 코드와 테스트를 대조해 실제 구현 기준으로 정제한 내용만 GitHub docs의 Current 기준으로 둡니다.

## 먼저 읽을 문서

1. [프로젝트 README](../README.md)
2. [Product 기준선](01_product/README.md)
3. [Architecture 기준선](02_architecture/README.md)
4. [AI Copilot · Current Architecture](03_ai/ai-copilot.md)
5. [AI Copilot · Final Evaluation Narrative](08_qa_reports/ai-copilot-final-evaluation.md)
6. [Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability](02_architecture/feature-traceability.md)
7. [AI / RAG 문서 안내](03_ai/README.md)
8. [AI Retrieval Current State](03_ai/retrieval-current-state.md)
9. [Backend / API 기준선](04_contracts/backend-api.md)
10. [Backend API Catalog](04_contracts/backend-api-catalog.md)
11. [Data / DB 기준선](04_contracts/data-and-db.md)
12. [DB ERD · Current](04_contracts/db-erd-current.md)
13. [Frontend / UI·UX 기준선](05_ui_ux/README.md)
14. [Frontend Screen · Component · API Contract](05_ui_ux/frontend-screen-contract.md)
15. [현재 Ownership / Handoff](07_handoff/current-ownership.md)
16. [Local Run / Operations Runbook](07_handoff/runbook.md)
17. [QA / E2E 기준](08_qa_reports/README.md)
18. [Requirement ↔ Test ↔ Golden/E2E Traceability](08_qa_reports/requirement-test-traceability.md)
19. [Post-Baseline Roadmap](09_roadmap/README.md)
20. [Product Integration Baseline Snapshot](mvp-baseline/README.md)

## 현재 문서 체계

```text
docs/
├─ README.md
├─ 01_product/
│  └─ README.md
├─ 02_architecture/
│  ├─ README.md
│  └─ feature-traceability.md
├─ 03_ai/
│  ├─ README.md
│  ├─ ai-copilot.md                 # Current Copilot
│  ├─ parallel-boundary.md
│  ├─ core-copilot-contract.md      # 초기 Proposed/Historical
│  └─ retrieval-current-state.md    # AI Core Retrieval
├─ 04_contracts/
│  ├─ backend-api.md
│  ├─ backend-api-catalog.md
│  ├─ data-and-db.md
│  └─ db-erd-current.md
├─ 05_ui_ux/
│  ├─ README.md
│  └─ frontend-screen-contract.md
├─ 06_decisions/
│  └─ README.md
├─ 07_handoff/
│  ├─ current-ownership.md
│  ├─ runbook.md
│  └─ ai-copilot-v3.1/              # 감사·설계·구현·통합 Historical Evidence
├─ 08_qa_reports/
│  ├─ README.md
│  ├─ ai-copilot-final-evaluation.md
│  ├─ ai-copilot-v1-evaluation.md
│  ├─ ai-copilot-v2/                # E0→E3 평가 원본
│  └─ requirement-test-traceability.md
├─ 09_roadmap/
│  └─ README.md
├─ llm-rag/                         # 초기 LLM/RAG 작업·설계 Historical
├─ mvp-baseline/                    # 기존 Snapshot 보존
├─ contracts/                       # 초기 계약 문서 보존
└─ parallel-development.md
```

## 문서 역할

- `README.md`: 빠른 탐색과 상태만 제공
- Current Architecture/Traceability/Contract/ERD/Catalog: 현재 구현 기준과 영향 범위
- `08_qa_reports`: 수치·평가 조건·실패 원인·전후 비교
- `07_handoff/ai-copilot-v3.1`: 감사와 구현 재검증의 상세 증거
- `llm-rag`: 초기 설계와 개발 과정 Historical
- `mvp-baseline`: 과거 통합 기준선 Snapshot
- Notion: 제품 배경, 회의, 결정, Planning 원문

## Copilot 문서 읽는 순서

평가자가 Copilot만 확인할 경우 다음 순서를 권장합니다.

```text
03_ai/ai-copilot.md
→ 08_qa_reports/ai-copilot-final-evaluation.md
→ 08_qa_reports/ai-copilot-v2/README.md
→ 07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md
→ 07_handoff/ai-copilot-v3.1/52-two-job-integration-result.md
```

`core-copilot-contract.md`, `llm-rag/08-chatbot-design-notes.md`, `ai-copilot-stage6-2-to10.md`는 현재 구현 계약이 아니라 **어떻게 설계가 발전했는지 보여주는 Historical 자료**로 읽습니다.

## Product Integration Baseline 이후 현재 핵심 후속 작업

- AI Core Requirement Extraction/Evidence의 실제 Golden 정량평가
- Copilot 새 독립 blind 질문셋
- Copilot 사람 사용자 Test Case 실제 수행
- v3.1 / Guided Job 실제 모델 latency 개선
- process-memory Conversation의 durable storage 필요성 검토
- meaningful 변경공고 G2 및 전체 Human Click E2E
- Production Deployment 구조 확정 및 Smoke Test

## 문서 갱신 규칙

- Contract 또는 Architecture가 바뀌면 관련 코드 PR에서 docs도 함께 수정합니다.
- Copilot 구조 변경 → `03_ai/ai-copilot.md` 확인
- Copilot 평가 변경 → `08_qa_reports/ai-copilot-final-evaluation.md` 확인
- API 변경 → `backend-api-catalog.md` 확인
- DB/Migration 변경 → `db-erd-current.md` 확인
- Route/Component/상태 변경 → `frontend-screen-contract.md` 확인
- Requirement/Rule/Askability 정책 변경 → `feature-traceability.md`, QA Traceability 확인
- AI Core Retrieval/Extraction 변경 → `retrieval-current-state.md`, Golden/Evaluation 갱신
- 논의 중인 설계는 `Proposed`로 표시하고 합의·구현 전 Current라고 쓰지 않습니다.
- Historical 문서의 당시 수치를 최신 Current 사실로 덮어쓰지 않고 상위 Current 문서에서 상태를 구분합니다.
- 실제 Task 일정/담당/Status를 docs에 중복 관리하지 않고 GitHub Projects/Issue를 사용합니다.
