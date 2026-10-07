# 함정과 요령

근거 표시: `[사실: 출처]` · `[추론]` · `[예선 실행]`(예선에서 겪고 기록함) · `[문서만]` · `[미확인]`. 출처 경로는 예선 저장소 루트 기준이다. 각 항목은 증상 → 원인 → 대응 순이다.

## 1. 이 폴더의 도구와 작업 흐름

- **비밀값 검사가 새 파일을 못 본다.** 증상: 방금 쓴 문서에 경로가 있는데 `python3 scripts/secret_scan.py`가 0건이다. 원인: 전체 모드는 `git ls-files`(추적 파일)만, 범위 모드는 커밋된 diff만 읽는다. 대응: 새 파일은 `git add <파일>` 뒤에 전체 모드로 보거나, 커밋 뒤 범위 모드(`main..HEAD`)로 본다. 확인: 걸린 곳 0과 종료 0.
- **문서에 쓴 경로가 검사에 걸린다.** 증상: 문서 커밋에서 `user_home`·`tmp_dir`·`tilde`가 걸린다. 원인: 사용자 홈 아래 절대 경로, macOS 임시 폴더 경로, 물결표+빗금으로 시작하는 경로는 모두 걸린다. 대응: `<colima Docker 소켓>`, `<로컬 경로>`처럼 자리표시로 쓴다. 키 모양·서비스키 파라미터 모양도 문서에 예시로 쓰지 않는다(검사 도구는 자기 패턴을 조각으로 이어 만들어 스스로 걸리지 않게 한다).
- **검사 도구에 예선 전용 예외가 남아 있다.** 증상: 경로가 들어간 행이 검사에 걸리지 않는다. 원인: `secret_scan.py`의 예외 셋. ① 컨테이너 경로 예외(`artifacts/openshell/`, `spikes/x1/` 아래 파일의 샌드박스 홈 경로 두 개)는 그 폴더가 생기면 살아난다. ② 이력 문서 기준선은 `docs/research/` 바로 아래 특정 파일의 특정 6행(sha256이 정확히 같을 때)만 뺀다. ③ 봉인 폴더 물결표 예외는 경로 조건이 없어 **어느 파일에서든 늘 작동한다**: 물결표 + `.tradesentry/sealed/`로 시작하는 경로는 걸리지 않는다. 대응: `artifacts/openshell/`, `spikes/x1/` 폴더를 만들지 않고, 봉인 폴더 기본값 문자열을 쓰지 않는다.
- **키 래퍼는 `NVIDIA_API_KEY` 한 줄만 읽는다.** NGC 키 등 다른 비밀값은 이 래퍼로 넘길 수 없다. 쓰게 되면 넣는 방법을 팀장에게 먼저 묻는다. 래퍼는 자식 환경에서 `DATA_GO_KR_SERVICE_KEY`, `TRADESENTRY_SEALED_DIR`를 뺀다(예선 변수, 이 폴더에선 영향 없음).
- **`nim_ping`이 200이어도 도구 호출은 별개다.** `nim_ping`은 `max_tokens 8`짜리 요청 하나만 본다. 도구 호출 왕복은 예선 `scripts/g4_nim_toolcall_probe.py`로 따로 본다.
- **한 작업 트리를 두 세션이 함께 쓰면 서로의 파일과 브랜치가 섞인다.** 증상: 커밋에 다른 세션의 파일이 섞이거나, 한 세션이 브랜치를 바꿔 다른 세션이 보던 파일이 바뀐다. 대응: main 폴더에서는 상위 오케스트레이터만 일하고, 하위 오케스트레이터는 각자 `app/.orch/<트랙>/wt` worktree에서 일한다. Hustler는 자기 노트북의 clone에서 일한다. Hustler 세션이나 두 번째 세션을 팀장 노트북의 main 폴더에서 띄우면 이 문제가 다시 생긴다. 디렉터리 분리는 "누가 어느 파일을 고치나"만 정할 뿐, 한 작업 트리를 함께 쓰는 문제는 풀지 못한다.
- **Hustler의 clone에는 git이 추적하지 않는 파일이 없다.** `.env`, `.claude/skills/`의 복사 스킬, `.dryforge/`는 clone에 생기지 않는다. Hustler는 키가 필요 없으므로 `.env`를 받지 않는다. `claude-design`·`architecture-diagram`의 원본은 팀장 노트북에만 있으므로, 필요하면 팀장이 `.claude/skills/<이름>/` 폴더를 파일로 넘기고 Hustler가 같은 자리에 둔다.
- **Hustler 브랜치는 `origin/`을 붙여 본다.** 증상: 병합 전 확인 명령이 "unknown revision"으로 끝나거나 옛 내용을 본다. 원인: Hustler 브랜치는 원격에만 있고, `git fetch origin` 전에는 팀장 쪽에 최신 내용이 없다. 대응: `git fetch origin` 뒤 `origin/hustler/<…>`로 diff·검사·병합한다. 병합 뒤에는 `git push origin main`으로 올리고 Hustler에게 알린다. 원격의 Hustler 브랜치는 지우지 않는다(삭제는 팀장 확인).
- **팀장 쪽 main 변경이 Hustler에게 안 보인다.** 증상: Hustler 데이터가 바뀐 계약 형식과 다르다. 원인: Hustler는 `origin/main`만 본다. 미션 접수 결과나 계약 변경을 main에 병합하고 push하지 않으면 Hustler 쪽 계약 문서는 옛 판이다. 대응: main이 바뀔 때마다 범위 검사 뒤 push하고 Hustler에게 알린다. Hustler 쪽은 `git fetch origin && git show origin/main:docs/contracts.md`로 최신 계약을 본다.
- **`git switch -c <브랜치> origin/main`은 원격 main을 추적하도록 설정한다.** 증상: `push.default=upstream`인 노트북에서 그냥 `git push`가 원격 main으로 간다. 대응: Hustler 브랜치는 `--no-track`으로 연다.
- **dryforge `go`는 쓰지 않는다**(2026-10-07 결정, ADR 0006). `ready`만 상위가 쓴다. `ready`는 뼈대(디렉터리·가짜 입력·스키마·진입점)를 작업으로 넣지 않으므로 `[사실: dryforge ready SKILL.md "Scaffold is not a task"]`, 설계에 "공통 뼈대·스키마·가짜 입력·`app/pyproject.toml`·lock은 0단계 작업 하나로 묶는다"를 명시해 0단계를 받아 낸다. 받아 내지 못하면 상위가 설계를 읽고 0단계를 정해 지시문에 쓴다. 뼈대의 가짜 입력·시험에는 평가 사례나 홀드아웃을 쓰지 않는다. `go`를 다시 쓰게 되면 결정 기록 05:55·08:50 줄의 함정(작업 base가 main, "Hand off only", 올리지 않은 main 커밋)을 먼저 본다.
- **트랙 worktree에는 git이 추적하는 파일만 있다.** 증상: 하위 세션이 설계 문서나 자료를 못 찾는다. 원인: `.env`, `.dryforge/`(설계 문서), `.claude/skills/`, 추적하지 않는 자료는 worktree에 생기지 않는다. 단 worktree는 main 폴더 안(`app/.orch/<트랙>/wt`)에 있어서 상위의 `.env`에 경로로는 닿는다. 하위가 키를 쓰지 않는 것은 규칙으로만 막힌다. 대응: 필요한 설계 내용과 자료 위치는 지시문에 글자 그대로 넣고, 키가 닿는 일은 `request`로 상위에 맡긴다. worker 정의(`.claude/agents/`)와 `scripts/orch.py`는 추적 파일이라 worktree에 있다. 단 `spawn` 전에 main에 커밋돼 있어야 한다.
- **트랙 worktree는 `spawn` 때의 main에서 갈라진다.** 증상: 뒤에 main에 들어간 계약 변경이나 공통 파일이 트랙에 보이지 않는다. 대응: 상위가 main에 넣은 뒤 `instruction`으로 알리고, 하위는 `git merge main`으로 받는다. 트랙은 squash로 main에 들어가므로 이 병합 커밋은 main에 남지 않는다.
- **기다릴 때 foreground `sleep`을 되풀이하면 막힌다.** 증상: "Blocked: sleep … Use Monitor" 같은 거부 `[사실: 2026-10-07 세션 관찰]`. 대응: `python3 scripts/orch.py wait … --timeout <초>`를 백그라운드로 돌려 끝날 때 깨어나게 하거나, Monitor(조건이 될 때까지 지켜보는 도구)를 쓴다.
- **`launch`로 띄운 세션이 다른 세션의 목록에 바로 안 보일 수 있다.** 2026-10-07 09:1x에 터미널 창으로 띄운 세션이 25분 넘게 세션 목록(ListAgents)에 보이지 않았다 `[사실: 세션 관찰]`. 그래서 지시·보고는 세션 사이 메시지가 아니라 작업기록 폴더의 파일과 flag로 주고받는다.
- **main 폴더에서 `git clean -x`(무시 파일까지 지우기)를 돌리면 `app/.orch/`의 트랙 worktree와 작업기록이 함께 지워진다.** 대응: `git clean`에 `-x`를 붙이지 않는다. 지울 것이 있으면 경로를 지정한다.
- **트랙 이름은 다시 쓸 수 없다.** squash 병합 뒤에도 `track/<트랙>` 브랜치와 작업기록 폴더는 남는다(`spawn`이 종료 2로 거부). 같은 폴더의 다음 작업은 새 트랙 이름으로 연다(`--scope`는 같은 폴더여도 된다). 같은 이유로 `status`의 "브랜치에만 있는 커밋"은 squash 뒤에도 0이 되지 않는다.
- **시험 도구가 `app/.orch/` 안의 다른 트랙 사본까지 훑을 수 있다.** 점으로 시작하는 폴더는 pytest가 기본으로 건너뛴다(`norecursedirs` 기본값에 `.*`) `[추론: pytest 기본 설정]`. 다른 도구를 쓰면 0단계에서 제외 설정을 넣는다.
- **미션 접수 결과는 기록 파일 예외로 커밋할 수 없다.** 증상: 접수 결과를 커밋하지 않은 채 0단계 브랜치를 열면 접수 문서 수정이 그 브랜치에 섞인다. 원인: 접수 결과가 들어가는 계약·업무 규칙·구성·작업 규칙 문서, 미션 접수 기록, 진입 안내는 예외 밖이라 브랜치·검토가 필요하다. 대응: 접수 결과는 브랜치 하나(`mission/<작업ID>-<설명>`)로 커밋 → 비밀값 검사(`python3 scripts/secret_scan.py <범위>` 종료 0) → 독립 검토 → squash 병합한 뒤 0단계를 시작한다. 동결 커밋 해시를 미션 접수 기록에 적는 일과, 새 트레이드오프 결정 파일(`NNNN-<설명>.md`)도 같은 방식이다. 결정 기록 표의 줄은 그 파일이 main에 들어간 뒤에 덧붙인다.
- **스킬은 `.claude/skills/`에 복사만 하면 실행 중인 세션에도 잡힌다.** 2026-10-06 복사 직후, 열려 있던 Claude Code 세션의 스킬 목록에 `claude-design`, `architecture-diagram`이 떴다 `[사실: 세션 관찰]`. 이 폴더는 git이 추적하지 않으므로 새 worktree나 새 clone에는 없다. 다른 작업 복사본에서 쓰려면 다시 복사한다.

