# X1: 자격 증명 주입과 게시 승인 경로 확인(2026-10-07 13:17 KST)

가장 위험한 연결을 첫 실행으로 끝까지 통과시킨 기록이다. 확인한 연결은 둘이다.
- OpenShell provider가 샌드박스 밖에서 실제 키를 넣는 경로(Claude, GitHub)
- 사람이 정책 파일을 적용해 게시를 승인하는 경로

타임박스는 45분이었고, 약 5분 만에 통과해 대체 경로는 쓰지 않았다.

## 조건

- OpenShell 0.0.116, 게이트웨이 `nemoclaw`, colima(Docker). 샌드박스 `kculture`(이미지 `kculture-sandbox:r1`, 2026-10-07 11:1x 생성)
- provider
  - 기존 `tradesentry-nvidia`(NIM)
  - 팀장이 자기 터미널에서 등록한 `kculture-claude`(기본 제공 프로필 `claude-code`)
  - 팀장이 자기 터미널에서 등록한 `kculture-github`(기본 제공 프로필 `github`, 게시 저장소 하나의 이슈 쓰기 권한만 있는 토큰)
- 에이전트와 worker는 토큰 값을 보지 않았다. 출력은 키 모양 줄을 걸러서 봤다.
- 새 샌드박스를 만들지 않았다. 떠 있는 `kculture`에 provider를 붙이고, 네트워크 정책만 실행 중에 바꿨다. 정적 계층(파일시스템·Landlock·프로세스)은 그대로다.

## 순서와 결과

| # | 한 일 | 명령(요지) | 결과 |
|---|---|---|---|
| 1 | provider 둘을 실행 중인 샌드박스에 붙임 | `openshell sandbox provider attach kculture kculture-claude`, `… kculture-github` | 둘 다 종료 0. `sandbox provider list`에 셋(tradesentry-nvidia, kculture-claude, kculture-github) |
| 2 | 샌드박스 안 키 모양 확인(값은 출력하지 않고 접두어만 판정) | 앱 Python으로 `os.environ` 검사 | `NVIDIA_API_KEY`·`ANTHROPIC_API_KEY`·`GITHUB_TOKEN` 모두 자리표시 값(`openshell:resolve:` 접두어). 실제 키 0건 |
| 3 | 기본 정책에 Claude 블록 추가(판 2) | `openshell policy set kculture --policy <기본+Claude> --wait` | 종료 0, `Policy version 2 loaded` |
| 4 | 앱 Python → Claude `POST /v1/messages`(모델 `claude-opus-5-5`, `max_tokens 16`) | `openshell sandbox exec … /opt/kculture/.venv/bin/python -c …` | HTTP 200, 응답 type `message` |
| 5 | 승인 전: 앱 Python → GitHub 이슈 POST | 같음 | HTTP 상태 없음. urllib 예외 `Tunnel connection failed: 403`(차단) |
| 6 | 승인: GitHub 이슈 블록을 더한 정책 적용(판 3) | `openshell policy set kculture --policy <승인 정책> --wait` | 종료 0, `Policy version 3 loaded` |
| 7 | 승인 뒤: 같은 게시 요청 | 같음 | HTTP 201, 시험 이슈 https://github.com/JoeHwangHee/kculture-course-publish/issues/1 |
| 8 | 회수: 판 2와 같은 정책 다시 적용(판 4) | `openshell policy set kculture --policy <기본+Claude> --wait` | 종료 0, `Policy version 4 loaded`(해시가 판 2와 같음) |

## OpenShell 감사 로그 발췌

`openshell logs kculture` 출력이다. 줄 맨 앞은 유닉스 초(UTC)다.

```
[1791346665.288] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] ALLOWED /opt/kculture/python/cpython-3.12.13-linux-aarch64-gnu/bin/python3.12(248) -> api.anthropic.com:443 [policy:claude_messages engine:opa]
[1791346665.338] [sandbox] [OCSF ] [ocsf] HTTP:POST [INFO] ALLOWED POST http://api.anthropic.com:443/v1/messages [policy:claude_messages engine:l7]
[1791346666.434] [sandbox] [OCSF ] [ocsf] NET:OPEN [MED] DENIED /opt/kculture/python/cpython-3.12.13-linux-aarch64-gnu/bin/python3.12(248) -> api.github.com:443 [policy:- engine:opa] [reason:endpoint api.github.com:443 is not allo…
[1791346685.204] [sandbox] [OCSF ] [ocsf] NET:OPEN [INFO] ALLOWED /opt/kculture/python/cpython-3.12.13-linux-aarch64-gnu/bin/python3.12(255) -> api.github.com:443 [policy:github_issue engine:opa]
[1791346685.216] [sandbox] [OCSF ] [ocsf] HTTP:POST [INFO] ALLOWED POST http://api.github.com:443/repos/JoeHwangHee/kculture-course-publish/issues [policy:github_issue engine:l7]
```

## 정책 이력(`openshell policy list kculture`)

| 판 | 해시 | 상태 | 뜻 |
|---|---|---|---|
| 4 | 4aecad12598c | Loaded | 회수(기본 + Claude) |
| 3 | e6f22f9588cd | Superseded | 승인(기본 + Claude + GitHub 이슈 POST 한 경로) |
| 2 | 4aecad12598c | Superseded | 기본 + Claude |
| 1 | 417d22542b60 | Superseded | 처음 만든 정책(NIM만) |

## 시험에 쓴 네트워크 블록

기본 정책(`app/sandbox/policy.yaml` 판 1)에 더한 블록이다. 정식 정책 파일 두 개는 G1 작업이 만든다.

```yaml
  claude_messages:
    name: claude-messages
    endpoints:
    - host: api.anthropic.com
      port: 443
      protocol: rest
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /v1/messages
    binaries:
    - path: /opt/kculture/python/**
  # 승인 정책에만 더한 블록
  github_issue:
    name: github-issue
    endpoints:
    - host: api.github.com
      port: 443
      protocol: rest
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /repos/JoeHwangHee/kculture-course-publish/issues
    binaries:
    - path: /opt/kculture/python/**
```

## 알게 된 것

- `openshell sandbox provider attach`로 실행 중인 샌드박스에 provider를 붙일 수 있다. 새 `exec` 프로세스에는 자리표시 값이 바로 들어간다.
- 승인 전 게시 차단은 앱에서 HTTP 응답이 아니라 연결 예외(`Tunnel connection failed: 403`)로 보인다. 앱의 차단 판정은 이 예외 문구를 쓴다(설계 2.4).
- 판 4와 판 2의 해시가 같다. 회수가 정확히 원래 정책으로 돌아갔다는 증거다.
- Claude 쪽 대체 경로는 필요 없었다.
