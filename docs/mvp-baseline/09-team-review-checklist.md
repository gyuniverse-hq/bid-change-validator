# 09. MVP Integration Baseline — Team Review Checklist

> 목적: `integration/mvp-baseline → develop` PR 전 팀이 공통으로 확인할 최종 Review 기준입니다.

## 1. Review decision

이 Review에서 결정할 것은 “모든 기능이 완성됐는가?”가 아닙니다.

다음을 판단합니다.

> **각 담당자가 이후 병렬 고도화할 수 있을 정도로 제품 전체 연결 기준선이 실제로 작동하는가?**

Go 조건:

- 핵심 Golden Path가 실제 제품 경로로 연결됨
- Contract / Status / ID 의미가 명확함
- fresh DB migration + regression CI 통과
- 담당별 Handoff가 가능함
- 남은 기능이 명시적 Known Gap으로 분리됨

---

## 2. Current Golden Path

```text
Notice v1 / Company Profile
→ Requirement Analysis
→ Deterministic Judgment
→ REGION / STAFF / PERFORMANCE SATISFIED
→ REGISTRATION UNKNOWN
→ Ask-back yes
→ USER_ANSWER SATISFIED
→ overall eligible
→ Notice v2
→ Canonical Requirement Diff
→ PERFORMANCE_AMOUNT 400M → 600M MODIFIED
→ affected-only Revalidation
→ PERFORMANCE_AMOUNT UNSATISFIED
→ overall ineligible
```

### Review

- [ ] 위 흐름이 서비스 정의와 일치한다
- [ ] `UNKNOWN`을 LLM 실패나 `UNSATISFIED`와 혼동하지 않는다
- [ ] Ask-back이 전체 분석 재실행 없이 해당 조건만 재판정하는 방향에 동의한다
- [ ] 변경공고는 Canonical Requirement 단위 diff/revalidation하는 방향에 동의한다

---

## 3. Automated verification

Stage 9 GitHub Actions 기준:

```text
PostgreSQL 16
→ Alembic 001 → 009
→ Backend full pytest: 69 passed

Frontend
→ frozen install
→ production build success
```

Golden E2E:

```text
apps/api/tests/test_mvp_golden_e2e.py
```

- [ ] fresh PostgreSQL migration chain 통과 확인
- [ ] Backend full regression 통과 확인
- [ ] Golden E2E 통과 확인
- [ ] Frontend production build 통과 확인
- [ ] 기존 Frontend lint debt는 현재 baseline blocker가 아니라 별도 개선 항목으로 관리하는 데 동의

---

# Frontend Review

## 4. Frontend reviewer checklist

Reference implementation:

```text
/qualification
apps/web/lib/qualification-api.ts
```

- [ ] Company 선택 → Case 생성 흐름이 최종 UI에 이식 가능하다
- [ ] `SATISFIED / UNSATISFIED / UNKNOWN`을 UI 상태로 충분히 표현할 수 있다
- [ ] `eligible / ineligible / insufficient_data` 종합 상태가 UI 요구와 맞는다
- [ ] Ask-back API가 필요한 입력 UX를 지원한다
- [ ] 변경공고 `UNCHANGED / MODIFIED / ADDED / REMOVED`를 화면에 표현할 수 있다
- [ ] 기존 메인 디자인을 Baseline이 강제로 덮어쓰지 않은 구조가 적절하다

### Frontend Known Gap

- [ ] Evidence click-through 최종 UX
- [ ] 최종 참가자격 화면 디자인 이식
- [ ] 전체 lint debt 정리
- [ ] Proposal RAG 결과 UI

위 항목은 develop merge blocker가 아니라 이후 Frontend 고도화 항목으로 분리 가능한지 확인합니다.

---

# Backend / DB Review

## 5. Backend reviewer checklist

핵심 lineage:

```text
Notice → Version → Document → extracted_blocks
Company
PreflightCase
AnalysisRun → Requirement / Evidence
JudgmentRun → Judgment
Answer → source/result Judgment
RevalidationRun → baseline/current Analysis + source/result Judgment
```

- [ ] ID / FK 관계가 향후 API 고도화에 충분하다
- [ ] `extracted_blocks`를 AI input Source of Truth로 유지하는 데 동의한다
- [ ] migration `006~009` 역할이 명확하다
- [ ] baseline/current Version을 같은 PreflightCase에서 추적하는 구조가 적절하다
- [ ] Profile completeness로 UNKNOWN을 구분하는 정책이 안전하다
- [ ] Profile 변경 시 affected-only revalidation을 거부하는 guard가 적절하다

### Backend / DB Known Gap

