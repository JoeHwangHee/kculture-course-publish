# 트랙 loop 최종 보고(L1: 무게 판단·계획·실행·기록)

- 범위 `app/loop/`, 브랜치 `track/loop`(base main cc6e182), 지시 0001(+0002·0004·0006·0007·0008·0010·0012). 이 본문은 final 0009를 대신한다(0010에 따라 라우터를 Nemotron으로 바꾼 판)
- 상태: 완료 조건 충족. 시험 종료 0. worker-reviewer 판정은 아래 "검토".

## 한 일

worker 둘이 같은 worktree에서 파일을 나눠 병렬로 만들었다(겹치는 파일 없음, 커밋은 하위가 검증 뒤).

**L1-A 바깥 경계**
- `budget.py`: 한도(설계 4.10)를 코드로 강제한다.
  - 대상: 라우터(Nemotron) 2회, 계획·도구 Nemotron 8회(둘은 따로 센다)(도구 안의 `deps.chat`도 같은 Budget을 거친다), 토큰 128,000(호출 전후 검사), 300초(승인 대기 `pause/resume` 제외), 도구 단계 12
  - 라우터 한도는 `getattr(limits, "ROUTER_CALLS_PER_RUN", 2)`다. 상위가 병합 때 공통 이름을 바꾼다.
  - `model_calls`·`tokens`는 `{"router","nemotron"}` dict다(0012).
  - `LimitHit(name)`의 `name`은 `router_calls`·`nemotron_calls`·`tokens`·`run_seconds`·`tool_steps` 가운데 하나다.
- `trace.py`: 의사결정 기록(`trace.jsonl`)을 쓴다.
  - 공통 `TraceLine`을 쓰고, `prev_hash`를 사슬로 잇는다.
  - 기존 파일에 이어 쓸 수 있다(`publish --run`). 끝 줄바꿈을 보정하고, run_id가 다르면 거부한다.
- `files.py`: 실행 폴더(`run_id`가 겹치면 다시 뽑고 덮어쓰지 않음), `run.json`·`answer.json`/`answer.md`·`publish.json`을 쓴다. 임시 파일에 쓴 뒤 바꿔 넣는다.
- (Claude 클라이언트 `claude.py`는 0010에 따라 지웠다. 이력: bea49ff에서 만들고 ad332eb에서 지움)
- `nemotron.py`: `NimClient`는 고치지 않는다. 계수용 전송 함수가 200 응답의 usage만 읽는다.
- `http.py`
  - `Deps.http_post_json`: 예외를 올리지 않고, `TUNNEL_403`·`NETWORK`을 판정하고, 본문은 앞 4KB, 리디렉션 거부
  - GitHub 인증: `https://api.github.com/` 주소에만 `GITHUB_TOKEN` 자리표시 값을 unredirected Bearer로 붙인다.
  - `read_path`: 실제 경로(`realpath`)가 `/hackathon` 밖이면 열지 않고 `OutOfScopePath`(`ValueError`, `kind = "OUT_OF_SCOPE"`)를 올린다(0008).
- `wiring.py`: 실제 `Deps`·등록표·fingerprint를 조립한다. retrieval·tools는 함수 안에서 늦게 import한다.

**L1-B 흐름**
- `router.py`: Nemotron(같은 NIM 클라이언트)이 무게 JSON(`{"weight","why"}`)을 낸다(0010). `<think>` 블록, 코드 펜스, 앞뒤 잡문을 벗겨 JSON 객체 하나를 뽑는다. trace `route` 줄의 model에는 Nemotron 모델 이름이 들어간다.
  - heavy/light 밖의 값, 빈 응답, 예외는 실패로 본다. 1회 다시 보내고, 또 실패하면 `UNAVAILABLE`(route `none`, 계획 Nemotron 0회)이다. 추측해서 다른 경로로 보내지 않는다.
