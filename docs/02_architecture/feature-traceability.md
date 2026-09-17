# Feature ↔ Screen ↔ API ↔ DB ↔ AI Traceability

> **상태: Current**  
> 기준: `develop` · 실제 코드/테스트가 최종 Source of Truth

이 문서는 제품 기능 하나를 바꿀 때 어떤 화면·API·저장 데이터·AI/Rule·검증이 함께 영향을 받는지 빠르게 찾기 위한 지도입니다.

## 전체 흐름

```text
사용자 화면
→ Product API / Case Context
→ Persisted Run / Version
→ AI Core 또는 deterministic Rule
→ 결과 저장
→ 화면 표시
→ Test / Golden / Human E2E
```

Copilot은 이 흐름을 대체하지 않고 현재 Case의 Product 결과와 공개 공고문 Source를 조회·설명하는 교차 기능입니다.

## 01~07 Traceability

| 기능 | Screen | 주요 API / Service | 주요 Persisted State | AI / Rule | 현재 검증 포인트 |
| --- | --- | --- | --- | --- | --- |
| 01 공고 찾기 | `/notices` | `GET /api/v1/notices`, `GET /api/v1/companies/{company_id}/notice-matches` | `bid_notices`, `bid_notice_versions`, Company Profile | cached qualification matching | 미분석 공고와 분석 완료 공고를 구분하고 추천 근거/상태를 과장하지 않음 |
| 02 참가자격 | `/qualification` | Qualification Analysis + Judgment API | `qualification_analysis_runs`, `qualification_requirements`, `qualification_evidence`, `qualification_judgment_runs`, `qualification_judgments` | Requirement Extraction → deterministic Judgment | `AnalysisStatus`와 `JudgmentStatus`를 분리하고 최신 Analysis와 일치하는 Judgment만 표시 |
| 03 확인 필요 | `/ask-back` | Questions + Answers API | `qualification_answers`, 새 `qualification_judgment_run` | `askability.py` + targeted re-judgment | `UNKNOWN != ASKABLE`; 단순 사용자 사실로 안전하게 해소 가능한 항목만 질문 |
| 04 근거 원문 | `/evidence` | Notice/Proposal document text/source/preview API | `notice_documents`, `proposal_documents`, `qualification_evidence` | Evidence grounding / locator | `requirement_key → evidence_key → document_id → location` 역추적 유지 |
| 05 평가 대응 | `/evaluation` | 현재 전용 Evaluation Product API 없음 | 전용 Evaluation persistence 미확정 | `evaluation_contracts.py`는 criteria contract이며 LLM 품질평가 Harness가 아님 | 현재 화면을 자격요건 분석 결과와 평가기준 전용 추출로 혼동하지 않음 |
| 06 변경 이력 | `/changes` | Notice Version 조회 + Qualification Revalidation API | `bid_notice_versions`, `qualification_revalidation_runs`, 이전/현재 Analysis/Judgment Run | `requirement_diff.py` + affected-only revalidation | 문자열 diff보다 Requirement 영향과 before/after Judgment를 우선 |
| 07 회사 프로필 | `/company` | Company CRUD / completeness / performance / certification | `companies`, `company_*`, completeness | qualification rule의 좌변 | 현재 Profile과 과거 `profile_snapshot`을 구분하고 수정이 과거 판정을 소급 변경하지 않게 함 |

## AI Copilot · Cross-cutting Traceability

Copilot은 02~06 Workspace의 `caseId`를 사용하며 여러 Product 기능을 하나의 대화 흐름에서 읽습니다.

| Copilot 기능 | UI | 주요 API / Service | 상태/데이터 | AI / Rule | 검증 포인트 |
| --- | --- | --- | --- | --- | --- |
| Guided Job catalog | Copilot Panel | `GET /api/v1/copilot/jobs` | 현재 Case / baseline/current version | 서버 고정 Job/Question Contract | UI 버튼이 임의 Task 범위를 만들지 않음; AVAILABLE/BLOCKED 사유 유지 |
| 자유질문 / 대화 | Copilot Panel | `POST /api/v1/copilot/chat` | process-memory ConversationState + 현재 Product reads | v3.1 Planner / Target resolution | scope 변경 시 과거 target/fact/source 해제; 모호한 순번 임의 선택 금지 |
| 판정 설명 | Copilot Panel | Qualification read adapter | persisted Judgment / profile snapshot | Product Judgment가 Source of Truth | LLM이 참가 가능 여부를 새로 계산하지 않음 |
| 원문 근거 QA | Copilot Panel | Copilot Document QA + notice documents | current notice version / document index | Hybrid Retrieval + Grounded Answer | current version만 사용; no-hit/no-citation은 abstain |
| 변경공고 설명 | Copilot Panel | Change read adapter / Revalidation result | baseline/current Analysis/Judgment | Requirement Diff + 저장 재검증 | 변경 표현과 실제 회사 영향 구분; 연결된 snapshot 없으면 추정 금지 |
| Claim validation | Copilot response | v3.1 coordinator | Fact / Source / Claim / AnswerEnvelope | rule/extractive/semantic validation | unsupported claim 게시 금지; 검증된 sibling은 유지하고 PARTIAL 가능 |
| Action proposal | Copilot + 기존 상세 화면 | `/chat` → Proposal | expected provenance | write 실행 없음 | 자연어 동의만으로 실행 금지 |
| Action confirm | 기존 확인 UI / controller | `POST /api/v1/copilot/actions/confirm` | 최신 case/company/version/analysis/judgment | 기존 Ask-back/Revalidation Service | stale/replay/outcome unknown 경계; 최신 provenance 재검증 |

