# 전용 로컬 사용자 평가 환경

2026-09-15 후속: 실제 사용자가 확인 질문 오류를 보고하여 평가가 시작됐다. 코드 보완과 현재 검증 상태는 [21번 보고서](21-user-evaluation-check-scope-fix.md)를 우선한다. 아래 NOT_RUN은 최초 환경 준비 시점 기록이다.

작성: 2026-09-15 KST. 시작 코드 `7926c36`, 작업 브랜치 `codex/ai-copilot-evaluation-ready`.

## 전체 순서와 현재 위치

| 단계 | 상태 |
|---|---|
| 1 감사 → 2 연결 → 3 기본 검사 | 기존 수행 기록 유지 |
| 4 통합 검증 | Q-007 지정 두 장문 질문 PASS. Q-009 원문 관계는 기관 확인 대기 |
| **5 평가 환경 준비** | **전용 DB·유지되는 계정·원문 파일·웹/API 연결 검증 완료** |
| **5 실제 사용자 평가 — 다음** | **NOT_RUN. 설명·원문·확인 질문·합성 입력 동작부터 평가 가능** |
| 6 최종 통합 판단 | NOT_RUN. 최신 develop 재비교·merge·배포 미실행 |

환경 준비 완료를 Q-009 정답 확정이나 사람 평가 완료로 취급하지 않는다. 전체 참가 가능 여부의 정답 평가에는 기관 해석과 합성 보충값 검수가 여전히 필요하다.

## 접속과 평가 범위

- 웹: `http://127.0.0.1:5181/login`
- API: `http://127.0.0.1:18125`
- 전용 DB: `bid-copilot-evaluation-db`, PostgreSQL 16, `127.0.0.1:54560/copilot_evaluation` (이 PC의 현재 할당 포트).
- 자동 검사 DB `bid-copilot-test-db`와 별개다. 기존 8000/3000 개발 서비스·공용 DB·원래 checkout을 변경하지 않았다.
- 로그인: `eval-j13`, `eval-j14`, `eval-j15`, `eval-j16`. 각각 일반 USER 권한이며 다른 회사 사례에 접근할 수 없다.
- 비밀번호와 직접 공고 링크는 **로컬 전용** `.ci-results/user-evaluation/시작안내.private.md`, 원본 계정 파일은 `accounts.private.json`이다. 원문·계정·응답·예산 파일은 Git에서 제외한다.
- 회사 이름에 합성·검수대기를 표시했다. 공고번호는 기존 replay adapter의 `LOCAL-SNAPSHOT-*`이며, 대상은 R26BK01684863의 000→001 과거 변경 사례다. 원본 snapshot은 수정하지 않았다.

| 계정 | 초기 업종 | 초기 개별 운반 결과 | 평가 시 다룰 입력 |
|---|---|---|---|
| eval-j13 | 1257 + 1227 | SATISFIED | 등록 보유 경로 |
| eval-j14 | 1257 + 1224 | UNKNOWN | 합성 시나리오로 직접 운반 법적 허가 조건 false를 명시 입력하는 경로 |
| eval-j15 | 1257 | UNKNOWN | 합성 시나리오로 처분 허가·직접 운반 법적 조건·필요 장비 모두 true를 명시 입력하는 경로 |
| eval-j16 | 1257 | UNKNOWN | 예외 미확인 상태를 유지하는 경로 |

J14/J15의 세부 보충값을 미리 답변 완료로 저장하지 않았다. 입력 전에는 둘 다 UNKNOWN인 것이 맞다. 보충값은 실제 회사 사실·증빙이 아니라 검수할 합성 시나리오다. 모든 프로필은 전북 소재이고 현장 방문 답변은 미확인이다. 기준일은 Golden의 2026-08-18로 고정했으며, 새로 실행하는 판정의 기준일도 평가자가 기록해야 한다.