- 가벼운 경로: 첫 줄에 `자료 근거 없음(일반 안내)`를 붙인다(중복 제거). `ANSWERED_LIGHT`.
- `planner.py`: 계획 프롬프트에 설계 2.2의 다섯 입력을 넣는다. 검사는 설계 4.5(도구 이름, 인자 형식, 단계 수 ≤ 12).
  - 빠진 칸만 기본값으로 채운다: why·args·constraints·publish_requested·work·start·time_budget_min. trace `plan_check`에 채운 칸을 남긴다.
  - 형식이 틀린 값은 그대로 떨어뜨린다.
- `executor.py`
  - 계획 전에 `list_input`을 돌린다(단계 수에 넣지 않음).
  - 단계 실행, 실행 맥락 전달
  - `TOOL_ERROR`에만 다시 계획한다. 읽기 거부·없음·범위 밖·텍스트 아님·64KB 초과는 기록하고 진행한다.
  - 한도를 넘으면 `FAILED` + `limits_hit`
  - 코스가 아닌 답(`ANSWERED_HEAVY`)은 코드가 만든다(추가 모델 호출 없음). 거부된 읽기에는 `접근이 거부됨(인프라 차단)`, 장소가 없으면 `자료에 해당 작품의 배경지가 없음`.
- `publish.py`
  - 시도 → 차단이면 10초 간격으로 다시 보내며 최대 180초 기다린다(실행 시간에서 뺌). 다시 보내기는 단계 수에 넣지 않는다.
  - `CREATED` → `PUBLISHED`, `HTTP_ERROR`/`NETWORK_ERROR` → `PUBLISH_FAILED`, 시간 초과 → `PUBLISH_PENDING_APPROVAL`
  - `publish.json`을 쓰고, `course.json`의 `publish`를 갱신한다.
  - 이슈 1개 보장: 한 실행에서 게시 결과가 하나라도 나오면 그 뒤 `request_publish`는 실행하지 않는다. `publish --run`은 `CREATED`가 있으면 보내지 않고 종료 1.
  - 도구 error 속 `/hackathon/` 밖 절대 경로는 trace에서 `<경로>`로 가린다.
- `runner.py`: 실행 하나를 끝까지 돌린다. 예상 못 한 예외에도 `run.json`과 trace `final`을 남긴다(`FAILED`).
- `baseline.py`: Nemotron 1회, 자료·도구·라우터 없음, 같은 한도.
  - `baseline.json`은 `Course` 최상위 키 9개 꼴이고, 모델 값은 고치지 않는다.
  - `BASELINE_DONE`, route `none`
- `__main__.py`(`python -m loop ask|publish --run|baseline`)
  - stdout 마지막 줄은 언제나 `run_id: <run_id>`이고, 실행 폴더를 만들기 전에 멈추면 `run_id: -`다(0007).

## 커밋

| 해시 | 내용 |
|---|---|
| bea49ff | L1-A 부품 7개 + 시험 |
| ebaca6d | L1-A 검토 반영(GitHub 인증 unredirected, trace 이어쓰기, 호출 전 토큰 검사) |
| 493abcf | L1-B 흐름 7개 + 시험 |
| a9dcc84 | L1-B 검토 반영 + CLI 마지막 줄 run_id(0007) + 계획 기본값 채우기 |
| 778decf | `read_path` 실제 경로 범위 확인(0008) |
| e0a3e96, b40957a | 도구가 `LimitHit`을 `TOOL_ERROR`로 삼켜도 `FAILED`로 끝나는지 보는 시험(0008). b40957a는 검토 반영 |
| ad332eb | 라우터를 Nemotron으로 바꾸고 Claude를 지움, `run.json`에 `router` 키(0010·0012) |
| 0817abd | L1-B 재검토 권고(깨진 publish.json에도 종료 1 안 냄, CLI 마지막 방어선 종료 3, CREATED 즉시 issue_url 보존) |

## 검증(하위가 직접 다시 돌린 값)

