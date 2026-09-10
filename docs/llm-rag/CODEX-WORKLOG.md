# Codex 작업 로그

> Codex가 수행한 LLM/RAG 세부 조정 내역을 시간순으로 기록합니다.
> 설계와 범위의 기준 문서는 `PROJECT.md`와 `SPEC.md`입니다.

## 2026-09-10 — 위험조항 9종 분류의 중첩 전달

- 기존 개별 검출 결과의 단일 `risk_type`은 이미 있었지만, 한 원문 조항에 여러 룰이 동시에 걸릴 때 전체 분류를 전달하는 필드는 없음을 확인했습니다.
- 기존 호환 필드 `risk_type`과 표시명 `category`를 유지하고, 같은 원문에 겹친 모든 값을 `risk_types`와 `categories` 배열로 API 응답에 추가했습니다.
- 중첩 판정은 같은 공고 버전·청크·조항에서 원문 발췌가 동일하거나 서로 포함되는 경우에만 묶습니다. 같은 청크에 있을 뿐 원문 문장이 다른 결과는 합치지 않습니다.
- `/api/review-text`와 `/api/notice` 모두 응답 최상위에 검출된 `risk_types` 목록을 포함하고, 각 finding에는 해당 원문에 겹친 분류 목록을 포함합니다.
- 데모 프론트는 각 finding의 `categories`를 분류 칩으로 모두 표시합니다. 지체상금 한 문장에 상한·요율이 함께 있으면 두 칩이 표시됩니다.
- 검증: 위험조항·사업계획서 관련 집중 테스트 51건과 DB 의존 테스트를 제외한 API 테스트 167건이 통과했습니다.

### 팀 설계 변경 반영

- 저장 계약을 `risk_type`(대표 코드), `category`(대표 한글 라벨), `categories`(전체 한글 라벨 JSON 배열)로 정리하고 finding의 중복 `risk_types` 배열은 제거했습니다.
- 원인이 하나뿐이어도 `categories`는 반드시 원소 1개짜리 배열이며, `categories[0] == category` 불변식을 지킵니다.
- 대표값은 `NEEDS_REVIEW → UNDETERMINED → COMPLIANT` 순으로 먼저 고르고, 동률이면 팀 확정 9종 순서를 적용합니다. 탐지 순서에 의존하지 않습니다.
- 데모 상세 화면은 `categories` 전부를 표시하고 복수이면 `N종에 걸림`을 함께 보여줍니다.
- `ClauseFinding` 자체도 `risk_type` 코드, `category`, `categories`, 별도 `label`을 갖도록 바꿔 데모 전용 직렬화가 아닌 브리핑 백엔드 응답에서도 같은 계약이 유지됩니다.
- 원격을 갱신해 확인했으나 현재 브랜치와 `origin/develop` 어디에도 팀원이 언급한 기존 `category` DB 컬럼/위험조항 저장 테이블은 아직 없습니다. 중복 마이그레이션은 만들지 않고 `02-integration-requests.md`에 안전한 JSONB 추가·백필 순서를 남겼습니다.
- 검증: DB 의존 테스트를 제외한 API 테스트 183건이 통과했습니다.

## 2026-09-10 — 사업계획서 초안 데모 프론트 연결

- 공고 검토 화면 하단에 `사업계획서 초안` 카드를 추가했습니다.
- 회사 소개, 제안 목표, 수행 방안, 차별점, 투입 조직·인력, 일정, 추가 참고사항을 입력받아 기존 `POST /api/business-plan-draft`로 현재 공고 컨텍스트와 기업 프로필을 함께 전송합니다.
- 공고를 불러오기 전 또는 구조화된 참가자격 요건이 없을 때는 생성 버튼을 비활성화합니다.
- 생성 중·성공·실패 상태와 서버가 반환한 검토 경고문을 화면에 표시하며, 모델 결과는 HTML로 해석하지 않고 텍스트로 렌더링합니다.
- 사용자 추가 입력이 전부 비어 있으면 요청을 보내지 않고 첫 입력란으로 안내합니다.
- 데모 HTML에 요청 필드와 엔드포인트 연결이 유지되는지 확인하는 회귀 테스트를 추가했습니다.
- 검증: `test_business_plan.py` 5건 및 DB 의존 테스트를 제외한 API 테스트 165건이 통과했습니다. 전체 수집은 현재 저장소의 비어 있는 `DATABASE_URL` 때문에 DB 모듈 7곳에서 중단되며 이번 프론트 변경과는 무관합니다.

