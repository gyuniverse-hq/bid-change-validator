> **과거 작업 이력 — 2026-09-16 이관.** 아래 본문은 이전 feature 브랜치 당시 기록입니다. 검사 결과·미완료 항목·승인 및 push 상태를 현재 상태로 해석하지 마세요. 최신 상태는 [45번 보고서](45-pipeline-result-and-next-step.md), 다음 설계는 [46번 제안](46-guided-job-ui-transition.md), 이관·근거 위치는 [47번 안내](47-workspace-consolidation.md)를 따릅니다. 본문의 증거 폴더와 `.ci-results` 경로는 원래 저장소 기준이며 증거를 새 브랜치에 복사하지 않았습니다.

# Q-006 — 규칙 변경 후 저장 판정 재사용 차단과 복구

2026-09-14. 기준 HEAD `3cf1f48053429e6f94e099fbe52c1e5af8a29d99` 위의 수정.

**Q-006의 Backend/API 수정 및 격리 DB 검증 완료.** 규칙 버전을 `qualification-rules-v0.2`에서 `qualification-rules-v0.3`으로 올렸다. #133의 지역 위계·표기 정규화로 판정 의미가 바뀌므로 기존 버전의 저장 판정을 부분 재검증에 재사용하지 않는다. 기존 버전 검사와 전체 재판정 API를 활용했으며, 과거 판정의 일괄 덮어쓰기나 DB migration을 새로 추가하지 않았다.

재검증 및 Copilot 제안 거절 메시지에 참가자격 화면에서 기준·현재 차수를 다시 판정하라는 안내를 추가했다. 프론트 ActionController는 409 응답의 안내를 유지하고 제안을 해제하며 같은 쓰기를 자동 재실행하지 않는다. 이번에는 화면 컴포넌트 자체를 변경하지 않았다.

## 재현과 수정 후 검증

별도 Docker `bid-copilot-test-db`, PostgreSQL 16, `127.0.0.1:57945/copilot_test`에서 실행했다. runner가 로컬 Docker 소켓, 컨테이너 라벨, 이미지, 임시 볼륨, loopback 바인딩, DB·사용자·서버 버전을 확인했다. dotenv를 비활성화하고 DB URL을 이 대상에만 지정했다. 외부 모델/네트워크는 차단했으며 비용은 $0이다.

과거 저장 상태는 합성 fixture로 준비했다. 요건은 `종전 광주광역시`, 회사 프로필은 `전남광주통합특별시`; 두 차수의 지역 요건은 동일하다. 저장된 v0.2 판정의 지역 항목은 `UNSATISFIED`다. 이는 실제 공용 DB의 이력을 가져온 것이 아니며 행정·법률 사실 검증도 아니다.

| 실행 | 결과 | 근거 |
|---|---|---|
| 수정 전 DB 재현 | **48 passed / 1 failed**, 9.30초 | 기대한 409 대신 200; 지역은 UNCHANGED라 옛 UNSATISFIED를 복사함 |
| 수정 후 DB 회귀 | **49 passed**, 8.98초 | 기존 48개와 새 전체 복구 시나리오 |
| 수정 후 오프라인 회귀 | **433 passed** | DB 접속 금지; Copilot·지역·추출·Golden 계약 검사 |
| Golden runner | **회귀 기준 PASS** | 40개 사례·138개 항목, 110개 기대값 일치·28개 보류·잘못된 확정 0. 전체 판정 37/40 일치 |
| 프론트 action 검사 | **PASS** | 규칙 변경 안내 유지, 제안 해제, 쓰기 재시도 0, 명시적 전체 검토 시작 가능 |
| 기존 프론트 계약 검사 | **PASS** | 인용·대화 격리·응답 계약 등 |

DB 흐름의 실제 관찰:

1. 과거 기준 판정으로 부분 재검증 → `409 RULE_CHANGED_FULL_REJUDGMENT_REQUIRED`.
2. 과거 판정으로 Copilot 재검증 제안 → `409 STALE_ACTION_CONTEXT`.
3. 두 거절 동안 저장 건수는 판정 3개·재검증 0개로 동일.
4. 기존 분석을 지정해 기준·현재 차수의 전체 판정 API를 명시적으로 호출 → 각각 새 v0.3 판정 생성, 지역은 `UNKNOWN/INSUFFICIENT_DATA`.
5. 새 기준 판정으로 부분 재검증 → 200. 지역 요건은 UNCHANGED이며 새 UNKNOWN을 재사용하고, 실적 요건만 재판정.
6. 최종 저장 건수는 판정 6개·재검증 1개. Copilot의 현재 판정 조회가 새 결과 ID와 v0.3을 반환.
7. 과거 판정 두 건의 응답 스냅샷은 그대로 보존. 회사 지역 값도 유지.

버전 변경은 모든 과거 v0.2 판정에 적용되므로, 지역과 무관한 사례도 부분 재검증/답변 반영 전에 새 규칙으로 다시 판정해야 할 수 있다. 규칙 단위 버전 관리로 범위를 줄이는 별도 설계는 이번에 도입하지 않았다.

## 변경 파일과 실행 근거

- `apps/api/app/qualification/rules/judgment.py`: 규칙 버전 증가 및 이유 기록.
- `apps/api/app/qualification/revalidation.py`, `apps/api/app/copilot/actions.py`: 재판정 안내.
- `apps/api/tests/test_copilot_rule_version_db.py`: 실제 로그인/API/PostgreSQL을 통한 과거 상태 차단·복구·이력 보존 검사.
- `scripts/test_copilot_db.py`: 새 DB 검사 연결; 규칙·판정 코드 해시를 실행 메타데이터에 포함.
- `apps/web/scripts/check-copilot-actions.mjs`: 409 안내·재시도 차단·전체 검토 전환 검사.

저장소 루트의 실행 자료:

- `.ci-results/copilot-db-20260914T081158Z/`: 수정 전 실패 로그·JUnit·환경/소스 해시.
- `.ci-results/copilot-db-20260914T081310Z/`: 수정 후 통과 로그·JUnit·환경/소스 해시·`rule-version-recovery.json`.
- `.ci-results/q006-20260914T081350Z/`: 오프라인·Golden·프론트 검사 및 소스 diff.

Docker 실행 파일 접근은 최초 sandbox에서 거절돼 DB 검사가 시작되지 않았다. 이후 승인된 실행으로 위 전용 DB 대상 검증을 완료했다. 최종 검사에는 기존 Starlette/AnyIO deprecation warning 1건이 있었으며 실패는 아니다.

## 현재 위치와 남은 작업

전체 순서: **1 감사 → 2 구현 → 3 기본 검사 → 4 확대 검증 → 5 사용자 평가 → 6 최종 통합 판단**.

- develop→feature 병합 완료(`3cf1f48`). Q-006의 Backend/API·프론트 상태 처리 검증 완료.
- 이번에는 실제 브라우저에서 재판정 안내를 클릭하는 경로와 계정 전환 확대 E2E를 실행하지 않았다. 프론트 상태 검사 통과를 화면 E2E 통과로 보지 않는다.
- 다음은 실제 남원 양 차수 snapshot 준비와 Q-005 장비·허가 예외의 입력/증빙/판정 계약 해결이다. Golden 초안의 28개 보류와 J15/J16 미지원은 그대로 남는다.
- **5번 사용자 자유 질문·이해도 평가는 미실행**, 6번 최종 통합 판단도 보류다. 공용 DB 변경·배포·원격 push는 하지 않았다.
