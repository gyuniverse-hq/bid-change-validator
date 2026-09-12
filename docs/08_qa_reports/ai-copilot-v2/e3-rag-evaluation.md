# AI Copilot E3 — 근거 기반 Document QA 평가

## 현재 상태

E3 Grounded Document QA 연결 후 기본 회귀를 통과했다.

- Backend 관련 테스트: **30 passed / 1.98s**
- Frontend semantic/document-RAG opt-in 경계: **PASS**
- `apps/web` production build: **Build complete**
- `vinext`의 일부 route `Unknown` 표시는 dynamic API usage를 정적 분석하지 못하는 안내이며 build failure가 아니다.

## 구현 경계

- Semantic 의미분류 동의와 Document RAG 외부처리 동의를 별도로 유지한다.
- Document RAG 동의가 없으면 공개 문서 retrieval/generation을 실행하지 않는다.
- 현재 notice version의 공개 문서만 검색한다.
- retrieval 0-hit이면 generation을 호출하지 않고 abstain한다.
- Grounded Answer가 검증 가능한 citation을 하나도 사용하지 않으면 생성 문장을 사용자에게 노출하지 않는다.
- 다른 notice version의 index/hit/citation 혼입은 fail-closed한다.
- Document QA는 회사 참가 가능/불가를 독자적으로 판정하지 않는다.

## 평가셋

고정 입력:

- `apps/api/eval/copilot_e3_document_qa.json`: 기존 `시나리오120`의 DOCUMENT_QA 60건
- `apps/api/eval/copilot_e3_expected_evidence.json`: 해당 질문이 참조하는 골든 근거 발췌

둘 다 **독립 검토자 승인 전 DRAFT**다. 정답률/법률적 정확도 확정 자료로 표현하지 않는다.

### 범위 예외

`D04-3`은 현재 001차 근거 `E014`와 이전 000차 근거 `E017`을 동시에 요구한다. 현재 Document RAG는 한 notice version만 검색하므로 이 케이스는 retrieval miss가 아니라 **cross-version scope gap**으로 별도 기록한다.

### 평가 타깃 버전 주의

원래 Copilot 시나리오 표는 초기 78개 근거를 기준으로 작성됐고, 이후 golden v0.2에 보완 발췌가 추가됐다. 따라서 아래는 retrieval 결과를 해석할 때 target drift 후보로 함께 검토한다.

- D03-1: 세 업종 상세는 E079~E081이 보완
- D03-2: 기술역량 OR 구조/대안은 E082~E086이 보완
- D15-1 / D15-3: 실제 5898 / 5815 / 7607 문구는 E087~E088이 보완

## 첫 Hybrid Retrieval baseline

실행 설정:

- method: `hybrid`
- `k=4`, `fetch_k=12`
- 총 질문 60, 실제 평가 59, scope gap 1
- DB 연결은 configured Supabase session pooler가 EMAXCONNSESSION으로 막혀 **transaction pooler fallback**을 사용
- source lookup failure: 0

원시 결과:

- 기대 evidence 72개 중 strict quote hit 54개
- **Evidence Recall@4 = 0.7500**
- **Case Any-hit@4 = 0.7288**
- **Case All-hit@4 = 0.7119**
- latency p50 **214.64ms**, p95 **1935.62ms**, mean **739.11ms**

이 수치는 **Unicode/공백 정규화 후 frozen excerpt 포함 여부만 보는 strict retrieval baseline**이다. 답변 정확도, 의미상 동등한 근거 지원률, 사용자 task completion이 아니다.

### baseline 해석 시 발견한 평가 데이터 문제

첫 run 결과의 `source_identity_matches_frozen_evidence`가 다수 false로 표시돼 원인을 재검산했다. RAG DB의 notice version이 틀어진 것이 아니라, 저장소에 처음 만든 `copilot_e3_expected_evidence.json` 일부가 golden fixture의 이전 UUID를 들고 있었다.

조치:

- `golden_fixtures_v02/sources/evidence_all.json`에서 실제 사용되는 63개 evidence row를 다시 추출해 expected evidence fixture를 v0.2로 갱신
- quote / document_id / version_id / source_order를 최신 golden v0.2와 정렬
- 독립 검토자 미승인 상태는 그대로 유지

이 identity 정정은 provenance 검증을 바로잡는 작업이다. 기존 75% strict recall을 임의로 높이기 위한 점수 조정이 아니다.

### strict miss 1차 관찰

strict `Case All-hit@4` 실패는 17건이었다.

`D04-1, D07-1, D08-1, D08-2, D11-1, D12-3, D13-2, D14-3, D15-1, D15-2, D15-3, D16-3, D17-1, D17-2, D17-3, D19-1, D19-2`

이 중 일부는 진짜 retrieval miss와 strict quote matcher false negative가 섞여 있다. 예를 들어 D08-1은 `단일 계약 건 2억원 이상`, D08-2는 최근10년/단일2억원 조건, D16-3은 설치 치수와 국솥 3대 문장이 Top-4에 실제 검색됐지만 frozen excerpt와 문자열이 완전히 같지 않아 strict miss로 집계됐다. 반대로 D04-1, D07-1처럼 Top-4에 요구 자격 문장이 전혀 나오지 않은 케이스는 실제 retrieval miss 후보다.

따라서 다음 비교에서는 두 층을 분리한다.

1. **Strict excerpt Recall@K**: 현재 기준 유지. 모델/휴리스틱으로 정답을 부풀리지 않는다.
2. **Support review**: strict miss를 사람이/고정 rubric으로 검토해 `실제 retrieval miss / equivalent-support / stale target / cross-version gap`으로 분류한다.

## Retrieval 평가 지표

- `Evidence Recall@4`: frozen 기대 발췌가 Top-4 chunk 안에 실제 포함됐는가
- `Case Any-hit@4`: 질문별 기대 발췌 중 하나 이상 검색됐는가
- `Case All-hit@4`: 질문별 기대 발췌가 모두 검색됐는가
- `Scope gap`: 현재 단일버전 retrieval로 원천적으로 답할 수 없는 질문
- retrieval latency p50 / p95 / mean

평가기는 fuzzy semantic judge로 검색 성공을 만들어내지 않는다. Unicode/공백 정규화 후 실제 발췌와 chunk의 포함 관계만 확인한다.

## 다음 실행

expected evidence identity 갱신 후 hybrid를 같은 조건으로 재실행해 provenance를 검산한다.

```powershell
python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa `
  --output e3-retrieval-hybrid-v2.json
```

그 다음 같은 frozen fixture에서 dense baseline을 실행한다.

```powershell
python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa `
  --method dense_post `
  --output e3-retrieval-dense.json
```

두 결과를 비교한 뒤에만 hybrid 유지/개선 여부를 결정하고, 이후 Grounded Answer citation/abstention/답변 정확도 평가로 넘어간다.
