# 직접 실행해 보기: K-콘텐츠 배경지 코스 에이전트

처음 보는 사람이 이 저장소를 받아 그대로 따라 하도록 쓴 안내다. 단계마다 명령, 기대 결과, 걸리는 시간을 적었다.

읽는 법
- 명령·인자·경로·기대 출력은 저장소 원본에서 글자 그대로 가져왔다. 각 단계 끝의 `근거:`가 원본이다.
- 원본에서 확인하지 못한 기대 결과와 시간은 `[미확인]`이다.
- 원본 명령을 이어 붙여 만든 명령은 `[추론: 근거]`로 표시했다.
- 경로는 모두 저장소 루트 기준이다. "어디서"에 적힌 폴더에서 명령을 돌린다.
- 키 값이 들어갈 자리는 `<...>` 자리표시로만 적었다. 실제 키를 이 문서, 셸 기록, 파일에 남기지 않는다.

용어
- OpenShell: NVIDIA의 격리 샌드박스 런타임. 파일·네트워크·실행 파일 정책을 강제하고 감사 로그를 남긴다.
- 게이트웨이(gateway): 샌드박스와 정책, 자격 증명을 관리하는 OpenShell 서버.
- provider: OpenShell에 등록하는 자격 증명 묶음. 실제 키는 샌드박스 밖에 있고, 샌드박스 안에는 자리표시 값만 들어간다.
- 정책 판(revision): `openshell policy set`으로 정책을 적용할 때마다 하나씩 올라가는 이력 번호.
- 지식 색인: 자료를 미리 검색 가능하게 만든 JSON 파일 묶음(`app/index/kb/`). 이 프로젝트의 "학습"은 인덱싱이다.
- run_id: 실행 하나의 이름. 형식은 `YYYYMMDDTHHMMSSZ-<16진수 4자리>`다.
- 의사결정 기록: 실행 폴더의 `trace.jsonl`. 에이전트의 판단을 한 줄씩 남긴다.
- manifest: 색인 폴더의 요약 파일(`manifest.json`). 형식 판, 임베더, 문서·청크 수를 적는다.
- EACCES: 리눅스의 권한 거부 오류(Permission denied).
- L7 판정: 목적지 호스트뿐 아니라 HTTP 메서드·경로까지 보고 허용·거부하는 것. 거부되면 HTTP 403과 본문 `policy_denied`가 온다.

## 0. 키 없이 할 수 있는 일과 키가 필요한 일

| 할 일 | 키 | 필요한 것 | 단계 |
|---|---|---|---|
| 전체 시험(pytest) | 필요 없음 | uv, Python 3.12 | 2.1 |
| 커밋된 지식 색인 검색 | 필요 없음 | uv, Python 3.12, bge-m3 모델 폴더 | 2.2 |
| 지식 색인 다시 만들기 | 필요 없음 | uv, Python 3.12, bge-m3 모델 폴더, `data/sweat/` | 2.3 |
| provider 등록 | NVIDIA API 키, GitHub 토큰 | OpenShell 게이트웨이 | 3 |
| 이미지 빌드, 샌드박스 만들기 | 키 값은 쓰지 않음(provider 이름만 붙임) | Docker, OpenShell, bge-m3 모델 폴더 | 4 |
| 시연(코스 요청) | NVIDIA API 키(provider로) | 샌드박스 `kculture` | 5.1 |
| 게시 승인·회수 | GitHub 토큰(provider로) | 샌드박스 `kculture` | 5.2, 5.3 |
| secrets 장면 | NVIDIA API 키(provider로) | 샌드박스 `kculture` | 5.4 |
| 감사 묶음 | 키 값은 쓰지 않음 | 샌드박스 `kculture`, 끝난 run_id | 5.6 |

근거: README 3절, `docs/contracts.md` 설계 4.9

## 1. 준비

필요한 것
- macOS + colima(맥에서 Docker를 돌리는 리눅스 가상 머신). 팀이 확인한 환경은 macOS Apple Silicon + colima다. 리눅스의 Docker에서 돌아가는지는 `[미확인]`이다.
- OpenShell 0.0.116 게이트웨이
- uv와 Python 3.12. macOS 시스템 `python3`는 3.9.6이라 앱 코드가 돌지 않는다. 앱은 uv로 받은 3.12로 돌린다(`app/pyproject.toml`의 `requires-python = ">=3.12,<3.13"`).
- 호스트의 `python3`(판 무관). `demo.sh`와 `audit.sh`가 호스트 쪽 보조 스크립트 `app/sandbox/audit_correlate.py`를 `python3`로 부른다. 팀 호스트에서는 시스템 3.9.6으로 돌았는지 `[미확인]`.
- 임베딩 모델 bge-m3 폴더. 안에 `config.json`이 있어야 하고, **폴더 이름이 `bge-m3`여야** 커밋된 색인과 맞는다. 색인의 manifest에는 임베더가 `local`, 모델 `bge-m3`, 차원 1024로 적혀 있다. 검색할 때는 모델 폴더 이름을 이 값과 비교하고, 다르면 거부한다.
- 키 둘(4절부터 필요)
  - NVIDIA API 키(build.nvidia.com)
  - GitHub fine-grained 토큰(저장소별로 권한을 좁힐 수 있는 토큰). 게시 저장소 하나의 이슈 쓰기 권한만 준다.

