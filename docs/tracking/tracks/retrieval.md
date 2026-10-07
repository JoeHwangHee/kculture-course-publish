# 트랙 `retrieval` 최종 보고: I1 JSON 색인과 출처 메타데이터

- 범위 `app/retrieval/`, 브랜치 `track/retrieval`(base main `cc6e182`)
- 받은 지시: 0001(I1), 0002(접점 이름), 0005(머리 정보 값 JSON 표기), 0006(요청 0004에 대한 답)

## 한 일

- **형식 판 3 색인**(`app/retrieval/index.py`)
  - `manifest.json`(색인의 형식 판·설정·파일 목록을 적은 파일), `chunks.json`(청크 배열, 한 줄에 한 청크, 내부용 `tokens` 포함), `vectors.json`(청크 순서, 소수 6자리)
  - 한 파일이 `MAX_FILE_BYTES`(50MB, 조정값, `build_index(max_file_bytes=)`)를 넘으면 `chunks-0001.json`…·`vectors-0001.json`…의 조각(나눈 파일)으로 나눈다. manifest의 `chunk_files`·`vector_files`(언제나 목록)에 순서대로 적고, 로드는 그 순서로 이어 붙인다.
  - `format_version`이 3이 아니면 "형식 버전" `InputError`로 거부한다(판 2의 `chunks.jsonl`·`embeddings.npy` 포함).
  - manifest에 `source_fingerprint`를 적는다. 정의: 입력 루트 아래 일반 파일마다 `상대경로\t크기\tsha256\n`, 상대 경로순으로 이은 UTF-8 바이트의 sha256(내용 해시). 테마 팩·`_collection.json`·지원하지 않는 형식을 포함하고, mtime(파일 수정 시각)·심볼릭 링크(다른 경로를 가리키는 바로가기 파일)·루트 밖 파일은 넣지 않는다.
  - 다시 색인할 때 기존 `manifest.json`(JSON 객체이고 `format_version` 키가 있음)이 있을 때만 이전 산출물(조각, 판 2 파일, `theme_packs/*.json`)을 지운다. `--index`를 잘못 줬을 때 원본이 지워지지 않게 하려는 것이다.
- **출처 메타데이터**(`app/retrieval/source_meta.py`, `loader.py`)
  - 채우는 순서: Markdown 머리 정보 > 같은 폴더의 `_collection.json` > 기본값(`source_type=informal`, `kind=other`). 키마다 따로 정한다.
  - 빈 값(빈 문자열·빈 목록)은 다음 단계로 넘어간다. 계약 밖 머리 정보 키(`published_precision`, `line`, `station_id` 등)는 오류 없이 무시한다.
  - 모든 청크에 `CHUNK_SOURCE_KEYS`가 들어간다. `place_ids`·`hours`·`closed`는 `kind: operating` 청크에만 넣는다.
  - `source_id`·`publisher`·`url`·`provenance`는 없으면 빈 문자열로 둔다(지어 채우지 않음, 지시 0006으로 확인). `provenance`는 `real|synthetic`만 받는다. `published`는 실제 있는 `YYYY-MM-DD`만 받고, 아니면 빈 문자열이다.
  - 머리 정보 값 해석(지시 0005): `"`로 시작하거나 `[…]`이면 `json.loads`를 먼저 시도한다. 결과가 문자열이거나 문자열 목록이면 그것을 쓰고, 아니면 기존 규칙(`[a, b]`는 쉼표로 나누고, 그 밖은 문자열)을 따른다. 목록이 아닌 칸에 목록이 오면 `, `로 잇는다. 닫는 줄 뒤 공백을 허용하고, 닫는 줄이 없으면 경고한다.
  - 공개 함수 `parse_front_matter(text) -> (meta, body)`와 `parse_front_matter_value(value)`는 `tools`의 `read_file`이 쓸 수 있다.
