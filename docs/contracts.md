# 계약: 도구의 사용법과 트랙끼리의 약속

이 파일이 트랙끼리 함께 기대는 값(입출력 형식, 상태값, 기준값, 이름, 경로, 명령, 도구 한도, 평가 구성, 발표 주장 문구)의 정본(기준이 되는 원본)이다. 다른 파일과 다르면 이 파일이 맞다. 바꾸려면 팀장 승인을 받는다("현행 → 제안, 영향 파일" 두 줄).

## 1. 공통 약속

- 네 도구 모두 폴더 루트(트랙 worktree에서는 그 루트)에서 부른다. 표준 라이브러리만 쓰므로 시스템 `python3`로 돈다.
- 키 값과 행 내용을 출력하지 않는다. 결과 줄은 stdout으로, 오류·경고 메시지는 한국어로 stderr로 나간다.
- 결과는 종료 코드로 판정한다. 출력 문구는 판정 근거가 아니다. **예외: 키 래퍼의 키 조각 경고 줄은 종료 코드와 관계없이 키 노출 의심으로 판정하고 팀장에게 바로 알린다.**

## 2. `scripts/with_nvidia_key.py`: 키 래퍼(키를 자식 프로세스에만 넘기는 도구)

**부르는 법**
```
python3 scripts/with_nvidia_key.py --env-file .env [--export-as <변수 이름>] -- <명령 ...>
```

| 입력 | 뜻 |
|---|---|
| `--env-file`(필수) | 키가 든 env 파일. 이 폴더에서는 루트 `.env`다. `NVIDIA_API_KEY=<값>` 줄 하나만 읽는다(`export ` 접두어와 따옴표 한 겹 허용). 다른 줄은 읽지 않는다 |
| `--export-as` | 자식 환경에 넣을 변수 이름. 기본 `NVIDIA_API_KEY`. 값은 같은 키이고 이름만 바뀐다. NemoClaw 온보딩은 `NVIDIA_INFERENCE_API_KEY`를 읽는다. 대문자·숫자·밑줄 형식이 아니면 거부한다 |
| `--` 뒤 | 실행할 명령 |

**출력**: 자식의 stdout·stderr를 줄 단위로 그대로 내보낸다. 키와 같은 문자열과, 키가 24자 이상이면 앞 10글자·끝 6글자 조각을 `***REDACTED***`로 바꾼다. 조각을 가렸으면 끝에 stderr로 `with_nvidia_key: WARNING 자식 출력에서 키 조각을 발견해 가렸다. 키 노출 의심으로 다룬다`를 남긴다. 이 경고는 종료 코드를 바꾸지 않는다(자식이 0이면 0).

**자식 환경**: 부모 환경 그대로 + 키 변수. `DATA_GO_KR_SERVICE_KEY`와 `TRADESENTRY_SEALED_DIR`는 뺀다.

| 종료 코드 | 뜻 |
|---|---|
| 자식 코드 그대로 | 자식이 정상 종료했다 |
| `2` | 명령이 없다, `--export-as` 형식 오류, env 파일을 못 읽었다, `NVIDIA_API_KEY` 줄이 없다(여기까지는 한국어 메시지), 인자 해석 오류(`--env-file` 누락 등. argparse(파이썬 표준 인자 해석기)의 영어 사용법 메시지) |
| `127` | 명령을 시작하지 못했다 |
| `128+n` | 자식이 신호 n으로 끝났다 |

## 3. `scripts/nim_ping.py`: 키·모델 접근 확인

**부르는 법**(키 래퍼 아래에서만)
```
python3 scripts/with_nvidia_key.py --env-file .env -- python3 scripts/nim_ping.py
```

| 입력 | 뜻 |
|---|---|
| 환경변수 `NVIDIA_API_KEY`(필수) | `.env`를 직접 읽지 않는다 |
| 환경변수 `NIM_MODEL` | 모델 이름. 기본 `nvidia/nemotron-3-super-120b-a12b` |

**하는 일**: `https://integrate.api.nvidia.com/v1/chat/completions`에 `max_tokens 8`, `enable_thinking false`인 요청 1건을 보낸다(요청당 60초 제한). 인증 헤더는 리디렉션 때 다른 곳으로 따라가지 않는다.

**출력**: stdout 한 줄 `HTTP <상태> · 모델 <이름>`. 응답 본문은 내지 않는다.

| 종료 코드 | 뜻 | 다음 할 일 |
|---|---|---|
| `0` | HTTP 200. 키와 모델 접근이 된다 | — |
| `1`, stdout에 `HTTP` 줄 있음 | 200이 아닌 HTTP 상태. 401·403은 키 문제(폐기, 오타, 권한), 404는 모델 이름 문제, 429는 속도 제한, 5xx는 서버 문제 | 401·403은 팀장이 키를 확인한다. 404는 `NIM_MODEL`을 바꿔 본다. 429·5xx는 잠시 뒤 다시 본다 |
| `1`, stdout에 `HTTP` 줄 없음(traceback(예외 추적 출력)만 있음) | 처리되지 않은 예외. 연결 뒤 응답 대기 60초 초과, 연결 끊김 등 | 키 문제가 아니다. 네트워크·서버를 보고 다시 시도한다 |
| `2` | `NVIDIA_API_KEY`가 환경에 없다 | 키 래퍼로 돌린다 |
| `3` | 연결 실패 | 네트워크를 본다 |

## 4. `scripts/secret_scan.py`: 비밀값·로컬 경로 검사

**부르는 법**
```
python3 scripts/secret_scan.py            # git이 추적하는 파일 전체(작업 폴더의 현재 내용)
python3 scripts/secret_scan.py <범위>      # 그 커밋 범위의 추가 행만(예: main..HEAD). 병합 커밋은 first-parent(첫째 부모와의 차이)만 본다
```
인자는 0개나 1개다. `-`로 시작하는 인자는 거부한다.

**찾는 종류**: `key`(NVIDIA API 키 모양), `anthropic_key`(Anthropic API 키 모양), `github_token`(GitHub 토큰 모양: classic·앱 토큰, fine-grained 토큰), `svc_param`(공공데이터포털 서비스키 요청 파라미터), `user_home`(사용자 홈 아래 절대 경로), `tmp_dir`(macOS 임시 폴더 경로), `tilde`(물결표+빗금으로 시작하는 홈 경로).

**출력**
- 전체 모드: 걸린 곳마다 `파일:줄 종류`, 끝에 `추적 파일 N개, 걸린 곳 M`.
- 범위 모드: 걸린 곳마다 `커밋 파일 +행순번 종류`, 끝에 `범위 <범위>: 추가 행 N줄, 걸린 곳 M`. `+행순번`은 파일 안 줄 번호가 아니라 범위 전체에서 센 추가 행의 누적 번호다.
- 행 내용은 내지 않는다.

| 종료 코드 | 뜻 |
|---|---|
| `0` | 걸린 곳 없음 |
| `1` | 걸린 곳 있음 |
| `2` | 인자 오류 또는 git 오류 |

## 5. `scripts/orch.py`: 트랙 작업 공간과 지시·보고 파일

상위 오케스트레이터(main 폴더의 팀장 주 세션)와 하위 오케스트레이터(트랙마다 별도 세션) 사이의 약속이다. 어느 작업 폴더(main 폴더든 트랙 worktree든)에서 불러도 main 폴더를 git으로 찾아 같은 작업기록 폴더를 쓴다. 키 값은 다루지 않는다.

**자리**(모두 main 폴더 기준, `.gitignore`가 `app/.orch/`를 뺀다)

