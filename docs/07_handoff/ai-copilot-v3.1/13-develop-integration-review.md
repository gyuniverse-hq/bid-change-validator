> **과거 작업 이력 — 2026-09-16 이관.** 아래 본문은 이전 feature 브랜치 당시 기록입니다. 검사 결과·미완료 항목·승인 및 push 상태를 현재 상태로 해석하지 마세요. 최신 상태는 [45번 보고서](45-pipeline-result-and-next-step.md), 다음 설계는 [46번 제안](46-guided-job-ui-transition.md), 이관·근거 위치는 [47번 안내](47-workspace-consolidation.md)를 따릅니다. 본문의 증거 폴더와 `.ci-results` 경로는 원래 저장소 기준이며 증거를 새 브랜치에 복사하지 않았습니다.

# develop 통합 사전 검토 — 2026-09-14

결론: **텍스트 충돌은 작지만 바로 develop에 병합하는 것은 보류 권장.** 최신 develop을 별도 통합 작업 공간에서 먼저 받아 검증하는 방향은 타당하다. 지역 판정 규칙 버전 문제(Q-006)를 보완하고, 실제 자료·사용자 평가를 마친 후 최종 통합을 판단한다. 이번에는 실제 Git merge·commit·push·배포를 하지 않았다.

## 1. 현재 기준과 보존 상태

`git fetch origin develop feature/ai-copilot-user-test-hardening` 성공 후 확인했다.

| 기준 | SHA |
|---|---|
| 현재 로컬 feature | `2c6c6bf7f35b9de5ec507df52d660b3d08abb59b` |
| 원격 feature | `e9b35056d322f79d987ac70770f585851ba8a7d1` |
| 최신 원격 develop | `c26cdcad3733a115bff8172d5674a61238860b39` |
| 공통 조상 | `81f101934608dd880f6ef1a633558b523c82ee6e` |

공통 조상 이후 로컬 feature 쪽 18개, develop 쪽 31개 고유 커밋이다. 원격 feature에는 최신 로컬 수정이 아직 반영되지 않았다.

기존 미커밋 문서 08·12, stash 2개, 작업 디렉터리 1개를 보존했다. 시작 시 staged 변경은 없었다. 이번에 추가한 것은 이 보고서와 무시되는 `.ci-results/develop-review-20260914/`의 검사 자료뿐이다. 검사 후보에는 커밋된 소스만 사용했으며 기존 미커밋 문서 변경은 넣지 않았다.

## 2. 텍스트 충돌

공통 조상 대비 양쪽 수정 파일의 교집합은 아래 2개다. develop 변경 목록에는 rename/delete가 없었다.

| 파일 | 확인 결과 | 결합 방법 |
|---|---|---|
| `.gitignore` | 충돌 1곳; `git merge-file -p` exit 1 | feature의 `.pnpm-store/`와 develop의 `artifacts/`를 모두 유지 |
| `apps/web/lib/copilot-api.ts` | 양쪽 수정이나 충돌 없음; `git merge-file -p` exit 0 | feature의 v3.1 envelope 계약과 develop의 `requirement_role`·`condition_complexity` 필드를 함께 유지 |

`git merge-tree --write-tree --messages`는 자동 승인 검토의 `Selected model is at capacity` 오류로 실행되지 않았다. 대신 Git 객체·index·브랜치를 변경하지 않는 `git merge-tree --trivial-merge`와 두 파일의 `git merge-file -p`를 실행했다. 이는 실제 merge commit 생성 성공을 의미하지 않는다.

검사 후보는 로컬 HEAD의 커밋된 소스에서 문서를 제외해 내보내고, develop의 변경을 적용해 만들었다. 공유 변경 두 파일은 위 방식으로 결합했다. `.git`이 없는 별도 폴더이며 원본 작업 파일을 덮어쓰지 않았다. 기존 web 의존성 디렉터리는 junction으로 참조했다.

## 3. 실제 실행한 호환성 검사

