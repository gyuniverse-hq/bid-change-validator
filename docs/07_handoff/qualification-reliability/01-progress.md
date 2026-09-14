# 공고 분석·판정 일관성 개선 — 진행 현황

## 기준

- 브랜치: `refactor/qualification-reliability`
- 출발: `develop`의 `c510c3e` (Copilot #139 포함)
- 1단계 `02265c4`: 원문 후보 ID/응답 누락 검사
- 2단계 `b875769`: 조항 문맥/요청 분할
- 3단계 `da380d5`: 후보별 호출/제한된 미응답 재처리
- 4-A `ebbfb46`: 원문 복원/수치 역할/조건 그래프
- 4-B `ba2851e`: 의미 응답/그래프/기존 회사 판정기 연결
- 현재: **5단계 상태 계약·저장 결과 선택·읽기 API 구현/분리 환경 검증 완료**
- 다음: **6단계 목록/매칭/상세 화면의 상태 소비와 검색·집계 연결**

## 전체 순서

| 단계 | 작업 | 상태 |
|---|---|---|
| 1 | 후보 ID·누락 검사 | 이전 구현 완료 |
| 2 | 상위 문맥·각주·요청 분할 | 이전 구현 완료 |
| 3 | 후보별 추출 호출·미응답 재처리 | 이전 구현 완료 |
| 4-A | 원문 복원·역할별 값·논리 구조 | 이전 구현 완료 |
| 4-B | 의미 응답·그래프·기존 판정기 연결 | 이전 코드 연결/합성 입력 검증 완료 |
| 5 | 실행/검토 완전성/판정/기준 유효성, 현재 결과 선택 | **이번 구현 및 90개 검증 통과** |
| 6 | 목록 필터·집계·매칭/상세 연결 | **다음 작업** |
| 7 | 실제 LLM/DB·변경 재검증·Copilot 전체 검증 | 대기 |

단계 완료는 해당 코드와 기록된 검증 범위에 한정한다. 실제 추출 성능 또는 제품 전체가
검증됐다는 뜻이 아니다. 이전 단계의 테스트 개수를 이번 실행 수에 합산하지 않는다.

## 5단계에서 연결한 것

- `qualification/state_contract.py`: 실행/coverage/저장 판정/freshness 상태와 부작용 없는 선택 함수.
- `qualification/state_service.py`: 기존 ORM/회사 스냅샷을 읽는 DB 어댑터. 읽기 전용/no_autoflush.
- `qualification/routers/state.py`: 기존 판정 라우터에 등록한 GET 상태 API.
- `qualification/semantic_state.py`: 4-B 실행 결과에 조항 수준 상태를 부여하는 명시적 진입점.

```text
GET /api/v1/preflight-cases/{case_id}/qualification-state
GET /api/v1/preflight-cases/{case_id}/qualification-state?reference_date=2026-09-15
```

최신 분석 우선/current-rule 정책을 유지한다. 실패한 최신 분석을 과거 성공으로 숨기지 않는다.
저장된 판정의 분석·차수·회사·규칙·요건/근거 연결을 확인하고 회사 스냅샷/요청 기준일도 대조한다.
프로필/기준일 변경은 재판정 필요, 조회 실패는 503, 잘못된 자료는 명시적인 오류/상태다.
읽는 도중 최신 분석 ID/상태가 바뀌면 409로 재조회를 요구한다.

`stored_overall_status`는 저장 사실이며 새 판정이 아니다. 선택한 판정 ID와 관측한 판정 ID를
구분한다. legacy SUCCEEDED를 coverage COMPLETE로 간주하지 않는다. 사용자 답변의 최신성은
현재 저장 계약만으로 검증하지 못하므로 UNVERIFIED다. 기준일 생략 시 오늘을 대입하지 않는다.

## 이번 검증

Python 3.13.5, pytest: **90개 통과**.

- 65개: 실제 상태 선택/coverage/조항 상태 함수, 합성 스냅샷 입력.
- 25개: 실제 조회 서비스 SQL과 상태 라우터, SQLite 최소 스키마/분리 FastAPI.
  운영 ORM/인증/회사 스냅샷 생성은 대역이며 SQLAlchemy Session과 GET 요청은 실제 실행.
  이 중 의미 wrapper 1개 테스트는 4-B 호출을 대역으로 교체해 전달/상태 추가만 검증.
- Python 구문 컴파일 통과. 기존 judgment router는 부모 blob 일치 확인 후 경로 등록만 추가.

실행 명령과 제한은 `05-step5-state-and-selection.md`에 기록했다.
운영 PostgreSQL/마이그레이션, 전체 앱 부팅/기존 API 회귀, 실제 LLM/J14/구내식당,
브라우저/Copilot/변경공고 E2E 및 GitHub CI는 이번에 실행하지 않았다.

## 보존한 경계와 남은 작업

- develop/main 미병합. PR #136 미병합. Copilot/기존 판정 규칙/골든셋/평가기/DB 스키마 그대로.
- 기존 HTTP 응답은 유지하고 새 GET만 추가했다. 새로운 모델 추출 기본값은 켜지 않았다.
- 프론트/매칭/Copilot의 새 상태 소비는 6단계다. 화면이 이미 바뀐 것은 아니다.
- 의미 경로의 전체 공고 적용 관계는 아직 미검증이다. 조항들을 임의 AND로 합치지 않는다.
- 전체 공고의 응찰 가능 여부를 이 상태 계약으로 새로 계산/확정하지 않는다.
- 조회는 관측 결과이며 쓰기 시점의 권한/최신성/동시성 검증을 대체하지 않는다.

## 상세 기록

- `00-start-and-boundaries.md`: 시작과 병렬 작업 경계
- `02-step3-execution.md`: 호출/재시도 계약
- `03-step4a-source-and-conditions.md`: 원문 복원/논리 기반
- `04-step4b-semantics-and-judgment.md`: 의미 응답/실제 판정기 연결
- `05-step5-state-and-selection.md`: 상태/결과 선택/GET API/검증 범위
