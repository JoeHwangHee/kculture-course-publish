# 운영: 당일 순서와 명령

근거 표시: `[사실: 출처]` · `[추론]` · `[DESIGN]`(팀 규칙) · `[미확인]`. 명령 끝 표시: `[예선 실행]`(예선에서 돌려 결과가 기록됨) · `[문서만]`(실행 기록 없음, 처음 쓸 때 결과를 확인). 출처 경로는 예선 저장소 루트 기준이다. 판(버전)이 바뀌었을 수 있으니 쓰기 전에 `--version`이나 `--help`로 판과 옵션을 확인한다.

**확인된 판** `[사실: 예선 artifacts/openshell/violation_tests.md, docs/eval/SKILL_DICTIONARY.md, 2026-09-24~26]`: OpenShell 0.0.116, NemoClaw v0.0.124, OpenClaw 2026.7.1, nvidia-nat·nvidia-nat-profiler 1.9.0, `skills` CLI 1.7.0, Python 3.12.13. 예선 환경은 macOS Apple Silicon + colima(Docker 29.5.2)였다.

## 1. 당일 시간표(2026-10-07)

공식 시간표(09:00~09:30 집결·정비, 09:30~10:30 온보딩, 10:30~17:30 해커톤 진행, 17:30~18:30 피칭·심사) 안에서 짠 팀 시간표다. "경과"는 10:30을 0:00으로 센 시간이다 `[DESIGN: 사용자 승인 2026-10-06]`.

| 시각 | 경과 | 방식 | Hacker(팀장 + 에이전트) | Hustler | 넘어가는 조건 |
|---|---|---|---|---|---|
| 09:00~09:30 | — | 정비 | 아침 점검(2절), Hustler GitHub 계정 초대(저장소는 2026-10-07 05:45에 만듦) | clone, `hustler/` 브랜치 열기 | 점검 결과를 상태 기록에 남김 |
| 09:30~10:30 | — | 온보딩 | 미션이 나오면 그때부터 접수(3절) 1~3번 시작. 심사 기준·발표 길이·제출물 확인 | 같이 듣는다 | — |
| 10:30~11:10 | 0:00 | 함께 | 접수 마무리: 한 문장 주장, 시연 장면, X1 대상·타임박스·대체 경로 → 팀장 확인 | 문제·사용자·메시지 정리 | 팀장 확인. 확인 즉시 X1 시작 |
| 11:10~12:00 | 0:40 | 분리 | X1 통합 시험(45~50분), 계약·평가 초안 | 경험자 인터뷰 2건 이상, 출처 있는 숫자 | X1 통과 기록(명령, 종료 코드, 로그 발췌) 또는 승인된 대체 경로 발동과 알림 |
| 12:00~12:10 | 1:30 | **접점 1** | 구현 가능 범위 + X1 결과 | 검증 결과 | **방향 유지 또는 전환 1회**(유일한 기회) |
| 12:10~12:30 | 1:40 | — | **동결 1 커밋**(지표 정의·사례·기대 결과·홀드아웃 분리)을 코드 없이 따로 → dryforge `ready`(트랙 묶음과 0단계 포함. 대상 파일은 `app/` 아래, 평가 사례·기대 결과·홀드아웃 경로는 제외라고 명시) | — | 동결 1 커밋 해시, `.dryforge/`에 작업 문서, 트랙 표 |
| 12:30~15:00 | 2:00 | 분리 | 0단계(공통 뼈대·스키마·가짜 입력·`app/pyproject.toml`·lock)를 worker로 → 검사·검토·squash → push → 트랙 나누기(3.1절: `orch.py spawn`·지시 `send`·`launch`) → 하위 오케스트레이터가 트랙별로 핵심 기능 하나를 끝까지(병렬): 결정적 계산, 모델 호출, 검증기, 한도 강제. 상위는 보고 받기·요청 처리·트랙 병합 | 예시 자료·화면 문구·발표 초안 | 핵심 기능 하나가 처음부터 끝까지 동작 |
| 15:00~15:10 | 4:30 | **접점 2** | **기능 동결**: 시연 밖 기능 제거 | 발표·시연 일치 확인 | 새 기능을 넣지 않기로 합의 |
| 15:10~16:30 | 4:40 | 분리 | **동결 2**(채점 스크립트) → 실행기 리허설 → 기준선과 본 시스템 1회 측정·채점 → 시연 경로 안정화(같은 경로 3회 반복, 끊기는 곳은 동선에서 뺌) → NVIDIA 증거 묶음(6절) → 화면 1개, README → 녹화 백업(1~2분) | 대본(인터뷰 인용·숫자) | 결과표(x/N, Wilson 구간), 녹화를 다시 재생해 확인 |
| 16:30~17:30 | 6:00 | 함께 | 화면 조작, 리허설 3회, 최종 커밋 | 발표, 시간 관리 | 17:30 전 최종 커밋 |
| 17:30~18:30 | — | — | 피칭·심사 | 발표 | — |

