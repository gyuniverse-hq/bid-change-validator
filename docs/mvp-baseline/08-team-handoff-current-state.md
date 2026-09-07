# 08. Team Handoff — Current Integration State

> 기준: `integration/mvp-baseline` Stage 0~9. 이 문서는 설계 원칙이 아니라 **현재 실제 구현 상태와 다음 담당 작업 시작점**을 전달하는 snapshot입니다.

## 1. Current product baseline

현재 통합 기준선의 핵심 vertical slice는 다음입니다.

```text
나라장터 Notice / Version / Document
→ Backend extracted_blocks
→ Semantic Chunking
→ Requirement Extraction + Guardrail
→ Deterministic Normalization
→ Canonical Requirement 8종 + Evidence
→ Analysis persistence
→ Company Profile deterministic Judgment
→ SATISFIED / UNSATISFIED / UNKNOWN
→ UNKNOWN Ask-back
→ USER_ANSWER partial re-judgment
→ Changed Notice Canonical Diff
→ affected-only Revalidation
→ Qualification reference UI (/qualification)
```

Golden E2E 기준 흐름:

```text
v1
REGION / STAFF / PERFORMANCE_AMOUNT = SATISFIED
REGISTRATION = UNKNOWN
→ Ask-back yes
→ REGISTRATION = SATISFIED (USER_ANSWER)
→ overall eligible

v2
PERFORMANCE_AMOUNT 400M → 600M
→ MODIFIED
→ PERFORMANCE_AMOUNT만 재판정
→ UNSATISFIED
→ overall ineligible
```

## 2. Contract / status baseline

### AI execution status

```text
SUCCEEDED / PARTIAL / FAILED
```

문서 분석 실행 자체의 상태입니다. Qualification 판단 결과와 섞지 않습니다.

### Requirement judgment status

```text
SATISFIED / UNSATISFIED / UNKNOWN
```

- `SATISFIED`: 비교 가능한 사실이 조건 충족
- `UNSATISFIED`: 해당 profile 영역이 complete이고 비교 결과 불일치
- `UNKNOWN`: 사실 부족 또는 profile 영역 incomplete

### Product overall status

```text
eligible / ineligible / insufficient_data
```

Frontend 표시용 종합 상태이며 Requirement-level status를 대체하지 않습니다.

### Changed-notice diff

```text
UNCHANGED / MODIFIED / ADDED / REMOVED
```

`MODIFIED` / `ADDED`만 affected-only re-judgment 대상입니다.

## 3. Canonical Requirement 8 types

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

현재 GitHub 기준은 8종입니다. 이전 Notion snapshot의 `Canonical 7종`, `feat/llm-rag-integration / PR·Merge 전` 표기는 과거 상태로 봅니다.

---

# Frontend handoff

## 4. Current frontend reference

실제 Qualification vertical slice reference screen:

```text
/apps/web/app/qualification/page.tsx
/apps/web/lib/qualification-api.ts
```

Route:

```text
/qualification
```

기존 `apps/web/app/page.tsx`는 Integration Baseline에서 대규모 수정하지 않았습니다. 최종 UI/UX는 기존 화면에 `qualification-api.ts` contract를 이식하는 방식이 안전합니다.

## 5. Frontend API surface

### Company / Case

```text
GET  /api/v1/companies
POST /api/v1/preflight-cases
```

### Requirement Analysis

```text
GET  /api/v1/notices/{notice_id}/versions/{version_number}/qualification-analyses
POST /api/v1/notices/{notice_id}/versions/{version_number}/qualification-analysis
GET  /api/v1/qualification-analyses/{run_id}
```

### Judgment

```text
POST /api/v1/preflight-cases/{case_id}/qualification-judgments
GET  /api/v1/preflight-cases/{case_id}/qualification-judgment-runs
GET  /api/v1/qualification-judgment-runs/{run_id}
```

`analysis_run_id`를 명시하면 해당 PreflightCase의 baseline 또는 current NoticeVersion 분석 결과를 판정할 수 있습니다.

### Ask-back

