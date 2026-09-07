# LLM / RAG 패키지 (`app.ai`)

> 작성 2026-09-08 · 담당 김재현, 이홍규
> 별도 PoC 저장소(`bid-change-validator-llm-rag`)의 기능을 이 저장소로 옮기고,
> DB 연결 전 단계에서 동작하는 데모까지 연결한 상태입니다.

## 이 패키지의 경계

`app.ai`는 **순수 라이브러리**입니다. ORM·파일 저장소·HTTP를 모르고, 기본 경로에서
네트워크 호출이 하나도 없습니다. 모델 호출은 전부 **주입**받습니다.

```
Backend 소유                          LLM/RAG 소유
routers/ services/ models.py          app/ai/**
       │                                   │
       └─ 문서 텍스트·블록 ───────────────▶ chunking → extraction → judgment
                                            clause_review / followup / assist
       ◀─ Requirement / Judgment / ClauseFinding (pydantic 계약)
```

이 경계 덕분에 오늘 작업 내내 백엔드 소유 파일을 **한 줄도 수정하지 않았습니다.**
수정한 공용 파일은 `app/ai/contracts.py`(optional 필드 3개 추가)뿐이고, 이는
`docs/contracts/backend-llm.md`가 권장하는 additive-optional 방식입니다.

## 절대 원칙

이 패키지 전체가 아래 네 가지를 지킵니다. 코드를 고칠 때 이것부터 확인하세요.

1. **판정은 코드가 한다.** LLM은 (1) 산문 → 정형 필드 변환, (2) 코드가 확정한 결과를
   문장으로 풀어쓰기, 이 둘만 합니다. 충족/미충족을 모델에게 묻지 않습니다.
2. **근거가 없으면 판정하지 않는다.** 기준값을 못 읽으면 옛 상수로 폴백하지 않고
   "확인 불가"로 남깁니다. 틀린 답을 확신 있게 내놓는 것이 가장 나쁜 실패입니다.
3. **"모름"과 "없음"을 구분한다.** 프로필에 실적 키가 없는 것(모름)과 빈 목록인 것
   (없다고 명시)은 판정이 달라야 합니다. `ProfileView.has()`가 그 구분입니다.
4. **모든 판정에 근거가 따라붙는다.** `Judgment.reason`, `ClauseFinding.standard`가
   화면에 그대로 나갑니다.

## 구조

```
app/ai/
├── contracts.py              QualificationRequirement / Evidence / Judgment
├── profile.py                CompanyProfileSnapshot + ProfileView       ← 오늘 추가
├── judgment.py               canonical 8종 요건 판정기                   ← 오늘 추가
├── extensions.py             공고별 추가 항목(SW기술자 등급, 계열사 여부)  ← 오늘 추가
├── followup.py               되묻기 답변 → 프로필 갱신안                 ← 오늘 추가
├── notice_requirements.py    공고 API 필드 → 요건 + 가격정보             ← 오늘 추가
├── summary.py                공고 요약 / 판정 결과 브리핑                ← 오늘 추가
├── assist.py                 막연한 질문 응대 도우미                     ← 오늘 추가
├── clause_review/            확인 필요 계약조항 탐지                     ← 오늘 추가
│   ├── lexicon.py            어휘 부품 사전
│   ├── pattern_match.py      경로 B — 과업범위 모호 (LLM 불필요)
│   ├── standard_diff.py      경로 A — 표준 대조 (LLM 불필요)
│   ├── embedding_fallback.py 경로 A 2차 — 임베딩 검색 + 원문 인용
│   └── standards/            예규 인덱싱 + 기준값 추출
├── providers/
│   ├── openai.py             OpenAIStructuredExtractor / OpenAINarrator
│   └── embeddings.py         OpenAIEmbedder + n-gram 폴백               ← 오늘 추가
├── analysis_pipeline.py      문서 → 요건 추출 (기존, PR #44)
├── chunking.py               의미 단위 청킹 (기존)
└── normalization/            수치 정규화 (기존, `extract_values` 오늘 보강)

app/demo/                     DB 연결 전 커넥터 데모                      ← 오늘 추가
├── connectors.py             NoticeSource / ProfileStore / IndustryCatalog / PriceBoard
├── pipeline.py               공고 → 요건 → 판정 → 조항검토 → 요약 조립
├── report.py                 리포트 텍스트 렌더러
└── api.py                    FastAPI 데모 앱 (main.py 미수정)
```