현재 화면의 전체 **참가 불가**는 합성 프로필에서 등록·인증 정보가 비어 있는 별도 요건의 미달이 반영된 결과다. 1224→1227 때문에 전체 판정이 반전했다고 설명하지 않는다. Q-009 업종군 관계는 분석 진단에 보류로 남는다. 화면의 PARTIAL 안내가 ‘첨부 일부만 읽음’처럼 일반적으로 표시되는 점은 해석 미확정과 구분해 평가 기록에 남긴다. 모든 원문 파일이 없다는 뜻은 아니다.

## 실행기와 보존 방식

`scripts/local_copilot_evaluation.py`는 로컬 Docker socket, 컨테이너 소유 label과 작업 폴더, 이미지, 저장 볼륨, loopback 포트, 실제 DB 이름·사용자·버전을 확인한다. 호출 환경의 DB URL을 사용하지 않고 dotenv를 끈다. `init`은 비어 있는 전용 DB에만 적재하며, manifest가 있으면 자료 hash·DB 신원을 확인하고 기존 계정·답변·판정을 보존한다. manifest 없는 기존 데이터가 있으면 덮어쓰지 않고 중단한다. 삭제·초기화 명령은 없다.

이미 확인한 HWP/PDF와 나라장터 공개 과업지시서 HWPX를 hash로 대조했다. 5개 고유 파일을 8개 문서 row에 연결하여 실제 `/content` 다운로드를 모두 검증했다. 공용 저장소 경로나 계정은 복사하지 않았다. 기존 snapshot의 텍스트·분석과 원본은 그대로 보존한다.

웹 실행기는 현재 앱을 로컬 API에 연결하며 프로젝트 `.env`·hosting 설정을 수정하지 않는다. 평가 API는 Copilot 3.1 요청만 받는다. 모델 키는 `--model-env` 파일의 OPENAI_API_KEY만 메모리로 읽고, 모델 어댑터에 직접 전달한다. 일반 환경변수의 키는 비워 두므로 다른 모델 경로가 이 키를 재사용하지 않는다.

실모델은 사용자 동의를 켠 요청에서만 사용한다. 모델은 `api.openai.com / gpt-5.6-luna`, 요청당 $0.25, 이 평가 환경 누적 $1의 **추정 예약 한도**다. 개발 runner와 같은 토큰 단가 가정으로 호출 전 $0.0068을 예약하고 실패해도 반환하지 않는다. 제공자 청구액을 보장하는 계정 단위 하드 캡은 아니다. 예산 파일은 재시작·재초기화로 초기화되지 않으며 총 승인 $10 중 일부로 운영한다. 이번 브라우저 검증은 2호출 성공, 예약 $0.0136이었다.

임베딩 호출은 별도 비용 우회를 막기 위해 이 환경에서 끈다. 원문 전체 읽기·기존 lexical 검색 범위를 사용하며, 임베딩 검색 품질을 검증했다고 주장하지 않는다. API는 한 프로세스로 실행하고 대화 문맥은 프로세스 메모리에 있어 API 재시작 시 초기화된다. DB에 저장한 답변·판정·계정과 예산 기록은 유지된다.

### 다시 실행할 때

이미 실행 중인 서버에 같은 명령을 중복 실행하지 않는다. 포트가 사용 중이면 중단하며 임의의 프로세스를 종료하지 않는다. 아래 명령은 별도 worktree 루트에서 실행한다. 이 PC의 Python은 원래 저장소의 `.venv-copilot-v31/Scripts/python.exe`다.