## 2. NIM

- **429·5xx가 연쇄로 난다.** 무료 키에서 HTTP 500이 간헐적으로 났다. 사례 하나가 약 5만 토큰이라 1분에 3건이면 429가 났다. 응답 스트림 안에 과부하 오류(`FailoverError: The AI service is temporarily overloaded`)가 섞여 왔다. 오류가 새벽 2~4시(KST)에 몰리는 경향이 있었다 `[추론]`. 대응: 재전송, 재전송을 한도에서 빼기, 속도 조절을 첫 호출 코드부터 넣는다. 예선은 이 문제로 약 반나절을 잃었다 `[예선 실행]`.
- **`nvext.guided_json`은 거부된다.** 이 모델·엔드포인트에서 HTTP 400이었다 `[예선 실행: 2026-09-25]`. 대응: 구조화 출력은 도구 호출이나 `response_format {"type":"json_object"}`(도구를 싣지 않은 요청에만)로 받는다.
- **모델 출력의 숫자와 호출 한도는 지침으로 지켜지지 않는다.** 모델이 "추가 조회 없이 보류" 지시를 어겼고, 점유율 감소를 증가로 썼다. 대응: 숫자는 검증기, 한도는 코드로 막는다.

## 3. OpenShell

- **colima를 켠 직후 끄면 샌드박스가 Error에 갇힌다.** 증상: `openshell sandbox list`가 Error, `sandbox exec`가 "not ready (phase: Error)"로 거부된다. 원인: `colima start` 직후 게이트웨이가 샌드박스 컨테이너를 올리는 중에 `colima stop`을 해 컨테이너가 강제 종료됐다(종료 코드 143·141). 게이트웨이가 이를 Error로 기록했고, OpenShell CLI에는 Error에서 빠져나오는 명령도 게이트웨이 재시작 명령도 없다. `nemoclaw <이름> recover`로 컨테이너와 감독 프로세스는 정상이 돼도 게이트웨이 상태는 Error로 남았다 `[사실: 2026-10-06 겪음]`. 대응: 끌 때는 Ready 상태에서 `openshell sandbox stop <이름>` 뒤 `colima stop`, 켤 때는 `colima start` 뒤 `openshell sandbox start <이름>` `[추론: 이 순서는 아직 시험하지 않음]`. 게이트웨이는 NemoClaw가 관리하는 서비스라 다른 방법으로 재시작하면 게이트웨이 자체가 깨질 수 있다.
- **`install.sh`가 종료 1로 끝난다.** compute driver가 설정되지 않아서다. 게이트웨이 설정 파일을 써야 하는데, NemoClaw 설치 뒤에 다시 쓰면 시연 게이트웨이가 깨진다. 대응: 이미 설치돼 있으면 다시 설치하지 않는다.
- **`sandbox create`가 이미지를 못 빌드한다.** colima에서는 `DOCKER_HOST`가 필요하다. `.dockerignore`에는 `!Dockerfile`이 필요하다.
- **provider만 붙여서는 목적지가 열리지 않는다(CONNECT 403).** `providers_v2_enabled`가 기본으로 꺼져 있어서다. 대응: 정책에 네트워크 블록을 직접 적는다.
- **`inference.local`이 정책을 우회한다.** 이 관리형 추론 주소는 감독 프로세스의 추론 라우터가 네트워크 정책 밖에서 처리한다. 정책 블록이 없어도 모든 실행 파일이 썼고, 블록을 두자 요청이 응답 없이 멈췄다. 경로는 작업 공간(게이트웨이 안의 자원 범위) 단위라 provider를 붙이지 않은 샌드박스도 썼다. NemoClaw 온보딩이 이 경로를 만든다. 대응: `openshell inference delete`, 실행 묶음 앞뒤 `openshell inference get` 기록 `[예선 실행: violation_tests.md V7·V8]`.
- **실행 파일 판정은 실제 실행 파일 기준이다.** `/proc/<pid>/exe`로 판정하고, 심볼릭 링크와 스크립트(shebang)는 실제 해석기로 풀린다. OpenClaw는 node 스크립트라 정책에 `openclaw`만 두면 거부되고 `/usr/local/bin/node`를 넣어야 한다. 허용된 실행 파일이 띄운 자식(curl 등)은 허가를 물려받는다. 목적지와 L7 제한은 그대로 걸린다.
- **거부 사유는 셋이다.** endpoint-miss(목록에 없는 목적지), binary-miss(목록에 없는 실행 파일, 로그에 조상 목록이 같이 찍힘), L7 불일치(403, 본문 `policy_denied`). L7 규칙은 method, path, query만 본다.
- **네트워크 위반 탐침이 허가를 물려받는다.** 대응: 탐침은 허용 실행 파일의 자손이 아닌 `openshell sandbox exec` 세션에서 시작하고, curl에는 `--fail`을 붙인다.
- **로그에 행이 빠진다.** `openshell logs`는 크기가 정해진 버퍼에서 읽는다. 완전한 기록은 샌드박스 안 `/var/log/openshell.*.log`다. 파일시스템 거부는 아예 로그에 남지 않는다.
- **Landlock이 알리지 않고 빠질 수 있다.** colima·Docker에서도 집행됐다(커널 ABI v4, 적용 방식 BestEffort). BestEffort는 커널이 지원하지 않으면 조용히 빠진다. 대응: 로그의 `rules_applied:N skipped:0`을 확인한다.
- **정책 계층마다 바꾸는 법이 다르다.** 정적 계층(`filesystem_policy`, `landlock`, `process`)은 만들 때 고정되고 바꾸려면 다시 만든다. 동적 계층(`network_policies`)은 `policy set`으로 다시 불러온다. 파일시스템은 허용 목록 방식이고 경로가 겹치면 가장 긴 앞부분이 이긴다.
- **`include_workdir: true`이면 `/sandbox`가 통째로 읽기·쓰기가 된다** `[문서만]`. 읽기 전용이어야 하는 입력을 `/sandbox` 아래에 두면 지켜지지 않는다. `/opt/...`에 둔다.
- **같은 이름으로 다시 만들면 정책 Version이 1로 돌아간다.** Version만으로는 다시 만든 것을 가리지 못한다.
- **`sandbox download`가 덮어쓴다.** 받는 곳의 같은 이름 파일을 알리지 않고 덮어쓰고 심볼릭 링크를 그대로 받는다. 대응: 임시 폴더로 받고 링크를 검사한 뒤 옮긴다.
- **`sandbox exec`가 돌아오지 않을 수 있다.** OpenClaw 게이트웨이 재시작 뒤 `--timeout`을 넘겨도 돌아오지 않은 적이 있다. 대응: exec는 하나씩 돌리고 호스트 쪽 감시 시간을 둔다.
  - 표준 입력을 열어 둔 채(TTY 없음) 부르면 명령이 끝나도 돌아오지 않고 `--timeout`도 끊지 못한다(2026-10-07 실측, OpenShell 0.0.116). 대응: `< /dev/null`로 닫는다.
