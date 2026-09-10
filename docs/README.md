# 프로젝트 문서 안내

> **문서 상태: Current**  
> 기준 브랜치: `develop` · Product Integration Baseline은 PR #75로 `develop`에 병합 완료되었습니다.

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
| 기획 배경·논의·회의 맥락 | **Notion** |
| 현재 작업·담당·진행 상태 | **GitHub Projects / Issue** |
| 중요한 기술 결정 | Notion Decision Log → 안정화 후 ADR |

> Notion 문서를 그대로 복사해 Current 문서로 사용하지 않습니다. 현재 `develop`의 코드와 테스트를 대조해 실제 구현 기준으로 정제한 내용만 GitHub docs의 Current 기준으로 둡니다.

## 먼저 읽을 문서

1. [프로젝트 README](../README.md)
2. [AI / RAG 문서 안내](03_ai/README.md)
3. [Product Integration Baseline Snapshot](mvp-baseline/README.md)
4. [Backend ↔ LLM/RAG 계약](contracts/backend-llm.md)
5. [Frontend ↔ Backend 계약](contracts/frontend-backend.md)
6. [초기 병렬 개발 가이드](parallel-development.md)

## 현재 폴더 안내

| 경로 | 상태 | 역할 |
| --- | --- | --- |
| `03_ai/` | Current + Proposed | AI Core, Copilot, 병렬 경계, Contract |
| `contracts/` | Current/Legacy 혼재 | 파트 간 API·데이터 계약 |
| `mvp-baseline/` | **Baseline Snapshot** | Product Integration Baseline 설계·Audit·Golden·Handoff 기록 |
| `parallel-development.md` | Historical | 초기 분리 Repository 기반 병렬 개발 운영 기록 |

## 목표 문서 체계

현재 문서를 한 번에 대규모 이동하지 않습니다. 기존 링크와 이력을 보존하면서 필요할 때 아래 목적별 구조로 점진적으로 승격합니다.

```text
docs/
├─ README.md
├─ 01_product/
├─ 02_architecture/
├─ 03_ai/
├─ 04_contracts/
├─ 05_ui_ux/
├─ 06_decisions/
├─ 07_handoff/
├─ 08_qa_reports/
├─ 09_roadmap/
├─ troubleshooting/
├─ assets/
└─ mvp-baseline/          # 기존 Snapshot 보존
```

아직 생성되지 않은 폴더는 **목표 구조**이며, 문서가 실제로 승격될 때 생성합니다.

## Product Integration Baseline 이후

PR #74에서 판정·Evidence·Case 일관성 안전성 보강을 수행했고, PR #75로 `integration/mvp-baseline`을 `develop`에 병합했습니다. 따라서 앞으로 신규 기능 Branch는 최신 `develop`을 기준으로 분기합니다.

현재 후속 핵심 작업은 다음입니다.

- 담당별 기능·품질 병렬 고도화
- LLM/RAG Core와 AI Copilot의 파일/Contract 경계 확정
- 실제 Extraction 품질 평가 및 Golden Set 확장
- meaningful 변경공고 시나리오 확보 및 Revalidation 검증
- 01~07 Human Click E2E 및 UI/접근성 검증

## 문서 갱신 규칙

- Contract 또는 Architecture가 바뀌면 관련 코드 PR에서 docs도 함께 수정합니다.
- 논의 중인 설계는 `Proposed`로 표시하고 합의·구현 전 Current라고 쓰지 않습니다.
- `mvp-baseline/`은 당시 통합 기준선의 Snapshot으로 보존하며 후속 상태를 소급해 다시 쓰지 않습니다.
- README는 상세 구현을 복제하지 않고 현재 상태와 탐색 경로를 제공합니다.
- 문서 하나는 가능한 한 하나의 책임만 갖게 유지합니다.
