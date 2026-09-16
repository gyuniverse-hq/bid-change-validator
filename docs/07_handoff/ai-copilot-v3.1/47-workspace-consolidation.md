# 작업 폴더 통일과 과거 문서 이관

> **후속 변경:** 사용자는 별도 폴더가 아닌 저장소 루트를 작업 위치로 지정했다. 아래는 첫 문서 이관 당시 기록이며, 실제 작업 위치·브랜치는 [49번 루트 이관 기록](49-root-workspace-migration.md)이 우선한다.

2026-09-16. **문서 이관·기존 변경 백업 완료. Codex 현재 대화의 연결 폴더 전환은 별도이며 미완료.**

## 앞으로 작업할 위치

- 브랜치: `codex/ai-copilot-evaluation-ready`
- 폴더: `E:/dev/02_TeamProjects/bid-change-validator/.ci-results/evaluation-ready`
- 현재 결과: [45번](45-pipeline-result-and-next-step.md). 다음 Job 선택형 설계: [46번](46-guided-job-ui-transition.md).
- 전체 순서: ① 감사 → ② 연결 → ③ 기본 검사 → **④ 통합 검증 중간 정리·작업 위치 통일** → Job 선택형 구현·검증 → ⑤ 사용자 평가 → ⑥ 최종 통합 판단.

## 완료한 보존·이관

- 원래 폴더의 미커밋 변경 4개와 최신 폴더의 기존 변경 63개를 ZIP·binary patch·HEAD·상태·SHA256 목록으로 백업했다. 무시되는 DB·자격증명·의존성 전체를 백업한 것은 아니다.
- 백업은 원래 루트의 `.ci-results/branch-consolidation/20260916T004036Z/`이며 Git 제외 대상이다. ZIP CRC와 모든 파일 해시를 대조했다.
- 과거 문서 05~15 총 11개를 복사했다. 08·12의 미커밋 수정과 미추적 13·15를 포함한다. 안내 머리말을 제외한 본문 바이트가 원본과 일치한다.
- 원래 폴더의 문서·브랜치와 최신 폴더의 기존 코드·문서는 덮어쓰거나 삭제하지 않았다.
- 코드 병합·commit·push·DB 변경·추가 모델 검사는 수행하지 않았다. 문서는 현재 작업 폴더에 아직 미커밋 상태다.

## 과거 근거의 위치

아래는 경로 존재 확인이다. 과거 검사의 재실행·내용 재검증을 뜻하지 않는다. 원문 trace와 Golden 자료를 무심코 Git 산출물에 추가하지 않도록 근거 파일은 기존 위치에 보존했다. NOT_FOUND는 현재 위치에서 확인하지 못한 상태이며 복구·검증 완료로 보고하지 않는다.

| 원래 저장소 기준 경로 | 확인 |
|---|---|
| `docs/07_handoff/ai-copilot-v3.1/db-evidence` | PRESENT (7 files) |
| `docs/07_handoff/ai-copilot-v3.1/review-evidence` | PRESENT (80 files) |
| `docs/07_handoff/ai-copilot-v3.1/q004-evidence` | PRESENT (49 files) |
| `docs/07_handoff/ai-copilot-v3.1/flow-evidence` | PRESENT (56 files) |
| `docs/07_handoff/ai-copilot-v3.1/golden-attachment-evidence` | PRESENT (60 files) |
| `docs/07_handoff/ai-copilot-v3.1/workflow-completion-evidence` | PRESENT (55 files) |
| `.ci-results/golden-attachment-20260914T070628Z` | PRESENT |
| `.ci-results/develop-review-20260914` | PRESENT |
| `.ci-results/integration-analysis-20260914T172817Z` | PRESENT |
| `.ci-results/copilot-db-20260914T081158Z` | PRESENT |
| `.ci-results/copilot-db-20260914T081310Z` | PRESENT |
| `.ci-results/q006-20260914T081350Z` | PRESENT |

## Codex 우측 브랜치 표시

이 대화의 연결 폴더는 원래 루트이고 그 HEAD는 `feature/ai-copilot-user-test-hardening`이다. 실제 구현 명령은 위 별도 worktree를 대상으로 실행했으므로 표시와 실제 작업 위치가 달랐다. VS Code에서 새 폴더를 열어도 이 대화의 연결 폴더는 자동 변경되지 않는다.

현재 제공된 도구로 이 대화 자체를 지정한 기존 worktree로 재연결할 수는 없다. 앱에서 대상 폴더를 프로젝트로 선택해 그 폴더에서 작업을 이어가야 한다. 기존 worktree에서 이미 사용하는 브랜치를 원래 폴더에 강제 checkout하지 않는다. Codex의 일반 Handoff는 Git 상태를 이동하므로, 사용자 정의 worktree와 무시되는 로컬 DB·자료를 그대로 쓰는 이번 전환과 동일하게 취급하지 않는다.

새 작업 위치에서 이어갈 때: 이 문서와 45·46을 읽고 기존 미커밋 변경을 보존한다. 현재 NOT_READY 및 실패·미실행 결과를 유지한다. Job 질문 카탈로그는 아직 제안 상태이며 main/develop 수정·공용 DB 변경·merge·배포를 하지 않는다.
