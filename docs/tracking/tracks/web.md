# 트랙 web 최종 보고: W2 사용자 화면을 실시간 조회로(2026-10-07)

## 한 일
- `app/web/server.py`(호스트 로컬 서버, 표준 라이브러리만)
  - 실행: `python3 app/web/server.py [--port 8787] [--sandbox kculture]`. 127.0.0.1에만 바인딩한다(`--host` 옵션 없음).
  - 경로: `GET /`(index.html), `POST /api/ask`(`{"question"}` → `{"job"}`, 돌고 있으면 409, 질문 1~500자·제어 문자 제거, "-"로 시작하면 400), `GET /api/jobs/<id>`(`state`·`elapsed_s`·`result`·`error`).
  - 실행: `openshell sandbox exec -n <sandbox> --workdir /opt/kculture --no-tty --timeout 600 [--env …] -- /opt/kculture/.venv/bin/python -m loop ask <질문>`. 인자 목록(셸 없음), 모든 호출 `stdin=DEVNULL`·`start_new_session=True`. 바깥 감시 660초, 넘으면 프로세스 그룹 SIGKILL·failed.
  - `--env`: `PUBLISH_REPO`, `NIM_BASE_URL`, `NIM_MODEL`, `NIM_API_KEY_ENV`, `KCULTURE_APPROVAL_WAIT_S` 다섯 이름만, 호스트에 있고 비어 있지 않을 때만 넘긴다. 값에 공백·따옴표·백틱·제어 문자가 있거나 키 모양이면 작업 failed(문구에 이름만).
  - 결과: stdout 마지막 비지 않은 줄을 `run_id: (\d{8}T\d{6}Z-[0-9a-z]{4})`로 fullmatch. 통과한 run_id로 `run.json`·`course.json`·`answer.json`·`publish.json`을 `cat`(timeout 30, stdin 닫음)으로 읽어 있는 것만 담는다. stdout 전문은 넣지 않고, 키 모양 문자열은 `***`로 가린다(result 재귀, error 문구).
  - 검토 반영: Host 머리글이 `127.0.0.1:<포트>`·`localhost:<포트>`가 아니면 403(DNS 재바인딩), POST의 Content-Type이 `application/json`이 아니면 415(교차 사이트 요청 위조). 요청 로그는 남기지 않는다(질문에 개인 내용이 있을 수 있음).
- `app/web/index.html`: 확정 목업(`design_reference.html`, 커밋 안 함)의 배치·테마·다크 모드·휴대폰 시트 그대로. "기록 재생"과 미리 넣은 대답을 지우고, 띠 문구를 "실시간 — 질문을 OpenShell 샌드박스 kculture 안의 에이전트가 처리"로 바꿨다. 보내면 1초 간격 폴링, 경과 시간과 "샌드박스 kculture에서 실행 중". 코스(요약·장소 카드·유래 등급 배지 A~D/근거 없음·출처 또는 입력 파일·운영 정보 3상태·오래된 자료·뺀 곳·게시 상태), 답(답 문장·근거 표시·읽으려 한 파일과 "읽기 거부(샌드박스 차단)"), UNAVAILABLE·FAILED 안내, 접힌 "실행 기록". 값은 모두 textContent, 링크는 `https://github.com/`으로 시작할 때만.
- `app/web/tests/test_server.py`: 가짜 `openshell`을 PATH 앞에 두는 시험 50건. 정상(코스·게시), light, UNAVAILABLE, run_id 없음 5종, 409(sleep 없이), 질문 길이·제어 문자, env 화이트리스트·키 이름·키 모양 값 거부, 가림, 표준 입력 닫힘 두 겹(Popen 인자 + 자식이 본 fd 0), 127.0.0.1 바인딩, 시간 초과, Host 403·Content-Type 415, `__init__.py` 없음.

## 커밋(track/web)
- 1767132 feat(W2): web 화면 — 확정 디자인으로 실시간 조회
- f61eb4f fix(W2): web 화면 — 실패 시 error 문구, 끝나면 패널 다시 열기, 운영 정보 없을 때 지어내지 않음, 400 사유
- 4023908 feat(W2): web 로컬 서버와 시험
- 0a109e7 test(W2): 환경변수 시험 — 키 이름이 argv에 없음을 단언
- 5f3f647 fix(W2): 검토 반영 — Content-Type·Host 검사, 키 모양 env 값 거부, 읽기 거부 표시, 출처 없을 때 입력 파일

