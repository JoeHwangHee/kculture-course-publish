# 구성: 이 폴더, NVIDIA 스택, 실행 사슬

근거 표시: `[사실: 출처]` · `[추론]` · `[DESIGN]`(팀 규칙) · `[미확인]` · `[예선 실행]`(예선에서 돌려 결과가 기록됨) · `[문서만]`(실행 기록 없음). 출처 경로는 예선 저장소 루트 기준이다.

## 1. 지금 있는 구성요소

제품 코드는 미션 공개 뒤에 `app/` 아래에 생긴다. Hustler의 목업·발표 자료·예시 데이터는 Hacker 경로(`app/`, `docs/`, `scripts/`, 루트 파일 4개, 점으로 시작하는 경로) 밖의 디렉터리에 생기고, 코드는 그중 계약 문서에 적은 데이터 파일만 읽는다. 지금 있는 것은 키·검사 도구와 호스트 쪽 NVIDIA 기반이다. colima는 macOS에서 Docker를 돌리는 가벼운 리눅스 가상 머신이다.

```
호스트(macOS Apple Silicon)
├── 폴더 루트 .env ──(NVIDIA_API_KEY 한 줄)──▶ scripts/with_nvidia_key.py ──(자식 환경에만)──▶ 자식 명령
│                                                                                          └─ scripts/nim_ping.py ──HTTPS──▶ NIM
├── scripts/secret_scan.py ──(git ls-files / git log -p)──▶ 이 저장소의 추적 파일·커밋
├── scripts/orch.py ──▶ app/.orch/<트랙>/{wt(worktree, track/<트랙>), log(지시·보고·flag·작업기록)} ◀── 상위·하위 오케스트레이터 세션
└── colima(Docker)
    └── OpenShell 게이트웨이 nemoclaw(https://127.0.0.1:8080, OpenShell 0.0.116)
        ├── 샌드박스 x1-demo(NemoClaw 시연용) ── provider nvidia-prod
        └── 샌드박스 ts-scored(예선 TradeSentry 채점 대상 실행용) ── provider tradesentry-nvidia
외부: NIM(integrate.api.nvidia.com), Brev(brev.nvidia.com, 웹 콘솔), 비공개 GitHub 저장소(origin, https://github.com/JoeHwangHee/nvidia-hackathon-2026-final. 팀장 노트북 ↔ Hustler 노트북이 브랜치를 주고받는 곳)
```

| 구성요소 | 역할 | 의존 방향 |
|---|---|---|
| `scripts/with_nvidia_key.py` | `.env`의 키를 자식 프로세스 환경에만 넘기고 출력에서 키를 가린다 | `.env` → 래퍼 → 자식. 다른 스크립트에 기대지 않는다 |
| `scripts/nim_ping.py` | 키와 모델 접근을 HTTP 상태 하나로 확인한다 | 래퍼가 넘긴 환경변수 → NIM |
| `scripts/secret_scan.py` | 커밋 전 비밀값·로컬 경로 검사 | git → 검사. 다른 스크립트에 기대지 않는다 |
| `scripts/orch.py` | 트랙 worktree와 작업기록 폴더를 만들고, 상위·하위 오케스트레이터가 지시·보고 파일과 flag를 주고받게 한다 | git(worktree) → 작업기록 폴더. 다른 스크립트에 기대지 않는다. 키를 다루지 않는다 |
| `.claude/agents/worker-*.md` | worker 서브에이전트 정의(구현자·검토자·debugger). 상위와 하위 오케스트레이터가 부른다 | 추적 파일이라 트랙 worktree에도 있다 |
| OpenShell 게이트웨이 | 샌드박스 밖에서 정책·자격 증명·추론 경로를 관리하는 서버. Linux 전용이라 macOS에서는 Docker 안에서 돈다 | colima가 켜져 있어야 연결된다 |
| 샌드박스 2개 | 예선에서 만든 격리 실행 환경. 지금 상태(Ready/Error)는 상태 기록에서 본다. 두 provider는 본선용 새 키로 갱신됐다. 새로 만드는 샌드박스에 `--provider tradesentry-nvidia`를 붙이면 새 키를 쓸 것으로 본다 `[미확인]` | 게이트웨이 → 샌드박스. 샌드박스 → NIM은 정책이 허용한 경로만 |

