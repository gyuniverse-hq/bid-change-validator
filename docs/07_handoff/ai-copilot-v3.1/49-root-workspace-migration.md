# 최신 작업을 저장소 루트로 이관

2026-09-16. 사용자가 원하는 위치는 별도 worktree가 아닌 **기존 저장소 루트**다. 47번의 별도 폴더 사용 제안을 대체한다.

## 현재 작업 위치

- 폴더: `E:/dev/02_TeamProjects/bid-change-validator`
- 브랜치: `codex/ai-copilot-evaluation-ready`
- HEAD: `6af3b4f` 그대로. 최신 미커밋 코드·문서·테스트를 루트에 복원했다.
- 현재 Codex 대화의 cwd는 이미 루트다. 작업 위치를 맞추기 위해 새 대화를 만들 필요가 없다. 앱의 브랜치 표시는 갱신 시 위 브랜치와 일치해야 한다.
- 새 채팅도 루트에서 시작하고 [48번 인계](48-two-job-new-chat-handoff.md)를 읽는다. 초기 제품 범위는 변경 공고 대응·입찰 참여 준비 두 Job이며 아직 선택형 구현 완료가 아니다.

## 보존과 복사

- feature 브랜치와 과거 커밋은 삭제하지 않았다. 원래 미커밋 문서 4개는 ZIP·patch와 별도 stash `8e493c8c208b6396313d393ecb81c97323afa9cc`에 보존했다. 기존 stash 2개도 유지했다. 이 stash를 최신 루트에 무조건 적용하지 않는다.
- 기존 `.ci-results/evaluation-ready`는 **detached HEAD의 복구용 worktree**로 유지한다. 기존 미커밋 파일도 남아 있다. 이제 여기서 서버나 새 작업을 시작하지 않는다.
- 새 백업: `.ci-results/root-migration/20260916T005313Z/`. 원래 문서 4개, 최신 변경 76개, binary patch, Git 상태, HEAD와 파일 해시를 기록했다. 원래 feature의 과거 문서·증거는 이 백업의 `feature-handoff/`에도 보존했다.
- 최신 추적 파일 698개와 변경 파일을 원본과 대조했다. checkout 줄바꿈 차이는 원본 바이트로 맞췄다. 이관 후 아래의 이관 지원 수정·인계 문서 갱신은 별도 변경이다.
- 기존 worktree의 `.ci-results`에서 로컬 자료·로그·인덱스·계정·비용 기록 **2741개 파일, 315868342바이트**를 루트 `.ci-results`로 복사하고 해시를 확인했다. 기존 루트 자료와 이름 충돌은 없었다.
- 과거 `pytest-tmp` 폴더 44개는 재생성 가능한 임시 자료이며 접근 제한 때문에 복사에서 제외했다. 기존 위치에서 삭제하지 않았다. DB 자체는 파일 복사나 재생성하지 않았다.
- 계정·API 키·원문·모델 trace는 Git 산출물로 추가하지 않는다. `.env`는 기존 루트 파일을 유지했다.

## 로컬 실행 경로

기존 API·웹 프로세스만 식별하여 종료하고 API 18125와 웹 5181을 루트에서 다시 실행했다. 격리 검사 전용 웹 5179는 중지 상태로 두며 필요한 검사 때만 시작한다. API 재시작으로 메모리 대화는 초기화될 수 있지만 DB 답변·판정은 유지된다.

```powershell
.\.venv-copilot-v31\Scripts\python.exe -X utf8 scripts/local_copilot_evaluation.py serve --model-env .env
```

이미 실행 중이면 위 명령을 중복 실행하지 않는다. 로그는 `.ci-results/user-evaluation/root-api.log`, `root-api-error.log`, `root-web.log`, `root-web-error.log`다. 모델 호출은 이관 검사에서 하지 않는다.

DB 컨테이너는 `bid-copilot-evaluation-db`, ID `db1c54d1eca32c90b50685f9d8afe449e4a9343fdd18b35d3c686f183a0cdd81`로 그대로다. 변경할 수 없는 기존 workspace label을 수용하기 위해 로컬 `workspace-migration.json`의 이전/현재 경로·컨테이너 이름·정확한 ID가 모두 일치할 때만 허용하는 검사를 실행 도구에 추가했다. 소유권 label, 이미지, localhost 바인딩, 저장소, 실제 DB 식별 검사는 유지한다. 다른 컨테이너나 임의 이전 경로는 허용하지 않는다.

## 확인 범위

- 이관 허용/거부 단위 검사: 1 passed, 7 deselected. 잘못된 경로·컨테이너·영수증·깨진 JSON을 거절한다. pytest cache 쓰기 권한 경고 1건은 검사 실패가 아니다.
- 원래 J13·네 초기 회사·판정·문서 기준·예약 사용자 사례 읽기 전용 검사 PASS.
- 루트 서버 로그인 화면 HTTP 200, 비로그인 API 조회 HTTP 401, 기존 DB ID 일치 확인.
- 로그인·사례 권한·문서 조회 검사 결과는 `.ci-results/user-evaluation/access-verification.json`의 이번 실행 기록을 따른다. 이전 기록만으로 현재 성공이라고 판단하지 않는다.
- 제품 모델 검증을 다시 실행하지 않았다. 45번의 NOT_READY, 실패·미실행 상태는 유지한다. 폴더 이관은 제품 품질 완료를 뜻하지 않는다.

commit·push·merge·배포·공용 DB 변경은 수행하지 않았다. 다음 제품 작업은 48번의 두 Job·여섯 질문 계약과 선택 UI 구현이다.
