# QA / E2E 문서 안내

> **상태: Current + Historical Evaluation Evidence**  
> 기준: `develop` · Copilot Current 기준 2026-09-17

이 문서는 기능 구현이 실제 제품 흐름에서 안전하게 동작하는지 검증하기 위한 공통 기준입니다. 자동테스트, 고정 회귀, Retrieval 평가, 실제 모델 실행, 사람 사용자 테스트를 서로 같은 의미로 사용하지 않습니다.

## 먼저 볼 문서

- [AI Copilot · Final Evaluation Narrative](ai-copilot-final-evaluation.md) — **Copilot 전체 개선·평가 요약**
- [AI Copilot v2 개선·평가 원본](ai-copilot-v2/README.md) — **E0→E3 재현 가능한 원본**
- [AI Copilot v1 평가](ai-copilot-v1-evaluation.md) — **Product Tool/Action 고정 회귀**
- [Requirement ↔ Test ↔ Golden / E2E Traceability](requirement-test-traceability.md)
- [v3.1 구현·재검증](../07_handoff/ai-copilot-v3.1/03-implementation-and-verification.md)

## 검증 레이어

```text
Unit / Domain
→ Service / API
→ Integration
→ Fixed Regression / Golden
→ Retrieval / Grounded Answer Evaluation
→ Actual Model Isolated Run
→ Human Click / User Task Test
→ Deployment Smoke
```

자동테스트 통과와 실제 사용자 E2E 완료를 같은 의미로 사용하지 않습니다.

## Product E2E Spine

```text
Company Profile
→ Notice 선택
→ Analysis
→ Judgment
→ UNKNOWN 확인
→ Ask-back
→ 부분 재판정
→ Evidence 원문 확인
→ Contract Risk Clause
→ Changed Notice
→ Revalidation
```

Copilot은 이 Product Spine 위에서 현재 Case의 판정·근거·회사정보 snapshot·변경 결과·공개 공고문을 대화로 연결합니다.

## Golden 기준

- **G0**: Synthetic deterministic regression
  - 특정 회사 1개에 과적합되지 않도록 복수 합성 Profile 사용
- **G1**: 실제 공고 Extraction / Evidence reality check
- **G2**: 실제 meaningful Qualification 변경공고 시나리오

과거 Product Baseline 상세 결과는 `docs/mvp-baseline/`을 Snapshot으로 참고합니다.

## 파트별 Evaluation

### AI Core

- Requirement precision / recall / F1
- Core Retrieval Recall@K / MRR
- Evidence grounding/citation correctness
- Unsupported / abstention correctness
- Guardrail / dropped requirement diagnostic
- 위험조항 9종 category/Evidence correctness

### AI Copilot — Current

Copilot은 한 개의 정확도 대신 다음 축을 분리합니다.

- Intent / routing exact match
- Product task reachability / tool selection
- Document QA Retrieval Recall@K
- Grounded citation 구조·version integrity
- Claim ↔ Fact ↔ Source validation
- Multi-turn target/context consistency
- Action safety / explicit confirm
- Actual model task COMPLETE/PARTIAL
- Human user task completion / 이해도
- latency p50/p95 또는 실제 turn elapsed

상세 수치와 해석 제한은 [AI Copilot · Final Evaluation Narrative](ai-copilot-final-evaluation.md)를 우선합니다.

### Frontend

- Route / Case Context 유지
- Loading / Error / Empty / Partial
- Evidence 이동
- Copilot Panel / Drawer
- 접근성
- Human Click E2E

### Backend / DB

- API Contract
- Error Code
- transaction/data integrity
- stale Run 방지
- Migration regression
- Supabase 공유 DB Alembic lineage

## Copilot 평가 발전 과정

```text
v1 Product 계약 회귀
→ E0 자유입력 기준선
→ E1 bounded UX 개선
→ E2 Semantic Routing
→ E3 Retrieval / Grounded Answer
→ v3.1 Fact/Source/Claim 검증
→ Guided Job 실제 모델 평가
→ Human User Test (결과 미완료)
```

현재 중요한 해석 원칙:

- v1 `100/100`은 노출된 고정 계약 회귀입니다.
- E2 `100/100`은 frozen intent routing입니다.
- E3 `Recall@4`는 Retrieval 지표이며 답변 정확도가 아닙니다.
- Citation version integrity는 인용 Version 연결의 무결성이지 의미 정답률이 아닙니다.
- Guided Job `23/24 COMPLETE`는 합성 프로필 실제 모델 격리 실행이며 사람 사용자 성공률이 아닙니다.

## Human User Test 상태

`ai-copilot-v2/stage11-user-test-plan.md`에는 사용자 관점 Core/Safety Test Case와 기록 양식이 정의돼 있습니다.

현재 최종 문서에서는 **사람 사용자 완료율을 완료된 결과로 주장하지 않습니다.** 실제 참여자 결과가 확보되면 자동평가와 별도 섹션으로 추가합니다.

## MVP Demo 인증 / 데이터

- 데모는 관리자 로그인 기준으로 진행합니다.
- Golden Set의 회사 Profile은 복수 합성 Profile을 사용합니다.
- 실제/합성 여부와 Dataset/Version을 기록합니다.
- 사용한 notice/company/version/analysis/judgment run 식별자를 데모 문서에 남깁니다.
- 남원 Demo Guided Job 평가에서는 합성 프로필 J13~J16을 사용한 실제 모델 격리 실행 기록이 존재합니다.

## CI 현재 기준

`.github/workflows/`의 실제 Workflow 파일을 Source of Truth로 둡니다. CI 통과만으로 G1/G2/Human E2E 또는 실제 모델 품질을 완료 처리하지 않습니다.

## 완료 조건

기능을 Done으로 판단하기 전에 최소한 다음을 확인합니다.

- 정상 경로 테스트
- 실패/불완전 데이터 경로
- 관련 Contract regression
- 실제 Golden 검증 필요 여부
- 생성형 답변이면 Fact/Source/Claim 경계
- 화면이면 Human E2E 필요 여부
- 기존 기능 영향
- 필요한 docs 갱신

## Known Gaps

- 새 독립 blind Copilot 질문셋
- Copilot 사람 사용자 테스트 실제 결과
- v3.1 / Guided Job 실제 모델 latency 개선
- 실제 운영 데이터 전체 E2E / Deployment Smoke
- AI Core Extraction 최종 정량평가와 Copilot Document QA 지표의 명확한 분리 유지
- 접근성/전체 lint debt 정리
