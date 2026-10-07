# K-콘텐츠 배경지 코스 에이전트

> **상태: 기능 동결**(2026-10-07 16:00, main `c12e481`). 날짜와 증거를 단 항목은 그날 실제로 돌려 확인한 것이다(샌드박스 안 실행, 호스트의 색인·감사 스크립트).
> - "(예정)"이 붙은 항목은 아직 동작을 확인하지 않은 것이다.
> - 확인한 항목에는 증거 파일을 단다.
> - 동결 뒤에 더한 것: 실시간 사용자 화면(`app/web/`, 에이전트 코드는 바꾸지 않음)과 팀 vLLM 연결(모델 주소·키 변수 설정, 정책 블록). 9절 평가 수치는 동결 판으로 잰 값이다.
> - 본문의 커밋 해시는 비공개 개발 저장소의 것이다.

K-콘텐츠를 보고 온 방문객이 목표를 말하면, 에이전트가 배경지를 잇는 코스를 짜고 각 장소 이름의 유래를 근거 등급과 함께 알려 준다. 에이전트의 모든 실행은 NVIDIA OpenShell 샌드박스 안에서 정책으로 통제되고, 감사 기록으로 남는다.

**심사자 가이드**: 직접 실행해 보기 [`docs/guide/RUN.md`](docs/guide/RUN.md) · 심사 기준별 확인 [`docs/guide/CHECK.md`](docs/guide/CHECK.md)

## 1. 소개

**시연 문장**: "케데헌 보고 왔어요. 오후 3시간, 혜화에서 시작할게요"

에이전트가 움직이는 순서(2026-10-07 샌드박스에서 확인)
1. 무게 판단: Nemotron이 요청이 자료 조회가 필요한 무거운 요청인지만 가른다(답하지 않음, 두 번 실패하면 응답 불가)
2. 계획: Nemotron이 도구 단계를 짜고, 코드가 검사한다. 코스 계획의 빠진 필수 단계는 코드가 채운다
3. 테마 팩에서 장소 선택(구간 이동 시간은 근거 자료로 조사, 근거가 없으면 "추정" 표시, 시간 예산은 코드가 자름)
4. 역명과 유래 조회, 작품 속 이름·옛 이름·현재 이름 정리
5. 근거 등급 부여(출처 종류로 코드가 계산)
6. 코스 파일 저장(`course.json`, `course.md`)
7. 게시 요청: OpenShell이 막고, 사람이 승인 정책을 적용하면 통과

