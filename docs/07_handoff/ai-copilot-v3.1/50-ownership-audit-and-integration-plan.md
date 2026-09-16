# 변경 영역 감사와 선별 통합 계획

2026-09-16. 사용자 요청: 다른 팀원 영역까지 넓어진 변경을 확인하고 안전하게 합칠 방법을 정리한다. 이번 작업은 감사이며 구현·병합 완료 보고가 아니다.

## 결론

현재 브랜치를 통째로 develop에 병합하는 것은 권하지 않는다. Copilot 조회·설명 연결 외에 공용 판정 규칙, 분석 보정, 답변 저장·재판정, 문서 추출, 기존 제품 화면까지 변경했다. 연결에 필요한 변경도 있지만, 이를 한 기능 묶음으로 누적한 것은 통합 부담을 키웠다. 최신 develop을 기준으로 필요한 변경만 기능과 담당 영역별로 분리해야 한다.

다른 팀원 코드가 원격에서 덮어써졌다는 뜻은 아니다. 이번 감사에서는 fetch와 읽기·임시 비교만 수행했다. 기존 구현과 미커밋 작업은 보존했다.

## 비교 기준과 근거

- 루트: `E:/dev/02_TeamProjects/bid-change-validator`
- 브랜치: `codex/ai-copilot-evaluation-ready`, HEAD `6af3b4fde3db775c73890b939beb3376ef4d2e01`
- 이번 fetch로 확인한 origin/develop: `0cfef1a2426e1b568dc2b3dc308eb95aa2b02699`
- 공통 조상: `c510c3e611ff7dc229f721733fa5e5a24cc9ed4d`
- 로컬 근거: `.ci-results/ownership-audit/20260916T010826Z/`의 `inventory.csv`, `summary.json`, 양쪽 patch와 `overlap-*/preview-lf.txt`.
- 담당 기준: [current-ownership.md](../current-ownership.md). Frontend 황수빈, Backend 전진환, Core/Evaluation 김재현, DB 정예린, Copilot/Integration 이홍규.

| 집계 | 경로 수 | 의미 |
|---|---:|---|
| 공통 조상 대비 로컬 추적 파일의 실제 내용 차이 | 135 | 커밋된 변경과 미커밋 변경 포함 |
| HEAD 대비 미커밋 추적 파일 내용 차이 | 39 | 위 집계와 중복되므로 합산 금지 |
| 미추적 파일 | 38 | 감사 문서 생성 전 기준 |
| develop의 공통 조상 이후 변경 | 26 | 로컬 변경과 별도 비교 |
| Copilot 전용 경로 밖 공용 제품 파일 | 23 | 아래 표의 검토 대상 |
| 양쪽이 수정한 파일 | 6 | 같은 줄 충돌 여부와 별개 |

Git status의 추적 수정 표시 130개 중 91개는 HEAD 대비 실제 내용 diff가 없다. 이를 모두 기능 변경으로 세면 안 된다. 원인은 이번 감사에서 확정하지 않았다. 인덱스를 갱신해 표시를 정리하지 않았다. 비교 목록에는 DB migration/schema 및 `apps/api/app/ai/**` 수정은 없지만, 공용 판정 의미에 영향을 주는 변경은 있다.

## 최신 develop과 겹치는 부분

임시 사본의 CRLF를 LF로 통일하여 `git merge-file -p`로 비교했다. 원본·인덱스·브랜치는 변경하지 않았다. 줄바꿈을 통일하기 전의 6개 충돌 결과를 실제 코드 충돌로 집계하지 않는다.

| 파일 | 텍스트 충돌 | 통합 시 주의 |
|---|---|---|
| `apps/api/app/routers/notices.py` | 없음 | develop의 OCI/S3 endpoint 연결 유지, 로컬 HWP MIME 처리만 별도 검토 |
| `apps/api/app/services/document_extraction.py` | 없음 | 저장소 클라이언트 변경과 HWP 디코딩 수정을 구분 |
| `apps/web/app/ask-back/page.tsx` | 없음 | 최신 화면을 기준으로 추가답변 표시 변경 필요성 판단 |
| `apps/web/app/changes/page.tsx` | 없음 | 최신 화면 구조 유지, 비교 근거·집계 연결만 선별 |
| `apps/web/app/qualification/page.tsx` | 1곳 | 로컬 완료 배너 분기와 develop의 제거가 충돌. 최신 상태 표현을 우선하고 필요한 의미만 반영 |
| `apps/web/lib/case-workspace.ts` | 없음 | develop 병렬 조회 유지. 로컬 규칙 버전 v0.4 상수만 먼저 넣으면 판정 호환성 문제 가능 |

