# 3단계 — 후보별 추출 호출과 누락 후보 재처리

## 현재 위치

- Branch: `refactor/qualification-reliability`
- 이번 작업의 부모 commit: `b875769` (2단계)
- 현재: **3단계 구현·독립 단위 검증 완료 / 실제 DB·LLM 및 제품 통합 검증 대기**
- 기존 HTTP API·서비스 설정은 그대로이며, 새 경로는 Python 함수의 명시적 선택으로만 실행한다.
- 골든셋/기대값/평가기, Copilot, 판정 규칙, DB 스키마는 변경하지 않는다.
- `develop`/`main`에 병합하지 않는다. PR #136도 합치지 않았다.

| 단계 | 작업 | 상태 |
|---|---|---|
| 1 | 원문 후보 ID·응답 누락 검사 | 이전 구현 완료 (27개 테스트 기록) |
| 2 | 조항·상위 문맥·각주·요청 분할 | 이전 구현 완료 (43개 신규, 당시 합계 70개 통과) |
| 3 | 후보 ID별 추출 호출·미응답 재처리 | **이번 구현 완료, 신규 65개 독립 테스트 통과** |
| 4 | 근거 의미 연결·기간/금액 역할·AND/OR·중복 | 다음 단계 |
| 5 | 분석 완전성·판정 상태·현재 결과 선택 | 대기 |
| 6 | 목록 필터·집계·상세 연결 | 대기 |
| 7 | 판정·변경 재검증·Copilot 전체 검증 | 대기 |

구현 완료는 제품의 정확성/재현율 개선을 실증했다는 뜻이 아니다.
이전 단계의 70개 테스트를 이번에 재실행한 것으로 합산하지 않는다.

## 변경 파일

- `extraction/review_execution.py`: JSON-schema 응답 계약, 실행·검증·재시도·호출 예산·추적 기록
- `extraction/review_extraction.py`: 기존 source-grounded slot 계약으로의 선택적 변환
- `extraction/analysis_pipeline.py`: 기본 legacy 유지, `extraction_strategy="review_v1"` 선택 경로
- `tests/test_review_execution.py`: 실제 후보/계획/실행/변환 모듈 53개 단위 테스트
- `tests/test_review_pipeline.py`: 실제 provider 4개와 orchestration 분기 8개 단위 연결 테스트

상대경로의 extraction은 `apps/api/app/ai/qualification/extraction`, tests는 `apps/api/tests`다.

## 호출 흐름

```text
Backend 문서 블록 (text·ID·hash 원본 보존)
→ ReviewInventory
→ ReviewPlan (모든 후보가 요청 또는 blocked에 배정됨)
→ structured_extract(system_prompt, body, json_schema)
→ 후보 ID/상태/필드/원문 인용 검증
→ 실제 미응답 후보만 원래 ID와 문맥으로 재요청
→ 자기 조항으로 표현 가능한 슬롯을 기존 normalization/canonical에 전달
→ 기존 RequirementAnalysisResult + REVIEW_EXECUTION_AUDIT 진단
```

`analyze_qualification_documents(..., extraction_strategy="legacy")`가 여전히 기본이다.
모델명/키는 기존 `OpenAIStructuredExtractor`와 호출자가 관리한다. 새 모듈은 키/DB를 읽지 않는다.
기존 호출 시 `review_options`를 잘못 전달하면 조용히 무시하지 않고 오류로 알린다.

```python
from app.ai.qualification.extraction.analysis_pipeline import analyze_qualification_documents
from app.ai.qualification.extraction.review_execution import ReviewOptions

# analysis_input과 extractor는 기존 Backend 입력/호출 어댑터를 사용한다.
result = analyze_qualification_documents(
    analysis_input,
    structured_extract=extractor,
    extraction_strategy="review_v1",
    review_options=ReviewOptions(max_retries=1, max_calls=64, max_elapsed_seconds=180),
)
```

HTTP router에 새 옵션을 노출하거나 배포 기본값을 전환하지 않았다.

## 응답 계약과 원문 소유권

응답은 decisions 배열이며 모든 대상 ID에 상태를 하나씩 반환한다.
상태는 REQUIREMENT / NOT_REQUIREMENT / UNRESOLVED / NEEDS_CONTEXT다.
REQUIREMENT에는 슬롯이 필요하고 나머지 상태에는 사유와 빈 슬롯 목록이 필요하다.

모델은 raw 문장·정규 수치·문자 위치 숫자를 생성하지 않는다. 각 필드는
`name`, `source_candidate_id`, `quote`를 반환한다. 서버는 그 ID의 원문에서
**유일한 연속 구간**을 확인해 실제 인용문과 부모 블록의 문자 위치를 계산한다.
동일 표현이 여러 번 있으면 첫 번째 위치를 임의로 선택하지 않는다.

검증 범위는 해당 후보 + 그 후보에 연결해 전송한 문맥이다.
같은 요청의 다른 원문에 있더라도 해당 후보의 문맥이 아니면 받아들이지 않는다.
이번 단계는 exact quote만 지원한다. 장식기호/공백 정규화 매칭은 다음 단계의 검토 대상이다.

