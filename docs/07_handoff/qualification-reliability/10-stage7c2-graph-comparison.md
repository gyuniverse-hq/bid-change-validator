# 7-C2 — 공고 그래프 저장·회사 판정·변경 비교

작업 브랜치: `refactor/qualification-reliability`.
시작: `c9d2aad73cb078ac26affb7ca20d21b43b7cb599`.
구현 commit: `cee51a529b4ba141adbaec65715d681863d66e1b`.
검증 코드 commit: `fc485296b8762049cf6903ee8d031f71c893e140`.
최종 CI: `34929357223`, backend/frontend 모두 성공.

사용자가 요청한 범위는 **Copilot을 제외하고 변경 비교까지**다.
이번에는 공고 그래프 분석→저장→회사 판정→두 실행 비교의 별도 API/화면을 연결했다.
기존 `legacy`, `review_v1`, 현재 저장 판정 선택 정책, Copilot 소스/동작은 변경하지 않았다.
실제 남원글로컬 공고의 정확도와 반복성 실측은 아직 수행하지 않았다.

## 1. 분석과 판정의 분리

`graph/document.py`는 회사 자료 없이 원문 블록과 문서 명세만 입력받는다.
기존 후보·근거·조항 그래프 해석기를 재사용하고, 별도 관계 해석으로 조항들을 연결한다.
관계 결과도 원문에 연결하고 전체 필수/미해결 후보가 빠짐없이 포함됐는지 검사한다.

회사 정보를 넣은 판정은 `graph/judgment.py`에서 별도로 수행한다.
저장 그래프를 읽어 기존 `judge_semantic_decision`과 실제 회사 판정기를 호출하며, LLM은 다시 호출하지 않는다.
조항별 결과를 ALL_OF/ANY_OF/NOT/EXEMPT_IF/POSSIBLE_EXEMPT_IF 관계대로 계산한다.
재량 면제 표현은 예외 사유가 참이어도 자동 면제로 확정하지 않는다.
미처리 원문/관계가 있으면 확인 필요 상태를 보존한다. 처리 완료가 의미 해석의 정답 보증은 아니다.

## 2. 전용 저장 구조

추가 마이그레이션 `023_qualification_graphs`:

- `qualification_graph_runs`: 공고 차수, 원문 스냅샷, 조항별 해석, 조건 그래프, 관계·근거, 해시, 처리 진단.
- `qualification_graph_judgment_runs`: 선택 그래프, 검토 건/회사, 기준일/규칙, 회사 스냅샷, 조항·그룹별 판정.

JSONB 저장 계약에 버전을 두고, 조회 시 타입/원문 구간/원자 의미/관계 및 지문을 다시 검증한다.
이전 실행을 갱신하는 API는 없으며 항상 새 실행을 추가한다. 기존 슬롯 분석 테이블에 그래프를 평탄화하지 않는다.
RLS를 활성화하고 backend 전용 역할이 존재할 경우 read/insert 정책을 추가한다.
API는 기존 검토 건의 회사 접근 권한을 확인한다. 공용 운영 DB에 마이그레이션을 실행하지 않았다.

원문이나 회사 정보가 읽은 이후 바뀌었는지 저장 전에 다시 대조한다.
이 대조는 관측 기반이며 완전한 CAS/직렬화 격리/동시 POST 멱등성을 보증하지 않는다.

## 3. 변경 비교

두 저장 실행 ID를 명시해서 GET으로 비교한다. 최신 실행을 임의로 고르지 않으며 비교 중 모델/DB 쓰기는 없다.
같은 공고 차수의 반복 분석도 비교할 수 있다. 이 경우 mode는 REPEATED_ANALYSIS다.

| 상황 | 분류 |
|---|---|
| 원문·구조화 의미·관계가 같음 | UNCHANGED |
| 원문 표현이 바뀌고 구조화 의미는 같음 | TEXT_CHANGED |
| 대응되는 원문과 조건 값/범위 등이 바뀜 | MODIFIED |
| 실제 원문에 추가/삭제가 확인되고 처리·대응이 충분함 | ADDED / REMOVED |
| 동일 원문에서 요건이 빠지거나 의미·관계만 달라짐 | ANALYSIS_INCONSISTENCY |
| 미처리 첨부, 애매한 문서 대응, 조항 분할/합침, 불명확 관계 | REVIEW_REQUIRED |

문서는 동일 내용 또는 유일한 파일명+수집 필드로 대응시킨다. 조항은 유일한 원문 일치를 우선 사용한다.
한 구간의 1:1 원문 수정은 유사도 기준을 추가 확인하고, 다대다·중복·이동 가능성은 확정하지 않는다.
이 자동 매칭은 휴리스틱이며 정확한 버전 간 동일성의 수학적 보증은 아니다.
현재 비교 정책은 보수적으로 처리하므로 조항 번호 변경/문서명 변경 등에서 수동 검토가 필요할 수 있다.
값이 바뀌었다고 단순히 삭제+추가로 만들지 않고, 대응 정보와 의미 내용 지문을 분리한다.
원문을 정규화할 때 내부 공백을 모두 제거하지 않아 '1 2'와 '12'를 같은 문자열로 만들지 않는다.

비교는 원문과 저장된 해석의 차이다. 변경만으로 회사의 참가 가능 전환을 확정하지 않는다.
자동 변경 재판정/제출·증빙 반영 및 Copilot은 이번 연결 범위가 아니다.

