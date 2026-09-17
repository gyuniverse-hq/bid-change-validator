# AI / RAG 문서 안내

> **문서 상태: Current + Historical/Proposed 참조 혼재**  
> 기준 브랜치: `develop` · Current Copilot 기준: 2026-09-17 / PR #151 이후

이 폴더는 Product Integration Baseline 이후 AI 영역을 **Core Intelligence**와 **AI Copilot**으로 나누고, 서로 다른 책임과 평가 범위를 관리합니다.

## 먼저 볼 문서

- [AI Copilot · Current Architecture](ai-copilot.md) — **Current**
- [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md) — **Current Summary + Historical Evidence**
- [AI Retrieval · Current State / Upgrade Path](retrieval-current-state.md) — **AI Core Current Baseline + Proposed Experiments**
- [Core → Copilot Contract](core-copilot-contract.md) — **초기 Proposed Contract / Historical Design Input**
- [AI Core ↔ Copilot 병렬 개발 기준](parallel-boundary.md) — **Ownership/병렬 개발 기준**

## 역할 상태

역할 분리는 합의 완료 상태입니다.

- **김재현 = LLM/RAG Core + Evaluation**
- **이홍규 = AI Copilot + Integration**

초기 문서에서는 `app/copilot/**`을 Proposed로 다뤘지만, 현재 `develop`에는 Copilot API·Conversation·Guided Job·Claim Validation·Frontend Panel이 구현되어 있습니다. Current 구조는 `ai-copilot.md`를 우선합니다.

## 현재 AI 구조

```text
나라장터 / 첨부문서
        ↓
Backend Parsing / extracted_blocks
        ↓
app.ai — Core Intelligence
├─ Semantic Chunking
├─ Eligibility section / keyword candidate selection
├─ Requirement Extraction
├─ Source-grounding validation
├─ Canonical Mapping / Normalization
├─ Evidence
├─ Askability Guardrail
├─ Contract Risk Clause classification
├─ deterministic Judgment
└─ Requirement Diff / Revalidation 기반
        ↓
Backend Product Service / DB
        ↓
app.copilot — Current Product Integration Layer
├─ Conversation / Scope
├─ Guided Job 2종 / 질문 6개
├─ Free-text Planning
├─ Product Tool Adapter
├─ Document QA / Hybrid Retrieval
├─ Fact / Source / Claim Validation
├─ Action Proposal / Explicit Confirm
└─ AnswerEnvelope v3.1
        ↓
Frontend Copilot Panel
```

## AI Core Retrieval과 Copilot RAG는 다릅니다

### AI Core Qualification Extraction

현재 Qualification Core의 기본 후보 선택은 **명시적인 Vector DB / Dense / Hybrid Production Retriever가 아닙니다.**

```text
Semantic Chunks
→ 참가자격 section anchor
→ keyword fallback
→ candidate context
→ LLM structured extraction
→ source-grounding validation
```

상세: [AI Retrieval · Current State / Upgrade Path](retrieval-current-state.md)

### AI Copilot Document QA

Copilot의 공개 공고문 질문은 별도 Document QA 경로에서 **Hybrid Retrieval(Dense + BM25/RRF)** 을 사용합니다. 이 경로는 회사 적격 판정과 분리되어 있고, 참가 가능 여부는 Product Judgment가 계속 Source of Truth입니다.

상세: [AI Copilot · Current Architecture](ai-copilot.md)

## 책임 경계

### 김재현 — LLM/RAG Core · Evaluation

> 공고문에서 자격요건·계약 위험조항과 근거를 얼마나 정확하고 안전하게 구조화할 수 있는가?

주요 영역:

- Semantic Chunking / Core Retrieval baseline·고도화
- Requirement Extraction
- Canonical Mapping
- Evidence Grounding
- UNKNOWN / Askability Guardrail
- 계약 위험조항 9종 분류와 Evidence
- Retrieval·Extraction Golden Set / Evaluation
- 변경공고 분석 Core / Revalidation 고도화

### 이홍규 — AI Copilot · Integration

> 이미 계산된 Product/Core 결과와 현재 공고문 근거를 사용자가 자연어로 어떻게 안전하게 탐색하고 이어서 업무할 수 있는가?

Current 주요 영역:

- Intent / Semantic Routing
- Conversation / Product Scope
- Guided Job / Tool Orchestration
- Qualification / Evidence / Ask-back / Change Adapter
- Document QA / Citation
- Fact / Source / Claim Validation
- Multi-turn Target Resolution
- Action Proposal / Explicit Confirm
- Copilot Evaluation / Integration