`app.ai` 5,919줄 + `app.demo` 988줄. 테스트 **184개 통과**(신규 139개).

## 실행

```bash
# 1) 표준 예규 인덱스 생성 (최초 1회, 예규 개정 시 재실행)
python scripts/build_standard_clauses.py

# 2) CLI 데모
python scripts/run_eligibility_demo.py --list
python scripts/run_eligibility_demo.py R26BK01705963 \
    --profile DEMO_적격업체 \
    --rfp data/demo/rfp/DEMO_공고_스마트도시플랫폼.txt \
    --extract --summary --narrative --assist "그래서 우리 들어갈 수 있어?"

# 3) HTTP 데모 (프론트 연동용, 실제 API와 별도 포트)
uvicorn apps.api.app.demo.api:app --reload --port 8100   # /docs
```

`--live`를 붙이면 나라장터 API를 실제 호출하고 응답을 `data/demo/notices/`에 캐시합니다.
키가 없으면 조항 검토·가격·업종 표시는 그대로 동작하고 LLM 경로만 사유를 밝히며 비웁니다.

### 환경변수

`.env`(루트, git 추적 안 됨)에 넣습니다. **`app/ai/` 안에 `ai.env`를 만들지 마세요** —
`.gitignore`의 `.env` / `.env.*` 규칙에 걸리지 않아 키가 그대로 커밋됩니다.

```
G2B_SERVICE_KEY=...        # 나라장터 (URL 인코딩된 상태로 저장, 코드가 unquote)
OPENAI_API_KEY=...
OPENAI_MODEL_DEFAULT=...   # 산문·추출용
OPENAI_EMBED_MODEL=...     # 임베딩 (미설정 시 n-gram 폴백)
```

값을 따옴표로 감싸도 되지만, 감쌌다면 읽는 쪽이 벗겨야 합니다. `pydantic-settings`는
자동으로 벗기고, CLI의 `_load_env`도 이제 벗깁니다.

## 오늘 실측한 것 (실제 공고 300건)

용역·공사·물품 각 100건을 나라장터 API로 받아 분석했습니다.

| | 건수 | 비율 |
|---|---|---|
| API 필드만으로 판정 가능한 요건이 나온 공고 | 2 | 0.7% |
| 업종제한 있으나 **허용업종 미제공** | 152 | 51% |
| 지역제한 있으나 **허용지역 미제공** | 69 | 23% |
| `lcnsLmtNm`(면허제한) / `permsnIndstrytyList`(허용업종) 수신 | 0 | 0% |

**결론: 공고 목록 API만으로는 참가자격을 판정할 수 없습니다.** 절반이 업종제한
공고인데 어느 업종인지 안 주고, 면허제한 필드는 300건 중 0건입니다. 구체적 참가자격은
공고문(첨부)에만 있으므로 **문서 추출 경로가 필수**입니다.

그래서 `build_notice_requirements()`는 값이 있으면 요건으로, **플래그만 있으면
진단(diagnostic)으로** 처리합니다. 기준을 모르는 채 판정하지 않기 위해서입니다.

## 오늘 찾아 고친 것

- **`rgnLmtBidLocplcJdgmBssNm`을 지역명으로 오독** (제가 넣은 버그). 실제 값은
  `본사또는참여지사소재지`로 **판단 기준**이지 지역이 아닙니다. 회사 소재지와 대조하면
  300건 중 69건(23%)에 거짓 미충족이 났을 것입니다. 진단으로 변경했습니다.
