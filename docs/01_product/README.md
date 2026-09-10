# Product 문서 안내

> **상태: Current**  
> 기준: `develop` + Figma 7개 화면

이 문서는 제품 고도화 전에 팀이 같은 사용자 흐름과 현재 범위를 보도록 하는 기준선입니다. 상세 구현은 각 기술 문서에서 관리합니다.

## 제품 목표

원공고를 기준으로 준비한 자격판정과 근거를 확인하고, 변경공고 이후에도 기존 판단이 유효한지 Requirement 단위로 다시 검증합니다.

제품 Vision에는 공고 찾기·자격판정·평가 대응·변경 재검증이 포함되지만, 현재 Release Spine은 **Qualification + Evidence + Ask-back + Change Revalidation**입니다. 05 Evaluation/Proposal 영역은 전용 Product pipeline이 확정되기 전까지 별도 범위로 봅니다.

## 현재 사용자 흐름

```text
회사 Profile
→ 공고 조회/선택
→ Preflight Case / 현재 Version
→ 문서 Parsing
→ Requirement Extraction + Evidence
→ deterministic Judgment
→ Askable UNKNOWN 해결
→ Evidence 원문 확인
→ 변경공고 Requirement Diff
→ affected-only Revalidation
```

## 현재 화면 기준

| 순서 | Route | 역할 |
| --- | --- | --- |
| 01 | `/notices` | 공고 찾기 / 분석된 공고 후보 확인 |
| 02 | `/qualification` | 참가자격 분석·판정 결과 |
| 03 | `/ask-back` | 확인 가능한 UNKNOWN에 답변 |
| 04 | `/evidence` | 판정 근거 원문 대조 |
| 05 | `/evaluation` | 평가 대응 참고 화면 · 전용 extraction 미완료 |
| 06 | `/changes` | 변경공고 Diff / 영향 확인 |
| 07 | `/company` | 회사 Profile 관리 |

Figma는 화면 IA와 UX 방향의 Source of Truth이며, 실제 지원 기능과 상태는 `develop` 코드/API를 우선합니다.

## 초기 기획 ↔ Current 구현 Reconciliation

초기 Notion 문서는 제품 의도와 의사결정 배경으로 보존합니다. 아래 항목은 현재 구현 정책이 발전한 부분이므로 초기 문구를 그대로 재구현하지 않습니다.

| 초기 기획 표현 | Current 기준 |
| --- | --- |
| 자격 7유형 | Qualification Canonical **8유형** (`COMPANY_SIZE` 포함) |
| 🟢/🔵/🟡/🔴 4상태를 판정 상태처럼 사용 | 개별 `SATISFIED/UNSATISFIED/UNKNOWN` + `basis_type` + 전체 `overall_status`로 분리 |
| `confidence: low`이면 Ask-back | **Superseded**. `UNKNOWN != ASKABLE`; grounding/diagnostic/profile completeness/askability를 분리 |
| Ask-back 답변을 자동 Profile 저장 | 현재 MVP Policy A는 기본 `apply_to_profile=false`; `USER_ANSWER` 판정 근거로 사용 |
| RAG = Vector DB 전제 | 현재 Core는 section/keyword Retrieval baseline. Vector/Hybrid/Reranker는 평가 후 선택 후보 |
| 05 Evaluation이 완성된 핵심 흐름 | Route는 존재하지만 전용 Evaluation Criterion extraction/product pipeline은 아직 별도 범위 |

## 제품 불변조건

- LLM이 최종 참가 가능/불가를 직접 결정하지 않습니다.
- `UNKNOWN`은 곧바로 사용자 질문 가능 상태가 아닙니다.
- `PARTIAL` Analysis를 완전한 성공처럼 표현하지 않습니다.
- 변경 전 결과를 덮어쓰지 않고 Version / Run 단위로 추적합니다.
- 결과에는 추적 가능한 Requirement / Evidence가 연결되어야 합니다.
- 현재 회사 Profile과 과거 Judgment의 `profile_snapshot`을 구분합니다.
- AI Copilot은 기존 Product Judgment를 설명하며 별도 판정기를 만들지 않습니다.

## 현재 고도화 포인트

- 현재 section/keyword Retrieval과 Requirement Extraction 품질 정량화
- meaningful 변경공고 G2 확보
- Evaluation/Proposal Release 범위 확정
- 01→02→03→04→06 Human Click Golden Story
- Figma 최신 7 Frame visual QA
- Production Deployment/Smoke
- AI Copilot을 기존 Product API 위에 추가

## 상세 Current 문서

- [Feature Traceability](../02_architecture/feature-traceability.md)
- [AI Retrieval Current State](../03_ai/retrieval-current-state.md)
- [DB ERD](../04_contracts/db-erd-current.md)
- [Backend API Catalog](../04_contracts/backend-api-catalog.md)
- [Frontend Screen Contract](../05_ui_ux/frontend-screen-contract.md)
- [Requirement/Test/Golden Traceability](../08_qa_reports/requirement-test-traceability.md)

## 변경 체크리스트

제품 흐름 또는 화면 범위를 변경하는 PR에서는 다음을 확인합니다.

- Figma와 실제 Route 영향
- Backend/API/DB/AI Contract 영향
- 초기 기획과 Current 정책 중 무엇을 변경하는지
- 기존 Case / Version / Analysis / Judgment lineage 호환성
- Golden/E2E 시나리오 수정 필요 여부
- 중요한 범위 변경의 Decision Log/ADR 필요 여부
