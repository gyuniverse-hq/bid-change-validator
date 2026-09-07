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

## 로컬 PostgreSQL 실행

PostgreSQL을 실행하고 마이그레이션, API, 변경공고 수집기를 시작합니다.

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

실행 주소는 다음과 같습니다.

- 상태 확인: `http://localhost:8000/health`
- Swagger API 문서: `http://localhost:8000/docs`

API가 시작되기 전에 Alembic이 데이터베이스 스키마를 자동으로 적용합니다. 마이그레이션을 수동으로 적용하려면 다음 명령을 사용합니다.

```powershell
docker compose run --rm migrate
```

업종, 품목, 기관 기준정보 CSV를 최초 적재하거나 갱신합니다.

```powershell
docker compose --profile tools run --rm master-data-import
```

기준정보 적재는 UPSERT 방식이므로 다시 실행해도 중복 데이터가 만들어지지 않고 기존 코드가 갱신됩니다.

기준정보 검색 API는 다음과 같습니다.

```text
GET /api/v1/master-codes/industries?q=토목&limit=20
GET /api/v1/master-codes/products?q=1010150201
GET /api/v1/master-codes/institutions?q=서울&active_only=false
GET /api/v1/master-codes/institutions/1011052
```

검색 결과는 정확한 코드, 코드 앞부분, 정확한 이름, 이름 앞부분 순서로 우선 정렬됩니다. `active_only=true`가 기본값이며 `limit`은 1부터 100까지 지정할 수 있습니다.

## 로컬 Qualification Integration 확인

`integration/mvp-baseline`의 `/qualification` 화면에서 실제 Backend API와 OpenAI 기반 자격요건 분석 경로를 확인할 수 있습니다.

먼저 저장소 루트에서 `.env.example`을 `.env`로 복사하고 OpenAI API Key를 입력합니다.

```powershell
Copy-Item .env.example .env
```

`.env`의 다음 값을 설정합니다.

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_DEFAULT=gpt-5.6-luna
```

`.env`와 `.env.*`는 Git ignore 대상이며 `.env.example`만 추적합니다. 실제 API Key를 commit하지 마세요.

Backend API 컨테이너를 시작합니다.

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

프론트엔드는 별도 터미널에서 실행합니다.

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

확인 주소:

- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- 기본 화면: `http://localhost:3000`
- Qualification Integration: `http://localhost:3000/qualification`

`OPENAI_API_KEY`가 비어 있으면 qualification analysis 실행 시 `AI_PROVIDER_NOT_CONFIGURED` 오류가 반환되는 것이 정상입니다.

## 나라장터 공고 수집

등록공고, 변경공고 또는 공고번호 한 건을 API로 수집할 수 있습니다.

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

수집기는 정규화한 공고 필드와 나라장터 원본 JSON을 함께 저장합니다. 이전과 동일한 원본 데이터는 기존 버전을 재사용하고, 내용이 바뀌면 다음 버전을 생성해 현재 버전으로 표시합니다.

표준공고문과 `ntceSpecDocUrl1`부터 `ntceSpecDocUrl10`까지의 첨부파일을 내려받습니다. URL과 파일 해시가 같은 파일은 한 번만 저장하며 저장경로, MIME 유형, 파일 크기, SHA-256, 다운로드 상태를 PostgreSQL에 기록합니다.

HWP/HWPX는 구역·문단 단위로, PDF는 페이지 단위로 텍스트를 추출합니다. `/text` API는 비교 화면에서 사용할 전체 텍스트와 원문 위치 블록을 반환합니다. 텍스트 추출 결과는 시각적 서식을 보존하지 않으므로 원본 파일을 최종 근거로 사용합니다.

PDF는 `/preview` API로 브라우저에서 표시합니다. HWP/HWPX는 rhwp WebAssembly 뷰어에서 렌더링할 수 있도록 `viewer_type`, `render_source_url`, `text_url`, `preview_url`을 제공합니다. 프론트엔드 연결 규격은 `docs/contracts/rhwp-viewer.md`에서 확인할 수 있습니다.

`notice-poller` 서비스는 5분마다 용역, 물품, 공사, 외자 분야의 변경공고를 조회합니다. 마지막 성공 구간부터 수집을 재개하며 경계 누락을 방지하기 위해 5분을 겹쳐 다시 조회합니다. 중복 데이터는 원본 해시로 걸러내고 PostgreSQL advisory lock을 사용해 여러 수집기가 동시에 실행되지 않도록 합니다.

실행 간격과 조회 범위는 `NOTICE_POLL_*` 환경변수로 조정할 수 있으며, 실행 결과는 `GET /api/v1/notices/collection-runs`에서 확인할 수 있습니다.

## 제안서 사전검토 건

공고 버전을 기준으로 검토 건을 생성하고 제안서 파일을 업로드합니다.

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

업로드 API는 HWP, HWPX, PDF, DOCX, TXT 형식을 지원합니다. 파일 크기를 제한하고 SHA-256으로 검토 건 안의 중복 파일을 차단합니다. 공고 첨부파일과 동일한 로컬/S3 저장구조를 사용하며 업로드 직후 텍스트를 추출합니다. 추출에 성공한 제안서가 하나 이상 있으면 검토 건 상태가 `DRAFT`에서 `READY`로 변경됩니다.

이 단계에서는 LLM을 호출하거나 자격판정 결과를 생성하지 않습니다.

## 프론트엔드 검토 화면

`apps/web`의 프론트엔드는 FastAPI와 직접 연결됩니다. 공고 검색, 검토 건 생성, 제안서 업로드, 공고 버전 선택, PDF 원문 표시, rhwp 기반 HWP/HWPX 페이지 렌더링을 지원합니다.

화면은 공고문, 제안서, 누락·합격조건의 3개 영역으로 구성됩니다. 현재 누락·합격조건 영역에는 문서 저장 및 텍스트 추출 준비 상태만 표시하며 LLM 분석은 수행하지 않습니다.

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm dev
```

프론트엔드는 `http://localhost:3000`에서 확인할 수 있습니다. FastAPI를 AWS에 배포한 뒤 `NEXT_PUBLIC_API_BASE_URL`을 실제 API 주소로 변경해야 합니다.

## AWS 배포 설정

로컬 Docker에서는 `notice_documents_data` 볼륨에 문서를 저장합니다. AWS에서는 다음 환경변수를 설정해 S3 저장소를 사용합니다.

- `DOCUMENT_STORAGE_BACKEND=S3`
- `DOCUMENT_S3_BUCKET`
- `DOCUMENT_S3_PREFIX`
- `AWS_REGION`

ECS 또는 EC2에는 고정 AWS 키를 저장하지 않고 IAM 역할로 S3 접근 권한을 부여해야 합니다. PostgreSQL은 RDS, API와 변경공고 수집기는 별도 ECS 서비스 또는 EC2 프로세스로 운영하는 구성을 권장합니다.

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