- **색인에서 빼기와 테마 팩**
  - 경로 조각에 `theme_packs`가 있는 파일과 이름이 `_collection.json`인 파일은 청크로 만들지 않고, `skipped`에 `theme pack`·`collection defaults`로 남긴다.
  - 입력 루트의 `theme_packs/*.json`을 색인 폴더 `theme_packs/`로 바이트 그대로 복사한다. JSON 객체가 아닌 팩은 색인 때 `InputError`(CLI 종료 2)이고, 건너뛴 팩은 `skipped`에 남긴다.
- **`Retriever` 접점**(지시 0002 이름 그대로)
  - `load(index_dir, embedder)`, `query(q, k, mode)`: 호출 모양과 토크나이저 불일치 오류, RRF(두 검색 순위를 합치는 방식) k=60이 그대로다. 검색 결과에 출처 키가 그대로 실린다.
  - `get_chunk(chunk_id) -> dict | None`
  - `chunks_where(kind, place_id) -> list[dict]`: 조건에 맞는 청크 전부, 색인 순서
  - `theme_packs() -> list[dict]`: 색인 폴더의 `theme_packs/*.json`, 파일 이름순. 깨진 팩은 `RetrievalError`.
  - 반환값은 모두 깊은 복사(목록 값까지 새로 만든 사본)이고 `tokens`가 없다.
- CLI `query`의 사람용 출력에 `출처 | 종류 | 출처 종류` 줄을 더했다.

## 커밋

- `0244577` feat(I1): JSON 색인 형식 판 3과 출처 메타데이터
- `c6da2b6` fix(I1): 머리 정보 JSON 표기 값, 닫는 줄 공백, 테마 팩 색인 때 검사, 정리 안전장치
- `eca640c` fix(I1): 테마 팩 폴더 검사를 쓰기 전으로, RecursionError 처리, 경고에 경로, BOM 팩
  - `RecursionError`: 너무 깊게 중첩된 JSON에서 나는 예외. BOM: UTF-8 파일 맨 앞에 붙는 표식 바이트
- 바뀐 파일 8개(모두 `app/retrieval/` 아래): `__main__.py`, `index.py`, `loader.py`, `source_meta.py`(새 파일), `tests/test_cli.py`, `tests/test_index.py`, `tests/test_index_v3.py`(새 파일), `tests/test_source_meta.py`(새 파일)

## 검증 명령과 종료 코드(`app/`에서, 하위가 직접 다시 돌림)

- 기준(작업 전, cc6e182): `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest` → 종료 0, 294 passed, 1 skipped
- `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest retrieval/tests -q` → 종료 0, 수집 154건(153 passed, 1 skipped)
- `env -u NVIDIA_API_KEY -u ANTHROPIC_API_KEY -u GITHUB_TOKEN uv run pytest -q`(전체) → 종료 0, 수집 368건(367 passed, 1 skipped)
  - 건너뛴 1건은 기존 `retrieval/tests/test_embedder.py:73`이다(`RETRIEVAL_MODEL_PATH` 미설정, 실제 모델 폴더가 필요한 시험).
- CLI(가짜 입력의 `sources/`·`theme_packs/`만 임시 폴더로 모음)
  - `uv run python -m retrieval index --input <tmp>/in --index <tmp>/idx --embedder=hash` → 종료 0. 문서 10, 청크 10, 건너뜀 2(`sources/_collection.json` collection defaults, `theme_packs/fx-byeolmuri.json` theme pack)
  - `uv run python -m retrieval query --index <tmp>/idx --embedder=hash --json "달무리나루 이름 유래"` → 종료 0. 결과 5건 모두 출처 키가 있다(1위 `fx-src-origin-dalmuri-blog`, 2위 `fx-src-origin-dalmuri-official`).
  - JSON 표기 머리 정보 문서(`source_type: "official"`, `about: ["혜화", "혜화역"]`)로 index → query → `source_type: official`, `about`은 목록. 따옴표가 남지 않는다.
  - 깨진 테마 팩으로 index → 종료 2(`입력 오류: 테마 팩이 JSON 객체가 아닙니다(깨진 JSON 포함): theme_packs/broken.json`)
