# 4-A — 원문 복원·수치 역할·조건 논리 기반

## 기준과 범위

부모 commit: `da380d5`, 브랜치: `refactor/qualification-reliability`.
4단계 전체 완료가 아니다. 이번에는 원문 복원을 기존 review_v1에 연결하고,
4-B의 의미 해석 계약이 사용할 역할별 피연산자와 조건 그래프를 구현했다.

기존 legacy·HTTP API·DB·Copilot·골든셋·평가기·판정 규칙은 변경하지 않았다.
PR #136을 합치거나 develop/main을 업데이트하지 않았다.

## 1. 유일한 실제 원문 구간

`review_grounding.resolve_source_quote(source, quote, base_offset=...)`

- exact 우선, 없을 때만 비교용 NFKC/공백/장식기호 정규화를 적용한다.
- 반환 quote는 실제 source slice이고 offset은 원래 block.text의 Python 문자 좌표다.
- 같은 표현이 여러 곳에 있으면 첫 번째로 고르지 않는다.
- 쉼표/세미콜론 분해나 서로 떨어진 원문 구간 합성은 하지 않는다.
- 15억원에서 5억원, 1.3억원에서 3억원, 14501에서 1450을 부분 인용하지 않는다.
- NFKC 확장 한 문자의 일부를 원문 문자 전체로 바꾸지 않는다.
- 문자별 정규화의 위치 매핑이 전체 NFKC와 다르면 명시적으로 거부한다.
  조합 자모/결합 문자 일반 지원은 아직 아니다. exact 일치는 그대로 가능하다.
- 장식기호를 검색에서 무시한다고 각주 의미를 삭제하거나 예외 적용을 승인하는 것은 아니다.

`review_execution`의 기존 candidate/문맥/문서 범위 검사 후 이 함수를 호출한다.
`GroundedField.match_method`로 EXACT/NORMALIZED를 기록하고 감사 기록에
`grounding_version`을 남긴다. 원문 텍스트를 감사 로그에 추가하지 않는다.
같은 실제 slot이 exact/normalized 두 형태로 반환돼도 중복 slot 검사를 우회하지 않는다.

## 2. 수치의 역할을 보존하는 피연산자

`review_operands.parse_source_operand(...)`는 실제 인용과 위치를 입력받는다.
역할을 코드가 임의 결정하지 않고 다음 역할 중 명시한 것을 사용한다.

| 역할 | 예시 | 코드 결과 |
|---|---|---|
| LOOKBACK_WINDOW | 최근 2년 이내 | 24 MONTH, <=, 기준일 별도 |
| OPERATION_DURATION | 1년 이상 | 12 MONTH, >= |
| PERFORMANCE_AMOUNT | 5천만원 이상 | 50000000 KRW, >= |
| BUDGET_AMOUNT | 5억원 이상 | 동일 숫자여도 실적 금액과 다른 역할 |
| PERFORMANCE_COUNT | 2개 이상 | 2 COUNT, >= |
| STAFF_COUNT | 5명 이하 | 5 PERSON, <= |
| DAILY_VOLUME | 1일 평균 800식 이상 | 800 MEAL_PER_DAY, >= |

부가세 포함/별도/제외는 인용에 명시된 것만 읽으며 미기재는 UNSPECIFIED다.
최근 기간의 anchor는 NOTICE_DATE/SUBMISSION_DEADLINE/CONTRACT_START 중 호출자가
제공하며 None이면 미지정이다. 현재 날짜로 자동 대체하지 않는다.

한 표현만 지원한다. 복수 기간/금액, 부정확한 쉼표, 근사치, 미지원 복합 숫자 표현,
연산자 없는 임계값은 임의 정규화하지 않는다. Decimal의 기본 정밀도를 넘는 숫자도
반올림하지 않도록 계산 정밀도를 조절한다.

현재 모델 응답에 role을 추가하거나 기존 기간_norm을 이 함수로 바꾸지는 않았다.
역할을 잘못 선택하면 원문에 있는 예산을 실적액으로 잘못 해석할 수 있다.
파싱 성공은 역할 선택/자격요건 여부/회사 판정의 정확성 보증이 아니다.

## 3. 논리 연결과 의미 지문

`review_conditions` 내부 계약:

- AtomicCondition: 유형·값·연산자·단위·기간·scope·주체·필수 여부·역할의 의미 JSON,
  별도 evidence ID 목록. raw 문자열 일치만으로 같은 원자로 보지 않는다.
- ConditionNode: ATOM / ALL_OF / ANY_OF / NOT / EXEMPT_IF.
- ConditionGraph: root와 명시적 node/atom 참조.

