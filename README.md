# bid-change-validator

> Validates how changed public procurement notices affect existing bid qualifications, required documents, and submission readiness.

## Project

**나라장터 변경공고 대응형 입찰 제출 검증기**

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 다시 확인하고, 변경된 조건과 원문 근거를 바탕으로 영향을 받은 항목을 재검증하는 프로젝트입니다.

**Current Stage**  
`develop` 기준 Product Integration + AI Copilot 통합 상태입니다. 이 README의 문서 기준은 2026-09-16 PR #151 병합 커밋 `f56d3484e9c3ca1b1badbeafcda9bd5f057c65d5` 이후입니다.

현재 구현에는 01~07 Product Workspace, deterministic Qualification Rule, Evidence/Ask-back/Revalidation, AI Copilot v3.1, Guided Job 2종·질문 6개와 자유 입력이 포함됩니다. 다만 **사람 사용자 평가, 새 독립 blind 평가, 실제 운영 데이터 전체 E2E와 Production Smoke가 모두 완료됐다는 뜻은 아닙니다.**

## Team

| Member | Initial Role | Current Focus |
| --- | --- | --- |
| 김재현 | LLM / RAG | LLM/RAG Core · Evaluation |
| 이홍규 | LLM / RAG · Collaboration Infrastructure | AI Copilot · Integration |
| 전진환 | Backend / Overall Structure | Backend / Overall Structure |
| 정예린 | DB / Data Management | DB / Data Management |
| 황수빈 | Frontend / UI·UX | Frontend / UI·UX |

> 초기 역할은 2026-09-02 회의 기준이며, AI 영역은 이후 Core와 Copilot/Integration으로 책임을 분리했습니다.

## Documentation

현재 구현·정책·평가의 시작점은 [docs/README.md](docs/README.md)입니다.

AI Copilot만 확인할 경우 다음 두 문서를 먼저 봅니다.

- [AI Copilot · Current Architecture](docs/03_ai/ai-copilot.md)
- [AI Copilot · Final Evaluation Narrative](docs/08_qa_reports/ai-copilot-final-evaluation.md)

과거 Product Integration Baseline은 [docs/mvp-baseline/README.md](docs/mvp-baseline/README.md)에 Snapshot으로 보존합니다. 초기 LLM/RAG 설계와 단계별 평가 보고서는 현재 문서의 근거·Historical Evidence로 사용합니다.

## Current Product Flow

```text
회사 Profile
→ 실제 공고 조회 / Case 선택
→ 공고·첨부 Parsing
→ Requirement Extraction + Evidence
→ deterministic Qualification Rule
→ SATISFIED / UNSATISFIED / UNKNOWN
→ Askable UNKNOWN만 USER_ANSWER
→ 부분 재판정
→ Evidence 원문 확인
→ 변경공고 Requirement Diff
→ affected-only Revalidation
```

현재 Qualification Rule 버전은 `qualification-rules-v0.3`입니다.

핵심 원칙:

- LLM이 최종 참가 가능/불가를 직접 결정하지 않습니다.
- 전체 자격상태의 Source of Truth는 저장된 Judgment Run입니다.
- `UNKNOWN != ASKABLE`입니다.
- `PARTIAL` Analysis를 완전한 성공으로 승격하지 않습니다.
- 현재 회사 Profile과 과거 판정의 `profile_snapshot`을 구분합니다.
- 변경 전 결과를 덮어쓰지 않고 Version / Analysis / Judgment lineage를 유지합니다.

## AI Copilot · Current

AI Copilot은 새로운 판정기가 아니라 **현재 Case의 저장 판정·회사정보 snapshot·공고 원문·변경 결과를 자연어로 조회하고 연결하는 업무 보조 인터페이스**입니다.

```text
사용자
→ Copilot Panel
→ Guided Job 또는 자유 입력
→ Product Read Tools / Document QA
→ Fact / Source
→ Claim 생성·검증
→ AnswerEnvelope v3.1
→ 근거가 연결된 답변 / 제한 / 후속 대상
```