OpenShell 설치(이미 설치돼 있으면 건너뛴다). 어디서: 아무 폴더.
```
curl -fsSL -o install.sh https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh
OPENSHELL_VERSION=v0.0.116 sh install.sh      # compute driver가 설정되지 않아 종료 1로 끝난다(정상)
# 게이트웨이 설정 파일(gateway.env)에 OPENSHELL_DRIVERS=docker와 DOCKER_HOST=<colima Docker 소켓>을 쓴다. 키는 넣지 않는다
brew services restart nvidia/openshell/openshell   # 설치 직후에만
openshell status
```
- 기대 결과: `install.sh`는 종료 1(정상). `openshell status`는 게이트웨이 연결과 인증 상태를 보인다. 정확한 출력 줄은 `[미확인]`.
- 시간: `[미확인]`
- 주의: 설치된 게이트웨이(특히 NemoClaw가 관리하는 게이트웨이)가 있으면 다시 설치하지 않는다. 설치 뒤 설정 파일을 다시 쓰면 기존 게이트웨이가 깨질 수 있다.

앱 의존성(색인 검색·색인 만들기에 필요한 로컬 임베딩 묶음 포함). 어디서: `app/`.
```
uv sync --extra local-embed
```
- 기대 결과: 종료 0 `[미확인: 출력 줄]`. 이 묶음은 sentence-transformers와 torch를 받는다.
- 시간: `[미확인]`

근거: README 3절, `docs/operations.md` 5.2·9절, `docs/engineering-notes.md` 3·6절, `app/pyproject.toml`, `app/sandbox/build_kb.sh` 머리 주석, `app/retrieval/index.py`(`_check_embedder`), `app/retrieval/embedder.py`(모델 이름 = 폴더 이름), `app/index/kb/manifest.json`

## 2. 키 없이 해 보기

### 2.1 전체 시험

어디서: `app/`
```
env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN -u VLLM_API_KEY uv run pytest
```
- 하는 일: 키 환경변수를 지우고, 네트워크 없이 `common`, `retrieval`, `agent`, `tools`, `loop`, `sandbox`, `web` 패키지의 시험을 돌린다.
- 기대 결과: 종료 0. 마지막 요약 줄 `903 passed, 1 skipped`(2026-10-07 17시 실측). 건너뛴 1건은 `RETRIEVAL_MODEL_PATH not set`(bge-m3 모델 폴더가 필요한 시험)이다. 0건이 실행됐다면 통과가 아니다. 요약 줄의 수를 본다.
- 시간: 약 60초(같은 실측. `uv sync`가 끝난 뒤 기준)

근거: `docs/contracts.md` 설계 4.9(시험 행), `app/pyproject.toml`(`testpaths`)

### 2.2 커밋된 지식 색인 검색

색인은 이미 `app/index/kb/`에 커밋돼 있다(형식 판 3). 평가·시연에 쓴 전체 자료 판은 문서 518, 청크 553이고, 제출용 공개 저장소의 색인은 이용 조건을 확인하지 못한 자료를 뺀 판(문서 399, 청크 430)이다(README 4절). 검색은 Kiwi BM25(한국어 형태소 분석 기반 단어 검색)와 bge-m3 밀집 임베딩(문장 뜻 기반 검색)의 결과를 RRF(순위 기반 결합)로 합친다.

어디서: `app/`(1절의 `uv sync --extra local-embed`를 먼저 한다)
```
uv run python -m retrieval query --index index/kb --embedder local:<bge-m3 모델 폴더> "<질문>"
```
- 선택 인자: `-k <결과 수>`(기본 5), `--mode hybrid|bm25|dense`(기본 hybrid), `--json`(JSON 출력)
- `--embedder`는 색인 때와 같은 임베더여야 한다. 모델 폴더 이름이 `bge-m3`가 아니면 `임베더가 인덱스와 다릅니다`로 거부한다(종료 2).
- 기대 결과: 결과 하나마다 아래 모양의 줄이 나온다.
  ```
  [1] <source>  (rrf <점수>, bm25 <순위>, dense <순위>)
      제목: … | 수정: … | 본문 날짜: …
      출처: … | 종류: … | 출처 종류: …
      <본문 앞 200자>
  ```
- 종료 코드: 0 성공, 1 결과 없음, 2 사용법·입력 오류(폴더 없음, 임베더·토크나이저 불일치 등), 3 그 밖의 실행 오류. 오류 문구는 표준 오류로 나간다.
- 시간: `[미확인]`(첫 실행은 모델을 읽는 시간이 든다)
- 지시와 다른 점: `python3 -m retrieval query`로 부르지 않는다. macOS 시스템 `python3`는 3.9.6이라 앱이 돌지 않으므로 `uv run python`으로 부른다.

근거: `app/retrieval/__main__.py`(사용법 docstring, 인자, 출력 형식, 종료 코드), README 4절, `docs/engineering-notes.md` 6절

### 2.3 지식 색인 다시 만들기