```text
GET  /api/v1/preflight-cases/{case_id}/qualification-questions
POST /api/v1/preflight-cases/{case_id}/qualification-answers
```

Answer 결과는 `basis_type=USER_ANSWER`로 남고 문서 분석/RAG를 다시 실행하지 않습니다.

### Change Revalidation

```text
POST /api/v1/preflight-cases/{case_id}/qualification-revalidation
```

Response 핵심:

```text
changes[]
revalidated_keys[]
result (new QualificationJudgmentRun)
```

## 6. Frontend next actions

추천 우선순위:

1. 기존 최종 디자인의 “참가 자격 판정” 화면에 `qualification-api.ts` 연결
2. 판정 → 근거 → 해결 순서로 `SATISFIED / UNKNOWN / UNSATISFIED` 표현
3. `UNKNOWN`만 Ask-back UI 노출
4. `requirement_evidence_keys`를 Analysis Evidence와 연결해 원문 근거 이동
5. 변경공고 화면에서 `MODIFIED / ADDED / REMOVED`와 `revalidated_keys`를 분리 표시
6. loading / empty / PARTIAL / FAILED / API error UX 보강
7. 기존 full-repo frontend lint debt 별도 정리

현재 `/qualification`은 최종 디자인이 아니라 **실제 API가 끝까지 연결되는 reference implementation**입니다.

---

# Backend / DB handoff

## 7. Migration chain

현재 fresh PostgreSQL에서 CI로 검증한 migration chain:

```text
001 company profile
002 bid notices
003 notice document storage
004 document text extraction
005 preflight cases
006 qualification analysis persistence
007 qualification judgment persistence
008 qualification answers
009 qualification revalidation lineage
```

Stage 9 CI에서 `alembic upgrade head` 전체 chain이 실제 통과했습니다.

## 8. Main persistence trace

```text
BidNotice
└─ BidNoticeVersion
   └─ NoticeDocument
      └─ extracted_blocks

Company
└─ Staff / StaffRole / Performance / Certification / Industry

PreflightCase
├─ company_id
├─ baseline_version_id
└─ current_version_id

QualificationAnalysisRun
├─ QualificationRequirementRecord
└─ QualificationEvidenceRecord

QualificationJudgmentRun
└─ QualificationJudgmentRecord

QualificationAnswer
└─ source judgment → result judgment

QualificationRevalidationRun
└─ baseline/current analysis + source/result judgment lineage
```

## 9. Backend ownership boundaries

- Low-level document parsing / `extracted_blocks`: Backend Source of Truth
- AI Core는 `extracted_blocks`를 입력으로 사용
- AI 실행 상태와 Judgment 상태는 별도 관리
- Company Profile 값 부재를 곧바로 미달로 해석하지 않음
- Profile completeness가 false이면 필요한 경우 `UNKNOWN`
- Ask-back의 `apply_to_profile=true`는 현재 지원하지 않음
- 변경공고 affected-only Revalidation은 source judgment의 profile snapshot과 현재 profile이 같을 때만 허용
- profile이 달라졌으면 `PROFILE_CHANGED_FULL_REJUDGMENT_REQUIRED`

## 10. Backend / DB next actions

추천 우선순위:

1. transaction / idempotency 정책 보강
2. analysis/judgment/revalidation 중복 실행 정책 확정
3. Company profile completeness 입력/수정 UX와 provenance 정책 확정
4. USER_ANSWER를 실제 Profile에 승격하는 정책 설계
5. OpenAPI contract 재생성/검산
6. 운영 데이터 migration/seed 전략 보강
7. observability / run audit / failure retry 보강

---

# LLM / RAG handoff

## 11. Current AI boundary

```text
Backend extracted_blocks
→ canonical source blocks
→ semantic chunks
→ requirement extraction
→ guardrail
→ deterministic normalization
→ Canonical Requirement + Evidence
→ RequirementAnalysisResult
```

현재 실제 코드가 있는 영역:

