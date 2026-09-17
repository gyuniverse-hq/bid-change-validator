# AI Copilot · Final Evaluation Narrative

> **상태: Current Summary + Historical Evaluation Evidence**  
> 문서 기준일: 2026-09-17 KST  
> Current 코드 기준: `develop` / `f56d3484e9c3ca1b1badbeafcda9bd5f057c65d5` (PR #151 병합 후)  
> 이 문서는 기존 평가 결과를 하나의 `정확도`로 합산하지 않습니다.

## 1. 목적

AI Copilot은 단일 모델 점수로 평가하기 어려운 기능입니다.

사용자 질문을 이해하는 문제, 올바른 Product Tool에 도달하는 문제, 공고문 근거를 검색하는 문제, 근거를 사용해 답변을 생성하는 문제, 대화 문맥을 유지하는 문제, 저장·재검증 같은 write를 안전하게 실행하는 문제는 서로 다른 실패 원인을 가집니다.

따라서 본 프로젝트는 평가를 다음처럼 분리했습니다.

```text
Routing
→ Product Task 도달
→ Retrieval
→ Grounded Answer / Citation
→ Multi-turn / Context
→ Action Safety
→ 실제 업무 Task
→ User Test
```

핵심 원칙은 **같은 분모가 아닌 수치를 하나의 `챗봇 정확도`로 합치지 않는 것**입니다.

## 2. 평가 스토리 한눈에 보기

| 단계 | 발견한 문제 | 개선 | 대표 결과 |
| --- | --- | --- | --- |
| Prototype | LLM이 판정까지 만들 위험 | 판정과 서술 분리 | `판정은 코드, 서술은 모델` |
| v1 | Tool/Action 계약 안정성 필요 | Product Tool + Proposal/Confirm 분리 | 고정 계약 회귀 최초 99/100 → 수정 후 100/100 |
| E0 | 자유입력 대부분 목표 기능에 도달하지 못함 | 기준선 고정 | intent exact 1/100, 정적 작업 완결 0/100 |
| E1 | 자주 쓰는 표현·UX 실패 | bounded alias + 실패 UX | intent 41/100, 대화·안전 완전 성공 5/20 → 9/20 |
| E2 | 키워드 substring 오분류 | weak read만 Semantic 재검토 | frozen routing 100/100 |
| E3 Retrieval | 관련 원문 회수 부족 | Dense → Hybrid 비교 | Recall@4 29.17% → 50.00% |
| E3 Rerank | 검색 품질 추가 개선 가능 | LLM Rerank 비교 | 55.56%, 그러나 지연/비용 때문에 기본 미채택 |
| E3 Prompt | 억지 citation·부분근거 과잉결론 | prompt v1 → v4 | fail-closed abstention, version integrity 100% |
| v3.1 | 생성문이 서버 사실과 반대일 수 있음 | Fact/Source/Claim 검증 | 합성/ASGI/브라우저 회귀 + 실제 모델 의미 검증 |
| Guided Job 평가 | 실제 업무 질문 범위의 안정성 필요 | 2 Job / 6 Question | 남원 J13~J16 24턴 중 23 COMPLETE |
| Human Test | 자동 점수와 실제 이해도 차이 | Stage 11 설계 | **최종 사람 결과 미완료** |

이 표의 수치는 평가 범위와 분모가 모두 다릅니다. 아래에서 각각을 따로 설명합니다.

---

# 3. Prototype — 판정과 서술을 먼저 분리

초기 챗봇 설계의 첫 번째 안전 원칙은 다음과 같았습니다.

> **판정은 코드가 끝내고, 모델은 이미 확정된 판정과 근거를 설명한다.**

초기 구현에서는 사람이 보는 판정 briefing과 모델이 보는 사실 입력을 가능한 한 동일하게 유지하고, 모델이 DB·판정 함수를 직접 사용해 새로운 적격 판단을 만들지 않도록 제한했습니다.

이 단계에서 얻은 교훈:

- 프롬프트에 `지어내지 마라`만 쓰는 것보다 모델에게 제공하는 사실 범위를 제한해야 한다.
- `이번 공고의 구체적 사실`과 `일반 지식 설명`은 다른 정책을 가져야 한다.
- 현재 사실은 매 턴 다시 읽고, 과거 모델 답변을 다음 턴의 사실 출처로 승격하지 않아야 한다.

참고: [`docs/llm-rag/08-chatbot-design-notes.md`](../llm-rag/08-chatbot-design-notes.md)

---

# 4. v1 — Product Tool / Action Contract 회귀

## 평가셋

`apps/api/eval/copilot_v1.json`

- Single-turn: **80개** = 8개 작업 × 10
- dev 40 / holdout 이름의 40
- Multi-turn: **20개**

8개 작업:

1. 판정 조회
2. 확인 항목
3. 요건 근거
4. 판정 당시 Profile
5. 변경 요건
6. 답변 제안
7. 재검증 제안
8. 문서 검색

Multi-turn에서는 `왜`, 순번, stale context, 자연어 동의, 부정, 부분/전체 재검증, 결과 조회 우선순위 등을 검사했습니다.

## 결과

| 그룹 | 최초 유효 실행 | 수정 후 고정셋 재검증 |
| --- | ---: | ---: |
| dev | 40/40 | 40/40 |
| holdout 이름의 40 | 39/40 | 40/40 |
| multi-turn | 20/20 | 20/20 |
| 합계 | **99/100** | **100/100** |

최초 실패는 `저장된 회사정보`라는 표현을 Profile read가 아니라 Action request로 오분류한 1건이었습니다.

수정은 `저장/반영/재검증` 같은 명사가 포함됐다는 이유만으로 write 의도라고 보지 않고 실제 실행 요청을 우선 확인하도록 조정했습니다.

### 해석 주의

수정 후 100/100은 **전체 챗봇 정확도 100%가 아닙니다.**

실패를 본 뒤 코드를 수정했기 때문에 같은 40문항의 재통과는 독립 holdout이 아니라 **노출된 고정 회귀셋 재검증**입니다.

참고: [`ai-copilot-v1-evaluation.md`](./ai-copilot-v1-evaluation.md)

---

# 5. E0 — 자유입력 Baseline

E0에서는 추천 버튼이나 명시 intent가 아니라 **사용자가 자기 표현으로 입력했을 때** 기존 deterministic router가 원하는 기능에 도달하는지를 측정했습니다.

평가셋:

- Document QA 60
- Judgment Explanation 32
- Change Comparison 8
- 총 100문항

## 결과

| 묶음 | 정확 intent 일치 |
| --- | ---: |
| Document QA | 1/60 |
| Judgment Explanation | 0/32 |
| Change Comparison | 0/8 |
| **전체** | **1/100 = 1.0%** |

현재 UI/API 계약을 정적으로 끝까지 따라갔을 때 요청한 전체 작업 계약까지 도달 가능한 경로는 **0/100**이었습니다.

이 결과는 의도적으로 낮은 출발점을 숨기지 않고 기록한 **실제 개선 기준선**입니다.

주요 실패:

- 자연스러운 공고 질문이 `UNKNOWN`
- `참가할 수 있는지`보다 뒤쪽 `확인` 단어를 먼저 잡아 판정 설명을 Required Checks로 보냄
- `무엇이 바뀌었는지` 같은 자연 표현을 변경 비교로 인식하지 못함

참고: [`ai-copilot-v2/e0-routing-baseline.md`](./ai-copilot-v2/e0-routing-baseline.md)

---

# 6. E1 — 규칙으로 확실히 고칠 수 있는 UX 먼저 개선

E1에서는 처음부터 모든 입력을 LLM에 보내지 않았습니다.

고신뢰 표현과 실패 UX를 deterministic하게 먼저 보완했습니다.

## 동일 100문항 재측정

| 묶음 | E0 | E1 |
| --- | ---: | ---: |
| Document QA | 1/60 | 1/60 |
| Judgment Explanation | 0/32 | 32/32 |
| Change Comparison | 0/8 | 8/8 |
| **전체** | **1/100** | **41/100** |

대화·안전 I01~I20:

- 완전 성공: **5/20 → 9/20**
- 부분 성공: **5/20 → 3/20**
- 실패: **10/20 → 8/20**
- 코드 경로에서 확인한 치명적 안전 위반 후보: **0 유지**

E1에서 해결하지 못한 항목도 그대로 기록했습니다.

- 회사 허가 vs 제품 허가처럼 subject 구분이 필요한 질문
- 상충 조항/계약 수치/평가항목처럼 문서 의미를 읽어야 하는 질문
- 자연어 진술을 안전한 업무 초안으로 구조화하는 문제
- 일정과 참가자격처럼 여러 정보 축을 함께 이해하는 문제

따라서 alias를 더 늘리는 대신 E2의 의미 기반 routing 문제로 분리했습니다.

참고: [`ai-copilot-v2/e1-evaluation-summary.md`](./ai-copilot-v2/e1-evaluation-summary.md)

---

# 7. E2 — Semantic Routing

## Semantic Router 단독

| Run | 전체 | Document QA | Judgment | Change | latency p50 | p95 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Run 1 | 89/100 | 56/60 | 25/32 | 8/8 | 2.33s | 3.99s |
| Run 2 | 98/100 | 60/60 | 32/32 | 6/8 | 2.04s | 3.03s |
| Run 3 | **100/100** | **60/60** | **32/32** | **8/8** | **1.98s** | **2.83s** |

그러나 실제 제품에서는 deterministic router가 Semantic Router보다 앞에 있어 false positive 10건이 Semantic까지 도달하지 못하는 문제가 발견됐습니다.

대표 예:

- `중소기업 확인서`의 `확인` substring → Required Checks 오분류
- `예외가 어떻게 적용되는지 설명`의 `적용` → Action Request 오분류
- `변경 때문에 판정이 달라지는지 확인` → Change보다 Required Checks 우선

## 정책 수정

모든 deterministic 결과를 모델이 덮어쓰게 하지 않았습니다.

```text
explicit UI intent / write payload / 명확한 실행문
→ deterministic 유지

UNKNOWN 또는 weak deterministic read
→ Semantic 재검토

Semantic 실패/낮은 confidence
→ deterministic fallback
```

최종 Combined v2 frozen routing은 **100/100**이었습니다.

### 해석 주의

이 100/100 역시:

- 답변 정답률이 아니고
- RAG 품질이 아니며
- 사용자 과업 완료율이 아닙니다.

**고정 100문항 intent routing 평가**입니다.

참고: [`ai-copilot-v2/e2-routing-evaluation.md`](./ai-copilot-v2/e2-routing-evaluation.md)

---

# 8. E3 — Document RAG Retrieval 비교

동일 평가 fixture에서 `k=4`, `fetch_k=12` 조건으로 Retriever를 비교했습니다.

## 결과

| 방식 | Evidence Recall@4 | Case Any-hit@4 | Case All-hit@4 | p50 latency |
| --- | ---: | ---: | ---: | ---: |
| Dense | **29.17%** | 32.20% | 27.12% | 144.50ms |
| Hybrid | **50.00%** | 52.54% | 49.15% | 170.58ms |
| Hybrid + LLM Rerank | **55.56%** | 57.63% | 57.63% | 2849.73ms |

Dense 대비 Hybrid:

- Recall: **+20.83%p**
- All-hit: **+22.03%p**
- p50 증가: 약 **26ms**

Hybrid + Rerank는 Hybrid보다 Recall이 **+5.56%p** 좋아졌지만 p50이 약 **171ms → 2.85s**로 증가하고 질문마다 추가 모델 호출이 필요했습니다.

## 제품 결정

**기본 Retrieval은 Hybrid를 선택했습니다.**

최고 자동 점수만 기준으로 기술을 선택하지 않고 정확도, latency, 비용, 운영 복잡도를 함께 봤습니다. Rerank는 hard query/selective rerank 후보로 남겼습니다.

참고: [`ai-copilot-v2/e3-rag-evaluation.md`](./ai-copilot-v2/e3-rag-evaluation.md)

---

# 9. E3 — Grounded Answer / Prompt v1→v4

## 최종 v4 구조 지표

- evaluable cases: **59** / scope gap 1
- generation success: **59/59**
- generation failure: **0**
- citation present: **57/59**
- citation notice-version integrity: **59/59 = 100%**
- strict expected evidence cited: **33/72 = 45.83%**
- total latency p50: **2925.77ms**
- total latency p95: **5449.73ms**

`45.83%`는 답변 정답률이 아니라 frozen expected excerpt와 실제 citation source의 strict matcher입니다.

## Prompt 개선 과정

### v1 — Citation 존재 자체를 품질로 착각

관련 근거가 Top-4에 없어도 다른 Source를 Citation하는 사례가 있었습니다.

### v2 — No Support → Abstain

질문의 핵심 주장을 직접 뒷받침하는 Source만 인용하고, 근거가 없으면 `확인할 수 없음` + zero citation으로 처리했습니다.

### v3 — Partial Evidence

부분 근거 하나로 전체 조건을 먼저 확정하지 않고 확인 가능한 항목과 확인 불가능한 항목을 분리했습니다.

### v4 — Source 자체의 오류를 모델이 고치지 않음

문서에 불완전한 코드/숫자가 있을 때 모델이 빠진 자릿수를 추정해 복원하지 않고 Source 표기를 그대로 설명하도록 했습니다.

## 제품 안전 경계

생성 답변에 검증 가능한 citation이 하나도 없으면 생성문을 그대로 노출하지 않고 deterministic abstention으로 fail-closed합니다.

---

# 10. v3.1 — 생성 답변을 Claim 단위로 검증

v3.1 감사에서는 기존 자동테스트가 통과하더라도 다음 경계가 부족할 수 있음을 다시 확인했습니다.

- 입력 불가 항목 집계 문제
- 수동 확인 항목의 source 연결 소실
- 저장 판정과 반대인 산문이 검증기를 통과할 가능성
- index readiness/fingerprint 부족

이를 바탕으로 다음 구조를 추가했습니다.

```text
현재 Scope 재확인
→ TaskPlan
→ Product Read Tools
→ EvidenceBundle(Fact / Source)
→ 답변 Draft
→ Claim ↔ Fact ↔ Source 검사
→ 의미 검증
→ 실패 Claim 한 번 수정·재검증
→ 검증된 Claim만 게시
→ 실패 범위는 PARTIAL / limitation
```

## 구현 재검증

기존 보고서에서 기록한 주요 결과:

- Python 회귀 9파일: **330 passed / 0 failed / 0 skipped**
- 고정 synthetic 4-turn replay: **PASS**
- 실제 ASGI v3.1 4-turn: **PASS** — 인증/도구/모델은 격리 대체
- 실제 모델 semantic classifier: **7/7 expected**
- Frontend TypeScript / oxlint / production build: **PASS**
- headless Chrome UI: **PASS** — mock API

실제 모델 4-turn 결과:

| Turn | 결과 | elapsed |
| --- | --- | ---: |
| 1 | PARTIAL | 41.968s |
| 2 | PASS | 8.156s |
| 3 | PASS | 7.281s |
| 4 | PARTIAL | 35.875s |

기대 Fact는 포함됐지만 복합 답변의 coverage와 복구 지연 때문에 모든 Turn을 PASS로 만들지 않았습니다.

### 해석

v3.1의 개선은 `모델이 더 똑똑해졌다`가 아니라 **지원되지 않는 문장을 게시하지 않는 검증 경계를 강화했다**는 데 의미가 있습니다.

동시에 복합 답변 latency가 커졌다는 trade-off도 남았습니다.

참고:

- [`../07_handoff/ai-copilot-v3.1/01-current-state-audit.md`](../07_handoff/ai-copilot-v3.1/01-current-state-audit.md)
- [`../07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md`](../07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md)

---

# 11. Guided Job 실제 모델 평가 — 남원 Demo 묶음

현재 Product는 변경공고 대응과 입찰 참여 준비라는 두 업무 Job의 6개 검증 질문을 제공합니다.

PR #151에 앞선 격리 통합 평가에서는 남원 Demo 합성 프로필 J13~J16에 대해 각 6문항, 총 24턴을 실행했습니다.

## 결과

- 총 **23/24 COMPLETE**
- J14: 6/6
- J15: 6/6
- J16: 6/6
- J13: 5/6
- J13 `준비 순서는?` 1건은 잘못된 Fact 참조의 추천 순서 Claim이 제거되어 **PARTIAL**
- HTTP / case-source scope / 내부 식별자 노출 / 예상하지 않은 write action 오류: **0건**
- 답변 최대 길이: **945자**
- 평균 응답시간: **26.92초**
- 최대 응답시간: **54.13초**

### 해석 주의

이 평가는 사람 사용자 24회가 아니라 **합성 프로필에 대한 실제 모델 격리 실행**입니다.

또한 해당 보고서는 PR #151 최종 병합 전 통합 작업의 실행 증거입니다. Current `develop`은 이후 **추천 질문 6개 + 자유 입력**을 함께 제공하도록 병합되었습니다.

따라서 23/24를 현재 모든 자유입력에 대한 정확도로 확장하지 않습니다.

참고: [`../07_handoff/ai-copilot-v3.1/52-two-job-integration-result.md`](../07_handoff/ai-copilot-v3.1/52-two-job-integration-result.md)

---

# 12. Human User Test — 아직 닫히지 않은 평가

Stage 11에는 실제 사용자를 위한 평가 설계가 존재합니다.

Core Test:

1. 참가 가능 여부 찾기
2. 답변 → 원문 근거 추적
3. 자연어 공고 질문
4. 변경공고 영향 확인
5. 확인 필요 요건에 정보 반영
6. 외부 AI 처리 경계 이해

Safety Challenge:

- 근거가 없을 때 abstention 이해
- 저장/확인 경계와 과신 여부

기록 항목:

- PASS / PARTIAL / FAIL
- CRITICAL safety
- 완료시간
- 힌트 수
- 잘못된 경로
- 사용자가 이해한 결론
- 신뢰도

## Current 상태

**평가 계획은 있으나 최종 사람 사용자 결과를 완료한 것으로 문서화할 근거는 아직 없습니다.**

따라서 본 문서에서는 사용자 완료율이나 사람 이해도 점수를 만들지 않습니다.

참고: [`ai-copilot-v2/stage11-user-test-plan.md`](./ai-copilot-v2/stage11-user-test-plan.md)

---

# 13. 지표를 어떻게 해석할 것인가

| 지표 | 무엇을 보는가 | 무엇을 의미하지 않는가 |
| --- | --- | --- |
| Routing exact match | 질문이 올바른 Task로 가는가 | 답변 사실 정확도 |
| Task reachability | 목표 기능까지 경로가 존재하는가 | 실제 사용자 성공률 |
| Recall@4 | 필요한 근거가 Top-4에 들어오는가 | 생성 답변 정답률 |
| Citation integrity | 인용이 같은 공고 Version에 연결되는가 | 인용의 법률적 해석 정확성 |
| Expected Evidence Citation Recall | frozen 발췌와 citation이 strict match하는가 | semantic answer correctness |
| Generation success | 모델 호출이 구조적으로 성공했는가 | 답변이 맞다는 뜻 |
| Claim validation | 게시 Claim이 확인된 Fact/Source와 일치하는가 | 모델의 무오류 보증 |
| COMPLETE/PARTIAL | 정의된 업무 범위를 얼마나 채웠는가 | 사람 사용성 |
| Human Task Completion | 사용자가 스스로 업무를 끝내는가 | 독립 법률 적격성 |

## 발표에서 피할 표현

- `챗봇 정확도 100%`
- `RAG 정확도 50%`
- `AI가 참가 가능 여부를 판정한다`
- `24개 중 23개 사용자 성공`

## 권장 표현

- `고정 100문항 routing exact match 100/100`
- `동일 evidence fixture에서 Hybrid Recall@4 50.00%`
- `판정은 deterministic Product Rule, Copilot은 조회·설명·근거 연결`
- `남원 합성 프로필 실제 모델 Guided Job 24턴 중 23 COMPLETE`

---

# 14. 기술 선택에 반영된 평가

## Hybrid 채택 / Rerank 미채택

Rerank가 더 높은 Recall을 보였지만 추가 LLM latency와 비용을 고려해 기본 경로는 Hybrid를 선택했습니다.

## Semantic 전면 적용 대신 Weak-read Recheck

모든 deterministic 결과를 LLM에 맡기지 않고 명확한 UI intent와 write 경계는 deterministic하게 유지했습니다.

## 자연어 동의보다 Explicit Confirm

편의성보다 write safety를 우선해 `응` 같은 자연어만으로 저장·재검증을 실행하지 않습니다.

## Full Retry보다 Safe Partial

복합 답변이 일부 검증에 실패했을 때 전체를 무한 재생성하지 않고 검증된 sibling claim을 유지하며 실패 범위만 제외합니다.

이 선택들은 단순 구현 취향이 아니라 각 단계의 실패와 지연을 측정한 결과입니다.

---

# 15. 현재 평가 관점의 강점

- 낮은 E0 기준선부터 숨기지 않고 동일 질문으로 전후 비교함
- Routing / Retrieval / Generation / Citation / Safety를 분리함
- `100/100` 수치의 범위를 문서마다 명시함
- Retriever를 같은 fixture에서 비교함
- 더 높은 Recall의 Reranker를 latency 때문에 제품 기본에서 제외함
- Prompt 실패 사례를 v1→v4로 보존함
- 자동테스트 PASS와 실제 모델/실사용을 구분함
- v3.1에서 Claim을 서버 Fact/Source에 연결하는 구조적 검증을 추가함
- 발표 Demo와 가까운 남원 합성 프로필 Guided Job 실행 결과가 있음

# 16. 현재 평가 관점의 한계

가장 큰 미완료는 다음입니다.

1. **독립적인 새 blind 질문셋**  
   기존 고정셋은 개선 과정에 노출됐으므로 일반화 성능으로 주장하지 않습니다.

2. **실제 사람 사용자 테스트 결과**  
   계획은 존재하지만 완료율·이해도·신뢰도 결과를 아직 확정하지 않습니다.

3. **실제 운영 데이터 전체 E2E**  
   격리 API/브라우저/합성 fixture 결과를 실제 배포 E2E와 합치지 않습니다.

4. **Latency**  
   v3.1 및 Guided Job 실제 모델 경로는 복합 질문에서 수십 초까지 걸릴 수 있습니다.

5. **AI Core와 Copilot 평가 분리**  
   Requirement Extraction 품질과 Copilot Document QA 품질은 서로 다른 문제입니다.

# 17. 최종 결론

AI Copilot의 개선 과정은 단순히 `LLM을 붙였다`가 아니라 다음과 같은 측정·개선 루프로 설명할 수 있습니다.

```text
자유입력 문제 측정(E0)
→ deterministic UX 개선(E1)
→ 의미 routing(E2)
→ 근거 검색 비교(E3)
→ Prompt grounding 개선
→ Fact/Source/Claim 검증(v3.1)
→ 실제 업무 Guided Job 평가
```

현재 가장 중요한 후속 평가는 자동 점수를 더 올리는 것이 아니라 **새 독립 질문셋과 실제 사용자 업무 완료 평가를 닫는 것**입니다.

## 관련 문서

- [AI Copilot Current Architecture](../03_ai/ai-copilot.md)
- [AI Copilot v2 원본 평가 인덱스](./ai-copilot-v2/README.md)
- [AI Copilot v1 평가](./ai-copilot-v1-evaluation.md)
- [E2 Routing](./ai-copilot-v2/e2-routing-evaluation.md)
- [E3 RAG](./ai-copilot-v2/e3-rag-evaluation.md)
- [v3.1 구현·검증](../07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md)
- [Guided Job 통합 평가](../07_handoff/ai-copilot-v3.1/52-two-job-integration-result.md)