- [ ] idempotency / duplicate run 정책
- [ ] USER_ANSWER → Profile 승격 provenance
- [ ] retry / async job orchestration
- [ ] production auth / authorization
- [ ] observability / audit

위 항목이 develop merge blocker인지 이후 운영성 고도화인지 구분합니다.

---

# LLM / RAG Review

## 6. LLM / RAG reviewer checklist

현재 AI boundary:

```text
extracted_blocks
→ chunking
→ requirement extraction
→ guardrail
→ deterministic normalization
→ Canonical Requirement + Evidence
→ AnalysisResult
```

- [ ] Canonical Requirement 8종이 현재 MVP 자격판정 범위를 충분히 커버한다
- [ ] LLM은 source-grounded extraction에 집중하고 Judgment는 deterministic code로 분리하는 방향에 동의한다
- [ ] Evidence provenance contract가 후속 Eval에 사용 가능하다
- [ ] `SUCCEEDED / PARTIAL / FAILED`와 Judgment 상태 분리가 적절하다
- [ ] unsupported/ambiguous requirement를 억지 판정하지 않는 방향에 동의한다

### LLM / RAG Known Gap

- [ ] 실제 OpenAI E2E
- [ ] 실공고 extraction 품질 평가
- [ ] Precision / Recall / Evidence grounding 평가
- [ ] Proposal RAG
- [ ] stable semantic requirement identity 고도화

특히 **Stage 9 Golden E2E는 모델 품질 평가가 아니라 제품 integration regression**임을 공통 인식합니다.

---

# Contract Review

## 7. Canonical Requirement 8 types

```text
PERFORMANCE_AMOUNT
PERFORMANCE_COUNT
INDUSTRY
REGION
STAFF
REGISTRATION_CERTIFICATION
EXPERIENCE_FIELD
COMPANY_SIZE
```

- [ ] 현재 8종을 Baseline contract로 채택
- [ ] 확장이 필요하면 기존 의미를 깨지 않고 명시적 contract version으로 변경

## 8. Status layers

### AI execution

```text
SUCCEEDED / PARTIAL / FAILED
```

### Requirement judgment

```text
SATISFIED / UNSATISFIED / UNKNOWN
```

### Overall product

```text
eligible / ineligible / insufficient_data
```

### Change diff

```text
UNCHANGED / MODIFIED / ADDED / REMOVED
```

- [ ] 네 상태 계층을 서로 섞지 않는 데 동의

---

# Known Gap Review

## 9. Explicit non-blockers candidate

다음은 현재 Baseline에서 명시적으로 남겨둔 고도화 후보입니다.

- 실제 OpenAI / 실공고 Quality Eval
- Proposal RAG / 제안서 대응 누락검사
- USER_ANSWER → Company Profile 자동 반영
- Evidence 최종 UX
- Frontend lint debt
- Production auth
- Retry / queue / observability
- 배포 환경 E2E

각 항목에 대해 팀 Review에서 다음 중 하나를 선택합니다.

```text
A. develop merge blocker
B. 병렬 고도화 backlog
C. MVP scope 밖
```

안전·실행 불가능 문제가 아니라면 자동으로 범위에서 제거하지 않고 팀이 결정합니다.

---

# Develop PR Gate

## 10. Required before `integration/mvp-baseline → develop`

- [ ] Stage 9 CI green
- [ ] Handoff snapshot review
- [ ] Frontend reviewer 확인
- [ ] Backend / DB reviewer 확인
- [ ] LLM / RAG reviewer 확인
- [ ] Contract blocker 없음
- [ ] develop merge blocker로 분류된 Known Gap 처리 또는 명시적 합의
- [ ] main / develop에 직접 커밋하지 않았음

## 11. Go / No-Go record

### Go

```text
integration/mvp-baseline이 공통 제품 기준선으로 충분하다.
각 담당자가 Contract를 유지하면서 병렬 고도화할 수 있다.
→ develop PR 진행
```

### Conditional Go

```text
Baseline은 유효하지만 develop merge 전에 해결할 blocker가 소수 존재한다.
→ blocker 명시 후 해결 → develop PR
```

### No-Go

```text
핵심 Golden Path / Contract / persistence lineage 중 하나가 실제로 연결되지 않았다.
→ 해당 Stage로 돌아가 수정
```

---

## 12. Review output

팀 Review가 끝나면 최소 아래를 남깁니다.

```text
Decision: GO / CONDITIONAL GO / NO-GO
Blockers: ...
Parallel backlog: ...
Owner: ...
Next: integration/mvp-baseline → develop PR 여부
```

이 결과를 기준으로 Stage 12를 진행합니다.