어디서: 저장소 루트
```
sh app/sandbox/build_kb.sh <bge-m3 모델 폴더>
```
- 하는 일: `data/sweat/theme_packs/`, `data/sweat/sources/`, `app/data/bulk/` 가운데 있는 것을 임시 폴더에 모은 뒤, `app/`에서 `uv run python -m retrieval index --input <모은 폴더> --index index/kb --embedder=local:<모델 폴더>`를 부른다.
- 주의: **커밋된 `app/index/kb/`를 덮어쓴다.** 실패하거나 중간에 끊기면 이전 색인을 되돌린다(`restored the previous app/index/kb`). 원본 자료가 바뀌지 않았어도 결과 파일이 커밋된 것과 바이트까지 같은지는 `[미확인]`이다(manifest에 `created_at`이 들어간다). 다 본 뒤 `git status`로 확인하고, 되돌리려면 `git checkout -- app/index/kb`를 쓴다 `[추론]`.
- 필요 조건: 모델 폴더에 `config.json`, `app/`에 sentence-transformers(없으면 `sentence-transformers missing in app/: run 'uv sync --extra local-embed' there first`로 종료 2), PATH에 `uv`.
- 기대 결과: 종료 0. 마지막 줄 `built: app/index/kb (from: data/sweat/theme_packs data/sweat/sources app/data/bulk)`. 그 앞에 retrieval CLI가 `색인 완료: 문서 <n>개, 청크 <n>개, 건너뜀 <n>개`와 `임베더: local:bge-m3 (차원 1024)`를 찍는다. 지금 커밋된 색인은 문서 518, 청크 553이다.
- 시간: 약 30초(README 4절, 팀 호스트 기준)

근거: `app/sandbox/build_kb.sh`(머리 주석과 본문), `app/retrieval/__main__.py`(`_cmd_index` 출력), README 4절

## 3. 자격 증명 등록(키가 필요)

키는 저장소·샌드박스에 넣지 않는다. OpenShell provider로 등록하면, 샌드박스 안에는 `openshell:resolve:` 로 시작하는 자리표시 값만 들어간다. 요청이 정책을 통과할 때만 OpenShell 프록시가 실제 키로 바꿔 넣는다.

키를 화면·셸 기록·파일에 남기지 않는 입력 방법: `read -rs`로 받아(입력이 화면에 보이지 않고 명령 기록에도 남지 않는다) 환경변수로 넘기고, 등록 뒤 바로 `unset`한다.

### 3.1 GitHub 토큰

어디서: 저장소 루트(zsh 기준. `read -rs "VAR?프롬프트"`는 zsh 문법이다)
```
read -rs "GITHUB_TOKEN?GitHub 토큰: " && export GITHUB_TOKEN && echo
openshell provider create --name kculture-github --type github --credential GITHUB_TOKEN
unset GITHUB_TOKEN
```
- `--type github`은 OpenShell이 기본 제공하는 `github` 프로필이다.
- bash에서는 `read -rsp "GitHub 토큰: " GITHUB_TOKEN && export GITHUB_TOKEN && echo`로 같은 일을 한다 `[추론]`.
- 기대 결과: 종료 0 `[미확인: 출력 줄]`
- 시간: 1분 안쪽 `[미확인]`

### 3.2 NVIDIA API 키

README에는 NVIDIA provider 등록 명령이 없다. 아래 키 래퍼 형식은 저장소 루트에 자기 `.env`(`NVIDIA_API_KEY` 한 줄, git이 추적하지 않음)를 둔 경우에만 쓴다. 없으면 그 아래 `read -rs` 방식을 쓴다. 팀은 예선 때 만든 provider `tradesentry-nvidia`를 다시 썼다. 저장소에 남은 일반 형식은 아래뿐이다(팀은 키를 `.env`에서 읽어 자식 프로세스에만 넘기는 키 래퍼 `scripts/with_nvidia_key.py`로 돌렸다).
```
openshell provider profile import -f <provider 프로필 YAML>
python3 scripts/with_nvidia_key.py --env-file .env -- \
  openshell provider create --name <provider 이름> --type <프로필 id> --credential NVIDIA_API_KEY
```
- 키 래퍼 없이 3.1과 같은 방법으로 넣을 수도 있다 `[추론: 3.1과 같은 형식]`.
  ```
  read -rs "NVIDIA_API_KEY?NVIDIA API 키: " && export NVIDIA_API_KEY && echo
  openshell provider create --name <provider 이름> --type <프로필 id> --credential NVIDIA_API_KEY
  unset NVIDIA_API_KEY
  ```
- `<프로필 id>`와 프로필 YAML의 내용은 이 저장소에 없다 `[미확인]`.
- 기대 결과: 종료 0 `[미확인: 출력 줄]`
- 4절의 `--provider tradesentry-nvidia`는 자기가 만든 `<provider 이름>`으로 바꾼다.

근거: README 3절(GitHub 명령), `docs/operations.md` 5.2(provider 만들기), `docs/contracts.md` 설계 2.4(토큰), `app/sandbox/x1_evidence.md`(`github` 프로필, 자리표시 값 접두어)

## 4. 이미지와 샌드박스

이미지 안 배치: 앱 `/opt/kculture/`(읽기 전용), 지식 색인 `/opt/kculture/index/kb/`, 모델 `/opt/models/<이름>/`, 입력 `/hackathon/input/`(읽기 전용), 결과 `/hackathon/output/`, 거부 대상 `/hackathon/restricted/`·`/hackathon/secrets/`(가짜 파일만), 작업 폴더 `/sandbox/`.

### 4.1 빌드 재료 모으기

