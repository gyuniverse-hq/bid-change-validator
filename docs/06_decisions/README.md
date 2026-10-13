# Decision / ADR 문서 안내

> **상태: Current Guide**

Notion Decision Log는 논의와 팀 결정의 원본 맥락을 보존합니다. 그중 실제 코드·아키텍처에 장기간 영향을 주는 결정은 안정화 후 이 폴더에 ADR(Architecture Decision Record)로 승격합니다.

## Notion과 ADR의 차이

```text
Notion Decision Log
= 무엇을 논의했고 왜 선택했는가

GitHub ADR
= 현재 코드가 어떤 결정을 전제로 구성되어 있는가
```

모든 회의 결정을 ADR로 만들지 않습니다.

## ADR 대상

- Rule과 LLM의 책임 경계
- 핵심 데이터/Version 모델 변경
- API 또는 Contract의 Breaking Decision
- Retrieval / Vector DB / Model 전략 확정
- AI Core / Copilot 모듈 경계 확정
- 인증 / 배포 Architecture 확정
- 중요한 기술을 도입하거나 포기한 결정

## 파일명

```text
ADR-001-short-title.md
ADR-002-short-title.md
```

## 템플릿

```markdown
# ADR-XXX 제목

> 상태: Proposed | Accepted | Superseded
> 날짜: YYYY-MM-DD

## Context
왜 이 결정이 필요한가?

## Options
검토한 선택지는 무엇인가?

## Decision
무엇을 선택했는가?

## Consequences
좋아지는 점, 비용, 제약은 무엇인가?

## Revisit Condition
언제 다시 검토할 것인가?
```

## 현재 주요 결정 / 상태

### Qualification 판정은 deterministic Product Rule이 소유

**Accepted / Current**

- LLM/Copilot이 회사 참가 가능/불가를 새로 계산하지 않습니다.
- 전체 상태는 저장된 Judgment Run의 `overall_status`가 Source of Truth입니다.
- Copilot Document QA 역시 회사 적격 판정을 대신하지 않습니다.

### AI Core와 AI Copilot 역할 분리

**Accepted / Current**

- 김재현: LLM/RAG Core + Evaluation
- 이홍규: AI Copilot + Integration
- Core는 Requirement/Evidence/Rule에 집중하고 Copilot은 Product/Core 결과를 대화로 조회·설명합니다.
- Copilot이 Core 내부 Retriever/Rule을 다시 구현해 이중 판정 구조를 만들지 않습니다.

### Copilot write는 Proposal → Explicit Confirm으로 분리

**Accepted / Current**

- `/chat`이 실제 저장/재검증을 직접 실행하지 않습니다.
- 자연어 `응`을 실행 확인으로 사용하지 않습니다.
- `/actions/confirm`에서 현재 provenance를 다시 확인한 뒤 기존 Product Service를 호출합니다.

### 자유입력 Routing은 deterministic + selective Semantic recheck

**Accepted / Current**

- 모든 질문을 모델 Router에 맡기지 않습니다.
- 명확한 UI intent/write 경계는 deterministic하게 유지합니다.
- UNKNOWN 또는 weak deterministic read만 Semantic Router가 재검토합니다.
- E0→E2 측정 과정과 결과는 `../08_qa_reports/ai-copilot-final-evaluation.md`를 참고합니다.

### Copilot Document QA 기본 Retriever는 Hybrid

**Accepted / Current**

- 동일 fixture에서 Dense, Hybrid, Hybrid + LLM Rerank를 비교했습니다.
- Rerank가 Recall은 더 높았지만 추가 모델 호출과 큰 latency 증가 때문에 기본 제품 경로에는 채택하지 않았습니다.
- 현재 기본은 Dense + BM25 Hybrid/RRF입니다.
- 이 결정은 AI Core Requirement Extraction Retrieval과 별개입니다.

### 생성 답변은 Fact / Source / Claim 분리 후 검증

**Accepted / Current v3.1**

- 서버 Fact/Source와 모델 Claim을 분리합니다.
- unsupported/contradicted claim을 전체 성공으로 게시하지 않습니다.
- 실패한 claim은 제한된 수정·재검증 후에도 불확실하면 제외하고 PARTIAL/limitation을 유지합니다.

### Guided Job 2종 / 질문 6개 + 자유입력 통합

**Accepted / Current**

- 변경 공고 대응 3문항
- 입찰 참여 준비 3문항
- 서버가 질문의 Tool 범위와 완료 기준을 소유합니다.
- PR #151 이후 Current UI는 Guided Question과 자유 입력을 함께 제공합니다.

### 위험조항 9종 taxonomy 및 `AI Core 분류 → Backend 저장`

**Accepted contract candidate / Current 구현과 함께 검증 필요**

위험조항 분류 책임을 Backend에 중복 구현하지 않는 경계를 유지합니다.

## 아직 미정 / 재검토 대상

- Copilot Conversation durable persistence / multi-worker 저장 구조 — **TBD**
- Selective rerank / hard-query 정책 — **Revisit candidate**
- 실제 모델 latency 최적화 전략 — **TBD**
- 05 평가 대응 전용 Product Contract — **Pending**
- Production Web/API 배포 구조 — **TBD**
- 첨부파일 최종 저장소 — **TBD**, 현재 LOCAL

## 관련 Current 문서

- [AI Copilot · Current Architecture](../03_ai/ai-copilot.md)
- [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md)
- [Architecture](../02_architecture/README.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)

중요한 결정이 장기간 유지되고 변경 조건까지 안정화되면 이 README의 목록에서 개별 ADR 파일로 승격합니다.
