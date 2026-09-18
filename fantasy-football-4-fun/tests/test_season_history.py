"""Network-free tests for the season-history interstitial: a multi-season
league opened with no season chosen shows a season-picker list instead of
jumping straight into the latest season's Overview; a single-season league
(or any request that already names a season) falls straight through
unchanged. Also covers GET /seasons, the on-demand reopen of that same list
that replaced the header's season <select> entirely (index.html's header
subtitle) -- see app.py's seasons_history(). Follows the direct-call
convention test_core.py/test_player_page.py use for other routes -- no
ASGI/TestClient layer, a fixture Season and a call straight into the route
function.
"""
from __future__ import annotations

import dataclasses

from webapp import app
from conftest import make_season


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def _mock_pick(monkeypatch, d):
    monkeypatch.setattr(app, "pick", lambda league, season, fresh=False: (
        d, d["seasons"][season if season in d["seasons"] else d["names"][-1]],
        season if season in d["seasons"] else d["names"][-1]))


def _multi_season_d():
    # Distinct league_ids per season, since Sleeper gives every season of a
    # real league a different one -- make_season() defaults every fixture
    # Season to the same "0", which would hide a bug where a row's link used
    # the CURRENT context's id instead of that season's own.
    s2024 = dataclasses.replace(make_season(season="2024"), league_id="L2024")
    s2025 = dataclasses.replace(make_season(season="2025"), league_id="L2025")
    return {"playoffs": {}, "names": ["2024", "2025"],
            "seasons": {"2024": s2024, "2025": s2025}}


def test_season_history_rows_newest_first_with_flags():
    d = _multi_season_d()
    rows = app._season_history_rows(d)
    assert [r["season"] for r in rows] == ["2025", "2024"]
    assert rows[0]["is_latest"] is True
    assert rows[1]["is_latest"] is False


def test_season_history_rows_carry_each_seasons_own_league_id():
    """Each row's league_id must be THAT season's own real Sleeper id, not
    whatever id the caller happened to load the league with -- Sleeper gives
    every season of a league a different id, and a 2022 row must link to
    2022's own id, not the current-season one shown elsewhere on the page."""
    d = _multi_season_d()
    rows = app._season_history_rows(d)
    by_season = {r["season"]: r for r in rows}
    assert by_season["2024"]["league_id"] == "L2024"
    assert by_season["2025"]["league_id"] == "L2025"


def test_multi_season_league_shows_history_when_no_season_given(monkeypatch):
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season=None, boot=1)
    body = resp.body.decode()
    assert "tab_season_history" not in body  # sanity: not literally the filename
    assert "2024" in body and "2025" in body
    assert resp.template.name == "tab_season_history.html"
    # Each row links to ITS OWN season's league_id, not "123" (the id this
    # request happened to be loaded with).
    assert 'href="/dashboard?league=L2024&season=2024&tab=overview"' in body
    assert 'href="/dashboard?league=L2025&season=2025&tab=overview"' in body
    assert "bracket recorded" not in body


def test_history_page_push_url_has_no_season_or_tab(monkeypatch):
    """Regression test for a real, shipped bug: the history branch used to
    call the generic _pushed(), which always bakes in a season and tab --
    since ctx["season"] here is `key` (the resolved LATEST season, set by
    _base_ctx before this branch runs), the pushed URL read
    /dashboard?league=X&season=<latest>&tab=overview even though the page on
    screen is the history LIST, not that season's Overview. Bookmarking or
    reloading that URL silently skipped the list and jumped straight to the
    latest season instead. The fix (_pushed_history) must push the bare
    /dashboard?league=X, with no season/tab at all -- reloading THAT must
    reproduce the same "no season given" condition that shows this page."""
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season=None, boot=1)
    assert resp.headers["HX-Push-Url"] == "/dashboard?league=123"
    assert "season=" not in resp.headers["HX-Push-Url"]
    assert "tab=" not in resp.headers["HX-Push-Url"]


def test_multi_season_league_skips_history_when_season_given(monkeypatch):
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season="2024", boot=1)
    assert resp.template.name != "tab_season_history.html"


