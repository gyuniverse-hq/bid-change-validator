# AI Core ↔ Copilot 병렬 개발 기준

> **문서 상태: Proposed**  
> 작성: 2026-09-10 · 기준: 최신 `develop`

## 목적

LLM/RAG 두 명이 같은 파일을 동시에 수정하는 구조를 피하고, 김재현의 Core Intelligence와 이홍규의 AI Copilot을 독립적으로 개발·테스트한 뒤 안정된 Contract에서 통합합니다.

## 원칙

- 김재현 Core: 공고문을 신뢰 가능한 Requirement / Evidence / Judgment 기반으로 변환
- 이홍규 Copilot: 자연어 질문을 기존 Product/API/Core 기능에 연결하고 결과를 근거 기반으로 설명
- Copilot은 참가 가능 여부를 새로 판정하지 않음
- 의존 방향은 `Copilot → Core / Business API` 단방향
- 공유 수정 영역은 Contract와 통합 지점으로 최소화

## 현재 Core

현재 `develop`의 주요 AI 파일:

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

기존 Core 파일은 대규모로 이동하지 않습니다. Backend import와 회귀 테스트를 유지하면서 신규 기능부터 경계를 명확히 합니다.

## 목표 폴더

```text
apps/api/app/
├─ ai/                              # 김재현 중심 · Core
│  ├─ 기존 Core 파일 유지
│  ├─ retrieval/                    # 필요 시 신규
│  │  ├─ keyword.py
│  │  ├─ embedding.py
│  │  ├─ hybrid.py
│  │  └─ reranker.py
│  ├─ evaluation/                   # 필요 시 신규
│  │  ├─ evaluator.py
│  │  ├─ metrics.py
│  │  └─ golden_loader.py
│  └─ providers/
│
├─ copilot/                         # 이홍규 중심 · 신규
│  ├─ __init__.py
│  ├─ contracts.py
│  ├─ service.py
│  ├─ intent.py
│  ├─ context.py
│  ├─ guardrail.py
│  ├─ narrator.py
│  ├─ tools/
│  │  ├─ qualification.py
│  │  ├─ evidence.py
│  │  ├─ notice.py
│  │  ├─ askback.py
│  │  ├─ changes.py
│  │  └─ evaluation.py
│  └─ prompts/
│
└─ 기존 qualification_* / routers / services
```

## Owner

| 영역 | Primary | 규칙 |
| --- | --- | --- |
| `app/ai/**` | 김재현 | Core 품질·Retrieval·Extraction·Evidence·Guardrail·Eval |
| `app/copilot/**` | 이홍규 | Intent·Context·Tool Orchestration·Grounded Answer |
| `app/ai/contracts.py` | 공동 | Breaking 변경 금지, 필요 시 사전 합의 |
| Backend qualification API | 전진환 중심 | Copilot에서 재구현하지 않고 기존 Service/API 재사용 |
| Router / OpenAPI | 통합 Review | API 노출이 필요한 시점에 최소 변경 |

## 테스트 경계

```text
apps/api/tests/
├─ 기존 test_ai_* / ai/             # Core
├─ copilot/                          # Copilot
└─ integration/                      # Core + Copilot E2E
```

- Core 테스트는 Copilot이 없어도 통과해야 합니다.
- Copilot 테스트는 Core 내부 함수가 아니라 공개 Contract / Product Tool 결과에 의존합니다.
- 첫 Integration E2E는 `질문 → Judgment/Evidence 조회 → Grounded Answer`입니다.

## 기존 `LLM` 브랜치 처리

현재 `LLM`은 `develop` 대비 diverged 상태이며 크게 뒤처져 있으므로 새 작업 Base로 사용하지 않습니다.

1. 동일/기반 코드가 이미 `develop`에 있으면 현재 버전 유지
2. `clause_review/`, embedding provider 등은 Core 고도화 후보로 선별 검토
3. `assist.py`, `summary.py`는 Copilot 요구사항 참고 자료로 검토
4. `followup.py`, 과거 profile/judgment PoC는 현재 Product Ask-back/DB Service가 우선
5. `app/demo/**`, Demo data/CLI는 직접 제품 Merge보다 Test/Historical 자료로 사용

## Branch

```text
develop
├─ feature/llm-core-hardening
└─ feature/ai-copilot
```

두 기능 Branch는 최신 `develop`에서 출발합니다. 통합 브랜치가 필요할 경우 두 작업을 검증하기 위한 임시 Integration 용도로만 둡니다.

## 확정 전 체크

- [ ] 김재현 현재 작업물이 원격 `LLM` 최신 상태와 같은지 확인
- [ ] Core 이식 후보 범위 합의
- [ ] Core → Copilot Contract 필수 필드 합의
- [ ] `app/copilot/**` 첫 Vertical Slice 작성
- [ ] 각 Branch 독립 테스트
- [ ] Integration E2E 통과 후 이 문서를 `Current`로 승격