- **`sandbox download`는 `/sandbox` 밖 경로를 받지 못한다.** `/hackathon/output/<run_id>`를 주면 "outside the sandbox workspace (/sandbox)"로 거부한다(2026-10-07 실측). 대응: exec로 `/sandbox/work/` 아래에 복사한 뒤 받는다.

## 4. NemoClaw·OpenClaw

- **설치기가 라이선스 고지 수락에서 멈춘다.** 에이전트가 대신 수락하지 않는다. 팀장 승인 뒤 수락 플래그로 돌린다.
- **`nemoclaw agent`는 성공한 턴에서도 종료 1이다(`replayInvalid`).** 대응: 판정은 결과 JSON의 `status`·`payloads`와 CLI 실행 기록으로 한다.
- **같은 세션에서 `exec`가 두 번 불려 CLI가 중복 실행됐다.** 요청 없이 턴이 1건 더 돈 일도 있다. 대응: 스킬에 "한 번만 실행" 규칙을 두고 결과를 대조한다.
- **스킬 호출이 다 성공하지 않는다.** 예선 성공률 5/7, 실패 2건의 원인은 기록되지 않았다. 대응: 발표는 녹화 백업이 기본이다.
- **런타임 스킬 작성 요령** `[사실: 예선 skills/tradesentry/SKILL.md]`: 값 형식을 검증한다(경로 구분자, `..`, 셸 기호가 든 값은 거부하고 다시 묻는다). 한 요청에 명령 하나만 실행한다. CLI 출력과 종료 코드를 고치지 않고 그대로 전한다. 실패하면 다른 명령으로 바꿔 다시 하지 않는다. 답 끝에 "CLI를 실제로 불렀는지와 실행 상태" 한 줄을 남긴다. 이 줄이 스킬 호출 성공률의 근거다.

