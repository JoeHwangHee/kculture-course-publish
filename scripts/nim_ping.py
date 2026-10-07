#!/usr/bin/env python3
"""NIM 키 확인: NVIDIA_API_KEY로 chat/completions에 아주 짧은 요청 1건을 보내 HTTP 상태만 출력한다(표준 라이브러리만 쓴다).

키는 환경변수로만 받고 .env를 직접 읽지 않는다. 키 래퍼와 함께 쓴다(폴더 루트에서):
    python3 scripts/with_nvidia_key.py --env-file .env -- python3 scripts/nim_ping.py

출력: `HTTP <상태> · 모델 <이름>` 한 줄. 키 값과 응답 본문은 출력하지 않는다.
    200      키와 모델 접근이 된다
    401·403  키 문제(폐기된 키, 오타, 권한)
    404      모델 이름 문제(환경변수 NIM_MODEL로 바꿔 볼 수 있다)
    429      속도 제한. 잠시 뒤 다시 본다
    5xx      서버 쪽 문제. 잠시 뒤 다시 본다
종료 코드: 0 HTTP 200, 1 그 밖의 HTTP 상태, 2 키 없음, 3 연결 실패.
"""
import json
import os
import sys
import urllib.error
import urllib.request

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = os.environ.get("NIM_MODEL", "nvidia/nemotron-3-super-120b-a12b")


def main() -> int:
    key = os.environ.get("NVIDIA_API_KEY")
    if not key:
        print("NVIDIA_API_KEY가 환경에 없습니다. 키 래퍼로 실행하세요(이 파일 머리 주석 참고).", file=sys.stderr)
        return 2
    body = {"model": MODEL, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8,
            "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", "Accept": "application/json"})
    req.add_unredirected_header("Authorization", f"Bearer {key}")  # 리디렉션 때 키를 다른 곳으로 보내지 않는다
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        status = exc.code
    except urllib.error.URLError as exc:
        print(f"연결 실패: {exc.reason}", file=sys.stderr)
        return 3
    print(f"HTTP {status} · 모델 {MODEL}")
    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