| 검사 | 결과 | 범위/한계 |
|---|---|---|
| Copilot 11개 테스트 파일 + develop Golden CI의 7개 테스트 파일 | **433 passed**, 7.27초 | `--noconftest`; DB 연결 금지, 외부 네트워크 차단, 모델은 fake. Starlette/AnyIO deprecation warning 1건 |
| Golden 회귀 runner | **회귀 게이트 PASS** | 40개 사례·138개 항목: 기대값 일치 110, 보류 28, 잘못된 확정 0. 전체 판정 일치 37/40 |
| 결합 후보 TypeScript | **PASS**, exit 0 | `tsc --noEmit --incremental false`; 실제 UI 실행은 아님 |
| `check-copilot.mjs` | **PASS**, exit 0 | 프론트 계약·인용·대화 격리 등 기존 검사; 네트워크 호출 없음 |
| `check-copilot-target-memory.mjs` | **PASS**, exit 0 | 비대상 후속 질문 뒤 대상 기억 |
| 지역 규칙 전후 비교 | **동작 차이 재현** | 아래 Q-006; 실제 DB 재검증 재현은 미실행 |

Golden PASS는 보류를 허용하는 회귀 기준의 통과다. 28개 보류를 정답으로 바꿔 기록하지 않았고, 기존 엄격 의미 평가 실패 및 J15/J16 미지원 문제를 해소한 것으로 보지 않는다. 과거 “47개 통과”는 여전히 UNVERIFIED다.

이번 결합 후보에서는 Docker DB 통합, 실제 모델, 브라우저 E2E, 사용자 평가는 실행하지 않았다. 이전 feature 단독 검사 결과를 결합 후보의 결과로 전용하지 않는다. 이번 모델 비용은 0이다.

근거는 저장소 루트 기준 `.ci-results/develop-review-20260914/`에 있다:

- `candidate-manifest.json`: 양쪽 SHA, 공통 조상, 후보 소스별 SHA256, 파일 결합 결과.
- `merge-tree-readonly.txt`: 읽기 전용 3방향 비교 결과.
- `candidate-tests.log`, `candidate-tests.xml`, `check-results.json`: 433개 검사 및 환경.
- `candidate-golden.json`, `candidate-golden.log`: 사례별 실제 엔진 결과.
- `candidate-typescript.log`, `candidate-web-contract.log`, `candidate-web-target-memory.log`: 프론트 검사.
- `region-before.json`, `region-after.json`: 동일 입력에 대한 규칙 전후 출력.
- `prepare_candidate.py`, `check_candidate.py`, `region_version_probe.py`: 재현 스크립트. 기존 후보를 덮어쓰지 않도록 준비 스크립트는 폴더가 존재하면 중단한다.

## 4. 기능 접점 검토

| develop 변경 | Copilot과의 관계 | 의견 |
|---|---|---|
| #132 변경 비교 화면 | 양쪽 원문·구조화 필드 비교, 원문 차이 배지, 접기/펼치기. Copilot이 연결하는 `/changes?caseId=...`와 공존 | 받아오는 방향 권장. 원문 차이를 무조건 무해한 표기 차이라고 설명하지 않아야 함. 실제 남원 건수는 snapshot으로 재확인 |
| #133 지역 위계 판정 | 같은 입력의 판정 결과를 바꿈. 기존 저장 판정을 읽는 Copilot 및 영향 요건만 재검증하는 경로와 연결 | **Q-006을 해결해야 함** |
| #134 계정·Case 분리 | 전역 최근 Case 복원 제거, 회사별 Case 조회. Copilot은 URL caseId를 사용하고 서버 상태는 owner/case/company를 확인 | 충돌 없이 수용 가능. 로그인 화면에서 Provider가 렌더링되지 않아 일반 로그아웃 경로에서는 메모리 store가 해제되는 구조. 계정 전환+이전 URL 접근은 결합 후보 브라우저로 추가 검증 필요 |
| Golden CI | 판정 회귀를 자동 감시하지만 추출·실제 DB·모델·사용자 평가를 대신하지 않음 | 기존 Copilot 검사와 함께 유지. 실제 자료 평가 완료 근거로 사용하지 않음 |

## 5. Q-006 — 지역 판정 변경과 규칙 버전·기존 판정 재사용

**상태: OPEN / 최종 통합 전 보완 권장.** develop에서 유입되는 문제이며 이번에 제품 코드를 수정하지 않았다.

**근거**

