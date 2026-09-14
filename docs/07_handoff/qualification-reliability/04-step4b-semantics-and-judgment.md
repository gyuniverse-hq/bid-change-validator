# 4-B — 모델의 의미 응답과 실제 회사 판정기 연결

부모 commit `ebbfb46`, 브랜치 `refactor/qualification-reliability`.
이 기록은 구현과 대역 기반 통합 검증 결과다. 실제 LLM/DB/웹 성능 실측이 아니다.

## 변경 범위

- `extraction/review_execution.py`: 선택적 ReviewResponseContract. 기존 슬롯 계약이 기본.
- `extraction/review_semantics.py`: 엄격한 의미 응답 스키마, source 구간/역할/관계 검사 및 그래프 컴파일.
- `extraction/review_semantic_judgment.py`: 새 그래프의 원자 → 기존 judge_requirement → 원래 논리 구조.
- `tests/test_review_semantics.py`, `tests/test_review_semantic_judgment.py`: 실제 모듈 연결 검증.
- 문서 두 개. 기존 HTTP API/DB/Copilot/판정 규칙/골든셋/평가기 변경 없음.

extraction 경로는 `apps/api/app/ai/qualification/extraction`, tests는 `apps/api/tests`다.

## 호출 흐름

```text
Backend가 전달한 문서 블록
→ 기존 ReviewInventory/ReviewPlan
→ 기존 실행기 + semantic_response_contract()
→ 후보별 상태 + 원자 + 논리 노드 + 원문 근거
→ 원문 구간 확인/수치 정규화/관계 구조 검증
→ 기존 QualificationRequirement로 표현 가능한 원자 변환
→ 기존 judge_requirement(실제 회사 스냅샷)
→ 원래 그래프의 AND/OR 결과 계산
→ 조항별 판정 및 미해결 사유
```

기존 `analyze_qualification_documents`와 기본 legacy는 그대로다. 새 경로의 반환형은
기존 RequirementAnalysisResult가 아니라 내부 SemanticAnalysis다. 그래프를 평탄한
목록으로 바꾸어 기존 저장소에 쓰지 않는다.

```python
from app.ai.qualification.extraction.review_semantic_judgment import analyze_qualification_semantics

result = analyze_qualification_semantics(
    analysis_input,                # 기존 Backend가 검증한 QualificationAnalysisInput
    structured_extract=extractor,  # 기존 OpenAIStructuredExtractor 호출 계약
    profile=company_snapshot,      # 기존 CompanyProfileSnapshot
    preflight_case_id=case_id,
    reference_date=reference_date,  # date 필수; 현재 날짜 자동 대입 없음
    anchor_dates={"NOTICE_DATE": notice_date},
)
# result.execution: 누락/오류/호출 내역
# result.judgments: 조항별 판정. 공고 전체 참가 가능 여부가 아님.
# result.audit(): 원문/회사 상세 자료를 복제하지 않는 진단
```

실제 키가 있는 extractor로 위 함수를 호출하면 모델 호출이 발생한다. 이번 검증에서는
동일한 callable 계약의 테스트 대역을 사용했으며 실제 API 요청은 보내지 않았다.

## 의미 응답 계약

후보별 decision은 candidate_id/status/reason/basis/role/atoms/nodes/root_id를 가진다.
REQUIREMENT는 그래프를 갖고, 나머지 상태는 reason과 빈 atoms/nodes 및 null root다.
미응답 후보만 원래 ID와 문맥으로 재요청하는 기존 정책을 재사용한다.

원자는 다음을 지정한다.

- type 및 BIDDER/REPRESENTATIVE/JOINT_VENTURE_MEMBER subject
- predicate_source: 하나의 조건과 수식어가 있는 연속 원문 구간
- value_role + value_source: 조건 안의 값 근거
- qualifiers: 기간/분야/대상 기관/운영기간/일일 규모/발급기관/인력 역할
- aggregation + aggregation_source: MAX/SUM은 명시적 단일/합산 근거가 필요

source는 source_candidate_id와 quote다. 모델이 정규 수치나 start/end 좌표를 작성하지
않는다. 코드는 실제 원문을 복원하고 값/수식어가 그 조건 내부에 있는지 확인한다.
반복 숫자는 유일한 조건 구간 안에서 위치를 찾는다. 공고 전체의 첫 일치값을 쓰지 않는다.

LOOKBACK_WINDOW는 인정기간, OPERATION_DURATION는 각 실적의 운영기간이다.
5천만원의 value는 코드로 50000000이 된다. 원문 예산을 실적액으로 붙이는 직접 반례를
차단한다. 부가세 기준과 시간 anchor도 명시한 근거를 확인하며 미지정은 추정하지 않는다.

nodes는 ATOM/ALL_OF/ANY_OF/NOT/EXEMPT_IF이며 논리 노드에도 원문 근거가 필요하다.
각 관계의 표식이 있고 근거 구간이 자식 조건 범위를 포함하는지 확인한다. 이 검사는
원문 뜻과 모델 그래프가 일치한다는 수학적 증명이 아니며 실모델 평가가 필요하다.

## 중복과 조건 손실 검사

