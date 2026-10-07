# nvidia-hackathon-2026-final: 2026 NVIDIA Korea Agentic AI Hackathon 본선

> `CLAUDE.md`와 `AGENTS.md`는 내용이 같다. Claude Code는 `CLAUDE.md`를, Codex(OpenAI의 코딩 에이전트 CLI)는 `AGENTS.md`를 먼저 읽는다. 고칠 때는 둘을 함께 고친다.

## 이 프로젝트

- 2026-10-07(수) 하루 오프라인 해커톤의 작업 폴더다. 공식 시간표는 09:00 집결·정비, 09:30 온보딩, **10:30~17:30 개발(7시간)**, 17:30~18:30 피칭·심사다. 미션은 당일 공개되고 주제는 미리 알 수 없다.
- 사람 둘이 각자 에이전트를 써서 만든다. 팀장이 Hacker(만드는 쪽)이고, 수요 검증·발표를 맡는 Hustler가 있다. 목표는 제품 완성이 아니다. 실제로 작동하는 핵심 기능 **하나**를 끊기지 않는 시연 장면 하나로 증명하고, 그 효과를 기준선과 비교한 숫자(x/N, Wilson 95% 구간)로 보이는 것이다.
- 기반은 NVIDIA 스택이다: NIM(OpenAI 호환 추론 API)/Nemotron, OpenShell(격리 샌드박스 런타임), NemoClaw(OpenShell 위 에이전트 참조 스택), NAT(에이전트 추적·프로파일 도구), Agent Skills, Brev(GPU 클라우드). 예선작은 TradeSentry다(관세청 수입통계 경보를 Nemotron 조사자·검수자가 반증하고 담당자의 다음 업무를 제안). 예선 저장소 `../nvidia-hackathon-2026/`(https://github.com/JoeHwangHee/nvidia-hackathon-2026)는 참고만 하고 고치지 않는다.
- 제품 코드는 미션 공개 뒤에 `app/` 아래에 생긴다. 지금 코드는 `scripts/`의 키·검사 도구 3개와 트랙 지휘 도구 `orch.py`뿐이다.
- 영역이 나뉜다. Hacker는 `app/`·`docs/`·`scripts/`·루트 파일 4개(`CLAUDE.md`, `AGENTS.md`, `.gitignore`, `README.md`)와 점(.)으로 시작하는 모든 경로(`.claude/`, `.agents/`, `.mcp.json`, `.github/` 등)를, Hustler는 그 밖(목업, 발표 자료, 예시 데이터)을 맡는다. Hustler는 자기 노트북에서 비공개 GitHub 저장소를 clone(원격 저장소를 통째로 내려받은 작업 복사본)해 `hustler/` 브랜치로 일하고, 그 브랜치를 push(원격에 올리기)해 넘긴다. Hustler 쪽 세션은 아래 "Hustler 쪽 세션이라면"을 먼저 따른다.
- 작업 설계는 상위 오케스트레이터(main 폴더에서 도는 팀장의 주 에이전트 세션)가 dryforge(Claude Code 플러그인)의 `ready`(작업 설계)로 한다. 구현·검증·검토·디버깅은 worker 서브에이전트(`.claude/agents/`의 `worker-implementer`·`worker-reviewer`·`worker-debugger`)가 맡는다. 공통 뼈대(0단계)는 상위가, 트랙 작업은 트랙마다 하위 오케스트레이터(트랙 하나를 맡아 worker를 지휘하는 별도 Claude 세션)가 지휘한다. 지시·보고는 `scripts/orch.py`가 작업기록 폴더(`app/.orch/<트랙>/log/`)에 만드는 파일과 flag(새 파일이 왔다는 표시 파일)로 주고받는다. dryforge `go`는 쓰지 않는다.

## 미션 요약(2026-10-07 설계 승인, 자세한 것은 `docs/tracking/roadmap.md`와 `docs/contracts.md` 6절)

- 한 문장 주장: K-콘텐츠를 보고 온 방문객이 목표를 말하면, 배경지를 잇는 코스를 짜고 각 장소 이름의 유래를 근거 등급과 함께 알려주는 에이전트.
- 하는 일
  - 요청의 무게를 Nemotron이 판단한다(답하지 않음, 실패하면 응답 불가). 14:35 팀장 결정으로 Claude에서 바꿨고, 제품은 Claude를 부르지 않는다.
  - 무거운 요청은 Nemotron이 계획하고, 코드가 도구로 실행한다: 테마 팩 장소 선택, 역명·유래 조회, 이름 정리, 근거 등급(코드 계산), 코스 파일 저장, GitHub 게시 요청.
  - 게시는 OpenShell이 막고, 팀장이 정책을 승인하면 통과한다.
  - 모든 판단은 의사결정 기록(해시 사슬)에, 허용·거부는 OpenShell 로그·정책 이력에 남긴다.
- 하지 않는 일: 실제 예약·결제·발송, 웹 검색, 실행 중 색인, 화면 개발, NemoClaw, 파인튜닝("학습"은 인덱싱).
- 실행 사슬: 요청 → 샌드박스 `kculture` 안 라우터(Nemotron) → 가벼우면 Nemotron 직답 / 무거우면 계획(Nemotron) → 도구 실행(지식 색인 JSON, `/hackathon/input` 직접 읽기) → `/hackathon/output/<run_id>/` → 게시 요청 → 사람의 승인(정책 파일 적용).
- 트랙과 파일 소유
  - `retrieval`(`app/retrieval/`), `tools`(`app/tools/`), `loop`(`app/loop/`)
  - 상위: `app/common/`·`app/conftest.py`·`app/pyproject.toml`·`uv.lock`·`app/sandbox/`·`app/index/`·`app/data/`·`docs/`
- X1 대상과 대체 경로(X1: 가장 위험한 연결을 첫 시간에 끝까지 한 번 통과시키는 시험): GitHub·Claude 토큰을 OpenShell provider가 대신 넣는 경로(45분)
  - 게시 쪽이 안 되면 키 없는 공개 서비스로 바꾼다.
  - Claude 쪽이 안 되면 멈추고 팀장이 정한다. X1은 13:17에 통과했고, 14:35 결정으로 Claude는 제품에서 뺐다.

## 문서 구조

```
nvidia-hackathon-2026-final/
├── CLAUDE.md                      ← 진입 안내(Claude Code). AGENTS.md와 내용이 같다
├── AGENTS.md                      ← 진입 안내(Codex)
├── docs/
│   ├── architecture.md            ← 지금 있는 구성요소, 제품 실행 사슬과 키가 경계를 넘는 방식, NVIDIA 스택 표, 제품 설계 원칙
│   ├── business-rules.md          ← 대회 조건, 팀 결정권표, 한 문장 주장·범위, 평가와 결과 표기, 대체 경로·줄일 순서, 자기 점검
│   ├── security.md                ← 지키는 자산, 키 경로(발급~폐기), 누가 무엇을 할 수 있나, 샌드박스 경계, 화면 가리기
│   ├── standards.md               ← 어기면 깨지는 규칙: 비밀값, git·main 반영, 검토, 계약, 평가 고정, 코드 경계, 파일 소유, 증거, 기록 형식
│   ├── engineering-notes.md       ← 함정(증상 → 원인 → 대응): 도구·dryforge·NIM·OpenShell·NemoClaw·NAT·macOS, 실패 패턴, 작업 설계 때 참고할 구현 방식, 예선 저장소 위치
│   ├── operations.md              ← 당일 시간표, 아침 점검, 미션 접수 절차, 평가 절차, NVIDIA 도구 명령, 증거 묶음, 발표·녹화, 쓰는 스킬
│   ├── contracts.md               ← `scripts/` 도구 4개의 입력·출력·종료 코드, 트랙끼리의 약속(계약 정본)
│   └── tracking/
│       ├── status.md              ← 점검 결과, 된 것, 막힌 것, 다음, 남은 범위, 줄일 순서, 자기 점검
│       ├── mission.md             ← 미션 원문, 다시 말하기, 질문, 심사 매핑, X1 대상, 동결 커밋 해시
│       ├── decisions/
│       │   ├── index.md           ← 결정 기록 표(한 줄씩 덧붙이기)와 트레이드오프 결정 목록
│       │   └── NNNN-<설명>.md      ← 트레이드오프 결정 하나씩
│       ├── findings.md            ← 지금 풀 수 없는 문제
│       └── tracks/<트랙>.md        ← 트랙별 최종 작업기록(하위가 정리, 트랙 병합 때 상위가 넣는다)
├── .claude/agents/                ← worker 서브에이전트 정의(구현자·검토자·debugger)
└── scripts/
    ├── orch.py                    ← 트랙 작업 공간(worktree·작업기록 폴더)과 지시·보고 파일을 다루는 도구
    └── AGENTS.md                  ← 키 래퍼·키 확인·비밀값 검사 도구의 범위와 지켜야 할 것
```

## 절대 규칙

1. **비밀값**: 키 원본은 폴더 루트 `.env`에만 있다. 에이전트는 `.env`를 열거나 출력하지 않고, provider(OpenShell에 등록한 자격 증명 묶음) 설정·게이트웨이 DB 내용을 읽지 않는다. 키가 닿는 명령은 팀장 승인 뒤 키 래퍼로만 돌린다. 키 값은 코드·문서·커밋·로그·trace(실행 추적 기록)·에이전트 지시에 넣지 않고, 샌드박스 안에는 자리표시 값만 둔다. 팀장, Hustler, 모든 에이전트에 똑같이 적용된다.
2. **계약**: 트랙끼리 함께 기대는 값은 `docs/contracts.md`에서 글자 그대로 가져온다. 바꾸려면 팀장 승인을 받는다.
3. **평가 고정**: 지표·사례·기대 결과는 구현 전(동결 1), 채점 스크립트는 측정 전(동결 2)에 커밋한다. 결과를 본 뒤 유리하게 고치지 않는다. 실패·시간 초과도 분모에 남긴다.
4. **정직한 주장**: 쓰지 않은 기능, 목업(시연용 모형 화면), 재생 실행(저장된 모델 응답 재생), 대체 경로를 실제인 것처럼 말하지 않는다. 숫자에는 x/N, Wilson 95% 구간, 자료 종류를 붙인다.
5. **main 반영**: 작업 브랜치 → 검사 → 독립 검토 → squash 병합(여러 커밋을 하나로 합치는 방식)으로만 넣는다. 스테이징은 `git add <파일>`로만 한다. 예외: `docs/tracking/status.md`와 `docs/tracking/decisions/index.md`만 바꿀 때는 비밀값 검사(종료 0) 뒤 main에 바로 커밋한다. 다른 파일이 섞이면 예외가 아니다.

사람이 정하는 것(미션 해석의 갈림, 범위 축소, 대체 경로 승인, 라이선스·고지 수락, 공개·제출·삭제·비용·외부 게시)과 Hustler가 정하는 수요 판단은 `docs/business-rules.md`의 결정권표를 따른다. 에이전트 세션은 자기를 띄운 사람과만 말한다.

## Hustler 쪽 세션이라면

Hustler 노트북에서 Hustler가 띄운 에이전트 세션은 이 절을 먼저 따른다. 현재 브랜치가 `hustler/`로 시작하면 Hustler 쪽 세션이다. 확실하지 않으면(예: clone 직후 `main`에 있을 때) 자기를 띄운 사람에게 먼저 묻는다. 아래 "일하기 전에 읽을 것"과 "멈추고 바로 팀장에게 알릴 것"은 팀장 쪽 세션 기준이다.

용어: clone(원격 저장소를 통째로 내려받은 작업 복사본), push(내 커밋을 원격에 올리기), `origin`(clone한 원격 저장소의 기본 이름. 여기서는 팀의 비공개 GitHub 저장소).

- **하는 일**: 목업(시연용 모형 화면), 발표 자료와 대본, 예시 데이터. Hustler 영역(아래 Hacker 경로 밖)에 디렉터리를 자유롭게 만든다.
- **하지 않는 일**
  - Hacker 경로를 더하거나 고치거나 지우는 일. Hacker 경로는 `app/`, `docs/`, `scripts/`, 루트 파일 4개(`CLAUDE.md`, `AGENTS.md`, `.gitignore`, `README.md`), 점(.)으로 시작하는 모든 경로다. 단 git이 추적하지 않는 로컬 폴더(`.claude/skills/` 등)는 예외다. 문서에 틀린 곳을 찾으면 고치지 말고 Hustler에게 알린다.
  - `artifacts/openshell/`, `spikes/x1/` 만들기(비밀값 검사가 일부 행을 건너뛰는 경로)
  - main에 커밋·push·병합하기, dryforge `ready` 실행, `scripts/orch.py` 실행
  - 미션 접수 절차, X1 통합 시험, colima·openshell·nemoclaw 명령 실행. 모두 팀장 쪽 일이다.
  - `.env` 만들기, 키를 받거나 다루기, 키가 닿는 명령(NIM 호출, OpenShell provider) 실행. Hustler 쪽 일에는 키가 필요 없다.
  - 미션 해석, 한 문장 주장, 계약, 평가를 정하는 일. 수요 판단(누가 왜 원하나)은 Hustler가 정하고, 나머지는 팀장이 정한다.
- **먼저 읽을 것**
  - `docs/business-rules.md`: 팀과 결정권, 한 문장 주장과 범위(목업 구분 원칙), 결과 표기의 "쓰지 않는 서술"
  - `docs/contracts.md`: "Hustler가 만들고 코드가 읽는 데이터" 칸. 코드가 읽을 데이터는 이 칸의 경로·형식·필드를 글자 그대로 지킨다. 칸이 비어 있으면 팀장에게 정해 달라고 한다. 계약은 당일 바뀌므로 작업 중에도 `git fetch origin && git show origin/main:docs/contracts.md`로 최신 판을 본다.
  - `docs/security.md`: 화면·녹화·발표에서 가릴 것
  - `docs/operations.md`: 당일 시간표(Hustler 칸)와 발표·녹화
- **처음 한 번**(Hustler 노트북에서). 필요한 것: git 2.31 이상 `[추론: 비밀값 검사가 쓰는 옵션]`, python3, 비공개 저장소에 접근할 GitHub 인증.
  ```
  git clone <비공개 저장소 주소> nvidia-hackathon-2026-final
  cd nvidia-hackathon-2026-final
  git switch -c hustler/<작업ID>-<설명> --no-track origin/main
  ```
- **넘길 때마다**
  ```
  git add <파일>                                    # 파일 이름을 하나씩. git add -A, git add . 금지
  git commit -m "hustler(<작업ID>): <요약>"
  git -c core.quotePath=false diff --no-renames --name-only origin/main...HEAD   # Hacker 경로가 하나도 없어야 한다
  python3 scripts/secret_scan.py origin/main..HEAD  # 종료 0이어야 한다
  git push -u origin hustler/<작업ID>-<설명>
  ```
  그 뒤 Hustler가 팀장에게 병합을 요청한다. 병합은 팀장 쪽 세션이 한다. push한 브랜치는 amend나 강제 push로 고쳐 쓰지 않는다.
- **병합된 뒤 다음 작업**: 같은 브랜치를 이어 쓰지 않는다. `git fetch origin && git switch -c hustler/<다음 작업ID>-<설명> --no-track origin/main`.
- **스킬**: `claude-design`(화면 프로토타입), `architecture-diagram`(구성도)은 git이 추적하지 않아 clone에 없다. 필요하면 팀장에게 `.claude/skills/<이름>/` 폴더를 받아 같은 자리에 둔다. 추적하지 않는 로컬 폴더라 Hacker 경로 규칙의 예외다.
- **멈추고 Hustler에게 알릴 것**(Hustler가 팀장에게 전한다): 키·토큰이 화면·파일·로그에 보일 때, Hacker 경로를 고쳐야 할 것 같을 때, 코드가 읽을 데이터 형식을 바꿔야 할 때, 미션 해석이 갈릴 때.

## 하위 오케스트레이터 세션이라면

현재 브랜치가 `track/`으로 시작하면(작업 폴더가 `app/.orch/<트랙>/wt`) 하위 오케스트레이터 세션이다. 이 절을 먼저 따른다. 위 "Hustler 쪽 세션이라면"과 아래 "일하기 전에 읽을 것"의 상위 전용 줄(`ready`, 트랙 나누기·병합)은 해당하지 않는다. 작업기록 폴더는 worktree 바로 옆 `../log/`다.

- **하는 일**: 상위가 보낸 지시(`instruction`)대로 자기 트랙의 작업을 worker 서브에이전트로 끝까지 한다. 구현은 `worker-implementer`, 검토는 `worker-reviewer`(작성 worker와 다른 새 에이전트), 시험·검증 실패나 worker의 BLOCKED는 `worker-debugger`에 맡긴다. worker의 자기 보고는 증거가 아니다. 검증 명령은 직접 다시 돌려 종료 코드를 본다. 커밋은 자기 브랜치 `track/<트랙>`에 `git add <파일>`로만 한다.
- **범위**: 지시문의 범위(`app/<트랙>/`)만 고친다. `app/` 바로 아래 공통 파일(공통 스키마·가짜 입력, `app/pyproject.toml`, `uv.lock`), `docs/`, `scripts/`, 루트 파일, 점(.)으로 시작하는 경로는 고치지 않는다. 필요하면 `request`로 상위에 요청한다. 문서 수정 제안은 최종 보고에 적는다(문서는 상위가 고친다).
- **하지 않는 일**: main 체크아웃·병합·push, 다른 트랙 폴더 수정, dryforge 실행, 키가 닿는 명령(필요하면 `request`. worktree가 main 폴더 안에 있어 상위의 `.env`에 경로로 닿지만, 열거나 가리키지 않는다), 평가 사례·기대 결과·홀드아웃 읽기, 계약·범위·평가를 스스로 바꾸기. 이 창에서 팀장이 직접 지시하면 따르되, 그 내용을 `report`로 상위에 알린다.
- **흐름**
  ```
  python3 scripts/orch.py inbox <트랙> --for sub          # 읽지 않은 지시(있으면 종료 0)
  python3 scripts/orch.py ack <트랙> <번호> --for sub      # 읽은 뒤
  python3 scripts/orch.py log <트랙> "<한 줄>"             # 작업 시작·끝, 명령과 종료 코드, 커밋 해시, worker 판정
  python3 scripts/orch.py send <트랙> --from sub --kind report|request|final --body-file - <<'EOF'
  <본문>
  EOF
  python3 scripts/orch.py wait <트랙> --for sub --timeout 1800   # 답을 기다릴 때. 백그라운드로 돌린다
  ```
  `report`는 작업 하나가 끝날 때마다, `request`는 막혔거나 범위 밖이 필요할 때, `final`은 트랙을 끝낼 때 한 번 보낸다. 기다릴 때 foreground `sleep`을 되풀이하지 않는다.
- **최종 보고(`final`)**: 작업기록(`../log/worklog.md`)을 정리해 쓴다. 한 일, 커밋 목록, 검증 명령과 종료 코드, `worker-reviewer` 판정, `worker-debugger`가 찾은 원인, 남은 일, 문서 수정 제안. 이 본문이 그대로 `docs/tracking/tracks/<트랙>.md`가 된다.
- **키·토큰이 화면·파일·로그에 보이면** 그 창의 팀장에게 바로 알리고 `request`로 상위에도 남긴다.
- **멈추고 상위에 `request`로 알릴 것**: 범위 밖 파일을 고쳐야 할 때, 계약 값이 맞지 않을 때, 같은 실패가 세 번 되풀이될 때, 평가 파일이 worker에게 드러났을 때.
- 보고와 작업기록에 키·토큰·로컬 절대 경로를 넣지 않는다.

## 일하기 전에 읽을 것

- 항상: `docs/standards.md`, `docs/engineering-notes.md`, `docs/tracking/status.md`. `scripts/`를 고치면 `scripts/AGENTS.md`.
- 미션이 공개되면: `docs/operations.md`의 미션 접수 절차와 당일 시간표, `docs/business-rules.md`의 결정권표·주장·평가 절.
- 키·provider·샌드박스를 건드리기 전: `docs/security.md`의 키 경로와 권한표, `docs/engineering-notes.md`의 OpenShell 절(colima(macOS에서 Docker를 돌리는 리눅스 가상 머신) 끄고 켜는 순서, `inference.local` 우회, 실행 파일 판정).
- NemoClaw 설치·온보딩 전: `docs/operations.md`의 NemoClaw 명령(고지 수락 플래그 → 팀장 승인), `docs/engineering-notes.md`의 NemoClaw 절(성공해도 종료 1, 중복 실행).
- 모델 호출 코드를 쓰기 전: `docs/operations.md`의 예선 모델 설정값(재전송·속도 조절·사례당 한도), `docs/standards.md`의 제품 코드 경계.
- 평가·채점·결과표 작업 전: `docs/business-rules.md`의 평가·결과 표기 절, `docs/standards.md`의 평가 고정 절.
- dryforge `ready`로 작업을 설계할 때(상위만): `docs/engineering-notes.md`의 "작업 설계 때 참고할 구현 방식", `docs/contracts.md`의 트랙끼리의 약속. 설계에 "대상 파일은 `app/` 아래", "평가 사례·기대 결과·홀드아웃 경로는 읽지도 작업 대상에 넣지도 않는다", "작업을 트랙(`app/<트랙>/`)별로 묶고 트랙끼리 같은 파일을 고치지 않는다", "공통 뼈대·스키마·가짜 입력·`app/pyproject.toml`·lock은 0단계 작업 하나로 묶는다"를 명시한다. `ready`는 동결 1 커밋 뒤에 부른다.
- 트랙을 나누기 전(상위): 미션 접수 결과와 기록 파일을 커밋하고 `git status --short`가 비었는지 본다. 0단계를 worker로 구현 → 검사 → 독립 검토 → squash → push한 뒤, 트랙마다 `python3 scripts/orch.py spawn <트랙> --scope app/<트랙>/` → 지시 `send` → `launch`. 순서와 지시문 양식은 `docs/operations.md`의 "트랙 나누기와 지휘".
- 트랙 브랜치를 병합하기 전(상위): 하위의 최종 보고(`final`)를 받고 `git -c core.quotePath=false diff --no-renames --name-only main...track/<트랙>`에 범위 밖 경로가 없는지, `python3 scripts/secret_scan.py main..track/<트랙>`이 종료 0인지 본 뒤 독립 검토 → squash. 최종 보고는 `docs/tracking/tracks/<트랙>.md`로 같은 병합에 넣는다.
- Hustler 브랜치를 병합하기 전: `git fetch origin` 뒤 `git -c core.quotePath=false diff --no-renames --name-only main...origin/<Hustler 브랜치>`에 Hacker 경로(`app/`, `docs/`, `scripts/`, 점으로 시작하는 경로, 루트 파일 4개)가 없는지 본다(`docs/standards.md`의 파일 소유).
- 발표·README를 확정하기 전: `docs/business-rules.md`의 "쓰지 않는 서술" 목록으로 한 번 검색한다.

## 멈추고 바로 팀장에게 알릴 것

- 키·토큰(NVIDIA 키, NGC 키, OpenClaw 게이트웨이 토큰)이 커밋·로그·trace·화면에 들어갔거나 그랬을 수 있을 때. 키 래퍼의 "키 조각" 경고도 여기에 든다.
- 평가 홀드아웃(개발에 쓰지 않는 평가 사례)이나 기대 결과가 개발 중인 에이전트에게 드러났을 때.
- 계약을 바꿔야 할 때. 승인 전에는 그 계약에 기대는 일만 멈춘다.
- X1 통합 시험이 타임박스 안에 통과하지 않을 때. 승인된 대체 경로가 있으면 그 경로로 가면서 알린다.
- 키 주입 방법이 모두 실패했을 때. 키를 샌드박스 안에 넣는 우회는 하지 않는다.
- 되돌릴 수 없는 일(공개, 삭제, 비용, 외부 게시, 라이선스 수락, 샌드박스·게이트웨이 삭제나 재시작) 앞에서.
- 미션 해석이 둘 이상으로 갈려 결과가 달라질 때.
- 동결 1·동결 2 커밋 뒤에 평가 파일이나 채점 스크립트를 고쳐야 할 때.

그 밖의 문제는 풀어 본다. 못 풀면 `docs/tracking/findings.md`에 적고(무엇이 깨지나, 영향, 지금 못 푸는 이유, 가능한 방법), 당일 진행을 막는 것은 `docs/tracking/status.md`의 "막힌 것"에도 적는다.

## 글쓰기

- 한국어로 쓰고, 용어가 처음 나올 때 괄호로 짧은 설명을 붙인다.
- 근거 표시: `[사실: 출처]` `[추론]` `[DESIGN]`(팀 규칙, 대회 공식 규칙 아님) `[미확인]`. 명령에는 `[예선 실행]` 또는 `[문서만]`을 붙인다.
- 문서·커밋·로그에 로컬 절대 경로, 키, 사람 이름(공개 저장소 주소의 계정 이름은 예외), 다른 팀 이름을 쓰지 않는다.
