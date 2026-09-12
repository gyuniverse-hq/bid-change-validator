# AI Copilot v2 개선·평가 기록

이 폴더는 AI Copilot 2차 개선의 **재현 가능한 평가 원본(Source of Truth)** 을 보관합니다.

- Notion `챗봇 2차 개선 정리`: 진행판, 의사결정, 팀 공유용 요약
- 이 GitHub 폴더: 수치·실험 조건·실패 원인·전후 비교의 원본
- 채팅에서 생성되는 다운로드 파일: 전달 편의를 위한 임시 사본

## 기준선

- Repository: `gyuniverse-hq/bid-change-validator`
- E0 기준 commit: `993e5cf446e46c740503ec0840a5996d1f82dfe1`
- 개선 작업 branch: `feature/ai-copilot-e1-ux-baseline`
- Golden Set: `golden_fixtures_v02`, 공고 20건 / 현재 회사 상태 32 / 이전차수 입력 8 / 변경 비교 8

## 진행 순서

0. 기준선·평가 설계 고정 ✅
1. E0 실행 준비 확인 ✅
2. E0 판정 엔진 Actual ✅
3. E0 Copilot 기준선 측정 ✅
4. E0 실패 유형 분석 ✅
5. E1 UX·응답구조 개선 ✅
6. E1 동일 평가 재측정 ✅
7. E2 자연어 이해·대화 문맥 개선 ◀ 현재
8. E2 동일 평가 재측정
9. E3 근거 기반 RAG 설명 연결
10. E3·RAG·Prompt 성능 비교
11. 사용자 관점 Test Case
12. 최종 회귀·잠금 평가
13. README·발표·데모 정리

## 문서 인덱스

- [`e0-rule-engine-baseline.md`](./e0-rule-engine-baseline.md): 회사 Fixture 40개 / canonical 138행 판정 엔진 기준선
- [`e0-routing-baseline.md`](./e0-routing-baseline.md): 자유입력 100개 라우팅·작업 도달성 기준선
- [`e0-conversation-safety.md`](./e0-conversation-safety.md): I01~I20 대화·안전 시나리오와 E0 실패 유형
- [`e1-routing-remeasurement.md`](./e1-routing-remeasurement.md): E1 제한적 alias 적용 후 동일 100문항 재측정
- [`e1-evaluation-summary.md`](./e1-evaluation-summary.md): E0↔E1 전후 비교, I01~I20 재분류, E2로 넘기는 실패 목록

E2 구현 문서는 Semantic Router 연결과 재측정이 끝나는 시점에 `e2-*` 문서로 추가합니다.

## 수치 해석 원칙

서로 다른 수치를 하나의 `정확도`로 합치지 않습니다.

- `913/913`: Fixture 자료 정합성 검사
- `104/138 = 75.4%`: 독립 검토 전 draft 기대값과 고정 판정 코드의 canonical exact match
- `1/100 = 1.0%`: E0 자유입력 intent 정확 일치율
- `41/100 = 41.0%`: E1 제한적 alias를 적용한 정적 라우팅 재측정
- `5/20 → 9/20`: I01~I20 코드 계약 기준 완전 과업 성공 수 변화
- 사용자 업무 완료율 / RAG 답변 정확도 / 실제 API·DB E2E는 별도 지표로 기록

## E2 안전 경계

E2 Semantic Router는 자연어 의미를 `intent / subject / task / target / confidence`로 구조화하는 역할만 맡습니다.

- 참가자격 판정은 기존 deterministic judgment가 담당
- 저장·반영·재검증은 기존 proposal → 명시 확인 → confirm 경계를 유지
- provider 없음/실패/낮은 confidence는 `UNKNOWN`으로 fail-closed
- 회사 프로필의 민감한 상세 사실을 semantic routing 입력으로 넘기지 않음
- 문서 QA와 생성형 설명은 E3에서 별도 근거성 평가

## PR 운영

개선 중간 PR은 만들지 않습니다. E1→E2→E3와 최종 회귀검증이 끝난 뒤 하나의 최종 PR로 `develop`에 제안합니다.