**넘어가는 규칙**
- 표의 시각은 늦어도 끝낼 시각이다. 앞 단계가 마무리되고 근거(검사 종료 코드, 검토 판정)가 모이면 시각 전이라도 넘어간다.
- 다만 절대 규칙, 계약 승인, "평가 고정 → 결과" 순서는 이 이유로 건너뛰지 않는다.
- X1은 미루지 않는다. 접수에 대한 팀장의 첫 확인을 받으면 바로 띄운다.
- 15:10~16:30은 빠듯하다. NVIDIA 증거(위반 시험표, trace, 프로파일)는 만드는 즉시 모으고, 시간이 모자라면 접수 때 정한 줄일 순서를 따른다.
- 09:30까지 환경(키, OpenShell, Docker)이 서 있지 않으면 X1 타임박스를 접수 때 다시 정한다.

## 2. 아침 점검(09:00~09:30)

폴더 루트에서 순서대로 돌린다. 앞 단계가 실패하면 뒤 단계는 의미가 없다.

```
colima start                         # Docker. 꺼져 있으면 게이트웨이에 연결되지 않는다
colima status
openshell --version                  # 기대: 0.0.116
openshell status                     # 기대: 게이트웨이 nemoclaw(https://127.0.0.1:8080)에 연결·인증
openshell sandbox list               # Error인 샌드박스가 있으면 아래 "샌드박스 Error 대응"을 팀장에게 올린다
python3 scripts/with_nvidia_key.py --env-file .env -- python3 scripts/nim_ping.py   # 기대: HTTP 200 · 모델 …, 종료 0. 키가 닿으므로 팀장 승인 뒤
uv --version
gh auth status
npx skills --version
```
- 결과는 `docs/tracking/status.md`의 점검 결과 표에 적는다.
- 사람이 챙길 것: 노트북 전원·영상 어댑터, 화면 녹화 도구, 발표 자료 틀. 발표자(Hustler)와 화면 조작(팀장)을 다시 확인한다.
- **비공개 GitHub 저장소(한 번만. 2026-10-07 05:45에 이미 만들었다. 다시 만들 때만 쓴다)**: `git switch main`으로 main을 체크아웃하고, `python3 scripts/secret_scan.py main`(main 이력 전체)이 종료 0인지 본 뒤 비공개 저장소를 만들어 올린다. 예: `gh repo create <이름> --private --source . --remote origin --push`(지금 체크아웃한 브랜치가 원격 기본 브랜치가 된다 `[추론]`). GitHub 저장소 설정에서 Hustler 계정을 쓰기 권한으로 초대한다. main 보호 규칙(직접 push 금지)은 요금제에 따라 비공개 저장소에서 못 쓸 수 있다 `[미확인]`. 못 쓰면 main push 금지는 문서 규칙으로만 지켜진다.
- **Hustler 노트북(한 번만, Hustler)**: git 2.31 이상, python3, GitHub 인증을 준비하고 `git clone <비공개 저장소 주소> nvidia-hackathon-2026-final` → `git switch -c hustler/<작업ID>-<설명> --no-track origin/main`. Hustler 세션은 그 폴더에서 띄운다. 확인: `git status`가 `hustler/<작업ID>-…` 브랜치를 보인다.
- **Hustler 브랜치 받기(병합할 때마다, 팀장 쪽 세션)**: `git fetch origin` → `git -c core.quotePath=false diff --no-renames --name-only main...origin/hustler/<…>`에 Hacker 경로가 없는지 → `python3 scripts/secret_scan.py main..origin/hustler/<…>` 종료 0 → 독립 검토 → `git switch main && git merge --squash origin/hustler/<…> && git commit -m "hustler(<작업ID>): <요약>"` → `python3 scripts/secret_scan.py origin/main..main` 종료 0 → `git push origin main` → Hustler에게 알린다. 원격의 Hustler 브랜치는 지우지 않는다(지우려면 팀장 확인).
- **main이 바뀔 때마다(팀장 쪽 세션, 원격을 만든 뒤)**: 작업 병합·미션 접수 결과·계약 변경은 바로, 기록 파일 예외 커밋은 다음 push 때 모아서 `python3 scripts/secret_scan.py origin/main..main` 종료 0 → `git push origin main` → Hustler에게 알린다. 특히 계약의 "Hustler가 만들고 코드가 읽는 데이터" 칸이 바뀌면 바로 올린다.
- **샌드박스 Error 대응**(팀장 승인 뒤, X1 타임박스 안에서): ① NemoClaw가 관리하는 게이트웨이 서비스를 재시작해 상태를 다시 맞춘다(방법 `[미확인]`) ② 안 되면 새 시연 샌드박스를 온보딩한다(5.3절, 예선 X1 기준 2~3시간. 온보딩은 provider `nvidia-prod`를 만들므로 이미 있는 같은 이름 provider와의 관계를 먼저 확인한다 `[미확인]`) ③ 시연 경로는 미루고 OpenShell만 쓰는 새 샌드박스로 시작한다(provider `tradesentry-nvidia` 재사용). 이미 실패한 것: `openshell sandbox start`(Stopped만 가능), `openshell sandbox stop`(Ready만 가능), 컨테이너 직접 시작, `nemoclaw x1-demo start`, `nemoclaw x1-demo recover`.
- **끄고 켜는 순서**: 끌 때는 샌드박스가 Ready일 때 `openshell sandbox stop <이름>`으로 먼저 멈춘 뒤 `colima stop`. 켤 때는 `colima start` 뒤 `openshell sandbox start <이름>` `[추론: 아직 시험하지 않음]`. colima를 막 켠 직후 바로 끄지 않는다.