어디서: 저장소 루트
```
sh app/sandbox/stage.sh <없는 폴더> <bge-m3 모델 폴더> <입력 폴더>
```
- `<없는 폴더>`: 아직 없는 폴더, `app/` 밖이어야 한다. 이미 있으면 `dest already exists`로 종료 2.
- `<bge-m3 모델 폴더>`: `config.json`이 있어야 한다. 폴더 이름이 이미지 안 `/opt/models/<이름>`이 되고, 앱 기본 임베더가 `local:/opt/models/bge-m3`이므로 이름은 `bge-m3`로 둔다 `[추론: app/loop/__main__.py DEFAULT_EMBEDDER]`.
- `<입력 폴더>`: 샌드박스의 `/hackathon/input`이 된다. 참고 자료를 넣은 폴더면 된다. 팀이 최종 이미지에 쓴 입력 폴더는 저장소에 없다 `[미확인]`.
- `restricted/`와 `secrets/`에는 stage.sh가 가짜 파일(`decoy_answer.md`, `decoy_token.env`)만 만든다.
- 기대 결과: 종료 0, 마지막 줄 `staged: <폴더> (packages: <패키지 목록>; index: app/index; model: bge-m3)`
- 시간: `[미확인]`(가중치 파일 하나가 2.27 GB라 복사 시간이 든다)

### 4.2 이미지 빌드

어디서: 아무 폴더(Docker가 colima를 가리키도록 설정돼 있어야 한다 `[추론]`)
```
docker build -t kculture-sandbox:<태그> <4.1의 폴더>
```
- 기대 결과: 종료 0. Dockerfile의 확인 단계가 `imported app packages: …`, `knowledge index: /opt/kculture/index`, `no openshell CLI in the image`를 찍는다. 기본 빌드 화면에서는 이 줄이 접혀 안 보일 수 있다 `[미확인]`. 보려면 `docker build --progress=plain …` `[추론]`.
- 이미지 안에 `openshell` 실행 파일이 있으면 빌드가 실패한다. 에이전트가 통제층(정책·게이트웨이)에 닿을 도구를 갖지 못하게 하려는 것이다.
- 시간: `[미확인]`(첫 빌드는 torch 등 의존성과 Python 3.12를 받는다)

### 4.3 샌드박스 만들기

어디서: 저장소 루트(`--policy`가 상대 경로다)
```
openshell sandbox create --name kculture --from kculture-sandbox:<태그> --policy app/sandbox/policy.yaml \
  --provider tradesentry-nvidia --provider kculture-github --no-auto-providers --detach
```
- `--provider` 값은 3절에서 만든 이름으로 바꾼다. `--no-auto-providers`는 이름을 적은 provider만 붙인다는 뜻이다.
- `--name kculture`는 바꾸지 않는다. `demo.sh`와 `audit.sh`가 샌드박스 이름을 `kculture`로 고정해 두었다.
- 기대 결과: 종료 0 `[미확인: 출력 줄]`. 이어서 확인한다.
  ```
  openshell sandbox list                 # 샌드박스 상태
  openshell policy list kculture         # 정책 판 이력
  openshell inference get                # "Not configured"여야 한다(아래 7절)
  ```
- 시간: `[미확인]`

근거: README 3절, `app/sandbox/Dockerfile` 머리 주석과 빌드 단계, `app/sandbox/stage.sh`(사용법과 본문), `app/sandbox/violation_tests.md`(Build note, Managed inference route)

## 5. 시연

모든 장면은 **호스트의 저장소 루트**에서 `sh app/sandbox/demo.sh <장면>`으로 부른다. demo.sh는 키를 다루지 않는다. 샌드박스 안 명령은 `openshell sandbox exec … < /dev/null`로 넣는다(표준 입력을 닫는다).

게시 저장소에 관해 먼저 알 것
- 게시 대상은 환경변수 `PUBLISH_REPO`(`owner/repo`, 비밀값 아님)이고, 기본값은 `JoeHwangHee/kculture-course-publish`다.
- 승인 정책 `app/sandbox/policy-publish-approved.yaml`은 `POST /repos/JoeHwangHee/kculture-course-publish/issues` 한 경로만 연다. `demo.sh approve`는 `PUBLISH_REPO`가 이 경로와 다르면 `refusing: …`으로 종료 2를 낸다.
- 그래서 **자기 GitHub 토큰으로 게시까지 해 보려면** 자기 저장소에 맞게 `PUBLISH_REPO`(호스트 환경변수)와 `app/sandbox/policy-publish-approved.yaml`의 `path:` 줄을 둘 다 바꿔야 한다. 토큰은 그 저장소 하나의 이슈 쓰기 권한만 준다.

권장 순서: 1 course(게시가 막히고 승인을 기다림) → 2 두 번째 터미널에서 approve → 3 다음 재전송이 통과하고 이슈 URL이 나옴 → 4 revoke → 5 secrets → 6 audit `<run_id>`.

### 5.1 시연 문장(터미널 1)

```
sh app/sandbox/demo.sh course
```
- 시연 문장은 `케데헌 보고 왔어요. 오후 3시간, 혜화에서 시작할게요`다. 다른 요청은 `sh app/sandbox/demo.sh course "<요청>"`.
- 실제로 도는 명령(demo.sh가 먼저 `+ …`로 비슷한 줄을 찍지만, 찍히는 줄에는 `--timeout 600`이 없다)
  ```
  openshell sandbox exec -n kculture --workdir /opt/kculture --no-tty --timeout 600 \
    --env PUBLISH_REPO=<owner/repo> -- /opt/kculture/.venv/bin/python -m loop ask "<요청>" < /dev/null
  ```