텍스트 충돌이 없다는 것은 실행 호환성 검증 통과가 아니다. develop의 문서 저장소·matching 개선, 기존 화면·상태 문구·빠른 초기 조회 등의 변경을 보존해야 한다. develop에만 있는 파일을 로컬 브랜치가 삭제한 파일로 해석해서는 안 된다.

## 공용 제품 23개 파일의 처리안

아래 경로는 저장소 상대 경로다. 같은 묶음 안에서도 필요한 부분만 옮긴다.

| 파일 | 실제 변경 목적 | 권장 처리 |
|---|---|---|
| `apps/api/app/ask_back_schemas.py` | 구조화 확인 필드·basis 추가 | 추가답변 계약 묶음으로 분리 |
| `apps/api/app/document_rag/langchain_pipeline.py` | LangChain 검색 파이프라인 신규 | 프로젝트 가이드상 유지 대상. 공용 검색 계약과 Copilot 어댑터 경계 정리 |
| `apps/api/app/document_rag/readiness.py` | 추출 품질, 검색 범위, passage 구성 | 공유 RAG 정책 변경으로 별도 검토 |
| `apps/api/app/qualification/ask_back.py` | 구조화 답변 노출·입력 검증 | 이번 읽기 중심 두 Job에서 기능 확장 제외 |
| `apps/api/app/qualification/judgment.py` | 분석 보정 경로 호출 | 판정 엔진 묶음으로 분리 |
| `apps/api/app/qualification/judgment_target.py` | 분석 보정 경로 호출 | 위와 동일 |
| `apps/api/app/qualification/revalidation.py` | 최신 결과 조회 + 답변 재사용 + source contract 검사 | 조회와 쓰기·판정 동작을 반드시 나눔 |
| `apps/api/app/qualification/routers/revalidation.py` | 권한 확인 후 최신 재검증 조회 GET | 변경 영향 설명에 필요한 최소 조회 계약 후보 |
| `apps/api/app/qualification/rules/askability.py` | source contract 기반 확인 질문 | 판정·추가답변 묶음 분리 |
| `apps/api/app/qualification/rules/judgment.py` | v0.4, 업종·예외·현장 방문 조건 처리 | Backend/Core 검토 대상. Copilot PR에 함께 넣지 않음 |
| `apps/api/app/qualification/rules/requirement_diff.py` | 선행 글머리표를 정규화한 요건 식별 | 공용 변경 감지 수정으로 별도 테스트·검토 |
| `apps/api/app/qualification/rules/source_contracts.py` | 조건 계약 검증과 입력 구조 | 현재 Copilot도 직접 의존. 삭제 전에 공개 계약으로 분리 필요 |
| `apps/api/app/qualification/source_repair.py` | 원문 패턴·검증 snapshot에 따른 분석 revision 보정 | 저장 분석에 영향. 데모 편의를 위한 일반 판정 변경으로 합치지 않음 |
| `apps/api/app/routers/notices.py` | 새 HWP extractor MIME 처리 | HWP 수정과 함께 작은 독립 변경 |
| `apps/api/app/services/document_extraction.py` | HWP 제어문자 디코딩, extractor 버전 | 독립 파서 수정으로 검토 |
| `apps/web/app/ask-back/page.tsx` | 확인 질문·답변 표시 | 추가답변 UI 묶음 분리 |
| `apps/web/app/changes/page.tsx` | 저장 비교 조회, 구조화 값/원문 차이 표시 | 최신 Frontend 위에 최소 연결만 선별 |
| `apps/web/app/login/page.tsx` | hydration 전 제출 방지 등 | 로그인 결함 수정으로 분리 |
| `apps/web/app/qualification/page.tsx` | 실패 후 조회 복구, 재판정·부분 완료 표시 | develop의 기존 개선과 중복 제거 후 남는 수정만 검토 |
| `apps/web/lib/case-workspace.ts` | 규칙 버전 v0.4 | 엔진과 함께 움직여야 함. Copilot 단독 변경에서 제외 |
| `apps/web/lib/confirmation-display.ts` | 구조화 답변의 사용자 문구 | 추가답변 UI 묶음 분리 |
| `apps/web/lib/qualification-api.ts` | 확인 필드 타입 확장 | 추가답변 API 계약과 함께 처리 |
| `apps/web/lib/requirement-diff.ts` | 원문/구조화 비교 표시 helper 신규 | 변경 화면 최소 연결 후보, 서버 의미와 일치 검증 |

