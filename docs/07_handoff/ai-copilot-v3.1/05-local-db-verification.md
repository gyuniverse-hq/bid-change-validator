> **과거 작업 이력 — 2026-09-16 이관.** 아래 본문은 이전 feature 브랜치 당시 기록입니다. 검사 결과·미완료 항목·승인 및 push 상태를 현재 상태로 해석하지 마세요. 최신 상태는 [45번 보고서](45-pipeline-result-and-next-step.md), 다음 설계는 [46번 제안](46-guided-job-ui-transition.md), 이관·근거 위치는 [47번 안내](47-workspace-consolidation.md)를 따릅니다. 본문의 증거 폴더와 `.ci-results` 경로는 원래 저장소 기준이며 증거를 새 브랜치에 복사하지 않았습니다.

# 로컬 PostgreSQL 검증 — 2026-09-14

## 실행 방법

Docker Desktop이 켜진 상태에서 저장소 루트의 PowerShell에서 실행한다. 현재 준비된 가상환경 기준이다.

```powershell
.venv-copilot-v31/Scripts/python.exe scripts/test_copilot_db.py
```

별도 테스트 컨테이너를 생성하거나 재사용하고, 마이그레이션과 선택한 DB 검사를 실행한다. `.env` 변경은 필요 없다. 실행 프로세스에만 DATABASE_URL과 MIGRATION_DATABASE_URL을 함께 지정하며 dotenv 로딩을 끈다. 테스트 DB는 재실행을 위해 유지한다.

## 실제 실행 결과

- 기준 HEAD: `e9b35056d322f79d987ac70770f585851ba8a7d1` + 이번에 추가한 실행기와 DB 테스트(미커밋).
- 독립 컨테이너: `bid-copilot-test-db`, PostgreSQL 16.15, `127.0.0.1:57945/copilot_test`.
- 기존 앱 컨테이너와 5432 DB는 유지했고 공용 Supabase에는 연결하지 않았다.
- 첫 실행: 001~022 마이그레이션 적용 성공, **44 passed**, 10.70초.
- 재실행: 같은 컨테이너 ID를 재사용, **44 passed**, 6.25초. 동일한 44개 검사이며 88개로 집계하지 않는다.
- 두 실행 모두 Starlette/anyio의 기존 deprecation warning 1건. 실패/skip 없음.
- 실제 외부 모델 호출 없음. 이번 검사의 모델 비용은 발생하지 않았다.

원본 로그와 JUnit XML, 환경 메타데이터는 `db-evidence/` 아래 각 실행 시각 디렉터리에 보존했다. 자격증명은 기록하지 않는다.

## 검증 범위와 한계

실제 PostgreSQL을 사용한 제품 도구 읽기, 판정/버전 정합성, 기존 API 흐름, 변경 공고 재검증, 쓰기 실패 시 트랜잭션 롤백을 검사했다. 새 v3.1 검사는 실제 저장된 판정 데이터를 ProductTools → coordinator → 응답까지 연결하고 출처 범위와 읽기 전용 상태를 확인한다.

외부 모델은 비활성화 또는 mock이다. 따라서 실제 모델 + DB + 로그인 + 브라우저의 전체 통합 검증 완료를 의미하지 않는다. 새 v3.1 검사의 extractive 응답은 의도적으로 PARTIAL이며 모델 작업 완료 PASS로 승격하지 않았다.

첨부 리뷰의 R-01(중복 claim_id), R-02(과도한 근거/응답 크기), R-03(후속 대상 식별), Q-003(작업 완료 기준)은 이번 작업에서 수정하지 않았다. DB 검사 통과만으로 해당 문제 해결이나 W0~W6 완료, merge 가능을 선언할 수 없다. 과거 ‘47개 통과’ 주장도 계속 UNVERIFIED다.

공용 DB 전환은 이번 범위가 아니다. 공용 DB에 이 테스트 실행기를 사용하거나 테스트 seed/reset을 실행하지 않는다.