순환, 고립된 원자/노드, 중복 ID, 빈 논리 그룹, 잘못된 연산자, 미해결 참조를 거부한다.
관계 노드에도 evidence ID를 요구하고, available_evidence_ids를 주면 존재 여부를 검사한다.
이 검사는 원문이 해당 논리를 의미한다는 의미적 검증과 다르다.

`semantic_fingerprint`는 AND/OR 자식 나열 순서와 표시 ID는 무시한다.
값·연산자·기간·범위·주체가 바뀌면 지문이 달라진다. EXEMPT_IF의 requirement와
exemption 순서는 보존한다. 이 지문은 버전 간 요건 계보/매칭 ID가 아니다.

## 4. 그룹을 잃지 않는 중복 처리

`deduplicate_atoms()`는 동일 의미의 원자를 공유하고 근거를 합친다.
하지만 해당 원자를 사용하는 각 그룹의 연결은 그대로 둔다.

```text
(A 또는 B) 그리고 (A 또는 C)
```

A 원자 데이터는 하나로 통합 가능하지만 두 그룹의 A 연결은 모두 남는다.
연산자·기간·범위·주체가 다르면 값이 같아도 통합하지 않는다.
업종명처럼 보인다는 이유로 별개 인증 요건을 삭제하지 않는다.

같은 A값을 공유하는 원자들에 일관된 판정값을 공급했을 때, 중복 전후 가능한
세 상태의 조합 27개에서 결과가 같음을 테스트했다. 이 정책을 기존 dedup에
전역 적용하지 않았다. 그룹 구조를 공급하는 4-B 경로에서 사용해야 한다.

## 5. 논리 계산과 동일 실적의 조건 집계

`evaluate_condition_graph(graph, judgments)`는 SATISFIED/UNSATISFIED/UNKNOWN으로
이미 판정한 원자들을 합성한다. 미지정 원자는 UNKNOWN이고 빈 그래프는 성공이 아니다.

```text
(A업종 AND 인증) OR B업종
A만 보유, 인증 없음, B 없음 → UNSATISFIED
```

EXEMPT_IF(requirement, exemption)는 명시적으로 그 요건을 면제하는 관계다.
일반적인 '다만/예외' 문장을 임의로 이 연산자로 바꾸면 안 된다.
이 함수는 조건식의 만족 여부를 계산하며 선호 조건을 포함한 전체 자격 판정을
자동 구성하지 않는다. 적용 범위와 mandatory 집계는 호출자 계약의 책임이다.

`count_matching_records()`는 실적/사업장마다 조건 전체를 평가한 뒤 만족하는 건수를 센다.
800식 기준은 사업장1, 1년 운영 기준은 사업장2가 만족한다고 한 건 충족으로 합치지 않는다.
실적 목록이 불완전하거나 일부 사실이 없으면 확실한 충족 수와 가능한 상한을 분리해
UNKNOWN을 처리한다. 충분한 충족 건수가 이미 있으면 목록이 불완전해도 충족은 입증 가능하다.
날짜/금액/실적 DB 사실의 실제 원자 판정은 이 함수가 직접 실행하지 않는다.

## 6. 테스트

```bash
python -m pytest -v apps/api/tests/test_review_execution.py \
  apps/api/tests/test_review_source_semantics.py \
  apps/api/tests/test_review_condition_logic.py
```

Python 3.13.5에서 246개 통과. 기존 53개 + 신규 70개 + 신규 123개다.
22개 subtest는 중복 합산하지 않는다.

실제 실행/계획/후보/slot 변환 모듈로 정상화 연결과 누락만 재시도하는 회귀를 검사했다.
모델 callable은 테스트 대역이고 수치/논리 입력은 합성 사례다.
기존 파일은 GitHub blob SHA와 일치함을 확인한 뒤 사용했다.

변경 파일 구문 컴파일 통과. 이번 테스트는 전체 API 회귀나 실제 모델 성능 평가가 아니다.
실제 LLM/DB/J14·구내식당/기존 canonical·판정기 전체/브라우저·Copilot은 미실행.
1~2단계 70개 및 3단계 provider/분기 12개는 이번 재실행 수에 포함하지 않는다.

## 7. 다음 연결 단계 (4-B)

- 역할·대상·조건 관계·면제 범위의 모델 응답 계약과 원문 근거 검증.
- 같은 실적에 적용되는 복수 조건을 명시하는 레코드 범위 계약.
- 새로운 내부 그래프에서 기존 판정 입력으로 변환할 수 있는 범위 검증.
- 표현되지 않는 조건을 축약해 기존 성공 상태로 보내지 않기.
- 고정 입력의 구 경로/새 경로 비교 및 실제 모델 반복 검증.

현재 review_v1의 응답은 slots 목록이다. 새 논리 그래프를 모델이 직접 공급하는
경로는 아직 없으며, 이 commit만으로 복합조건 추출 성능 향상을 주장하지 않는다.