## 기록 규칙

각 작업에는 다음 내용을 남깁니다.

- 작업 일시와 목적
- 변경한 파일
- 구현 또는 조사 결과
- 실행한 검증과 결과
- 남은 문제나 후속 작업

## 2026-09-09

### 작업 범위 확인

- `README.md`, `PROJECT.md`, `SPEC.md`를 읽고 LLM/RAG 파트의 소유 범위와 금지 사항을 확인했습니다.
- 우선 작업 대상으로 F8 확장항목 입력 반영, SW 기술자 등급 판정 경로 정리, `payment_period` 수치 인식 실패 조사, 공사 공고 지체상금 수치 인식 실패 조사를 확인했습니다.
- 저장소에 이미 존재하는 미커밋 변경은 보존하며, 이후 작업은 요청받은 범위만 최소한으로 수정합니다.
- 코드 변경 및 테스트 실행은 아직 하지 않았습니다.

### F8 확장항목 입력 반영 및 SW 기술자 등급 경로 정리

- 변경 파일:
  - `apps/api/app/ai/judgment.py`
  - `apps/api/app/ai/demo_web.py`
  - `apps/api/app/ai/demo_web.html`
  - `apps/api/tests/test_ai_extensions.py`
- `CompanyProfileSnapshot.extensions`를 추가하고, 데모 화면에서 공고별 확장 질문의 입력란을 동적으로 생성해 `/api/judge`와 `/api/assist`에 전달하도록 연결했습니다.
- 서버에서 확장 답변 문자열을 `parse_answer_for()`로 파싱한 뒤 프로필을 검증하도록 했습니다. 모델은 개입하지 않습니다.
- SW 기술자 등급 요건은 `extensions._sw_grade_judge`가 단독으로 판정하게 했습니다. 기존 화면의 고정 특급/고급/중급 입력은 제거했고, 일반 인력 요건은 기존 `staff` 판정 경로를 유지합니다.
- 기업규모 제한과 상호출자제한기업집단 제한이 한 요건에 함께 있는 경우에도 계열사 확장 답변을 실제 판정에 반영하도록 연결했습니다. 답변이 없으면 작은 기업도 `UNKNOWN`, 계열사이면 `UNSATISFIED`, 비계열사이면 규모 판정 결과를 유지합니다.

### 실제 공고의 수치 인식 실패 조사

- 변경 파일:
  - `apps/api/app/ai/normalization/numbers.py`
  - `apps/api/tests/test_clause_review_standard_diff.py`
- `R26BK01705963`의 `payment_period` 원문을 확인했습니다. 문언은 “용역계약일반조건 및 계약서 등에 따라 … 대가를 지급”으로, 지급기한 숫자가 없습니다. 다른 숫자를 끌어오지 않고 `UNDETERMINED`를 유지하는 것이 맞다고 판단해 회귀 테스트를 추가했습니다.
- `R26BK01716363`의 공사 지체상금 원문은 “지체1일당 1/1,000”입니다. 기존 정규화기가 `천분의 1`과 `%`만 지원해 실패한 것이 원인이었습니다.
- 슬래시 비율(`1/1,000`)을 백분율(`0.1%`)로 변환하도록 정규화기를 확장했습니다.
- 실제 캐시 문서를 다시 추출해 공사 지체상금이 `CHUNK-0315`, `0.1%`, `NEEDS_REVIEW`로 판정되는 것을 확인했습니다.

### 검증

