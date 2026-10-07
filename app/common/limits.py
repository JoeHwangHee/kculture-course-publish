"""Default limits the code enforces (spec 4.10) and the other values the spec marks 조정값 (adjustable default).

They are contract values: change one only with the team lead's approval. A limit written only into a prompt does not
count as a limit (docs/standards.md section 6); the loop and the tools enforce these in code and, when one is hit,
end the run as FAILED with the limit named in run.json `limits_hit`.
"""

# ---------------------------------------------------------------- spec 4.10

ROUTER_CALLS_PER_RUN = 2  # logical router calls (Nemotron weight judgment): the first + one retry (2.1).
#                            Counted apart from NEMOTRON_CALLS_PER_RUN. HTTP resends are not counted.
NEMOTRON_CALLS_PER_RUN = 8  # logical calls for plan, tools, light answer and baseline. HTTP resends after 429/5xx (NimClient rule) are not counted.
TOKENS_PER_RUN = 128_000  # cumulative tokens of both models (sum of response usage)
RUN_SECONDS = 300  # wall time of one run, excluding the approval wait
APPROVAL_WAIT_SECONDS = 180  # waiting for the publish approval, resending meanwhile (2.4)
TOOL_STEPS = 12  # executed plan steps incl. re-planned ones; publish resends and the pre-plan list_input excluded
READ_FILE_MAX_BYTES = 64 * 1024  # one read_file reads at most this much; longer files are cut and TOO_LARGE noted

# ---------------------------------------------------------------- other values from the spec

PLAN_STEPS_MAX = 12  # 4.5 steps in one plan (plan check)
REPLANS_PER_RUN = 1  # 2.2 "다시 계획을 받는 것은 실행 전체에서 한 번까지" (rule, not marked 조정값)
PUBLISH_RETRY_INTERVAL_SECONDS = 10  # 2.4 resend interval while waiting for approval
ORIGIN_K_DEFAULT = 5  # 4.2 lookup_origin `k`: chunks per name
DEFAULT_STAY_MIN = 60  # 4.6 stay when the theme pack has no stay_min (marked estimate)
TRAVEL_MINUTES_MIN = 1  # 4.6 a leg whose minutes are not an integer in 1..180 becomes unknown (rule)
TRAVEL_MINUTES_MAX = 180
MAX_PLACES_WITHOUT_BUDGET = 5  # section 5: no time budget -> up to this many places by priority
HTTP_BODY_MAX_BYTES = 4 * 1024  # 4.2 Deps.http_post_json returns at most the first 4KB of the response body