## 3. 미션 접수(공개 즉시 시작)

결과를 쓰는 곳: 미션 원문·다시 말하기·질문·심사 매핑·X1 대상은 `docs/tracking/mission.md`, 트랙끼리의 약속과 한 문장 주장·지표 정의의 값은 `docs/contracts.md`의 "트랙끼리의 약속" 표(정본), 하는 일 / 하지 않는 일은 `docs/business-rules.md`의 "한 문장 주장과 범위" 절, 실행 사슬은 `docs/architecture.md`의 "제품의 실행 사슬" 절, 트랙·파일 소유는 `docs/standards.md`의 "파일 소유" 절, 줄일 순서·지킬 것은 `docs/tracking/status.md`. 진입 안내(`CLAUDE.md` = `AGENTS.md`)의 "미션 요약"은 주장은 계약 표에서, 나머지는 위 각 문서에서 글자 그대로 옮겨 채운다.

**두 번에 나눠 확인한다.** 1~7번과 10번으로 10:30~11:10 안에 팀장의 첫 확인을 받고 X1을 띄운다. 8·9번(계약·평가 초안)은 11:10~12:00에 X1과 나란히 쓰고 접점 1 전에 확인받는다.

1. **원문 보관**: 요약하지 말고 그대로 붙인다. 사진이면 글로 옮긴다.
2. **다시 말하기**: 한 문단. 해석이 갈리는 곳은 질문으로 뽑아 "주최측에 물을 것"과 "팀이 정할 것"으로 나눈다. 제출물 형식, 써야 하는 도구, Brev 사용 의무, 제공 자료를 확인한다. 갈리는 해석과 주최측 질문은 다른 접수 일보다 먼저 팀장에게 올리고, 그동안 접수를 계속한다.
3. **심사 기준 매핑표**: `기준 | 보여 줄 증거 | 어디서(파일·화면·발표 장면)`. 1번 기준(NVIDIA 활용 심도)은 "그 구성요소를 빼면 무엇이 사라지나"로 적는다.
4. **한 문장 주장**: "A가 B보다 C 조건에서 D 지표가 낫다."
5. **하는 일 / 하지 않는 일**: 판단의 성격, 쓰는 사람, 범위로 나눈다. 과장할 여지를 먼저 막는다.
6. **실행 사슬 그림**: 요청 → 하네스 → 스킬 → 샌드박스 안 실행 → 모델(NIM) → 검증 → 결과 → 사람의 결정. 경계(호스트·컨테이너·네트워크·키 경로)마다 "처음 통과시켜 볼 것"을 표시한다.
7. **가장 위험한 연결 3개**: 문서만으로 동작을 확정할 수 없는 경계. X1 대상이다. 대상마다 타임박스와 대체 경로를 적는다.
8. **계약 초안**: 입출력 형식, 상태값, 이름, 경로, 명령, 한도.
9. **평가 초안**: 사례 5~10개와 기대 결과, 결정적 채점 방법, 기준선(같은 조건에서 처리만 다른 비교 대상).
10. **줄일 순서 3개와 끝까지 지킬 것 3개.**
11. **팀장 확인**: 결정이 필요한 것만 번호를 매겨 묻는다. 첫 확인(1~7, 10)을 받으면 X1을 바로 띄운다.
12. **접수 결과 커밋**: 접수 결과는 기록 파일 예외에 들지 않는다. 8·9번까지 확인받은 뒤 접점 1 전에 한 번, 브랜치 하나(`mission/<작업ID>-<설명>`)로 커밋 → `python3 scripts/secret_scan.py <범위>` 종료 0 → 독립 검토 → squash 병합한다. 동결 1은 접점 1 뒤에 따로 커밋한다. X1을 같은 작업 폴더에서 돌리는 동안에는 브랜치를 바꾸지 않는다(X1은 worktree에서 돌리거나, 끝난 뒤 바꾼다). 이걸 끝내야 작업 트리가 깨끗해져 0단계 브랜치를 열 수 있다. 핵심 기능 구현은 그 뒤 동결 1 → dryforge `ready`(작업 설계) → 0단계 → 트랙 나누기(3.1절)로 한다.

