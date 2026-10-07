# 상태(마지막 갱신 2026-10-07(수) 16:27)

## 아침 점검(2026-10-07 08:56~09:00, 에이전트 실행)

| 항목 | 결과 | 확인 방법 |
|---|---|---|
| colima(Docker) | 켰다. 실행 중 | `colima start` 종료 0, `colima status` |
| OpenShell | `0.0.116`. 게이트웨이 `nemoclaw`(`https://127.0.0.1:8080`) Connected, Authenticated(mTLS(서로 인증서를 확인하는 암호화 연결)) | `openshell --version`, `openshell status` |
| 샌드박스 | `x1-demo`, `ts-scored` 둘 다 여전히 **Error**(아래 "막힌 것") | `openshell sandbox list` |
| NIM 키 확인 | `HTTP 200 · 모델 nvidia/nemotron-3-super-120b-a12b`, 종료 0(팀장 승인 뒤 에이전트가 키 래퍼로 실행, 08:59) | `python3 scripts/with_nvidia_key.py --env-file .env -- python3 scripts/nim_ping.py` |
| 도구 | uv 0.11.28, git 2.50.1, python3 3.9.6, `npx skills` 1.7.1 | 각 `--version` |
| GitHub | `gh` 로그인됨(저장소 소유 계정). 저장소 협업자 2명, 대기 중인 초대 0건 → Hustler가 초대를 받아들인 것으로 본다 `[추론]` | `gh auth status`, `gh api repos/<저장소>/collaborators`, `…/invitations` |
| Codex | `codex-cli 0.160.0`, ChatGPT 계정으로 로그인됨. 독립 검토에 쓸 수 있다 | `codex --version`, `codex login status` |

## 점검 결과(전날 밤)

| 항목 | 결과 | 확인 방법 |
|---|---|---|
| 이 폴더의 git | `main` 브랜치, `.gitignore`(`.env` 등 제외). 원격 `origin` = 비공개 GitHub https://github.com/JoeHwangHee/nvidia-hackathon-2026-final(아래 "된 것") | `git remote -v` |
| 검사·키 도구 | 예선 사본 `scripts/secret_scan.py`(비밀값·로컬 경로 검사), `scripts/with_nvidia_key.py`(키 래퍼), 새로 만든 `scripts/nim_ping.py`(키 확인). 셋 다 실행해 확인 | 첫 커밋 전 실행 |
| colima(Docker) | 꺼져 있다. 아침에 `colima start`가 필요하다 | `colima status` |
| OpenShell 게이트웨이 | `openshell 0.0.116`. 게이트웨이 `nemoclaw`(`https://127.0.0.1:8080`)에 연결·인증됐다 | `openshell --version`, `openshell status`(colima를 켠 상태) |
| 샌드박스 | 둘 다 남아 있으나 **Error** 상태다(아래 "막힌 것") | `openshell sandbox list` |
| Brev | CLI는 설치돼 있지 않다. 웹 콘솔 로그인 확인(팀장, 22시 무렵) | https://brev.nvidia.com |
| NVIDIA API 키 | 폴더 루트 `.env`의 새로 발급한 키로 NIM 호출 `HTTP 200`(팀장 실행, 22시 무렵) | `python3 scripts/with_nvidia_key.py --env-file .env -- python3 scripts/nim_ping.py` |
| 스킬 | `claude-design`, `architecture-diagram`을 `.claude/skills/`에 복사. Claude Code 스킬 목록에 뜨는 것 확인 | 스킬 목록 |

### 샌드박스 목록

| 이름 | 쓰임 | 생성(목록 표시 그대로, UTC로 보임) | 상태(23:05) | provider |
|---|---|---|---|---|
| `x1-demo` | NemoClaw 시연 샌드박스 | 2026-09-24 08:20:31 | Error | `nvidia-prod`(새 키로 갱신) |
| `ts-scored` | 예선 TradeSentry 채점 대상 실행용 | 2026-09-25 18:54:59 | Error | `tradesentry-nvidia`(새 키로 갱신) |

## 된 것(2026-10-07 오후, 시각순)

