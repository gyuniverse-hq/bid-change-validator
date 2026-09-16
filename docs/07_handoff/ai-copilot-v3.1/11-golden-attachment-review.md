> **과거 작업 이력 — 2026-09-16 이관.** 아래 본문은 이전 feature 브랜치 당시 기록입니다. 검사 결과·미완료 항목·승인 및 push 상태를 현재 상태로 해석하지 마세요. 최신 상태는 [45번 보고서](45-pipeline-result-and-next-step.md), 다음 설계는 [46번 제안](46-guided-job-ui-transition.md), 이관·근거 위치는 [47번 안내](47-workspace-consolidation.md)를 따릅니다. 본문의 증거 폴더와 `.ci-results` 경로는 원래 저장소 기준이며 증거를 새 브랜치에 복사하지 않았습니다.

# Desktop 전달 Golden 자료 확인·실행 — 2026-09-14

## 결론

사용자가 보낸 자료가 맞다. 실행담당자 ZIP은 기존 Golden v0.2를 실행에 필요한 파일로 재포장한 자료이며, 두 ZIP의 `fixture_bundle.json`은 바이트 단위로 같다. 다른 사례를 잘못 받은 것이 아니다. 이전차수 입력 CH07/CH08도 포함돼 있다. 다만 **고정 평가 입력과 원문 발췌**이며, 실제 서비스의 양 버전 원문·분석·판정 전체 snapshot은 아니다.

현재 코드로 추가 검사를 실행했다. 자료 내부 일관성 검사는 통과했으나 실제 제품 엔진의 엄격 의미 검사는 실패했다. 원본 엑셀과 ZIP은 수정하지 않았다. 자료의 실행 안내·설계 의견을 사용자 승인이나 검수 완료로 간주하지 않았다.

## 자료별 확인

| 자료 | 확인한 내용 | 사용할 범위 |
|---|---|---|
| 골든셋_실행담당자_v02.zip | 52개 파일, 현재 32개·이전 8개 입력, 실제 엔진 runner, 과거 자료검사 요약 | 로컬 고정 입력 평가 |
| golden_fixtures_v02.zip | 동일 fixture bundle, 원문 발췌와 출처·이전차수 비교 자료 | 출처 추적·평가 입력 |
| 골든셋_팀검토_v02.xlsx | `03_판정검토32!G18:H21` 미실행/검토 전, `04_변경비교8!I12:J13` 미실행/검토 전, `05_검수할일!A14:H14` D07 예외 해석 검토 전 | 검수할 항목·담당 구분 |
| golden_fixture_review_v02.xlsx | `판정32!A17:K20` PARTIAL·미실행·검토 전, `변경8!A11:L12` 전체 반전 보류 | 세부 기대값과 입력 계약 |
| README_진행결과.md | 독립 검토 전 초안, scenario_facts는 제품 API 계약이 아님, 자료검사와 제품 정확도 구분 | 평가 범위·제약 확인 |

원본 파일별 경로·SHA256·크기와 runner 목록은 `golden-attachment-evidence/manifest.json`, 엑셀 확인 셀은 `workbook-review-excerpts.json`에 기록했다. 엑셀의 과거 미실행 표시는 그대로 보존하고 이번 실행은 별도 결과로 남겼다.

## 이번 실제 실행

2026-09-14 07:06 UTC, HEAD `e9b35056d322f79d987ac70770f585851ba8a7d1` + 현재 수정본. 원본 기준 commit `993e5cf...`와 다르므로 차이를 명시적으로 기록하고 초안 측정에만 `--allow-draft --allow-code-drift`를 사용했다. 정답 승인 의미가 아니다.

실행 스크립트와 import를 확인한 뒤 저장소 `.ci-results/golden-attachment-20260914T070628Z`에 복사했다. Python socket 접속을 차단한 `offline_run.py`를 통해 실행했다. DB·API·LLM을 호출하지 않았고 모델 비용은 추가되지 않았다. 실제 프로젝트의 `app.qualification.rules.judgment.judge_requirements`와 계약 모델을 import했다.

| 검사 | 실제 결과 | 해석 |
|---|---|---|
| validate_bundle.py | exit 0, 913/913 | 파일·입력·초안 기대값의 내부 일관성. 제품 정확도 점수가 아님 |
| run_project_engine.py --strict-semantic | **exit 1**, 40개 입력·138개 항목 | 110개 초안 일치, 28개 SAFE_ABSTENTION |
| 110개 일치의 구성 | SATISFIED 64 / UNSATISFIED 29 / UNKNOWN 17 | UNKNOWN 일치를 지원 기능 완료로 해석하지 않음 |
| 잘못된 확정 판정 | 초안 대비 양성 0 / 음성 0, 실행 예외 0 | 독립 검수 정답이 아니므로 법적 정확도나 일반화 보장 아님 |
| 전체 판정 | insufficient_data 32 / ineligible 8 | J06·J07·CH04-BEFORE는 초안의 ineligible 대신 insufficient_data, 전체 기대와 3개 불일치 |

