# scripts/: 키·검사 도구

## 맡는 것

- `with_nvidia_key.py`: 키 래퍼. `.env`의 `NVIDIA_API_KEY` 한 줄을 자식 프로세스 환경에만 넣고, 자식 출력에서 키를 가린다. 예선 저장소 `bc0616f`의 `spikes/x1/with_nvidia_key.py` 사본이다.
- `nim_ping.py`: 키·모델 접근 확인. 짧은 요청 1건의 HTTP 상태만 낸다. 이 폴더에서 새로 만들었다.
- `secret_scan.py`: 커밋 전 비밀값·로컬 경로 검사. 예선 저장소 `bc0616f`의 `scripts/secret_scan.py` 사본이다.
- `orch.py`: 상위·하위 오케스트레이터 사이의 트랙 작업 공간(worktree·작업기록 폴더)과 지시·보고 파일·flag. 이 폴더에서 새로 만들었다(2026-10-07). 키를 다루지 않는다.

## 맡지 않는 것

- 제품(미션) 코드, 앱 패키지, 채점 스크립트, 시험. 이것들은 `app/` 아래에 둔다. 여기에 넣지 않는다.
- 발표 자료, 목업, 예시 데이터. Hustler가 자기 영역(`app/`, `docs/`, `scripts/`, 루트 파일 4개, 점으로 시작하는 경로의 밖)에 만든다.
- `.env`의 생성·편집. 팀장만 한다.
- NGC 키 등 `NVIDIA_API_KEY` 밖의 비밀값 주입. 키 래퍼를 늘려 해결하지 말고 팀장에게 넣는 방법을 먼저 묻는다.
- OpenShell provider·게이트웨이 설정을 읽는 코드.

## 지켜야 할 것

- 네 파일 모두 표준 라이브러리만 import한다. 시스템 `python3`(macOS 3.9.6)에서 돌아야 한다. 3.10 이후 문법(`match`, `X | Y` 타입 표기의 런타임 평가 등)과 외부 패키지를 넣지 않는다. 확인: 아래 두 명령이 둘 다 종료 0이다(2026-10-06 확인). 문법 오류와 import 오류도 실행하면 종료 1이라, 도구를 그냥 돌려서는 이 성질을 확인할 수 없다.
  ```
  /usr/bin/python3 -m py_compile scripts/with_nvidia_key.py scripts/nim_ping.py scripts/secret_scan.py scripts/orch.py
  /usr/bin/python3 -c "import sys; sys.path.insert(0, 'scripts'); import secret_scan, with_nvidia_key, nim_ping, orch"
  ```
- 키 값을 stdout·stderr·파일에 쓰지 않는다. `nim_ping.py`는 응답 본문도 내지 않는다.
- `nim_ping.py`는 인증 헤더를 `add_unredirected_header`로 붙인다. 리디렉션 때 키가 다른 호스트로 가지 않게 하기 위해서다. `add_header`나 `headers=`로 옮기지 않는다.
- `nim_ping.py`는 `.env`를 직접 읽지 않는다. 키는 환경변수로만 받는다.
- `with_nvidia_key.py`는 키를 디스크에 쓰지 않고, 자식 종료 코드를 그대로 돌려준다(신호 종료는 `128+n`). 출력은 `readline()`으로 줄 단위로 가린다. 블록 단위 읽기로 바꾸면 키가 경계에 걸려 가려지지 않을 수 있다.
- `secret_scan.py`의 패턴 문자열은 조각을 이어 만든다(키 접두어, 서비스키 이름, 홈·임시 폴더 경로). 이 파일과 문서가 스스로 걸리지 않게 하기 위해서다. 패턴을 한 덩어리 문자열 리터럴로 쓰지 않는다. 패턴 원문을 문서에 옮겨 적지 않는다.
- `secret_scan.py`는 행 내용을 출력하지 않는다. `파일:줄 종류`(범위 모드는 `커밋 파일 +행순번 종류`)만 낸다.
- 종료 코드 약속을 바꾸지 않는다: `nim_ping` 0(200)/1(다른 HTTP 상태, 또는 처리되지 않은 예외)/2(키 없음)/3(연결 실패), `secret_scan` 0/1/2, `with_nvidia_key` 자식 코드/2/127/128+n, `orch` 0/1(받을 것 없음·대상 없음·시간 초과)/2(사용법·전제 조건)/3(git·OS 실패). `inbox`·`wait`의 0/1은 기다리는 쪽이 판정에 쓴다. 다른 사람이 이 값으로 판정한다. 바꾸려면 팀장 승인을 받는다.
- `nim_ping`은 `HTTPError`와 `URLError`만 잡는다. 연결 뒤 응답을 기다리다 60초를 넘기거나(`socket.timeout`) 연결이 끊기면(`RemoteDisconnected`) traceback(예외 추적 출력)과 함께 종료 1이 되고, stdout에 `HTTP` 줄이 없다. Python 3.9의 `urllib`은 요청 보내기만 `URLError`로 감싸고 응답 읽기는 감싸지 않기 때문이다.
- `with_nvidia_key`의 키 조각 경고는 종료 코드를 바꾸지 않는다(자식 코드를 그대로 돌려준다). 경고 줄이 나왔는지는 stderr로 따로 본다.
- `with_nvidia_key`의 인자 해석 오류(`--env-file` 누락 등)는 argparse(파이썬 표준 인자 해석기)가 영어 사용법 메시지와 함께 종료 2로 끝낸다.

