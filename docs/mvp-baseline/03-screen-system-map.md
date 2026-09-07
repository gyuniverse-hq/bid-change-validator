# 03. Screen ↔ System Map

이 문서는 화면 요구사항을 실제 Backend / DB / AI 연결점에 매핑합니다.

`Actual`은 현재 저장소에서 확인된 경로이며, `TBD`는 Stage 2 Contract Gap 검산 후 확정할 경로입니다.

## 1. MVP screen map

| Screen / UX | User action | Backend/API | Data / AI | Baseline status |
| --- | --- | --- | --- | --- |
| 공고 찾기 | 공고 검색/선택 | `GET /api/v1/notices`, `GET /api/v1/notices/{notice_id}` | Notice | Actual |
| 공고 버전 | 현재/이전 버전 확인 | `GET /api/v1/notices/{notice_id}/versions` | Notice Version | Actual |
| 회사 프로필 | 회사 생성/조회/수정 | `/api/v1/companies` CRUD | Company + industries/staff/performance/certification | Actual |
| 제안서 사전검토 | Case 생성/파일 업로드 | `/api/v1/preflight-cases` | Preflight Case + Proposal Document | Actual |
| 참가자격 분석 | 공고 자격조건 분석 실행/조회 | Stage 2에서 API entry point 확정 | `RequirementAnalysisResult` | Connect / verify |
| 참가자격 판정 | Requirement별 결과 확인 | Stage 2에서 API 계약 확정 | Requirement + Company Profile + Judgment | Connect / missing check |
| 근거 원문 | 판정 근거 클릭/원문 대조 | notice document `/text`, `/preview`, `/source` | Evidence locator + Document | Actual source API / result link TBD |
| 확인 필요 | UNKNOWN 질문 확인 | Stage 2에서 Ask-back API 확정 | UNKNOWN + reason/basis | TBD |
| 답변 입력 | 부족 회사정보/사실 입력 | Stage 2에서 Answer API 확정 | User Answer | TBD |
| 부분 재판정 | 답변 후 영향 항목 갱신 | Stage 2에서 re-judgment contract 확정 | Judgment | TBD |
| 변경 이력 | 변경공고/버전 비교 | Notice versions + Stage 2 diff API/logic | Version + Requirement Diff | Partial |
| 재검증 결과 | 변경 영향 판정 확인 | Stage 2 revalidation contract 확정 | Affected Requirements + Judgments | TBD |

## 2. Product UX principle

핵심 화면 흐름은 다음 순서를 유지합니다.

```text
판정
↓
근거
↓
해결
```

사용자는 먼저 무엇이 충족/미달/확인 필요인지 보고, 그다음 왜 그런 판정인지 원문 근거를 확인하고, 마지막으로 해결 가능한 행동을 수행합니다.

## 3. Qualification screen target

### Summary layer

화면 상단은 최종 판정을 단일 색상으로 단순화하기보다 Requirement 분포를 보여줄 수 있어야 합니다.

```text
충족: N
미달: N
확인 필요: N
분석 경고: N
```

`분석 경고`는 AI Analysis의 `PARTIAL`/diagnostic이고, `확인 필요`는 Judgment `UNKNOWN`입니다. 서로 합치지 않습니다.

### Requirement rows

각 Requirement row가 최소한 다음 정보를 표시할 수 있어야 합니다.

- Requirement label / normalized condition
- Judgment status
- reason
- Company Profile basis
- Evidence link
- 해결 액션 여부
- 변경공고 영향 여부

### Evidence drawer / panel

근거 클릭 시 다음 연결이 유지되어야 합니다.

```text
requirement_key
→ evidence_key
→ document_id
→ source location
→ original preview/source
```

HWP/HWPX는 존재하지 않는 PDF page를 임의 생성하지 않고 Backend extracted block locator를 사용합니다.

## 4. Company Profile screen target

현재 Backend Company Profile은 단순 회사명 수준이 아니라 다음 판정 정보를 포함할 수 있습니다.

- 업종
- 지역
- 기업규모
- 인력 및 역할
- 수행실적 / 경험분야
- 인증/등록 정보

Baseline에서는 이 정보를 Canonical Requirement와 직접 대응시킬 수 있어야 합니다.

```text
INDUSTRY                    ↔ industries
REGION                      ↔ region
STAFF                       ↔ staff / roles
PERFORMANCE_AMOUNT          ↔ performances.amount
PERFORMANCE_COUNT           ↔ performances
EXPERIENCE_FIELD            ↔ performance fields
REGISTRATION_CERTIFICATION  ↔ certifications
COMPANY_SIZE                ↔ company_size
```

Stage 2에서 실제 필드명/검증여부(`verified`)와 Canonical 비교 규칙을 확정합니다.

## 5. Change history screen target

변경공고 화면은 단순 문서 diff보다 **사용자에게 미치는 판정 영향**을 우선합니다.

권장 표현:

```text
변경된 공고 조건
→ 영향을 받은 Requirement
→ 이전 판정
→ 현재 판정
→ 이전 Evidence / 현재 Evidence
→ 필요한 조치
```

전체 문서 변경 내역은 보조 정보로 두고, 실제 제출 가능성에 영향을 주는 변경을 우선 표시합니다.

## 6. API contract rule

이 문서에 `TBD`로 표시한 endpoint 이름은 아직 최종 계약이 아닙니다.

Stage 2에서 다음 순서로 확정합니다.

1. 이미 존재하는 실제 router/service를 먼저 조회
2. DB Model과 stable ID 확인
3. 현재 AI contract와 연결
4. 기존 Frontend ↔ Backend 초안과 비교
5. 중복 API를 만들지 않고 최소 integration endpoint 결정
