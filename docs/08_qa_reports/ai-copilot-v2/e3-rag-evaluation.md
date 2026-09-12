# AI Copilot E3 — 근거 기반 Document QA 평가

## 현재 상태

E3 Grounded Document QA 연결 후 기본 회귀와 retrieval 비교를 진행했다.

- Backend 관련 테스트: **30 passed / 1.98s**
- Frontend semantic/document-RAG opt-in 경계: **PASS**
- `apps/web` production build: **Build complete**
- `vinext`의 일부 route `Unknown` 표시는 dynamic API usage를 정적 분석하지 못하는 안내이며 build failure가 아니다.
- 현재 retrieval 기준선: **Hybrid (BM25 + Dense, RRF)**
- 현재 단계: Dense vs Hybrid 비교 완료, Hybrid + LLM rerank 평가 대기

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
- `apps/api/eval/copilot_e3_expected_evidence.json`: 해당 질문이 참조하는 golden v0.2 근거 발췌

둘 다 **독립 검토자 승인 전 DRAFT**다. 정답률/법률적 정확도 확정 자료로 표현하지 않는다.

현재 canonical 비교 fixture:

- cases SHA256: `b0aa4e891da01004d32473f41b6e5a26386feab1a1f71b559969f48f89dae585`
- evidence SHA256: `94952b895818d576b7b45b640132d38a752e66114943ee341e3b50b77b48e6f4`

### 범위 예외

`D04-3`은 현재 001차 근거 `E014`와 이전 000차 근거 `E017`을 동시에 요구한다. 현재 Document RAG는 한 notice version만 검색하므로 이 케이스는 retrieval miss가 아니라 **cross-version scope gap**으로 별도 기록한다.

### 평가 타깃 버전 주의

원래 Copilot 시나리오 표는 초기 78개 근거를 기준으로 작성됐고, 이후 golden v0.2에 보완 발췌가 추가됐다. 따라서 아래는 retrieval 결과를 해석할 때 target drift 후보로 함께 검토한다.

- D03-1: 세 업종 상세는 E079~E081이 보완
- D03-2: 기술역량 OR 구조/대안은 E082~E086이 보완
- D15-1 / D15-3: 실제 5898 / 5815 / 7607 문구는 E087~E088이 보완

## Historical run — provenance 정정 전 Hybrid

초기 expected evidence fixture의 일부 `version_id/document_id`가 golden v0.2와 달랐던 상태에서 다음 결과가 한 번 측정됐다.

- Evidence Recall@4 = 0.7500
- Case Any-hit@4 = 0.7288
- Case All-hit@4 = 0.7119

이 결과는 **현재 canonical retrieval 성능으로 사용하지 않는다.** 이후 `golden_fixtures_v02/sources/evidence_all.json` 기준으로 expected evidence 63개 row의 quote / document_id / version_id / source_order를 재정렬했다. 따라서 아래 v2 결과와 이 historical 75%를 직접 증감 비교하지 않는다.

## Canonical Retrieval 비교 — 동일 fixture

공통 조건:

- 총 질문: 60
- 실제 평가: 59
- cross-version scope gap: 1 (`D04-3`)
- source lookup failure: 0
- `k=4`, `fetch_k=12`
- 동일 cases/evidence SHA 사용
- Supabase session pooler가 포화되어 transaction pooler fallback 사용

### Dense post-processing

- 기대 evidence: 72개
- strict evidence hit: 21개
- **Evidence Recall@4 = 0.2917**
- **Case Any-hit@4 = 0.3220**
- **Case All-hit@4 = 0.2712**
- latency p50 **144.50ms**, p95 **210.98ms**, mean **176.04ms**

### Hybrid (Dense + lexical BM25 + RRF)

- 기대 evidence: 72개
- strict evidence hit: 36개
- **Evidence Recall@4 = 0.5000**
- **Case Any-hit@4 = 0.5254**
- **Case All-hit@4 = 0.4915**
- latency p50 **170.58ms**, p95 **230.54ms**, mean **214.36ms**

### 비교

| Metric | Dense | Hybrid | Difference |
|---|---:|---:|---:|
| Evidence Recall@4 | 29.17% | **50.00%** | **+20.83%p** |
| Case Any-hit@4 | 32.20% | **52.54%** | **+20.34%p** |
| Case All-hit@4 | 27.12% | **49.15%** | **+22.03%p** |
| latency p50 | **144.50ms** | 170.58ms | +26.08ms |
| latency p95 | **210.98ms** | 230.54ms | +19.56ms |
| latency mean | **176.04ms** | 214.36ms | +38.32ms |