## 5. NAT

- **`nat` CLI가 `.env`를 읽는다.** import 때 `load_dotenv()`가 돈다. 대응: 파이썬 API를 쓰고 `PYTHON_DOTENV_DISABLED=1`, `NAT_TELEMETRY_ENABLED=false`를 준다.
- **마지막 이벤트가 빠진다.** `stop()`은 남은 쓰기를 기다리지 않는다. 대응: `wait_for_tasks()`를 부른다.
- **프로파일러가 토큰을 못 본다.** NIM을 직접 부르고 LLM 이벤트를 남기지 않으면 그렇다(예선 X1). 대응: LLM_START/END 이벤트에 토큰을 싣는다.
- MCP, A2A(에이전트끼리 통신하는 규약), NAT 내장 평가 시스템은 예선에서 쓰지 않았다 `[문서만]`.

## 6. macOS와 라이브러리

- 시스템 `python3`는 3.9.6이라 앱 코드가 돌지 않는다. uv로 받은 3.12를 쓴다.
- `/bin/bash`는 3.2라 `set -u`에서 빈 배열이 터진다.
- zsh에는 `PIPESTATUS`가 없다. 소문자 `pipestatus`를 쓴다.
- `timeout` 명령이 없다. 백그라운드 실행 + 감시로 대신한다.
- streamlit을 lock에 넣으면 NAT의 websockets 판과 충돌한다. `--with "streamlit==<판>"`으로 실행 때만 받는다.
- 작업 도구의 사용량 한도로 약 3시간 멈춘 적이 있다. Codex(OpenAI의 코딩 에이전트 CLI)는 인증 오류 뒤 사용량 한도로 막혔다. 대응: 당일 아침에 Codex를 쓸 수 있는지 먼저 확인하고, 안 되면 Claude 독립 검토로 대신한다(팀장 동의 1회, PR에 그 사실을 적는다).

