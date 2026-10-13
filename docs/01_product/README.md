# Product 문서 안내

> **상태: Current**  
> 기준: `develop` + Figma 7개 화면 · Copilot Current 기준 2026-09-17

이 문서는 팀이 같은 사용자 흐름과 현재 범위를 보도록 하는 제품 기준선입니다. 상세 구현은 각 기술 문서에서 관리합니다.

## 제품 목표

원공고를 기준으로 준비한 자격판정과 근거를 확인하고, 변경공고 이후에도 기존 판단이 유효한지 Requirement 단위로 다시 검증합니다.

제품 Vision에는 공고 찾기·자격판정·계약 위험조항 확인·평가 대응·변경 재검증이 포함됩니다. 현재 Release Spine은 **Qualification + Evidence + Ask-back + Contract Risk Clause + Change Revalidation**이며, AI Copilot은 이 Product Spine의 결과와 공고문 근거를 자연어로 연결하는 보조 인터페이스입니다.

`05 평가 대응` Route는 존재하지만 EvaluationCriterion 전용 Product pipeline은 아직 별도 완성 범위로 보지 않습니다. **점수 예측은 현재 범위에서 제외**합니다.

## 현재 사용자 흐름

```text
회사 Profile
→ 공고 조회/선택
→ Preflight Case / 현재 Version
→ 문서 Parsing
→ Requirement Extraction + Evidence
→ deterministic Judgment
→ Askable UNKNOWN 해결
→ Evidence 원문 확인
→ 계약 위험조항 확인
→ 변경공고 Requirement Diff
→ affected-only Revalidation
        ↕
AI Copilot
→ 저장 판정 / 회사정보 snapshot / 확인사항 / 원문 / 변경 결과를 대화로 조회·설명
```

## 현재 화면 기준

| 순서 | Route | 역할 |
| --- | --- | --- |
| 01 | `/notices` | 공고 찾기 / 분석된 공고 후보 확인 |
| 02 | `/qualification` | 참가자격 분석·판정 결과 |
| 03 | `/ask-back` | 확인 가능한 UNKNOWN에 답변 |
| 04 | `/evidence` | 판정 근거 원문 대조 |
| 05 | `/evaluation` | 평가 대응 참고; 전용 EvaluationCriterion Product pipeline은 미완료 |
| 06 | `/changes` | 변경공고 Diff / 영향 확인 |
| 07 | `/company` | 회사 Profile 관리 |

02~06은 같은 `caseId`를 공유하며 Copilot Panel은 현재 Case Context를 사용합니다.

Figma는 화면 IA와 UX 방향의 Source of Truth이며, 실제 지원 기능과 상태는 `develop` 코드/API를 우선합니다.

## AI Copilot · Current Product Role

Copilot은 별도의 Qualification Rule을 만들지 않습니다.

현재 사용자에게 제공하는 두 업무 Job:

```text
변경 공고 대응
├─ 무엇이 바뀌었나요?
├─ 우리 회사에 어떤 영향이 있나요?
└─ 무엇을 확인해야 하나요?

입찰 참여 준비
├─ 필요한 서류·기한·방법은?
├─ 준비 순서는?
└─ 아직 확인하지 못한 것은?
```

이 6개 추천 질문과 자유 입력을 함께 제공하며, 서버가 Guided Job의 Tool 범위·완료 기준·사용 가능 여부를 관리합니다.

Copilot이 다루는 Product 사실:

- 현재 저장 판정 / 요건별 상태
- 판정 당시 회사정보 snapshot
- Askable/Manual 확인사항
- Requirement Evidence와 원문 위치
- baseline/current 변경과 저장 Revalidation 결과
- 현재 공고 Version의 공개 문서 근거

회사 참가 가능 여부는 Product Judgment가 Source of Truth이며 Document QA가 독자적으로 판정하지 않습니다.

상세: [AI Copilot · Current Architecture](../03_ai/ai-copilot.md)

## 계약 위험조항 · MVP Current

위험조항 검토는 MVP에 포함합니다. 현재 taxonomy는 9종입니다.

- `WARRANTY_PERIOD`
- `LATE_PENALTY`
- `LATE_PENALTY_RATE`
- `COPYRIGHT_OWNERSHIP`
- `ACCEPTANCE_CRITERIA`
- `SCOPE_AMBIGUITY`
- `TERMINATION_CONDITION`
- `PAYMENT_TERMS`
- `LIABILITY_SCOPE`

위험조항 `category`는 **AI Core가 분류**하고, Backend는 이를 별도 규칙으로 재분류하지 않고 저장하는 경계를 사용합니다. Frontend는 저장된 category를 사용자용 Label로 표현합니다.

## 초기 기획 ↔ Current 구현 Reconciliation

초기 Notion 문서는 제품 의도와 의사결정 배경으로 보존합니다. 아래 항목은 현재 구현 정책이 발전한 부분이므로 초기 문구를 그대로 재구현하지 않습니다.