| 명령 | 종료 | 수 |
|---|---|---|
| `app/`에서 `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest loop/tests` | 0 | 175 passed |
| `app/`에서 `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest`(전체) | 0 | 468 passed, 1 skipped(retrieval `RETRIEVAL_MODEL_PATH not set`) |
| `python3 scripts/secret_scan.py main..track/loop` | 0 | 추가 4920줄, 걸린 곳 0 |
| `git -c core.quotePath=false diff --no-renames --name-only main...track/loop`에서 `app/loop/` 밖 경로 | — | 0건 |
| `app/`에서 `__pycache__`를 빼고 `grep -rniE "anthropic|claude" loop` | 1(일치 없음) | 0건 |
| 보호 장치(`HeavyRun._raise_if_limit`)를 임시로 끄고 `-k swallowed` | 1 | 2 failed. 시험이 그 장치를 실제로 지킨다 |
| 새 프로세스 진입점: `app/`에서 `uv run python -m loop`(인자 없음), `… python -m loop publish --run 20261007T000000Z-abcd --output-dir <빈 폴더>` | 둘 다 2 | stdout 마지막 줄 `run_id: -` |

완료 조건 7경로와 시험(검토자가 대조함)

| 경로 | 시험 위치 |
|---|---|
| 가벼운 질문 | `test_runner.py` |
| 라우터 실패 두 번 → `UNAVAILABLE`(0010 뒤에는 Nemotron 라우터) | `test_runner.py` |
| 계획 검사 실패 → 다시 계획 | `test_runner.py` |
| `TOOL_ERROR` → 다시 계획 | `test_runner.py` |
| 게시 차단 → 대기 → 통과 | `test_runner.py` |
| 읽기 거부 → `ANSWERED_HEAVY` | `test_runner.py` |
| 기준선 파일 형식 | `test_baseline.py` |

더 시험한 것
- `publish_requested` false → `COURSE_SAVED`(게시 0회)
- 대기 초과 → `PUBLISH_PENDING_APPROVAL`
- HTTP 오류 → `PUBLISH_FAILED`
- 다시 계획도 실패 → `FAILED`
- 한도(Nemotron 9번째, 단계 13번째, 시간) → `FAILED` + `limits_hit`
- `publish --run`: CREATED면 1(전송 0회), 승인되면 0, 초과면 3, 없는 실행이면 2, 게시 중 예외면 3
- CLI 마지막 줄 정규식

모든 실행 시험에서 다섯 가지를 확인한다.
- `verify_trace == []`
- `RunRecord`·`AnswerRecord`·`PublishRecord.from_dict`가 통과한다.
- trace 마지막 줄이 `final`이다.
- trace에 로컬 tmp 경로가 없다.
- 진짜 sleep·네트워크가 없다(시험 전체가 1초 안).

## worker-reviewer 판정

- L1-A(bea49ff): `CHANGES_REQUIRED`, 차단 1건
  - 지적: GitHub `Authorization`이 unredirected 머리글이 아니었다.
  - 처리: ebaca6d에서 고쳤다. 같은 커밋에 권고 3건(trace 끝 줄바꿈, 호출 전 토큰 검사, nemotron docstring)도 넣었다. 수정 뒤 grep과 시험을 하위가 확인했다.
  - 재검토(ebaca6d): `PASS`. 차단이 풀렸다. 회귀 시험 `test_github_auth_header_unredirected_through_real_post`가 실제 경로를 지난다.
- L1-B(493abcf): `CHANGES_REQUIRED`, 차단 1건
  - 지적: `publish_run`이 예외 때 `final`·`run.json`·시도를 남기지 않았고, 종료 1(= 이미 CREATED)과 겹쳤다.
  - 처리: a9dcc84에서 고쳤다. 권고 5건도 모두 반영했다.
    - publish 명령의 검사 순서
    - 자동 게시를 단계로 세지 않음
    - trace 경로 가리기
    - 코스 실행의 budget 경고
    - stderr 예외 본문과 KIND 상수