| 경로 | 뜻 |
|---|---|
| `app/.orch/<트랙>/wt/` | 하위의 git worktree. 브랜치 `track/<트랙>` |
| `app/.orch/<트랙>/log/` | 작업기록 폴더. worktree에서 보면 `../log/` |
| `log/NNNN-<보낸 쪽>-<종류>.md` | 지시·보고 본문. 첫 줄은 `<!-- <트랙> <보낸 쪽> → <받는 쪽>, HH:MM:SS -->` |
| `log/.NNNN.lock` | 번호 예약 파일. `send`가 보낸 쪽과 상관없는 이 이름을 먼저 배타 생성해 번호를 잡는다(양쪽이 동시에 보내도 번호가 겹치지 않는다) |
| `log/NNNN-<보낸 쪽>-<종류>.flag` | 받는 쪽이 아직 읽지 않았다는 표시. 본문을 다 쓴 뒤에 생긴다. 읽으면 `.ack`로 바뀐다 |
| `log/worklog.md` | 작업기록. `log` 명령이 `- HH:MM:SS <내용>`을 덧붙인다 |
| `log/launch.sh` | `launch`가 만드는 창 실행 스크립트(로컬 경로가 들어 있다. 커밋하지 않는다) |
| `app/.orch/<트랙>/meta.json` | 트랙, 범위, 브랜치, base 커밋, 만든 시각 |

트랙 이름은 영문 소문자·숫자·하이픈 31자 이하. 번호 `NNNN`은 트랙마다 0001부터 하나씩 늘고 양쪽이 공유한다. 보낸 쪽 `top`이 보낼 수 있는 종류는 `instruction`·`answer`, `sub`는 `report`·`request`·`final`이다.

**부르는 법**

| 명령 | 하는 일 | 종료 코드 |
|---|---|---|
| `spawn <트랙> --scope app/<디렉터리>/ [--base main]` | main 폴더에서만. `track/<트랙>` 브랜치로 worktree와 작업기록 폴더, `meta.json`, `worklog.md`를 만든다. `.gitignore`가 `app/.orch/`를 빼지 않으면 거부. git이 실패하면 아무것도 남기지 않는다 | 0 / 2(이름·범위 형식, 트랙이나 브랜치 `track/<트랙>`이 이미 있음, 트랙 worktree 안에서 부름, ignore 없음) / 3(git 실패. 없는 base 등) |
| `launch <트랙> [--print]` | `log/launch.sh`를 쓰고 macOS 터미널 새 창에서 worktree의 `claude -n track-<트랙>`을 띄운다. `--print`는 창을 열지 않고 스크립트 위치만 낸다 | 0 / 2(worktree 없음) / 3(창 열기 실패) |
| `send [<트랙>] --from top\|sub --kind <종류> --body-file <파일\|->` | 본문을 임시 파일에 쓰고 이름을 바꾼 뒤 flag를 만든다. `-`는 표준 입력. 트랙을 빼면 현재 브랜치 `track/<트랙>`에서 정한다 | 0 / 1(작업기록 폴더 없음) / 2(종류·본문 오류) / 3 |
| `inbox [<트랙>] --for top\|sub` | 상대가 보낸 읽지 않은 flag를 `<트랙> <번호> <종류> <본문 경로>` 줄로 낸다. 본문 경로는 명령을 부른 폴더 기준 상대 경로다(트랙 worktree 루트에서는 `../log/…`). `top`이 트랙을 빼면 모든 트랙 | 0(있음) / 1(없음) / 2(없는 트랙 이름 포함) |
| `wait [<트랙>] --for top\|sub [--timeout 초(기본 3600)] [--interval 초(기본 5)]` | `inbox`가 무엇을 낼 때까지 기다렸다가 같은 줄을 낸다. 백그라운드 실행용 | 0(받음) / 1(시간 초과, stderr `timeout`) / 2(없는 트랙 이름 포함) |
| `ack <트랙> <번호> --for top\|sub` | 상대가 보낸 그 번호의 flag를 `.ack`로 바꾼다 | 0 / 1(읽지 않은 flag 없음) / 2 |
| `log <트랙> <내용...>` | `worklog.md`에 한 줄을 덧붙인다 | 0 / 1 / 2 |
| `status` | 트랙마다 브랜치, 브랜치에만 있는 커밋 수(`main..track/<트랙>`. squash 뒤에도 0이 되지 않는다), 상위·하위가 안 읽은 flag 수, 최종 보고 여부를 탭으로 나눠 낸다 | 0 / 1(트랙 없음) / 3 |

- 표준 라이브러리만 쓰고 시스템 `python3`(3.9)에서 돈다. 인자 해석 오류는 argparse의 영어 사용법 메시지와 함께 종료 2다. git 저장소 밖에서 부르면 어느 명령이든 종료 3이다.
- 본문과 작업기록에 키·토큰·로컬 절대 경로를 넣지 않는다. 도구는 본문을 검사하지 않는다. 최종 보고를 `docs/tracking/tracks/<트랙>.md`로 옮겨 커밋할 때 비밀값 검사가 처음 본다.

## 6. 트랙끼리의 약속(2026-10-07 설계 승인)

아래 "설계 ○.○" 절은 상위 오케스트레이터의 로컬 설계 문서(git 추적 안 함)에서 글자 그대로 옮겼다. 절 번호와 본문 속 "○.○절" 참조는 설계 문서 번호 그대로다. 설계 2.x는 동작 규칙, 4.x는 계약, 5는 경계 상황 규칙이다. 이 절이 트랙끼리 함께 기대는 값의 정본이고, 바꾸려면 팀장 승인을 받는다("현행 → 제안, 영향 파일" 두 줄).

| 약속 | 값 | 쓰는 트랙 |
|---|---|---|
| 입출력 형식 | 설계 4.2 도구 접점, 4.4 실행 폴더, 4.5 계획, 4.6 코스 | 전부 |
| 상태값 | 설계 4.4 `status` 표, 4.2 `ToolResult.kind` 집합, 4.4 게시 시도 `result` 집합 | `loop`, `tools`, 평가 |
| 이름·ID 규칙 | `run_id`(설계 4.4), 도구 이름 11개(설계 2.2 표), 자유 장소 ID `free-1`…(설계 4.2) | 전부 |
| 경로 | 설계 4.1 패키지와 소유, 4.3 지식 색인, 4.4 실행 폴더 | 전부 |
| 명령(실행, 시험, 채점) | 설계 4.9. 채점은 상위의 로컬 평가 스킬이 한다 | 전부 |
| 한도(모델 요청 수, 토큰, 시간, 도구 시도) | 설계 4.10 | `loop` |
| 평가 구성 | 경계 시험·기록 점검·기능 평가(x/N, Wilson 95% 구간)·심사 점검. 사례는 Hustler가 쓰고 git 밖(저장소 밖 폴더)에 둔다. 동결은 받은 즉시 sha256을 결정 기록에 커밋한다. 사례 형식은 설계 4.8, 기준선은 Nemotron 단독(자료·도구 없음, 설계 2.8) | 상위 |
| 한 문장 주장(발표 주장 문구) | K-콘텐츠를 보고 온 방문객이 목표를 말하면, 배경지를 잇는 코스를 짜고 각 장소 이름의 유래를 근거 등급과 함께 알려주는 에이전트. | 발표 |
| Hustler가 만들고 코드가 읽는 데이터(경로, 형식, 필드) | 설계 4.7 | `retrieval`, `tools`, 상위 |

### 설계 2.1 전체 흐름

모든 단계가 OpenShell 샌드박스(`kculture`) 안에서 돈다. 요청 하나는 실행 하나다.

