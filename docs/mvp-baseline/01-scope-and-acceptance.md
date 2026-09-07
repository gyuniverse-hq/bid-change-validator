# 01. Scope and Acceptance

## 1. Baseline scope

MVP Integration Baseline의 목적은 모든 기능을 완성하는 것이 아니라 **한 개의 실제 제품 흐름이 Frontend → Backend → DB → AI/RAG → Backend → Frontend로 끝까지 이어지는 기준선**을 만드는 것입니다.

### In scope

- 나라장터 공고 조회 및 Version 식별
- 공고 원문/첨부문서와 추출 Source Block 사용
- Company Profile 생성·조회·수정
- Qualification Requirement 분석
- Canonical Requirement 8종과 Evidence 연결
- Company Profile과 Requirement를 이용한 판정
- Requirement 단위 `SATISFIED / UNSATISFIED / UNKNOWN`
- UNKNOWN에 대한 Ask-back
- Answer 저장 후 영향 Requirement만 재판정
- 변경공고 발생 시 이전/현재 Version 비교
- 변경된 Requirement의 영향 범위 재판정
- Frontend에서 판정 → 근거 → 해결 → 변경이력을 확인
- 최소 Golden Scenario 기반 E2E 및 회귀 테스트

### Not required for this baseline

아래는 가능하지만 Baseline 완료 조건에 포함하지 않습니다.

- 최종 UI polish 및 전체 디자인 완성
- 모든 나라장터 업무 유형/예외 케이스 지원
- Canonical Requirement 8종 외 임의 확장
- 제안서 배점 자동 점수화
- 복잡한 추천/랭킹 모델
- 운영환경 수준의 Observability/Autoscaling
- 최종 AWS Production Architecture 완성
- 모든 실험용 LLM/RAG 기능의 통합

## 2. Definition of Done

Baseline은 아래 조건이 모두 실제 동작으로 검증될 때 완료로 봅니다.

### A. Runtime

- [ ] PostgreSQL + API가 정상 실행된다.
- [ ] Frontend가 API와 연결된다.
- [ ] `/health`가 정상 응답한다.
- [ ] Baseline Golden Scenario를 재현할 수 있는 실행 절차가 문서화되어 있다.

### B. Notice and source

- [ ] 하나의 공고가 `notice_id`로 식별된다.
- [ ] 해당 공고의 특정 버전이 `notice_version_id`로 고정된다.
- [ ] 분석 대상 `document_id`와 원본 hash가 추적된다.
- [ ] Evidence가 Backend의 extracted block/source locator로 되돌아갈 수 있다.

### C. Company Profile

- [ ] Company Profile을 생성/조회할 수 있다.
- [ ] 업종, 지역, 인력, 수행실적, 인증 중 Golden Scenario에 필요한 값이 저장된다.
- [ ] 판정이 참조한 Profile field를 추적할 수 있다.

### D. Requirement Analysis

- [ ] Backend 문서 블록을 AI 분석 입력으로 전달한다.
- [ ] 분석 결과가 `RequirementAnalysisResult` 계약을 만족한다.
- [ ] Canonical Requirement에 `requirement_key`가 존재한다.
- [ ] Requirement에 최소 하나의 원문 근거를 연결할 수 있다.
- [ ] 분석 실패/부분 성공이 정상 성공으로 위장되지 않는다.

### E. Judgment

- [ ] Requirement와 Company Profile을 비교해 Requirement 단위 판정을 만든다.
- [ ] 판정 결과는 `SATISFIED / UNSATISFIED / UNKNOWN` 중 하나다.
- [ ] 판정마다 `reason_code`와 판단 근거가 있다.
- [ ] 정보 부족은 임의 추론으로 채우지 않고 UNKNOWN으로 남는다.

### F. Ask-back

- [ ] UNKNOWN의 원인이 사용자 입력으로 해결 가능한지 식별한다.
- [ ] 사용자에게 필요한 질문을 노출한다.
- [ ] 답변이 해당 Case/Requirement와 연결되어 저장된다.
- [ ] 답변 후 전체 분석을 무조건 다시 돌리지 않고 영향 Requirement를 우선 재판정할 수 있다.

### G. Change / Revalidation

- [ ] 변경공고가 새 Notice Version으로 식별된다.
- [ ] 이전 Version과 현재 Version의 자격 Requirement 차이를 비교할 수 있다.
- [ ] 변경 영향을 받은 Requirement를 식별한다.
- [ ] 변경되지 않은 판정과 변경된 판정을 구분해 보여준다.
- [ ] 새 Evidence가 현재 Version 원문을 가리킨다.

### H. Frontend

- [ ] 사용자가 공고를 선택할 수 있다.
- [ ] Company Profile을 선택/입력할 수 있다.
- [ ] 참가자격 판정 결과를 볼 수 있다.
- [ ] 각 판정의 원문 근거를 확인할 수 있다.
- [ ] UNKNOWN의 해결 입력을 할 수 있다.
- [ ] 변경공고 발생 시 변경된 항목과 재판정 결과를 확인할 수 있다.

### I. Regression

- [ ] Golden Scenario가 자동 또는 재현 가능한 수동 E2E로 검증된다.
- [ ] Canonical Contract fixture가 회귀 테스트에 포함된다.
- [ ] 같은 입력/같은 원문 기준으로 ID·Evidence 연결 규칙이 깨지지 않는다.

## 3. Acceptance principle

Baseline은 단순히 화면이 열리는 데모가 아니라 아래 trace가 이어져야 합니다.

```text
notice_id
→ notice_version_id
→ document_id
→ source block
→ requirement_key
→ evidence_key
→ company/profile field
→ judgment_key
→ optional user answer
→ re-judgment
```

이 trace가 끊기는 구간이 있으면 해당 구간은 Baseline 미완료입니다.

## 4. Safety / truthfulness rule

- 근거가 없는 판정을 LLM이 만들어내지 않습니다.
- 원본 document identity와 extracted text identity를 혼동하지 않습니다.
- `PARTIAL` 분석을 `SUCCEEDED`로 표시하지 않습니다.
- UNKNOWN을 UI 편의를 위해 임의로 SATISFIED 또는 UNSATISFIED로 변환하지 않습니다.
- 변경공고 재판정 시 이전 Version Evidence를 현재 근거처럼 노출하지 않습니다.