## 이 폴더만의 방식

- 경로·키 값은 코드에 적지 않고 인자나 환경변수로 받는다(`--env-file`, `NIM_MODEL`). `orch.py`는 main 폴더를 `git rev-parse --git-common-dir`로 찾는다. 로컬 절대 경로는 git 제외 파일(`log/launch.sh`)에만 쓴다.
- 사람이 읽는 오류는 한국어로 stderr에, 판정용 결과 줄은 stdout에 낸다.
- 두 사본 파일의 머리 주석에 사본 출처(예선 커밋)를 남긴다. 예선 쪽 경로를 가리키는 docstring(`spikes/x1/...`, `tests/test_secret_scan.py`)은 출처 설명이다. 이 폴더에 그 파일이 있다는 뜻이 아니다.
- `secret_scan.py`의 예선 전용 예외는 셋이고 성질이 다르다.
  - 컨테이너 경로 예외: `artifacts/openshell/`·`spikes/x1/` 아래 파일에서 샌드박스 컨테이너 홈 경로 두 개를 뺀다. 이 폴더에 그 경로가 없어 지금은 작동하지 않는다. 그 폴더를 만들면 그 아래 파일의 그 경로 행이 검사에서 빠진다. 만들지 않는다.
  - 이력 문서 기준선: `docs/research/` 바로 아래 특정 파일 이름과 행 sha256이 정확히 맞는 6행만 뺀다. 같은 파일·같은 행을 다시 만들지 않는 한 작동하지 않는다.
  - 봉인 폴더 물결표 예외: 경로 조건 없이 내용만 본다. **어느 파일에서든 늘 작동한다.** 예선 봉인 폴더 기본값(물결표 + `.tradesentry/sealed/`)으로 시작하는 홈 경로는 검사에 걸리지 않는다. 이 문자열을 문서·코드에 쓰지 않는다.
- `scan_range`의 `+행순번`은 파일 안 줄 번호가 아니라 범위 전체에서 센 추가 행의 누적 번호다.

## 시험할 것

자동 시험은 아직 없다. 고칠 때는 고치기 전에 아래를 시험으로 만든다.
- `secret_scan.scan_line`: 키 모양 1행, 사용자 홈 경로 1행, macOS 임시 폴더 1행, 물결표 경로 1행이 각각 해당 종류로 걸리고, 평문 1행과 URL 안의 같은 글자는 걸리지 않는다. 행이 여러 종류에 걸리면 종류마다 한 번 나온다.
- `secret_scan.main`: 인자 2개 이상이나 `-`로 시작하는 인자 → 2. git 밖 폴더 → 2.
- `with_nvidia_key.Redactor`: 키 전체, 앞 10글자 조각, 끝 6글자 조각이 각각 가려지고, 조각을 가렸을 때만 `fragment_seen`이 참이 된다. 키가 24자 미만이면 조각 검사를 하지 않는다.
- `with_nvidia_key.read_key`: `export ` 접두어, 따옴표 한 겹, 빈 값(→ 없음 처리), `NVIDIA_API_KEY_OLD=` 같은 다른 이름(→ 읽지 않음).
- `with_nvidia_key.main`: `--` 뒤 명령 없음 → 2, `--export-as lower` → 2, 없는 env 파일 → 2, 없는 명령 → 127.
- `nim_ping.main`: `NVIDIA_API_KEY` 없음 → 2(네트워크 호출 없이).
- `orch`(임시 git 저장소에서): 잘못된 트랙 이름·`app/` 밖 범위·이미 있는 트랙 → 2, `app/.orch/`를 빼지 않는 `.gitignore` → 2, `spawn` 뒤 main 폴더의 `git status --short`가 빈다, `send`의 종류 제한(`top`이 `report` → 2), `inbox` 있음 0·없음 1, `ack` 뒤 `inbox` 1, `wait --timeout 1` 시간 초과 1, 없는 트랙 이름 → 2, 이미 있는 `track/<트랙>` 브랜치 → 2, 없는 base → 3이고 찌꺼기 폴더가 없다, 트랙 worktree에서 `inbox`가 낸 본문 경로가 열린다, 양쪽이 동시에 30건씩 `send`해도 번호가 겹치지 않는다. 2026-10-07에 임시 저장소에서 손으로 확인했다(독립 검토가 찾은 번호 겹침을 `.NNNN.lock` 예약으로 고친 뒤 다시 확인). 자동 시험은 아직 없다.
- 시험은 실제 키 없이, 가짜 키 문자열로 돈다. 가짜 키도 키 모양 패턴에 걸리지 않게 조각을 이어 만든다.