- 저장소 내부 `.venv`에 `apps/api/requirements-dev.txt` 의존성을 설치했습니다. `.venv`는 Git 추적 대상이 아닙니다.
- 확장항목·판정·계약조항 관련 테스트: `52 passed`
- 최종 DB 제외 전체 회귀 테스트: `158 passed in 1.02s`
- `pytest` 캐시 쓰기 권한 경고를 피하기 위해 최종 실행에서는 `-p no:cacheprovider`를 사용했습니다.

### 남은 확인

- 실제 브라우저에서 동적 확장 입력란의 시각적 배치와 입력 UX를 수동 확인할 수 있습니다. 서버 판정 경로와 자동 테스트는 통과했습니다.

### 챗봇 온·오프 토글

- 변경 파일: `apps/api/app/ai/demo_web.html`
- 우측 하단의 원형 `?` 버튼을 상태가 명확한 `챗봇 켜기` / `챗봇 끄기` 토글로 변경했습니다.
- 토글 상태를 `aria-expanded`와 `aria-pressed`에 함께 반영했습니다.
- 끄면 패널만 숨기고 기존 대화 기록은 유지하며, 다시 켜면 질문 입력란에 포커스를 둡니다.
- `Escape` 키로도 챗봇을 끌 수 있고, 꺼진 상태에서는 질문 전송 함수를 실행하지 않습니다.

### 데모 화면 수동 검증

- `computer-use` 스킬로 실제 localhost 데모를 브라우저에서 조작했습니다.
- 챗봇 토글을 켰을 때 패널이 나타나고 입력란으로 포커스가 이동하며, 끄면 접근성 트리에서도 패널이 제거되고 대화 상태는 유지되는 것을 확인했습니다.
- 390×844 뷰포트에서 본문 가로폭은 375px로 가로 넘침이 없었고, 열린 챗봇 패널은 약 346px로 화면 안에 들어왔습니다. 확인 후 뷰포트 설정을 원래대로 복원했습니다.
- 기존 8200 서버가 이전 Python 코드를 들고 있어 종료하고 최신 코드로 재시작했습니다. 확인 후 새 서버도 정상 종료했습니다.
- 새 프로세스에서 세 캐시 공고를 UI로 다시 불러오지 못한 최초 원인을 조회 키 문제로 잘못 판단했습니다. 후속 점검 결과 `.env`의 `G2B_SERVICE_KEY`는 정상적으로 존재하고 `Settings`의 URL 디코딩 후에도 유효했습니다. 동일 조회를 샌드박스 밖에서 실행하자 `R26BK01716363`이 `CONSTRUCTION`으로 정상 조회됐으므로 실제 원인은 테스트 서버의 네트워크 샌드박스 제한입니다. 키 설정 문제라는 이전 기록은 이 문장으로 정정합니다.

### 참가자격 검색 골든셋 측정 하네스

- 추가 파일:
  - `apps/api/app/ai/goldenset/__init__.py`
  - `apps/api/app/ai/goldenset/fixtures.py`
  - `apps/api/app/ai/goldenset/spans.py`
  - `apps/api/app/ai/goldenset/scoring.py`
  - `apps/api/app/scripts/retrieval_report.py`
  - `apps/api/tests/test_goldenset_scoring.py`
  - `samples/golden/retrieval-v0.1/spans.json`
  - `samples/golden/retrieval-v0.1/README.md`