## 3.1 트랙 나누기와 지휘(12:30~, 상위 오케스트레이터)

용어: 상위 오케스트레이터(main 폴더의 팀장 주 에이전트 세션), 하위 오케스트레이터(트랙 하나를 맡아 worker를 지휘하는 별도 Claude 세션), worker(서브에이전트: 구현자·검토자·debugger), 작업기록 폴더(`app/.orch/<트랙>/log/`, git 제외), flag(새 지시·보고가 왔다는 표시 파일. 읽으면 `.ack`로 바뀐다). 명령의 입력·출력·종료 코드는 `docs/contracts.md` 5절.

1. **트랙 정하기**: `ready`의 작업을 고치는 파일 집합으로 묶는다. 묶음끼리 파일이 겹치지 않게 하고, 둘 이상이 쓰는 파일은 0단계에 넣는다. 묶음 수가 하위 오케스트레이터 수다(최대 3, 조정값). 하나면 하위를 만들지 않고 상위가 worker를 직접 지휘한다. 트랙 표를 `docs/standards.md` 7절에 적는다.
2. **0단계**(상위): 공통 뼈대·스키마·가짜 입력·`app/pyproject.toml`·`uv.lock`·키 없이 도는 시험 1개를 `worker-implementer`로 만든다 → `worker-reviewer` → 브랜치 검사 → 독립 검토 → squash → push. 트랙 worktree는 이 main에서 갈라지므로 공통 파일이 모든 트랙에 보인다.
3. **트랙 만들기**: `python3 scripts/orch.py spawn <트랙> --scope app/<트랙>/`. worktree `app/.orch/<트랙>/wt`(브랜치 `track/<트랙>`)와 작업기록 폴더가 생긴다.
4. **지시 보내기**: `python3 scripts/orch.py send <트랙> --from top --kind instruction --body-file -`에 지시문을 넣는다(아래 양식).
5. **띄우기**: `python3 scripts/orch.py launch <트랙>`. 새 터미널 창에서 그 worktree의 Claude 세션이 뜬다. 처음에는 폴더 신뢰 확인이, 그 뒤로는 권한 확인이 그 창에 뜬다. 사람이 그 창에서 받는다.
6. **받기**: `python3 scripts/orch.py wait --for top --timeout 1800`을 백그라운드로 돌린다(flag가 생기면 끝나 세션이 깨어난다). 받은 파일을 읽고 `ack <트랙> <번호> --for top`. `request`에는 `answer`로 답한다. 키가 닿는 요청은 팀장 승인 뒤 상위가 main 폴더에서 키 래퍼로 돌리고, 종료 코드와 걸러낸 출력만 답한다. 전체 상황은 `python3 scripts/orch.py status`.
7. **계약·공통 파일이 바뀌면**: main에 넣은 뒤 각 트랙에 `instruction`으로 알린다. 하위는 `git merge main`으로 받는다(트랙은 squash로 들어가므로 이 병합 커밋은 main에 남지 않는다).
8. **병합**: `final`을 받으면 `git -c core.quotePath=false diff --no-renames --name-only main...track/<트랙>`에 범위 밖 경로가 없는지 → `python3 scripts/secret_scan.py main..track/<트랙>` 종료 0 → 상위가 부른 독립 검토 `PASS` → `git merge --squash track/<트랙>` → 최종 보고 본문을 `docs/tracking/tracks/<트랙>.md`로 옮겨 같은 커밋에 넣는다(`git add <파일>`) → 커밋 → 최신 main에서 전체 시험 → `python3 scripts/secret_scan.py origin/main..main` 종료 0 → push → Hustler에게 알린다. 트랙끼리 파일이 겹치지 않으면 병합 순서는 상관없다.
9. **정리**: 병합한 트랙의 worktree는 팀장 확인 뒤 `git worktree remove app/.orch/<트랙>/wt`로 지운다. 브랜치와 작업기록 폴더는 대회가 끝날 때까지 둔다. 그래서 같은 트랙 이름은 다시 쓸 수 없다. 같은 폴더의 다음 작업은 새 트랙 이름으로 연다(`--scope`는 같은 폴더여도 된다).

