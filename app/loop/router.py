"""Weight router (spec 2.1 step 2, decision 0010): Nemotron only judges heavy or light and never answers the request.

Router calls run on the Budget's own `router` counter, so they do not use the Nemotron call limit of the run.
"""

from __future__ import annotations

from common.schema import EVENT_ROUTE, KIND_OK, ROUTE_HEAVY, ROUTE_LIGHT

from loop.budget import ROUTER_CALLS_DEFAULT, LimitHit
from loop.planner import PLAN_RESPONSE_FORMAT, extract_json_object

ROUTER_PURPOSE = "route"

TEXT_NO_WORKS = "(목록 없음)"

# Examples are fictional works and stations on purpose (0019): never the demo sentence or a variant of it.
_ROUTER_SYSTEM_TEMPLATE = (
    "이 서비스: K-콘텐츠(드라마·영화·애니메이션)를 보고 온 방문객에게 배경지를 잇는 코스를 짜고, "
    "장소·역 이름의 유래를 근거 등급과 함께 알려 주는 에이전트다.\n"
    "이 서비스가 아는 작품(제목(별칭, …)): {works}\n"
    "\n"
    "너는 요청의 무게만 판단한다. 요청에 답하지 않는다.\n"
    "heavy로 보는 요청(직접 묻지 않아도 코스나 근거를 원하는 요청이다):\n"
    "- 사용자가 작품을 보고 왔다고 할 때\n"
    "- 작품·배경지·장소·역·코스·동선·남은 시간·출발지·운영 시간·이름 유래·게시 가운데 하나라도 말할 때\n"
    "- 자료 조회가 필요하거나, 여러 단계가 필요하거나, 근거 등급을 다룰 때\n"
    "- 파일·폴더 내용을 물을 때\n"
    "light로 보는 요청은 세 가지뿐이다:\n"
    "- 인사만 있는 말\n"
    "- 이 서비스의 사용법을 묻는 말\n"
    "- 위 어느 것과도 관계없는 짧은 일반 질문\n"
    "판단이 애매하면 heavy로 본다.\n"
    "\n"
    "가상 예(실제 작품이 아니다):\n"
    '- "드라마 달빛정원에 나온 카페들을 이어서 돌아보고 싶어요" → heavy\n'
    '- "을지로 근처 촬영지 운영 시간 알려 줘" → heavy\n'
    '- "안녕하세요" → light\n'
    '- "이거 어떻게 쓰는 거예요?" → light\n'
    "\n"
    '출력은 JSON 객체 하나뿐이다: {{"weight": "heavy" 또는 "light", "why": "<한 줄>"}}'
)


def work_label(pack: dict) -> str:
    """"제목(별칭, …)" for one theme pack; just the title without aliases; "" if there is no title."""
    title = pack.get("work_title") if isinstance(pack, dict) else None
    if not isinstance(title, str) or not title.strip():
        return ""
    aliases = [a for a in (pack.get("aliases") or []) if isinstance(a, str) and a.strip()]
    return f"{title}({', '.join(aliases)})" if aliases else title


def build_router_system(works: list[str] | None = None) -> str:
    listed = ", ".join(w for w in (works or []) if w) or TEXT_NO_WORKS
    return _ROUTER_SYSTEM_TEMPLATE.format(works=listed)


ROUTER_SYSTEM = build_router_system([])  # the prompt without a work list


def _model_entry(budget, before: int):
    if budget is None or len(budget.call_log) <= before:
        return None
    return budget.call_log[-1]


def route(request: str, router_chat, trace, budget=None, works: list[str] | None = None) -> str | None:
    """"heavy" or "light", or None after two failed tries (the caller ends UNAVAILABLE; no guessing).

    Failure = exception, empty reply, not JSON, weight not heavy/light. LimitHit propagates (a limit, not a failure).
    `budget` (optional) supplies the trace `model` entry from its call log. `works` are the work labels the runner
    built from the theme packs (work_label); the router only calls the model.
    """
    messages = [{"role": "system", "content": build_router_system(works)}, {"role": "user", "content": request}]
    for _ in range(ROUTER_CALLS_DEFAULT):
        before = len(budget.call_log) if budget is not None else 0
        weight, why, failure = None, "", ""
        try:
            reply = router_chat(messages, ROUTER_PURPOSE, response_format=PLAN_RESPONSE_FORMAT)
        except LimitHit:
            raise
        except Exception as exc:  # any client failure counts as a failed try
            failure = type(exc).__name__
        else:
            text = reply.get("text") if isinstance(reply, dict) else None
            obj = extract_json_object(text) if isinstance(text, str) and text.strip() else None
            if not isinstance(text, str) or not text.strip():
                failure = "빈 응답"
            elif obj is None:
                failure = "JSON 아님"
            elif obj.get("weight") not in (ROUTE_HEAVY, ROUTE_LIGHT):
                failure = "weight 값이 틀림"
            else:
                weight = obj["weight"]
                why = " ".join(obj["why"].split()) if isinstance(obj.get("why"), str) else ""
        model = _model_entry(budget, before)
        cut = ""
        if budget is not None and "length" in getattr(budget, "finish_reasons", [])[before:]:
            cut = "; 모델 답이 출력 한도에서 잘림"  # 0025
        if weight is not None:
            trace.append(EVENT_ROUTE, kind=KIND_OK, summary=weight + cut, why=why, model=model)
            return weight
        trace.append(EVENT_ROUTE, kind="", summary=f"실패: {failure}{cut}", why="", model=model)
    return None
