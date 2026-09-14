# 5단계 — 상태 축과 현재 결과 선택

부모 commit `ba2851e`, 브랜치 `refactor/qualification-reliability`.
운영 배포나 전체 제품 성능 실측이 아니라 상태 계약/읽기 경로 구현 기록이다.

## 1. 상태를 하나의 null/성공 값으로 합치지 않는다

| 필드 | 의미 |
|---|---|
| lookup_state | 조회 성공/실패 |
| execution_state | 분석 미실행/진행 중/성공/부분 성공/실패 |
| coverage_state | 후보 처리 기록: UNVERIFIED/COMPLETE/INCOMPLETE/INVALID/EMPTY |
| judgment_state | 저장 판정 없음/있음/재판정 필요/차단/자료 불일치 |
| freshness_state | 검사한 기준 일치/불일치/검사 미완료/확인 불가 |
| display_state | 상태로부터 만든 표시 코드. 기존 overall_status와 다름 |
| stored_overall_status | 읽은 저장 판정이며 현재 참가 여부를 새로 계산한 값이 아님 |

RESULT_AVAILABLE에서도 coverage가 UNVERIFIED일 수 있다. 저장 결과의 존재와 원문 전체의
완전성을 구분한다. full_notice_eligibility_asserted는 false다. PARTIAL의 저장 판정을 다른
판정으로 수정하지 않고 분석 경고를 별도 표시한다. 프론트는 경고/기준과 함께 표시해야 한다.
미검토/회사 판정 필요/분석 불완전/재판정 필요/조회 실패를 구분한다.
INFO인 REVIEW_EXECUTION_AUDIT 자체를 오류로 보지 않는다. 다만 COMPLETE/건수/누락 목록이
모순되면 INVALID다. legacy SUCCEEDED에는 후보 기록이 없으므로 UNVERIFIED다.
현재 DB는 종료 상태 3종만 저장한다. RUNNING/PENDING은 순수 계약에서 지원하며 작업 큐에
연결해 실시간 진행 상태를 읽는 기능까지 추가한 것은 아니다.

## 2. 현재 결과 선택

1. 허용된 case/company/notice version 범위만 고려한다.
2. 최신 분석을 created_at, id 순으로 선택한다. 요건 수나 원하는 판정을 기준으로 고르지 않는다.
3. 최신 분석이 실패/진행 중이면 과거 성공으로 돌아가지 않는다.
4. 최신 분석 + 차수 + 회사 + case + 현재 rule_version에 맞는 최신 판정만 후보로 둔다.
5. 선택한 결과가 잘못됐다고 예전 결과로 대체하지 않는다.
6. 분석 상태/요건 키/근거 연결을 확인한다.
7. 저장 프로필 JSON과 현재 프로필 JSON 지문 및 요청 기준일을 비교한다.
8. 달라지면 REJUDGMENT_REQUIRED다. observed_judgment_run_id와 selected_judgment_run_id를 구분한다.

프로필의 알 수 없는 필드/배열 순서는 보존한다. 정렬만 달라져도 보수적으로 재판정이 필요할
수 있다. 임의 정규화로 의미 차이를 숨기지 않으며 기존 스냅샷 생성기의 정렬은 유지한다.

기준일을 생략하면 저장 기준일을 보여주되 날짜 최신성을 검사했다고 주장하지 않는다.
reference_date_check=NOT_REQUESTED, freshness=CHECKS_INCOMPLETE다. date.today()를 넣지 않는다.
사용자 답변 기반 판정에는 충분한 답변 revision/hash 연결이 없어 answer_basis_check=UNVERIFIED다.
저장 답변을 설명할 수 있지만 현재 답변까지 검증했다는 뜻은 아니다. 쓰기 확인 버튼은 유지한다.

## 3. 읽기 전용 API

```text
GET /api/v1/preflight-cases/{case_id}/qualification-state
GET /api/v1/preflight-cases/{case_id}/qualification-state?reference_date=YYYY-MM-DD
```

기존 qualification/routers/judgment.py가 state router를 포함한다. /api/v1을 중복하지 않는다.

- authorize_case_access부터 적용하고 다른 회사의 상태를 노출하지 않는다.
- 권한 조회와 상태 조회 모두 no_autoflush 안에서 수행한다.
- 모델 호출/규칙 재판정/분석 및 판정 생성/commit/결과 포인터 갱신을 하지 않는다.
- 최신 분석 1건, 현재 기준 판정 1건. 없을 때 최근 과거 판정 1건은 사유 분류에만 사용한다.
- 전체 판정 목록을 상위 100건으로 잘라 현재 판정을 놓치는 구조가 아니다.
- 조회 중 최신 분석 ID/상태 변경을 재확인하면 409 QUALIFICATION_STATE_CHANGED로 재조회한다.
- 이 재확인은 프로필/답변의 모든 동시 변경을 검출하는 snapshot isolation/CAS가 아니다.
  쓰기 작업은 쓰기 경계에서 최신성과 권한을 재검증해야 한다.