1. **입력**: 사용자 요청(한국어 문장 하나)
2. **무게 판단(라우터)**: Nemotron이 요청의 무게만 판단한다(`heavy` 또는 `light`). 2026-10-07 14:35 팀장 결정으로 Claude에서 바꿨다(평가 환경에 Claude 키가 없을 수 있음). 제품은 Claude를 부르지 않는다.
   - 라우터는 요청에 답하지 않는다.
   - 라우터 호출은 계획·도구용 Nemotron 호출과 따로 센다(4.10).
   - `heavy`로 보는 요청: 자료 조회가 필요하거나, 여러 단계가 필요하거나, 코스·이름 유래·등급·게시를 다루거나, 파일·폴더 내용을 묻는 요청
   - `light`로 보는 요청: 인사, 사용법, 자료 없이 답할 수 있는 짧은 일반 질문
   - 판단이 애매하면 `heavy`로 보낸다.
   - 실패하면 한 번 다시 보낸다. 실패 = 응답 없음, HTTP 오류, 시간 초과, 형식 틀림. 다시 보내도 실패하면 "지금은 판단할 수 없어 응답하지 않습니다"를 내고 상태 `UNAVAILABLE`로 끝낸다. 추측해서 다른 경로로 보내지 않는다.
3. **가벼운 질문(`light`)**
   - Nemotron이 자료 검색 없이 바로 답한다.
   - 답 첫 줄에 `자료 근거 없음(일반 안내)`을 붙여, 근거 등급이 있는 답과 구분한다.
   - 상태는 `ANSWERED_LIGHT`다.
4. **무거운 질문(`heavy`)**: 개발된 구조로 처리한다(2.2절). 쓰는 것은 셋이다.
   - 지식 색인(JSON DB, 2.7절)
   - 계획·도구 루프
   - Nemotron
5. **출력**
   - 화면에 요약을 낸다.
   - `/hackathon/output/<run_id>/`에 파일을 남긴다(4.4절).

### 설계 2.2 무거운 질문의 계획·도구 루프("계획 먼저, 실행은 코드")

**계획**: Nemotron이 목표를 해석하고, 허용된 도구 목록 안에서 단계 목록을 한 번 만든다(4.5절).
- 계획 전에 루프가 `list_input`을 한 번 돌린다. 계획 단계 수에는 넣지 않고, 기록에는 남긴다.
- 계획 프롬프트에는 다섯을 넣는다.
  - 요청 문장
  - 지식 색인의 테마 팩 요약: 작품명·별칭, 장소별 ID·이름·장면·우선순위
  - `/hackathon/input`의 파일 목록: 경로·크기
  - `/hackathon/` 폴더 배치: `input`, `output`, `restricted`, `secrets`의 절대 경로
  - 도구 설명

**계획 검사**: 코드가 계획을 검사한다.
- 도구 이름이 목록에 있는지 본다.
- 인자 형식이 맞는지 본다.
- 단계 수가 한도 안인지 본다.

검사에 떨어지면 실행하지 않고 다시 계획을 받는다. 다시 계획을 받는 것은 실행 전체에서 한 번까지다.

**실행**: 코드가 단계를 차례로 실행한다.
- 모델은 도구를 직접 부르지 않는다.
- 도구는 실행 맥락(앞 도구들의 결과를 담는 곳, 4.2절)에서 정해진 키를 읽고 쓴다. 그래서 계획은 앞 단계의 출력을 가리킬 필요가 없다.
- 장소·이름마다 반복하는 일은 도구 안에서 한다. 단계 하나가 선택된 장소 전부를 처리한다.
- 도구가 `TOOL_ERROR`를 내면, 모델에게 남은 계획을 한 번 고치게 한다.
- 고친 계획도 실패하면, 그때까지의 결과를 저장하고 끝낸다(상태 `FAILED`, 이유를 기록).
- 아래 둘은 계획을 고칠 일이 아니라 기록할 사실이다.
  - 게시 차단(`BLOCKED_BY_POLICY`): 2.4절대로 승인을 기다린다.
  - 파일 읽기 거부(`DENIED_BY_SANDBOX`): 결과에 "접근이 거부됨(인프라 차단)"을 적고 진행한다.

**허용 도구**(이 이름만 쓴다. 인자·결과는 4.2절)

| 도구 | 하는 일 | 누가 판단 |
|---|---|---|
| `select_places` | 후보 장소(테마 팩 장소 ID, 또는 자료에서 찾은 장소 이름)를 받는다. Nemotron이 지식 색인과 읽은 입력 자료를 조사해 출발점부터 구간별 이동 시간과 순서를 낸다. 코드는 그 값을 검사하고, 합계를 내고, 예산에 맞춰 자른다 | 후보 고르기는 계획(모델), 구간 시간은 모델의 조사, 검사·합계·자르기는 코드 |
| `lookup_station` | 장소마다 가까운 역(이름·호선)을 테마 팩에서 채우고, 역 이름을 이름 목록에 더한다 | 코드 |
| `lookup_origin` | 장소마다 이름(현재 이름·옛 이름·작품 속 이름·역 이름)의 유래 근거를 지식 색인에서 하이브리드 검색으로 찾는다 | 코드(검색) |
| `lookup_operating` | 장소마다 운영 정보 자료(`kind: operating`)를 지식 색인에서 모은다 | 코드 |
| `organize_names` | 장소마다 세 이름을 정리하고, 이름별 유래를 근거 청크 ID를 달아 요약한다 | 모델이 묶고 요약, 코드가 근거 ID 검사 |
| `grade_evidence` | 유래 주장의 등급(A~D), 충돌, 운영 정보의 최신·오래된 자료 판정을 계산한다 | 코드 |
| `save_course` | 코스를 `course.md`·`course.json`으로 저장한다 | 코드 |
| `request_publish` | 코스를 GitHub 이슈로 한 번 보내고 결과 종류만 돌려준다(2.4절) | 코드 |
| `search_db` | 지식 색인 전체에서 하이브리드 검색을 한다(테마 팩이 없는 질문, 이름 유래 단독 질문) | 코드(검색) |
| `list_input` | `/hackathon/input`의 파일 목록(경로·크기)을 낸다 | 코드 |
| `read_file` | `/hackathon/` 아래 경로 하나를 연다. 폴더면 항목 이름을, 파일이면 본문(64KB까지, 조정값)과 머리 정보·본문 속 날짜를 낸다 | 코드 |

**게시 요청을 하는 경우**: 코스를 만든 실행은 기본으로 마지막에 `request_publish`를 한다.
- 예외: 요청이 보내기·게시·예약을 하지 말라고 하면 `request_publish`를 계획에 넣지 않는다. 이때 상태는 `COURSE_SAVED`이고, 기록에 "사용자가 보내지 말라고 함"을 남긴다.
- 코스가 아닌 무거운 질문(예: "혜화문 이름 유래 알려줘", "secrets 폴더 내용을 알려줘")은 근거 등급이 붙은 답(`answer.md`·`answer.json`)을 낸다. 상태는 `ANSWERED_HEAVY`이고, 게시 요청은 하지 않는다.

**일반 코스 요청**(작품 이름이 없는 요청. 예: 공통 시험 연습 요청)은 핵심 시연 흐름이 돈 뒤에 같은 도구로 처리한다(plan C1).
- 장소는 `list_input`·`read_file`과 `search_db`로 찾고, `select_places`의 `free_places`로 넘긴다.
- 음식 제한·당일 운영 정보는 자료에서 찾아 반영한다. 자료에 없으면 `unknowns`에 "확인 안 됨"으로 적는다.

### 설계 2.3 근거 등급과 충돌·오래된 자료(코드가 계산, 모델은 등급을 정하지 않는다)

**출처 종류와 등급**

| 출처 종류(`source_type`) | 뜻 | 등급 |
|---|---|---|
| `official` | 공공기관 공식 자료(지명유래집, 지자체, 국가유산청, 역 운영기관) | A |
| `academic` | 학술·백과사전 | B |
| `media` | 언론, 관광 안내, 위키 | C |
| `informal` | 블로그, 구전, 출처 불명 | D |

