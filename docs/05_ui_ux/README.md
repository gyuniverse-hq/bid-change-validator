# Frontend / UI·UX Baseline

> **상태: Current**  
> 기준: `develop` + Figma

이 문서는 Frontend 고도화 시 화면 흐름, API 연결, 실패/빈 상태를 일관되게 유지하기 위한 기준선입니다.

## 현재 Route

- `/notices`
- `/qualification`
- `/ask-back`
- `/evidence`
- `/evaluation`
- `/changes`
- `/company`

## 화면 흐름

```text
공고 찾기
→ 참가자격 검토
→ 확인 필요 응답
→ 근거 원문 대조
→ 평가 대응 참고
→ 변경 이력 확인
→ 회사 프로필 관리
```

02~06은 같은 Case/Notice Context 안에서 이동하는 Workspace 성격을 가집니다.

## Source of Truth

- 화면 IA / 디자인 방향: Figma
- 실제 지원 기능 / 상태: `develop` 코드와 Backend API
- Figma와 구현이 다르면 이유를 문서 또는 Decision Log에 남깁니다.

## 구현 원칙

- `SATISFIED / UNSATISFIED / UNKNOWN`과 전체 `eligible / ineligible / insufficient_data`를 혼동하지 않습니다.
- 최신 Analysis/Judgment와 연결된 데이터만 표시합니다.
- Loading / Error / Empty / Partial 상태를 명시적으로 처리합니다.
- Evidence는 사용자가 실제 원문으로 이동할 수 있어야 합니다.
- Evaluation 화면은 자격요건과 별도 평가기준을 혼동하지 않습니다.

## AI Copilot 확장 지점

Copilot은 기존 화면을 대체하기보다 Product Workspace를 연결하는 보조 인터페이스로 검토합니다.

예시:
- 현재 선택한 공고/Case Context를 사용
- 판정 이유 설명
- Evidence 이동
- Ask-back 유도
- 변경사항 설명

## Known Gaps

- 01~07 전체 Human Click E2E 완료 필요
- Figma visual QA / 접근성 정리
- Error/Empty 상태 통일
- Copilot Panel의 위치·모바일 대응 미확정

## 변경 체크리스트

- Figma와 차이 여부
- API Contract 영향
- Case/Version Context 유지 여부
- Loading/Error/Empty 상태
- Evidence deep link
- 접근성 및 키보드 사용성
- E2E 시나리오 갱신 여부