**지시문(`instruction`) 양식**
1. 트랙, 범위(`app/<트랙>/`), base 커밋, 시한(조정값)
2. 팀장 요청 원문, 이 트랙의 작업(`ready` 설계에서 해당 작업을 글자 그대로), 완료 조건과 검증 명령(종료 코드 0)
3. 계약 값(`docs/contracts.md`에서 글자 그대로). worktree에는 `.dryforge/`의 설계 문서와 git이 추적하지 않는 자료가 없으므로 필요한 내용을 지시문에 직접 넣는다. 키 값은 넣지 않는다
4. 고정 금지 문장(`docs/engineering-notes.md` 8절)
5. 보고 시점: 작업마다 `report`, 막히면 `request`, 끝나면 `final`

## 4. 평가 절차

1. 지표 정의를 3줄로 쓴다(접수 9번).
2. 사례 파일과 기대 결과를 쓰고, 홀드아웃 몇 건을 떼어 둔다.
3. **동결 1 커밋**(12:10~12:30, 접점 1 뒤). 지표·사례·기대 결과·홀드아웃만 담고 코드나 뼈대를 섞지 않는다(동결 해시가 코드와 섞이지 않게). 그 뒤 dryforge `ready` → 0단계 → 트랙 나누기(3.1절).
4. 기능을 구현한다.
5. **동결 2 커밋**: 채점 스크립트를 완성해 커밋한다(15:10 직후).
6. 실행기를 리허설한다. 홀드아웃이 아닌 사례로 한다. 예선의 첫 공식 실행 무효는 실행기가 그 자료 묶음을 받지 않는 결함이었고, A등급 주장 보류는 운영자 값에 참/거짓 대신 문장을 넣은 형식 오류였다. 둘 다 리허설로 잡을 수 있었다.
7. 기준선과 본 시스템을 같은 사례·같은 조건으로 1회 실행하고 채점한다. 홀드아웃은 마지막에 1회만 돌린다.
8. 결과표를 만든다. 숫자는 채점 스크립트 출력에서만 옮긴다.

## 5. NVIDIA 도구 명령

### 5.1 NIM
- 엔드포인트 `https://integrate.api.nvidia.com/v1/chat/completions`, 모델 `nvidia/nemotron-3-super-120b-a12b` `[예선 실행: HTTP 200]`.
- 키·모델 확인: 2절의 `nim_ping` 명령.
- 도구 호출 왕복까지 볼 때: 예선 저장소 `scripts/g4_nim_toolcall_probe.py`를 같은 키 래퍼로 돌린다 `[문서만]`. 이 probe는 이미 있는 환경변수를 덮어쓰지 않으므로 래퍼가 넘긴 키로 확인된다. 결과 파일은 예선 저장소 `artifacts/runs/`(git 추적 제외)에 생긴다. 예선 작업 폴더에 출력을 남기지 않도록 별도 worktree(`git worktree add --detach <새 폴더> origin/main`, 브랜치 없이 특정 커밋을 꺼낸 작업 복사본)에서 돌린다.

**예선 모델 설정값** `[예선 실행: configs/model/model.json, config_version model-1.7]`

| 묶음 | 값 |
|---|---|
| 요청 | temperature 1.0, top_p 0.95, max_tokens 8192, tool_turn_max_tokens 1024, enable_thinking false |
| 재전송 | 5xx·429만 요청당 3회, 대기 5·10·20초. `Retry-After`가 오면 `max(지수 대기, min(Retry-After, 60초))`. 클라이언트 자동 재시도는 끄고 코드가 직접 보낸다. 리디렉션은 따르지 않는다 |
| 시간 제한 | 요청당 60초 |
| 사례당 한도 | 모델 요청 10회, 누적 토큰 128,000, 경과 시간 300초, 도구 시도 8회 |
| 속도 조절 | 요청 간격 최소 60초, 분당 토큰 50,000, 429 뒤 120초 |

요청 모양: `tools`, `tool_choice`, `chat_template_kwargs.enable_thinking`. `response_format {"type":"json_object"}`는 도구를 싣지 않은 요청에만 넣는다.

### 5.2 OpenShell(0.0.116)
설치·기동(macOS + colima, 이미 설치돼 있으면 건너뛴다) `[예선 실행]`
```
curl -fsSL -o install.sh https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh
OPENSHELL_VERSION=v0.0.116 sh install.sh      # compute driver가 설정되지 않아 종료 1로 끝난다(정상)
# 게이트웨이 설정 파일(gateway.env)에 OPENSHELL_DRIVERS=docker와 DOCKER_HOST=<colima Docker 소켓>을 쓴다(팀장 승인 뒤). 키는 넣지 않는다
brew services restart nvidia/openshell/openshell   # 설치 직후에만. 샌드박스 Error 복구용으로는 팀장 승인 없이 쓰지 않는다(게이트웨이를 깨뜨릴 수 있다)
openshell status
```
샌드박스와 정책 `[예선 실행]`
```
DOCKER_HOST=<colima Docker 소켓> openshell sandbox create --name <이름> --from <Dockerfile 폴더> \
  --policy <정책 YAML> --provider <provider 이름> --no-auto-providers --detach
openshell policy set <이름> --policy <정책 YAML> --wait
openshell policy get <이름> --full
openshell sandbox exec -n <이름> --no-tty --timeout <초> -- <명령> < /dev/null   # 표준 입력을 닫는다. 열어 두면 끝나도 돌아오지 않는다
openshell sandbox upload <이름> <로컬 경로> <샌드박스 경로>
openshell sandbox download <이름> /sandbox/<경로> <로컬 경로>
openshell logs <이름> --since <기간> -n <행 수>
openshell inference get                        # 실행 묶음 앞뒤로 "Not configured"인지 기록
openshell inference delete                     # 관리형 추론 경로를 지운다
```
`openshell sandbox delete <이름>`은 `[문서만]`이다.

