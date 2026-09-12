# 사업계획서 초안 — 프론트 연결 계약

작성: 2026-09-13 · 재현 · 프론트 담당자용

---

## 먼저: 지금 연결할 것이 없습니다

확인해 보니 **엔드포인트도 프론트 코드도 0건**입니다.

```
apps/api  business-plan 라우터           없음
apps/web  business-plan 관련 파일        없음
```

원래 엔드포인트가 `qualification_briefing_router` 안에 있었는데, 그 라우터가
Copilot 영역이라 이번 PR 에서 제외했습니다(PR #104 리뷰 의견). 그래서 지금 있는 것은
**라이브러리 함수와 그 출력 계약**뿐입니다.

이 문서는 "연결 방법"이 아니라 **"이 모양으로 연결해 주세요"** 입니다. 프론트가 먼저
화면을 잡아도 되도록 응답 계약을 확정해 두는 것이 목적입니다.

---

## 1. 제안하는 엔드포인트

팀 컨벤션(`APIRouter(prefix="/api/v1")`, `/preflight-cases/{case_id}/...`)에 맞췄습니다.

```
POST /api/v1/preflight-cases/{case_id}/business-plan-draft
```

### 요청

```jsonc
{
  "judgment_run_id": "uuid | null",   // 생략하면 그 사건의 최신 판정 실행
  "inputs": {
    "company_overview": "string",
    "proposal_goal": "string",
    "approach": "string",
    "differentiators": "string",
    "staffing": "string",
    "schedule": "string",
    "additional_notes": "string"
  }
}
```

일곱 칸 전부 선택입니다. 하나도 안 채우면 `EMPTY_INPUT` 이 돌아옵니다.

### ⚠️ 판정 내용은 클라이언트가 보내지 않습니다

초안의 근거가 되는 **검토 브리핑은 서버가 `judgment_run_id` 로 직접 만듭니다.**
프론트가 판정 텍스트를 만들어 보내는 형태로 설계하면 안 됩니다.

클라이언트가 근거를 실어 보내면 위조할 수 있고, 그러면 "참가 불가"인 공고에 대해
"전부 충족"이라고 적힌 초안을 만들어 낼 수 있습니다. 측정에서 확인한 것은
**사용자 입력을 통한 인젝션을 모델이 막는다**는 것이지, 위조된 근거를 걸러낸다는
뜻이 아닙니다 — 그건 모델이 알 수 없습니다.

---

## 2. 응답 계약

Pydantic `app/ai/narration/business_plan.py::BusinessPlanDraft` 가 원본입니다.

```ts
// apps/web/lib/business-plan-api.ts (신규)
export type BusinessPlanStatus =
  | 'OK'
  | 'MISSING_BRIEFING'        // 판정 결과가 비어 근거 없이 쓸 수 없음
  | 'EMPTY_INPUT'             // 담당자 입력이 하나도 없음
  | 'NARRATOR_UNAVAILABLE'    // OPENAI_API_KEY 미설정
  | 'FAILED';                 // 모델 호출 실패 또는 빈 응답

export type BusinessPlanWarning =
  | 'MISSING_REQUIRED_SECTION'
  | 'INVALID_SECTION_ORDER'
  | 'DRAFT_TOO_LONG'
  | 'DRAFT_TOO_SHORT'
  | 'QUALIFICATION_ITEM_MISMATCH'    // 판정 항목 표기가 브리핑과 다름
  | 'UNSUPPORTED_GENERIC_CHECKLIST'; // 입력에 없는 일반 체크리스트를 임의로 추가

export type BusinessPlanDraft = {
  text: string;                 // 한국어 Markdown, 고정 6장
  status: BusinessPlanStatus;
  disclaimer: string;           // 화면에 반드시 노출
  notice_id: string | null;
  source: {                     // 어떤 근거 위에서 쓴 초안인지
    notice_id: string | null;
    judgment_count: number;
    flagged_clause_count: number;   // 미달 + 확인 필요 요건 수
  };
  warnings: BusinessPlanWarning[];
};
```

> `warnings` 는 아직 작업 중인 브랜치(`feat/business-plan-draft`, Codex 세션)에만
> 있습니다. 필드 이름이 바뀔 수 있으니 머지 전에 한 번 더 맞춰 주세요.

### HTTP 상태

모델 호출이 실패해도 **200 + `status: 'FAILED'`** 로 돌려주는 것을 제안합니다.
초안 생성 실패는 서버 장애가 아니라 결과의 한 종류이고, 화면이 사유별로 다르게
안내해야 하기 때문입니다.

---

## 3. 화면이 해야 할 일

### status 별 안내 — 사유마다 담당자가 할 일이 다릅니다

| status | 화면 | 담당자가 할 일 |
|---|---|---|
| `OK` | 초안 + 면책 문구 | 검토 후 사용 |
| `EMPTY_INPUT` | 입력 폼으로 유도 | 회사 정보·수행 방안을 한 가지 이상 입력 |
| `NARRATOR_UNAVAILABLE` | 설정 안내 | 운영에 문의(사용자가 할 수 있는 게 없음) |
| `MISSING_BRIEFING` | 판정 화면으로 유도 | 자격요건 판정을 먼저 끝내기 |
| `FAILED` | 재시도 버튼 | 다시 시도 |

이 다섯을 "생성 실패" 하나로 묶지 말아 주세요. `EMPTY_INPUT` 은 사용자가 고칠 수
있고 `NARRATOR_UNAVAILABLE` 은 못 고칩니다.

### 면책 문구는 항상 노출

```
AI가 작성한 사업계획서 초안입니다. 제출 전에 담당자가 사실과 표현을 검토하세요.
```

`status` 가 `OK` 가 아니어도 `disclaimer` 는 채워져 옵니다. 화면이 분기하지 않도록
일부러 그렇게 했습니다.

### 초안 안의 `[담당자 확인 필요: ...]`

모델이 근거가 부족한 자리를 이 표시로 남깁니다. 측정에서 초안당 **최소 2개, 중앙
9개, 최대 27개** 나왔습니다. 이걸 그냥 본문에 섞어 두지 말고 **체크리스트로 뽑아
보여주면** 담당자가 바로 씁니다.

```
(대괄호 형태)  [담당자 확인 필요: 공장등록증 보유 여부]
(불릿 형태)    - 담당자 확인 필요: 공장등록증 보유 여부
```

**두 형태가 다 나옵니다.** 대괄호만 찾으면 표시를 13개 단 초안을 0개로 읽게 됩니다
(제 검사기가 실제로 그렇게 틀렸습니다). 정규식은 `담당자\s*확인\s*필요\s*:` 로.

### warnings 노출

`DRAFT_TOO_LONG` 은 사용자에게 안 보여도 됩니다(품질 신호). 다만
**`QUALIFICATION_ITEM_MISMATCH`** 는 초안의 참가자격 표기가 실제 판정과 어긋났다는
뜻이라, 담당자에게 "자격요건 절은 판정 화면과 대조해 주세요"라고 알려야 합니다.

### 문구는 `status-copy.ts` 에

새 문구를 컴포넌트에 직접 쓰지 말고 `apps/web/lib/status-copy.ts` 에 모아 주세요.
기존 규칙이기도 하고, **초안 안의 판정 문구가 화면과 같아야** 하기 때문입니다.
초안은 판정 상태를 이렇게 적습니다 — 화면과 글자까지 같습니다.

```
충족 · 미달 · 확인 필요            (JUDGMENT_STATUS_LABEL)
참가 가능 · 참가 불가 · 확인 필요   (OVERALL_STATUS_COPY)
```

같은 판정을 두 곳에서 다른 말로 부르면 사용자는 다른 결과로 읽습니다.

---

## 4. 초안이 어떻게 생겼는지

고정 6장 Markdown 입니다. 순서가 바뀌거나 빠지면 `warnings` 에 잡힙니다.

```
# 1. 사업 이해 및 제안 목표
# 2. 추진 전략 및 수행 방안
# 3. 조직·인력 및 역할
# 4. 일정 및 산출물 계획
# 5. 품질·위험 및 계약조건 대응
# 6. 자격요건·제출 전 확인사항
```

표를 많이 씁니다(Markdown table). 길이는 중앙값 약 4,000자, 최대 4,850자입니다.
**렌더러가 표와 인라인 코드(`` ` ``)를 지원해야 합니다.**

6장 실제 예:

```markdown
| 참가자격 항목 | 판정 상태 | 확인 및 대응 |
|---|---|---|
| 요건1 업종: 충족 | 충족 | 회사 정보상 industry.code=6315 이며 공고 요건과 일치한다. |
| 요건2 등록·인증: 확인 필요 | 확인 필요 | 직접 생산확인 증명서 제출 가능 여부를 확인한다. |
```

---

## 5. 백엔드가 만들어야 할 것 (누가 할지 미정)

라이브러리는 끝나 있고, 붙이는 일만 남았습니다.

```
1. 서비스   judgment_run_id -> 판정 결과 -> 브리핑 문자열
             조판 함수는 있음: quality_eval/business_plan/briefing_format.render_briefing
             (지금은 평가용으로 들어가 있는데, 제품에 붙일 때 위치를 옮겨야 합니다)
2. 라우터   POST /api/v1/preflight-cases/{case_id}/business-plan-draft
3. 나레이터 app.ai.providers.openai.OpenAINarrator 주입
```

생성 자체는 이미 동작합니다 — 초안 288편을 뽑아 측정을 마쳤습니다.

---

## 6. 프론트가 알아야 할 성능·한계

- **느립니다.** 초안 한 편에 10~20초입니다. 로딩 상태와 취소를 반드시 설계해
  주세요. 스트리밍은 지원하지 않습니다.
- **매번 다릅니다.** 같은 입력에도 문장이 달라집니다. 다만 측정에서 **96개 조합
  전부 판정 내용은 흔들리지 않았습니다** — 달라지는 것은 표현이지 사실이 아닙니다.
- **초안은 판정을 바꾸지 않습니다.** 288편 531행에서 판정을 숨기거나 왜곡한 사례가
  0건입니다. 그러니 화면에서 초안과 판정 결과를 나란히 놓아도 서로 어긋나지
  않습니다. 자세한 근거는 `10-business-plan-conformance.md` 에 있습니다.
- **적격 공고는 아직 검증 못 했습니다.** 골든셋에 참가 가능한 공고가 0건이라,
  "참가 가능"인 상황에서의 초안 품질은 측정된 바 없습니다.

---

## 질문 주실 곳

엔드포인트 경로·응답 필드는 제안이라 바꿔도 됩니다. 다만 두 가지는 지켜 주세요.

1. **브리핑을 클라이언트가 만들어 보내지 않기** — 근거 위조가 가능해집니다.
2. **status 다섯 가지를 뭉치지 않기** — 사유마다 담당자가 할 일이 다릅니다.