## 핵심 Lineage

```text
BidNotice
  └─ BidNoticeVersion
       ├─ NoticeDocument
       └─ QualificationAnalysisRun
            ├─ QualificationRequirementRecord
            └─ QualificationEvidenceRecord

Company + PreflightCase + AnalysisRun
  └─ QualificationJudgmentRun
       └─ QualificationJudgmentRecord
            ├─ QualificationAnswer → result JudgmentRun
            └─ QualificationRevalidationRun → result JudgmentRun
```

Copilot은 위 lineage를 별도로 복제하지 않고 현재 Scope로 참조합니다.

```text
Conversation Scope
→ case_id
→ company_id
→ notice_id / notice_version_id
→ analysis_run_id
→ judgment_run_id
→ Product Fact / Document Source
→ validated Claim
```

## 화면 공통 Case Context

02~06 화면은 서로 독립된 결과 화면이 아니라 같은 `preflight_case_id`를 공유하는 Workspace입니다.

```text
caseId
→ company_id
→ notice_id
→ baseline/current version
→ latest compatible analysis
→ matching rule-version judgment
→ ask-back / evidence / revalidation
```

Frontend는 `apps/web/lib/case-workspace.ts`에서 이 관계를 맞춥니다. 오래된 Analysis/Judgment를 단순히 최신 생성시각만 보고 섞지 않습니다.

Copilot 또한 현재 authorized Case Scope를 기준으로 Product Tool을 다시 읽고 과거 대화의 fact/source를 현재 사실처럼 승격하지 않습니다.

## 변경 시 영향 확인

### Requirement Contract 변경

확인 대상:

- `app/ai/contracts.py`
- Analysis persistence/schema
- Judgment rule
- Frontend qualification/evidence rendering
- Askability / Requirement Diff
- Copilot Product Tool Adapter / Claim Source mapping
- Golden fixture / regression

### Company Profile 변경

확인 대상:

- SQLAlchemy model + Alembic
- Company API
- Profile completeness
- deterministic Judgment
- `/company`, `/qualification`, Matching
- `profile_snapshot` 재현성
- Copilot `READ_PROFILE` / 회사 영향 설명

### Evidence locator 변경

확인 대상:

- source block/chunk adapter
- `qualification_evidence.location`
- Document source/preview API
- `/evidence` / qualification evidence link
- Copilot Product Evidence Source / EvidenceChip
- citation/evidence accuracy test

### Changed Notice 로직 변경

확인 대상:

- Notice Version / relation
- Requirement Diff
- Revalidation lineage
- `/changes`
- Copilot `READ_CHANGES` / `changed_notice` Guided Job
- G2 Golden scenario

### Copilot Contract 변경

확인 대상:

- `app/copilot/v31_contracts.py`
- `job_catalog.py`
- `orchestration.py`
- `tool_adapters.py`
- `answer_validation.py`
- `apps/web/lib/copilot-api.ts`
- `apps/web/lib/copilot-conversation.ts`
- `apps/web/components/copilot/**`
- Copilot fixed regression / E2 routing / E3 RAG / Guided Job tests
- `docs/03_ai/ai-copilot.md`
- `docs/08_qa_reports/ai-copilot-final-evaluation.md`

## 문서 갱신 규칙

기능 PR에서 위 연결 중 하나가 바뀌면 해당 파트 문서만 수정하는 것으로 끝내지 않고 이 Traceability의 연결도 함께 확인합니다. 실제 Task 상태는 이 문서에 복제하지 않고 GitHub Issue / Projects에서 관리합니다.