### Guided Job 2종 / 질문 6개

**변경 공고 대응**

1. 무엇이 바뀌었나요?
2. 우리 회사에 어떤 영향이 있나요?
3. 무엇을 확인해야 하나요?

**입찰 참여 준비**

1. 필요한 서류·기한·방법은?
2. 준비 순서는?
3. 아직 확인하지 못한 것은?

추천 질문의 Tool 범위와 완료 조건은 `GET /api/v1/copilot/jobs`의 서버 계약이 소유합니다. 추천 질문과 함께 자유 입력도 사용할 수 있습니다.

### Copilot API

```text
GET  /api/v1/copilot/jobs?case_id={case_id}
POST /api/v1/copilot/chat
POST /api/v1/copilot/actions/confirm
```

Current Frontend의 대화 경로는 `response_version=3.1`을 사용합니다.

- `/chat`: 조회·설명·Action Proposal
- `/actions/confirm`: 사용자 명시 확인 후 최신 provenance를 다시 검증하고 기존 Product Service 실행

자연어 `응`만으로 저장·재검증을 실행하지 않습니다.

### Product Judgment와 Document QA 분리

회사 참가 가능 여부는 Product Judgment가 결정합니다.

공고문의 일반 조항·제출조건 질문은 현재 공고 Version의 검증된 Source를 조회합니다. 준비된 index가 있고 일반 질문이면 Hybrid Retrieval(Dense + BM25/RRF)을 우선 사용하며, broad 질문은 current section을 넓게 읽고 index/embedding 사용이 어려운 경우 lexical/current-section fallback을 사용합니다.

```text
현재 공개 공고문 Source snapshot
→ index readiness / fingerprint 확인
→ READY + 일반 질문: Hybrid Retrieval (k=4, fetch_k=12)
→ broad 질문: current sections
→ 필요 시 lexical/current-section fallback
→ Fact / Source
→ Claim 생성·검증
→ AnswerEnvelope v3.1
```

채팅 요청 중 새 document index를 build하거나 문서 전체를 새로 embedding하지 않습니다. 문서 근거를 확보하지 못한 범위는 `NOT_FOUND` 또는 limitation으로 남기며, 이를 모델이 새 사실로 보완하지 않습니다.

AI Core의 Requirement Extraction Retrieval은 별도 영역이며 현재 section-aware + keyword fallback baseline을 사용하므로, 프로젝트 전체 Retrieval을 하나의 방식으로 표현하지 않습니다.

## AI Copilot Evaluation Snapshot

서로 다른 지표를 하나의 `챗봇 정확도`로 합치지 않습니다.

| 평가 단계 | 대표 결과 | 의미 |
| --- | ---: | --- |
| E0 자유입력 기준선 | 1/100 | frozen 100문항 intent exact match |
| E1 bounded UX 개선 | 41/100 | 동일 routing set 재측정 |
| E2 Semantic Routing | 100/100 | frozen routing set, 답변 정확도 아님 |
| Dense Retrieval | Recall@4 29.17% | expected evidence retrieval |
| Hybrid Retrieval | Recall@4 50.00% | 준비된 index의 기본 검색 전략으로 채택 |
| Hybrid + LLM Rerank | Recall@4 55.56% | latency/비용으로 기본 미채택 |
| Grounded Answer v4 | citation version integrity 100% | semantic answer accuracy와 구분 |
| 남원 합성 프로필 Guided Job | 23/24 COMPLETE | 실제 모델 격리 실행, 사람 사용자 성공률 아님 |

상세 조건·분모·한계는 [AI Copilot · Final Evaluation Narrative](docs/08_qa_reports/ai-copilot-final-evaluation.md)에 기록합니다.

현재 가장 중요한 남은 평가 과제는 **새 독립 blind 질문셋과 사람 사용자 업무 완료 평가**입니다.

## 현재 제품 화면과 실제 흐름

아래 7개 Product Route는 같은 Case/Version 문맥을 공유합니다.