## 7. 7시간 해커톤의 실패 패턴

| 증상 | 원인 | 대응 |
|---|---|---|
| 만들 시간이 5시간도 안 남는다 | 아이디어 회의에 2시간을 썼다 | 10:30~11:10 40분 안에 한 문장으로 정한다 |
| 발표에 근거가 없고 일이 Hacker에게 몰린다 | Hustler가 아이디어만 냈다 | 접점 1(12:00)까지 실제 경험자 인터뷰 2건 이상 |
| 시연할 화면이 없다 | Hacker가 보이지 않는 부분을 완벽하게 만들었다 | 시연 장면에 나오는 기능부터 구현 |
| 발표 속 제품과 시연 제품이 다르다 | 접점 없이 끝까지 따로 갔다 | 12:00과 15:00 접점 고정 |
| 잘 되던 기능까지 깨진다 | 동결 뒤 "이것만 더" 넣었다 | 15:00 기능 동결을 지킨다 |
| 시연 중 처음 본 오류를 수습 못 한다 | 리허설 없이 올라갔다 | 리허설 3회와 녹화 백업 |
| 예선은 첫 커밋부터 결과표까지 약 64시간, 그중 계획 문서 11종에 약 7.5시간이 들었다 `[추론: git 커밋 시각]` | 계획 문서를 나눠 썼다 | 하루짜리는 미션 접수 기록 한 장으로 줄인다 |
| X1의 막힘이 모두 첫 통합에서 드러났다(라이선스 고지 수락, node 실행 파일 판정, 추론 경로 우회) | 경계 실패는 끝까지 이어 봐야 보인다 | X1을 첫 시간에, 45~50분 타임박스로 |

