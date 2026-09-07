# 02. System Flow

## 1. Current integration spine

현재 저장소에서 확인되는 기본 축은 다음과 같습니다.

```text
apps/web
   ↓ HTTP
apps/api
   ├─ companies
   ├─ master-codes
   ├─ notices
   └─ preflight-cases
        ↓
PostgreSQL + document storage
        ↓
notice/document extracted blocks
```

공고 수집과 문서 추출, Company Profile, Preflight Case는 Backend 영역에 이미 존재합니다.

AI 영역에는 Backend state를 직접 수정하지 않는 Qualification 분석 파이프라인이 존재합니다.

```text
Backend extracted blocks
        ↓
canonical source blocks
        ↓
semantic chunks
        ↓
structured extraction
        ↓
deterministic normalization
        ↓
Canonical Requirement + Evidence
        ↓
RequirementAnalysisResult
```

## 2. Target MVP Integration Flow

Baseline에서 연결하려는 최종 흐름입니다.

```text
[1] 나라장터 Notice Sync / Poller
        ↓
[2] Notice
        ↓
[3] Notice Version
        ↓
[4] Notice Documents
        ↓
[5] Extracted Source Blocks
        ↓
[6] Qualification Analysis
        ↓
[7] Canonical Requirements + Evidence
        ↓
[8] Company Profile
        ↓
[9] Judgment Engine
        ↓
    SATISFIED
    UNSATISFIED
    UNKNOWN
        ↓
[10] UNKNOWN → Ask-back
        ↓
[11] User Answer 저장
        ↓
[12] 영향 Requirement 부분 재판정
        ↓
[13] Frontend 결과 표시
```

변경공고가 들어오면 동일한 제품 흐름에 Version 축이 추가됩니다.

```text
Notice Version N
        ↓
Canonical Requirements N
        ↓
기존 Judgment

        + 변경공고

Notice Version N+1
        ↓
Canonical Requirements N+1
        ↓
Requirement Diff
        ↓
Affected Requirement Keys
        ↓
Revalidation
        ↓
변경 전/후 판정 + 새 Evidence
```

## 3. Responsibility boundaries

### Frontend — `apps/web`

책임:

- 공고 탐색/선택
- Company Profile 입력 및 선택
- 참가자격 판정 화면
- 근거 원문 이동
- Ask-back 입력
- 변경 전/후 결과 표현

Frontend는 Canonical 판정 로직을 자체 복제하지 않습니다.

### Backend — `apps/api`

책임:

- API request validation
- 원본 Backend ID의 source of truth
- DB 조회/저장
- Notice/Version/Document 관리
- Company Profile 관리
- AI 분석 호출
- Judgment orchestration
- Ask-back / Answer state 관리
- Change/Revalidation orchestration
- Frontend용 안정된 응답 제공

### DB / Storage

책임:

- Notice / Version
- Document metadata / hash / storage location
- Extracted blocks
- Company Profile
- Preflight Case
- Baseline에서 추가 연결되는 Requirement / Evidence / Judgment / Answer / Revalidation state

실제 저장 Model 존재 여부는 Stage 2에서 코드 기준으로 확정합니다.

### LLM / RAG — `apps/api/app/ai` + related modules

책임:

- Backend extracted block을 입력으로 받음
- Semantic chunking
- Structured requirement extraction
- Deterministic normalization과 결합
- Canonical Requirement 생성
- Evidence provenance 보존
- 분석 diagnostic 반환

AI가 Backend DB PK나 원본 문서 ID를 임의 생성해 source of truth를 대체하지 않습니다.

### Judgment / Rule layer

Baseline 목표 책임:

- Canonical Requirement와 Company Profile 비교
- `SATISFIED / UNSATISFIED / UNKNOWN` 생성
- `reason_code`, basis, profile reference 기록
- UNKNOWN이 사용자 입력으로 해소 가능한지 식별

구체 구현 위치는 Stage 2 Gap 검산 후 확정합니다.

## 4. Identifier chain

핵심 식별자는 다음 순서로 추적 가능해야 합니다.

```text
notice_id
└─ notice_version_id
   ├─ document_id
   │  └─ extracted block locator
   │     └─ evidence_key
   └─ requirement_key
      └─ judgment_key
         ├─ preflight_case_id
         ├─ company/profile refs
         └─ optional user answer
```

### Identifier rules

- `notice_id`: 공고 identity
- `notice_version_id`: 분석과 판정의 공고 버전 고정점
- `document_id`: Backend가 관리하는 원본/첨부문서 identity
- `evidence_key`: Requirement와 원문 근거 연결 key
- `requirement_key`: 해당 Version의 Canonical Requirement identity
- `judgment_key`: 특정 Case/Version/Requirement 판정 identity

## 5. Evidence flow

```text
원본 파일
→ file_sha256
→ extracted text
→ extracted_text_sha256
→ source blocks
→ semantic chunks
→ Evidence location
→ UI 원문 근거
```

원본 파일 hash와 추출 텍스트 hash는 서로 다른 identity이며 합쳐서 취급하지 않습니다.

## 6. Failure flow

### AI analysis failure

```text
SUCCEEDED → 정상 canonical result
PARTIAL   → 일부 결과 + diagnostic
FAILED    → canonical requirement/evidence를 성공 결과처럼 사용 금지
```

### Judgment information gap

```text
Requirement는 유효
+ Profile 정보 부족
→ UNKNOWN
→ Ask-back 또는 확인 필요
```

AI 분석 실패와 사용자 Profile 정보 부족은 서로 다른 상태이므로 같은 상태값으로 합치지 않습니다.

## 7. Stage 2 verification points

다음 연결부는 실제 코드/DB 모델을 확인해 **Implemented / Connect / Missing**으로 분류합니다.

- AI pipeline 호출 entry point
- AI result DB persistence
- Requirement/Evidence persistence
- Judgment implementation
- Ask-back model/API
- Answer persistence
- Requirement Diff / Revalidation implementation
- Frontend result mapping
