# 공고 분석·판정 일관성 개선 — 진행 현황

브랜치 `refactor/qualification-reliability`, 출발 `c510c3e` (Copilot #139 포함).
주 검증 대상: **전북대학교 남원글로컬캠퍼스 본관동 생활폐기물 처리 용역** (`R26BK01684863`).
현재: **7-A 전체 CI·실제 Chromium 합성 통합 검증 통과. 7-B 실측 도구 구현/검증 완료, 대상 DB·실모델 측정은 미실행.**
검증된 코드 commit: `c4463dff1b164bfd24ffc27e25ffa4a2ac1f7253`.
최종 코드 검증 run: `34907225441` (backend/frontend 모두 성공).

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 원문 후보/누락 검사 | `02265c4`, 구현 및 회귀 검증 |
| 2 | 상위 문맥/각주/요청 분할 | `b875769`, 구현 및 회귀 검증 |
| 3 | 후보별 호출/미응답 재처리 | `da380d5`, 구현 및 회귀 검증 |
| 4-A | 원문 복원/수치 역할/논리 구조 | `ebbfb46`, 구현 및 회귀 검증 |
| 4-B | 의미 응답/그래프/기존 판정기 | `ba2851e`, 내부 경로 연결 및 합성 검증 |
| 5 | 상태 축/현재 결과 선택/읽기 API | `7fdf5e5`, 상태 계약/읽기 API 구현 |
| 6-A | 전체 검색 범위 목록·필터·집계 | `1e1f5b2`, 프론트 연결 |
| 6-B | 상세 상태·근거·쓰기 후 재조회 | `4690559`, 프론트 연결 |
| 7-A | 전체 빌드/회귀/Chromium 검증 | **이번 통과. 발견된 타입/라우터 조립 문제 수정** |
| 7-B | 남원글로컬 동일 입력 반복 실측 | **측정기 구현·17개 테스트 통과. 대상 DB/실모델은 미실행** |
| 7-C | 새 그래프 제품 경로·변경 재검증/Copilot 운영 E2E | **남은 연결·검증 필요** |

전체 CI 성공은 남원글로컬 실측이나 새 그래프의 제품 기본 경로 전환 완료가 아니다.
7단계 전체 완료로 처리하지 않는다.

## 이번 실제 검증

GitHub Actions의 일회용 PostgreSQL 16/Python 3.12 및 Node 22/pnpm 10.15.0에서 수행했다.
프로젝트 의존성·lockfile을 그대로 설치했으며 전체 TypeScript 검사와 vinext 빌드를 실행했다.

- backend: **1444 passed / 1 skipped / 0 failed**. JUnit total 1445.
- Node: **148 passed / 0 skipped / 0 failed**.
- 전체 `pnpm exec tsc --noEmit`, `pnpm build`: 성공.
- 기존 Copilot 클라이언트 계약 검사 스크립트 5개: 성공.
- 실제 PostgreSQL migrations, 실제 앱 OpenAPI/mapper 등록: 성공.
- 기존 골든 회귀 실행: 성공. 골든셋·기대값·평가기 파일은 수정하지 않았다.
- 실제 React/Chromium + 합성 HTTP 6흐름: 성공. pageerror/예상 밖 API 요청 0.
- 신규 반복 측정기 테스트 17개는 위 backend 수에 포함된다. 별도로 중복 합산하지 않는다.

1 skipped는 jsonschema가 프로젝트 개발 의존성에 없어 기존 importorskip이 적용된 테스트다.
운영 DB·실제 모델 테스트를 합성 테스트 통과 숫자에 포함하지 않는다.

## 실제 통합에서 수정한 결함

1. detail API의 Response.json 오류 본문을 unknown에서 검사하도록 수정 — 전체 tsc TS2339 2건 해결.
2. state/catalog 라우터를 독립 모듈로 유지하고 상위 judgment 라우터에서 조립 — 분리 테스트의 불필요한 의존성 제거.
3. catalog 테스트의 실제 등록 대상을 새 조립 구조에 맞춤. 기존 assertion/기대값은 유지.
4. 실제 HTTP/OpenAPI를 검사하도록 앱 경로 테스트 보강. 내부 라우팅 자료형에 의존하지 않음.

## 실제 브라우저로 확인한 것

공사 필터의 서버 전달, 상태가 선택한 판정/근거, 재판정 시 재추출 금지,
프로필 변경 상태와 `—` 건수, 저장 후 GET 실패의 읽기 전용 복구, 503과 미검토 구분을 확인했다.
스크린샷의 회사/공고는 `[합성 검증]` 자료이며 실제 데모 자료를 공개 저장소에 옮기지 않았다.

## 실제 반복 실측 도구

`python -m apps.api.app.scripts.check_qualification_repeatability`

- 기본은 READ ONLY 캡처. `--live-model`이 있어야 실제 모델 호출.
- 정확한 case/공고번호/차수/회사/기준일을 고정한다.
- 새 PostgreSQL READ ONLY 트랜잭션에서 읽고 세션을 닫은 뒤 모델을 호출한다.
- legacy/review_v1/review_graph_v1의 의미·판정·입력 지문과 진단을 비교한다.
- 실제 PostgreSQL에서 의도하지 않은 UPDATE가 차단됨을 테스트했다.
- 원문/모델 응답/회사 상세는 보고서에 복제하지 않는다. 내부 식별자는 비공개로 보관한다.
- 안정성은 정확도가 아니다. quality_verdict는 NOT_ESTABLISHED로 남긴다.

현재 assistant 환경에는 나라장터 DB/모델 키가 구성되지 않아 실제 데모 공고 측정은 실행하지 못했다.
실행 방법과 검증 구분은 `08-stage7-integration-verification.md`에 있다.

## 남은 연결과 기준

- 새 의미 그래프는 내부 명시적 Python 경로다. 기존 제품 HTTP 분석은 legacy를 유지한다.
- 공고 전체 조항 간 적용·예외, 그래프 저장/API 연결 및 실모델 원문 정답 검증이 필요하다.
- 서로 다른 판정 기준을 사용하는 다른 화면/Copilot의 운영 E2E 일치 여부는 별도다.
- 남원글로컬의 회사 정보와 기준일을 확인하고 정상 미달과 추출 오류를 구분해야 한다.
- 캐시/유리한 실행 선택/회사 정보 변경/골든 정답 변경으로 실측을 대신하지 않는다.
- develop/main 미병합. PR #136 미병합. DB 스키마·판정 규칙·Copilot 소스·lockfile 유지.

이 문서 갱신 commit은 문서만 변경한다. 위 검증 commit/run과 문서 head를 구분한다.
