# Post-Baseline Roadmap

> **상태: Proposed**  
> Product Integration Baseline 이후의 **남은 고도화 방향**을 기록합니다. 실제 일정·담당·진행 상태는 GitHub Projects/Issue를 Source of Truth로 둡니다.

## 목적

이 문서는 Task 목록을 대신하지 않습니다. 이미 구현·평가가 완료된 항목은 Current 문서와 QA 보고서로 이동하고, 여기에는 아직 닫히지 않은 기술·제품 과제를 남깁니다.

Current Copilot 구현은 [AI Copilot · Current Architecture](../03_ai/ai-copilot.md), 평가 결과는 [AI Copilot · Final Evaluation Narrative](../08_qa_reports/ai-copilot-final-evaluation.md)를 우선합니다.

## 현재 고도화 Track

### Frontend / UI·UX

- 01~07 Human Click E2E 최종 완료
- Copilot 사람 사용자 Test Case 실제 수행
- 접근성/키보드/스크린리더 검증
- Error/Empty/PARTIAL 표현 정리
- 실제 사용자 피드백 기반 Panel 정보 밀도 개선

### Backend / API

- 도메인별 모듈 구조 정리 검토
- API Error/Contract 안정화
- 인증/권한 및 분리 배포 환경 정책
- Copilot durable conversation/history API 필요성 검토
- 실제 운영에서 multi-worker Conversation 동작 설계

### DB / Data

- 실제 ERD 최신화
- Profile provenance / data quality
- Evaluation Criterion 저장 전략
- 실제 변경공고 Golden 데이터 확장
- Copilot Conversation을 persistence할 경우 tenant/user/case 범위 설계

### LLM/RAG Core

- 실제 Golden 기반 Requirement Extraction precision / recall / F1
- Core Retrieval baseline 정량화
- Evidence grounding / dropped requirement diagnostic
- 필요 시 Dense/Hybrid/Reranker 실험 — Copilot Document QA와 별도 평가
- 변경공고 의미 변화 품질 고도화

### AI Copilot

다음 항목은 **이미 Current**이므로 Roadmap 대상이 아닙니다.

- Product Tool 기반 판정/근거 조회
- Semantic Routing
- Multi-turn target/context
- Document QA Hybrid Retrieval
- Fact / Source / Claim Validation
- Guided Job 2종 / 질문 6개
- 자유 입력
- Action Proposal / Explicit Confirm

남은 Copilot 고도화:

- 새 독립 blind 질문셋 평가
- Stage 11 사람 사용자 평가 실제 결과 확보
- 실제 모델 복합 답변 latency 개선
- Guided Job COMPLETE/PARTIAL 안정성 개선
- process-memory Conversation의 durable storage 전환 여부 결정
- selective rerank / hard-query 전략 필요성 재검토
- 실제 운영 데이터 전체 E2E와 배포 Smoke Test

### Infra / Operations

- 실제 배포 Target 확정
- CI gate 개선
- 환경변수/Secret 관리
- logging / observability
- 모델 호출 usage/latency trace 운영화
- backup / restore / 운영 Runbook

## 현재 단계

```text
Product Integration Baseline
→ Copilot E0/E1/E2/E3 개선·평가
→ v3.1 Claim Validation
→ Guided Job 통합
→ Current docs 정리
→ Human User Test / Blind Evaluation
→ Deployment Smoke
→ Final Submission / 발표 근거 고정
```

## Roadmap 작성 원칙

- 가능성과 확정 계획을 구분합니다.
- 이미 구현된 Current 기능을 계속 `향후 구현`으로 남기지 않습니다.
- 실험 후보를 바로 최종 Architecture처럼 기록하지 않습니다.
- 선택이 확정되면 Current 문서 또는 Decision Log/ADR로 이동합니다.
- 실제 일정/Owner/Status는 Issue/Project에서 관리합니다.
- 완료된 항목은 최종 문서에 결과와 근거를 남기고 단순 체크리스트로 끝내지 않습니다.
- Routing, Retrieval, Grounded Answer, 사용자 평가를 하나의 `정확도`로 합치지 않습니다.