| 시각 | 한 것 | 증거 |
|---|---|---|
| 13:1x~13:4x | 설계 승인, X1 통과, 0단계, 평가 스킬 동결 2, G1 정책·스크립트 | 결정 기록 13:xx 줄, 커밋 `cc6e182`·`7945071` |
| 14:1x~14:3x | 자료 변환(sweat 두 팩, 역명 유래 274), 본문 판정 표시 정리, 라우터 Claude → Nemotron(팀장 결정) | 결정 기록 14:xx 줄 |
| 14:5x~15:1x | 트랙 셋 병합(retrieval·tools·loop), B1 샌드박스 다시 만들기, 시연 문장 끝까지(라우터·계획 필수 단계·이름 정리 토큰 수정 뒤) | 커밋 `ff3473c`, `app/sandbox/violation_tests.md` |
| 15:2x | 평가 사례 12건 sha256 동결 | 결정 기록 15:2x 줄, 커밋 `05e965b` |
| 15:3x | 위반 시험 v2 B1 실측 모두 일치, 게시 차단 → 팀장 승인 → 통과(이슈 #2) → 회수, 감사 21/21 짝 | `app/sandbox/violation_tests.md` B1 절 |
| 15:5x | 이동 시간 자료(공식·공개 출처 15건), 지식 색인 커밋, 기능 동결 `c12e481`, 최종 이미지·샌드박스 | 결정 기록 15:5x 줄, 커밋 `c12e481`·`9308b74` |
| 16:0x | 공식 평가(동결 판, NVIDIA API 카탈로그 모델): 본 시스템 dev 8/8, holdout 3/4. 기준선 dev 3/5, holdout 1/3. 구간이 겹쳐 차이 주장 안 함(합성 사례) | README 9절 |
| 16:0x | 공통 시험 저장소 연습 요청: `COURSE_SAVED`, 게시 안 함, 입력 파일 근거 인용(D). 운영 공지·음식 제한은 못 반영(한계) | README 9절·11절 |
| 16:1x | 사용자 화면 목업(질문 → 오른쪽 답변, 기록 재생 표시), README 확인 사실·결과표 | 비공개 링크(팀장), 커밋 `0f29bb5` |
| 16:2x | 팀 vLLM(Brev) 연결 준비: provider 프로필, 정책 `vllm_chat`, 키 변수 허용 목록, User-Agent | 커밋 `aae2ba3`, 결정 기록 16:1x 줄 |
| 16:3x | 심사자 실행 가이드 병합(`docs/guide/RUN.md`), 트랙 `web`·`checkguide` 최종 보고 받음(범위·비밀값 검사 통과) | 커밋 `8ed2bd9`, 트랙 작업기록 |
| 16:4x | 팀 vLLM 401 해결(팀장이 provider 키를 바로잡음). 샌드박스 안에서 vLLM으로 가벼운 질문 1회 답(`ANSWERED_LIGHT`, run_id `20261007T074558Z-3db8`), OpenShell 로그에 `policy:vllm_chat` ALLOWED(OPA·L7) | OpenShell 로그 |

## 하는 중

- `web` 병합 준비: 시험 903 통과(web 50 포함). 실제 샌드박스 왕복과 사용 화면 사진을 따로 돌리는 중이다(vLLM으로 시연 문장 전체 흐름을 함께 잰다).
- `checkguide` 병합 준비: vLLM 연결 이전 main을 보고 쓴 부분(5절, 정책 끝점, 줄 번호)과 `RUN.md`의 vLLM 설명을 지금 main으로 고치는 중이다.
- 공개판 로컬 준비: 언론 인용 문서 90건(`source_type: media`)과 「내 손안에 서울」 도보 시간 5건을 빼고 색인을 다시 만드는 스크립트. 저장소 생성·push는 팀장 승인 뒤.

## 막힌 것

- 제출 마감 시각을 아직 모른다(미션 기록 질문 4). 공개 저장소가 제출 자격이다.
- 오래된 샌드박스 `ts-scored`(Error)는 오늘 작업과 무관하다. 지우지 않았다.

## 다음

1. [상위] `web`·`checkguide` 병합, README에서 실시간 화면·확인 가이드를 잇는다.
2. [상위] secrets 장면을 앱으로 1회 실행해 run_id·거부 기록을 남긴다.
3. [상위] 17:30 전 최종 커밋: 상태·README 마무리("쓰지 않는 서술" 검색), 증거 경로 정리.
4. [팀장] 공개 저장소 이름과 생성·push 승인 → 상위가 준비한 묶음을 올린다. 그 뒤 Slack 제출(팀장).

## 줄일 순서 / 지킬 것

- 지킨 것: 시연 문장 흐름, 게시 차단 → 승인 → 통과, secrets 장면, 위반 시험표.
- 줄인 것: 없음(기준선과 일반 코스 요청은 돌렸다. 일반 코스 요청의 운영 공지·음식 제한 반영은 한계로 적었다).

## 심사 기준 자기 점검(기준 | 근거 한 줄 | 증거 경로)

| 기준 | 근거 한 줄 | 증거 |
|---|---|---|
| 실행 경계·Runtime policy | 기본 거부, 앱 Python만, 호스트·메서드·경로(L7), 파일(Landlock). 위반 시험 B1 실측 모두 예측과 일치 | `app/sandbox/policy*.yaml`, `app/sandbox/violation_tests.md` |
| 사후 감사 | 실행마다 해시 사슬 trace, 게시 시도와 OpenShell 로그 21/21 짝, 정책 판 이력 | `app/sandbox/audit.sh`, 감사 묶음 `outputs/audit/<run_id>/` |
| 의사결정 확인 | trace의 route·plan·plan_check·step·final 줄에 이유·모델·결과 | `/hackathon/output/<run_id>/trace.jsonl` |
| Agent-Native Infrastructure | 맥 + colima + OpenShell 게이트웨이, 접속 명령 README 3절 | README 3절 |
| Deployment Flexibility | NIM 경로 → (Claude 열었다 닫음) → GitHub는 승인 때만 → 팀 vLLM 블록 추가. 하나씩 연 기록 | 결정 기록, 정책 머리 주석 |
| Deterministic Governance | 한도·등급·예산 자르기·계획 검사·필수 단계·라우터 실패 시 응답 불가를 코드가 정함 | `app/common/limits.py`, `app/tools/`, `app/loop/` |
