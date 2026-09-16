> **과거 작업 이력 — 2026-09-16 이관.** 아래 본문은 이전 feature 브랜치 당시 기록입니다. 검사 결과·미완료 항목·승인 및 push 상태를 현재 상태로 해석하지 마세요. 최신 상태는 [45번 보고서](45-pipeline-result-and-next-step.md), 다음 설계는 [46번 제안](46-guided-job-ui-transition.md), 이관·근거 위치는 [47번 안내](47-workspace-consolidation.md)를 따릅니다. 본문의 증거 폴더와 `.ci-results` 경로는 원래 저장소 기준이며 증거를 새 브랜치에 복사하지 않았습니다.

# 남원글로컬 지정 사례 검증 및 Q-005 — 2026-09-14

## 결과

사용자가 지정한 `R26BK01684863`의 Golden J13~J16을 실제 로컬 PostgreSQL 제품 판정 경로로 실행했다. **네 프로필 모두 운반 요건 UNKNOWN / UNSUPPORTED_REQUIREMENT**다. 전체 판정도 모두 `insufficient_data`다. J13·J14·J15는 원본 Golden의 운반 조건 기대값과 달라 검사 FAIL이다. J16은 UNKNOWN이 우연히 일치하지만 예외 정보의 미확인 경로가 연결됐다는 증거가 아니다.

실행 근거: `flow-evidence/copilot-db-20260914T065052Z/namwon-results.json`, `tests.xml`, `run.log`. 1 pytest failed, 1.04초. 네 프로필 관찰을 네 pytest 통과로 보고하지 않는다.

원본은 로컬 Downloads의 `golden_fixtures_v02.zip`이며 SHA256은 `0d29c1b6dd7acb5dfbe061b36973f1759b2a54c2c09e65bde4a1bcedb4c68a89`다. 네 사례의 필드를 수정하지 않고 선택해 기존 `seed_golden_v02_accounts()` → 실제 SQL 적재 → `run_qualification_judgment()` → `get_required_checks()`를 실행했다. 기존 함수 내부 commit은 savepoint에 한정했고 외부 트랜잭션을 마지막에 롤백했다. 공용 DB와 기존 테스트 자료는 변경하지 않았다. 이 검사는 브라우저 E2E나 원문에서 새로 추출한 결과가 아니다.

| 사례 | 원본 회사 업종 | 장비·허가 예외 시나리오 값 | 운반 조건 기대값 | 제품 관찰 |
|---|---|---|---|---|
| J13 | 1257, 1227 | false | SATISFIED | UNKNOWN |
| J14 | 1257, 1224 | false | UNSATISFIED | UNKNOWN |
| J15 | 1257 | true | SATISFIED | UNKNOWN |
| J16 | 1257 | null | UNKNOWN | UNKNOWN — 경로 검증 실패 |

이 기대값은 **운반 조건 부분식**의 기대값이다. 전체 공고 참가 가능 여부의 승인값이 아니다. 네 사례는 전북 소재 합성 회사이며 서울 소재 그린브릿지 글로벌과도 구분한다.

## Q-005 — Golden 보류 요건과 장비·허가 예외 입력의 제품 연결

