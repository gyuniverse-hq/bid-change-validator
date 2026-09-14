# 운반 예외·입력 취소·저장 후 조회 검사

2026-09-15 KST. 시작 코드 9269d46. 이번 변경은 검사·테스트 웹 실행기·보고서이며 제품 판정 규칙 변경은 없다.

## 전체 순서와 현재 위치

| 순서 | 상태 |
|---|---|
| 1 감사 → 2 연결 → 3 기본 검사 | 기존 수행 기록 유지 |
| 4 통합 검증 | Q-009 기관 해석 미확정 유지 |
| **5 사용자 평가 — 현재** | **한국어 검토 화면·운반 예외 양쪽 입력·취소·저장/조회·계정 경계 개발 검증 통과** |
| 5 남은 평가 | 사람 재평가, 다양한 자연어 표현·정정의 의미 처리. 아래 제한 참조 |
| 6 최종 통합 판단 | 최신 develop 비교·미해결 사항 검토 필요. merge·배포 미실행 |

## 남원 snapshot 판정 재검증

`scripts/test_copilot_db.py --snapshot .ci-results/namwon-source-reextracted.json --namwon-bundle <로컬 Golden ZIP>` 실행. 전용 PostgreSQL16 테스트 DB copilot_test, 127.0.0.1:57945에서 롤백 트랜잭션으로 수행했다. 공고 source hash는 기존 52cb91a7…8102f0이다.

| 사례 | 운반 조건 입력 전 | 통제된 보충값 적용 후 |
|---|---|---|
| J13 | SATISFIED | SATISFIED |
| J14 | UNKNOWN | UNSATISFIED: 법적 운반 허가 조건 false |
| J15 | UNKNOWN | SATISFIED: 처분/재활용 허가·직접 운반 법적 조건·필요 장비 true |
| J16 | UNKNOWN | UNKNOWN: 미답변 유지 |

**1개 테스트에서 4개 프로필 PASS**. 근거 `.ci-results/copilot-db-20260914T213657Z/namwon-snapshot-results.json`, `tests.xml`. J14/J15 보충값은 합성 통제값이며 원본 ZIP의 검증된 실제 회사 사실이 아니다. 업종군 AND/OR는 계속 미확정이다. 원본 snapshot/원문을 수정하지 않았다.

## 실제 브라우저·API·DB 검사

테스트 웹 5179/API18123은 사용자 평가 웹5181/API18125와 분리했다. `scripts/local_copilot_test_web.mjs` 실행 후 `scripts/test_copilot_db.py --browser`로 수행한다. 외부 네트워크와 모델 호출은 차단하고 실제 Chrome·로그인·API·PostgreSQL을 사용했다. API 응답 mock 없음.

최종 **4개 테스트 PASS**, `.ci-results/copilot-db-20260914T213950Z/tests.xml` (27.51초). 최초 양쪽 입력 검사도 `copilot-db-20260914T213826Z`에서 통과했으며 취소 검사 추가 후 최종 재실행했다.

- 운반 예외 법적 허가 false/true를 각각 독립 테스트 데이터에서 실행하여 UNSATISFIED/SATISFIED 확인.
- 모든 필드의 초기값 미확인, 장비만 입력한 경우 제안 비활성화 확인.
- 부분 입력 취소 시 저장0, 다시 열면 조건값 모두 미확인으로 초기화됨 확인.
- 한국어 계약 항목·예/아니요 표시 및 basis JSON 미노출 확인. 실제 미충족 검토 화면 스크린샷 시각 확인.
- 명시 확인 전 저장0, 실행 후 confirm 요청1회·200, askback 근거 판정 확인.
- 저장 후 ‘반영 후 새 판정 결과를 확인했습니다’ 표시까지 대기하여 자동 조회 연결 확인.
- 일반 조회/대상 유지, 이전 규칙의 명시적 재판정·변경 재검증, 로그아웃/타사 로그인 후 접근403·동의 초기화 검사 통과.

양쪽 운반 입력의 브라우저 자료는 `source-confirmation-false-browser.json`, `source-confirmation-true-browser.json`, `source-confirmation-*-before.png`에 저장했다. 이 브라우저 사례는 운반 계약이 있는 격리 Golden fixture이고, 위 실제 남원 snapshot 4프로필 검사와 구분한다. 남원 J14~J16 각각의 실제 사용자 계정을 저장하며 UI E2E를 수행했다고 주장하지 않는다.

`check-copilot-actions.mjs`도 실행하여 입력 정정 시 제안 무효화, 중복/재전송 방지, 저장 결과 불명 시 재실행 차단, 조회만 재시도, 한국어 false 표시 등을 확인했다. 이는 controller 검사이며 모든 자유 자연어의 의미 해석 검사가 아니다.

## 보존·한계

사용자 평가 DB copilot_evaluation을 READ ONLY로 대조했다. 기존 J13 답변1건만 유지되고 J14~J16 저장 답변은 없다. 이번 외부 모델 호출·비용0. 공용 DB·main/develop·merge·배포 변경 없음. 로컬 원문·계정·응답은 Git 제외.

다양한 자연어 정정·모호한 답변을 모델이 모두 올바르게 처리하는지는 여전히 미검증이다. 현장 방문의 명확한 두 상태 문법 지원을 범용 자연어 입력 지원으로 확대하지 않는다. 입력 불명확 시 자동 저장하지 않는 구조와 구조화 폼의 미확인 상태는 검사했으나, 사용자 의도를 충분히 이해하는지는 사람 평가가 필요하다.