```powershell
# 최초 준비 또는 보존 확인; 기존 manifest가 있으면 덮어쓰지 않는다.
python scripts/local_copilot_evaluation.py init --snapshot .ci-results/namwon-source-reextracted.json --bundle C:/Users/HGLEE/Downloads/golden_fixtures_v02.zip

# 파일 연결; 승인된 hash와 일치하는 로컬 원본만 사용한다.
python scripts/local_copilot_evaluation.py documents --files .ci-results/namwon-originals .ci-results/q009-source-review .ci-results/user-evaluation

# 각각 별도 터미널. --model-env 생략 시 모델은 사용하지 않는다.
python scripts/local_copilot_evaluation.py serve --model-env E:/dev/02_TeamProjects/bid-change-validator/.env
node scripts/local_copilot_evaluation_web.mjs

# 실제 로그인·CORS·회사 경계·원본 다운로드 확인
python scripts/local_copilot_evaluation.py verify
```

모든 원문·비밀번호·로그가 있어야 이 PC에서 재현된다. 이 자료를 GitHub에서 자동으로 받을 수 있다고 가정하지 않는다.

## 이번 실행 근거

별도 worktree `.ci-results/` 아래의 실제 실행 파일이다.

| 검사 | 결과 | 근거 |
|---|---|---|
| 전용 DB 최초 적재 | 계정 4, 사례 4, v1/v2 판정, Q-009 보류 유지 | `user-evaluation/manifest.json` |
| 실제 HTTP 인증·회사 경계·CORS | PASS, 4계정 자기 사례 200/다른 사례 403, 비로그인 401, 사전 요청 200 | `user-evaluation/access-verification.json` |
| 원본 다운로드 | 8개 응답 200·SHA 일치 | `user-evaluation/document-files.json`, verify 실행 |
| Chrome 로그인→회사→공고→동의→실모델 요약 | PASS, 모델 task_status PASS, JS 오류·예상 밖 API 오류 없음 | `user-evaluation/browser-2026-09-14T20-40-29-553Z/browser-verification.json`, `browser.png` |
| 초기화 재실행 보존 | PASS, 계정·manifest·사용한 예산 hash 불변 | `user-evaluation/reinit-verification.json` |
| 예산 영속·실패 예약·동시 호출·임베딩 우회 방어 포함 오프라인 회귀 | 413 PASS | `copilot-v31-20260914T204132Z/tests.xml` |
| 사람 평가·모든 자유 질문·기관 답변·배포 | NOT_RUN | 수행하지 않음 |

실모델 요약은 전북 소재·인원 8명·1257/1227과 미등록 인증을 설명하고 미등록을 실제 미보유로 단정하지 않았다. 과거 Q-007 장문 검증을 이번 실행에서 반복한 것은 아니다. 프론트 제품 코드는 변경하지 않았으며 이번에는 웹 build를 다시 실행하지 않았다.

초기 검증 실패도 보존했다. Playwright 모듈 형식 오류는 브라우저 실행 전에 끝났다. 첫 브라우저 시도는 React 준비 전 입력이 초기화되어 로그인에 실패했다. 다음 시도는 평가 실행기의 CORS OPTIONS 본문 처리 오류로 실패했고 모델 호출은 없었다. 준비 상태 대기와 POST 전용 본문 검사를 적용한 뒤 최종 브라우저 검사를 통과했다. 기존 개발 서버는 종료하지 않았다.

## 사용자가 이어서 할 일

1. 로컬 시작 안내의 eval-j13으로 로그인하고 직접 공고 링크를 연다.
2. 17번 U02/U03/U06의 질문·답변 이해도를 먼저 기록한다. 의미 처리와 원문 전송 동의는 원하는 범위에서 켠다.
3. J14/J15/J16으로 계정을 바꿔 추가 질문·명시 확인 전 미저장·예외 미확인 동작을 평가한다. 합성 보충값임을 기록한다.
4. 미리 제시하지 않은 자유 질문과 어색한 답변을 `.ci-results/user-evaluation/평가기록.md`에 남긴다. 개발자가 대신 실행한 결과를 사람 평가 결과로 채우지 않는다.
5. Q-009 기관 해석과 프로필 기대값 확정 후 전체 판정 정답 검증을 이어간다. 그 뒤 최신 develop 차이와 통합 여부를 판단한다.
