# DB ERD · Current develop

> **상태: Current**  
> 기준: `develop`의 SQLAlchemy Model + Alembic Migration

이 문서는 현재 제품의 핵심 데이터 관계를 빠르게 이해하기 위한 논리 ERD입니다. 실제 컬럼/제약조건의 최종 Source of Truth는 코드와 Migration입니다.

## 핵심 관계

```text
Company
├─ CompanyIndustry
├─ CompanyStaff
├─ CompanyStaffRole
├─ CompanyPerformance
│  └─ CompanyPerformanceField
└─ CompanyCertification

BidNotice
└─ BidNoticeVersion
   └─ NoticeDocument

Company + BidNotice + current/baseline Version
└─ PreflightCase
   ├─ ProposalDocument
   ├─ QualificationJudgmentRun
   │  └─ QualificationJudgmentRecord
   ├─ QualificationAnswer
   └─ QualificationRevalidationRun

BidNoticeVersion
└─ QualificationAnalysisRun
   ├─ QualificationRequirementRecord
   └─ QualificationEvidenceRecord
```

## 분석 → 판정 Lineage

```text
BidNoticeVersion
        ↓
QualificationAnalysisRun
        ├─ status: SUCCEEDED | PARTIAL | FAILED
        ├─ contract_version
        ├─ target_chunk_ids
        └─ diagnostics
        ↓
RequirementRecord + EvidenceRecord
        ↓
PreflightCase + Company
        ↓
QualificationJudgmentRun
        ├─ analysis_run_id
        ├─ company_id
        ├─ notice_version_id
        ├─ overall_status
        ├─ rule_version
        ├─ reference_date
        └─ profile_snapshot
        ↓
QualificationJudgmentRecord[]
```

`profile_snapshot`은 중요한 재현성 장치입니다. 현재 회사 DB 값이 바뀌어도 과거 Judgment Run이 어떤 회사 정보로 계산됐는지 보존합니다.

## Ask-back Lineage

```text
source JudgmentRun
      ↓
QualificationAnswer
├─ requirement_key
├─ normalized_value
├─ evidence_held
├─ apply_to_profile
└─ answer_json
      ↓
result JudgmentRun
```

현재 MVP Policy A에서는 `apply_to_profile=false`를 기본으로 사용하며, 사용자 답변은 Case의 판정 근거(`basis_type=USER_ANSWER`)로 사용될 수 있습니다. 답변을 회사 Profile에 자동 영구 저장한다고 가정하지 않습니다.

## Revalidation Lineage

```text
source JudgmentRun
      +
baseline AnalysisRun
      +
current AnalysisRun
      ↓
Requirement Diff
      ↓
QualificationRevalidationRun
├─ changes
├─ revalidated_keys
└─ result_judgment_run_id
      ↓
result JudgmentRun
```

핵심은 모든 요구사항을 무조건 새로 판정하는 것이 아니라 **영향받은 Requirement key를 추적해 재판정 lineage를 남기는 것**입니다.

## 주요 상태

### Analysis

- `SUCCEEDED`
- `PARTIAL`
- `FAILED`

### 개별 Judgment

- `SATISFIED`
- `UNSATISFIED`
- `UNKNOWN`

### Judgment basis

- `PROFILE`
- `USER_ANSWER`
- `NONE`

### Judgment reason

- `RULE_MATCH`
- `RULE_MISMATCH`
- `INSUFFICIENT_DATA`
- `NEEDS_REVIEW`
- `UNSUPPORTED_REQUIREMENT`

### 전체 Qualification

- `eligible`
- `ineligible`
- `insufficient_data`

## 물리 저장

기본 Docker Compose 기준:

- PostgreSQL data → `postgres_data`
- Notice / Proposal document storage → `notice_documents_data` 기반 Local storage
- `DOCUMENT_STORAGE_BACKEND=S3` 구성 시 S3-compatible storage 확장 가능

현재 로컬 볼륨과 배포 DB/Storage는 같은 개념이 아닙니다. Production 환경에서는 DB URL, Storage Backend, Secret, backup/restore 정책을 별도 확정합니다.

## Migration 기준

```text
001 Company
002 Notice / Version
003 Document Storage
004 Text Extraction
005 Preflight Case / Proposal
006 Qualification Analysis
007 Qualification Judgment
008 Qualification Answer
009 Qualification Revalidation
```

## 고도화 시 확인할 것

- Evaluation Criterion / Proposal Retrieval 결과를 저장할지
- Copilot Session/Message persistence가 실제 제품에 필요한지
- provenance/evidence-held 의미를 UI와 DB에서 동일하게 쓰는지
- 신규 테이블이 Version/Run lineage를 깨지 않는지
- 기존 Golden fixture/migration regression 갱신 여부