이번 913은 실제 실행한 자료 검사 개수다. 과거 “47개 격리 검사”나 제품 테스트 수와 합산하지 않는다. runner 기본 exit 0은 안전 보류를 허용하므로 사용하지 않고, 보류도 실패로 반영하는 엄격 모드의 exit 1을 보존했다.

재현: 동일 해시 ZIP을 작업 폴더에 풀고 프로젝트 가상환경으로 `scripts/validate_bundle.py`, 이어서 `scripts/run_project_engine.py --repo <저장소> --allow-draft --allow-code-drift --strict-semantic`을 실행한다. 이번 정확한 명령·종료 코드는 manifest, 원시 결과는 `golden_runner_v02/results/product_engine_actual.json`과 로그에 있다. 소스 해시는 결과 JSON에 기록했다. API·브라우저 검사는 보고서 10과 별개다.

증거 원본의 pytest 로그/XML·patch에는 후행 공백이 있어 전체 `git diff --cached --check`에서 경고가 발생했다. 원시 로그를 공백 정리해 바꾸지 않았으며, 제품 코드·테스트·수정 보고서는 따로 공백 검사를 수행한다.

## 남원글로컬 결과와 Q-005 유지

J13·J14·J15의 운반 조건은 기대 SATISFIED/UNSATISFIED/SATISFIED와 달리 모두 UNKNOWN/UNSUPPORTED_REQUIREMENT다. J16도 같은 미지원 사유로 UNKNOWN이며, 예외 미확인 경로가 검증됐다고 할 수 없다. 원본 입력의 `REVIEW_HELD`, composite, null value 및 별도 scenario_facts 계약은 그대로다. 이번 엔진 직접 실행은 보고서 09의 DB 제품 실행에서 관찰한 문제를 재확인했다.

CH07·CH08의 이전차수 입력도 실제 엔진에 넣었다. 두 비교 모두 이전·현재 전체 결과가 insufficient_data다. 1224→1227 원문 표기의 고정 비교 입력은 있지만, 실서비스의 MODIFIED 3건이나 `scope.issuer` 추출 차이를 재현한 결과는 아니다.

**Q-005의 근거가 강화됐으며, 검수 완료로 해소되지 않았다.** 권장안은 보고서 09의 B: 원문을 기준으로 운반 업종 또는 적법한 허가·장비 예외를 검수한 후 공고·버전·요건에 묶인 입력/증빙/답변 저장 계약으로 연결한다. 현재 가드를 풀거나 scenario_facts의 boolean을 임의로 제품 자격 충족에 반영하지 않는다.

## 추가로 필요한 자료를 정확히 구분

같은 Golden ZIP·엑셀을 다시 받을 필요는 없다. 다음 자료가 Desktop에 별도로 있다면 그것이 필요한 추가 자료다.

1. R26BK01684863 차수 000/001의 실제 원문 PDF/HWP/HWPX와 관련 별첨. 버전 ID `96264b55-4205-4cd3-8c02-59eb0181c94d` / `fbc095ba-5d92-4461-a4cc-d436f5532c3b`와 연결할 수 있는 출처 정보.
2. 두 버전의 실제 추출·분석 요건 JSON(raw, value, scope, 근거 위치 포함), 사용한 회사 프로필 및 판정 결과 JSON. 변경 3건과 구조화 필드 차이를 재현할 대상 한정 export면 충분하며 전체 DB dump나 비밀번호는 필요 없다.
3. 검토표 D07의 코드 정정·허가/장비 예외 검수 결과. 아직 검수하지 않았다면 미검수 상태를 유지한다.

1번만 있어도 원문 재분석 검사는 진행할 수 있다. 다만 당시 서비스의 변경 3건을 같은 입력으로 재현하려면 2번이 필요하다. 자료 확보와 별개로 가정/제안 답변 품질 및 W6 실제 사용자 평가는 남아 있다.

## Git 보존 상태

이번 결과까지 commit/push하려 했으나, 자동 승인 검토가 `Selected model is at capacity`를 이유로 대상 보고서·증거의 `git add`를 두 번 거절했다. 쓰기 명령은 실행되지 않았다. 기존 222개 staged 변경과 이번 추가 파일을 그대로 보존했으며, HEAD는 e9b3505다. 이 단계의 commit/push나 원격 반영을 완료로 보고하지 않는다. 승인 검토 우회는 하지 않았다.