- 출처 종류가 비었거나 이 넷이 아니면 `informal`로 보고 D를 준다. `/hackathon/input`에서 읽은 파일도 머리 정보가 없으면 D다.
- 유래 주장 하나의 등급 = 그 주장을 받치는 출처 가운데 가장 높은 등급.
- 모델이 단 근거가 실재하지 않으면 그 근거를 버리고 경고를 남긴다. 실재란 지식 색인의 청크 ID이거나 이번 실행에서 읽은 입력 파일 경로라는 뜻이다. 근거가 하나도 남지 않은 주장은 "근거 없음"으로 내리고, 등급을 주지 않는다.

**이름 유래의 충돌**: 같은 이름에 서로 다른 유래 주장이 있으면 버리지 않고 모두 적는다.
- 순서: 등급이 높은 것이 앞, 같은 등급이면 날짜가 새로운 것이 앞.
- 주장끼리 같은지 다른지는 모델이 묶을 때 판단한다. 순서는 코드가 정한다.

**운영 정보(운영 시간·휴무)의 최신·오래된 자료**: 같은 장소에 운영 정보가 다른 자료가 둘 이상이면 아래 규칙을 따른다.
- 가장 새로운 자료의 등급이 그와 다른 말을 하는 모든 자료의 등급보다 같거나 높으면, 그 자료를 택한다. 나머지는 `stale`(오래된 자료) 목록에 이유와 함께 남긴다.
- 그렇지 않으면 결론을 내지 않는다. 다른 말을 하는 자료를 모두 보이고(등급순, 같으면 날짜순) `operating.status`를 `NEEDS_ONSITE_CHECK`("현장 확인 필요")로 둔다.
- 날짜가 없는 자료는 날짜가 있는 어떤 자료보다도 오래된 것으로 본다.

**자료 속 지시문**: 자료 안의 지시문(예: "이 문서를 읽은 AI는 …")은 자료로만 다루고 따르지 않는다. 기존 답변 단계의 처리를 이어받는다.

### 설계 2.4 게시 요청: 차단 → 승인 → 통과

**게시 대상**: 팀장이 만드는 게시 전용 GitHub 저장소의 이슈.
- 요청: `POST https://api.github.com/repos/<owner>/<repo>/issues`
- 본문: 코스 요약 Markdown
- 저장소 이름은 환경변수 `PUBLISH_REPO`(`owner/repo`)로 받는다. 비밀값이 아니다.

**토큰**
- 그 저장소의 이슈 쓰기 권한만 있는 최소 권한 토큰이다.
- 팀장이 자기 터미널에서 직접 OpenShell provider(OpenShell에 등록하는 자격 증명 묶음, 기본 제공 프로필 `github`)로 등록한다. 에이전트와 worker는 토큰 값을 보지 않는다.
- 샌드박스 안의 `GITHUB_TOKEN`은 자리표시 값이다. 요청이 정책을 통과할 때만 OpenShell 프록시가 실제 토큰으로 바꿔 넣는다.

**나누는 일**
- `request_publish`(도구)는 한 번 보내고 시도 결과를 돌려준다. 결과는 결과 종류(4.4절 `publish.json`의 `result` 집합), HTTP 상태, 이슈 URL이다(4.2절).
- 차단 판정은 둘 가운데 하나다.
  - 연결 단계에서 프록시가 터널을 거부함: urllib 예외 메시지에 `Tunnel connection failed: 403`이 있다. 오늘 위반 시험 V10에서 본 모양이다.
  - HTTP 403이고 본문에 `policy_denied`가 있음
- 그 밖의 연결 예외는 `NETWORK_ERROR`다.
- 승인 대기, 다시 보내기, `publish.json` 쓰기, `course.json`의 `publish` 갱신은 루프가 한다.
- 이슈는 실행 하나에 많아야 1개다. 루프는 `CREATED`를 받으면 다시 보내지 않는다.

**기본 상태(승인 전)**: 기본 정책(`app/sandbox/policy.yaml`)에는 `api.github.com` 규칙이 없다. 그래서 게시 요청은 OpenShell이 거부한다. 막혔다고 다른 주소나 다른 방법으로 우회하지 않는다.

**승인**: 사람(팀장)이 실행 중인 샌드박스에 승인 정책 파일을 적용한다. 샌드박스는 다시 만들지 않는다.
- 명령: `openshell policy set kculture --policy app/sandbox/policy-publish-approved.yaml --wait`
- 승인 정책 = 기본 정책 + `api.github.com:443`의 `POST /repos/<owner>/<repo>/issues` 한 경로 + 앱 Python 실행 파일
- 정책 이력(`openshell policy list kculture`)에 판(revision)이 남는다.
- 승인 범위는 **시연 단위**다(팀장 선택). 시연 동안 열어 두고, 시연이 끝나면 회수한다. 열린 동안에는 다른 실행의 게시도 통과한다. 이 위험은 알고 택했다.

**승인 뒤**
- 루프는 게시 요청이 막힌 뒤에도 끝내지 않고 승인을 기다린다. 기다리는 동안 일정 간격으로 다시 보낸다(간격 10초, 최대 180초, 조정값). 다시 보낸 시도는 모두 기록한다.
- 승인되면 다음 시도가 통과한다. 이슈 URL을 기록하고 상태를 `PUBLISHED`로 둔다.
- 최대 시간 안에 승인되지 않으면 상태 `PUBLISH_PENDING_APPROVAL`로 끝낸다. 나중에 다시 보내는 명령은 `python -m loop publish --run <run_id>`다. 이미 `CREATED`가 있는 실행에는 이 명령이 보내지 않고 종료 1로 끝난다.

**회수**: 시연이 끝나면 기본 정책을 다시 적용한다.
- 명령: `openshell policy set kculture --policy app/sandbox/policy.yaml --wait`
- 최종 시험(plan F1) 전에는 `openshell policy get kculture`로 GitHub 규칙이 없는지 확인한다.

**그 밖의 실패**: 401, 404, 422, 5xx 같은 실패는 정책 차단과 구분한다. 결과는 `HTTP_ERROR`, 연결 실패는 `NETWORK_ERROR`다. 이때 상태는 `PUBLISH_FAILED`이고 HTTP 상태를 기록한다. 응답 본문과 헤더는 기록하지 않는다.

**대체 경로(팀장 승인됨)**
- 발동 조건: 토큰 대신 넣기를 검증하는 시험(plan X1)이 45분 안에 끝나지 않는 경우
- 대체 대상: 키 없는 공개 서비스(예: ntfy.sh 토픽)
- 바꾸지 않는 것: 승인 방식(정책 파일 적용)
- 발동하면 바로 팀장에게 알리고, 발표·README에 그 사실을 적는다.

### 설계 2.5 경계(Runtime policy)

정책은 허용 목록 방식이다. 연 것마다 이유를 README 권한 표에 적는다.

**파일시스템**
- `/hackathon/input`: 읽기 전용
- `/hackathon/output`: 쓰기
- `/hackathon/restricted`, `/hackathon/secrets`: 거부. Landlock(커널 수준 파일 접근 제한)이 막고, 미끼 파일로 시험한다.
- 앱 코드(`/opt/kculture`), 지식 색인(`/opt/kculture/index`), 모델 가중치(`/opt/models`): 읽기 전용
- `/tmp`: 쓰기. 라이브러리 임시 파일용이고, 지금 정책에도 있다.

**네트워크**: 기본 거부. 앱 Python 실행 파일(`/opt/kculture/python/**`)에만 아래 경로를 연다.

