# bid-change-validator

> Validates how changed public procurement notices affect existing bid qualifications, required documents, and submission readiness.

## Project

**나라장터 변경공고 대응형 입찰 제출 검증기**

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하고, 변경된 조건과 원문 근거를 바탕으로 영향을 받은 항목을 재검증하는 프로젝트입니다.

**Current Stage**  
`Topic Selected → MVP / User Flow / Architecture Design`

## Team

| Member | Initial Role |
| --- | --- |
| 김재현 | LLM / RAG |
| 이홍규 | LLM / RAG · Collaboration Infrastructure |
| 전진환 | Backend / Overall Structure |
| 정예린 | DB / Data Management |
| 황수빈 | Frontend / UI·UX |

> 역할은 2026-09-02 회의에서 정한 초기 역할 기준이며, 기능별 세부 책임은 Figma·프로토타입 검토 후 조정할 수 있습니다.

## Parallel Development Workspaces

주말 초기 병렬작업을 위해 Frontend / Backend / LLM·RAG workspace를 분리 운영합니다.

| Workspace | Owners | Repository |
| --- | --- | --- |
| Frontend | 황수빈 (Main), 이홍규 (Sub) | https://github.com/gyuniverse-hq/bid-change-validator-frontend |
| Backend / Data | 전진환 (Backend), 정예린 (DB / Data) | https://github.com/gyuniverse-hq/bid-change-validator-backend |
| LLM / RAG | 김재현, 이홍규 | https://github.com/gyuniverse-hq/bid-change-validator-llm-rag |

초기에는 빠른 구현과 실험을 우선하고, 영역 간 연결점은 아래 공통 문서에서 맞춥니다.

- 병렬 작업 가이드: `docs/parallel-development.md`
- Frontend ↔ Backend 계약 초안: `docs/contracts/frontend-backend.md`
- Backend ↔ LLM / RAG 계약 초안: `docs/contracts/backend-llm.md`

## Current Focus

- Figma 기반 핵심 User Flow 및 화면설계
- 초기 Backend / API / 데이터 흐름 프로토타입
- 나라장터 도메인 및 데이터 구조 검토
- LLM / RAG · Guardrail · Evaluation Harness 사전 검토
- Jira · GitHub · Notion 기반 협업 구조 적용

## Local PostgreSQL

Start PostgreSQL, apply migrations, the API, and the changed-notice poller:

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

The API is available at:

- Health check: `http://localhost:8000/health`
- Swagger UI: `http://localhost:8000/docs`

Alembic applies the schema before the API starts. Apply pending migrations manually with:

```powershell
docker compose run --rm migrate
```

Import or refresh the industry, product, and institution master-code CSV files:

```powershell
docker compose --profile tools run --rm master-data-import
```

The master-data import uses upserts, so running it again updates existing codes
without creating duplicates.

Search master codes through the API:

```text
GET /api/v1/master-codes/industries?q=토목&limit=20
GET /api/v1/master-codes/products?q=1010150201
GET /api/v1/master-codes/institutions?q=서울&active_only=false
GET /api/v1/master-codes/institutions/1011052
```

Search results prioritize exact code, code prefix, exact name, and name prefix in
that order. `active_only=true` is the default, and `limit` accepts 1 through 100.

## Bid Notice Collection

Collect registered, changed, or single-number G2B notices through the API:

```text
POST /api/v1/notices/sync
GET  /api/v1/notices?q=정보시스템&business_type=SERVICE
GET  /api/v1/notices/{notice_id}
GET  /api/v1/notices/{notice_id}/versions
GET  /api/v1/notices/collection-runs
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/content
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/text
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/preview
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/source
POST /api/v1/notices/documents/extract-pending
```

The collector stores the normalized notice fields and the complete source JSON.
An identical source payload reuses the existing version; a changed payload creates
the next version and marks it current. Standard notice documents and attachment
URLs (`ntceSpecDocUrl1` through `ntceSpecDocUrl10`) are downloaded once per unique
URL/content hash. Their storage key, MIME type, byte size, SHA-256, and download
status are recorded in PostgreSQL.

The `notice-poller` service checks changed notices every five minutes for service,
goods, construction, and foreign-procurement categories. It resumes from the last
completed window, overlaps five minutes to avoid boundary misses, and relies on
payload hashes for idempotency. A PostgreSQL advisory lock allows only one poller
instance to collect at a time when the service is replicated on ECS or EC2. Tune
the interval and recovery window with the `NOTICE_POLL_*` environment variables;
poll outcomes remain visible through `GET /api/v1/notices/collection-runs`.

HWP/HWPX text is extracted into section/paragraph blocks, and PDF text is
extracted into page blocks. The `/text` endpoint returns both the complete text
and the source-location blocks for comparison UI. Text extraction does not
preserve visual formatting: the `/preview` endpoint serves original PDFs inline,
while HWP/HWPX requires a separate rendering/conversion engine for a browser
preview. The original downloaded file always remains the authoritative source.

HWP/HWPX browser rendering is delegated to the MIT-licensed rhwp WebAssembly
viewer. The API returns `viewer_type`, `render_source_url`, `text_url`, and
`preview_url` for each document. See `docs/contracts/rhwp-viewer.md` for the
frontend integration contract. Pin and regression-test the selected rhwp release;
its layout engine is still converging toward Hancom-compatible pagination.

## Proposal Preflight Cases

Create a review case for a notice version, then upload proposal documents:

```text
POST /api/v1/preflight-cases
GET  /api/v1/preflight-cases
GET  /api/v1/preflight-cases/{case_id}
POST /api/v1/preflight-cases/{case_id}/documents
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/source
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/content
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/text
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/preview
```

The upload endpoint accepts multipart HWP, HWPX, PDF, DOCX, and TXT files. Files
are size-limited, hashed, deduplicated within the case, stored through the same
local/S3 abstraction as notice documents, and text-extracted immediately. A case
moves from `DRAFT` to `READY` when at least one proposal document is extracted.
This pipeline does not call an LLM or create qualification judgments.

## Frontend Review Console

The frontend in `apps/web` connects directly to the FastAPI contract. It supports
notice search, case creation, proposal upload, current-version selection, inline
PDF viewing, rhwp-based HWP/HWPX page rendering, and the three-column notice / proposal /
review-result workspace. The result column currently reports document readiness
only; no LLM analysis is performed.

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_API_BASE_URL` to the deployed API
origin when the FastAPI service is moved to AWS.

Local Docker uses the `notice_documents_data` volume. For AWS, set
`DOCUMENT_STORAGE_BACKEND=S3`, `DOCUMENT_S3_BUCKET`, `DOCUMENT_S3_PREFIX`, and
`AWS_REGION`; ECS/EC2 should receive S3 access through an IAM role rather than
static credentials.

## Collaboration

기본 개발 흐름은 다음과 같이 운영합니다.

```text
Figma / Requirement
→ Jira Work Item
→ Branch
→ Pull Request
→ Review / Test
→ Merge
→ Jira Done
```

- `main`: 안정 버전 / 배포 기준
- `develop`: 통합 개발 브랜치
- 기능 브랜치: `feat/SKN34-XX-summary`, `fix/SKN34-XX-summary` 등
- 주요 변경은 Pull Request와 최소 1명 Review를 거칩니다.

## Documentation

세부 아키텍처, 기술 스택, 실행 방법, API·데이터 흐름, 평가 결과는 설계가 확정되는 순서대로 이 README와 `docs/`에 반영합니다.
