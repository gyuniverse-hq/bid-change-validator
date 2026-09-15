# 공고 분석·판정 일관성 개선 — 진행 현황

브랜치 `refactor/qualification-reliability`, 출발 `c510c3e` (Copilot #139 포함).
주 검증 대상: **전북대학교 남원글로컬캠퍼스 본관동 생활폐기물 처리 용역** (`R26BK01684863`).
현재: **7-C1 조항별 누락 검토(review_v1)의 선택형 제품 실행·저장 연결과 전체 CI 통과**.
검증된 코드 commit: `3031bb7b7209244c654ecbdaeb1de9d1b1dce689`.
최종 코드 검증 run: `34922535098` (backend/frontend 모두 성공).
실제 대상 DB/실모델 측정과 복합조건 그래프의 공고 전체 제품 연결은 남아 있다.

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
| 7-A | 전체 빌드/회귀/Chromium 검증 | 전체 검증 통과 및 이번 변경으로 재실행 |
| 7-B | 남원글로컬 동일 입력 반복 실측 | 측정기 구현/검증 완료, 대상 DB/실모델 미실행 |
| 7-C1 | review_v1 선택 → 분석 API → 저장 → 판정 → 상태 조회 | **이번 연결 및 합성 자료 전체 검증 통과** |
| 7-C2 | 복합조건 그래프의 전체 공고 적용·저장·제품 판정 | **남은 구현/검증** |
| 7-C3 | 실제 변경 재검증·Copilot 운영 E2E | **남은 연결/검증** |

`review_v1`은 슬롯형 계약의 조항별 누락 검사이고, `review_graph_v1`과는 다르다.
전체 CI 성공을 실제 남원글로컬 정확도나 그래프의 제품 기본 경로 전환 완료로 취급하지 않는다.
7단계 전체 완료로 처리하지 않는다.

## 이번 실제 검증

GitHub Actions의 일회용 PostgreSQL 16/Python 3.12 및 Node 22/pnpm 환경에서 수행했다.
프로젝트 의존성·lockfile을 그대로 설치하고 전체 타입 검사·빌드·실제 Chromium을 실행했다.

- Backend **1459 passed / 1 skipped / 0 failed**, JUnit total 1460.
- Node **163 passed / 0 failed**.
- 새 Backend 15개 및 Node 전략 계약 15개는 위 전체 수에 포함된다. 로컬 실행과 중복 합산하지 않는다.
- PostgreSQL에서 POST 분석 → 기존 테이블 저장 → GET → 실제 회사 판정 → 상태/카탈로그 일치 검증 통과.
- 모델/원문/회사 자료는 합성이다. 위 저장 테스트는 실제 모델 정확도나 복합조건 정답 검증이 아니다.
- 전체 `pnpm exec tsc --noEmit`, `pnpm build` 및 기존 Copilot 클라이언트 계약 검사 5개 통과.
- PostgreSQL migrations, 기존 골든 회귀 통과. 기대값/평가기 변경 없음.
- 실제 React/Chromium + 합성 HTTP **7흐름 통과**. pageerror/예상 밖 API 0.
- 1 skipped는 기존 jsonschema 선택 의존성 검사다. 이번 신규 저장 왕복 테스트는 CI에서 실행·통과했다.

이전 기준 `c4463df` / run `34907225441`의 결과(Backend 1444, Node 148, Chromium 6흐름)는
`08-stage7-integration-verification.md`에 보존한다. 이번 결과와 누적하지 않는다.

## 이번에 제품 경로로 연결한 것

- 기존 분석 POST에 optional `extraction_strategy`를 추가. 생략하면 legacy다.
- 서버 `QUALIFICATION_REVIEW_V1_ENABLED` 기본 false. 활성화 여부를 GET options로 제공한다.
- 화면에서 허용된 방식을 명시적으로 선택하고 새 분석을 실행한다. 회사 재판정은 추출하지 않는다.
- 기존 경로/미확인 분석을 review_v1의 결과로 재사용하지 않고, 저장 응답의 실제 경로를 검사한다.
- 원문 입력과 첨부 상태 지문/경로/모델/예산을 기존 진단 JSON에 보존하고 상세 응답에 노출한다.
- 누락 첨부는 review 분석 PARTIAL, 실행 중 원문 변화는 저장 전 중단한다.
- 새 분석은 새 실행으로 저장한다. 과거 실행을 덮거나 유리한 결과로 fallback하지 않는다.
- 기존 상태·판정·근거 계약을 사용하며 DB 스키마는 바꾸지 않았다.
- 실제 배포 환경이나 사용자의 로컬 폴더는 변경하지 않았다. 켜지지 않은 서버에서 새 모드를 자동 실행하지 않는다.

## 이전 통합에서 수정한 결함

1. detail API의 Response.json 오류 본문을 unknown에서 검사하도록 수정 — 전체 tsc TS2339 2건 해결.
2. state/catalog 라우터를 독립 모듈로 유지하고 상위 judgment 라우터에서 조립.
3. catalog 테스트의 등록 대상을 새 조립 구조에 맞춤. assertion/기대값 유지.
4. 실제 HTTP/OpenAPI를 검사하도록 앱 경로 테스트 보강. 내부 라우팅 자료형에 의존하지 않음.

## 실제 반복 실측 도구

`python -m apps.api.app.scripts.check_qualification_repeatability`

- 기본은 READ ONLY 캡처. `--live-model`이 있어야 실제 모델 호출.
- 정확한 case/공고번호/차수/회사/기준일을 고정한다.
- 새 PostgreSQL READ ONLY 트랜잭션에서 읽고 세션을 닫은 뒤 모델을 호출한다.
- legacy/review_v1/review_graph_v1의 의미·판정·입력 지문과 진단을 비교한다.
- 실제 PostgreSQL에서 의도하지 않은 UPDATE 차단 테스트가 통과했다.
- 원문/모델 응답/회사 상세는 보고서에 복제하지 않는다. 내부 식별자는 비공개로 보관한다.
- 안정성은 정확도가 아니다. quality_verdict는 NOT_ESTABLISHED로 남긴다.

현재 실행 환경에는 나라장터 DB/모델 키가 구성되지 않아 실제 데모 공고 측정은 실행하지 못했다.
실행 방법과 검증 구분은 `08-stage7-integration-verification.md`에 있다.

## 남은 연결과 기준

- 새 의미 그래프는 내부 명시적 Python 경로다. HTTP는 legacy와 허용된 review_v1만 받는다.
- 공고 전체 조항 간 적용·예외, 그래프 저장/API 연결 및 실모델 원문 정답 검증이 필요하다.
- 다른 화면/Copilot의 운영 E2E 일치 여부는 별도다. 이번에는 Copilot 소스를 변경하지 않았다.
- 남원글로컬의 실제 회사 정보와 기준일을 확인하고 정상 미달과 추출 오류를 구분해야 한다.
- 캐시/유리한 실행 선택/회사 정보 변경/골든 정답 변경으로 실측을 대신하지 않는다.
- source 전후 비교는 쓰기 CAS/완전한 동시성 보증이 아니다. 운영 자원·성능 확인도 남는다.
- develop/main 미병합. PR #136 미병합. DB 스키마·판정 규칙·Copilot 소스·lockfile 유지.

이번 연결/설정/검증/한계는 `09-stage7c-product-extraction.md`에 기록했다.
이 문서 갱신 commit은 문서만 변경한다. 위 코드 검증 commit/run과 문서 head를 구분한다.