def test_boot_shell_sync_league_box_keeps_league_field_name(monkeypatch):
    """Regression test for two real, shipped bugs in sequence on this one
    attribute. (1) _shell_sync.html's out-of-band swap (fired on every
    boot=1 first-panel-load AND every /load response, see _pushed())
    re-rendered #league with a stale name="league" while index.html's own
    box had briefly been renamed to "q" for the new single-box /lookup
    search -- since this swap REPLACES the box wholesale, it silently
    reverted the live page's field name on every view, so every search
    submitted an empty query string. (2) Renaming this OOB copy to "q" to
    match then broke every OTHER consumer of #league's value (#panel's boot
    fetch, the .tabs nav), both of which hx-include #league by id expecting
    it to serialize as `league=` -- so every /tab/* request silently fell
    back to DEFAULT_LEAGUE, and clicking a league link from the user-search
    results always landed on the same (wrong) league regardless of which
    was clicked. The fix keeps this input's name as "league" for those other
    consumers; index.html's own /lookup submit handler builds its request by
    hand instead of relying on form serialization. Assert directly on the
    rendered OOB fragment rather than only on the route's context, since
    both bugs were purely in template markup and invisible to a
    context-only check."""
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season="2024", boot=1)
    body = resp.body.decode()
    assert 'name="league" id="league"' in body
    assert 'name="q" id="league"' not in body


def test_single_season_league_never_shows_history(monkeypatch):
    s = make_season(season="2025")
    d = {"playoffs": {}, "names": ["2025"], "seasons": {"2025": s}}
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season=None, boot=1)
    assert resp.template.name != "tab_season_history.html"


def test_history_only_applies_to_the_boot_fetch(monkeypatch):
    """Without `boot`, this is an in-tab request (e.g. clicking to a
    different tab within an already-loaded league); the season was already
    resolved once at boot, so it must never re-surface the interstitial."""
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.tab("overview", _Req(), league="123", season=None, boot=0)
    assert resp.template.name != "tab_season_history.html"


def test_season_history_rows_flags_the_current_season():
    """`current_season` marks whichever row is actually being viewed right
    now -- only meaningful for the on-demand /seasons reopen; the boot-time
    interstitial (no `current_season` passed) never sets it, since nothing
    has been chosen yet."""
    d = _multi_season_d()
    rows = app._season_history_rows(d, current_season="2024")
    by_season = {r["season"]: r for r in rows}
    assert by_season["2024"]["is_current"] is True
    assert by_season["2025"]["is_current"] is False

    rows_no_current = app._season_history_rows(d)
    assert all(r["is_current"] is False for r in rows_no_current)


def test_seasons_route_renders_history_with_current_flagged(monkeypatch):
    """GET /seasons is what the header subtitle opens -- reopens the
    season-history list for an ALREADY-loaded league, independent of `boot`
    (unlike tab()'s own interstitial branch, this route has no boot gate at
    all: it's meant to be reachable any time)."""
    d = _multi_season_d()
    _mock_pick(monkeypatch, d)

    resp = app.seasons_history(_Req(), league="123", season="2024")
    assert resp.template.name == "tab_season_history.html"
    ctx = resp.context
    by_season = {r["season"]: r for r in ctx["history"]}
    assert by_season["2024"]["is_current"] is True
    assert by_season["2025"]["is_current"] is False
    # Same bookmarkable shape as the boot-time interstitial: bare
    # /dashboard?league=X, no season/tab -- see test_history_page_push_url_
    # has_no_season_or_tab for why that distinction matters.
    assert resp.headers["HX-Push-Url"] == "/dashboard?league=123"


def test_seasons_route_bad_league_degrades_to_message(monkeypatch):
    """A typo'd/unreachable league id is a normal thing to hit from the
    header subtitle -- same tolerant-failure contract as /load, a message in
    the panel rather than a 500."""
    def _boom(league, season, fresh=False):
        raise RuntimeError("boom")
    monkeypatch.setattr(app, "pick", _boom)

    resp = app.seasons_history(_Req(), league="bad-id")
    assert resp.status_code == 200
    assert b"season history" in resp.body.lower() or b"try again" in resp.body.lower()