- 재검토(a9dcc84): `PASS`
  - 차단 지적은 풀렸다.
  - 권고 가운데 쉬운 2건은 0817abd에 반영했다: `has_created` 형식 방어와 CLI 마지막 방어선, CREATED 직후 issue_url 보존.
  - 반영하지 않은 권고: 첫 전송에서 바로 예외가 나는 경로의 시험, `_do_publish`(BaseException)와 `publish_run`(Exception)이 잡는 예외 범위 차이. 다음 작업으로 미룬다.

- 0008 추가분
  - 778decf: `PASS`
  - e0a3e96: `CHANGES_REQUIRED`. 지적은 "시험이 보호 장치를 꺼도 통과"였다. b40957a에서 고쳤고, 하위가 장치를 끈 상태에서 시험이 실패하는 것을 다시 확인했다.
- ad332eb(라우터 교체): `PASS`(차단 없음). 남은 권고 세 가지는 남은 일 9번에 적었다.

## worker-debugger

부르지 않았다. 시험·검증 실패와 BLOCKED가 없었다.

## 남은 일(병합 뒤 상위가 확인할 것)

1. 실제 연결은 시험하지 않았다(키·네트워크 금지).
   - 무엇: `wiring.build_real`과 CLI의 실제 경로(NIM·GitHub·retrieval·tools)
   - 확인 방법: tools·retrieval 병합 뒤 샌드박스에서 시연 문장을 한 번 돌린다.
   - 아직 없는 것: tools의 `register_all`, retrieval의 형식 판 3 색인과 `Retriever.get_chunk`·`chunks_where`
   - get_chunk·chunks_where가 없으면 `retriever.chunks`를 거르는 대체 경로로 돈다.
2. retrieval이 manifest에 `source_fingerprint`를 쓰는지 확인한다. 지금 worktree의 retrieval은 쓰지 않아 `run.json`의 `index.fingerprint`가 `""`가 된다.
3. 라우터(Nemotron)가 샌드박스에서 실제로 `{"weight","why"}` JSON을 내는지 확인한다[미확인]. 형식이 두 번 틀리면 `UNAVAILABLE`로 끝난다.
4. tools가 `OutOfScopePath`를 `OUT_OF_SCOPE`로 받기 전까지(요청 0011), 범위 밖을 가리키는 링크는 `TOOL_ERROR`가 된다. 파일은 열지 않지만 다시 계획 1회를 쓴다. 검사와 열기 사이의 틈(TOCTOU)은 막지 않는다. 최종 경계는 Landlock이다.
5. 병합 때 상위가 할 일: 공통 `ModelCalls`·`Tokens`의 키를 `router`로, `limits`의 라우터 한도 이름을 `ROUTER_CALLS_PER_RUN`으로 바꾼다. 지금 loop는 `RunRecord(...).to_dict()` 뒤 두 칸을 덮어써서 쓰므로 바꾸기 전후 모두 돈다. 완료 명령의 `env -u ANTHROPIC_API_KEY`는 이제 필요 없다.
6. `ask`는 라우터 결과와 상관없이 처음에 색인·임베더를 불러온다. light·UNAVAILABLE 실행에서도 bge-m3 적재 시간이 든다. 느리면 늦게 불러오게 바꾼다(L1-B `__main__.py`).
7. `COURSE_SAVED`("보내지 말라") 실행에 사람이 `publish --run`을 하면 보낸다. 사람이 직접 부르는 명령이라 막지 않았다. 막아야 하면 알려 달라.
8. 계획 JSON에 `goal` 객체가 통째로 없으면 기본값을 채우지 않고 검사에서 떨어뜨린다(다시 계획 1회를 쓴다).
9. ad332eb 검토 권고(차단 아님)
   - JSON 뽑기는 처음 읽히는 객체를 고른다. 추론 문장 속 예시 `{"weight":...}`를 먼저 집을 수 있다. 위험은 낮다(`<think>`는 벗기고, 전체를 JSON으로 읽는 시도가 먼저 돈다).
   - 기준선도 같은 뽑기 함수를 써서 JSON 읽기가 조금 너그러워졌다. 흐름과 결과 꼴은 그대로다. 기준선에 옛 함수를 둘지 상위가 정한다.
   - `limits_hit` 이름이 `router_calls`로 바뀌었다. 병합 때 계약에 적는다.