그래프의 고립 노드/원자·순환·외부 참조는 거부한다. 기존 조건 모듈의 의미 지문은
값/기간/범위/역할/주체/논리를 포함하며 모델 로컬 ID나 나열 순서에는 의존하지 않는다.
판정 시 같은 의미 원자를 공유하되 원래 그룹 연결을 유지한다. 같은 의미의 원자가
원문 의존 규칙 때문에 서로 다르게 판정되면 임의 선택하지 않고 UNKNOWN으로 만든다.

일부 명시적 업종코드/ISO 인증/임계값/최근 기간이 값 또는 수식어로 표현되지 않으면
UNREPRESENTED_EXPLICIT_VALUE를 남긴다. 이는 제한된 누락 탐지이며 전체 자연어
요건의 완전성을 보증하지 않는다. 후보 모두가 NOT_REQUIREMENT인 오분류도 별도 평가 대상이다.

## 기존 판정기의 실제 재사용

실제 contracts와 rules.judge_requirement를 호출한다. 원래 안전 가드와 확장 로직을
끄지 않으며, 새로운 scope를 기존 엔진이 무시하게 그대로 넘기지도 않는다.
표현 가능한 scope만 명시적으로 변환한 뒤 기존 엔진에 전달한다.

합성 원문 `(A업종 AND 인증) OR B업종`에서:

- A만 보유, 인증·B 없음 → UNSATISFIED
- A와 인증 보유 → SATISFIED
- B만 보유 → SATISFIED
- A 보유, 인증 자료 불완전, B 없음 → UNKNOWN
- B 보유, 인증 자료 불완전 → SATISFIED

실적액은 기존 MAX/SUM/UNSPECIFIED 판정 경로를 사용한다. 각 1.2억원 두 건과
2억원 기준에서 MAX는 미충족, SUM은 충족, 집계 미지정은 UNKNOWN으로 검증했다.

추가 운영개월/일일급식량은 RecordObservation(record_ref, basis_id, ...)으로 받는다.
이는 Backend/검증 자료가 공급하는 사실이며 LLM 출력에서 만들지 않는다.
기간을 임의 날짜 차이로 만들거나 부가세 기준을 추정하지 않는다. 고유한 record_ref를
프로필과 대조하고 같은 실적 하나에 날짜/분야/규모/기간 조건 전체를 적용한다.

사업장1이 규모만, 사업장2가 운영기간만 충족한다고 합쳐 세지 않는다. 자료가 부족하면
UNKNOWN이며, 확실한 충족 건수가 충분하면 실적 목록 전체가 미완성이어도 충족을 입증할 수 있다.
PERFORMANCE_COUNT의 >=/>와 운영기간·급식량 필터 조합을 지원한다. 다른 미지원 조합은
RECORD_FILTER_COMBINATION_UNSUPPORTED로 보존한다. 새 DB 입력 기능은 이번에 만들지 않았다.

회사/기준일/추가 사실의 유효성은 모델 호출 전에 확인한다. 회사 스냅샷은 추출 모델에
보내지 않는다. 판정 context 지문에는 회사 스냅샷/검토 건/기준일/anchor/추가 사실/규칙 버전을
넣고, 결과에는 상세 회사 자료 대신 지문을 남긴다.

## 미해결 상태와 안전한 범위

- 다중 조항 상속·미해결 별표·다른 후보의 조건·공동수급 주체는 pending으로 보존한다.
- partial 원자 몇 개만으로 해당 후보 전체를 확정하지 않는다.
- 선호/정보성 role을 그대로 유지한다. 선호 조건의 미충족을 공고 전체 미달로 승격하지 않는다.
- 결과는 조항별 조건식의 만족 여부다. 조항 간 관계를 일괄 AND라고 가정하지 않는다.
- audit의 notice_overall_status는 None이다. 다음 상태/적용 범위 계약이 필요하다.
- 원문 grounding/스키마 준수가 모델 의미 판단의 정확성을 보장하지 않는다.

## 이번 실행 검증

```bash
python -m pytest -v apps/api/tests/test_review_semantics.py \
    apps/api/tests/test_review_semantic_judgment.py
```

Python 3.13.5에서 **93개 통과**: 응답/컴파일/실행 36개 + 실제 판정 연결 57개.
기존 단계 테스트를 합산하지 않는다. 동일 93개를 여러 번 실행해도 테스트 수는 93개다.
JSON Schema 검사도 실제 수행했다. 테스트 데이터는 합성 원문/회사 자료이며
모델 I/O만 대역이다. 기존 판정기/확장/정규화 함수는 반환값을 모킹하지 않았다.
앱 패키지 초기화만 분리하고 실제 모듈 파일을 로드했다. 기존 의존 파일은 blob SHA 일치 확인.

검증에는 중첩 OR, 인증 누락, 동일 실적 필터, 불완전 자료, 단일/합산, VAT, 기준일,
공고 밖 값 연결, 원문/모델 응답 변조, 잘못된 회사 입력의 선제 차단, 회사 자료의 모델 입력
유출 방지, 원문 없는 audit, 기존 슬롯 계약 기본값 유지, 누락 후보만 재요청을 포함한다.

**미실행:** 전체 API 회귀/CI, 실제 DB/LLM, J14·구내식당 반복, 브라우저/Copilot,
기존 제품 HTTP부터 이어지는 E2E, 변경공고 의미 diff.
이 commit만으로 실제 모델 정확도/재현율 향상이나 현재 화면 문제가 해결됐다고 주장하지 않는다.