## 4. API와 화면

```
GET  /api/v1/qualification-graph-options
GET  /api/v1/preflight-cases/{case_id}/qualification-graphs
POST /api/v1/preflight-cases/{case_id}/qualification-graphs
GET  /api/v1/preflight-cases/{case_id}/qualification-graphs/{run_id}
POST /api/v1/preflight-cases/{case_id}/qualification-graph-judgments
GET  /api/v1/preflight-cases/{case_id}/qualification-graph-judgments/{judgment_id}
GET  /api/v1/preflight-cases/{case_id}/qualification-graphs/compare?baseline_run_id=...&current_run_id=...
```

POST 분석은 `{version_role: baseline|current}`만 받는다. 모델·예산·회사 자료를 클라이언트가 임의 지정하지 않는다.
POST 판정은 `{graph_run_id, reference_date}`가 필요하고 오늘 날짜를 자동 대입하지 않는다.
새 실행에는 서버 `QUALIFICATION_GRAPH_ENABLED=true` 설정과 023 마이그레이션이 필요하다. 기본값 false.
기존 환경의 활성화·배포 설정을 이번 작업에서 변경하지 않았다.

화면: `/qualification-graph?caseId=...`.
기존 참가자격 페이지에 이동 링크만 추가했고 기존 화면/Copilot 작업은 바꾸지 않았다.
기준·현재 그래프 분석, 저장 목록 조회, 명시적인 두 실행 선택, 회사 재판정, 원문·조건·관계 비교를 제공한다.
동일 원문 추출 불일치와 조회 실패를 변경 없음으로 표시하지 않는다. 이전/현재 원문을 나란히 보여준다.
분석·판정 POST를 자동 재시도하지 않는다. 저장 응답을 확인했으나 후속 조회가 실패하면 읽기 재조회만 안내한다.
최근 100개 실행만 표시하고 전체가 아닐 수 있음을 명시한다. 기존 '현재 판정'으로 자동 승격하지 않는다.

## 5. 실제 실행 검증

GitHub Actions의 일회용 PostgreSQL16/Python3.12/Node22, 프로젝트 lockfile 그대로 설치.
원문·회사·모델 응답은 합성이고 실제 모델 네트워크 호출은 없다.

| 항목 | 결과 |
|---|---|
| Backend 전체 | **1499 passed / 1 skipped / 0 failed**, JUnit total1500 |
| 신규 그래프 단위 테스트 | 25개, 위 수에 포함 |
| 신규 실제 PostgreSQL/API 저장·판정·비교 | 15개, 위 수에 포함 |
| Node 전체 | **180 passed**, 신규 그래프 계약17개 포함 |
| 전체 tsc / frontend build | 성공 |
| 023 포함 PostgreSQL migrations / 기존 골든 회귀 | 성공 |
| 기존 합성 Chromium 흐름 | 7개 재통과 |
| 신규 그래프 Chromium 흐름 | **2개 통과**, pageerror/예상 밖 요청0, POST0 |

1 skipped는 기존 jsonschema 선택 의존성 검사다. 새 저장/비교 테스트를 건너뛴 것이 아니다.
전체 회귀의 기존 Copilot 계약 스크립트도 그대로 실행했으나 신규 연결이나 소스 수정은 하지 않았다.
CI 보고서·JUnit·Node 로그·브라우저 result.json을 내려받아 확인했다.
데스크톱1440px/모바일390px 캡처를 확인했다. 캡처 자료는 실제 남원글로컬 공고가 아니라 `[합성]` 테스트다.

검증 사례: 원문/그래프 JSON 왕복, 같은 분석의 다른 회사 재판정 시 모델 미호출,
원문 금액 변경을 MODIFIED로 식별, 같은 원문 누락은 분석 불일치, 실제 원문 삭제와 누락 첨부 구분,
AND→OR 관계 변화, 재량 면제 확인 필요, 타회사 권한, 잘못된 차수/방향, 변조된 저장 데이터 거부,
저장 후 원문 변경 시 재판정 중단, 비교 SQL 쓰기 없음, 실패 응답의 오인 방지.

## 6. 남아 있는 한계

- 실제 남원글로컬 R26BK01684863의 현재 원문·회사·기준일을 사용한 실제 LLM 반복 실측은 미실행이다.
- 원문 의미의 정답 검증과 조항간 적용의 정답은 모델 및 검수에 의존한다. 근거 참조 검증만으로 보증하지 않는다.
- 여러 문서에 걸친 적용, 기존 컴파일러의 CONTEXT_DEPENDENT 보류, 장비·허가 사실의 모델링/입력은 모두 해결한 것이 아니다.
- '요구하지 않을 수 있다'는 자동 승인하지 않는다. 실제 적용 근거·회사 자료 입력은 별도 작업이다.
- 그래프 결과를 기존 공통 상태/목록의 현재 판정으로 자동 선택하지 않는다. 별도 그래프 화면에서 확인한다.
- 변경 비교만 연결했다. 자동 영향 재판정·Copilot 연결은 보류한다.
- 새 저장 데이터/모델 호출 비용·성능, 대규모 원문 범위, 동시 쓰기 멱등성은 운영 검증이 남아 있다.

Copilot 소스·골든셋·평가기·기존 판정 규칙은 변경하지 않았다. develop/main 미병합.
이 연결 검증을 실제 공고 정확도 향상/발표 데모 성능 확보로 표현하지 않는다.