- 완료 조건 시험: `retrieval/tests/test_index_v3.py`의 `test_search_results_carry_source_keys`, `test_theme_pack_and_collection_not_in_chunks`(통과)
- 비밀값 검사(검토 worker가 실행): `python3 scripts/secret_scan.py cc6e182..eca640c` → 종료 0

## worker-reviewer 판정

- 1차(`0244577`): APPROVE, 막는 결함 없음. 권고 6건 가운데 5건을 수정 라운드에서 반영했다: 닫는 줄 뒤 공백, 깨진 팩이 색인 뒤에야 터지는 문제, 정리 단계의 원본 삭제 위험, 없는 날짜, 머리 정보 값을 잃는 문제. 마지막 것은 지시 0005의 JSON 표기 규칙으로 바꿔 반영했다. 따옴표 친 값(`"2026-01-01"`, `"[공지] …"`)은 해결됐지만, 따옴표 없는 대괄호 값(`title: [공지] 변경 [최종]`)은 지시 0005 규칙상 지금도 목록으로 읽혀 `공지] 변경 [최종`이 된다(문서 수정 제안 참고). 나머지 1건(벡터 JSON의 숫자 형 검사)은 영향이 작아 두었다.
- 2차(`c6da2b6`, 새 에이전트): APPROVE, 막는 결함 없음. 권고 5건.
  - 반영한 4건: 색인 폴더 검사를 쓰기 전으로 옮김, `RecursionError` 처리, 닫는 줄 경고에 경로, BOM 팩.
  - 두지 않은 1건: 정리되지 않은 색인 폴더의 기존 팩을 `theme_packs()`가 함께 읽는 문제. 설계 문제라 문서 제안으로 넘긴다.
- 3차(`eca640c`, 새 에이전트): APPROVE, 막는 결함 없음.
  - 권고 1: `RecursionError` 경로 넷 가운데 시험이 있는 것은 머리 정보 값 하나다. 나머지 셋(테마 팩 색인 때, `_is_index_folder`, `theme_packs()`)은 검토자가 임시 스크립트로 동작을 확인했다.
  - 권고 2: `_write_theme_packs`에 같은 검사가 겹쳐 있다. 안전장치로 둔다.

## worker-debugger가 찾은 원인

- 부르지 않았다. 검증 실패나 BLOCKED가 없었다.

## 남은 일

- `RecursionError` 나머지 세 경로의 시험(3차 검토 권고, 동작은 확인됨)
- 실제 자료(sweat 228건, 역명 유래 274건)와 실제 임베더(`--embedder=local:<모델 폴더>`)로 `app/index/kb/`를 굽는 일은 상위 몫이다(`build_kb.sh`). 이 트랙은 가짜 입력과 hash 임베더로만 확인했다.
- 벡터 JSON 값의 숫자 형 검사(1차 권고 5, 영향 작음)

## 문서 수정 제안

- 계약 4.3: 값 해석 규칙(JSON 표기 우선)과 함께 "대괄호가 든 문자열 값(예: 제목)은 JSON 따옴표로 감싼다. 감싸지 않으면 `[a, b]` 목록 규칙에 걸린다"를 적는다. "목록 항목은 문자열만"도 적는다(`["a", 1]`은 대체 규칙으로 처리되어 따옴표가 남는다).
- 계약 4.3: `published`는 실제 있는 날짜만 받고, 아니면 빈 값이 된다는 점을 적는다.
- 계약 4.3: 다시 색인할 때 정리 규칙(기존 manifest가 있을 때만)과 `skipped` 이유 글자(`theme pack`, `collection defaults`, `theme pack not copied: <이유>`)를 적는다.
- 계약 4.2(설계 제안): 색인 폴더에 원래 있던 `theme_packs/*.json`이 정리되지 않은 경우 `theme_packs()`가 함께 읽는다. manifest에 복사한 팩 이름 목록을 적고 `theme_packs()`가 그 목록만 읽게 하는 방안이 있다.
- `tools` 트랙 메모: 청크의 `char_start/char_end`는 머리 정보를 떼고 공백을 정리한 본문 기준이다. `parse_front_matter`가 돌려준 원문 본문을 이 오프셋으로 자르면 어긋날 수 있다.