```text
apps/api/app/ai/backend_blocks.py
apps/api/app/ai/chunking.py
apps/api/app/ai/requirement_extraction.py
apps/api/app/ai/normalization/
apps/api/app/ai/canonicalize.py
apps/api/app/ai/evidence_adapter.py
apps/api/app/ai/analysis_result.py
apps/api/app/ai/providers/openai.py
```

Judgment는 LLM이 아니라 deterministic code입니다.

```text
apps/api/app/ai/judgment.py
```

Changed-notice diff도 deterministic code입니다.

```text
apps/api/app/ai/requirement_diff.py
```

## 12. LLM / RAG next actions

현재 가장 큰 미구현/고도화 영역은 다음입니다.

### A. Actual model quality evaluation

- 실제 OpenAI E2E
- 실제 나라장터 공고 샘플
- Requirement extraction precision / recall
- Evidence grounding 정확도
- unsupported / ambiguous clause 평가
- abstention / PARTIAL / diagnostic 품질

Stage 9의 Golden E2E는 제품 연결 회귀 테스트이지 모델 품질 평가가 아닙니다.

### B. Proposal RAG

현재 자격판정 vertical slice와 별개로 **제안서/제출서류 대응 확인**은 아직 본격 구현되지 않았습니다.

목표 후보:

```text
Canonical Requirement / 제출 요구사항
+
ProposalDocument extracted_blocks
→ retrieval
→ 대응 근거
→ 누락 / 충족 / 확인 필요
```

이 영역은 최종 MVP 범위와 팀 역할을 확인해 병렬 고도화하면 됩니다.

### C. Requirement key stability

현재 Requirement key는 extraction order 영향을 받습니다. Stage 7에서 semantic fallback으로 변경공고 diff 오판을 줄였지만, 장기적으로는 stable semantic identity 전략을 별도 검토할 가치가 있습니다.

---

# Verification / CI handoff

## 13. Automated baseline verification

Stage 9 기준 GitHub Actions:

```text
.github/workflows/mvp-integration-baseline.yml
```

Backend gate:

```text
PostgreSQL 16
→ alembic upgrade head
→ pytest apps/api/tests
```

검증 결과:

```text
69 passed
```

Frontend gate:

```text
pnpm install --frozen-lockfile
→ existing lint debt inventory (non-blocking)
→ vinext build (blocking)
```

production build 통과를 확인했습니다.

Golden E2E:

```text
apps/api/tests/test_mvp_golden_e2e.py
```

Master Code 테스트는 fresh DB에서도 재현 가능하도록:

```text
apps/api/tests/conftest.py
```

에서 테스트에 필요한 최소 seed를 자체 관리합니다.

## 14. Known gaps / non-goals

Baseline 완성 여부와 별개로 다음은 이후 고도화 대상입니다.

- 실제 OpenAI + 실공고 품질 Eval
- Proposal RAG / 제출서류 누락 검사 제품 연결
- USER_ANSWER → Company Profile 영구 반영
- Evidence click-through 최종 UX
- Frontend 전체 lint debt
- production auth / authorization
- production observability / retry / job orchestration
- 배포 환경 E2E

이 항목들은 **현재 Qualification integration baseline이 연결됐다는 사실과 분리**해 관리합니다.

## 15. Handoff completion checkpoint

현재 팀원이 다음 기준으로 병렬 고도화를 시작할 수 있습니다.

### Frontend

```text
qualification-api.ts contract를 신뢰하고 최종 UX에 연결
```

### Backend / DB

```text
NoticeVersion / Company / AnalysisRun / JudgmentRun / Answer / RevalidationRun lineage를 신뢰하고 운영성 고도화
```

### LLM / RAG

```text
extracted_blocks → RequirementAnalysisResult contract를 신뢰하고 모델 품질/Eval/Proposal RAG 고도화
```

### Integration

```text
Golden E2E + CI를 공통 회귀 기준선으로 사용
```

다음 통합 단계는 팀 Review 후:

```text
integration/mvp-baseline
→ PR to develop
→ CI / 통합 검증
→ merge
→ develop → main release review
```
