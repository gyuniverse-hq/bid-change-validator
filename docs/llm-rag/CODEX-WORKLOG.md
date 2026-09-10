# Codex 작업 로그

## 2026-09-10 — 로컬 서버 종료 및 Docker Compose 전환

- 로컬에서 실행 중이던 Backend API(8000)와 AI 데모 서버(8200) Python 프로세스를 종료했습니다.
- Docker Desktop 사용자 설치 경로의 CLI를 확인하고 API·notice-poller 이미지를 현재 코드로 다시 빌드했습니다.
- 기존 PostgreSQL 볼륨은 프로젝트 기본 로컬 계정으로 생성됐지만 현재 `.env`의 `POSTGRES_*` 값은 외부 DB용 값이라 마이그레이션 인증이 실패함을 확인했습니다.
- `.env`와 기존 DB 볼륨은 변경·삭제하지 않고, Compose 실행 프로세스에만 프로젝트 기본 로컬 DB 접속값을 적용해 서비스를 재생성했습니다.
- 마이그레이션 종료 코드 0, DB/API healthy, `/health` 응답 `{"status":"ok"}`를 확인했습니다.
- API 컨테이너 내부에서 `OPENAI_API_KEY`와 `OPENAI_MODEL_DEFAULT`가 모두 전달됐음을 값 노출 없이 확인했습니다.