## 2. 제품의 실행 사슬(미션 접수 때 구체화한다)

```
요청 → 하네스(에이전트 실행 틀) → 스킬 → 샌드박스 안 실행 → 모델(NIM) → 검증 → 결과 → 사람의 결정
```

- 경계는 넷이다: 호스트, 컨테이너(샌드박스), 네트워크, 키 경로. 경계마다 "처음 통과시켜 볼 것"을 접수 때 표시한다.
- 그중 문서만으로는 동작을 확정할 수 없는 연결 3개가 X1 통합 시험(가장 위험한 연결을 첫 시간에 끝까지 한 번 통과시키는 시험)의 대상이다. 구성요소를 따로따로 확인하면 경계에서 나는 실패를 늦게 발견한다 `[사실: DEV_PLAN 13절 결정 17]`.
- **키가 경계를 넘는 방식**: 호스트 `.env` → 키 래퍼 → provider 등록(게이트웨이 안) → 샌드박스 안에는 자리표시 값만 → 샌드박스 프로세스가 자리표시 값을 헤더에 실음 → 감독 프로세스의 프록시가 요청 시점에 실제 키로 바꿈 → NIM.
- **외부 전송은 한 경로**: 샌드박스에서 나가는 것은 정책이 허용한 실행 파일의 NIM `POST /v1/chat/completions`뿐이다. 그 밖의 목적지·실행 파일은 거부된다.
- 예선 대표 흐름: NemoClaw 요청 → 스킬 → 샌드박스 안 CLI → NIM 200 → NAT 추적 → 차단 로그 1건. 첫날 재시도 끝에 조건부로 통과시켰다(node 실행 파일을 허용하되 경로를 `POST /v1/chat/completions` 하나로 좁힘). 15:19 시작, 18:00 통과로 벽시계 약 2.7시간이고 사용자 대기가 포함돼 있다 `[사실: 예선 docs/tracking/journal.md 408·436행]`.

## 3. NVIDIA 스택

| 구성요소 | 무엇 | 예선에서 쓴 방식 | 심사에 보일 증거 |
|---|---|---|---|
| NIM / Nemotron | OpenAI 호환 추론 API와 Nemotron 모델. base URL `https://integrate.api.nvidia.com/v1`, 인증 `Authorization: Bearer <키>` | 조사자·검수자 추론, native tool call(모델이 도구 호출을 구조화된 형식으로 요청하는 기능). 모델 `nvidia/nemotron-3-super-120b-a12b` `[예선 실행]` | 실행별 모델 요청 수·토큰, trace |
| OpenShell | 커널 수준 격리 샌드박스 런타임. YAML 정책으로 파일·네트워크·프로세스를 통제하고 허용·거부를 감사 로그로 남긴다 | 채점 대상 실행 격리. 외부 전송 NIM 한 경로, 샌드박스 안 키 없음 | 위반 시험표(예측·실측 대조), 감사 로그 발췌, 라이브 정책 사본 |
| NemoClaw / OpenClaw | OpenClaw(에이전트 실행 틀), OpenShell, 정책을 묶은 참조 스택. 알파 단계 | 시연 경로: 요청 → 스킬 → 샌드박스 안 CLI | 시연 기록, 스킬 호출 성공률(x/N) |
| NAT | NVIDIA NeMo Agent Toolkit. 에이전트 실행을 추적·프로파일·평가한다 | 사례 흐름 1건을 NAT 함수로 감싸 추적·프로파일. NIM 호출은 자체 클라이언트가 하고 NAT에는 이벤트만 남김 | `nat_trace.jsonl`, 프로파일 파일 |
| Agent Skills | `SKILL.md` 형식(머리말 `name`·`description` + 절차 본문)의 에이전트용 작업 절차와 NVIDIA 공식 스킬 | 런타임 스킬 1개, 평가 스킬 2개, 거버넌스 카드(스킬의 능력 범위를 밝히는 카드) | `SKILL.md`, 쓴 공식 스킬 목록, 카드 |
| Brev / L40S | GPU 인스턴스 플랫폼(드라이버·CUDA·Docker 세팅됨)과 48GB GPU. Launchable(하드웨어·소프트웨어·코드를 한 번에 띄우는 링크), NemoClaw·OpenShell 런처블이 있다 | 쓰지 않았다 `[문서만]` | — |

