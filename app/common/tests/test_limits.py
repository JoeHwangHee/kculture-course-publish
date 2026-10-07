"""Default limits (spec 4.10 and the other 조정값 the tools/loop tracks share)."""

from common import limits


def test_limits_of_spec_4_10():
    assert limits.ROUTER_CALLS_PER_RUN == 2
    assert limits.NEMOTRON_CALLS_PER_RUN == 8
    assert limits.TOKENS_PER_RUN == 128_000
    assert limits.RUN_SECONDS == 300
    assert limits.APPROVAL_WAIT_SECONDS == 180
    assert limits.TOOL_STEPS == 12
    assert limits.READ_FILE_MAX_BYTES == 64 * 1024


def test_other_tunables_from_the_spec():
    assert limits.PLAN_STEPS_MAX == 12  # 4.5
    assert limits.REPLANS_PER_RUN == 1  # 2.2
    assert limits.PUBLISH_RETRY_INTERVAL_SECONDS == 10  # 2.4
    assert limits.ORIGIN_K_DEFAULT == 5  # 4.2 lookup_origin.k
    assert limits.DEFAULT_STAY_MIN == 60  # 4.6
    assert (limits.TRAVEL_MINUTES_MIN, limits.TRAVEL_MINUTES_MAX) == (1, 180)  # 4.6
    assert limits.MAX_PLACES_WITHOUT_BUDGET == 5  # 5
    assert limits.HTTP_BODY_MAX_BYTES == 4 * 1024  # 4.2 http_post_json body


def test_limits_are_positive_integers():
    names = [n for n in dir(limits) if n.isupper()]
    assert len(names) >= 16
    for name in names:
        value = getattr(limits, name)
        assert isinstance(value, int) and not isinstance(value, bool) and value > 0, name