## 재요청 및 실패 처리

- 누락만: 원래 inventory를 유지하고 누락 ID만 재요청한다. 완료 후보는 덮어쓰지 않는다.
- 중복 ID: 마지막 응답 우선으로 합치지 않는다. 그 후보를 격리한다.
- 외부/문맥 전용 ID 또는 식별 불가능한 행: 해당 요청 응답을 격리한다.
- 잘못된 필드/인용/유형: 후보를 격리하고, 반복해서 유리한 답을 고르지 않는다.
- UNRESOLVED/NEEDS_CONTEXT: 같은 문맥으로 자동 반복하지 않는다. 후속 문맥 해결 대상이다.
- 호출 오류/거부/불완전 JSON: 오류를 기록하며 현재 실행기에서 자동 재호출하지 않는다.
- 빈 후보: EMPTY. 전부 NOT_REQUIREMENT여도 제품 경로의 자동 성공으로 만들지 않는다.

기본 재시도는 1회, 논리적 extractor 호출 상한은 64회다.
180초 예산은 다음 호출을 막고 늦은 응답을 버리는 기준이며 **실행 중인 동기 SDK 호출을
취소하는 timeout이 아니다**. provider의 HTTP timeout/retry 설정은 별도다.

문자 예산은 계획에 적용한다. 정확한 입력 토큰 검사를 사용하려면
`token_counter(prompt, body, schema)`와 `max_input_tokens`를 함께 설정한다.
미설정 상태는 `token_budget_checked=false`로 기록하며 모델 토큰 예산 검증을 주장하지 않는다.
출력 토큰 여유분/모델별 실제 context 한도와 SDK 내부 호출 수는 호출자/provider에서 관리한다.

## 아직 표현하지 못하는 조건

`CONTEXT_DEPENDENT`, 다른 후보의 필드 근거, 미해결 별표 참조는 지금의 단일 raw 슬롯으로
억지 합성하지 않는다. 해당 후보 전체를 adapter_pending에 남기고 분석은 불완전으로 처리한다.
원문 범위 공백(source_gaps)도 성공으로 숨기지 않는다.

canonical에서 UNMAPPED_* / UNKNOWN_LEGACY_*가 된 새 경로의 요건은 NOTICE_FACT로만
처리하지 않고 PIPELINE/WARNING으로 표시한다. 기존 legacy 정책은 변경하지 않는다.

처리 내역 COMPLETE와 의미 정확성은 여전히 다르다. 모델이 NOT_REQUIREMENT로 잘못
분류하거나 독립 조건으로 잘못 판단하는 문제, 원문 안의 값 역할·조건 관계의 정확성,
부모 조건의 적용, 추출 이후 판정 정확성은 이 단계에서 입증하지 않았다.
AND/OR 트리·예외·그룹 보존·버전 간 요건 정체성은 4~5단계에서 구현한다.

## 추적 기록

진단에는 요청/응답/프롬프트/스키마 SHA-256, 대상/문맥 ID, 호출 시간과 결과 코드,
미응답·오류·차단 목록, 서버가 확인한 필드 구간과 후보 위치를 기록한다.
원문 텍스트·모델 사유·예외 메시지·API 키는 진단에 복사하지 않는다.
외부 ID 자체에 원문을 넣은 응답도 해시로 바꿔 기록한다.

모델명·temperature·seed·system_fingerprint·미지원 파라미터는 어댑터가 노출하는
필드만 기록한다. 현재 기준 provider가 노출하지 않는 항목은 null/부재일 수 있다.
이 기록으로 모델 결정성이나 실제 지원 파라미터를 추정하지 않는다.

## 이번 검증

Python 3.13.5에서 아래 두 명령으로 **같은 신규 테스트 65개**를 실행했다.
두 실행을 130개 테스트로 합산하지 않는다.

```bash
python -m unittest discover -s apps/api/tests -p 'test_review_execution.py' -v
python -m unittest discover -s apps/api/tests -p 'test_review_pipeline.py' -v
python -m pytest -q apps/api/tests/test_review_execution.py apps/api/tests/test_review_pipeline.py
```

- 53개: 후보·계획·실행·변환 모듈 실제 파일, 모델 callable만 테스트 대역
- 4개: 실제 OpenAIStructuredExtractor + fake SDK client, 거부/JSON 오류 포함
- 8개: 실제 analysis_pipeline 파일의 분기·전달·상태 처리, 기존 후단 의존성은 테스트 대역
- JSON Schema 구조와 정상 샘플을 jsonschema로 검사
- 변경 파일 구문 컴파일 통과
- 재현에 사용한 기존 review_coverage/review_plan/provider 원문은 GitHub blob SHA와 일치 확인

**미실행:** 이전 70개 테스트의 이번 재실행, 전체 API·DB 회귀, 실제 OpenAI 호출,
J14/구내식당 반복 실측, 실제 canonical/판정기까지 연결한 전체 실행, 브라우저/Copilot E2E.
따라서 CI 전체 통과나 실모델 성능 향상을 보고하지 않는다.
