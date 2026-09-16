# 선별 통합 전 보존 지점

2026-09-16. 사용자 승인 범위: 현재 미커밋 작업을 현재 브랜치에 커밋하고 push하는 단계까지. 이 기록은 구현 완료나 develop 병합 승인이 아니다.

- 보존 브랜치: `codex/ai-copilot-evaluation-ready`
- 보존 직전 로컬·원격 HEAD: `6af3b4fde3db775c73890b939beb3376ef4d2e01`
- 대상: 실제 내용 변경 39개와 미추적 코드·테스트·문서·합성 fixture 39개, 이 보존 기록. status만 수정으로 보이고 내용 diff가 없는 파일은 새 기능 변경으로 세지 않는다.
- 상태: **WIP / NOT_READY**. 과거 테스트 결과는 각 문서의 실행 조건에 한정된다. 이번 보존 커밋을 위해 제품·모델 검사를 다시 실행하지 않았다.
- 이번에 확인한 항목: 커밋 경로 목록, 새 합성 회사 fixture, 주요 비밀키/개인키/자격증명 URL 패턴, 원격 HEAD. 패턴 검사는 비밀정보 부재의 완전한 증명이 아니다.
- 제외하고 로컬에 유지: `.env*` 실제 환경 파일, `.ci-results/`의 로컬 DB 실행 자료·공고 복사본·로그·예산 장부·감사 근거, 가상환경과 node_modules. 강제 추가하지 않는다.
- 보존된 작업에는 공용 판정·추출·화면 변경도 있다. 이 브랜치 전체를 통합하지 말고 [50번 감사](50-ownership-audit-and-integration-plan.md)를 따른다.
- 사용자 전달 상태: #136은 develop 병합 완료, #145는 CI 확인 후 병합 예정. 새 작업을 시작할 때 실제 원격 상태와 최종 SHA를 다시 확인한다.
- 다음 권장 브랜치: `feature/copilot-two-job-integration`. #145까지 반영된 develop에서 분기하고, 현재 루트 작업 폴더를 유지한다. 이번 보존 단계에서는 생성하지 않는다.
- 범위: 변경 공고 대응과 입찰 참여 준비의 두 Job. #136 판정/추출, #145 회사 편집을 기준으로 기존 작업의 필요한 부분만 옮긴다. 기존 v0.4 저장 결과를 새 기준의 검증 결과로 간주하지 않는다.

로컬 복구 자료 위치:

- `.ci-results/ownership-audit/20260916T010826Z/`
- `.ci-results/root-migration/20260916T005313Z/`
- `.ci-results/branch-consolidation/20260916T004036Z/`
- `.ci-results/evaluation-ready/` — 기존 detached 복구 worktree, 새 작업용 아님.

현재 브랜치의 보존 커밋과 위 로컬 자료는 보존 범위가 다르다. GitHub에는 제외 자료가 올라가지 않는다.