케이스 비교에서도 Dense만 `all-hit` 성공하고 Hybrid가 실패한 케이스는 **0건**이었다. 반대로 Hybrid에서만 추가 `all-hit` 성공한 케이스는 **13건**이었다.

따라서 현재 실험 범위에서는 **Dense 단독보다 Hybrid를 retrieval 기준선으로 유지**한다. latency 증가는 p50 약 26ms / p95 약 20ms인 반면 strict retrieval 지표는 약 20~22%p 개선됐다.

## Strict metric 해석 주의

현재 수치는 **Unicode/공백 정규화 후 frozen excerpt 포함 여부만 보는 strict retrieval metric**이다. 답변 정확도, 의미상 동등한 근거 지원률, 사용자 task completion이 아니다.

Hybrid v2의 strict `Case All-hit@4`는 29/59다. 실패 30건 중 일부는 실제 retrieval miss지만 일부는 답을 만들 수 있는 의미상 동등 근거가 Top-4에 있는데 frozen quote가 문자 그대로 포함되지 않아 실패 처리된다.

예시:

- `D08-1`: Top-4에 `최근 10년`, `단일 계약 건 2억원 이상` 근거가 검색됐지만 E034 frozen quote 전체와 문자열이 동일하지 않아 strict miss.
- `D09-2`: Top-1에 `3572 ... 또는 ... 1320` 문장이 검색됐지만 frozen quote normalization 차이로 strict miss.
- `D12-1`: 공동수급 구성원별 기술인 1명 이상 조건이 Top-2에 검색됐지만 frozen quote wording과 정확 일치하지 않아 strict miss.
- `D14-1`: 회사 제조/수입/판매 허가와 제품 품목허가가 Top-4에 함께 존재하지만 quote 단위 strict matcher에서는 miss.
- `D16-3`: 설치 치수와 국솥 3대 동시가동 근거가 Top-2에 존재하지만 strict E064 quote와 정확 일치하지 않아 miss.
- `D20-1` / `D20-3`: 사전 신청 허용, 5일 내 확인, 기업구분, 유효기간 시작일 조건이 긴 Top hit에 포함돼 있으나 E077/E078 frozen quote 단위와 일치하지 않아 strict miss.

반면 `D04-1`, `D07-1`처럼 질문에 필요한 핵심 자격 근거가 Top-4에 실제로 나오지 않는 케이스는 **실제 retrieval miss 후보**다.

따라서 최종 평가는 두 층을 유지한다.

1. **Strict excerpt Recall@K**: 현재 자동 점수. fuzzy judge로 점수를 올리지 않는다.
2. **Support review**: strict miss를 `actual retrieval miss / equivalent support / stale target / cross-version scope gap`으로 분리한다.

## 다음 단계 — Hybrid + LLM Rerank

저장소에 `apps/api/app/scripts/evaluate_copilot_e3_rerank.py`를 추가했다.

기존 `retrieval.py`의 `hybrid_rerank`를 그대로 사용한다.

- 후보 생성: 현재 Hybrid
- 후보 수: 최대 12
- LLM 역할: 질문에 직접 답하는 근거를 위로 재정렬만 함
- 새 사실 생성/참가자격 판정 금지
- 최종 Top-4로 동일 strict metric 재측정
- 59개 평가 케이스이므로 정상 완료 시 rerank model call 59회
- 모델명 / model_calls / latency를 결과에 기록

채택 기준은 사전에 다음처럼 둔다.

- Hybrid 대비 retrieval 지표가 의미 있게 개선되어야 함.
- 특히 현재 Hybrid가 놓치는 실제 retrieval miss가 회수되는지 확인한다.
- LLM latency / 비용 증가가 작은 품질 향상에 비해 과도하면 제품 경로에는 채택하지 않는다.
- rerank 점수도 답변 정확도나 전체 Copilot 정확도로 표현하지 않는다.

실행:

```powershell
python -m apps.api.app.scripts.evaluate_copilot_e3_rerank `
  --output e3-retrieval-hybrid-rerank.json
```

Rerank 결과를 Dense / Hybrid와 비교한 뒤 retrieval 방식을 잠그고, 이후 Grounded Answer citation support / abstention / 답변 정확도 평가로 이동한다.