1. 기존 feature와 최신 develop의 `apps/api/app/qualification/rules/judgment.py`는 모두 `RULE_VERSION = "qualification-rules-v0.2"`다.
2. 동일한 합성 입력(요건 `종전 광주광역시`, 회사 지역 `전남광주통합특별시`, 기준일 2026-07-15)을 직접 판정했다. feature는 `UNSATISFIED/RULE_MISMATCH`, 결합 후보는 `UNKNOWN/INSUFFICIENT_DATA`였지만 규칙 버전은 동일했다. 이는 코드 동작 비교이며 행정·법률 사실의 독립 검증은 아니다.
3. `apps/api/app/qualification/revalidation.py:80`은 저장된 `source.rule_version != RULE_VERSION`일 때만 `RULE_CHANGED_FULL_REJUDGMENT_REQUIRED`로 전체 재판정을 요구한다.
4. 같은 파일의 `UNCHANGED` 분기는 기존 판정을 `_copy_judgment`로 복사한다. 따라서 옛 엔진으로 저장한 지역 미달이 있고 차수 간 지역 요건이 동일하면, 새 규칙에서도 버전 검사를 통과해 옛 미달을 유지할 수 있다. 이 DB 경로는 코드로 확인했으며 이번에 실제 DB로 재현하지는 않았다.

**영향**

전체 재판정은 UNKNOWN인데 변경 요건만 재검증하면 과거 UNSATISFIED가 남는 불일치가 가능하다. Copilot은 저장된 판정을 설명하므로 잘못된 최신성 인상을 줄 수 있다. Golden CI의 새 입력 직접 판정만으로는 과거 저장 판정 재사용을 검증하지 못한다.

**대안**

- A. 규칙 버전을 올리고 기존 버전의 판정을 재사용할 때 기준 차수부터 전체 재판정을 요구한다. 기존 오류 코드와 경계를 재사용할 수 있다.
- B. 규칙 묶음별 버전 또는 영향 요건 이관 정책을 도입해 지역 요건만 다시 판정한다. 범위가 크고 혼합 버전의 판정 출처·감사가 복잡해진다.

**권장안**

A를 우선 적용한다. 과거 저장 결과를 일괄 덮어쓰지 않고, 격리 DB에서 옛 판정→새 규칙의 부분 재검증 차단→명시적인 전체 재판정→새 결과 표시까지 검증한다. 화면의 재판정 안내도 함께 확인한다. 공용 DB 변경은 이번 요청 범위에 포함하지 않는다.

**설계 대화 전달 문장**

> Q-006: develop #133은 지역 판정 결과를 바꾸지만 RULE_VERSION을 v0.2로 유지합니다. 동일 입력이 UNSATISFIED→UNKNOWN으로 바뀌는 것을 재현했습니다. 현재 affected-only 재검증은 규칙 버전이 같으면 UNCHANGED 요건의 옛 판정을 복사하므로 새 전체 판정과 불일치할 수 있습니다. 규칙 버전을 올리고 기존 판정은 명시적 전체 재판정으로 전환하는 A안을 권장합니다. 실제 DB 전환 경로 검증은 아직 필요합니다.

## 6. 전체 순서와 남은 작업

기존 번호는 유지한다. 이번 검토는 사용자가 요청한 사전 확인이며 5번을 건너뛰어 6번을 완료한 것이 아니다.

| 순서 | 상태 |
|---|---|
| 1 감사·보존 | 기존 조사 범위 완료; 이번 Git 상태 재확인 |
| 2 핵심 구현·연결 | 기존 구현 있음; 전체 완료 아님 |
| 3 기본 결함 수정·검사 | 기존 범위 통과; 이번 후보의 추가 오프라인 검사 통과 |
| 4 확대 검증 | 합성 흐름은 기존 범위 통과. 실제 남원 snapshot·Q-005 장비 예외 계약은 남음 |
| **5 사용자 자유 질문·이해도 평가** | **미실행. 실제 지정 사례 준비와 기존 차단점 해결 후 진행해야 함** |
| 6 최종 검토·통합 | 보류. Q-006 및 결합 후보 DB·브라우저 검증, 5번 결과 확인 필요 |

권장 진행: 별도 통합 작업 공간에서 최신 develop 반영 → Q-006 보완 및 격리 DB·계정 전환 검증 → 남원 실제 자료/Q-005와 5번 평가 → 최종 feature→develop 병합 판단. 최신 develop 반영을 제품 완료나 발표 준비 완료로 간주하지 않는다. 공개 원격 push에 관한 기존 승인 차단도 이번 검토로 해제되지 않는다.