- 청크 ID가 아니라 공백을 제거한 원문 문자열 스팬으로 POSITIVE/TRAP 라벨을 매칭하도록 했습니다. 문서 ID도 함께 검사해 중복 PDF/HWPX가 서로의 정답으로 계산되지 않습니다.
- 청크 수, 중앙값 크기, 50자 미만 비율, 최대 크기 초과, 스팬 포함률, recall, precision, trap rate, 문자 예산 사용률, heading-only 비율과 스팬별 깔때기를 한 명령으로 JSON 출력합니다.
- 현재 깔때기의 `extracted`와 `canonical`은 결정적 검색 기준선에서는 `null`로 명시합니다. 이후 고정 모델 3회 결과를 입력받는 연결이 필요합니다.
- 첫 라벨은 캐시에 확실히 존재하는 `R26BK01705963`의 POSITIVE 4개와 TRAP 2개입니다. 일반화 목표인 8~10공고/60~90 POSITIVE/40 TRAP에는 아직 못 미치므로 README에 제한을 명시했습니다.
- 기준선 재현 결과: 328청크, 중앙값 56.5자, 50자 미만 47.26%, 1,800자 초과 46개, 최대 2,838자, 검색 4청크, recall 1.0, precision 0.25, trap rate 0.5, 예산 사용률 13.69%, heading-only 25%.
- 실행 명령: `python -m apps.api.app.scripts.retrieval_report --goldenset samples/golden/retrieval-v0.1 --retriever default --json`
- 최종 DB 제외 전체 회귀 테스트: `160 passed in 1.27s`.

## 2026-09-10

### 위험조항 목록 및 실제 구조화 샘플 팀 공유

- `apps/api/app/ai/clause_review/contracts.py`의 `RiskType`과 `RISK_TYPE_BY_RULE`을 다시 대조해 최종 공유 위험유형이 9종임을 확인했습니다.
- 기존 8종에서 지체상금 상한(`LATE_PENALTY`)과 일별 요율(`LATE_PENALTY_RATE`)을 서로 다른 근거로 판정하기 위해 분리한 것이 9종이 된 이유입니다.
- 내부 검사 `warranty_bond_rate`는 합의 유형에 매핑되지 않아 `risk_type=null`이며 9종 목록에는 포함하지 않습니다.
- 캐시된 실제 공사 공고 `R26BK01716363`의 `LATE_PENALTY_RATE` 구조화 결과를 재생성했습니다. 공고 `1/1,000` → `0.1%`, 시행규칙 기준 `1천분의 0.5` → `0.05%`, 판정 `NEEDS_REVIEW`를 확인했습니다.
- 팀 전달 문서: `docs/llm-rag/06-risk-types-and-structured-sample.md`

### 사업계획서 초안 생성 프로토타입

- 추가 파일:
  - `apps/api/app/ai/business_plan.py`
  - `apps/api/tests/test_business_plan.py`
- 변경 파일:
  - `apps/api/app/ai/demo_web.py`
  - `docs/llm-rag/SPEC.md`
- 새 엔드포인트 `POST /api/business-plan-draft`를 추가했습니다. 요청은 `context_id`, 기존 회사 프로필, 사업계획서용 사용자 추가 입력을 받습니다.
- 기존 `build_briefing()`과 `render_briefing_text()`를 그대로 사용해 판정·사유·공고 근거·계약조항·공고 요약을 모델의 사실 컨텍스트로 조립합니다.
- 모델이 양식을 즉흥 생성하지 않도록 사업 이해, 추진 전략, 조직·인력, 일정·산출물, 품질·위험, 제출 전 확인사항의 6개 Markdown 목차를 고정했습니다.
- 입력에 없는 실적·인력·인증·금액·일정은 생성하지 않고 `[담당자 확인 필요: ...]`로 남기도록 프롬프트 경계를 설정했습니다.
- 모든 응답에 `AI가 작성한 사업계획서 초안입니다. 제출 전에 담당자가 사실과 표현을 검토하세요.` 경고를 별도 `disclaimer` 필드로 반환합니다.
- 빈 추가 입력은 `EMPTY_INPUT`, 모델 미사용 환경은 `NARRATOR_UNAVAILABLE`, 호출 실패나 빈 응답은 `FAILED`로 열화합니다.
- 관련 단위·브리핑·확장항목 테스트: `29 passed in 0.88s`.
- 최종 DB 제외 전체 회귀 테스트: `164 passed in 2.99s`.
- 후속 수정: `.assist { display:flex }`가 브라우저의 기본 `[hidden]` 스타일을 덮어쓰던 문제를 발견해 `.assist[hidden] { display:none }`을 추가했습니다. 이제 토글을 끄면 챗봇 패널 전체가 실제로 사라집니다.