| 화면 | Route | 현재 범위 |
| --- | --- | --- |
| 01 공고 찾기 | `/notices` | 공고 조회·선택·Profile Matching |
| 02 참가자격 검토 | `/qualification` | Analysis / Judgment / Requirement / 근거 요약 |
| 03 확인 필요 | `/ask-back` | ASKABLE UNKNOWN 응답 및 부분 재판정 |
| 04 근거 원문 | `/evidence` | Evidence → 실제 공고 원문 대조 |
| 05 평가 대응 | `/evaluation` | 자격정보 참고; 전용 EvaluationCriterion Product pipeline은 미완료 |
| 06 변경 이력 | `/changes` | Version / Requirement Diff / Revalidation |
| 07 회사 프로필 | `/company` | 회사 기본정보·수행실적·인증/등록 관리 |

Copilot은 이 화면을 대체하지 않고 현재 `caseId`를 사용하는 보조 Panel로 연결됩니다.

## 로컬 PostgreSQL 실행

PostgreSQL을 실행하고 마이그레이션, API, 변경공고 수집기를 시작합니다.

```powershell
docker compose up -d --build api notice-poller
docker compose ps
```

실행 주소:

- 상태 확인: `http://localhost:8000/health`
- Swagger API 문서: `http://localhost:8000/docs`

API 시작 전에 Alembic이 데이터베이스 스키마를 적용합니다. 마이그레이션을 수동으로 적용하려면:

```powershell
docker compose run --rm migrate
```

업종, 품목, 기관 기준정보 CSV를 최초 적재하거나 갱신합니다.

```powershell
docker compose --profile tools run --rm master-data-import
```

기준정보 적재는 UPSERT 방식입니다.

기준정보 검색 API 예시:

```text
GET /api/v1/master-codes/industries?q=토목&limit=20
GET /api/v1/master-codes/products?q=1010150201
GET /api/v1/master-codes/institutions?q=서울&active_only=false
GET /api/v1/master-codes/institutions/1011052
```

## 로컬 Qualification / Copilot Integration 확인

저장소 루트에서 `.env.example`을 `.env`로 복사하고 OpenAI API Key를 설정합니다.

```powershell
Copy-Item .env.example .env
```

```env
OPENAI_API_KEY=sk-...
OPENAI_MODEL_DEFAULT=gpt-5.6-luna
```

`.env`와 `.env.*`는 Git ignore 대상이며 `.env.example`만 추적합니다. 실제 API Key를 commit하지 마세요.

Backend 코드를 변경한 뒤에는 API 이미지를 다시 빌드합니다.

```powershell
docker compose up -d --build api
```

프론트엔드는 별도 터미널에서 실행합니다.

```powershell
cd apps/web
Copy-Item .env.example .env.local
pnpm install
pnpm dev
```

확인 주소:

- API health: `http://localhost:8000/health`
- Swagger: `http://localhost:8000/docs`
- 기본 화면: `http://localhost:3000`
- Qualification: `http://localhost:3000/qualification`

`OPENAI_API_KEY`가 비어 있으면 qualification analysis 실행 시 `AI_PROVIDER_NOT_CONFIGURED` 오류가 반환되는 것이 정상입니다.

## 나라장터 공고 수집

등록공고, 변경공고 또는 공고번호 한 건을 API로 수집할 수 있습니다.

```text
POST /api/v1/notices/sync
GET  /api/v1/notices?q=정보시스템&business_type=SERVICE
GET  /api/v1/notices/{notice_id}
GET  /api/v1/notices/{notice_id}/versions
GET  /api/v1/notices/collection-runs
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/content
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/text
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/preview
GET  /api/v1/notices/{notice_id}/versions/{version_number}/documents/{document_id}/source
POST /api/v1/notices/documents/extract-pending
```

수집기는 정규화한 공고 필드와 나라장터 원본 JSON을 함께 저장합니다. 이전과 동일한 원본 데이터는 기존 버전을 재사용하고, 내용이 바뀌면 다음 버전을 생성해 현재 버전으로 표시합니다.