provider 만들기(키가 닿는다, 팀장 승인 뒤) `[예선 실행]`
```
openshell provider profile import -f <provider 프로필 YAML>
python3 scripts/with_nvidia_key.py --env-file .env -- \
  openshell provider create --name <provider 이름> --type <프로필 id> --credential NVIDIA_API_KEY
```

정책 네트워크 블록 예 `[예선 실행: configs/openshell/policy.yaml]`
```yaml
network_policies:
  tradesentry_nim_chat:
    name: tradesentry-nim-chat
    endpoints:
    - host: integrate.api.nvidia.com
      port: 443
      protocol: rest
      enforcement: enforce
      rules:
      - allow:
          method: POST
          path: /v1/chat/completions
    binaries:
    - path: /opt/tradesentry/python/**
```

위반 시험표의 열: `# | 샌드박스 | 요건 | 입력 | 예측 | 종료 코드 | HTTP | 분류 | 로그 근거 | 일치 | 비고`. 분류는 incomplete, access-denial, completed, command failed다. 대표 행은 미끼 정답 파일 읽기(EACCES), 비허용 호스트, 비허용 실행 파일(curl)로 NIM 호출, 샌드박스 안 실제 키 0건, 대조군(허용 실행 파일의 NIM 호출 200)이다. 시험 도구는 예선 저장소 `scripts/openshell_violation_tests.py`다.

### 5.3 NemoClaw·OpenClaw(v0.0.124 / 2026.7.1)
**설치와 온보딩은 라이선스·제3자 고지 수락 플래그가 들어 있다. 팀장 승인 뒤에만 돌린다.** `[예선 실행]`
```
curl -fsSL -o nemoclaw.sh https://www.nvidia.com/nemoclaw.sh
env -u NVIDIA_API_KEY -u NVIDIA_INFERENCE_API_KEY DOCKER_HOST=<colima Docker 소켓> \
  NEMOCLAW_INSTALL_TAG=v0.0.124 NEMOCLAW_PROVIDER=build bash nemoclaw.sh --yes-i-accept-third-party-software
# 키 없이 돌리면 온보딩 [3/8]에서 종료 1로 끝난다(정상)

python3 scripts/with_nvidia_key.py --env-file .env --export-as NVIDIA_INFERENCE_API_KEY -- \
  env DOCKER_HOST=<colima Docker 소켓> NEMOCLAW_PROVIDER=build \
  NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b NEMOCLAW_POLICY_TIER=restricted NEMOCLAW_POLICY_MODE=skip \
  NEMOCLAW_WEB_SEARCH_PROVIDER=none NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 \
  nemoclaw onboard --non-interactive --fresh --name <이름> --yes-i-accept-third-party-software
```
온보딩이 바꾸는 것 `[예선 실행]`
- 게이트웨이 설정 파일을 다시 쓴다(포트 8080).
- provider `nvidia-prod`를 만든다.
- **작업 공간 추론 경로(`inference.local`)를 만든다.**
- 기본 네트워크 블록 7개를 둔다.

온보딩 뒤에 할 일 `[예선 실행]`
1. `openshell inference delete`로 온보딩이 만든 추론 경로를 지운다.
2. 네트워크 정책을 `nvidia` 블록 하나로 좁힌다. 실행 파일 `/usr/local/bin/node`, L7 `POST /v1/chat/completions` 하나.
3. 샌드박스 안 `/sandbox/.openclaw/openclaw.json`의 `models.providers.inference`에서 `baseUrl`을 `https://integrate.api.nvidia.com/v1`로, `apiKey`를 자리표시 값으로 바꾸고 설정 해시를 다시 계산한다. 이 파일에는 게이트웨이 토큰이 있으니 내용을 출력하지 말고 필요한 키만 바꾼다. 대안 `nemoclaw <이름> config set …`은 `[문서만]`.
4. 정적 계층은 NemoClaw 판이 정하므로 그대로 둔다.

