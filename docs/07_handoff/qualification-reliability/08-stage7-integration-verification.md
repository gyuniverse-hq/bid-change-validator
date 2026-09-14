# 7단계 — 전체 통합 검증과 실제 공고 실측 준비

검증 대상: **전북대학교 남원글로컬캠퍼스 본관동 생활폐기물 처리 용역** (`R26BK01684863`).
J14는 이 공고를 가리키던 qualification 골든셋 식별자다. 구내식당을 발표 데모로 바꾸지 않는다.
작업 브랜치: `refactor/qualification-reliability`; 시작 commit `4690559`.

## 1. 현재 단계

7-A: 프로젝트 전체 회귀/타입/빌드 및 실제 Chromium UI 검증을 실행하고 발견된 결함을 수정했다.
7-B: 실제 공고의 읽기 전용 캡처 및 반복 측정 도구를 구현했다. 실제 모델/대상 DB 실측은 미실행이다.
7-C: 새 의미 그래프의 공고 전체 적용 관계, 저장·제품 API 전환, 변경 재검증/Copilot 운영 E2E는 남아 있다.

단계별 합성 테스트가 모두 통과하더라도 실제 남원글로컬 추출·판정 정확도까지 통과한 것은 아니다.

## 2. 전체 환경에서 발견한 문제와 수정

| 확인 | 원인 | 수정 |
|---|---|---|
| 첫 전체 tsc: TS2339 2건 | Workers/DOM Response.json 타입에서 오류 본문을 검증하지 않고 접근 | unknown에서 객체/문자열 필드 검사 |
| 첫 backend 수집 ImportError | state 모듈이 catalog를 포함하면서 독립 테스트에 불필요한 의존성 전파 | state/catalog를 독립시키고 상위 judgment 라우터에서 조립 |
| 두 번째 backend HTTP 테스트 10건 실패 | catalog 테스트가 이전 state 포함 구조에 의존 | 테스트가 실제 catalog 라우터를 등록하도록 수정. assertion/기대값 유지 |
| 새 라우팅 테스트 1건 실패 | FastAPI 내부 app.routes 자료형을 가정 | 실제 HTTP 응답, OpenAPI, mapper 구성으로 검증 |

기존 테스트를 건너뛰거나 타입 검사를 약화해 통과시키지 않았다. 골든 기대값은 수정하지 않았다.

## 3. 검증 기록

`.github/workflows/qualification-reliability.yml`은 이 작업 브랜치 push에서 실행된다.
GitHub Actions의 일회용 PostgreSQL 16 / Python 3.12 / Node 22 / pnpm 10.15.0 환경이다.
프로젝트 lockfile을 그대로 설치했고 TypeScript도 프로젝트 지정 버전을 사용했다.
공용 DB·실제 모델·배포 자격증명은 사용하지 않았다.

- 1차: `1e36608`, run `34904609059` — Node 140 통과/build 통과, tsc 및 pytest 수집 실패.
- 2차: `433adcb`, run `34905054574` — frontend 전체 성공, backend 1416 통과/11실패/1건너뜀.
- 3차: `c764ee6`, run `34905954442` — backend 1427 통과/1건너뜀, Node 148 통과,
  전체 tsc/build 및 기존 Copilot 클라이언트 검사 5개, Chromium 6흐름 성공.
- 4차: `c4463df`, run `34907225441` — backend **1444 통과/1건너뜀**, Node **148 통과**,
  전체 tsc/build/Copilot 5검사 및 Chromium 6흐름 재통과. 반복 측정기 신규 17개가 포함됐다.
  READ ONLY 강제 검증 3개는 일회용 실제 PostgreSQL과 운영 ORM에서 실행됐다.
- 실제 전체 앱 OpenAPI 및 ORM mapper 구성과 PostgreSQL migrations 성공.
- 기존 `run_golden_regression.py` 성공. 정답·평가기 파일은 그대로다.

단 하나 건너뛴 테스트는 jsonschema가 프로젝트 개발 의존성에 없어 기존 importorskip이 작동한
스키마 검사다. 이 항목을 통과로 세지 않는다. 변경 전후 실행 수를 누적하지 않는다.

## 4. 실제 브라우저 검증의 범위

`apps/web/scripts/check-qualification-browser.cjs`는 실제 React/vinext/Chromium을 실행한다.
공고·회사·판정 HTTP 응답은 합성 자료로 intercept한다. 이름도 `[합성 검증]`으로 표시한다.

1. 사업 유형 필터를 서버 검색 조건으로 전달.
2. 상태가 선택한 판정과 원문 근거를 표시. 읽는 동안 POST 없음.
3. 회사 재판정은 judgment POST만 호출하고 공고 분석 POST는 호출하지 않음.
4. 회사 기준 변경 시 재판정 필요/건수 `—`, 과거 eligible를 현재로 표시하지 않음.
5. 저장 확인 후 GET 실패는 재조회로 복구. 동일 POST 자동 반복 없음.
6. 503을 미검토/0건으로 변환하지 않음.

