# 트랙 `tools` 최종 보고(K1 코스 도구)

- 범위: `app/tools/`, 브랜치 `track/tools`(base main cc6e182)
- 기간: 13:44 지시 0001 수신 ~ 14:31 최종 보고(시한 14:50). 0005 final을 지시 0004·0007 반영분까지 넣어 다시 쓴 판

## 한 일

설계 2.2의 도구 11개를 설계 4.2 접점(`run(args, ctx, deps) -> ToolResult`, `ToolResult`는 도구 결과 `{ok, kind, data, error}`)대로 만들고 `tools.register_all(registry)` 하나로 등록했다. 모델 호출(`chat`)과 바깥 접근(검색·청크·테마 팩·HTTP·파일 읽기)은 모두 `Deps`(도구가 바깥과 만나는 주입 함수 묶음)로 주입받고, 시험은 가짜 `Deps`(`app/tools/tests/fakes.py`, 가짜 입력 `app/common/fixtures/` 기반)로만 돈다. `app/retrieval/`·`app/loop/`·`app/agent/`는 import하지 않는다.

| 모듈 | 도구 | 요점 |
|---|---|---|
| `places.py` | `select_places`, `lookup_station` | chat(구간 조사) 1회. 코드가 구간 검사(1~180 정수, 청크 실재 → `cited`/`estimate`, 후보 밖·중복 버림), 머무는 시간(없으면 60분 추정), `arrive_min`·합계, 예산 자르기(우선순위 낮은 것부터, 같으면 순서 뒤쪽부터, 앞뒤 구간 더해 `estimate`)를 한다. `free_places`에는 `free-1`… ID를 붙인다. 예산이 없으면 우선순위 순 최대 5곳 |
| `evidence.py` | `lookup_origin`, `lookup_operating`, `organize_names`, `grade_evidence`, `search_db` | `organize_names`는 장소 전부를 묶어 chat 1회. 근거 실재 검사(색인 청크 ID, 이번 실행에서 kind `file`로 읽은 입력 경로). 등급·충돌 순서·운영 정보 최신/오래된 판정은 코드가 한다(2.3). 운영 정보는 칸(`hours`, `closed`)마다 따로 판정한다(지시 0007) |
| `files.py` | `list_input`, `read_file` | `/hackathon/` 밖은 열지 않고 `OUT_OF_SCOPE`. restricted·secrets는 앱이 거르지 않는다. 권한 오류는 `DENIED_BY_SANDBOX`, 64KB 넘으면 앞 64KB만 쓰고 `TOO_LARGE` |
| `course.py` | `save_course` | `Course.from_dict`로 검사한 뒤 `course.json`·`course.md`를 쓴다. 이름 유래마다 등급과 출처(발행처·날짜), 추정 구간에는 "(추정)" |
| `publish.py` | `request_publish` | 한 번만 보낸다. `TUNNEL_403` 또는 403+`policy_denied`이면 `BLOCKED_BY_POLICY`, 201이면 `CREATED`(`html_url`만 읽음. 4KB에서 잘려 JSON이 안 읽히면 `/issues/`가 든 첫 `html_url` 값을 정규식으로 찾음, 지시 0004), 그 밖의 HTTP 응답은 `HTTP_ERROR`, 연결 실패는 `NETWORK_ERROR`. 응답 본문·머리글은 `data`·`error`에 넣지 않는다 |
| `_shared.py`, `__init__.py` | 공용 함수, `register_all` | 경고에 넣는 모델 값은 `shown()`(공백을 접어 한 줄로 만들고 60자로 자르는 함수)을 거친다 |

### loop 트랙과 맞춘 접점(계약 4.2 안에서 정한 세부, 보고 0002·0003)

- `ok`·`kind` 조합
  - `read_file`: 정상 `ok=true, OK`. 64KB 넘음 `ok=true, TOO_LARGE`(+warnings). 권한 오류 `ok=false, DENIED_BY_SANDBOX`(`data.note`="접근이 거부됨(인프라 차단)"). 없음 `NOT_FOUND`, 범위 밖 `OUT_OF_SCOPE`, 텍스트 아님 `NOT_TEXT`, NUL 경로·그 밖의 OS 오류 `TOOL_ERROR`
  - `request_publish`: `CREATED`만 `ok=true`. `data`={"http_status","issue_url"}만
  - `select_places`·`organize_names`: 모델 실패나 쓸 수 없는 답은 `TOOL_ERROR`
- `ctx.places` 항목: 4.6 places의 이름·역·시간 키 + 추가 키 `priority`, `pack_id`. `save_course`는 추가 키를 버린다. `total_min`은 `save_course`가 마지막 `arrive_min + stay_min`으로 계산한다
- `read_files[경로].kind`: `file`, `dir`, `DENIED_BY_SANDBOX`, `NOT_FOUND`, `OUT_OF_SCOPE`, `NOT_TEXT`, `TOOL_ERROR`. 근거로는 `file`만 인정한다
- `excluded.reason`: "시간 예산 초과"(계약), "시간 예산 없는 요청의 최대 5곳 초과", "구간 조사 답에 없음"(모델이 구간 답에서 빠뜨린 후보)