스킬과 에이전트 호출 `[예선 실행]`
```
nemoclaw <이름> skill install <스킬 폴더>/      # /sandbox/.openclaw/workspace/skills/<이름>에 들어간다
nemoclaw <이름> gateway restart
nemoclaw <이름> agent --agent main --json --timeout 300 -m "<요청>"
```
정리 `[문서만]`: `nemoclaw <이름> skill remove <스킬>`, `nemoclaw <이름> stop | start | destroy`, `nemoclaw uninstall [--keep-openshell]`.

포트: 대시보드 `127.0.0.1:18789`, 게이트웨이 `127.0.0.1:8080` `[문서만]`.

### 5.4 NAT(nvidia-nat·nvidia-nat-profiler 1.9.0)
- Python `>=3.11,<3.14`가 필요하다(uv 가상환경, 예선은 3.12.13).
- 사례 흐름 하나를 NAT 함수로 등록하고 `WorkflowBuilder`·`SessionManager`로 돌린다. NIM 호출은 자체 클라이언트가 하고, NAT에는 LLM_START/END(토큰 포함), TOOL_START/END, SPAN_START/END 이벤트로 기록만 남긴다 `[문서만: 예선 src/tradesentry/workflow/nat_wrap.py]`.
- 환경변수: `PYTHON_DOTENV_DISABLED=1`, `NAT_TELEMETRY_ENABLED=false`.
- 출력 `[예선 실행]`: 추적 `nat_trace.jsonl`, 프로파일 `workflow_profiling_metrics.json`, `workflow_profiling_report.txt`, `inference_optimization.json`, `standardized_data_all.csv`, `all_requests_profiler_traces.json`.

### 5.5 Agent Skills
NVIDIA 공식 스킬 설치. 먼저 `npx skills add <저장소> --list`로 이름을 확인한다(`--skill`을 여러 개 줄 때 동작은 증거가 없다).
```
npx skills add NVIDIA/OpenShell --skill openshell-cli --skill generate-sandbox-policy --skill debug-inference --agent claude-code -y   # [문서만]
npx skills add NVIDIA/skills --skill nemoclaw-user-guide --agent claude-code -y                                                       # [문서만]
npx skills add NVIDIA/skills --skill skill-card-generator                                                                              # [예선 실행]
```
설치 위치 `.agents/skills/`, `.claude/skills/`는 git이 추적하지 않는다. 우리가 만드는 런타임 스킬과 거버넌스 카드는 `app/skills/<이름>/`에 둔다. 아래 `scripts/`는 skill-card-generator 설치본 안의 스크립트이고, 이 저장소의 `scripts/`가 아니다. 저장소 루트에서 설치본 경로를 붙여 부른다(예: `.claude/skills/skill-card-generator/scripts/render_card.py`). 그래야 `app/skills/<이름>` 상대 경로가 맞는다. 설치 경로는 처음 쓸 때 확인한다 `[미확인]`.

거버넌스 카드(skill-card-generator 설치본 스크립트, `uv run --locked python`, jinja2 필요) `[예선 실행]`
```
scripts/discover_assets.py app/skills/<이름>
scripts/render_card.py --context <context.json> --template references/skill-card.md.j2 --out app/skills/<이름>/<이름>-card.md
scripts/validate_submission.py app/skills/<이름>/<이름>-card.md   # 렌더 직후 종료 1(소유자 항목 VERIFY 표시). 소유자가 확인하고 표시를 지우면 0
```

### 5.6 Brev
웹 콘솔 https://brev.nvidia.com (로그인 확인됨). Brev CLI는 설치돼 있지 않다. 크레딧은 인스턴스 시간으로 쓰므로 쓰지 않을 때는 인스턴스를 멈춘다 `[추론]`. 문서: https://docs.nvidia.com/brev/latest/index.html , https://docs.nvidia.com/brev/latest/concepts/launchables `[문서만]`.

## 6. NVIDIA 증거 묶음(15:10~16:30, 만드는 즉시 모은다)

- [ ] 구성요소별 삭제 시험 답: 빼면 무엇이 사라지나, 한 줄씩
- [ ] OpenShell: 라이브 정책 사본, 위반 시험표(예측·실측), 감사 로그 발췌(미끼 파일 EACCES, 비허용 호스트 거부, 비허용 실행 파일 거부, 샌드박스 안 실제 키 0건, 대조군 허용)
- [ ] NIM: 모델 ID, 엔드포인트, 실행별 요청 수·토큰(trace)
- [ ] NAT: `nat_trace.jsonl`, 프로파일 요약
- [ ] NemoClaw: 시연 기록(요청 → 스킬 → CLI → 결과), 스킬 호출 성공률(x/N)
- [ ] Agent Skills: `SKILL.md`, 쓴 공식 스킬 목록, (선택) 거버넌스 카드
- [ ] README에 "무엇이 어디에 있는지" 표 하나

## 7. 발표와 녹화

