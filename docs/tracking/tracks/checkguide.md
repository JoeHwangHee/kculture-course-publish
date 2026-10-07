# 트랙 checkguide 최종 보고(지시 G-check)

## 한 일
- `app/checkguide/CHECK_GUIDE.md`(331줄)를 새로 만들었다. 심사자가 기준마다 직접 확인할 수 있는 가이드다.
  - 맨 앞: 용어 목록(colima, X1, B1 등)과 "5분 확인 순서"(가장 강한 증거 5개)
  - 기준 7개 절: 1 실행 경계·Runtime policy, 2 사후 감사, 3 의사결정 확인, 4 Agent-Native Infrastructure, 5 Deployment Flexibility, 6 Deterministic Governance, 7 평가 결과
  - 절마다 주장 / 확인 방법(명령·기대 결과) / 증거 파일(경로·줄) / 실측 기록 / 한계
- 병합 때 상위가 `docs/guide/CHECK.md`로 옮기고 README에서 잇는다(지시대로).

## 커밋
- `2a07ec2` docs(checkguide): 심사 기준별 확인 가이드 CHECK_GUIDE.md(커밋 하나)

## 대조한 원본 파일
README.md(1~12절), app/sandbox/policy.yaml, app/sandbox/policy-publish-approved.yaml, app/sandbox/violation_tests.md, app/sandbox/x1_evidence.md, app/sandbox/audit.sh, app/sandbox/demo.sh, app/sandbox/Dockerfile(27행), app/common/schema.py, app/common/limits.py, app/agent/nim_client.py, app/loop/(router·runner·executor·planner·publish·trace·nemotron·baseline·__main__), app/tools/(files·evidence·places), app/*/tests 시험 이름, docs/contracts.md(4절, 6절 설계 2.3~2.6·4.3·4.4·4.6·4.10·5), docs/tracking/decisions/index.md, docs/tracking/status.md, docs/engineering-notes.md 3절, docs/operations.md, docs/business-rules.md "쓰지 않는 서술"

## 검증 명령과 종료 코드
- 문서의 저장소 경로 65개 `test -e`: 없는 것은 `docs/guide/RUN.md`(병합 예정 표시) 하나
- 문서의 시험 ID 36개 `cd app && uv run --offline pytest --collect-only -q ...`: 44 collected, 종료 0
- `cd app && uv run --offline pytest -q common/tests loop/tests tools/tests`: 558 passed, 종료 0
- `cd app && uv run --offline pytest -q common/tests/test_trace_hash.py`: 16 passed, 종료 0
- 문서의 verify_trace 한 줄을 빈 입력에 실행: `OK`, 종료 0. 줄 하나를 고친 가짜 trace에서는 종료 1(검토 worker 실행)
- `diff app/sandbox/policy.yaml app/sandbox/policy-publish-approved.yaml`: 종료 1, 차이는 `github_issue` 블록뿐
- `python3 scripts/secret_scan.py main..HEAD`: 추가 행 331줄, 걸린 곳 0, 종료 0(오케스트레이터가 직접 실행)
- `git -c core.quotePath=false diff --no-renames --name-only main...HEAD`: `app/checkguide/CHECK_GUIDE.md` 하나(오케스트레이터가 직접 실행)
- 로컬 절대 경로 grep: 0건

## worker-reviewer 판정
- 1차 REQUEST_CHANGES. 반드시 고칠 것 4건:
  - 등급 다시 계산 절차의 필드(`source.source_type` → 청크 최상위 `source_type`)
  - vLLM 문장의 출처
  - 5절에 한계가 없고 주장이 단정형
  - X1·B1·colima 용어 설명 누락
- 고치면 좋은 것 9건도 받았다.
- 2차 APPROVE: 반드시 4건과 좋은 것 8건 반영. 남은 1건은 RUN.md 병합 예정 표시로, 지시상 예외다.
- worker-debugger는 부르지 않았다. 실패한 검증이 없었다.

## 지시문과 저장소가 다른 점
- `NIM_API_KEY_ENV`라는 환경변수는 없다.
  - 바꿔 끼울 수 있는 것은 `NIM_BASE_URL`·`NIM_MODEL` 둘이다.
  - 키 변수 이름은 코드 상수 `API_KEY_ENV = "NVIDIA_API_KEY"`(app/agent/nim_client.py 30행)다.
  - 문서에는 실제 상태대로 적었다.
- trace 줄 종류는 지시의 6가지가 아니라 schema.py 87~96행의 10가지 전부를 적었다.
- "코드 규칙"과 "모델 판단"은 `model`이 null인지가 아니라 `why` 문구로 가른다. 근거는 코드다. 문서 3절에 표로 적었다.

## 확인 못 한 것([미확인]으로 둠)
- secrets 장면을 샌드박스 안에서 앱으로 실행해 trace에 `DENIED_BY_SANDBOX`가 남은 기록(run_id·trace)이 저장소에 없다.
  - 커널 쪽 근거는 B1의 V1~V3이다. 앱이 아니라 `cat`/`ls`로 찔러 본 시험이다.
  - 앱 쪽 근거는 샌드박스 밖 단위 시험으로 나눠 달았다.
- B1 때의 Landlock `rules_applied` 값. 저장소의 `rules_applied:13 skipped:0`은 11:15 이미지 r1 기록이다.
- 등급을 다시 계산하는 채점 스크립트 내용(git 밖, sha256으로만 동결). 평가 사례를 공개할 위치.
- Brev NIM의 주소·모델(decisions/index.md 14:3x 줄 자체가 미확인).
- 엔드포인트를 실제로 바꿔 실행한 기록 없음(5절 한계에 적음).

## 남은 일·문서 수정 제안(상위)
- `docs/guide/RUN.md`가 병합되지 않으면 CHECK_GUIDE 4절의 RUN.md 링크를 README 3절로 바꾼다.
- 5절의 vLLM 문장은 근거가 상위 지시(저장소 밖)다. 공개 전에 팀 vLLM 연결이 병합되지 않으면 지운다(검토 권고).
- 지시문 양식의 `NIM_API_KEY_ENV`는 코드에 없다. 다른 문서에 같은 이름이 있으면 바로잡는다.
- 31행 `test_trace_hash.py`는 아직 `[문서만]`이다. 실행 기록(16 passed, 종료 0)으로 바꿀 수 있다.