### 지시 0004·0007 처리

- 0004
  1. 잘린 201 본문의 `issue_url`: 반영(ba6dcd1). GitHub 응답에는 `user.html_url`(사용자 프로필 주소)도 있어서 `/issues/`가 든 첫 값만 쓴다. 번호(`number`)는 tools가 쓰지 않아 찾지 않는다
  2. `read_file` 크기 판정: 이미 함(`read_path(path, 64KB+1)`)
  3. `theme_packs()` 예외: 이미 함(`select_places`·`lookup_station` 모두 `TOOL_ERROR`)
  4. `provenance`(출처 종류: 실제·합성) 빈 값: 해당 없음. tools는 이 값을 읽거나 채우지 않고 등급은 `source_type`만으로 정한다
- 0007: 반영(844a9fb). 칸마다 그 칸을 채운 문서만 정렬해(새 날짜 먼저, 날짜 없음은 가장 옛것, 같은 날짜면 높은 등급, 그다음 source_id) 판정한다.
  - 칸 판정: newest(그 칸을 채운 가장 새 문서)와 값이 다른 문서가 모두 같거나 낮은 등급이면 newest 값으로 정한다. 아니면 현장 확인이고, 최신 날짜·최고 등급 동점끼리 값이 갈려도 현장 확인이다
  - `status`: 현장 확인 칸이 없으면 `CHOSEN`, 있으면 `NEEDS_ONSITE_CHECK`. 정해진 칸 값은 보이고, 현장 확인 칸만 빈 값이다. `candidates`에는 현장 확인 칸의 후보만 넣는다
  - `stale`: 칸별 합집합이고, 이유에 칸 이름을 붙인다(예: "hours: …; closed: …")
  - 정해진 칸이 하나도 없으면(두 칸 모두 현장 확인, 또는 한 칸은 현장 확인이고 다른 칸은 빈 값) `source_ids`는 관련 문서 전부다. 지시 글자대로라면 빈 목록이다. 상위가 빈 목록을 원하면 한 줄 수정이다
  - `NEEDS_ONSITE_CHECK`여도 정해진 칸의 `stale`은 남는다. `course.md`는 상태와 관계없이 `stale`을 보이므로 문제없다

## 커밋(track/tools)

| 커밋 | 내용 |
|---|---|
| 52d9b69 | K1-W0 공용 뼈대(`register_all` 지연 등록, 공용 함수, 시험용 가짜 Deps) |
| de18e82 | K1-W1 `select_places`·`lookup_station` |
| e8e6fd7 | K1-W2 근거 조회·정리·등급 도구 |
| 5c60e91 | K1-W3 `list_input`·`read_file`·`save_course`·`request_publish`와 등록·도구 사슬 시험 |
| ad0b785 | K1-W4 경고 속 모델 값 정리 공용화, Deps 예외를 `TOOL_ERROR`로, 문구 숫자를 한도 값에서 |
| fe8524e | K1-W5 운영 정보 unknowns·list_input 경고·팩 오류 문구의 값도 한 줄·60자로 |
| ba6dcd1 | K1-W6 4KB에서 잘린 201 본문에서도 이슈 html_url을 찾음(지시 0004) |
| 844a9fb | K1-W7 운영 정보를 hours·closed 칸마다 따로 판정(지시 0007) |

## 검증 명령과 종료 코드(하위가 직접 다시 돌림)

- `app/`에서 `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest -q`: 463 passed, 1 skipped, 종료 0. 건너뛴 1건은 retrieval 임베더 시험(`RETRIEVAL_MODEL_PATH` 없음)이고 이 트랙과 무관하다. 기준(base cc6e182)은 294 passed, 1 skipped였다
- `… uv run pytest tools/tests -q`: 170 passed, 종료 0
- `python3 scripts/secret_scan.py main..HEAD`: 종료 0(걸린 곳 0)
- `git -c core.quotePath=false diff --no-renames --name-only main...HEAD`: 16개 파일, 모두 `app/tools/` 아래

### 완료 조건별 시험

| 완료 조건 | 시험 |
|---|---|
| 출발역에서 시작한 예산 안의 코스와 예산 밖 장소의 `excluded` | `test_chain.py`(새벽솔역 출발, 180분 예산, 162분 코스, fx-06·fx-05가 "시간 예산 초과"), `test_places.py` |
| 유래 충돌 표시 | `test_chain.py`·`test_evidence.py`(달무리나루: A official → D blog) |
| 운영 정보 두 경우 | `test_chain.py`·`test_evidence.py`(fx-02 `CHOSEN` + 2024 자료 `stale`(오래된 자료 목록), fx-03 `NEEDS_ONSITE_CHECK` + 후보 2개) |
| 막힌 게시의 `BLOCKED_BY_POLICY` | `test_chain.py`(TUNNEL_403), `test_publish.py`(403+`policy_denied`; 표시 없는 403은 `HTTP_ERROR`) |
| 권한 오류의 `DENIED_BY_SANDBOX` | `test_chain.py`·`test_files.py`(`/hackathon/secrets`, read_path를 실제로 부름) |