| 초기 기획 표현 | Current 기준 |
| --- | --- |
| 자격 7유형 | Qualification Canonical 8유형 (`COMPANY_SIZE` 포함) |
| 🟢/🔵/🟡/🔴 4상태를 판정 상태처럼 사용 | 개별 `SATISFIED/UNSATISFIED/UNKNOWN` + `basis_type` + 전체 `overall_status`로 분리 |
| `confidence: low`이면 Ask-back | Superseded. `UNKNOWN != ASKABLE`; grounding/diagnostic/profile completeness/askability를 분리 |
| Ask-back 답변을 자동 Profile 저장 | 기본 `apply_to_profile=false`; `USER_ANSWER` 판정 근거로 사용 |
| RAG = Vector DB 전제 | AI Core Extraction은 section/keyword baseline, Copilot Document QA는 별도 Hybrid Retrieval |
| 05 Evaluation이 완성된 핵심 흐름 | Route는 존재하지만 전용 EvaluationCriterion Product pipeline은 미완료 |
| 위험조항 8종 | 현재 taxonomy 9종 |
| Copilot은 향후 추가 | Current 구현: v3.1 Conversation/Claim Validation + Guided Job 6문항 + 자유입력 |

## 기존 Proposal Preflight 기능

통합 전 Backend Prototype에 있던 제안서 업로드·Parsing·누락검사·원문 비교 기능은 폐기 대상으로 보지 않습니다. 현재 Product Contract와 평가 대응 범위에 맞춰 재사용 여부를 판단합니다.

## Demo / Golden 데이터 방향

- 데모 인증은 관리자 로그인 기준으로 진행합니다.
- 자격판정 Evaluation은 특정 회사 1개에 과적합되지 않도록 합성 회사 Profile 여러 개를 Golden Set에 사용합니다.
- 실제/합성 여부와 사용한 `company / notice / version / analysis / judgment run` 식별자를 함께 기록합니다.
- 남원 Demo 관련 Copilot Guided Job 평가에서는 합성 프로필 J13~J16의 실제 모델 격리 실행 기록을 사용하되 사람 사용자 결과와 구분합니다.

## 제품 불변조건

- LLM이 최종 참가 가능/불가를 직접 결정하지 않습니다.
- `UNKNOWN`은 곧바로 사용자 질문 가능 상태가 아닙니다.
- `PARTIAL` Analysis를 완전한 성공처럼 표현하지 않습니다.
- 변경 전 결과를 덮어쓰지 않고 Version / Run 단위로 추적합니다.
- 결과에는 추적 가능한 Requirement / Evidence가 연결되어야 합니다.
- 현재 회사 Profile과 과거 Judgment의 `profile_snapshot`을 구분합니다.
- AI Copilot은 기존 Product Judgment를 설명하며 별도 판정기를 만들지 않습니다.
- 생성 Claim은 확인된 Fact/Source 범위 안에서 게시하며 검증 실패는 PARTIAL/limitation으로 남깁니다.
- Copilot의 자연어 `응`만으로 저장/재검증하지 않고 명시 Confirm을 요구합니다.
- 위험조항 category는 Core 출력과 Backend 저장 경계를 분리해 이중 분류를 만들지 않습니다.

## 현재 고도화 포인트

- AI Core Requirement Extraction/Evidence 실제 Golden 정량평가
- 위험조항 9종의 실제 문서 Extraction/Evidence/API/UI 연결 고도화
- meaningful 변경공고 G2 확대
- 05 평가 대응 전용 Contract 정리
- 01→02→03→04→06 Human Click Golden Story
- Copilot 사람 사용자 Test Case 실제 수행
- Copilot 새 독립 blind 질문셋
- Copilot 실제 모델 latency 개선
- process-memory Conversation의 durable storage 필요성 검토
- Production Deployment 구조 확정 및 Smoke Test

## 상세 Current 문서

- [Architecture](../02_architecture/README.md)
- [Feature Traceability](../02_architecture/feature-traceability.md)
- [AI Copilot · Current Architecture](../03_ai/ai-copilot.md)
- [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md)
- [AI Retrieval Current State](../03_ai/retrieval-current-state.md)
- [DB ERD](../04_contracts/db-erd-current.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [Frontend Screen Contract](../05_ui_ux/frontend-screen-contract.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## 변경 체크리스트

제품 흐름 또는 화면 범위를 변경하는 PR에서는 다음을 확인합니다.

- Figma와 실제 Route 영향
- Backend/API/DB/AI/Copilot Contract 영향
- 초기 기획과 Current 정책 중 무엇을 변경하는지
- 기존 Case / Version / Analysis / Judgment lineage 호환성
- Copilot Guided Job / Fact / Source / Claim 영향
- Golden/E2E/User Test 시나리오 수정 필요 여부
- 중요한 범위 변경의 Decision Log/ADR 필요 여부