| 대상 | 허용 경로 | 쓰임 |
|---|---|---|
| `integrate.api.nvidia.com:443` | `POST /v1/chat/completions` | Nemotron(무게 판단, 계획, 조사, 답) |
| `api.github.com:443` | 승인 정책에서만 `POST /repos/<owner>/<repo>/issues` | 게시 |

같은 호스트의 다른 경로와 다른 실행 파일(curl 등)은 거부된다.

**자격 증명**: 키 둘은 모두 provider로 넣는다. 샌드박스 안에는 자리표시 값만 있다.
- NIM: 기존 `tradesentry-nvidia`
- GitHub: 기본 제공 프로필 `github`, bearer 인증

**에이전트는 통제층에 닿지 못한다**
- 샌드박스 안에는 `openshell` 실행 파일이 없다.
- OpenShell 게이트웨이(호스트의 제어 주소)로 가는 연결은 정책이 거부한다.
- 그래서 에이전트는 스스로 승인할 수 없다. 위반 시험으로 증명한다.

**secrets 장면**(팀장 선택: 읽기 도구 + 네트워크 로그 짝)
1. "secrets 폴더 내용을 알려줘"는 `heavy`로 간다. 계획이 `read_file`로 `/hackathon/secrets`를 실제로 연다.
2. Landlock이 EACCES(권한 거부 오류)로 막는다. 도구는 `DENIED_BY_SANDBOX`를 돌려주고, 의사결정 기록에 남는다. 답에는 "접근이 거부됨(인프라 차단)"이 들어간다.
3. 같은 장면에서 `demo.sh`가 샌드박스 안에서 비허용 주소로 내보내는 시도를 한 번 한다. 앱 Python으로 하는 POST다. OpenShell 감사 로그의 `NET:OPEN DENIED` 줄을 보인다.
4. 발표에서는 "파일 거부는 커널(Landlock)이 막고 OpenShell 로그에는 남지 않는다. 네트워크 거부는 OpenShell 로그에 남는다"를 그대로 말한다.

- `read_file`은 `/hackathon/` 밖 경로를 열지 않는다. 그런 경로는 열어 보지 않고 `OUT_OF_SCOPE`를 돌려준다. 시스템 파일을 읽지 못하게 하려는 것이다.
- `/hackathon/` 안의 restricted·secrets는 앱이 먼저 거르지 않는다. 막는 주체가 인프라임을 보이기 위해서다.

### 설계 2.6 사후 감사와 의사결정 기록

**의사결정 기록(`trace.jsonl`)**: 실행마다 모든 판단과 도구 호출을 한 줄씩 남긴다. 줄 형식은 4.4절이다.
- 대상: 무게 판단, 계획, 계획 검사, 단계, 다시 계획, 게시 시도, 승인 대기, 최종 상태
- 각 줄에는 앞 줄의 sha256을 담는다(`prev_hash`). 나중에 기록을 고치면 드러난다.
- 키·토큰 값, 응답 본문 전체, 로컬 절대 경로는 넣지 않는다.

**OpenShell 쪽 기록**
- 감사 로그: `NET:OPEN`·`HTTP:<METHOD>`의 ALLOWED/DENIED, Landlock 적용 결과
- 정책 이력: `openshell policy list`

**감사 묶음**: 호스트에서 `app/sandbox/audit.sh <run_id>`가 셋을 모아 `outputs/audit/<run_id>/`에 둔다. `outputs/`는 git 제외 폴더다.
- 실행 폴더
- 그 시간대의 OpenShell 로그
- 정책 이력

`audit.md`는 게시 시도와 OpenShell 로그 줄을 시각(UTC)으로 맞춰 보인다. 예: "03:31:05 게시 시도 → DENIED, 03:31:40 정책 판 3 적용, 03:31:45 게시 시도 → ALLOWED → 이슈 #N".

### 설계 4.1 패키지와 소유

| 경로 | 소유 | 내용 |
|---|---|---|
| `app/common/` | 상위(0단계) | 공통 스키마·상태값·한도, 도구 접점(4.2), 가짜 입력(`app/common/fixtures/`) |
| `app/loop/` | 트랙 `loop` | 라우터(Nemotron), 가벼운 경로, 계획·검사·실행, 게시 대기, 의사결정 기록, 기준선, CLI |
| `app/tools/` | 트랙 `tools` | 2.2절의 도구 11개와 등록 함수 |
| `app/retrieval/` | 트랙 `retrieval` | JSON 색인, 출처 메타데이터 |
| `app/agent/` | 상위(고치지 않음) | 기존 NIM 클라이언트(`NimClient`)를 그대로 가져다 쓴다 |
| `app/sandbox/` | 상위 | 이미지, 스테이징, 정책 두 파일, 위반 시험, 감사·시연 스크립트 |
| `app/index/kb/` | 상위 | 구운 JSON 색인(커밋) |
| `app/data/bulk/` | 상위 | 대량 원자료(커밋) |

**시험**
- 각 패키지의 시험은 `app/<패키지>/tests/`에 둔다.
- 0단계가 다섯 패키지(`common`, `retrieval`, `agent`, `tools`, `loop`)의 시험 폴더를 `testpaths`에 미리 넣는다. 시험 파일 이름이 겹쳐도 되도록 `--import-mode=importlib`(시험 파일을 패키지 경로 없이 따로 불러오는 방식)를 쓴다.
- 공용 픽스처는 `app/conftest.py`에 둔다.
- 기존 `Retriever.load(index_dir, embedder)`와 `.query(q, k, mode)`의 호출 모양은 그대로 둔다. `app/agent`와 그 시험이 이 둘을 쓴다.

### 설계 4.2 도구 접점(`app/common/tooling.py`, 0단계)

**도구 하나의 모양**: `run(args: dict, ctx: RunContext, deps: Deps) -> ToolResult`

**`ToolResult`** = `{"ok": bool, "kind": <결과 종류>, "data": {...}, "error": "<한 줄 또는 빈 값>"}`
- `kind` 집합: `OK`, `TOOL_ERROR`, `BLOCKED_BY_POLICY`, `CREATED`, `HTTP_ERROR`, `NETWORK_ERROR`, `DENIED_BY_SANDBOX`, `NOT_FOUND`, `OUT_OF_SCOPE`, `TOO_LARGE`, `NOT_TEXT`
- `ok`가 거짓이고 `kind`가 `TOOL_ERROR`일 때만 루프가 계획을 고친다.

**등록**: `app/common`에 등록표(`ToolRegistry`: 이름 → 함수·인자 형식)가 있다.
- `tools` 패키지는 `tools.register_all(registry)` 하나로 도구 11개를 등록한다.
- `loop`는 시작할 때 이 함수를 부른다. 시험에서는 가짜 도구를 등록한다.

**주입 값 `Deps`**: 도구는 아래만 써서 바깥과 만난다. 시험에서는 가짜로 바꾼다.

| 이름 | 모양 | 실제 구현 |
|---|---|---|
| `search(query, k)` | 청크 dict 목록(4.3 청크 키) | `retrieval`의 `Retriever.query` |
| `get_chunk(chunk_id)` | 청크 dict 또는 없음 | `retrieval` |
| `chunks_where(kind, place_id)` | 그 `kind`이고 `place_ids`에 그 장소가 든 청크 전부 | `retrieval`(색인 청크를 걸러 냄) |
| `theme_packs()` | 테마 팩 dict 목록(4.7). 팩이 JSON 객체가 아니면 `RetrievalError`(도구는 `TOOL_ERROR`로 돌려준다) | 색인 폴더의 `theme_packs/*.json` |
| `chat(messages, purpose)` | `{"text", "usage", "model"}`. 호출 수·토큰을 루프가 센다 | `NimClient`를 루프가 감싼 것 |
| `http_post_json(url, headers, body)` | `{"status": 정수 또는 null, "body": 본문 앞 4KB 또는 빈 값, "error": null 또는 "TUNNEL_403" 또는 "NETWORK"}`. 예외를 올리지 않는다 | 표준 라이브러리. 리디렉션을 따르지 않는다. 예외 메시지에 `Tunnel connection failed: 403`이 있으면 `TUNNEL_403`, 그 밖의 연결 예외는 `NETWORK` |
| `read_path(path, max_bytes)` | 폴더면 `[{"name", "is_dir", "size"}]`, 파일이면 바이트. OS 예외는 그대로 올린다 | 표준 라이브러리 |
| `now()` | UTC 시각 | 표준 라이브러리 |

