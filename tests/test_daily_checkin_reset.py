from datetime import datetime

from landppt.services.community_service import CommunityService


def _ts(year: int, month: int, day: int, hour: int, minute: int = 0, second: int = 0) -> float:
    return datetime(
        year,
        month,
        day,
        hour,
        minute,
        second,
        tzinfo=CommunityService.CHECKIN_TIMEZONE,
    ).timestamp()


def test_checkin_day_uses_previous_period_before_eight_am():
    assert CommunityService._today_key(_ts(2026, 3, 20, 7, 59, 59)) == "2026-03-19"


def test_checkin_day_switches_at_eight_am():
    assert CommunityService._today_key(_ts(2026, 3, 20, 8, 0, 0)) == "2026-03-20"


def test_checkin_window_reports_next_reset_timestamp():
    checkin_day, next_reset_at = CommunityService._checkin_window(_ts(2026, 3, 20, 7, 30, 0))

    assert checkin_day == "2026-03-19"
    assert next_reset_at == _ts(2026, 3, 20, 8, 0, 0)
