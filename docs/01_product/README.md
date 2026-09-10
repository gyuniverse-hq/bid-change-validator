# Product 문서 안내

> **상태: Current**  
> 기준: `develop` + Figma 7개 화면

이 문서는 제품 고도화 전에 팀이 같은 사용자 흐름과 현재 범위를 보도록 하는 기준선입니다. 상세 구현은 각 기술 문서에서 관리합니다.

## 제품 목표

원공고를 기준으로 준비한 자격판정·필수서류·제출 준비 상태가 변경공고 이후에도 유효한지 확인하고, 변경된 조건과 원문 Evidence를 바탕으로 영향받은 항목만 다시 검증합니다.

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
| 05 | `/evaluation` | 평가 대응 참고 화면 |
| 06 | `/changes` | 변경공고 Diff / 영향 확인 |
| 07 | `/company` | 회사 Profile 관리 |

Figma는 화면 IA와 UX 방향의 Source of Truth이며, 실제 지원 기능과 상태는 `develop` 코드/API를 우선합니다.

## 제품 불변조건

- LLM이 최종 참가 가능/불가를 직접 결정하지 않습니다.
- `UNKNOWN`은 곧바로 사용자 질문 가능 상태가 아닙니다.
- 변경 전 결과를 덮어쓰지 않고 Version / Run 단위로 추적합니다.
- 결과에는 추적 가능한 Requirement / Evidence가 연결되어야 합니다.

## 현재 고도화 포인트

- 실제 Requirement Extraction 품질 평가
- meaningful 변경공고 Golden 확보
- Evaluation 전용 extraction / 제품 범위 확정
- 01~07 Human Click E2E 및 접근성/실패 상태 정리
- AI Copilot을 기존 Product API 위에 추가

## 변경 체크리스트

제품 흐름 또는 화면 범위를 변경하는 PR에서는 다음을 확인합니다.

- Figma와 실제 Route 영향
- Backend/API/DB/AI Contract 영향
- 기존 Case / Version / Judgment 흐름 호환성
- Golden/E2E 시나리오 수정 필요 여부
- 중요한 범위 변경의 Decision Log 기록 여부