## 검증 명령과 종료 코드(하위가 직접 다시 돌림)
- `app/`에서 `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest -q web/tests/test_server.py`: 종료 0(50 passed)
- `python3 scripts/secret_scan.py main..HEAD`: 종료 0(추가 행 1619줄, 걸린 곳 0)
- `git -c core.quotePath=false diff --no-renames --name-only main...HEAD`: `app/web/` 세 파일뿐
- `find app/web -name __init__.py`: 없음
- 가짜 openshell로 서버 수동 확인: `GET /` 200(127.0.0.1·localhost), 다른 Host 403, text/plain POST 415, ask → done과 결과 4종, 빈 질문 400, LISTEN 127.0.0.1만
- 브라우저 확인(가짜 openshell): 질문 → 오른쪽 패널에 코스 요약·장소 카드·B 배지·"현장 확인 필요"·게시 "승인 대기", 콘솔 오류 없음

## worker-reviewer 판정
- 1차(1767132~0a109e7): APPROVE, 차단 없음. 변이 시험 5건(stdin 제거, 0.0.0.0 바인딩, GITHUB_TOKEN 화이트리스트 추가, killpg 무력화, 가림 제거)을 모두 시험이 잡음. 권고 7건 중 4건(CSRF·DNS 재바인딩, 키 모양 env 값, 읽기 거부 표시, 빈 출처)을 5f3f647로 반영.
- 2차(5f3f647): APPROVE, 차단 없음. Host 비교(strip·lower 뒤 정확히 일치), Content-Type(`;` 앞부분 정확히 일치, 교차 사이트 application/json은 사전 요청이 OPTIONS 처리기 없음으로 막힘), 화면 fetch 회귀 없음(상대 경로·application/json)을 확인. 권고: 읽기 거부·입력 파일 표시의 JS 시험 없음(시연 전 눈으로 확인), 403·415는 화면에서 일반 실패 문구로만 보임.

## worker-debugger
- 부르지 않음(시험·검증 실패 없음).

## 남은 일
- 실제 샌드박스 연결 확인(상위, 병합 뒤): 호스트에서 `PUBLISH_REPO` 등 환경변수를 둔 채 `python3 app/web/server.py`를 띄우고 브라우저로 질문 하나. 샌드박스 안 openshell이 질문 argv를 그대로 넘기는지는 `[미확인]`(기존 `app/sandbox/demo.sh`·`run_cases.py`가 같은 방식이라 보존된다고 봄 `[추론]`).
- 화면 표시 변경(읽기 거부, 입력 파일)에는 자동 시험이 없다. 문법 검사·grep·가짜 DOM 스모크로만 봤다.
- 실제 openshell·모델로는 돌리지 않았다(지시대로).

## 문서·설정 수정 제안(상위)
- `app/pyproject.toml` testpaths에 `"web/tests"` 추가. 없으면 계약 4.9절의 `uv run pytest`가 web 시험을 0건 돌린다.
- 화면 문구 "읽기 거부(샌드박스 차단)"와 계약이 답 본문에 넣으라는 "접근이 거부됨(인프라 차단)"이 다르다. 맞출지 상위가 정한다(`kind` 값 `DENIED_BY_SANDBOX`는 같음).
- 출처는 course.json에 `source_ids`만 있어 ID 그대로 보인다. 목업처럼 발행처·날짜로 보이려면 계약에 필드가 더 있어야 한다.
- `RUN_ID_RE`의 `[0-9a-z]{4}`는 계약의 "16진수 4자리"보다 넓다(지시 원문을 따름, 경로 위험 없음).
- `docs/operations.md`에 웹 화면 실행 명령(`python3 app/web/server.py`, 127.0.0.1:8787)과 "CSP(허용 출처 응답 헤더)를 넣으면 인라인 스크립트 화면이 멈춘다"를 적기.