- NemoClaw는 모델·하네스·도구·런타임을 포함한 배포 패키지이고, OpenShell은 그 안에서 에이전트의 파일·네트워크·자격 증명·도구 접근을 강제하는 보안 런타임이다 `[문서만: 대회 조사 문서 8-2절]`.
- L40S(48GB)에서는 Ultra 550B를 셀프호스팅할 수 없다. Nano·Super가 후보다. 셀프호스팅 NIM에는 NGC API 키가 필요하다. 실패하면 호스팅 NIM API로 대체한다 `[문서만]`.
- 써 보지 않은 Nemotron 3 계열: Nano 30B A3B, Ultra 550B A55B, 3.5 Lightning `[문서만]`.

**미션에 따라 고려할 보조 구성요소**(예선에서 쓴 적 없음. 고르면 X1 대상에 넣는다) `[문서만: 대회 조사 문서 8-4·8-8절]`

| 미션 성격 | 구성요소 | 무엇 |
|---|---|---|
| 안전·정책 준수 | NeMo Guardrails | 프로그래머블 가드레일(입력·출력·검색·대화 규칙) |
| 안전·정책 준수 | NemoGuard NIM | 콘텐츠 안전, 주제 통제, 탈옥 탐지 |
| 문서 검색·RAG(검색 증강 생성) | NeMo Retriever NIM | 임베딩, 리랭킹, OCR |
| 음성 | Riva / Speech NIM | 음성 인식, 음성 합성, 번역 |
| 경로·일정 최적화 | cuOpt | GPU 가속 최적화 |
| 빠른 시작 | AI Blueprints | 바로 가져다 쓸 수 있는 참조 구현 |

## 4. 제품 설계 원칙(예선 결과를 만든 것)

1. **결정적 계산은 코드, 모델은 조사·선택·설명.** 탐지가 결정적이어야 재현과 채점이 된다.
2. **숫자는 검증된 값으로 틀을 채우고 검증기가 막는다.** 계기: NIM 도구 호출 시험에서 모델이 점유율 감소를 증가로 쓴 응답이 통과했다 `[사실: journal 1190행]`.
3. **기준선은 처리 방식만 다르게** 두고 처음부터 같이 돌린다.
4. **한도는 코드로 강제한다.** 모델이 "추가 조회 없이 보류" 지시를 어겼고, OpenShell 정책으로는 호출 횟수를 걸 수 없었다.
5. **지침 튜닝보다 코드 경계.** temperature, 역할 분담, 답변 매뉴얼 실험 3종은 효과가 없거나 지표의 뜻을 바꿔 기각했다 `[사실: journal 692~697행]`.
6. **점수용 실행과 시연 경로를 나눈다.** 하네스가 한 겹 더 끼면 비교가 흐려진다. 예선은 NemoClaw를 시연으로 따로 증명하고 "정확도 지표에 영향 없음"이라고 밝혔다.

**예선 약점에서 나온 본선 설계 방향** `[추론]`
- 모델: 예선은 Nemotron 1개를 두 역할로만 불렀다. 역할마다 다른 Nemotron 모델을 설정 파일로 지정한다.
- 도구 호출: native tool call만 썼다. 도구를 MCP(모델 컨텍스트 프로토콜, 도구를 표준 방식으로 노출하는 규약)로 노출하는 설계를 검토한다. NAT가 MCP 클라이언트·서버를 지원한다 `[문서만]`.
- NemoClaw: 시연 경로만 있었다. 라우팅이 필요한 이유가 생기는 설계라면 하네스 교체나 모델 라우팅을 쓴다.
- 에이전트여야 하는 이유: 규칙 기반 기준선이 못 푸는 과제(정성 판단, 비정형 입력)를 고른다.
- 삭제 시험: NVIDIA 구성요소가 지표에 직접 닿게 설계한다. 예선은 NemoClaw·Agent Skills·NAT를 빼도 정확도가 같았다.
- 화면: 모델 원초안 → 검수 뒤 → 검증 뒤를 나란히 보이는 화면 1개를 둔다.