| 순서 | 길이(5분 기준) | 내용 |
|---|---|---|
| 1. 문제 | 0:30 | 현장 문제와 출처 있는 숫자 하나, 인터뷰에서 들은 말 |
| 2. 한 장 그림 | 0:40 | 실행 사슬, 샌드박스 경계, 외부 전송 한 경로 |
| 3. 시연 | 1:30 | 녹화 영상이 기본. 라이브는 여유가 있을 때만 |
| 4. NVIDIA 증거 | 0:40 | 6절 묶음에서 2~3개 |
| 5. 결과 | 0:40 | x/N, Wilson 구간, 자료 종류, 기준선 대비 |
| 6. 하지 않는 일과 다음 단계 | 0:20 | 범위와 과장 방지 |

- 발표 길이는 온보딩에서 확인하고 비율대로 줄인다.
- 녹화 백업(1~2분)은 16:30 전에 만들고 다시 재생해 확인한다. 실제 핵심 경로를 처음부터 끝까지 1회 찍는다. macOS 기본 화면 녹화를 쓴다.
- 경과 시간은 녹화분의 실제 값을 적는다. 편집으로 줄였으면 그렇게 적는다. 숫자는 결과표 문구를 그대로 쓴다.
- 리허설은 3회. Hustler가 발표하고 팀장이 화면을 조작한다.

## 8. 쓰는 스킬(Claude Code)

| 쓰임 | 스킬 | 언제 | 준비 상태 |
|---|---|---|---|
| 작업 설계 | dryforge `ready`(상위 오케스트레이터만) | 동결 1 뒤 핵심 기능 설계, 트랙 묶음 | 켜져 있다. `go`는 쓰지 않는다 |
| 구현·검증·검토·디버깅 | worker 서브에이전트 `worker-implementer`·`worker-reviewer`·`worker-debugger`(`.claude/agents/`) | 0단계(상위가 지휘), 트랙 작업(하위가 지휘), 데모 경로 안정화, 제출 전 검토 | 정의 파일을 커밋했다. 실제로 불러 본 적은 없다 |
| 트랙 작업 공간·지시·보고 | `scripts/orch.py`(계약 문서 5절) | 트랙 나누기부터 병합까지 | 임시 저장소에서 명령별 종료 코드 확인(2026-10-07). `launch`의 창 띄우기는 이 저장소에서 아직 안 해 봤다 |
| 핵심 화면 프로토타입 | `claude-design` | 핵심 화면이 아직 없을 때만, 90분 안 | 폴더 `.claude/skills/`에 복사함(git 추적 제외). Claude Code 스킬 목록에 뜨는 것 확인(2026-10-06). 실제 산출물을 만들어 본 적은 없다 |
| 시스템 구조 그림 1장 | `architecture-diagram` | 제출 요구나 기술 설명이 필요할 때, 10~20분 | 같음 |

- `claude-design`은 사용자가 행동하고 결과를 확인하는 화면(조작·설정형)에 쓴다. 랜딩 페이지에 쓰지 않는다. 이미 작동하는 화면이 있으면 쓰지 않는다.
- `architecture-diagram`은 실제로 만든 구성만 그린다. 만들지 않은 배포 인프라나 클라우드 구성도를 그리면 신뢰를 잃는다. README에 Mermaid 한 장이면 충분하면 그쪽이 빠르다.
- 생성형 영상 스킬(`manim-video`, `ascii-video`)과 시안 비교 스킬(`sketch`)은 쓰지 않는다. 설치·렌더링 시간이 핵심 기능 안정화보다 우선순위가 낮고, `manim`·Pillow도 설치돼 있지 않다.
- 두 복사 스킬의 원본은 Hermes(다른 에이전트 도구) 스킬이다. 본문의 `write_file`은 Claude Code의 파일 쓰기 도구로 바꿔 읽는다.

## 9. 환경 설정

| 이름 | 뜻 | 어디서 |
|---|---|---|
| `NVIDIA_API_KEY` | NIM 키 | `.env`에만. 키 래퍼가 자식 환경에 넣는다 |
| `NVIDIA_INFERENCE_API_KEY` | NemoClaw 온보딩이 읽는 키 이름(값은 같은 키) | 키 래퍼 `--export-as` |
| `NIM_MODEL` | `nim_ping` 모델 이름(기본 `nvidia/nemotron-3-super-120b-a12b`) | 명령 앞에 붙인다 |
| `DOCKER_HOST` | colima Docker 소켓. `sandbox create`의 이미지 빌드와 NemoClaw 설치에 필요 | 명령 앞에 붙인다 |
| `PYTHON_DOTENV_DISABLED=1`, `NAT_TELEMETRY_ENABLED=false` | NAT가 `.env`를 읽지 않게, 원격 전송을 끄게 | NAT 실행 환경 |