## worker-reviewer 판정

- 파일별 1차 검토 3건(W1·W2·W3): 모두 `CHANGES_REQUIRED` → 반영
  - W1: 모델 값이 경고에 줄바꿈째 들어감, `excluded`가 다시 돌 때 쌓임
  - W2: 운영 판정이 동점일 때 입력 순서에 따라 결론이 바뀜, `organize_names`가 형식 틀린 답을 OK로 처리
  - W3: NUL 경로에서 예외가 그대로 올라감
- 트랙 전체 최종 검토: `CHANGES_REQUIRED`(evidence·files 경고에 모델 값 미정리) → W4로 반영
- W4 반영분 재확인: `CHANGES_REQUIRED`(운영 정보 unknowns 두 줄에 자유 장소 이름 미정리) → W5로 반영
- W5 반영분과 트랙 전체 마지막 훑기: **`PASS`**(경고·unknowns 쓰는 자리 28곳 모두 확인, 계획·모델 값은 모두 `shown()`을 거침)
- W6(지시 0004 1번, 잘린 201 본문의 `html_url`) 검토: `PASS`
- W7(지시 0007, 운영 정보 칸별 판정) 검토: `PASS`

## worker-debugger가 찾은 원인

- 부르지 않았다. 시험 실패는 모두 worker가 시험을 먼저 쓴 뒤의 의도한 실패였고, BLOCKED도 없었다.

## 남은 일

- `course.md` 유래 줄에 모델이 쓴 `summary`·`name`이 그대로 들어간다. 요약에 줄바꿈이 있으면 Markdown 목록 모양이 깨질 수 있고, 같은 글이 이슈 본문으로 나간다. 줄바꿈만 공백으로 접는 정리를 권한다(검토자 권고, 미반영).
- 실제 자료(`data/sweat/` 케데헌 팩)로는 돌려 보지 않았다. 가짜 입력으로만 시험했다.
- `[추론]` 루프가 `Deps.chat`에서 호출 수·토큰 한도 예외를 올리는 방식이면, `select_places`·`organize_names`가 그 예외를 `TOOL_ERROR`로 바꾼다. 그러면 `FAILED`+`limits_hit` 대신 다시 계획으로 갈 수 있다. loop가 한도를 도구 호출 밖에서(감싼 chat의 계수기로) 판정하거나, common에 한도 예외를 정해 tools가 다시 올리게 맞춰야 한다.
- 심볼릭 링크(다른 경로를 가리키는 링크 파일)로 `/hackathon/` 밖을 가리키는 경우를 앱이 거르지 못한다(글자 판정만 함). 실제 `Deps.read_path` 구현(loop)이 realpath(링크를 모두 푼 실제 경로)로 범위를 다시 보게 하는 것을 권한다. 지금 최종 경계는 Landlock(커널 수준 파일 접근 제한)이다.
- `[추론]` 등급이 null인 주장("근거 없음")도 충돌에 들어간다(2.3 "버리지 않고 모두 적는다" 글자대로). 평가 키 `must_flag_conflict_names`에서 거짓 양성(실제 충돌이 아닌데 충돌로 잡힘)이 날 수 있어 해석이 필요하면 팀장이 정한다.
- `[추론]` 시연 자료에서 먼 곳이 모델 순서의 중간에 오면, 빠진 장소의 앞뒤 구간을 더하는 규칙(4.6) 때문에 합친 구간이 커져 이웃 장소까지 빠질 수 있다. 실제 테마 팩으로 한 번 확인하는 것을 권한다.
- `course.json`의 `goal.start`는 요청 문구 그대로(예: "새벽솔역")이고, `select_places`는 역 이름("새벽솔")으로 맞춰 쓴다. 화면에 두 표기가 섞일 수 있다.

## 문서 수정 제안(상위가 고침)

- `docs/contracts.md` 6절 설계 4.2: `read_files[*].kind` 값 집합과 `read_file`·`request_publish`의 `ok`·`kind` 조합(위 "loop 트랙과 맞춘 접점")을 적는다.
- 설계 4.6: `excluded.reason`의 그 밖의 값 두 가지("시간 예산 없는 요청의 최대 5곳 초과", "구간 조사 답에 없음")를 적는다. 모델이 구간 답에서 빠뜨린 후보를 코스에서 뺀다는 규칙도 함께 적는다.
- 설계 4.6: 출발점이 없을 때 첫 장소는 "구간 없음"(`arrive_min` 0, unknown 구간으로 세지 않음)이라는 규칙을 적는다.
- 설계 2.5: 실제 `Deps.read_path`가 realpath 뒤 `/hackathon/` 범위를 다시 확인한다는 한 줄을 보탠다(위 남은 일).
- 설계 4.10 또는 2.2: 도구가 `chat` 한도 예외를 받았을 때의 처리(위 남은 일)를 loop와 정해 적는다.
