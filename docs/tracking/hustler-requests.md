# Hustler 요청(2026-10-07)

팀장이 승인한 설계에서 Hustler에게 부탁하는 일이다. 형식과 필드 이름은 `docs/contracts.md` 6절의 "설계 4.7"(sweat 자료)과 "설계 4.8"(평가 사례)이 정본이다. 바뀌면 main에 올리고 팀장이 알린다. 최신 판은 `git fetch origin && git show origin/main:docs/contracts.md`로 본다.

## 1. sweat 더미데이터: 조사 묶음을 계약 형식으로 옮기기

조사 묶음(`data/sweat/kdh_pack/`)은 잘 받았다. 코드가 읽으려면 아래 형식으로 옮겨야 한다. 옮기는 일은 Hustler가 한다(팀장 결정).

**만들 것**(Hustler 브랜치, `data/sweat/` 아래)
- `data/sweat/theme_packs/<pack_id>.json`: 테마 팩 1개(케데헌)
  - 최상위: `pack_id`, `work_title`, `aliases`, `provenance`, `stations`, `places`
  - `stations`: 출발역 혜화와 각 장소의 가까운 역. `name`, `aliases`, `line`. 좌표(`lat`·`lon`)는 있으면 넣는다
  - `places`: 장소마다 `place_id`, `current_name`, `in_work_name`, `scene`, `old_names`, `station`, `stay_min`, `appearance_source_ids`, `priority`
- `data/sweat/sources/<source_id>.md`: 자료 한 건에 파일 하나
  - 맨 위 머리 정보(`---`로 둘러싼 `키: 값`): `source_id`, `title`, `publisher`, `source_type`, `published`, `url`, `provenance`, `kind`, `about`
  - `source_type`은 넷 중 하나다: `official`(공공기관 공식), `academic`(학술·백과), `media`(언론·관광 안내·위키), `informal`(블로그·구전·출처 불명)
  - `kind`는 넷 중 하나다: `origin`(이름 유래), `operating`(운영 정보), `appearance`(작품 속 등장 근거), `other`
  - 운영 자료(`kind: operating`)는 `place_ids`, `hours`, `closed`를 더한다
  - 그 아래가 본문이다
- 선택: `data/sweat/sources/_collection.json`(묶음 기본값)

**옮길 때 지킬 것**
- 등급은 코드가 `source_type`으로 계산한다. 조사 묶음의 `grade` 열은 옮기지 않아도 된다.
- 이동 시간은 테마 팩에 넣지 않는다. 역에서 장소까지 도보 시간 같은 동선 정보는 자료 본문에 쓰고, 출처가 있으면 URL을 단다. 에이전트(Nemotron)가 이것을 조사해 구간 시간을 낸다.
- 실제 출처에서 옮긴 문장은 `provenance: real`과 URL을, 만든 내용은 `provenance: synthetic`을 쓴다.
- 일부러 넣을 것(개발용)
  - 같은 이름에 다른 유래를 말하는 자료 한 쌍(출처 종류 다르게)
  - 운영 정보가 옛 날짜·새 날짜로 다른 한 쌍
  - 관계없는 자료 1건 이상
- 조사 묶음의 메모(`traps.md`, `open_questions.md`, `_parts/`, `BRIEF.md`)는 그대로 두어도 된다. 색인 도구는 `theme_packs/`와 `sources/`만 모은다.

**넘기는 법**: Hustler 브랜치에 커밋 → `python3 scripts/secret_scan.py origin/main..HEAD` 종료 0 → push → 팀장에게 병합 요청.

**기한**: 14:30. 15:00 무렵 색인을 굽고 샌드박스를 다시 만들기 때문이다.

## 2. 평가 사례 10~15건

**형식**: JSONL. 한 줄에 사례 하나다(`docs/contracts.md` 6절 "설계 4.8"). 기대 키 가운데 비운 것은 채점하지 않는다.

**구성**
- 사례마다 `split`을 `dev`(개발용) 또는 `holdout`(개발에 쓰지 않고 마지막에 한 번만 돌리는 사례)으로 표시한다.
- 시연 문장의 변형, 처음 보는 요청, 막혀야 할 요청(예: secrets 내용 요구, 보내지 말라는 요청), 함정(충돌·오래된 자료·관계없는 자료)을 섞는다.
- 장소 ID·자료 ID는 sweat 테마 팩·자료의 ID를 쓴다.

**넘기는 법(중요)**
- git에 올리지 않는다. Hustler 브랜치에도 넣지 않는다.
- clone 폴더 밖에 저장하고, 메신저 파일 등으로 팀장에게 직접 넘긴다. clone 안에 두면 에이전트가 커밋할 수 있다.
- 팀장이 받은 즉시 파일 지문(sha256)을 결정 기록에 커밋해 동결한다. 내용은 측정이 끝난 뒤에만 공개한다.

**기한**: 14:30 전(팀장 답).

## 3. 발표에서 준비할 질문(설계에서 나온 것)

- "무게 판단은 무엇이고 왜 Nemotron인가?" 요청이 자료 조회가 필요한 무거운 요청인지 먼저 가른다. 판단만 하고 답하지 않으며, 판단에 실패하면 응답하지 않는다. 처음에는 Claude가 맡았지만, 평가 환경에 다른 회사 키가 없어도 돌도록 Nemotron으로 바꿨다(14:35). 모델이 나가는 길은 NIM 하나이고 OpenShell 정책이 그 길만 연다.
- "파일 거부가 OpenShell 로그에 안 남는 이유는?" 파일 거부는 커널(Landlock)이 막아서 OpenShell 로그에 남지 않는다. 의사결정 기록에는 EACCES로 남는다. 네트워크 거부는 OpenShell 로그에 DENIED로 남는다.
- "게시 승인은 무엇인가?" 사람이 호스트에서 승인 정책 파일을 적용하는 일이다. 에이전트는 샌드박스 안에서 정책을 바꿀 수 없다. 승인은 시연 동안 열고 끝나면 회수하며, 정책 이력에 남는다.
