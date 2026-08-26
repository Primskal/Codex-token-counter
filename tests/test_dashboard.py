from __future__ import annotations

import json
import urllib.error
import urllib.request
from importlib.resources import files

from codex_token_monitor.dashboard import DashboardServer
from codex_token_monitor.monitor import MonitorService
from codex_token_monitor.settings import AutostartManager

from test_settings_single_instance import FakeRegistry


def get(url):
    with urllib.request.urlopen(url) as response:
        return response.status, response.read(), response.headers


def post(url, token, payload=b"{}"):
    request = urllib.request.Request(url, data=payload, method="POST", headers={
        "Content-Type": "application/json", "X-CSRF-Token": token
    })
    with urllib.request.urlopen(request) as response:
        return response.status, response.read()


def test_dashboard_local_api_csv_and_csrf(repository, tmp_path):
    monitor = MonitorService(repository, roots_override=[tmp_path / "logs"])
    autostart = AutostartManager(repository, FakeRegistry())
    server = DashboardServer(repository, monitor, autostart, port=0)
    server.start()
    try:
        status, body, headers = get(server.url)
        assert status == 200 and b"Codex Token Monitor" in body
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        status, body, _ = get(server.url + "format.js")
        assert status == 200 and b"formatTokens" in body
        status, body, _ = get(server.url + "api/status")
        assert status == 200 and "processed_events" in json.loads(body)
        status, body, _ = get(server.url + "api/settings")
        settings = json.loads(body)
        assert status == 200
        assert "custom_log_paths" not in settings and "backfill_days" not in settings
        status, body, headers = get(server.url + "api/csv?start=2026-08-24&end=2026-08-25")
        assert body.startswith(b"\xef\xbb\xbf") and headers["Content-Type"].startswith("text/csv")
        assert post(server.url + "api/rescan", server.csrf_token)[0] == 200
        bad = urllib.request.Request(server.url + "api/rescan", data=b"{}", method="POST")
        try:
            urllib.request.urlopen(bad)
            assert False, "CSRF 없는 요청이 거부되어야 함"
        except urllib.error.HTTPError as error:
            assert error.code == 403
    finally:
        server.stop()


def test_dashboard_refreshes_statistics_when_backfill_adds_events():
    """The initial empty view must not remain stale while a backfill is running."""
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")
    stylesheet = (files("codex_token_monitor") / "web" / "dashboard.css").read_text("utf-8")
    table_stylesheet = (files("codex_token_monitor") / "web" / "dashboard-layout.css").read_text("utf-8")

    assert "let renderedEventCount = -1" in script
    assert "const shouldRefreshStats=s.processed_events!==renderedEventCount" in script
    assert "if(shouldRefreshStats)await loadStats()" in script
    assert ":root{color-scheme:light" in stylesheet
    assert "table-layout:fixed" in table_stylesheet


def test_dashboard_trend_includes_models_total_and_hover_tooltip():
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")
    template = (files("codex_token_monitor") / "web" / "dashboard.html").read_text("utf-8")
    stylesheet = (files("codex_token_monitor") / "web" / "dashboard.css").read_text("utf-8")

    assert "function trendSeries(trend)" in script
    assert "name: '총합'" in script
    assert "addEventListener('pointermove', handleTrendPointer)" in script
    assert "fmt.format(item.values[index])" in script
    assert 'id="trend-legend"' in template
    assert 'id="trend-tooltip"' in template
    assert ".trend-tooltip" in stylesheet


def test_dashboard_range_presets_select_buttons_and_request_expected_granularity():
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")
    template = (files("codex_token_monitor") / "web" / "dashboard.html").read_text("utf-8")
    stylesheet = (files("codex_token_monitor") / "web" / "dashboard.css").read_text("utf-8")

    for preset in ("today", "7d", "month", "quarter", "half", "year"):
        assert f'data-range="{preset}"' in template
    assert "today: {months: 0, granularity: '30m'}" in script
    assert "quarter: {months: 3, granularity: '10d'}" in script
    assert "half: {months: 6, granularity: 'month'}" in script
    assert "year: {months: 12, granularity: 'month'}" in script
    assert "button.classList.toggle('selected', selected)" in script
    assert ".presets button.selected" in stylesheet


def test_dashboard_uses_semantic_model_colors_and_dark_gray_total():
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")

    assert "sol: '#f97316'" in script
    assert "terra: '#16a34a'" in script
    assert "luna: '#ca8a04'" in script
    assert "color: '#6b7280'" in script
    assert "model.toLowerCase().includes(name)" in script


def test_dashboard_increases_all_text_roles_by_one_point():
    stylesheet = (files("codex_token_monitor") / "web" / "dashboard.css").read_text("utf-8")

    assert "body{font-size:calc(16px + 1pt)}" in stylesheet
    assert "h1{font-size:calc(29px + 1pt)}" in stylesheet
    assert "button,.button-link,body table,dl,#diagnostics{font-size:calc(13px + 1pt)}" in stylesheet
    assert ".trend-legend{font-size:calc(11px + 1pt)}" in stylesheet


def test_dashboard_renames_week_preset_and_toggles_trend_series_from_legend():
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")
    template = (files("codex_token_monitor") / "web" / "dashboard.html").read_text("utf-8")
    stylesheet = (files("codex_token_monitor") / "web" / "dashboard.css").read_text("utf-8")

    assert 'data-range="7d" aria-pressed="false">이번 주</button>' in template
    assert "const hiddenTrendSeries = new Set()" in script
    assert "hiddenTrendSeries.add(item.name)" in script
    assert "hiddenTrendSeries.delete(item.name)" in script
    assert "series.filter(item => !hiddenTrendSeries.has(item.name))" in script
    assert "button.trend-legend-item.disabled" in stylesheet


def test_dashboard_uses_daily_usage_title_and_hides_advanced_log_options():
    script = (files("codex_token_monitor") / "web" / "dashboard.js").read_text("utf-8")
    template = (files("codex_token_monitor") / "web" / "dashboard.html").read_text("utf-8")

    assert "날짜별 사용량" in template
    assert "날짜 × 모델" not in template
    assert "custom-paths" not in template and "custom-paths" not in script
    assert "backfill-days" not in template and "backfill-days" not in script