- DB 오류는 503 QUALIFICATION_STATE_UNAVAILABLE이며 성공한 빈 목록으로 바꾸지 않는다.
- 파싱 불가 자료는 409 QUALIFICATION_STATE_INVALID. 감지된 연결 불일치는 DATA_INVALID다.
- 기존 권한 오류/404는 유지하고 SQL/DB 주소/예외 원문을 응답하지 않는다.

응답은 ID/상태/기준일/고정 사유 코드/지문이다. 원문/회사 상세/모델 사유는 포함하지 않는다.
state_sha256은 응답 비교용이며 쓰기용 낙관적 잠금 토큰이 아니다. 기존 판정 상세는 그대로다.

## 4. 4-B 의미 분석 연결

```python
from app.qualification.semantic_state import analyze_semantics_with_state

outcome = analyze_semantics_with_state(
    analysis_input,
    structured_extract=extractor,
    profile=company_snapshot,
    preflight_case_id=case_id,
    reference_date=reference_date,
    anchor_dates=anchor_dates,
)
# outcome.analysis: 기존 SemanticAnalysis를 그대로 보존
# outcome.state: 조항 수준 상태. 상세 원문/회사 자료 복사 없음
```

후보/판정 연결, 처리 건수, 회사/문맥/규칙 혼합을 검사한다. 실행 누락, 의미 미해결,
회사 자료 부족을 구분하고 선호 조건 미달을 필수 미달로 올리지 않는다. 전체 조항 관계를
임의 ALL_OF로 만들지 않으며 notice_overall_status는 None이다. semantic_coverage COMPLETE는
알려진 미해결이 없다는 처리 기록이지 자연어 의미의 정확성 증명이 아니다.
현재 HTTP 분석 기본값에 이 wrapper를 연결하거나 그래프를 DB에 저장하지 않았다.

## 5. 검증

```bash
python -m pytest -v apps/api/tests/test_qualification_state.py \
  apps/api/tests/test_qualification_state_api.py
```

Python 3.13.5 / pytest: **90개 통과** (65개 + 25개).

- 실제 상태 선택/의미 상태 코드를 합성 스냅샷으로 검증.
- 실제 state_service 쿼리를 SQLite 최소 스키마와 SQLAlchemy Session으로 실행.
- 실제 새 라우터를 분리 FastAPI에 등록해 GET/경로/직렬화/오류를 검증.
- 운영 PostgreSQL ORM/인증/스냅샷 생성은 대역. 전체 운영 스키마 검증은 아니다.
- 의미 wrapper 테스트는 4-B 호출을 대역으로 바꿔 전달/상태 추가만 검사한다.
- 읽기 중 쓰기 SQL 없음, 권한 조회의 pending flush 없음 확인.
- 최신 실패/분석 변경/규칙 변경/프로필 변경/날짜 변경, 참조 불일치/빈 요건/중복 판정,
  사용자 답변 최신성 미검증, DB 오류 503, 권한 오류 403, 날짜 오류 422 확인.
- 조회 도중 최신 분석 변경의 409 처리 확인.
- 변경 Python 구문 컴파일 통과. 수정한 기존 라우터의 부모 blob SHA 일치 확인.

미실행: 이전 단계/전체 API 회귀, 실제 PostgreSQL/마이그레이션/전체 앱 부팅,
실제 LLM/J14/구내식당, 브라우저/Copilot/변경공고 E2E 및 GitHub CI.
이 숫자를 모델 정확도/추출 재현율 개선 수치로 사용하지 않는다.

## 6. 다음 단계

프론트 목록/상세가 null을 미검토로 바꾸는 대신 새 상태 계약을 사용하도록 한다.
매칭과 저장 판정은 서로 다른 경로이므로 출처/범위를 숨기지 않고 같은 기준으로 연결한다.
검색/사업 유형/상태 집계는 상위 100건이 아닌 동일 검색 범위로 설계한다.
Copilot 정책 변경은 병렬 작업과 함께 검증하고, 전체 공고 범위/조항 관계를 검증하기 전
그래프를 기존 저장 형식에 평탄화하지 않는다. develop/main 병합이나 DB 변경은 하지 않았다.