**데모 경로 안정화 순서**(15:00 기능 동결 뒤 핵심 경로에만)
1. 깨끗한 시작 상태에서 연다.
2. 데모 입력을 넣는다.
3. 핵심 결과가 나오는지 본다.
4. 네트워크 실패·API 한도·타임아웃 때 무엇을 보여 줄지 확인한다(재생 실행 대체 포함).
5. 1~4를 최소 세 번 반복한다. 확인: 세 번 모두 같은 결과.

## 8. 작업 설계 때 참고할 구현 방식

dryforge `ready`로 작업을 설계할 때와 지시문을 쓸 때 아래를 참고 자료로 쓴다. `ready`는 이 저장소의 영역 규칙을 모르므로, 설계에 "대상 파일은 `app/` 아래(문서 갱신은 `docs/`), Hustler 영역과 `scripts/`·루트 파일은 고치지 않는다", "평가 사례·기대 결과·홀드아웃 경로는 읽지도 작업 대상에 넣지도 않는다", "작업을 트랙(`app/<트랙>/`)별로 묶고 트랙끼리 같은 파일을 고치지 않는다"를 명시한다. 우리 금지 문장은 지시문과 worker 정의(`.claude/agents/`)를 거쳐 worker에 닿는다. 동결 1 파일(평가 사례·기대 결과·홀드아웃)은 `app/` 밖에 둔다(위치는 계약 문서의 평가 구성 칸). 트랙은 `spawn` 때의 main에서 갈라지므로, 트랙끼리 함께 쓰는 가짜 입력·스키마는 0단계에서 만든다. 예선에서 결과를 낸 운영 방식이다 `[사실: docs/rules/AGENT_OPS.md, docs/rules/PARALLEL_DEV_RULES.md를 줄임]`.