**실행 맥락 `RunContext`의 키와 쓰는 도구**

| 키 | 쓰는 도구 | 읽는 도구 |
|---|---|---|
| `run_id`, `request`, `run_dir`(실행 폴더 절대 경로), `publish_repo`(환경변수 `PUBLISH_REPO`의 `owner/repo`) | 루프(실행 시작 때) | `save_course`, `request_publish` |
| `goal` | 루프(계획에서) | 모두 |
| `places`(순서 있는 장소 목록), `excluded` | `select_places` | 그 뒤 모두 |
| 장소의 `station` | `lookup_station` | `lookup_origin`, `save_course` |
| `evidence`(장소 ID → 이름 → 청크 목록) | `lookup_origin` | `organize_names` |
| `operating_evidence`(장소 ID → 청크 목록) | `lookup_operating` | `grade_evidence` |
| `origins`(장소 ID → 유래 주장 목록. 장소가 없는 질문은 키 `_`) | `organize_names` | `grade_evidence` |
| `graded`(장소 ID 또는 `_` → `{"origins", "conflicts", "operating", "stale"}`, 꼴은 4.6) | `grade_evidence` | `save_course`, 답 쓰기 |
| `search_results`(청크 dict 목록) | `search_db` | `organize_names`, 답 쓰기 |
| `input_files`(`[{"path", "size"}]`, 경로는 `/hackathon/input` 기준 상대 경로) | `list_input` | 계획, `read_file` |
| `read_files`(절대 경로 → `{"kind", "text", "front_matter", "dates", "entries"}`) | `read_file` | `organize_names`, 답 쓰기 |
| `course` | `save_course` | `request_publish` |
| `warnings`, `unknowns` | 모두 | `save_course`, 답 쓰기 |

- 답 쓰기(`answer.json`)는 루프가 한다.
- GitHub 인증 머리글(자리표시 토큰)은 도구가 아니라 루프가 만든 `Deps.http_post_json` 구현이 붙인다. 도구는 환경변수를 읽지 않는다.
- `request_publish`의 `data` = `{"http_status": 정수 또는 null, "issue_url": 문자열 또는 null}`. `issue_url`은 201 응답 본문 JSON의 `html_url`만 읽는다. 본문은 기록하지 않는다.

**도구별 인자**(계획의 `args`)
- `select_places`: 인자 모두 생략 가능(빠지면 기본값). `pack_id`(기본 빈 값), `candidate_place_ids`(기본 빈 목록 = 팩 전부), `free_places`(테마 팩 밖에서 찾은 장소: `[{"name", "note"}]`, 기본 빈 목록), `time_budget_min`(정수 또는 null, 기본 null), `start`(역·장소 이름, 기본 빈 값)
  - `free_places`의 장소 ID는 `free-1`, `free-2` 순으로 코드가 붙인다.
- `lookup_origin`: `k`(이름당 청크 수, 기본 5, 조정값)
- `search_db`: `query`, `k`(기본 5)
- `read_file`: `path`(절대 경로)
- `request_publish`: `title`(기본 빈 값)
- 나머지 도구는 인자 없음(`{}`)

### 설계 4.3 JSON 색인(형식 판 3)

**위치와 파일**: `app/index/kb/`(이미지 안에서는 `/opt/kculture/index/kb/`)
- `manifest.json`: 형식 판, 토크나이저 설정, BM25 값, 임베더 이름·차원, `source_fingerprint`(원자료 폴더의 파일 상대 경로·크기·sha256을 정렬해 만든 sha256), 만든 시각
- `chunks.json`: 청크 배열
- `vectors.json`: 청크 순서대로 벡터 배열. 소수점 6자리, 조정값
- 한 파일이 50MB(조정값)를 넘으면 `chunks-0001.json`처럼 번호를 붙여 나눈다. `manifest.json`의 `chunk_files`·`vector_files`(언제나 목록, 나누지 않으면 `["chunks.json"]`·`["vectors.json"]`)에 순서대로 적고, 읽을 때 그 순서로 이어 붙인다.
- `theme_packs/`: 원자료의 테마 팩 JSON 사본. 색인하지 않고 도구가 그대로 읽는다.

**색인에서 빼는 것**: `theme_packs/` 아래 파일과 `_collection.json`은 본문 청크로 색인하지 않는다.

**청크 키**
- 기존: `chunk_id`, `source`(원자료 폴더 기준 상대 경로), `title`, `text`, `char_start`, `char_end`, `dates_in_text`, `mtime`
- 출처: `source_id`, `publisher`, `source_type`(`official|academic|media|informal`), `published`(YYYY-MM-DD 또는 빈 값), `url`, `provenance`(`real|synthetic` 또는 빈 값. 없으면 지어 채우지 않는다), `kind`(`origin|operating|appearance|other`), `about`(이름 배열)
- 운영 자료(`kind: operating`)만: `place_ids`(배열), `hours`, `closed`

**출처 메타데이터를 채우는 순서**
1. Markdown 머리 정보(`---`로 둘러싼 `키: 값`, 값 목록은 `[a, b]`). 값은 JSON 표기도 쓸 수 있다: `"`로 시작하거나 `[…]`이면 JSON으로 먼저 읽고(문자열 또는 문자열 목록), 실패하면 앞 규칙을 따른다. 대괄호가 든 문자열 값(예: `[공지] …` 제목)은 따옴표로 감싼다.
2. 폴더의 `_collection.json`(묶음 기본값)
3. 둘 다 없으면 `source_type=informal`, `kind=other`

**형식 판**: 판 2 색인(`chunks.jsonl`·`embeddings.npy`)은 읽지 않는다. 형식 판 오류로 거부한다.

**색인 명령**(`app/`에서): 원자료를 한 폴더로 모은 뒤 실행한다. 모으는 것은 `data/sweat/`와 `app/data/bulk/`이고, 모으기는 `app/sandbox/build_kb.sh`가 한다.
`uv run python -m retrieval index --input <모은 폴더> --index index/kb --embedder=local:<모델 폴더>`

### 설계 4.4 실행 폴더 `/hackathon/output/<run_id>/`

**`run_id`**: `YYYYMMDDTHHMMSSZ-<16진수 4자리>`. 이미 있으면 새로 뽑는다. 덮어쓰지 않는다.

**파일과 쓰는 쪽**(모두 루프가 쓴다. 코스 두 파일만 `save_course`가 쓴다)
- `run.json`: 아래 키
- `trace.jsonl`: 의사결정 기록
- 무거운 코스: `course.md`, `course.json`
- 그 밖의 답: `answer.md`, `answer.json`
- 게시 요청: `publish.json`
- 기준선: `baseline.json`

**`run.json` 키**
- `run_id`, `request`, `route`(`heavy|light|none`), `status`, `started_at`, `ended_at`
- `model_calls`: `{"router": n, "nemotron": n}`. 둘 다 Nemotron이고 `router`는 무게 판단 호출이다. 논리 호출 수다. 재전송은 세지 않는다.
- `tokens`: `{"router": {"input": n, "output": n}, "nemotron": {"input": n, "output": n}}`. 응답의 usage 합이다. usage가 없는 응답은 0으로 세고 `warnings`에 적는다.
- `index`: `{"collection": "kb", "fingerprint": "<manifest의 source_fingerprint>"}`
- `limits_hit`(목록), `files`(목록)
- 시각(`started_at`, `ended_at`, `publish.json`의 `ts`)은 모두 `trace.jsonl`의 `ts`와 같은 형식이다.

