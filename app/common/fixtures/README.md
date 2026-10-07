# 가짜 입력(fixture: 시험용으로 고정한 입력)

설계 4.7절 형식을 그대로 따른 가상 자료다. Hustler의 실제 자료(`data/sweat/`)가 오기 전에 세 트랙(`retrieval`, `tools`, `loop`)이 이 자료로 개발한다. 작품·역·장소·발행처는 모두 지어낸 이름이고, 자료는 모두 `provenance: synthetic`이다. 평가 사례가 아니다.

- `theme_packs/fx-byeolmuri.json`: 가상 작품 「별무리 수호단」(별칭 별수단). 역 3개, 장소 6곳.
- `sources/<source_id>.md`: 자료 10건. 머리 정보(`---`로 둘러싼 `키: 값`, 값 목록은 `[a, b]`) 아래가 본문이다.
- `sources/_collection.json`: 묶음 기본값. 머리 정보 키와 같은 이름의 평평한 객체로 두었다 `[추론: 설계에 형식이 없어 이렇게 정함]`.
- 이 파일(`README.md`)은 `theme_packs/`·`sources/` 밖에 있어 색인 대상이 아니다.

## 장소와 역

| place_id | 지금 이름 | 작품 속 이름 | 가까운 역 | stay_min | priority |
|---|---|---|---|---|---|
| fx-01 | 달무리나루 선착장 | 수호단 비밀 부두 | 달무리나루 | 30 | 1 |
| fx-02 | 별가루 골목시장 | 반짝 장터 | 새벽솔 | 30 | 2 |
| fx-03 | 솔빛고개 전망쉼터 | 수호단 망루 | 솔빛고개 | 20 | 3 |
| fx-04 | 새벽솔 약속정원 | 약속의 정원 | 새벽솔 | 30 | 3 |
| fx-05 | 바람끝곶 등대 | 마지막 신호탑 | 솔빛고개 | 60 | 4 |
| fx-06 | 구름안개 폭포마당 | 수호단 수련터 | 달무리나루 | 60 | 5 |

- 출발역은 새벽솔로 쓴다. 동선 자료 기준으로 fx-01~fx-04는 역에서 5~12분, fx-05·fx-06은 75~80분 걸리는 먼 곳이다. 먼 두 곳은 우선순위도 가장 낮아(4·5), 여섯 곳을 고른 3시간 코스가 예산을 넘으면 먼저 빠진다.
- fx-03과 fx-04는 priority가 같다. 예산을 넘을 때 "같은 우선순위면 순서의 뒤쪽부터 뺀다"를 시험할 수 있다.

## 자료와 일부러 넣은 상황

| source_id | kind | source_type(등급) | published | 쓰임 |
|---|---|---|---|---|
| fx-src-origin-dalmuri-official | origin | official(A) | 2023-05-10 | 달무리나루 유래 ① 달무리가 잘 보이던 나루 |
| fx-src-origin-dalmuri-blog | origin | informal(D) | 2025-11-02 | 달무리나루 유래 ② 뱃사공 이름. ①과 충돌 |
| fx-src-origin-solbit-academic | origin | academic(B) | 2022-07-01 | 역 이름 솔빛고개의 유래 |
| fx-src-op-byeolgaru-2024 | operating | media(C) | 2024-03-01 | fx-02 옛 운영 정보 |
| fx-src-op-byeolgaru-2026 | operating | official(A) | 2026-08-01 | fx-02 새 운영 정보. 새 자료 등급이 같거나 높음 → 새 자료를 택하고 옛 자료는 `stale` |
| fx-src-op-solbit-2025 | operating | official(A) | 2025-01-10 | fx-03 옛 운영 정보 |
| fx-src-op-solbit-2026 | operating | informal(D) | 2026-09-01 | fx-03 새 운영 정보. 새 자료 등급이 낮음 → `NEEDS_ONSITE_CHECK` |
| fx-src-route-walk | other | media(C) | 2026-06-15 | 역에서 장소까지 도보 시간, 역 사이 이동 시간(구간 조사의 근거) |
| fx-src-appearance | appearance | media(C) | 2026-02-20 | 작품 속 장면과 장소 대응. 테마 팩 `appearance_source_ids`가 가리킨다 |
| fx-src-unrelated | other | informal(D) | 2026-03-03 | 무관한 자료(감자전 조리법) |

- fx-01·fx-04·fx-05·fx-06에는 운영 자료가 없다. 운영 정보가 없는 장소(`UNKNOWN`)를 시험할 수 있다.
- 형식 검사는 `app/common/tests/test_fixtures.py`가 한다.