**역할**

| 역할 | 하는 일 | 하지 않는 일 |
|---|---|---|
| 상위 오케스트레이터(main 폴더의 팀장 주 세션) | `ready`, 트랙 묶기, 0단계 지휘, 지시·답, 키가 닿는 명령(팀장 승인 뒤), 병합·push, 팀장 소통, 증거 재확인 | 키 값을 지시·보고에 넣기 |
| 하위 오케스트레이터(트랙마다 별도 세션) | 자기 worktree에서 worker 지휘, 검증 재실행, `track/<트랙>` 커밋, 작업기록·보고 | main 병합·push, 범위 밖 수정, 키가 닿는 명령 |
| `worker-implementer` | 지시된 작업 하나를 시험 먼저 쓰고 구현 | 범위 밖 수정, push, 병합, 사람에게 직접 묻기 |
| `worker-reviewer` | 읽기 전용 검토. 작성 worker와 다른 새 에이전트 | 파일 수정 |
| `worker-debugger` | 시험·검증 실패, BLOCKED 때 재현 → 원인 → 최소 수정과 회귀 시험 | 시험 삭제·기대값 변경, 평가 파일 읽기 |
| Codex(선택) | 시험이 먼저 커밋된 1~2파일 부품, 교차 검토. 키·봉인 경로 변수를 뺀 환경에서 `-s read-only`나 `-s workspace-write`로만 | 비밀값, 키가 필요한 실행, 커밋, push |

**서브에이전트 지시에 넣을 것**
1. 작업 ID와 목표(팀장 요청 원문 포함)
2. 바꿔도 되는 파일 목록
3. 완료 기준 명령(종료 코드 0)
4. 계약 값. 새 worktree에는 git이 추적하지 않는 파일(자료 등)이 없으므로 자료의 위치와 내용을 지시에 직접 넣는다. `.env`와 키 값은 넣지 않는다. 키가 닿는 명령은 오케스트레이터가 팀장 승인 뒤 팀장 작업 폴더에서 키 래퍼로 돌린다
5. 고정 금지 문장:
   - "`.env`를 열거나 출력하지 않는다. 키 값을 드러낼 수 있는 조회를 하지 않는다."
   - "지시문의 범위 안 파일만 고친다. push·PR·병합을 하지 않는다. 스테이징은 `git add <파일>`로만 한다."
   - "사람에게 직접 묻지 않는다. 막히면 추측하지 말고 `NEEDS_CONTEXT`나 `BLOCKED`로 돌아온다."
   - "평가 홀드아웃 사례와 기대 결과를 열지 않는다."(구현 작업일 때)