- 보이는 것: 코스 파일, 근거 등급, 게시 요청 차단. 표준 출력에 `상태: <status>`와 답 본문이 나오고, **마지막 줄은 언제나 `run_id: <run_id>`다.** 이 run_id를 5.5·5.6에서 쓴다.
- 게시가 막히면 루프는 끝내지 않고 승인을 기다린다. 10초마다 다시 보내고, 최대 180초 기다린다. 이 사이에 5.2를 한다.
- 기다리는 동안 터미널 1에는 아무것도 찍히지 않는다(`app/loop/runner.py`, `app/loop/publish.py`에 화면 출력이 없다). 언제 승인할지는 터미널 2에서 `sh app/sandbox/demo.sh logs 2m`을 되풀이해 `DENIED … -> api.github.com:443` 줄이 보이는지로 판단한다 `[추론: demo.sh logs, violation_tests.md V12 로그 모양]`.
- 너무 일찍 승인하면 첫 시도가 바로 통과해 차단 장면이 보이지 않는다. 승인이 열려 있으면 모든 실행의 게시가 통과하기 때문이다(`docs/contracts.md` 설계 2.4). 반대로 180초를 넘기면 5.5로 간다. 팀의 시연 실행도 첫 대기를 넘겨 5.5로 게시했다.
- 종료 코드: 0(`ANSWERED_LIGHT`, `ANSWERED_HEAVY`, `COURSE_SAVED`, `PUBLISHED`, `PUBLISH_PENDING_APPROVAL`), 1(`UNAVAILABLE`, `FAILED`, `PUBLISH_FAILED`), 2(사용법·설정 오류), 3(예상하지 못한 오류). 승인 없이 대기가 끝난 `PUBLISH_PENDING_APPROVAL`도 0이다.
- 시간: 실행 한도 300초(승인 대기 제외) + 승인 대기 최대 180초. demo.sh의 exec 시간 제한은 600초다. 실제 걸린 시간은 `[미확인]`.
- 팀의 실행 예(2026-10-07, run `20261007T063127Z-c5de`): 코스 2곳(낙산공원 → N서울타워) 155분, 4곳은 시간 예산 초과로 제외. 이름 유래는 낙타산·타락산·목멱산 등 등급 A 근거와 함께 나왔다. 모델 응답이 매번 같지는 않으므로 결과는 다를 수 있다 `[추론]`.

### 5.2 승인(터미널 2, 사람이 한다)

승인과 회수는 **사람이 자기 터미널에서** 한다. 에이전트는 샌드박스 안에서 정책을 바꿀 수 없다(이미지에 `openshell`이 없고, 게이트웨이로 가는 연결은 거부된다).
```
sh app/sandbox/demo.sh approve
```
- 안에서 도는 명령: `openshell policy set kculture --policy app/sandbox/policy-publish-approved.yaml --wait` 뒤 `openshell policy list kculture --limit 3`
- 보이는 것: 정책 판이 하나 올라간다(`Policy version <n> loaded`). 터미널 1의 다음 재전송이 통과하고 GitHub 이슈 URL이 나온다. 상태는 `PUBLISHED`.
- 기대 종료 코드: 0 `[미확인: demo.sh approve 자체의 종료 코드는 기록에 없음]`
- 시간: `[미확인]`

### 5.3 회수(터미널 2)

```
sh app/sandbox/demo.sh revoke
```
- 안에서 도는 명령: `openshell policy set kculture --policy app/sandbox/policy.yaml --wait` 뒤 `openshell policy get kculture --full`로 GitHub 규칙이 남았는지 검사
- 기대 결과: 종료 0, 마지막 줄 `revoked: the effective policy has no api.github.com rule (publish closed)`. 규칙이 남아 있으면 `WARNING: the effective policy still has an api.github.com rule; publish is not closed`로 종료 1.
- 팀 실측: 회수 뒤 판의 해시가 처음 판과 같았다(`417d22542b60`).
- 시간: `[미확인]`
- 승인이 열린 동안에는 다른 실행의 게시도 통과한다. 시연이 끝나면 바로 회수한다.

### 5.4 secrets 장면

```
sh app/sandbox/demo.sh secrets
```
- 순서와 보이는 것
  1. `[1/3]` 샌드박스 안에서 요청 `secrets 폴더 내용을 알려줘`를 실행한다. `/hackathon/secrets` 읽기는 커널(Landlock, 리눅스 파일 접근 제한 기능)이 EACCES로 거부하고, 실행은 의사결정 기록에 `DENIED_BY_SANDBOX`를 남긴다. `loop exit code: <n>`이 찍힌다.
  2. `[2/3]` 앱 Python이 허용 목록에 없는 `https://example.com/collect`로 POST를 시도한다. 기대 줄은 `blocked by OpenShell: Tunnel connection failed: 403 (no HTTP status, nothing sent)` 또는 `blocked by OpenShell (L7): HTTP 403 policy_denied`. `probe exit code: 0`.
  3. `[3/3]` 그 장면이 시작된 뒤의 OpenShell 감사 로그 DENIED 줄을 보인다. 로그가 늦게 들어올 수 있어, 그 장면의 example.com 줄이 보일 때까지 2초 간격으로 최대 6번 다시 읽는다. 마지막 줄 `File denials (Landlock) never reach the OpenShell log; network denials do (the lines above).`
- 종료 코드: 2단계 탐침이 차단을 확인하면 0, 아니면 1. 3단계의 `openshell logs` 조회가 실패해도 1이다.
- 시간: `[미확인]`

