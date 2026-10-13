# Frontend Screen · Component · API Contract

> **상태: Current**  
> 기준: `develop` · Copilot Current 기준 2026-09-17

이 문서는 7개 Product Route가 어떤 공통 Context/API/상태 표현을 공유하는지 정리합니다.

## 1. Route Map

| Screen | Route | 핵심 역할 |
| --- | --- | --- |
| 01 | `/notices` | 공고 검색·선택·Profile Matching |
| 02 | `/qualification` | Analysis/Judgment 결과와 근거 요약 |
| 03 | `/ask-back` | ASKABLE UNKNOWN 응답 및 부분 재판정 |
| 04 | `/evidence` | Requirement Evidence 원문 대조 |
| 05 | `/evaluation` | 평가 대응 참고; 전용 extraction은 미완료 |
| 06 | `/changes` | Requirement Diff / Revalidation 결과 |
| 07 | `/company` | 회사 Profile 관리 |

02~06은 같은 `caseId`를 공유하는 Workspace입니다.

## 2. Case Workspace Contract

`apps/web/lib/case-workspace.ts`는 02~06 화면의 공통 데이터 로더입니다.

```text
caseId
→ PreflightCase
→ Notice + Versions
→ Company
→ current/baseline Analysis
→ current Analysis detail
→ source/display Judgment
→ Ask-back questions
```

중요한 안전 규칙:

- Judgment는 같은 `analysis_run_id`를 가리켜야 합니다.
- Judgment의 `notice_version_id`가 Analysis와 일치해야 합니다.
- Judgment의 `company_id`가 Case의 회사와 일치해야 합니다.
- 현재 화면은 호환되는 Rule 결과만 사용하고 stale 결과를 묵시적으로 섞지 않습니다.
- baseline/current version이 없으면 조용히 추측하지 않고 오류로 처리합니다.

즉 “가장 최근에 생성된 결과”를 무조건 화면에 쓰지 않습니다.

## 3. 상태 Copy Contract

`apps/web/lib/status-copy.ts`를 사용자 상태문구의 공통 기준으로 사용합니다.

### 개별 Judgment

```text
SATISFIED   → 충족
UNSATISFIED → 미달
UNKNOWN     → 확인 필요
UNJUDGED    → 미판정
```

### Basis

```text
PROFILE     → 회사 프로필 기준
USER_ANSWER → 귀사 답변 기준
NONE        → 근거 없음
```

### Analysis

```text
SUCCEEDED → 분석 완료
PARTIAL   → 일부만 읽었습니다
FAILED    → 첨부를 읽지 못했습니다
```

### Overall

```text
eligible          → 참가 가능
ineligible        → 참가 불가
insufficient_data → 확인 필요
```

`PARTIAL`은 `UNKNOWN`과 같은 상태가 아닙니다.

- `PARTIAL` = 문서 분석 자체의 완전성/diagnostic
- `UNKNOWN` = 특정 Requirement Judgment 상태

## 4. Evidence Location

Frontend는 page/clause를 임의 조립하지 않습니다.

우선순위:

```text
Evidence.location.display
→ clause_label
→ page (존재할 때만)
→ 아무 locator도 없으면 표시하지 않음
```

HWP/HWPX는 PDF page가 없을 수 있으므로 `p.null` 같은 가짜 위치를 만들지 않습니다.

## 5. Product Components

`apps/web/components/product/`의 주요 공통 부품:

| Component | 역할 |
| --- | --- |
| `app-header.tsx` / `app-footer.tsx` | 공통 Shell |
| `page-container.tsx` | Product 화면 폭/레이아웃 |
| `case-header.tsx` | 02~06 Case 탭/맥락 |
| `qualification-row.tsx` | Requirement + Judgment row |
| `qualification-source-overview.tsx` | Analysis source / diagnostic 요약 |
| `evidence-quote.tsx` | Evidence 원문 표시 |
| `conclusion-box.tsx` | 전체 결론/설명 |
| `cached-notice-matches.tsx` | 01 Profile Matching 결과 |
| `profile-records-manager.tsx` | 07 수행실적/인증 CRUD |

Copilot UI는 `apps/web/components/copilot/**`에 별도 보조 패널로 구현되어 Product 화면을 대체하지 않습니다.

## 6. Screen ↔ API

### 01 `/notices`

- Notices search/detail/version
- Companies
- Company notice matches
- Case create/list

### 02 `/qualification`

- Case workspace
- Qualification Analysis
- Qualification Judgment
- Qualification Questions
- Revalidation trigger/result