6. 반환 양식(`worker-implementer` 정의와 같다. `commit`은 지시문이 커밋을 시켰을 때):
```
status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED
files_changed: [...]
verification: [명령과 종료 코드]
commit: <해시>
concerns: [...]
```

**검토자에게 줄 것**: 팀장 요청 원문, 기준(계약 값), 범위(diff), 대조할 정본 파일, 검사 명령, 보고 형식(`PASS`/`CHANGES_REQUIRED`, `파일:행 — 이유 — 고칠 방법`).

**트랙 나누기**: 트랙 2~3개와 파일 소유 표로 나눈다. 가짜 입력과 스키마를 먼저 커밋해 다른 트랙이 진짜 자료를 기다리지 않게 한다("기다리면 하루를 잃는다").

## 9. 예선 저장소에서 찾을 것

`../nvidia-hackathon-2026/` 또는 https://github.com/JoeHwangHee/nvidia-hackathon-2026 (커밋 `bc0616f` 기준). 참고만 하고 고치지 않는다.

| 무엇 | 경로 |
|---|---|
| 전체 그림, 실행 사슬, NVIDIA 스택 표, 5분 재현 | `README.md` |
| 기획·개발 일지(시간순 결정·대안·이유) | `docs/tracking/journal.md` |
| 결정 방식과 작업 운영 | `docs/rules/AGENT_OPS.md`, `docs/rules/PARALLEL_DEV_RULES.md` |
| 설계: 실행 사슬, 정책 요건, 판정 규칙 | `docs/plan/DEV_PLAN.md`(3~7절, 13절 결정 기록, 14절 도입 시나리오, 부록 A 검토 회의) |
| 평가 룰북과 결과표 | `docs/eval/RULEBOOK.md`, `docs/eval/RESULTS.md` |
| 겪은 함정 | `docs/engineering-notes.md` |
| 실행 절차와 X1 재현 | `docs/operations.md`, `spikes/x1/README.md` |
| OpenShell 증거 | `artifacts/openshell/violation_tests.md`, `artifacts/openshell/openshell_violation_tests-260926145339/` |
| 정책·모델·NAT 설정 | `configs/openshell/`, `configs/model/model.json`, `configs/nat/workflow.yml` |
| 위반 시험·이미지 준비 도구 | `scripts/openshell_violation_tests.py`, `scripts/stage_sandbox_image.py` |
| 모델 클라이언트(재전송 규칙) | `src/tradesentry/workflow/model_client.py` |
| 런타임 스킬 작성 예와 스킬 사전 | `skills/tradesentry/SKILL.md`, `docs/eval/SKILL_DICTIONARY.md` |
| 재생 실행 파일 만들기와 예 | `scripts/make_smoke_replay.py`, `eval/dev/smoke/` |
| 대회 조사(일정, 심사, 스택 레퍼런스) | `docs/research/NVIDIA-FastCampus-Korea-Agentic-AI-Hackathon-2026.md` |
| 자기채점 예 | `artifacts/scorecard/scorecard-260926155108/scorecard-260926155108.md` |

**재생 실행(키 없는 시험·시연 대체)의 원리** `[예선 실행]`: 기록된 모델 응답을 차례로 내준다. 보내려는 요청 본문의 해시(키를 정렬한 JSON의 sha256)가 기록과 같은지 대조하고, 다르면 실패(종료 1)한다. 기록이 남아도 실패다. 도구는 재생 때도 실제로 돈다. 가상 시계로 대기를 생략한다. 표준 오류에 "재생 실행" 알림을 한 줄 남긴다. 재생 파일은 실제 NIM으로 끝까지 돈(`COMPLETED`) 실행 기록에서만 만들고, 키 모양이나 로컬 경로 모양이 있으면 만들지 않는다. 지침이나 요청 구성이 바뀌면 해시가 달라지므로 다시 만든다.
