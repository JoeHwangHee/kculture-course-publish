# 트랙 runguide 최종 보고(지시 G-run)

## 한 일
- 심사자가 직접 실행해 보는 가이드 `app/runguide/RUN_GUIDE.md`를 새로 썼다(377줄). 상위가 병합할 때 `docs/guide/RUN.md`로 옮긴다.
- 구성
  - 0절: 키 없이 할 수 있는 일과 키가 필요한 일 표
  - 1절: 준비
  - 2절: 키 없이 해 보기(pytest, 색인 검색, 색인 다시 만들기)
  - 3절: provider(OpenShell에 등록하는 자격 증명 묶음) 등록. 키는 `read -rs`로 받는다.
  - 4절: stage.sh → docker build → sandbox create
  - 5절: demo.sh 장면별 시연. course, approve, revoke, secrets, 나중 게시, audit, logs
  - 6절: 결과 보는 곳
  - 7절: 문제 해결(실측된 함정만)
  - 8절: 병합 예정 항목
- 단계마다 명령, 돌리는 폴더, 기대 결과, 시간, `근거:` 원본을 적었다. 원본에 없는 내용은 `[미확인]`이나 `[추론]`으로 표시했다.

## 커밋
- b235167 docs(runguide): 심사자가 직접 실행해 보는 가이드 app/runguide/RUN_GUIDE.md

## 검증 명령과 종료 코드
- `app/`에서 `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest -q` → 종료 0, 842 passed, 1 skipped, 34.57초. 하위가 직접 돌렸다. 가이드 2.1절에 실측값으로 넣었다.
- `python3 scripts/secret_scan.py main..HEAD` → 종료 0. 추가 행 377줄, 걸린 곳 0.
- `git -c core.quotePath=false diff --no-renames --name-only main...HEAD` → `app/runguide/RUN_GUIDE.md` 하나

## worker-reviewer 판정
- APPROVE. 명령, 인자, 경로, 출력 줄, 종료 코드를 원본과 대조했고 모두 같았다.
- 권장 6건 중 4건을 반영했다.
  - 2.1절 시험 수·시간을 실측값으로 채웠다.
  - 3.2절 `--env-file .env` 형식을 쓸 수 있는 조건을 적었다.
  - 5.4절에 logs 조회가 실패할 때의 종료 1을 더했다.
  - 8.2절에 `[미확인]`과 근거 줄을 더했다.
- 반영하지 않은 것: `KCULTURE_APPROVAL_WAIT_S` 참고 줄(시연에 필요 없다). 범위 모드 비밀값 검사 권장은 위 검증으로 이미 했다.

## 대조한 원본
- README.md 1·3·4·5·6·7·10·11절
- app/sandbox/
  - Dockerfile, stage.sh, build_kb.sh, demo.sh, audit.sh
  - policy.yaml, policy-publish-approved.yaml
  - violation_tests.md, x1_evidence.md
- docs/
  - engineering-notes.md, operations.md 5.1·5.2·9절
  - contracts.md, security.md
- app/
  - pyproject.toml
  - retrieval/__main__.py, index.py, embedder.py, index/kb/manifest.json
  - loop/__main__.py, nemotron.py
  - common/limits.py, schema.py
  - agent/nim_client.py
- 평가 사례, 기대 결과, run_cases.py는 열지 않았다.

## 지시와 원본이 어긋난 점(원본을 따랐다)
1. **색인 검색**: 지시의 `python3 -m retrieval query`는 macOS 시스템 python3 3.9.6에서 돌지 않는다. 그래서 `app/`에서 `uv run python -m retrieval query --index index/kb --embedder local:<bge-m3 폴더> "<질문>"`로 썼다. 먼저 `uv sync --extra local-embed`가 필요하다.
2. **`credential_unavailable`**: 저장소에서 찾지 못했다(git grep 0건). 실측 함정 표에 넣지 않고, 표 밖에 "전달받았으나 확인 못 함 `[미확인]`"으로만 적었다.
3. **`NIM_BASE_URL`·`NIM_MODEL`**: 이미 main의 `app/agent/nim_client.py`에 있어 "(병합 예정)"을 붙이지 않았다. "(병합 예정)"은 `NIM_API_KEY_ENV`와 `app/web/server.py`에만 붙였다. 샌드박스 정책은 integrate.api.nvidia.com만 열기 때문에, 다른 엔드포인트를 쓰려면 정책도 바꿔야 한다고 `[추론]`으로 적었다.
4. **나중 게시를 호스트에서 부르는 명령**: 원본에 글자 그대로 없다. demo.sh의 exec 형식으로 조립하고 `[추론]`으로 표시했다.
5. **심사자가 자기 토큰으로 게시하는 경우**: `PUBLISH_REPO`와 `policy-publish-approved.yaml`의 `path:`를 둘 다 바꿔야 한다. demo.sh approve는 둘이 다르면 거부한다. 5절 앞에 적었다.

## 확인 못 한 것([미확인])
- 리눅스 Docker에서 도는지
- 단계별 시간: uv sync, stage.sh, docker build, sandbox create, 시연 각 장면
- 출력 줄: openshell status, provider create, sandbox create
- NVIDIA provider 프로필 id와 프로필 YAML(저장소에 없다)
- 최종 이미지에 넣은 입력 폴더
- demo.sh approve의 종료 코드
- app/web/server.py의 동작과 포트

## 문서 수정 제안(상위가 판단)
- README 3절에 NVIDIA provider 등록 명령과 프로필 id가 없다.
- README 5절 표에 `demo.sh logs` 장면이 없다.
- `app/sandbox/violation_tests.md`가 가리키는 `app/tests/fixtures/input` 경로가 지금 저장소에 없다.