- **`재작년`이 `작년`으로 파싱** (PoC 버그). dict 순회 중 `"작년" in "재작년"`이 먼저
  걸려 실적 완료연도가 1년 늦게 기록됐습니다. 긴 키부터 검사하도록 수정.
- **`ISO 9001` 환각이 통과** (PoC 버그). 명칭 대조가 `any(토큰)`이라 답변에 `ISO 27001`만
  있어도 `ISO` 토큰 하나로 통과했습니다. 숫자를 포함한 명칭은 숫자 토큰이 일치해야
  하도록 변경(`ISO/IEC 27001` ↔ `ISO 27001`은 여전히 통과).
- **임베딩 유사도 문턱 `0.22`가 폴백에 안 맞음.** OpenAI 임베딩 기준으로 튜닝된 값인데,
  n-gram 폴백에서는 관련 조항 0.096~0.364 / 무관 최대 0.162로 **범위가 겹칩니다.**
  실제 임베딩일 때만 문턱을 쓰고 폴백일 땐 상위 K개 순위로만 거르도록 변경.
- **`extract_values` 포팅 누락.** 조항에서 수치를 뽑는 경로 A의 핵심 함수가
  `normalization/numbers.py`에 안 들어와 있었습니다.
- **`.env` 따옴표 미제거.** CLI 파서가 `'sk-proj...'`를 따옴표째 전송해 401·403이
  났습니다. 키 문제로 오진했다가 바로잡았습니다.

## 팀에 넘길 것

**1. HWPML 지원이 백엔드 추출기에 없습니다.** 법제처가 계약예규를 확장자만 `.hwp`인
XML(HWPML)로 배포합니다. `app/services/document_extraction.py`는 PDF·HWP(OLE2)·HWPX·DOCX만
다뤄 셋 다 거부했습니다. 예규 인덱싱은 `scripts/build_standard_clauses.py` 안에 임시
리더를 넣어 해결했지만, **나라장터 공고 첨부에도 같은 형식이 오면 텍스트 추출이 실패하고
그 공고는 분석 자체가 안 됩니다.** 백엔드 추출기에 분기 추가가 필요합니다.

**2. `docker-compose.yml`에 `OPENAI_API_KEY`가 전달되지 않습니다.** 로컬 CLI/데모는
되지만 컨테이너 안에는 키가 없습니다. `api`·`notice-poller` 서비스에 한 줄 추가 필요.

**3. DB 이음새.** `app/demo/connectors.py`의 `ProfileStore` / `IndustryCatalog`가
프로토콜입니다. 테이블이 확정되면 `FileProfileStore` 자리에 SQLAlchemy 구현을 끼우면
파이프라인은 그대로입니다. `app/demo/pipeline.py`가 그대로
`app/services/analysis.py`가 될 자리이며, 그때 `requirements` / `evidence` /
`judgments` / `clause_findings` 테이블 마이그레이션이 필요합니다.

## 아직 안 한 것

- `monitor/align.py`, `monitor/rejudge.py` — 변경공고 조항 정렬·재판정 (레포 이름값 기능)
- `goldenset/` — 평가 하네스
- 사업계획서 초안 생성 (다음 작업)

사업계획서 생성은 오늘 만든 `NoticeFacts`(공고 정보) · `ProfileView`(회사 정보) ·
`EligibilityReport`(판정 결과)를 그대로 입력으로 쓰면 됩니다.

## 데모 데이터 주의

`data/demo/profiles/*.json`의 회사 3곳과 `data/demo/rfp/`의 공고문은 **전부 가상**이며
`_demo: true`로 표시돼 있습니다. 여기서 나온 판정 결과를 실제 업체에 대한 것으로
제시하지 마세요. 테스트가 이 표시를 강제합니다(`test_demo_profiles_are_all_marked_as_fictional`).