스크린샷: 목록/상세/재판정 필요/390px 모바일. pageerror 및 예상 밖 API 요청은 0이다.
브라우저 검증 전체에서 judgment POST 2회, analysis POST 0회였다.
공유된 실제 회사나 원문을 합성 테스트 파일에 복사하지 않았다.
이는 UI 통합 검증이며 실제 공고의 모델 답변, 운영 DB, 배포된 제품 E2E를 보증하지 않는다.

## 5. 실제 남원글로컬 반복 측정 도구

모듈: `apps.api.app.scripts.check_qualification_repeatability`.

기본 동작은 READ ONLY 캡처다. 실제 모델 호출은 `--live-model` 명시 시에만 실행한다.

```powershell
# 실행 환경에 DATABASE_URL이 구성돼 있어야 한다. 비밀 값을 채팅·문서에 붙이지 않는다.
# CASE_ID와 기준일은 실제 데모 검토 건을 확인한 후 지정한다.
python -m apps.api.app.scripts.check_qualification_repeatability `
  --case-id "<검증할 검토 건 UUID>" `
  --notice-number R26BK01684863 `
  --reference-date "<YYYY-MM-DD>" `
  --output "<보호된 출력 폴더>/namwon-capture.json"

# OPENAI_API_KEY가 구성된 환경에서만 실행. API 비용이 발생한다.
python -m apps.api.app.scripts.check_qualification_repeatability `
  --case-id "<검증할 검토 건 UUID>" `
  --notice-number R26BK01684863 `
  --reference-date "<YYYY-MM-DD>" `
  --live-model --runs 3 --max-calls 60 `
  --strategies legacy review_v1 review_graph_v1 `
  --output "<보호된 출력 폴더>/namwon-repeatability.json"
```

- PostgreSQL 새 트랜잭션을 REPEATABLE READ / READ ONLY로 시작해 원문·회사·차수를 한 번 읽는다.
- case의 공고번호를 명시한 대상과 비교하며 다른 공고면 중단한다.
- 기준·현재 차수의 원문 입력/첨부 상태/해시와 회사 스냅샷 해시를 고정한다.
- DB 세션을 닫은 뒤 실제 구/신 추출 함수와 회사 판정 함수를 메모리에서 실행한다.
- 공유 분석/판정 테이블에는 결과를 저장하지 않는다. 캐시 결과 재사용으로 반복성을 꾸미지 않는다.
- 모델 호출 수 상한과 HTTP timeout을 두고 SDK 자동 재시도를 끈다. 호출 수는 금액 상한과 다르다.
- 원문/모델 응답/회사 상세는 결과 파일에 넣지 않는다. 요청/응답/의미/판정 지문과 진단을 기록한다.
- 로컬 보고서에는 내부 식별자가 포함될 수 있으므로 공개 저장소에 올리지 않는다.
- 같은 오답도 재현될 수 있다. accuracy는 null, quality_verdict는 NOT_ESTABLISHED다.
- graph 결과는 조항별 판정이다. legacy의 공고 전체 판정과 동일한 성능 지표로 합산하지 않는다.
- --reference-date 생략은 허용하지 않는다. 오늘 날짜를 자동 기준으로 쓰지 않는다.
- 반환코드 0은 측정 완료이지 성능 통과가 아니다. NOT_RUN은 2, 행 실행 오류는 3이다.

## 6. 아직 남은 실제 검증 조건

현재 assistant 실행 환경에는 대상 프로젝트의 DB 접속과 모델 키가 구성되어 있지 않다.
연결된 Supabase 목록에서도 해당 나라장터 프로젝트에 대한 접근을 확인하지 못했다.
기존에 공유된 화면/문서 기록은 현재 DB의 원문·차수·회사 스냅샷을 대신하지 않는다.
회사 정보/기대 판정을 바꿔 데모를 통과시키거나 골든셋을 수정하지 않았다.

실제 실행 전후에 다음을 확인해야 한다.

- 남원글로컬의 정확한 기준/현재 차수·첨부·검토 건·회사 프로필·판정 기준일.
- 선택형 업종, 수집·운반 관련 조건과 예외, 지역 조건, 현장 확인 관련 조건의 원문 검수.
- 확정 미달이 회사 사실 때문인지, 요건 누락/오분류/논리 손실 때문인지 분리.
- 새 의미 그래프의 조항 간 적용/예외·미지원 사항을 없애지 않은 제품 저장/API 경로.
- 실제 모델 반복성과 원문 정답 대비 정확도, 변경 전후 의미 비교, Copilot의 기준 일치.

이 항목들이 남아 있으므로 **7단계 전체 완료 또는 현재 데모 성능 확보로 처리하지 않는다.**