시연 문장 실행 결과(run `20261007T063127Z-c5de`): 코스 2곳(낙산공원 → N서울타워) 155분, 4곳은 시간 예산 초과로 제외. 이름 유래는 낙타산·타락산·목멱산 등 등급 A 근거와 함께 나왔다. 게시는 OpenShell이 막았고, 첫 승인 대기(180초) 안에 승인이 없어 실행은 `PUBLISH_PENDING_APPROVAL`로 끝났다. 팀장이 승인 정책을 적용한 뒤 `python -m loop publish --run <run_id>`(나중 게시)로 같은 실행을 게시해 21번째 시도가 201이 되었고(차단 20회, GitHub 이슈 #2), 바로 회수했다. 감사 결과 게시 시도 21번이 OpenShell 로그와 모두 짝이 맞았다(증거: `app/sandbox/violation_tests.md` B1 실측의 C2·회수·감사 행). 이 시연 실행은 9절 점수의 근거와 별개다.

**하지 않는 일**
- 실제 예약·결제·발송. 게시는 승인 뒤 GitHub 이슈 하나뿐이다.
- 웹 검색. 근거는 미리 만든 지식 색인과 `/hackathon/input`뿐이다.
- 파인튜닝. "학습"은 인덱싱이다(4절).

## 2. 구조

```
요청 ─▶ [OpenShell 샌드박스 kculture]
         Nemotron(라우터): 요청의 "무게"만 판단(답하지 않음). 판단 실패 → "응답 불가"
           ├─ 가벼움 → Nemotron이 바로 답("자료 근거 없음(일반 안내)" 표시)
           └─ 무거움 → Nemotron이 계획 → 코드가 도구 실행
                        (지식 색인 검색 · 장소 선택 · 이름 정리 · 등급 계산 · 코스 저장 · 게시 요청)
         ─▶ /hackathon/output/<run_id>/ (코스·의사결정 기록)
         ─▶ 게시 요청 ─✕ OpenShell 차단 ─▶ 사람이 승인 정책 적용 ─▶ 통과
```

**NVIDIA 구성요소**

| 구성요소 | 쓰임 | 빼면 사라지는 것 |
|---|---|---|
| OpenShell | 파일·네트워크·실행 파일 정책 강제, 자격 증명 주입, 감사 로그, 정책 이력 | `/hackathon/secrets`·`restricted` 차단이 모델의 거절에만 기대게 된다. 키를 샌드박스 안에 넣어야 하고, 게시를 사람이 정책으로 승인·회수하는 단계와 허용·거부 감사 로그가 없어진다 |
| Nemotron(NIM) | 요청의 무게 판단, 계획, 이름 유래 요약, 구간 이동 시간 조사, 가벼운 질문의 답 | 요청을 읽고 도구 순서를 짜는 주체가 없어 고정 순서의 검색만 남는다. 작품 속 이름·옛 이름·현재 이름 정리와 가벼운 질문의 답이 없어진다 |
| Brev(GPU 클라우드) | 팀 GPU에 Nemotron을 vLLM(고속 추론 서버)으로 띄움. 설정 세 값으로 NIM 대신 고른다(3절) | 기본 경로(NVIDIA API 카탈로그)로만 돈다. 없어지는 기능은 없다 |

## 3. 설치와 실행(환경 설정)

**필요한 것**
- macOS + colima(Docker)
- OpenShell 0.0.116 게이트웨이
- uv와 Python 3.12
- 임베딩 모델 bge-m3 폴더
- 키 둘
  - NVIDIA API 키(build.nvidia.com)
  - 게시 저장소 하나의 이슈 쓰기 권한만 있는 GitHub fine-grained 토큰

**자격 증명 등록**: 키는 저장소·샌드박스에 넣지 않는다. OpenShell provider로 등록하고, 샌드박스 안에는 자리표시 값만 있다.
```
read -rs "GITHUB_TOKEN?GitHub 토큰: " && export GITHUB_TOKEN && echo
openshell provider create --name kculture-github --type github --credential GITHUB_TOKEN
unset GITHUB_TOKEN
```

**선택: 팀의 vLLM으로 모델 바꾸기**(Brev GPU의 vLLM, OpenAI 호환)
```
openshell provider profile import -f app/sandbox/providers/kculture-vllm-chat.yaml
VLLM_API_KEY="$(ssh <GPU 호스트> cat <키 파일 경로> | tr -d '\r\n')" \
  openshell provider create --name kculture-vllm --type kculture-vllm-chat --credential VLLM_API_KEY
# 샌드박스를 만들 때 --provider kculture-vllm 을 더한다(정책 두 파일에는 vllm_chat 블록이 이미 있다)
NIM_BASE_URL=https://nemotron-ye5klfyey.gobrev.dev/v1 NIM_MODEL=nemotron NIM_API_KEY_ENV=VLLM_API_KEY \
  sh app/sandbox/demo.sh course
```
- 키 값에 줄바꿈(CR/LF)이 섞이면 OpenShell이 넣기를 거부한다(`credential_unavailable`). `tr -d '\r\n'`으로 지운다.
- `NIM_API_KEY_ENV`는 `NVIDIA_API_KEY`나 `VLLM_API_KEY`만 받는다. 다른 provider의 자리표시 값이 모델 요청에 실리지 않게 하려는 것이다.

**이미지와 샌드박스**(2026-10-07 14:51 B1에서 빌드·생성 확인)
```
sh app/sandbox/build_kb.sh <bge-m3 모델 폴더>                       # 지식 색인 app/index/kb/ (호스트)
sh app/sandbox/stage.sh <없는 폴더> <bge-m3 모델 폴더> <입력 폴더>   # 빌드 재료를 저장소 밖 폴더에 모음
docker build -t kculture-sandbox:<태그> <그 폴더>
openshell sandbox create --name kculture --from kculture-sandbox:<태그> --policy app/sandbox/policy.yaml \
  --provider tradesentry-nvidia --provider kculture-github --no-auto-providers --detach
```
- `<입력 폴더>`는 샌드박스의 `/hackathon/input`이 된다. `restricted/`·`secrets/`에는 가짜 파일만 넣는다(stage.sh).
- 이미지 안에 `openshell` 실행 파일이 있으면 빌드가 실패한다. 에이전트가 통제층에 닿을 도구가 없게 하려는 것이다.
- `openshell sandbox exec`로 명령을 넣을 때는 표준 입력을 닫는다(`< /dev/null`). 열어 두면 명령이 끝나도 돌아오지 않는다.

**로컬 환경 접속 방법**(Agent-Native Infrastructure)
- `openshell status`: 게이트웨이 연결·인증
- `openshell sandbox list`: 샌드박스 상태
- `openshell sandbox connect kculture`: 샌드박스 셸
- `openshell logs kculture`: 감사 로그(ALLOWED/DENIED)
- `openshell term`: 터미널 화면 도구
- `openshell policy get kculture --full`·`openshell policy list kculture`: 지금 정책과 판 이력

## 4. 학습(= 인덱싱)

- 모델 가중치는 바꾸지 않는다(파인튜닝 없음). 자료를 Kiwi(한국어 형태소 분석기) BM25 + bge-m3 밀집 임베딩으로 색인하고, 질문 때 두 결과를 RRF(순위 기반 결합)로 합친다.
- 색인은 프로젝트 안 JSON(`app/index/kb/`)으로 저장·관리한다. 호스트에서 미리 만들어 샌드박스에 읽기 전용으로 넣는다.
- 만드는 명령: `sh app/sandbox/build_kb.sh <bge-m3 모델 폴더>`(호스트, 약 30초).
- 평가·시연에 쓴 색인(전체 자료 판)은 문서 518, 청크 553, `source_fingerprint` `2caf792e…`(원자료의 경로·크기·sha256으로 만든 지문)다. 9절 수치와 1절 시연 결과는 이 판으로 잰 값이다.
- 제출용 공개 저장소에는 이용 조건을 확인하지 못한 자료를 넣지 않았다: 언론 기사를 인용한 문서 90건(`source_type: media`), 서울시 「내 손안에 서울」 글에서 옮긴 문서 24건과 도보 시간 자료 5건. 공개 저장소의 색인은 남은 자료로 다시 만든 것이다(문서 399, 청크 430, `source_fingerprint` `99bce8c6…`). 그래서 공개 저장소에서 돌린 결과는 위 수치와 다를 수 있다.
- 자료와 출처
  - 케데헌 테마 팩과 자료 83건(`data/sweat/`): 수요 검증 담당이 조사한 실제 출처 자료. 시험용으로 만든 자료 2건은 `provenance: synthetic`으로 표시
  - 궁궐 테마 팩과 자료 146건(`data/sweat/`): 같은 조사 묶음에서 옮김
  - 서울교통공사 역명 유래 274건(`app/data/bulk/station_origin/`, 서울 열린데이터광장 OA-12036, 공공누리 제1유형)
  - 구간 이동 시간 15건(`app/data/bulk/travel/`): 서울교통공사 역간거리 및 소요시간(OA-12034)의 표준 운행시간 합, 서울시 「내 손안에 서울」의 역~장소 도보 시간
  - 색인에 넣기 전에 조사자의 판정 표시(등급 메모, 함정 표시)는 본문에서 지웠다. 원문 인용은 그대로다
- 공개 전에 자료별 라이선스를 확인한다.

## 5. 데모 실행 안내(2026-10-07 확인)

| 장면 | 명령 | 보이는 것 |
|---|---|---|
| 시연 문장 | `sh app/sandbox/demo.sh course` | 코스 파일, 근거 등급, 게시 요청 차단 |
| 승인 | `sh app/sandbox/demo.sh approve` | 정책 판이 올라가고 게시가 통과, GitHub 이슈 |
| 회수 | `sh app/sandbox/demo.sh revoke` | 기본 정책으로 돌아감 |
| secrets 요청 | `sh app/sandbox/demo.sh secrets` | 파일 거부(EACCES, 의사결정 기록)와 외부 전송 거부(OpenShell 로그 DENIED) |
| 감사 묶음 | `sh app/sandbox/demo.sh audit <run_id>` | 게시 시도와 OpenShell 로그의 짝 |
| 실시간 화면 | `python3 app/web/server.py` 뒤 브라우저로 `http://127.0.0.1:8787` | 질문 하나를 넣으면 오른쪽 영역에 샌드박스 `kculture` 안 에이전트의 답(코스, 유래 근거 등급, 운영 정보, 게시 상태)이 열린다 |

- 승인과 회수는 사람이 자기 터미널에서 한다. 에이전트는 샌드박스 안에서 정책을 바꿀 수 없다.
- 승인 대기(최대 180초) 안에 승인되지 않으면 실행은 `PUBLISH_PENDING_APPROVAL`로 끝난다. 승인 뒤 같은 실행을 `python -m loop publish --run <run_id>`(샌드박스 안)로 게시할 수 있다.
- 호스트에서 `openshell sandbox exec`를 부를 때는 표준 입력을 닫는다(`< /dev/null`).
- 실시간 화면(`app/web/`): 호스트의 로컬 서버(표준 라이브러리만, 127.0.0.1에만 열림)가 질문마다 `openshell sandbox exec`로 샌드박스 안 `python -m loop ask`를 돌리고, 끝나면 그 실행의 결과 파일(`run.json`·`course.json`·`answer.json`·`publish.json`)을 읽어 그린다. 한 번에 한 질문만 돈다. 샌드박스로 넘기는 환경변수는 `PUBLISH_REPO`·`NIM_BASE_URL`·`NIM_MODEL`·`NIM_API_KEY_ENV`·`KCULTURE_APPROVAL_WAIT_S` 다섯 이름뿐이고, 키 값은 넘기지 않는다.

## 6. OpenShell 정책 파일 경로

- `app/sandbox/policy.yaml`: 기본 정책
- `app/sandbox/policy-publish-approved.yaml`: 게시 승인 정책. 기본 정책에 GitHub 이슈 POST 한 경로만 더한 것

## 7. 권한 설계와 근거

허용 목록 방식이다. 기본은 거부하고, 필요한 것을 하나씩 열었다.

| 대상 | 권한 | 근거 |
|---|---|---|
| `/hackathon/input` | 읽기 전용 | 주어진 자료를 오염시키지 않는다 |
| `/hackathon/output` | 쓰기 | 결과물이 나가는 유일한 경로 |
| `/hackathon/restricted`, `/hackathon/secrets` | 거부(Landlock) | 요청을 받아도 모델이 아니라 인프라가 막는다 |
| 앱 코드 `/opt/kculture`, 지식 색인, 모델 가중치 `/opt/models` | 읽기 전용 | 에이전트가 자기 코드·근거·모델을 바꾸지 못한다 |
| `/tmp` | 쓰기 | 라이브러리 임시 파일 |
| 네트워크 `integrate.api.nvidia.com:443` | `POST /v1/chat/completions`만, 앱 Python만 | Nemotron 호출(무게 판단 포함). 기본 모델 경로 |
| 네트워크 `nemotron-ye5klfyey.gobrev.dev:443` | `POST /v1/chat/completions`만, 앱 Python만 | 팀 vLLM(Brev)으로 모델을 바꿀 때. 모델로 나가는 길은 이 둘뿐이다 |
| 네트워크 `api.github.com:443` | 승인 정책에서만 `POST /repos/JoeHwangHee/kculture-course-publish/issues`, 앱 Python만 | 사람이 승인한 게시 |
| 그 밖의 호스트·경로·실행 파일(curl 등) | 거부 | 최소 권한 |
| 자격 증명 | 샌드박스 밖(OpenShell provider). 안에는 자리표시 값 | 에이전트가 키를 볼 수 없다 |
| 통제층(정책·게이트웨이) | 샌드박스에서 닿지 않음 | 에이전트가 스스로 승인할 수 없다 |

검증 기록
- 위반 시험표: `app/sandbox/violation_tests.md`
- 자격 증명 주입과 게시 승인 경로 확인(X1): `app/sandbox/x1_evidence.md`

## 8. 사용하는 외부 API·서비스와 허용 범위

| 서비스 | 쓰임 | 허용 범위 | 자격 증명 |
|---|---|---|---|
| NVIDIA NIM(build.nvidia.com), `nvidia/nemotron-3-super-120b-a12b` | 무게 판단, 계획, 요약, 이동 시간 조사, 가벼운 답 | `POST /v1/chat/completions` | provider `tradesentry-nvidia` |
| 팀의 vLLM(Brev GPU, Cloudflare 터널) `nemotron-ye5klfyey.gobrev.dev`, 모델 `nemotron` | 같은 쓰임(NIM 대신 고를 때). 2026-10-07 확인: 시연 문장 1회(run `20261007T075459Z-27fb`, 70초, 코스 2곳·게시 승인 대기), 가벼운 질문 1회(run `20261007T074558Z-3db8`) | `POST /v1/chat/completions` | provider `kculture-vllm`(프로필 `app/sandbox/providers/kculture-vllm-chat.yaml`, 변수 `VLLM_API_KEY`) |
| GitHub REST API | 승인된 코스 게시(전용 저장소 `JoeHwangHee/kculture-course-publish`의 이슈. 이 제출용 공개 저장소와 같은 저장소이고, 시연 게시가 이슈 #2다) | 승인 정책에서만 `POST /repos/JoeHwangHee/kculture-course-publish/issues` | provider `kculture-github`(그 저장소 이슈 쓰기만) |
| 서울 열린데이터광장 OA-12036 | 역명 유래 자료 | 호스트에서 색인할 때 한 번 받음. 샌드박스 실행 중에는 부르지 않는다 | 없음 |
| 서울 열린데이터광장 OA-12034, 서울시 「내 손안에 서울」 | 구간 이동 시간 자료(역간 표준 운행시간, 역~장소 도보 시간). 「내 손안에 서울」 자료는 공개 저장소에 넣지 않았다(4절) | 호스트에서 자료를 만들 때 한 번 조회. 샌드박스 실행 중에는 부르지 않는다 | 없음 |

## 9. 평가 절차와 결과

- **경계 시험**: 막혀야 할 시도와 대조군을 예측과 실측으로 기록한다. `app/sandbox/violation_tests.md`의 B1 실측에서 파일·네트워크·실행 파일·키·통제층 시험과 게시 차단 → 승인 → 통과 → 회수가 모두 예측과 맞았다.
- **기록 점검**: 의사결정 기록의 해시 사슬, 인용 근거 실재, 등급 다시 계산, 게시 시도와 OpenShell 로그의 짝을 본다.
- **기능 평가**: 고정 사례를 결정적으로 채점한다. x/N과 Wilson 95% 구간(표본이 작을 때 쓰는 비율 신뢰구간)으로 적고, 기준선은 Nemotron 단독(자료·도구 없음)이다.
  - 평가 사례는 측정 전에 지문(sha256)으로 동결했다.
  - 사례 내용은 측정 뒤 공개한다.
- **결과표**(2026-10-07 16:00 동결 판 `c12e481`, 최종 이미지, 모델 NVIDIA API 카탈로그 `nvidia/nemotron-3-super-120b-a12b`). 자료 종류: **합성 사례**(요청과 기대값은 팀이 썼고, 장소·근거 자료는 실제 출처)

  | 대상 | dev(개발에 노출) | holdout(개발에 쓰지 않음) |
  |---|---|---|
  | 본 시스템 | 8/8 = 100% (Wilson 95% 67.6%~100%) | 3/4 = 75.0% (Wilson 95% 30.1%~95.4%) |
  | 기준선(Nemotron 단독, 자료·도구 없음) | 3/5 = 60.0% (Wilson 95% 23.1%~88.2%) | 1/3 = 33.3% (Wilson 95% 6.1%~79.2%) |

  - 사례는 수요 검증 담당이 쓴 12건이다(dev 8, holdout 4). 요청과 기대값을 팀이 만들었으므로 합성 사례다. 장소·자료 ID는 실제 출처 자료로 만든 테마 팩의 것이다. 측정 전에 sha256으로 동결했다.
  - 기준선의 분모가 작은 것은, 기준선으로 잴 수 없는 키(무게 판단·상태)만 있는 사례를 뺐기 때문이다. 이 규칙은 측정 전에 sha256으로 동결한 채점 스크립트에 들어 있다.
  - 두 구간이 겹치므로 기준선과의 차이를 주장하지 않는다. 사례 10건 안팎의 참고치다.
  - dev는 개발 중에 보았다. 기능 동결 전 리허설에서 dev 1건이 실패해, 그 원인(시간 예산이 없는 요청에서 모델이 빠뜨린 후보를 버림)을 고쳤다.
  - holdout 실패 1건은 출발역 표기다. 계획이 출발지를 "혜화역"으로 적었고, 기대값은 역 이름 "혜화"였다.
- **공통 시험 저장소의 연습 요청**(`TASK.md`, 입력 자료 20개를 `/hackathon/input`에 넣은 샌드박스)
  - 결과는 `COURSE_SAVED`(코스 2곳)이고, 사용자가 보내지 말라고 해 게시는 시도하지 않았다.
  - 입력 파일 4개를 읽고, 장소 이름 설명은 입력 파일을 근거로 인용했다(머리 정보가 없는 파일이라 등급 D).
  - 당일 운영 공지와 음식 제한은 코스에 반영하지 못했다(11절 한계).

## 10. 사후 감사와 의사결정 기록

- `/hackathon/output/<run_id>/trace.jsonl`: 무게 판단, 계획, 도구 호출, 게시 시도를 한 줄씩 남긴다. 각 줄은 앞 줄의 sha256을 담아, 나중에 고치면 드러난다.
- OpenShell 감사 로그와 정책 이력: 무엇이 언제 허용·거부되고 정책이 언제 바뀌었는지
- `sh app/sandbox/audit.sh <run_id>`: 위 셋을 모아 시각으로 짝을 맞춘다. 시연 실행 `20261007T063127Z-c5de`에서 시도 21, 짝 21, 어긋남 0, 해시 사슬 정상이었다.

## 11. 한계와 표기

- 파일 거부(Landlock)는 OpenShell 로그에 남지 않는다. 의사결정 기록의 EACCES로 확인한다.
- 구간 이동 시간은 Nemotron이 자료를 조사해 낸 값이다. 근거가 없으면 "추정"으로 표시한다.
- 게시 승인은 시연 동안 열고 끝나면 회수한다. 열린 동안에는 다른 실행의 게시도 통과한다.
- 만든 자료로 낸 숫자는 "합성"으로 표기한다.
- 지하철 구간 시간은 표준 운행시간의 합이다(정차·환승 시간 제외).
- 장소 하나에 여러 시설(케이블카, 전망대 등)의 운영 시간이 섞이면 결론을 내지 않고 "현장 확인 필요"로 보인다.
- 테마 팩 밖 장소의 일반 코스 요청은 입력 파일을 읽지만, 당일 운영 공지와 음식 제한을 구조화해 코스에 반영하지 못한다(공통 시험 저장소의 연습 요청으로 확인).
- 처음에는 요청의 무게 판단을 Claude가 맡았으나, 평가 환경에 Claude 키가 없을 수 있어 Nemotron으로 바꿨다. 제품은 Claude를 부르지 않는다.

## 12. 저장소 구조

| 경로 | 내용 |
|---|---|
| `app/retrieval/` | 하이브리드 검색과 JSON 색인 |
| `app/tools/` | 에이전트 도구 11개 |
| `app/loop/` | 무게 판단, 계획·실행, 의사결정 기록, CLI |
| `app/common/` | 공통 스키마와 도구 접점 |
| `app/agent/` | NIM 클라이언트와 RAG 답변 단계 |
| `app/sandbox/` | 이미지, 정책 파일, 위반 시험, 감사·시연 스크립트 |
| `app/index/kb/` | 지식 색인(JSON) |
| `app/web/` | 실시간 사용자 화면(호스트 로컬 서버, 127.0.0.1) |
| `docs/guide/` | 심사자 가이드: 실행(`RUN.md`), 심사 기준별 확인(`CHECK.md`) |
| `docs/`(그 밖) | 설계·운영 문서와 당일 기록(제출용 공개 저장소에는 넣지 않음) |