현재 02 화면은 필요 시 Analysis → Judgment를 실행하고 호환되는 Analysis/Judgment 관계를 확인합니다.

### 03 `/ask-back`

- Questions
- Answer
- result Judgment Run

답변 결과는 회사 Profile 영구 저장을 자동 전제로 하지 않습니다.

### 04 `/evidence`

- Analysis/Evidence
- document text/source/preview

### 05 `/evaluation`

현재 Product Route는 존재하지만 EvaluationCriterion 전용 Product pipeline은 미완료입니다. 자격 Requirement를 평가기준으로 오표기하지 않습니다.

### 06 `/changes`

- baseline/current Analysis
- Requirement changes
- Qualification Revalidation
- before/after Judgment

### 07 `/company`

- Company CRUD
- performance/certification
- profile completeness

## 7. Copilot UI · Current

Copilot은 7개 화면을 대체하는 독립 ChatGPT clone이 아니라 **현재 Case Context를 소비하는 보조 Panel**입니다.

```text
현재 Screen / caseId
→ Copilot Panel
→ GET /api/v1/copilot/jobs
→ POST /api/v1/copilot/chat (response_version=3.1)
→ Product Tool / Document QA
→ AnswerEnvelope / Sources
→ 필요 시 Evidence / Qualification / Changes 화면 이동
```

### 현재 Panel 기능

- 추천 질문 6개
- 자유 입력
- AI 상세 설명 사용 옵션
- 공고문 근거 답변 사용 옵션
- 후속 질문
- Source/Evidence Chip
- 새 대화
- 모바일 modal / 데스크톱 panel
- Loading / no-judgment / insufficient-evidence / error 상태

### Guided Job

Frontend는 질문 목록을 하드코딩해 Product 범위를 결정하지 않습니다. `GET /api/v1/copilot/jobs`가 현재 Case에 맞는 다음 정보를 제공합니다.

- Job / question ID
- 표시 label
- 순서
- answer scope
- completion criteria
- required tools
- AVAILABLE / BLOCKED 및 사유

### 자유 입력

`apps/web/lib/copilot-conversation.ts`는 현재 요청에 `response_version='3.1'`을 사용합니다. 자유 입력도 현재 authorized Case를 벗어나 임의 DB 상태를 조회하거나 write를 직접 실행하지 않습니다.

### 외부 AI 처리 옵션

- `AI 상세 설명 사용`: Product 사실을 자연어로 설명하는 모델 처리
- `공고문 근거 답변 사용`: 공개 공고문 검색/생성형 Document QA

두 옵션은 별도이며 Document QA를 회사 참가 가능 여부 판정기로 사용하지 않습니다.

### Action 경계

Copilot 응답의 Proposal과 실제 실행을 구분합니다.

```text
/chat → 설명 / Proposal
/actions/confirm → 명시 확인 후 실제 Product Service 실행
```

자연어 `응`만으로 저장 또는 재검증을 실행하지 않습니다.

## 8. Copilot ↔ Product Navigation

Copilot의 Product Evidence Source는 가능한 경우 `/evidence`의 실제 원문으로 이동합니다.

- 응답 당시 Analysis 기준을 유지합니다.
- 과거 분석의 Evidence를 현재 분석 Evidence처럼 자동 치환하지 않습니다.
- stale/모호한 target은 사용자에게 다시 선택하도록 합니다.
- 판정 없음/조회 실패를 참가 가능 또는 변경 없음으로 오표현하지 않습니다.

## 9. Frontend PR 체크리스트

- 같은 Case/Version Context가 유지되는가
- stale Analysis/Judgment가 화면에 섞이지 않는가
- enum이나 내부 Tool ID가 사용자에게 그대로 노출되지 않는가
- Loading/Error/Empty/PARTIAL이 구분되는가
- Evidence가 실제 원문까지 연결되는가
- Copilot Guided Job catalog와 UI 순서가 일치하는가
- 외부 AI 처리 동의 범위가 화면에서 구분되는가
- 자연어 동의가 write confirm으로 오인되지 않는가
- Figma 변경이라면 UX Source of Truth와 차이를 기록했는가
- 관련 Human Click / Copilot User Test를 갱신했는가

상세 Copilot 구조는 [`../03_ai/ai-copilot.md`](../03_ai/ai-copilot.md), 평가 흐름은 [`../08_qa_reports/ai-copilot-final-evaluation.md`](../08_qa_reports/ai-copilot-final-evaluation.md)를 참고합니다.
