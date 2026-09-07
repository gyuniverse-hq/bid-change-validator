# MVP Integration Baseline

> Branch baseline: `integration/mvp-baseline`  
> Purpose: 팀 전체 기능이 실제 제품 흐름으로 연결되는 공통 기준선을 먼저 확보하고, 이후 각 담당자가 같은 기준선 위에서 병렬 고도화하기 위한 문서입니다.

## Why this baseline exists

이 작업은 Frontend / Backend / DB / LLM·RAG 담당 영역을 대신 구현하는 작업이 아닙니다.

목표는 다음 한 문장으로 정의합니다.

> **MVP Integration Baseline을 먼저 만든다 → 전 구간이 실제로 연결되는 기준선을 확보한다 → 그 기준선을 각 담당자가 병렬로 고도화한다.**

따라서 Baseline 단계에서는 최종 품질보다 **계약, 식별자, 상태값, 근거 추적, E2E 연결성**을 우선합니다.

## Current repository snapshot

`integration/mvp-baseline`에서 현재 확인된 축은 다음과 같습니다.

### Already present

- `apps/web`: FastAPI와 연결되는 Frontend
- `apps/api`: FastAPI Backend
- `db`: migration / schema / seed 구조
- 나라장터 공고 수집, 공고 버전 관리, 첨부문서 저장 및 텍스트 추출
- PDF / HWP(HWPX) 원문·텍스트 조회 흐름
- Company Profile CRUD 및 업종/인력/실적/인증 데이터 구조
- Preflight Case 생성 및 제안서 업로드
- `app.ai` 내부 Qualification Requirement 분석 파이프라인
- Canonical Requirement 8종, Evidence, Judgment 계약 객체
- Frontend ↔ Backend / Backend ↔ LLM 초안 계약 문서

### Integration gaps to verify in Stage 2

아래 항목은 코드 일부가 존재하더라도 실제 API → DB → UI E2E 연결 여부를 아직 확정하지 않습니다.

- RequirementAnalysisResult 호출 경로와 저장 방식
- Canonical Requirement / Evidence 영속화 여부
- Company Profile 기반 Judgment 실행 경로
- `SATISFIED / UNSATISFIED / UNKNOWN`의 API/UI 집계 규칙
- UNKNOWN에 대한 Ask-back 질문·답변 저장·부분 재판정
- 변경공고 Version Diff → 영향 Requirement 탐지 → Revalidation
- Frontend의 판정 → 근거 → 해결 화면 연결

## Target integrated flow

```text
나라장터 공고 / 변경공고
        ↓
Notice + Version + Document 저장
        ↓
원문 텍스트 / Source Block 추출
        ↓
Qualification Requirement Analysis
        ↓
Canonical Requirement + Evidence
        ↓
Company Profile
        ↓
Judgment
SATISFIED / UNSATISFIED / UNKNOWN
        ↓
UNKNOWN이면 Ask-back → Answer 저장 → 부분 재판정
        ↓
변경공고 발생 시 Version Diff → 영향 항목 재판정
        ↓
Frontend
판정 → 근거 → 해결 → 변경이력
```

## Document index

1. [`01-scope-and-acceptance.md`](./01-scope-and-acceptance.md) — MVP 범위와 완료 기준
2. [`02-system-flow.md`](./02-system-flow.md) — 현재/목표 전체 시스템 흐름
3. [`03-screen-system-map.md`](./03-screen-system-map.md) — 화면 ↔ API ↔ DB ↔ AI 연결 맵
4. [`04-contract-and-status-map.md`](./04-contract-and-status-map.md) — Contract, Canonical Type, Status 기준
5. [`05-e2e-golden-path.md`](./05-e2e-golden-path.md) — E2E Golden Path와 회귀 기준
6. [`06-handoff-and-merge.md`](./06-handoff-and-merge.md) — 담당별 Handoff와 브랜치/머지 규칙

기존 문서는 유지하며 이 Baseline 문서가 상위 통합 기준으로 참조합니다.

- `docs/parallel-development.md`
- `docs/contracts/frontend-backend.md`
- `docs/contracts/backend-llm.md`
- `docs/contracts/rhwp-viewer.md`

## Full execution sequence

```text
0. integration/mvp-baseline 생성                    ✅ 완료

1. MVP Baseline 문서 기준선 반영                   ◀ 현재
   ├─ Scope / DoD
   ├─ 전체 System Flow
   ├─ 화면 ↔ API ↔ DB ↔ AI Map
   ├─ Contract / Status 기준
   ├─ E2E Golden Path
   └─ Handoff / Merge 규칙

2. 현재 코드 ↔ Contract Gap 검산
   ├─ Company Profile
   ├─ Canonical Requirement 8종
   ├─ Evidence
   ├─ Judgment
   ├─ Notice Version
   └─ 변경공고 Relation

3. MVP용 실제 E2E 데이터/시나리오 확정
4. Backend / DB Integration Spine 연결
5. Qualification Judgment 연결
6. Ask-back → 부분 재판정 연결
7. 변경공고 Diff → Revalidation 연결
8. Frontend 실제 데이터 연결
9. Baseline E2E / 회귀 테스트
10. 담당별 Handoff 작성
11. 팀원 전체 공유 / Review
12. integration/mvp-baseline → develop PR
13. develop 통합 검증 → main PR
14. 각 담당자 병렬 고도화
```

## Baseline rule

- `main`, `develop`에는 Baseline 작업 중 직접 반영하지 않습니다.
- 모든 통합 작업은 `integration/mvp-baseline` 하위 작업 브랜치에서 진행합니다.
- 실제 코드와 문서가 충돌하면 임의로 한쪽을 숨기지 않고 **Contract Gap**으로 기록한 뒤 Stage 2에서 확정합니다.
- AI가 만든 식별자가 Backend 원본 식별자를 대체하지 않습니다.
- 판정에는 가능한 한 원문 Evidence가 연결되어야 합니다.
- 정보가 부족한 경우 억지로 합격/불합격으로 확정하지 않고 UNKNOWN/Review 경로를 유지합니다.