표준공고문과 첨부파일을 내려받고 URL·파일 hash가 같은 파일은 중복 저장하지 않습니다. HWP/HWPX는 구역·문단 단위, PDF는 페이지 단위로 텍스트를 추출합니다. 추출 텍스트는 시각적 서식을 완전히 보존하지 않으므로 최종 증빙은 원본 파일과 함께 확인합니다.

`notice-poller`는 설정된 주기로 변경공고를 조회하고 마지막 성공 구간부터 수집을 재개합니다. 실행 결과는 `GET /api/v1/notices/collection-runs`에서 확인할 수 있습니다.

## 제안서 사전검토 건

공고 버전을 기준으로 검토 건을 생성하고 제안서 파일을 업로드할 수 있습니다.

```text
POST /api/v1/preflight-cases
GET  /api/v1/preflight-cases
GET  /api/v1/preflight-cases/{case_id}
POST /api/v1/preflight-cases/{case_id}/documents
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/source
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/content
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/text
GET  /api/v1/preflight-cases/{case_id}/documents/{document_id}/preview
```

업로드 API는 HWP, HWPX, PDF, DOCX, TXT 형식을 지원합니다. 파일 크기를 제한하고 SHA-256으로 검토 건 안의 중복 파일을 차단합니다.

이 업로드 단계 자체가 Qualification Judgment를 생성하는 것은 아닙니다.

## Historical Product Baseline

`docs/mvp-baseline/`에는 2026-09-08 전후 Product Integration Baseline 감사·Golden·handoff 기록을 보존합니다.

현재 Rule/Frontend/Copilot은 그 이후 발전했으므로 Baseline 문서의 당시 버전·브랜치·테스트 수치를 Current 구현 사실로 읽지 않습니다.

현재 Rule은 `qualification-rules-v0.3`이며, 과거 Analysis/Judgment가 존재한다는 이유만으로 현재 Rule·grounding 정책을 통과했다고 간주하지 않습니다. 필요하면 현재 Version/Analysis/Rule 조합으로 재분석·재판정·재검증합니다.

## AWS 배포 설정

로컬 Docker에서는 `notice_documents_data` 볼륨에 문서를 저장합니다. AWS에서는 다음 환경변수를 설정해 S3 저장소를 사용할 수 있습니다.

- `DOCUMENT_STORAGE_BACKEND=S3`
- `DOCUMENT_S3_BUCKET`
- `DOCUMENT_S3_PREFIX`
- `AWS_REGION`

ECS 또는 EC2에는 고정 AWS 키를 저장하지 않고 IAM 역할로 S3 접근 권한을 부여해야 합니다. PostgreSQL은 RDS, API와 변경공고 수집기는 별도 ECS 서비스 또는 EC2 프로세스로 운영하는 구성을 검토할 수 있습니다.

이 구성 설명은 실제 Production Deployment 완료를 의미하지 않습니다.

## Collaboration

기본 개발 흐름:

```text
Requirement / Design
→ GitHub Issue / Project
→ Branch
→ Pull Request
→ Review / Test
→ Merge
→ Done
```

- `main`: 안정 버전 / 최종 반영 기준
- `develop`: 팀 통합 브랜치
- 기능·수정·문서 작업은 별도 Branch에서 시작합니다.
- 주요 변경은 Pull Request와 Review를 거칩니다.
- 과거 Jira/분리 workspace 기록은 Historical 협업 맥락으로만 참고합니다.

초기 병렬 개발에서 사용한 별도 workspace:

| Workspace | Owners | Repository |
| --- | --- | --- |
| Frontend | 황수빈 (Main), 이홍규 (Sub) | https://github.com/gyuniverse-hq/bid-change-validator-frontend |
| Backend / Data | 전진환 (Backend), 정예린 (DB / Data) | https://github.com/gyuniverse-hq/bid-change-validator-backend |
| LLM / RAG | 김재현, 이홍규 | https://github.com/gyuniverse-hq/bid-change-validator-llm-rag |

현재 구현과 계약은 이 통합 저장소 `develop`과 `docs/`를 우선합니다.