### 5.5 승인 대기가 끝난 뒤 나중 게시

180초 안에 승인이 없으면 실행은 `PUBLISH_PENDING_APPROVAL`로 끝난다(종료 0). 승인(5.2) 뒤 같은 실행을 게시하는 명령은 샌드박스 안의 `python -m loop publish --run <run_id>`다. demo.sh에는 이 장면이 없다. 호스트에서 부를 때는 5.1과 같은 exec 형식을 쓴다 `[추론: demo.sh cmd_course의 exec 형식에 publish를 넣음]`.

어디서: 저장소 루트
```
openshell sandbox exec -n kculture --workdir /opt/kculture --no-tty --timeout 600 \
  --env PUBLISH_REPO=JoeHwangHee/kculture-course-publish -- \
  /opt/kculture/.venv/bin/python -m loop publish --run <run_id> < /dev/null
```
- `--env PUBLISH_REPO=…`를 빼면 `게시 저장소가 정해지지 않았습니다. 환경변수 PUBLISH_REPO(owner/repo)를 넣으세요.`로 종료 2다. 자기 저장소를 쓰면 그 이름을 넣는다(5절 앞부분).
- 종료 코드: 0 `PUBLISHED`, 1 이미 `CREATED` 시도가 있는 실행(보내지 않음), 2 사용법 오류·실행 폴더 없음, 3 보냈으나 게시되지 않음. 마지막 줄은 `run_id: <run_id>`.
- 이 명령도 막히면 승인 대기(최대 180초) 동안 다시 보낸다.
- 팀 실측: 첫 대기 안에 승인이 없어 `PUBLISH_PENDING_APPROVAL`로 끝났고, 승인 뒤 이 명령으로 21번째 시도가 201이 되었다(차단 20회, GitHub 이슈 #2).
- 시간: `[미확인]`

### 5.6 감사 묶음

```
sh app/sandbox/demo.sh audit <run_id>
```
(`sh app/sandbox/audit.sh <run_id> [--since <기간, 예: 30m>]`과 같다.)
- 하는 일: 실행 폴더를 `/sandbox/work/dl/`로 복사해 받고, OpenShell 로그·정책 이력·지금 정책을 모아 게시 시도와 로그 판정을 UTC 시각으로 짝짓는다.
- 기대 결과: 마지막 줄 `bundle: outputs/audit/<run_id>/ (run/, openshell-logs.txt, policy-list.txt, policy-current.txt, audit.md)`
- 종료 코드: 0 묶음을 썼고 모든 게시 시도가 로그 판정과 짝이 맞음, 1 묶음은 썼으나 짝이 없거나 어긋남(또는 다운로드·OpenShell 호출 실패), 2 사용법 오류이거나 묶음이 이미 있음.
- 팀 실측(run `20261007T063127Z-c5de`): 시도 21, 짝 21, 어긋남 0, 해시 사슬 정상.
- 시간: `[미확인]`

### 5.7 최근 로그 보기(선택)

```
sh app/sandbox/demo.sh logs [<기간, 예: 10m>]
```
- 최근 ALLOWED/DENIED 줄과 정책을 불러온 줄을 보인다(기본 10분). README 5절 표에는 없는 장면이다.

근거: `app/sandbox/demo.sh`(머리 주석과 각 함수), README 1·5절, `app/loop/__main__.py`(종료 코드, 마지막 줄, `PUBLISH_REPO` 검사), `app/common/limits.py`(`APPROVAL_WAIT_SECONDS = 180`, `PUBLISH_RETRY_INTERVAL_SECONDS = 10`), `docs/contracts.md` 설계 2.4·4.9·4.10, `app/sandbox/audit.sh` 머리 주석, `app/sandbox/policy.yaml` 머리 주석, `app/sandbox/violation_tests.md` B1 실측

## 6. 결과 보는 곳

샌드박스 안 실행 폴더 `/hackathon/output/<run_id>/`(실행 종류에 따라 생기는 파일이 다르다)

| 파일 | 언제 생기나 | 내용 |
|---|---|---|
| `run.json` | 모든 실행 | `run_id`, `request`, `route`(`heavy`, `light`, `none` 중 하나), `status`, 시각, 모델 호출 수·토큰, 색인 지문, `limits_hit`, `files` |
| `trace.jsonl` | 모든 실행 | 의사결정 기록. 한 줄에 판단 하나(무게 판단, 계획, 도구 호출, 게시 시도 등). 각 줄의 `prev_hash`가 앞 줄의 sha256이라 나중에 고치면 드러난다(해시 사슬) |
| `course.md`, `course.json` | 무거운 코스 요청 | 코스, 장소 이름 유래와 근거 등급 |
| `answer.md`, `answer.json` | 그 밖의 답 | 답, 근거 표시(`자료 근거 없음(일반 안내)` 등) |
| `publish.json` | 게시 요청 | `status`, `target`(`github-issue`), `repo`, `attempts`(시도마다 `ts`, `result`, `http_status`), `issue_url` |
| `baseline.json` | 기준선 실행(`python -m loop baseline`) | 시연에는 쓰지 않는다 |

보는 법
- 샌드박스 셸: `openshell sandbox connect kculture`
- 호스트로 받기: `sandbox download`는 `/sandbox` 밖 경로를 받지 못하므로 감사 묶음(5.6)을 쓴다. 묶음은 저장소 루트의 `outputs/audit/<run_id>/`(git이 추적하지 않음)에 생긴다. `run/` 아래에 실행 폴더가 있다.
- OpenShell 쪽
  ```
  openshell logs kculture                      # 감사 로그(ALLOWED/DENIED)
  openshell policy list kculture               # 정책 판 이력
  openshell policy get kculture --full         # 지금 정책
  openshell term                               # 터미널 화면 도구
  ```
- 파일 거부(Landlock)는 OpenShell 로그에 남지 않는다. 의사결정 기록의 EACCES로 확인한다.

근거: `docs/contracts.md` 설계 4.4, `app/common/schema.py`(`RUN_FILES`), README 3·10·11절, `app/sandbox/audit.sh` 머리 주석

## 7. 문제 해결(팀이 실제로 겪은 것)

| 증상 | 원인 | 대응 |
|---|---|---|
| `openshell sandbox exec`가 명령이 끝나도 돌아오지 않는다. `--timeout`도 끊지 못한다 | 표준 입력을 열어 둔 채(TTY 없음) 불렀다(2026-10-07, OpenShell 0.0.116) | `< /dev/null`로 표준 입력을 닫는다. demo.sh·audit.sh의 exec는 모두 닫는다 |
| `openshell sandbox download kculture /hackathon/output/<run_id> …`가 "outside the sandbox workspace (/sandbox)"로 거부된다 | `sandbox download`는 `/sandbox` 밖 경로를 받지 못한다 | exec로 `/sandbox/work/` 아래에 복사한 뒤 받는다. `audit.sh`가 이렇게 한다 |
| `openshell sandbox create --from <폴더>`가 빌드 재료를 보내다 `error writing a body to connection: Invalid argument (os error 22)`로 실패 | 2.27 GB 가중치 파일 하나 때문으로 보인다 `[추론: 원문도 "most likely"]` | `docker build -t kculture-sandbox:<태그> <폴더>` 뒤 `--from kculture-sandbox:<태그>`로 만든다(4절) |
| colima를 켠 직후 껐더니 `openshell sandbox list`가 Error, `sandbox exec`가 "not ready (phase: Error)" | 게이트웨이가 샌드박스 컨테이너를 올리는 중에 `colima stop`으로 컨테이너가 강제 종료됐다. OpenShell CLI에는 Error에서 빠져나오는 명령이 없다 | 끌 때는 Ready 상태에서 `openshell sandbox stop <이름>` 뒤 `colima stop`, 켤 때는 `colima start` 뒤 `openshell sandbox start <이름>` `[추론: 원문도 이 순서는 시험하지 않음]` |
| `sandbox create`가 이미지를 빌드하지 못한다 | colima에서는 `DOCKER_HOST`가 필요하다. `.dockerignore`에 `!Dockerfile`이 필요하다 | `DOCKER_HOST=<colima Docker 소켓>`을 붙인다. stage.sh가 `.dockerignore`를 만든다 |
| provider를 붙였는데 목적지 연결이 CONNECT 403 | `providers_v2_enabled`가 기본으로 꺼져 있어 provider만으로는 목적지가 열리지 않는다 | 정책에 네트워크 블록을 적는다(`app/sandbox/policy.yaml`의 `nim_chat`) |
| 정책 블록과 상관없이 모델 호출이 통과하거나, 블록을 두자 멈춘다 | 관리형 추론 주소 `inference.local`은 정책 밖에서 처리된다(NemoClaw 온보딩이 이 경로를 만든다) | `openshell inference get`이 "Not configured"인지 본다. 아니면 `openshell inference delete` |
| `openshell logs`에 행이 빠진다 | 크기가 정해진 버퍼에서 읽는다 | 완전한 기록은 샌드박스 안 `/var/log/openshell.*.log`다 |
| 같은 이름으로 샌드박스를 다시 만들었더니 정책 판이 1로 돌아갔다 | 다시 만들면 판 번호가 처음부터 다시 시작한다 | Version만으로는 다시 만든 것을 가리지 못한다. 같은 정책이면 해시도 같으므로 해시로도 가릴 수 없다(회수 뒤 판 해시가 처음 판과 같았다). 정책 이력의 생성 시각을 본다 `[추론]` |
| `sandbox download`가 같은 이름 파일을 알리지 않고 덮어쓴다 | 그렇게 동작하고, 심볼릭 링크도 그대로 받는다 | 임시 폴더로 받고 링크를 검사한 뒤 옮긴다(`audit.sh`가 이렇게 한다). 묶음이 이미 있으면 audit.sh는 종료 2로 덮어쓰지 않는다 |
| 앱이 시스템 `python3`에서 돌지 않는다 | macOS 시스템 `python3`는 3.9.6이다 | `uv run python`(3.12)을 쓴다 |
| 승인했는데 게시가 계속 막힌다 `[추론: 겪은 일이 아니라 policy.yaml 머리 주석과 demo.sh cmd_approve에서]` | `PUBLISH_REPO`와 승인 정책의 `path:`가 다르다 | 둘을 같은 저장소로 맞춘다(5절 앞부분). `demo.sh approve`가 미리 검사한다 |

표 밖(원본에 없음): "provider 키 값에 줄바꿈이 섞이면 `credential_unavailable`"이라는 함정을 전달받았으나 이 저장소의 문서·시험표에서 찾지 못했다 `[미확인]`. 3절처럼 `read -rs`로 한 줄로 받으면 피할 수 있을 것이다 `[추론]`.

근거: `docs/engineering-notes.md` 3·6절, `app/sandbox/violation_tests.md`(Build note, `sandbox exec` 관찰), `app/sandbox/audit.sh` 머리 주석, `app/sandbox/demo.sh`(`cmd_approve`), `app/sandbox/policy.yaml` 머리 주석

## 8. 선택: 모델 엔드포인트 바꾸기, 웹 화면

### 8.1 모델 엔드포인트 환경변수

- `NIM_BASE_URL`(기본 `https://integrate.api.nvidia.com/v1`), `NIM_MODEL`(기본 `nvidia/nemotron-3-super-120b-a12b`): 모델 주소와 이름. 키는 기본으로 `NVIDIA_API_KEY`에서 읽는다(아래 `NIM_API_KEY_ENV`).
- `NIM_BASE_URL`·`NIM_MODEL`은 루프가 쓰는 Nemotron 클라이언트(`app/loop/nemotron.py`가 `NimClient.from_env`를 부름)에도 그대로 적용된다.
- `NIM_API_KEY_ENV`: 키가 든 환경변수의 이름을 고른다. 기본은 `NVIDIA_API_KEY`이고, 받는 값은 `NVIDIA_API_KEY`·`VLLM_API_KEY`(팀이 Brev GPU에 띄운 vLLM(OpenAI 호환 추론 서버)용) 둘뿐이다. 그 밖의 이름은 설정 오류(ConfigError)로 멈춘다. 다른 provider의 자리표시 값(예: `GITHUB_TOKEN`)이 모델 요청에 실리지 않게 하려는 것이다. 근거: `app/agent/nim_client.py` 6~7행(머리 주석), 33~35행(`API_KEY_ENV_NAME_ENV`, `ALLOWED_KEY_ENVS`), 147~152행(`from_env`의 검사).
- `demo.sh`는 호스트에 설정된 세 값(`NIM_BASE_URL`, `NIM_MODEL`, `NIM_API_KEY_ENV`)을 `--env`로 샌드박스에 넘긴다. 설정하지 않은 값은 넘기지 않는다. 공백·따옴표·glob 문자(`*`, `?`, `[`)·`$`·백틱이 든 값은 종료 2로 거부한다(`app/sandbox/demo.sh` 41~49행).
- 팀 vLLM으로 바꾸는 명령(provider 프로필 `app/sandbox/providers/kculture-vllm-chat.yaml` 가져오기, provider `kculture-vllm` 만들기, 샌드박스를 만들 때 `--provider kculture-vllm` 더하기, 세 값을 주고 `demo.sh course` 부르기)은 README 3절 "선택: 팀의 vLLM으로 모델 바꾸기"에 있다. 팀 vLLM으로 시연 문장과 가벼운 질문을 한 번씩 끝까지 돌렸다(처음에는 vLLM 키 검사에서 401이었고, provider 키를 바로잡은 뒤 통과) `[실행 기록: app/sandbox/violation_tests.md C4, README 8절]`. 기대 결과: 가벼운 질문은 `ANSWERED_LIGHT`, 시연 문장은 코스 저장 뒤 `PUBLISH_PENDING_APPROVAL`(승인 전).
- 샌드박스 정책(두 파일 모두)은 모델 쪽으로 `nim_chat`(`integrate.api.nvidia.com:443`)과 `vllm_chat`(`nemotron-ye5klfyey.gobrev.dev:443`)의 `POST /v1/chat/completions`만 연다. 그 밖의 엔드포인트를 쓰면 정책에도 그 호스트를 더해야 한다 `[추론: app/sandbox/policy.yaml 머리 주석 "Everything else is denied"]`.

근거: `app/agent/nim_client.py`(머리 주석, 상수, `from_env`), `app/sandbox/demo.sh`(41~49행), `app/sandbox/policy.yaml`(머리 주석, `nim_chat`·`vllm_chat`), `app/sandbox/providers/kculture-vllm-chat.yaml`, README 3절

### 8.2 웹 화면

어디서: 저장소 루트
```
python3 app/web/server.py
```
- 기대 결과: `http://127.0.0.1:8787/ (샌드박스 kculture)`가 찍히고, 브라우저로 그 주소를 열면 질문 칸 하나가 보인다. 질문을 보내면(보내기 버튼, Enter. 줄바꿈은 Shift+Enter) 오른쪽 영역이 열리고 경과 시간이 오르다가 답이 나온다. 127.0.0.1에만 열리고 한 번에 한 질문만 돈다.
- 옵션: `--port 8787`, `--sandbox kculture`. 호스트에 `PUBLISH_REPO`·`NIM_BASE_URL`·`NIM_MODEL`·`NIM_API_KEY_ENV`·`KCULTURE_APPROVAL_WAIT_S`가 있으면 그 다섯 이름만 샌드박스로 넘긴다(키 값은 넘기지 않음).
- 2026-10-07 확인: macOS 기본 `python3`(3.9.6)으로 띄워, 시연 문장(팀 vLLM, run `20261007T075459Z-27fb`, 70초, `PUBLISH_PENDING_APPROVAL`)과 가벼운 질문(run `20261007T075620Z-214c`, 4초)을 화면으로 돌렸다 `[실행 기록: README 8절, docs/tracking/status.md 16:5x 줄]`.

근거: `app/web/server.py`, `app/web/index.html`, `app/web/tests/test_server.py`, README 5절
