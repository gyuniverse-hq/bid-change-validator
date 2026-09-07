# 04. Contract and Status Map

## 1. Source-of-truth order

Baseline에서 계약 충돌이 생기면 조용히 변환하지 않고 아래 순서로 확인합니다.

1. 실제 Backend source identity / DB data
2. `apps/api/app/ai` Canonical contract
3. 승인된 MVP Baseline contract decision
4. 기존 `docs/contracts/*` 초안
5. 화면 표시용 derived status

기존 문서는 폐기하지 않습니다. 서로 다른 상태 체계가 있으면 Stage 2 Contract Gap으로 기록하고 명시적으로 통합합니다.

## 2. Canonical Requirement types

현재 AI Canonical contract의 닫힌 Requirement Type은 8종입니다.

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

Baseline에서는 우선 이 8종을 공통 판정 언어로 사용합니다.

새 유형이 필요하면 기존 유형에 억지로 끼워 넣지 않고 Contract 변경으로 다룹니다.

## 3. Requirement operators

현재 Canonical contract에서 허용하는 operator:

```text
>=
>
<=
<
=
MATCH
RANGE
```

Requirement는 `raw` 원문과 normalized value를 함께 유지해야 합니다.

## 4. AI analysis status

AI Requirement 분석 실행 자체의 상태입니다.

| Status | Meaning | UI / Backend rule |
| --- | --- | --- |
| `SUCCEEDED` | Canonical 변환까지 정상 완료 | 정상 결과 사용 가능 |
| `PARTIAL` | 일부 결과는 있으나 diagnostic 존재 | 결과 + 경고를 함께 노출/저장 |
| `FAILED` | Canonical 결과를 신뢰할 수 없음 | 성공 판정 흐름으로 전달 금지 |

이 상태는 회사 자격 충족 여부가 아닙니다.

## 5. Judgment status

Requirement와 Company Profile/User Answer를 비교한 판정 상태입니다.

```text
SATISFIED
UNSATISFIED
UNKNOWN
```

| Status | Meaning | Next action |
| --- | --- | --- |
| `SATISFIED` | 현재 근거 기준 조건 충족 | 근거 확인 가능 |
| `UNSATISFIED` | 현재 근거 기준 조건 미충족 | 해결 가능성/조치 안내 |
| `UNKNOWN` | 판정에 필요한 데이터 부족 또는 확인 필요 | Ask-back / review |

## 6. Judgment basis and reason

현재 Canonical contract 기준:

### Basis type

```text
PROFILE
USER_ANSWER
NONE
```

### Reason code

```text
RULE_MATCH
RULE_MISMATCH
INSUFFICIENT_DATA
NEEDS_REVIEW
UNSUPPORTED_REQUIREMENT
```

Baseline에서는 `status`만 저장하지 않고 최소한 `basis_type`과 `reason_code`를 같이 유지합니다.

## 7. Existing draft status gap

기존 `docs/contracts/frontend-backend.md`와 `docs/contracts/backend-llm.md`에는 다음 aggregate status 초안이 존재합니다.

```text
eligible
ineligible
needs_review
insufficient_data
```

세부 check 상태 초안:

```text
passed
failed
unknown
warning
```

반면 현재 Canonical code는 Requirement-level `SATISFIED / UNSATISFIED / UNKNOWN`을 사용합니다.

### Baseline decision

Stage 1에서는 기존 상태를 삭제하거나 강제로 하나로 합치지 않습니다.

- Canonical business judgment: `SATISFIED / UNSATISFIED / UNKNOWN`
- AI execution status: `SUCCEEDED / PARTIAL / FAILED`
- Frontend aggregate status: **Stage 2에서 mapping 확정**

### Mapping candidate for Stage 2 discussion

아래는 확정값이 아니라 검토 기준입니다.

```text
all required SATISFIED
→ eligible 후보

any required UNSATISFIED
→ ineligible 후보

no UNSATISFIED + one or more UNKNOWN
→ insufficient_data / needs_review 중 reason_code에 따라 구분 후보

AI PARTIAL
→ business judgment와 별도로 warning 표시 후보
```

`UNKNOWN`과 `PARTIAL`을 같은 의미로 취급하지 않습니다.

## 8. Evidence contract

Evidence는 최소 다음 identity를 보존합니다.

- `evidence_key`
- `source_type`
- `document_id`
- `notice_version_id` 또는 Case context
- `location`
- `quote`
- `source_sha256`
- `extracted_text_sha256`

### Location rule

Backend extracted block이 source of truth입니다.

가능한 locator:

- block range
- PDF page
- section index
- paragraph range
- source line range
- clause label

HWP/HWPX에 존재하지 않는 page 정보를 임의로 생성하지 않습니다.

## 9. Requirement contract

Requirement는 최소 다음을 추적합니다.

- `requirement_key`
- optional group key / ALL_OF / ANY_OF
- `notice_version_id`
- `type`
- `operator`
- `value`
- `unit`
- `period_months`
- `scope`
- `required`
- `raw`
- `confidence`
- `evidence_keys`

## 10. Judgment contract

현재 Canonical object의 핵심 필드:

- `judgment_key`
- `preflight_case_id`
- `notice_version_id`
- `requirement_key`
- `status`
- `basis_type`
- `evidence_held`
- `reason_code`
- `requires_evidence`
- `profile_refs`
- `requirement_evidence_keys`
- `rule_version`

Stage 2에서는 이 object가 실제 어디서 생성되고 저장되는지 검산합니다.

## 11. Contract Gap checklist for Stage 2

- [ ] 기존 draft `eligible/...`와 Canonical Judgment status mapping
- [ ] Company Profile field ↔ Requirement type mapping
- [ ] RequirementAnalysisResult API entry point
- [ ] Requirement / Evidence persistence model
- [ ] Judgment generator / persistence model
- [ ] Ask-back Question contract
- [ ] User Answer contract
- [ ] Answer가 어떤 Requirement/Judgment를 invalidate하는지 관계
- [ ] Notice Version relation / 변경공고 연결 규칙
- [ ] Requirement Diff identity rule
- [ ] Revalidation Run identity/status
- [ ] Frontend aggregate status contract

## 12. Change rule

계약을 바꿀 때는 다음 원칙을 적용합니다.

- 새 optional field 추가는 비교적 자유롭게 진행합니다.
- stable ID 의미를 변경하지 않습니다.
- 기존 field name/type/meaning 변경은 관련 영역에 공유합니다.
- LLM prompt나 retriever 내부 구현은 contract를 깨지 않는 범위에서 자유롭게 교체할 수 있습니다.
- 실제 구현이 문서와 다르면 실제 상태를 먼저 기록하고 팀 합의로 contract를 갱신합니다.
