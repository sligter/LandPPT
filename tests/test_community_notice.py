from landppt.services.community_service import CommunityService


def test_build_public_site_notice_returns_active_notice_within_window():
    service = CommunityService()

    notice = service.build_public_site_notice(
        {
            "site_notice_enabled": True,
            "site_notice_level": "warning",
            "site_notice_title": "Maintenance Notice",
            "site_notice_message": "Metrics deployment in progress.",
            "site_notice_start_at": 90,
            "site_notice_end_at": 110,
        },
        now_ts=100,
    )

    assert notice is not None
    assert notice["active"] is True
    assert notice["level"] == "warning"
    assert notice["title"] == "Maintenance Notice"


def test_build_public_site_notice_returns_none_when_outside_window():
    service = CommunityService()
    settings = {
        "site_notice_enabled": True,
        "site_notice_title": "Scheduled Update",
        "site_notice_message": "Starts later.",
        "site_notice_start_at": 120,
        "site_notice_end_at": 180,
    }

    assert service.build_public_site_notice(settings, now_ts=100) is None
    assert service.build_public_site_notice(settings, now_ts=200) is None


def test_build_public_settings_payload_normalizes_notice_fields():
    service = CommunityService()

    payload = service.build_public_settings_payload(
        {
            "sponsor_page_enabled": True,
            "site_notice_enabled": True,
            "site_notice_level": "ALERT",
            "site_notice_title": "  Service Update  ",
            "site_notice_message": "  New rollout window.  ",
            "site_notice_start_at": 220,
            "site_notice_end_at": 120,
        },
        now_ts=150,
    )

    assert payload["sponsor_page_enabled"] is True
    assert payload["sponsor_page_url"] == "/sponsors"
    assert payload["site_notice"] is not None
    assert payload["site_notice"]["level"] == "info"
    assert payload["site_notice"]["title"] == "Service Update"
    assert payload["site_notice"]["message"] == "New rollout window."
    assert payload["site_notice"]["start_at"] == 120
    assert payload["site_notice"]["end_at"] == 220
