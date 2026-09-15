# Oracle 미리보기 배포·복구 절차

> 상태: Current(2026-09-15 확인) + Proposed(다음 배포 절차)
> 범위: 발표 전 미리보기 환경. 정식 운영 SLA나 자동 배포가 아니다.
> 담당: Backend/배포. 실제 변경 전에는 통합 담당자와 배포 시점을 합의한다.

## 현재 확인된 구성

2026-09-15 기준 `develop` HEAD는 `2d51c1a`이며, Oracle의 활성 릴리스는 `/opt/bidcheck/releases/c77111e`다. 두 리비전의 코드 트리는 같지만 서버의 릴리스 이름은 별도로 유지한다. 이 상태를 다음 배포의 기준으로 삼되, 작업 중 다른 PR이 병합되면 다시 확인한다.

```text
HTTPS: 140-83-82-100.sslip.io
  └─ nginx
      ├─ /api, /health → 127.0.0.1:8000 → FastAPI 컨테이너
      └─ 나머지 경로 → 127.0.0.1:3000 → vinext production 웹 컨테이너

FastAPI / notice-poller → Supabase PostgreSQL
FastAPI / notice-poller → OCI Object Storage(S3 호환) 원본 파일
```

- 같은 HTTPS 도메인에서 웹과 API를 제공하므로 브라우저의 HttpOnly 세션 쿠키를 동일 출처로 사용한다.
- 웹은 `dist/client`만 정적 서빙하지 않는다. 현재 서버의 웹 컨테이너는 `pnpm exec vinext start --hostname 0.0.0.0 --port 3000`으로 RSC/SSR 응답까지 제공한다. 저장소의 `docker-compose.prod.yml`은 API·migration·poller만 정의하며 웹 컨테이너는 현재 별도 관리다. 이 차이를 자동 배포 구성으로 오인하지 않는다.
- API와 수집기는 Supabase transaction pooler(6543)를 소규모 pool로 사용한다. Alembic은 별도 session pooler(5432)를 사용한다. 실제 연결 문자열과 암호는 서버의 비공개 환경변수에만 둔다.
- 원본 PDF/HWP는 OCI Object Storage에 저장하고, Supabase에는 공고 메타데이터·추출 텍스트·파일 키를 둔다. 원본 조회/다운로드는 Backend가 발급하는 임시 URL 경로를 사용한다.
- `/health`는 2026-09-15에 HTTPS 200과 API 컨테이너 healthy 상태를 확인했다. 이것만으로 화면·로그인·판정의 정상 동작을 인증하지 않는다.

## 다음 배포 전 확인(Proposed)

1. 통합 담당자에게 배포 대상 commit과 시간을 공유한다. 발표 QA 중에는 승인되지 않은 코드 병합·서버 재배포를 하지 않는다.
2. 대상 commit이 최신 `develop`인지, 관련 GitHub CI가 green인지 확인한다. 특히 Backend/Frontend, Copilot integration, golden-regression을 구분해 기록한다.
3. 새 migration 유무와 공용 Supabase의 현재 Alembic revision을 확인한다. 현재 릴리스에 맞지 않는 이전 코드를 DB에 붙여 시험하지 않는다. migration은 별도 승인·백업 계획 없이 반복 실행하지 않는다.
4. 기존 활성 릴리스 경로, 웹/API 이미지 태그, nginx upstream, 필요한 비공개 환경변수의 **존재 여부**를 기록한다. 값 자체를 채팅·PR·로그에 복사하지 않는다.
5. 새 릴리스는 기존 릴리스를 보존한 채 별도 경로와 이미지 태그로 준비한다. API와 웹이 모두 준비되고 내부 health 확인이 끝난 뒤 공개 트래픽을 바꾼다.
6. [발표 데모·Golden human QA](../08_qa_reports/presentation-human-qa.md)의 최소 smoke를 실행하고 결과·소요 시간·실패 화면을 기록한다. 자동 CI 통과와 화면 QA 통과를 동일하게 취급하지 않는다.

### 읽기 전용 점검 예시

다음은 **서버를 변경하지 않는** 점검이다. SSH 접근 권한과 현재 릴리스 경로는 담당자가 별도로 관리한다.

```bash
readlink -f /opt/bidcheck/current
sudo docker ps --format '{{.Names}} {{.Status}}'
sudo nginx -T 2>/dev/null | grep -E 'proxy_pass http://127.0.0.1:(3000|8000)'
curl -fsS -o /dev/null -w '%{http_code}\n' https://140-83-82-100.sslip.io/health
```

## 실패 시 판단과 복구

- 공개 전 내부 health가 실패하면 **전환하지 않고** 새 릴리스 원인을 조사한다.
- 공개 후 로그인/핵심 이동이 실패하면 새 배포를 중단하고, 먼저 웹 upstream·API upstream·컨테이너 상태·세션 응답을 분리해 확인한다. 사용자의 브라우저 캐시나 DB 문제라고 단정하지 않는다.
- 릴리스 복구는 **DB schema와 원본 저장 계약이 호환되는 이전 릴리스**에 한해 검토한다. 서버에 보존된 이전 릴리스 `/opt/bidcheck/releases/6b2769b`도 OCI 원본 저장 도입 이후의 코드다. #140 이전 코드를 단순히 켜는 방식은 이미 `storage_key`가 OCI를 가리키는 공용 DB와 호환된다고 볼 수 없다.
- 코드/컨테이너 전환은 DB migration, 이미 저장된 공고/판정, OCI 객체를 자동으로 되돌리지 않는다. DB downgrade·객체 삭제를 복구 절차에 포함하지 않는다. 해당 조치가 필요하면 별도 백업·영향 검토와 팀 승인을 받는다.
- 결과를 통합 담당자에게 공유할 때는 대상 commit, 실패 경로, 시작/종료 시간, 복구 후 smoke 결과만 적고 Secret과 사용자 비밀번호는 제외한다.

## 현재 범위와 미완료

- GitHub push/merge가 Oracle 배포를 자동으로 수행하는 workflow는 없다. 이 문서는 수동 배포의 검증 기준이며 자동 배포 구현 완료를 뜻하지 않는다.
- 발표 시연의 기본 대체 경로는 로컬 앱이다. Oracle이 동작하더라도 로컬·서버 중 어느 쪽을 발표에 사용할지 QA 결과로 결정한다.
- 수집기의 전체 이력 백필, 외부 g2b 요청 실패, 원본 누락은 health 200과 별개의 데이터 운영 항목이다. 발표 대상 공고의 문서·차수는 Golden manifest와 화면에서 별도 검증한다.
