# QA / E2E 문서 안내

> **상태: Current + Proposed**  
> 기준: `develop`

이 문서는 기능 구현이 실제 제품 흐름에서 안전하게 동작하는지 검증하기 위한 공통 기준입니다.

## 검증 레이어

### Unit / Domain
- Requirement Extraction
- Canonical Mapping
- deterministic Judgment
- Askability
- Requirement Diff / Revalidation
- Backend Service
- Frontend data handling

### Integration
- Frontend ↔ Backend API
- Backend ↔ DB
- Backend ↔ AI Core
- Version / Case / Analysis / Judgment 연결

### E2E

```text
Company Profile
→ Notice 선택
→ Analysis
→ Judgment
→ UNKNOWN 확인
→ Ask-back
→ 부분 재판정
→ Evidence 원문 확인
→ Changed Notice
→ Revalidation
```

## Golden 기준

현재 Product Baseline에서 사용한 Golden 개념은 다음처럼 유지합니다.

- **G0**: Synthetic deterministic regression
- **G1**: 실제 공고 Extraction reality check
- **G2**: 실제 meaningful Qualification 변경공고 시나리오

G0/G1/G2의 과거 상세 결과는 `docs/mvp-baseline/`을 Baseline Snapshot으로 참고합니다.

## 파트별 Evaluation

### AI Core
- Requirement recall / precision
- type/value mapping 정확도
- Evidence grounding 정확도
- Unsupported / UNKNOWN 처리
- Retrieval 품질

### AI Copilot
- Intent accuracy
- Tool selection accuracy
- Grounded answer correctness
- Citation accuracy
- Multi-turn context accuracy

### Frontend
- Route / Case Context 유지
- Loading / Error / Empty / Partial
- Evidence 이동
- 접근성

### Backend / DB
- API Contract
- Error Code
- transaction/data integrity
- stale Run 방지
- Migration regression

## CI 현재 기준

`.github/workflows/`에는 Product Baseline CI와 Project Ready-for-review 자동화가 존재합니다. CI의 실제 명령과 통과 조건은 Workflow 파일을 Source of Truth로 둡니다.

## 완료 조건

기능을 Done으로 판단하기 전에 최소한 다음을 확인합니다.

- 정상 경로 테스트
- 실패/불완전 데이터 경로
- 관련 Contract regression
- 기존 기능 영향
- 필요한 docs 갱신

## Known Gaps

- 실제 meaningful G2 확보 필요
- 01~07 전체 Human Click E2E 완료 필요
- AI Core 정량 Evaluation Harness 고도화 필요
- Copilot Golden Set 신규 설계 필요
- 접근성/전체 lint debt 정리 필요
