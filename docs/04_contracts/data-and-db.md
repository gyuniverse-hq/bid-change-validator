# Data / DB Baseline

> **상태: Current**  
> 기준: `develop`

이 문서는 현재 데이터 저장 구조와 DB 변경 시 확인해야 할 기준을 정리합니다. 실제 테이블 정의는 SQLAlchemy Model과 Alembic Migration을 Source of Truth로 둡니다.

## 현재 저장 대상

- Company Profile
- Bid Notice / Notice Version
- Notice Document / 추출 상태
- Preflight Case
- Qualification Analysis Run
- Requirement / Evidence
- Qualification Judgment Run / Records
- Qualification Answer
- Qualification Revalidation
- Master Codes

## Migration 흐름

현재 Alembic Migration은 대략 다음 도메인 순서로 쌓여 있습니다.

```text
001 Company Profile
002 Bid Notices
003 Notice Document Storage
004 Document Text Extraction
005 Preflight Cases
006 Qualification Analysis
007 Qualification Judgment
008 Qualification Answers
009 Qualification Revalidation
```

## 저장 원칙

- 공고의 변경 상태는 overwrite보다 Version 단위 보존을 우선합니다.
- Analysis / Judgment / Revalidation은 Run 이력을 남겨 과거 결과와 현재 결과를 구분합니다.
- Company Profile은 판정 시점 Snapshot과 현재 Profile을 구분합니다.
- 원본 파일과 extracted text는 재현성을 위해 Hash/identity를 추적합니다.
- Requirement와 Evidence는 `requirement_key`, `evidence_key` 기반 연결을 유지합니다.

## 물리 저장

`docker-compose.yml` 기준:

- PostgreSQL → `postgres_data`
- Notice 원본 문서 → `notice_documents_data`
- Document Storage Backend는 `LOCAL` 기본이며 S3 관련 설정 확장 지점이 존재합니다.

## DB 구조 변경 시 원칙

- 기존 데이터 마이그레이션 경로를 명확히 합니다.
- Schema 변경은 Alembic migration으로 추적합니다.
- 현재 API Response 및 Frontend Contract 영향을 확인합니다.
- AI Contract와 DB Model을 동일 개념으로 착각하지 않습니다. AI는 Backend-owned PK를 생성하지 않습니다.

## Known Gaps / 고도화 후보

- ERD를 현재 실제 Model 기준으로 최신화 필요
- Evaluation Criterion 저장 여부/Schema 미확정
- Copilot Session/Message 저장 필요 여부 미확정
- Profile provenance / evidence status 정책 추가 검토 가능
- `db/schema/`, `db/migrations/`, Alembic의 역할 중복 여부 정리 필요

## 변경 체크리스트

- Migration 생성 여부
- downgrade 전략 필요 여부
- 기존 데이터 호환성
- FK / unique / index 영향
- API Schema 영향
- AI Requirement/Evidence/Judgment 계약 영향
- Golden/E2E fixture 갱신 필요 여부
