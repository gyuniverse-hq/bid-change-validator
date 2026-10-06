# Frontend / UI·UX Baseline

> **상태: Current**  
> 기준: `develop` + Figma · Copilot Current 기준 2026-09-17

이 문서는 Frontend 고도화 시 화면 흐름, API 연결, 실패/빈 상태를 일관되게 유지하기 위한 기준선입니다. 상세 연결은 [Frontend Screen · Component · API Contract](frontend-screen-contract.md)를 함께 봅니다.

## 현재 Route

- `/notices`
- `/qualification`
- `/ask-back`
- `/evidence`
- `/evaluation`
- `/changes`
- `/company`

02~06은 같은 `caseId`를 공유하는 Workspace입니다.

## Source of Truth

- 화면 IA / 디자인 방향: Figma
- 실제 지원 기능 / 상태: `develop` 코드와 Backend API
- 화면 공통 Context/상태 표현: `case-workspace.ts`, `status-copy.ts`
- Copilot 현재 동작: `apps/web/components/copilot/**`, `apps/web/lib/copilot-*.ts`
- Figma와 구현이 다르면 이유를 문서 또는 Decision Log에 남깁니다.

## 구현 원칙

- `SATISFIED / UNSATISFIED / UNKNOWN`과 전체 `eligible / ineligible / insufficient_data`를 혼동하지 않습니다.
- `PARTIAL` Analysis와 `UNKNOWN` Judgment를 같은 상태로 합치지 않습니다.
- 최신 Analysis/Judgment와 연결된 데이터만 표시합니다.
- Loading / Error / Empty / Partial 상태를 명시적으로 처리합니다.
- Evidence는 실제 원문으로 이동할 수 있어야 하며 HWP/HWPX에 가짜 page를 만들지 않습니다.
- Evaluation 화면은 자격요건과 별도 평가기준을 혼동하지 않습니다.

## 상세 문서

- [Frontend Screen · Component · API Contract](frontend-screen-contract.md)
- [AI Copilot · Current Architecture](../03_ai/ai-copilot.md)
- [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md)
- [Feature Traceability](../02_architecture/feature-traceability.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## AI Copilot · Current UI

Copilot은 7개 화면을 대체하는 독립 ChatGPT clone이 아니라 **현재 Product Workspace의 Case Context를 사용하는 보조 Panel**입니다.

현재 주요 UI:

- `AI Copilot` Panel / 모바일 modal dialog
- 서버에서 불러오는 추천 질문 6개
- 자유 입력 textarea
- `AI 상세 설명 사용` 옵션
- `공고문 근거 답변 사용` 옵션
- 답변 근거 chip / Evidence 이동
- 후속 추천 질문
- 새 대화
- Loading / no-judgment / insufficient-evidence / error 상태

현재 추천 질문은 두 업무로 묶입니다.

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

추천 질문의 순서·범위·완료 기준은 Frontend가 임의 정의하지 않고 `GET /api/v1/copilot/jobs`의 서버 계약을 사용합니다.

## Copilot UI 안전 경계

- Panel은 현재 `caseId`를 사용합니다.
- 참가 가능 여부는 생성 답변이 아니라 저장된 Product Judgment를 기준으로 합니다.
- 원문 근거 답변과 AI 상세 설명의 외부처리 옵션을 분리합니다.
- 자연어 `응`만으로 write를 실행하지 않습니다.
- Action Proposal과 실제 Confirm을 구분합니다.
- Evidence source가 있으면 현재 Case/Analysis 기준으로 원문 화면에 연결합니다.
- stale/모호한 대상은 임의로 다른 요건에 연결하지 않습니다.

## Known Gaps

- 01~07 전체 Human Click E2E 최종 완료 필요
- Copilot 사람 사용자 Test Case 실제 결과 필요
- 접근성/키보드/스크린리더 전면 검증
- process-memory 대화가 서버 재시작 시 초기화됨
- 실제 모델 복합 응답 latency 개선
- 전체 저장소 lint debt와 Copilot 변경 파일의 품질을 구분해 관리

## 변경 체크리스트

- Figma와 차이 여부
- API Contract 영향
- Case/Version Context 유지 여부
- Loading/Error/Empty/PARTIAL 상태
- Evidence deep link
- Guided Job catalog/availability 변화
- Copilot 외부처리 안내 문구
- Action Proposal / Confirm 경계
- 기존 Product Component 재사용 여부
- 접근성 및 키보드 사용성
- `frontend-screen-contract.md` 갱신 필요 여부
- Copilot/Human E2E 시나리오 갱신 여부