Copilot 이름의 Frontend 파일도 Frontend 담당 영역이다. 읽기 응답 표시와 실행 제안·저장 UI를 분리한다. `app/copilot/**`라는 경로만으로 전부 이번 범위에 포함하지 않는다.

## Q-053 — 읽기 중심 두 Job이 공용 판정 변경에 의존하는 문제

**근거:** `product_tools.py`가 `qualification.rules.source_contracts.valid_contract`를, `tool_adapters.py`가 confirmation 계약과 LangChain retrieval을 사용한다. 공용 judgment는 규칙 v0.4와 조건 계약 처리로 의미가 바뀌었다. source repair는 명시적 재판정 시 저장 분석 revision에도 영향을 준다. 따라서 Copilot 폴더만 복사해도 되는 독립 기능 상태가 아니다.

**대안 A:** 기존 변경을 통째로 통합한다. 작업은 단순하지만 다른 담당 영역과 결합되고 원인 추적·회귀 검토 범위가 커진다. 비권장.

**대안 B:** 최신 develop의 판정 동작을 유지하고 Copilot은 공개 조회 계약으로 저장 결과·원문·불확실성을 설명한다. 필수 공용 수정은 별도 변경으로 검토한다. 권장.

**대안 C:** 먼저 판정 v0.4 및 분석 보정 전체를 합의·통합한 뒤 챗봇을 연결한다. 네 회사 프로필의 엔진 동작까지 제품에 반영하려면 필요한 선택일 수 있으나 두 Job UI보다 범위가 크다.

**권장안:** B를 기본으로 삼고 C에 해당하는 변경은 별도 보존한다. 단, 로컬 v0.4로 생성한 남원 판정 자료를 develop 엔진에서도 검증된 결과처럼 재사용하지 않는다. develop 호환 데이터로 다시 검증하거나 판정 변경의 별도 통합이 먼저 필요함을 명시한다. 이는 실제 회귀 실패 확인이 아니라 코드 의존성에서 확인한 통합 위험이다.

## 통합 순서와 최소 검증

1. **현재 — 변경 감사 완료:** 내용 diff, 담당 영역, 의존성과 충돌 후보를 기록한다. 기존 작업은 보존한다.
2. **다음 — 변경 묶음 분리:** 보존 지점을 확보한 뒤 최신 develop 기반 통합 후보에 필요한 부분만 옮긴다. 기존 혼합 커밋 전체 cherry-pick이나 파일 전체 덮어쓰기는 피한다. 사용자가 요청한 루트 작업 폴더를 유지하며, 브랜치 전환 전에 미커밋·미추적 보존을 확인한다. 이번 감사에서는 전환하지 않았다.
3. **최소 조회 계약:** 인증·사건 소유권·판정 버전·회사 snapshot·비교 lineage를 갖춘 최신 재검증 조회. 답변 재사용·새 판정 생성과 분리한다. 다른 사건 접근 차단과 조회 중 저장 변경 없음 검증.
4. **Copilot 두 Job 연결:** 변경→회사 영향→확인사항, 서류·기한·방법→준비 순서→미확인 항목. LangChain 유지, 서버 질문 계약과 제한된 읽기 도구, 접힌 상세 표시. 기존 제품 화면은 최소 연결만 적용한다.
5. **독립 수정 검토:** HWP parser/MIME, 공용 판정·분석 보정, 추가답변, 로그인·화면 복구를 각각 분리한다. 담당 영역별 검토 자료를 준비하되 이 문서 작성으로 팀 동의를 받았다고 보지 않는다.
6. **필수 회귀 후 사용자 평가:** 변경된 패키지의 계약/단위 검사와 두 Job의 연속 질문을 한 묶음으로 검증한다. 회사·버전 혼선, 구조화/원문 차이, 기한·방법 연결, 미확인 이유, 조회 중 데이터 불변, 응답 시간을 확인한다. HWP 수정은 fixture와 저장소 client mock으로 검증하고 공용 DB는 변경하지 않는다.

기존 오프라인 통과 수는 이 통합 후보의 통과 근거가 아니다. 최신 develop 기반 실행·모델·화면 통합 검증은 아직 수행하지 않았고 사용자 평가 준비 상태는 **NOT_READY**다. 감사 단계에서 모델 비용이나 공용 DB 접근은 필요하지 않았다.

## 이번 실행 범위

실행: origin/develop fetch, 공통 조상과 실제 diff 목록 확인, 책임 문서 및 관련 코드 읽기, 임시 파일의 3-way 텍스트 비교, 감사 문서 작성. 미실행: 제품 수정, 실제 merge/rebase/cherry-pick, commit/push, DB 변경, 모델 호출, 제품 회귀 검사, 팀원 메시지 전송.
