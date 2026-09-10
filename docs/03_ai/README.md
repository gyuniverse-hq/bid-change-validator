# AI / RAG 문서 안내

> **문서 상태: Current + Proposed 혼재**  
> 기준 브랜치: `develop`

이 폴더는 Product Integration Baseline 이후 AI 영역을 **Core Intelligence**와 **AI Copilot**으로 나누고, 병렬 개발 시 파일 소유권과 Contract 경계를 관리합니다.

## 현재 AI 구조

```text
나라장터 / 첨부문서
        ↓
Parsing / extracted_blocks
        ↓
app.ai
├─ Chunking
├─ Requirement Extraction
├─ Canonical Mapping
├─ Evidence
├─ Askability Guardrail
├─ deterministic Judgment
└─ Requirement Diff / Revalidation 기반
        ↓
Backend Product API / DB
        ↓
app.copilot (신규 예정)
├─ Intent
├─ Product Context
├─ Tool Adapter
├─ Grounding Guardrail
└─ Narration
        ↓
사용자 대화 UI
```

## 책임 경계

### 김재현 — LLM/RAG Core · Evaluation

Core가 책임지는 질문은 다음입니다.

> 공고문에서 자격요건과 근거를 얼마나 정확하고 안전하게 구조화할 수 있는가?

주요 영역:

- Semantic Chunking / Retrieval
- Requirement Extraction
- Canonical Mapping
- Evidence Grounding
- UNKNOWN / Askability Guardrail
- Retrieval·Extraction Golden Set / Evaluation
- 필요 시 변경공고 분석 Core 고도화

### 이홍규 — AI Copilot · Integration

Copilot이 책임지는 질문은 다음입니다.

> 이미 계산된 Product/Core 결과를 사용자가 자연어로 어떻게 안전하게 탐색하고 이어서 업무할 수 있는가?

주요 영역:

- Intent Classification
- Conversation / Product Context
- Tool Orchestration
- Qualification / Evidence / Ask-back / Change API Adapter
- Grounded Response / Citation
- Multi-turn Flow
- Copilot Evaluation / Integration E2E

## 절대 원칙

1. **판정은 LLM/Copilot이 새로 만들지 않습니다.**
   - 개별 상태: `SATISFIED | UNSATISFIED | UNKNOWN`
   - 전체 상태: `eligible | ineligible | insufficient_data`
   - 전체 상태의 Source of Truth는 Backend Judgment Run입니다.

2. **근거가 없는 확정 답변을 만들지 않습니다.**
   - `PARTIAL`, `FAILED`, `UNKNOWN`은 확정 결과로 승격하지 않습니다.

3. **Copilot → Core 의존만 허용합니다.**
   - Core는 Copilot을 알지 않습니다.
   - Copilot은 Core 내부 Retriever나 Extraction 함수를 직접 조립하지 않고 안정된 Contract 또는 Product API를 사용합니다.

4. **기존 Core 파일을 대규모 재배치하지 않습니다.**
   - 현재 Backend와 테스트의 import 경로를 보존합니다.
   - 신규 Retrieval/Evaluation 영역과 `app/copilot/**`부터 분리합니다.

## 문서

- [AI Core ↔ Copilot 병렬 개발 기준](parallel-boundary.md)
- [Core → Copilot Contract](core-copilot-contract.md)

향후 추가 후보:

- `llm-rag-core.md`
- `ai-copilot.md`
- `retrieval.md`
- `evaluation.md`

## 현재 `develop` Core 주요 파일

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
├─ legacy_slots.py
├─ normalization/
├─ providers/
├─ requirement_diff.py
└─ requirement_extraction.py
```

## 기존 `LLM` 브랜치 처리 원칙

`LLM` 브랜치는 최신 `develop` 대비 크게 뒤처져 있으므로 통째로 Merge하지 않습니다.

- 이미 `develop`에 존재: 최신 `develop` 유지
- Core 가치가 남은 모듈: 함수/테스트 단위 선별 이식
- 대화·설명 PoC: `app/copilot/**` 설계 참고
- DB 연결 전 Demo 전용 코드: 제품 Merge보다 Historical/Test 자료로 활용

우선 검토 후보는 `clause_review/`, embedding provider이며, `assist.py`, `summary.py`는 Copilot 요구사항 참고 자료로 봅니다.

## 다음 개발 순서

1. Core ↔ Copilot Contract 확정
2. 재현 현재 작업물과 최신 `develop` Diff 최종 검산
3. 최신 `develop`에서 각 담당 Branch 생성
4. Core / Copilot 독립 테스트
5. `질문 → Product Tool → Judgment/Evidence → Grounded Answer` 첫 E2E
6. Ask-back → Revalidation → Change 질의 순으로 확장
