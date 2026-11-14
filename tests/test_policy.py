from horizon_explorer.policy import may_navigate, risk_for, same_allowed_origin


def test_limits_navigation_to_horizon_https() -> None:
    assert same_allowed_origin("https://www.discoverhorizon.com/authenticated/schedule/Page.aspx")
    assert not same_allowed_origin("http://www.discoverhorizon.com/authenticated/")
    assert not same_allowed_origin("https://example.test/")


def test_risky_url_needs_exact_confirmation() -> None:
    url = "https://www.discoverhorizon.com/authenticated/schedule/Edit.aspx?id=1"
    assert risk_for("", url) == "risky"
    assert may_navigate(url, set()) == (False, "risky URL requires exact explicit confirmation")
    assert may_navigate(url, {url}) == (True, "")


def test_schedule_view_is_safe_to_inspect() -> None:
    url = "https://www.discoverhorizon.com/authenticated/schedule/ScheduleDayViewX.aspx"
    assert may_navigate(url, set()) == (True, "")