## 계약 위험조항 · MVP Current

위험조항은 MVP에 포함하며 현재 taxonomy는 9종입니다.

`WARRANTY_PERIOD`, `LATE_PENALTY`, `LATE_PENALTY_RATE`, `COPYRIGHT_OWNERSHIP`, `ACCEPTANCE_CRITERIA`, `SCOPE_AMBIGUITY`, `TERMINATION_CONDITION`, `PAYMENT_TERMS`, `LIABILITY_SCOPE`

경계:

```text
AI Core
→ contract risk category 분류 + 근거
→ Backend는 category를 재분류하지 않고 저장
→ Frontend가 사용자용 Label로 표현
```

## 절대 원칙

1. **판정은 LLM/Copilot이 새로 만들지 않습니다.**
   - 개별 상태: `SATISFIED | UNSATISFIED | UNKNOWN`
   - 전체 상태: `eligible | ineligible | insufficient_data`
   - 전체 상태의 Source of Truth는 Backend Judgment Run입니다.

2. **근거가 없는 확정 답변을 만들지 않습니다.**
   - Product Evidence 또는 현재 공고문 Source로 확인되지 않은 사실을 확정적으로 게시하지 않습니다.
   - 검증 실패 범위는 PARTIAL/limitation 또는 abstention으로 남깁니다.

3. **`UNKNOWN != ASKABLE`입니다.**
   - 질문 가능 여부는 `askability.py` 정책으로 별도 판정합니다.

4. **Copilot은 기존 Product/Core 결과를 소비합니다.**
   - Copilot이 별도 Qualification Rule을 만들어 이중 판정 구조를 만들지 않습니다.
   - Document QA는 공개 문서 설명용이며 회사 적격 판정 경로를 대체하지 않습니다.

5. **write는 대화와 분리합니다.**
   - `/chat`은 조회·설명·Proposal까지만 수행합니다.
   - 실제 저장/재검증은 명시적 confirm과 최신 provenance 검증 후 기존 Product Service를 사용합니다.

## 현재 주요 코드

### AI Core

```text
apps/api/app/ai/
├─ analysis_pipeline.py
├─ analysis_result.py
├─ askability.py
├─ backend_blocks.py
├─ canonicalize.py
├─ chunking.py
├─ contracts.py
├─ evaluation_contracts.py
├─ evidence_adapter.py
├─ judgment.py
├─ normalization/
├─ requirement_diff.py
└─ requirement_extraction.py
```

### AI Copilot

```text
apps/api/app/copilot/
├─ router.py
├─ job_catalog.py
├─ orchestration.py
├─ v31_contracts.py
├─ tool_adapters.py
├─ answer_validation.py
├─ conversation_state.py
├─ document_qa.py
├─ semantic_router.py
├─ narration.py
├─ actions.py
└─ change_impact.py
```

`evaluation_contracts.py`는 **입찰 평가기준(Evaluation Criterion)의 source-grounded 구조 계약**이며, AI 품질평가 Harness 자체를 의미하지 않습니다.

## 설계 역사 문서 읽는 법

과거 문서에는 당시 구현 상태가 그대로 남아 있습니다.

- `core-copilot-contract.md`: 2026-09-10 초기 Contract 제안
- `../llm-rag/08-chatbot-design-notes.md`: 초기 `판정은 코드, 서술은 모델` 설계
- `../08_qa_reports/ai-copilot-stage6-2-to10.md`: Product Tool / Proposal-Confirm 발전 과정
- `../08_qa_reports/ai-copilot-v2/`: E0→E3 개선·평가 원본
- `../07_handoff/ai-copilot-v3.1/`: 감사 → 설계 결정 → Claim Validation → Guided Job 통합 과정

이 문서들은 당시 사실을 보존하는 Historical Evidence이며, **현재 구현 설명에는 `ai-copilot.md`를 우선합니다.**

## 현재 후속 과제

- 사람 사용자 Test Case 실제 수행 및 결과 기록
- 새 독립 blind 질문셋으로 일반화 평가
- v3.1 / Guided Job 실제 모델 latency 개선
- process-memory Conversation의 durable storage 필요성 검토
- AI Core Requirement Extraction과 Copilot Document QA를 분리한 최종 발표 지표 유지
