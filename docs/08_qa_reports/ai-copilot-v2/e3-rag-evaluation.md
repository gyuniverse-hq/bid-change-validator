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

원래 Copilot 시나리오 표는 초기 78개 근거를 기준으로 작성됐고, 이후 golden v0.2에 보완 발췌가 추가됐다. 따라서 아래는 첫 retrieval run 결과를 해석할 때 target drift 후보로 함께 검토한다.

- D03-1: 세 업종 상세는 E079~E081이 보완
- D03-2: 기술역량 OR 구조/대안은 E082~E086이 보완
- D15-1 / D15-3: 실제 5898 / 5815 / 7607 문구는 E087~E088이 보완

이 항목은 점수를 올리기 위해 임의로 정답을 바꾸지 않는다. 첫 run miss 결과와 최신 107개 근거를 함께 보고, **retrieval failure와 stale evaluation target을 분리**한 뒤 평가셋 수정 여부를 기록한다.

## Retrieval 평가 지표

첫 실행은 생성 답변과 분리해 `hybrid(k=4, fetch_k=12)` retrieval만 측정한다.

- `Evidence Recall@4`: frozen 기대 발췌가 Top-4 chunk 안에 실제 포함됐는가
- `Case Any-hit@4`: 질문별 기대 발췌 중 하나 이상 검색됐는가
- `Case All-hit@4`: 질문별 기대 발췌가 모두 검색됐는가
- `Scope gap`: 현재 단일버전 retrieval로 원천적으로 답할 수 없는 질문
- retrieval latency p50 / p95 / mean

평가기는 fuzzy semantic judge로 검색 성공을 만들어내지 않는다. Unicode/공백 정규화 후 실제 발췌와 chunk의 포함 관계만 확인한다.

## 실행

```powershell
python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa --validate-only

python -m apps.api.app.scripts.evaluate_copilot_e3_document_qa `
  --output e3-retrieval-hybrid.json
```

첫 결과를 받은 뒤 miss 케이스를 `검색 실패 / 기대근거 target drift / chunk boundary / source scope gap`으로 분류하고, 그 다음에 dense vs hybrid vs rerank 비교 및 Grounded Answer 채점을 진행한다.