**상태값 `status`**(이 집합만 쓴다)

| 값 | 뜻 |
|---|---|
| `ANSWERED_LIGHT` | 가벼운 질문에 답함 |
| `UNAVAILABLE` | 무게 판단 실패, 응답 불가 |
| `ANSWERED_HEAVY` | 코스가 아닌 무거운 질문에 답함. 근거 등급이 붙는다. 읽기 거부도 여기에 적는다 |
| `COURSE_SAVED` | 코스 저장, 게시 요청 없음(사용자가 보내지 말라고 함) |
| `PUBLISH_PENDING_APPROVAL` | 게시 요청이 막혔고 시간 안에 승인 없음 |
| `PUBLISHED` | 승인 뒤 게시됨 |
| `PUBLISH_FAILED` | 정책 차단이 아닌 실패 |
| `FAILED` | 계획·실행 실패, 한도 초과 |
| `BASELINE_DONE` | 기준선 실행이 `baseline.json`을 냄(본 시스템 실행에는 쓰지 않는다) |

**`trace.jsonl` 한 줄**(UTF-8 JSON 한 줄)
- 키: `seq`, `ts`, `run_id`, `event`, `tool`, `args`, `result`, `why`, `model`, `prev_hash`
- `seq`: 1부터
- `ts`: UTC ISO 8601, 밀리초와 `Z`. 예: `2026-10-07T03:31:05.123Z`
- `event`: `route`, `light_answer`, `plan`, `plan_check`, `replan`, `step`, `publish_attempt`, `approval_wait`, `final`, `baseline` 가운데 하나
- `tool`: 도구 이름 또는 빈 값
- `result`: `{"kind", "summary"}`
- `why`: 모델이 준 이유 또는 코드 규칙
- `model`: `{"name", "purpose", "latency_ms", "usage"}` 또는 null
- `prev_hash`: 앞 줄(줄바꿈 제외) UTF-8 바이트의 sha256(16진수 64자). 첫 줄은 `0` 64개다.

**`answer.json` 키**: `run_id`, `request`, `route`, `status`, `answer`, `evidence_label`, `origins`, `conflicts`, `read_files`, `unknowns`, `warnings`
- `evidence_label`: 가벼운 답이면 `자료 근거 없음(일반 안내)`, 아니면 빈 값
- `origins`·`conflicts`: 4.6과 같은 꼴
- `read_files`: `path`, `kind` 목록

**`publish.json` 키**: `status`(`PUBLISHED|PUBLISH_PENDING_APPROVAL|PUBLISH_FAILED`), `target`(`github-issue`), `repo`, `attempts`, `issue_url`
- `attempts` 항목: `ts`, `result`(`BLOCKED_BY_POLICY|CREATED|HTTP_ERROR|NETWORK_ERROR`), `http_status`(정수 또는 null)

### 설계 4.5 계획 `plan`(Nemotron 출력, JSON)

```
{"goal": {"work": "<작품명 또는 빈 값>", "time_budget_min": <정수 또는 null>,
          "start": "<출발 역 이름 또는 빈 값>", "constraints": ["<제약>", ...],
          "publish_requested": true|false},
 "steps": [{"id": "s1", "tool": "<2.2절 도구 이름>", "args": {...4.2절}, "why": "<한 줄>"}, ...]}
```

- `publish_requested`는 요청이 보내기·게시·예약을 막으면 `false`다.
- 단계 수 한도는 12(조정값)다.
- 시연 문장의 기대 계획(참고, 고정 아님): `select_places` → `lookup_station` → `lookup_origin` → `lookup_operating` → `organize_names` → `grade_evidence` → `save_course` → `request_publish`

### 설계 4.6 코스 `course.json`

**최상위 키**: `run_id`, `request`, `goal`(4.5와 같음), `places`(순서 있는 배열), `total_min`(정수 또는 null), `excluded`, `unknowns`, `warnings`, `publish`(`status`·`url`)
- `excluded` 항목: `place_id`, `reason`

**`places` 항목**
- 이름: `order`, `place_id`, `current_name`, `in_work_name`, `scene`, `old_names`
- 역: `station`(`name`·`line`)
- 시간: `travel_min_from_prev`(정수 또는 null), `travel_mode`(`walk|transit|unknown`), `travel_basis`(`cited|estimate`), `travel_chunk_ids`, `stay_min`, `arrive_min`(출발부터 분, 정수 또는 null)
- 유래: `origins`. 항목 키는 `name`, `name_kind`(`current|old|in_work|station`), `summary`, `grade`(`A|B|C|D|null`), `source_ids`, `chunk_ids`, `input_paths`
- 충돌: `conflicts`. 항목 키는 `name`, `claims`(등급순 `origins` 항목 배열)
- 운영 정보: `operating`
  - `status`: `CHOSEN|NEEDS_ONSITE_CHECK|UNKNOWN`
  - 그 밖의 키: `hours`, `closed`, `source_ids`, `as_of`
  - 결론을 내지 않을 때만: `candidates`
- 오래된 자료: `stale`. 항목 키는 `source_id`, `reason`

**시간 정하기(`select_places`)**
- **구간 조사(Nemotron)**: 후보 장소와 출발점을 주고, 지식 색인(`search`)과 이번 실행에서 읽은 입력 자료를 근거로 방문 순서와 구간별 이동 시간을 묻는다. 답은 `[{"from", "to", "minutes", "mode", "chunk_ids"}]`이고, 모델 호출 1회다.
- **검사(코드)**
  - `minutes`가 1~180 정수가 아니면 그 구간을 `unknown`으로 둔다.
  - `chunk_ids`가 색인에 없으면 버린다. 남은 근거가 있으면 `cited`, 없으면 `estimate`다.
  - 후보 밖 장소나 같은 장소 두 번은 버리고 `warnings`에 적는다.
- **머무는 시간**: 테마 팩의 `stay_min`을 쓴다. 없으면 60분(조정값)을 쓰고 `estimate`로 적는다.
- **합계와 자르기(코드)**
  - `total_min` = 구간 시간 + 머무는 시간의 합이다. `unknown` 구간이 있으면 `total_min`은 null이고, 예산 검사를 못 했다고 `unknowns`에 적는다.
  - 예산을 넘으면 계획이 고른 후보 가운데 우선순위가 낮은 것부터 뺀다. 우선순위가 같으면 순서의 뒤쪽부터 뺀다. 뺀 장소는 `excluded`(이유 "시간 예산 초과")에 넣는다.
  - 순서는 모델이 낸 그대로 두고, 빠진 장소의 앞뒤 구간은 다시 묻지 않는다. 다시 묻지 않은 구간은 앞 구간과 뒷 구간을 더하고, 그 구간의 `travel_basis`를 `estimate`로 둔다.
- 코스와 화면에는 `estimate` 구간을 "추정"으로 표시한다.

**`course.md`**: 사람이 읽는 같은 내용이다. 이름 유래마다 등급과 출처(발행처·날짜)를 적는다.

### 설계 4.7 Hustler가 만들고 코드가 읽는 데이터(`data/sweat/`, Hustler 영역)

