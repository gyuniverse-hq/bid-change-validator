# Local Run / Operations Runbook

> **상태: Current**  
> 기준: `develop`

이 문서는 개발자가 새 환경에서 현재 제품을 실행하고, 코드 변경 후 필요한 재빌드/검증을 확인하기 위한 운영 기준입니다.

## 기본 구성

`docker-compose.yml` 기준 서비스:

- `db`: PostgreSQL 16
- `migrate`: Alembic migration
- `api`: FastAPI
- `notice-poller`: 나라장터 변경공고 수집 Worker
- `master-data-import`: 기준정보 적재 Tool

Frontend는 `apps/web`에서 별도로 실행합니다.

## Backend 실행

```powershell
Copy-Item .env.example .env
docker compose up -d --build api notice-poller
docker compose ps
```

확인:

- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`

Backend 컨테이너는 build image 방식이므로 Backend 코드를 변경하면 다시 build 합니다.

```powershell
docker compose up -d --build api
```

## Migration

```powershell
docker compose run --rm migrate
```

또는 `api` 시작 시 migration service 완료를 기다리는 compose dependency를 사용합니다.

## Master Data

```powershell
docker compose --profile tools run --rm master-data-import
```

현재 업종/품목/기관 기준정보 적재에 사용합니다.

## Frontend 실행

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

기본 주소: `http://localhost:3000`

## 주요 환경변수

- PostgreSQL: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`
- 나라장터: `G2B_SERVICE_KEY`
- OpenAI: `OPENAI_API_KEY`, `OPENAI_MODEL_DEFAULT`
- Document Storage: `DOCUMENT_STORAGE_BACKEND`, `DOCUMENT_STORAGE_PATH`, S3 관련 값
- CORS: `CORS_ORIGINS`
- Notice polling: `NOTICE_POLL_*`

Secret은 `.env`에 두고 Commit하지 않습니다.

## 데이터 볼륨

- `postgres_data`: PostgreSQL 데이터
- `notice_documents_data`: 공고 원본 문서

컨테이너 재생성만으로 볼륨 데이터가 삭제되지는 않습니다. 데이터 초기화가 필요한 경우 볼륨 삭제는 별도 의도된 작업으로 취급합니다.

## 변경 후 확인

### Backend 변경
- image rebuild
- migration 필요 여부
- pytest
- Swagger/API regression

### Frontend 변경
- type check / lint
- build
- 주요 Route 확인

### AI 변경
- 기존 Golden regression
- 실제 Extraction sample
- Contract version/Schema 변경 여부

### DB 변경
- migration upgrade
- 기존 데이터 호환성
- API regression

## Known Gaps

- 실제 배포 환경 Runbook은 아직 확정되지 않았습니다.
- `infra/`는 현재 구현이 없어 Production deployment 문서는 Proposed로 남깁니다.
- 장애 대응 / backup / restore 정책은 배포 구조 확정 후 추가합니다.