## 조정값과 해석(문서에 적을 것 제안)

- **다시 계획**: 실행 전체에서 1회. 계획 검사 실패와 `TOOL_ERROR`가 그 1회를 나눠 쓴다. `TOOL_ERROR` 때 다시 계획해도 첫 계획의 `goal`은 그대로 둔다. 도구가 한도 초과를 `TOOL_ERROR`로 감싸도, `limits_hit`가 늘었으면 다시 계획하지 않고 `FAILED`다.
- **게시**
  - 계획에 게시 단계가 없으면 루프가 마지막에 자동으로 게시한다. 이것은 단계 수에 넣지 않는다.
  - `publish_requested` false면 계획에 게시 단계가 있어도 실행하지 않는다(trace에 `사용자가 보내지 말라고 함`).
  - 게시 결과가 하나라도 나오면 그 뒤 게시는 하지 않는다. 180초 대기가 두 번 생기지 않게 하려는 것이다.
- **CLI 종료 코드**

  | 명령 | 0 | 1 | 2 | 3 |
  |---|---|---|---|---|
  | `ask` | `ANSWERED_LIGHT`·`ANSWERED_HEAVY`·`COURSE_SAVED`·`PUBLISHED`·`PUBLISH_PENDING_APPROVAL` | `UNAVAILABLE`·`FAILED`·`PUBLISH_FAILED` | 사용법·설정 오류 | 예상 못 한 예외 |
  | `publish --run` | `PUBLISHED` | 이미 CREATED, 보내지 않음(계약) | 사용법·실행 폴더 없음·trace를 읽지 못함 | 보냈지만 게시 안 됨, 게시 중 예외 |
  | `baseline` | `BASELINE_DONE` | `FAILED` | 사용법 | 예상 못 한 예외 |

- **환경변수**(0003·0004)

  | 변수 | 기본값 |
  |---|---|
    | `NVIDIA_API_KEY`·`NIM_BASE_URL`·`NIM_MODEL` | 기존 NimClient 그대로 |
  | `GITHUB_TOKEN` | 없음(자리표시 값) |
  | `PUBLISH_REPO` | 없음 |
  | `KCULTURE_INDEX_DIR` | `/opt/kculture/index/kb` |
  | `KCULTURE_EMBEDDER` | `local:/opt/models/bge-m3` |
  | `KCULTURE_OUTPUT_DIR` | `/hackathon/output`(CLI `--output-dir`로도 지정) |

- **라우터 한도 이름**: `LimitHit`·`limits_hit`의 이름은 `router_calls`다(옛 이름 대신).

## 문서 수정 제안(상위가 고칠 것)

- `docs/contracts.md` 4.9
  - CLI 종료 코드 표와 마지막 줄 `run_id:` 규칙(0007)을 적는다.
  - 위 환경변수 표를 적는다.
- `docs/contracts.md` 2.2·4.10
  - "다시 계획 1회는 검사 실패와 `TOOL_ERROR`가 함께 쓴다"를 적는다.
  - "계획 밖 자동 게시는 단계로 세지 않는다"를 적는다.
- `docs/engineering-notes.md`
  - 라우터 모델의 요청 본문은 샌드박스에서 확인한 필드만 쓴다는 점을 적는다. 400이 나면 모든 요청이 `UNAVAILABLE`이 된다.
- `docs/engineering-notes.md`
  - GitHub 201 응답은 4KB를 넘을 수 있어 `html_url`을 정규식으로도 찾는다는 점을 적는다(tools에 지시됨, 0006).
  - `read_path`는 `max_bytes + 1`로 불러 64KB 초과를 판정한다는 점을 적는다.