- **관련 단계:** W0/W1/W5/W6.
- **확인한 코드·로그:** 원본 네 사례의 `transport_literal`은 `mapping=REVIEW_HELD`, `operator=null`, `value=null`, `condition_complexity=composite`, `requirement_role=informational`이다. 별도 `code_review`도 composite로 보류돼 있다. 제품 `judge_requirement()`는 composite 조건을 UNKNOWN으로 반환한다. 기존 seed는 `scenario_facts.equipment_exception_confirmed`를 판정 입력·사용자 답변으로 옮기지 않는다. 실제 추가 질문에서 운반/해석 보류 항목 모두 `askable=false`다.
- **추가 연결 한계:** 같은 notice version에 한 분석을 공유하므로 J14~J16도 J13의 요건 키를 사용한다. 이는 현재 seed의 버전별 분석 캐시 동작이다. seed가 만든 case는 baseline=current이며, 이번 입력만으로 실제 v1→v2 변경 데모를 구성할 수 없다.
- **부족한 결정:** 보류 중인 운반 조건을 어떤 검수된 계약으로 제품화할지, 공고별 장비·허가 확인의 질문·근거·저장 범위를 확정해야 한다. 단순 트럭 보유나 단일 프로필 boolean을 곧바로 법적 충족으로 승격해서는 안 된다.
- **대안 A:** 현재 보류 계약을 유지하고 UNKNOWN·직접 확인으로 표시한다. 보수적인 동작은 유지되지만 J13~J16 분기 데모는 완성되지 않는다.
- **대안 B(권장):** 원문과 적용 대상을 검수한 뒤 `1227 등록 OR 해당 폐기물의 직접 수집·운반에 필요한 허가·장비 조건 충족`을 구분해서 표현한다. 예외 확인은 해당 공고·버전·요건에 묶인 사용자 답변과 증빙 확인으로 수집하고, 제안→명시 확인→판정 반영 경계를 유지한다. 미확인은 UNKNOWN, 부정은 예외 불충족으로 구분한다. 원본 DRAFT를 덮어쓰지 말고 새 검수 버전의 입력과 migration 필요 여부를 별도로 검토한다.
- **영향:** 단순 Copilot 프롬프트 수정이 아니라 Golden 정규화·추가 질문·답변 저장·프로필/판정 적재 계약의 변경이다. 기존 composite 안전 가드를 일괄 해제하지 않는다.
- **답변 전 가능한 작업:** 현재 네 사례 실패 고정, 출처/원문 확보, 변경 비교와 실행 경계 검사, 사용자 평가 기록표 준비.
- **필요한 결정/자료:** B의 입력·증빙 범위 검수, 해당 v1/v2 원문·추출·분석·판정 snapshot, 다른 담당자의 진행 중 변경과 접점. 현 상태를 장비 예외 E2E 완료로 보고하지 않는다.

## 변경 건수는 세 개의 질문으로 나눠야 한다

사용자는 원문 변경 감지 3건 중 업무상 조건 변경은 업종코드 1224→1227 1건이라고 설명했다. 이는 검증할 기대 기준으로 보존했다.

2026-09-14 조회한 [PR #132](https://github.com/gyuniverse-hq/bid-change-validator/pull/132)는 열려 있고 미병합 상태다. 최신 PR 본문은 변경 3건 중 구조화 값 차이를 **2건**으로 보고한다. 업종코드 외에 인증·등록 `scope.issuer`가 현재 차수에서 빠졌다는 설명이다. 작성자는 이를 추출 차이 후보로 기록했으며 원문 표기 차이로 자동 무시하지 않았다. 이 본문의 결과는 PR 작성자의 보고로, 이 작업에서 해당 실제 DB 결과를 재실행한 것은 아니다.

따라서 아래를 동일한 숫자로 취급하면 안 된다.

1. **변경 감지 건수:** raw까지 비교한 현재 서버의 MODIFIED 등 결과.
2. **구조화 필드 차이 건수:** raw를 제외한 값·scope·역할 등 JSON 차이. 추출 흔들림도 포함할 수 있다.
3. **업무상 조건 변경 건수:** 원문 검수로 판정한 의미 변화. 현재 사용자 기대는 1건이며, 기계적 JSON 비교만으로 확정하지 않는다.

이 작업은 #132를 수정·병합하지 않았다. 그린브릿지의 참가 불가를 코드 변경 탓으로 단정하지 않으며, 전체 판정 반전은 별도 통제 프로필과 양 버전 판정으로 검증해야 한다.

## 확보한 자료와 남은 자료

- 기존 실제 Golden 저장 자료 5사례/문서 참조 23개는 파일/hash 검사를 통과했다. 정답 label은 0개, 외부 원본 binary 검증은 0개다. 남원글로컬 원본 snapshot을 확보했다는 뜻은 아니다.
- 현재 버전 `fbc095ba-5d92-4461-a4cc-d436f5532c3b`의 로컬 legacy index에는 74개 청크가 있고, 1227과 허가·장비 예외 문구가 함께 있다. 재추출한 원문이나 검증된 v3.1 세대로 취급하지 않았다.
- 이전 버전 `96264b55-4205-4cd3-8c02-59eb0181c94d`의 같은 로컬 index는 없다. 원본 ZIP의 CH07/CH08 비교 입력도 DRAFT이며 전체 판정 반전을 주장하지 않는다.
- 실제 v1/v2 source·analysis·judgment를 갖춘 로컬 이식 가능한 snapshot을 추가로 확보해야 한다. 공용 DB를 변경하거나 기존 index를 덮어써서 대신하지 않았다.