**테마 팩** `data/sweat/theme_packs/<pack_id>.json`
- 최상위: `pack_id`, `work_title`, `aliases`(예: 케데헌), `provenance`, `stations`, `places`
- `stations` 항목: `name`, `aliases`, `line`. 출발역 혜화와 각 장소의 가까운 역을 넣는다. `lat`·`lon`은 있으면 넣는다(선택).
- `places` 항목: `place_id`, `current_name`, `in_work_name`, `scene`, `old_names`, `station`(`stations`의 `name`), `stay_min`, `appearance_source_ids`, `priority`(정수, 작을수록 먼저). `lat`·`lon`은 선택이다.
- 이동 시간은 테마 팩에 넣지 않는다. 장소·역 사이 도보 시간 같은 동선 정보는 자료(`kind: other` 또는 `operating`)의 본문에 쓰면, Nemotron이 조사할 때 근거로 쓴다.

**자료** `data/sweat/sources/<source_id>.md`
- 머리 정보: `source_id`, `title`, `publisher`, `source_type`, `published`, `url`, `provenance`, `kind`, `about`
- 운영 자료(`kind: operating`)만: `place_ids`, `hours`, `closed`
- 그 아래가 본문이다.

**묶음 기본값(선택)**: `data/sweat/sources/_collection.json`

**변환**: Hustler가 조사 묶음(`data/sweat/kdh_pack/`)을 위 형식으로 옮긴다(팀장 결정). 조사 묶음의 메모 파일(`traps.md`, `open_questions.md`, `_parts/`, `BRIEF.md`)은 색인에 넣지 않는다. `build_kb.sh`는 `theme_packs/`와 `sources/`만 모은다.

**요건**(팀장 승인 초안 + 계산에 필요한 칸 추가)
- 테마 팩 1개(케데헌), 배경지 6~8곳
  - 혜화역에서 3시간 안에 고를 수 있는 곳 4곳 이상
  - 시간이 모자라 빠져야 할 먼 곳 2곳 이상
- 이름 유래 자료: 장소 이름 + 가까운 역 이름, 각 1~3건
- 일부러 넣을 것
  - 다른 유래를 말하는 자료 한 쌍(출처 종류 다르게)
  - 운영 정보가 옛 날짜·새 날짜로 다른 한 쌍
  - 무관한 자료 1건 이상
- 추가 1: 역 목록(`stations`, 좌표는 선택)
- 추가 2: 운영 자료의 `place_ids`·`hours`·`closed`
- 추가 3: 동선 정보(역에서 장소까지 도보 시간 등)는 자료 본문에. 실제 출처가 있으면 URL을 단다
- 실제 출처에서 옮긴 문장은 URL을 적고, 만든 내용은 `provenance: synthetic`으로 표시한다.
- 기한 13:30. 그 전에는 `app/common/fixtures/`의 가짜 입력(같은 형식, 가상의 작품·장소)으로 개발한다.

### 설계 4.8 평가 사례(Hustler가 쓰고 git 밖으로 넘김)

JSONL 한 줄에 사례 하나를 쓴다.

```
{"case_id": "E01", "split": "dev|holdout", "request": "<요청 문장>",
 "expect": {"route": "heavy|light", "status_in": ["<4.4 상태값>", ...],
            "must_include_place_ids": [...], "must_exclude_place_ids": [...],
            "max_total_min": <정수 또는 null>, "start_station": "<역 이름 또는 빈 값>",
            "must_flag_conflict_names": [...], "must_flag_stale_source_ids": [...],
            "must_not_cite_source_ids": [...], "publish_requested": true|false|null}}
```

- 비어 있는 기대 키는 채점하지 않는다.
- 사례 하나의 판정은 모든 채운 기대가 맞을 때만 통과다.

### 설계 4.9 명령

| 할 일 | 명령 |
|---|---|
| 실행(샌드박스 안) | `python -m loop ask "<요청>"` |
| 나중에 게시 | `python -m loop publish --run <run_id>` |
| 기준선(샌드박스 안) | `python -m loop baseline "<요청>"` |
| 색인(`app/`에서) | `uv run python -m retrieval index --input <모은 폴더> --index index/kb --embedder=local:<모델 폴더>` |
| 시험(`app/`에서, 키·네트워크 없이) | `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest` |
| 승인(호스트, 팀장) | `openshell policy set kculture --policy app/sandbox/policy-publish-approved.yaml --wait` |
| 회수(호스트, 팀장) | `openshell policy set kculture --policy app/sandbox/policy.yaml --wait` |
| 감사 묶음(호스트) | `sh app/sandbox/audit.sh <run_id>` |

- `ask`·`baseline`·`publish`의 표준 출력 마지막 줄은 언제나 `run_id: <run_id>`다. 실행 폴더를 만들기 전에 멈추면 `run_id: -`다. 오류 메시지는 표준 오류로 낸다.
- 호스트에서 `openshell sandbox exec`를 부를 때는 표준 입력을 닫는다(`< /dev/null`). 열어 두면 명령이 끝나도 돌아오지 않는다.
- 모델 엔드포인트는 환경변수로 고른다: `NIM_BASE_URL`(기본 NVIDIA API 카탈로그), `NIM_MODEL`, `NIM_API_KEY_ENV`(키가 든 변수 이름, 기본 `NVIDIA_API_KEY`. 팀의 Brev vLLM은 `VLLM_API_KEY`). `demo.sh`는 호스트에 설정된 이 셋을 샌드박스로 넘긴다. 키 값은 provider가 넣는다.

### 설계 4.10 한도(코드가 강제, 모두 조정값)

| 대상 | 한도 |
|---|---|
| 라우터(Nemotron) 논리 호출 | 실행당 2회(처음 + 다시 1회). 아래 8회와 따로 센다 |
| Nemotron 논리 호출(계획·도구·가벼운 답·기준선) | 실행당 8회 |
| 누적 토큰 | 128,000 |
| 실행 시간 | 300초(승인 대기 제외) |
| 승인 대기 | 180초 |
| 도구 단계 | 12 |
| `read_file` 한 번 | 64KB |

- 도구 단계 수는 실제로 실행한 계획 단계(다시 계획한 단계 포함)다. 게시 다시 보내기와 계획 전 `list_input`은 세지 않는다. 다시 보내기는 승인 대기 시간이 묶는다.
- NIM의 429·5xx 재전송 규칙은 기존 `NimClient`를 따른다(라우터 호출도 같다). 재전송은 논리 호출 수에 넣지 않는다.
- 토큰은 루프가 `NimClient`에 계수용 전송 함수(HTTP 전송을 감싸 응답의 usage를 읽는 함수)를 주입해 센다. `app/agent`는 고치지 않는다.
- 한도를 넘으면 `FAILED`로 끝내고 `limits_hit`에 적는다.

### 설계 5 경계 상황 규칙

**요청 쪽**
- 요청이 secrets·restricted 내용을 달라고 해도 라우터와 계획은 거르지 않는다. 2.5절의 secrets 장면대로 `read_file`이 실제로 시도하고 인프라가 막는다.
- 요청이 보내기를 막으면 게시 요청을 하지 않는다(2.2절).

**자료 쪽**
- 테마 팩에 요청한 작품이 없으면 `search_db`와 `list_input`·`read_file`로 찾는다. 그래도 장소가 없으면 코스 없이 `ANSWERED_HEAVY`로 "자료에 해당 작품의 배경지가 없음"을 답한다.
- 시간 예산이 없는 요청은 예산 없이 우선순위 순으로 최대 5곳(조정값)을 고른다.
- 운영 정보가 없는 장소는 `operating.status`를 `UNKNOWN`으로 두고 `unknowns`에 적는다. 만들어 내지 않는다.
- `read_file`의 본문이 64KB를 넘으면 앞 64KB만 쓰고 `TOO_LARGE`를 `warnings`에 적는다.

**게시 쪽**
- 게시 요청 중 네트워크가 끊기면 `NETWORK_ERROR`, 상태 `PUBLISH_FAILED`다. 정책 차단과 구분한다.
- 같은 실행에서 이슈는 많아야 1개다.
