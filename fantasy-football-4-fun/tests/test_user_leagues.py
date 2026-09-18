"""Network-free tests for the /user-leagues route: the user-id search must
be season-agnostic (sweeps every season regardless of any season input) and
must group a real league's per-season league_ids into one row, redirecting
to the last season the user was actually in it. Follows the direct-call
convention test_player_page.py/test_nflref.py use for other page routes --
no ASGI/TestClient layer, just a minimal fake Request and a call straight
into the route function.
"""
from __future__ import annotations

import pytest

from webapp import app


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def _lg(league_id, season, prev=None, name="Dank Soupers", status="complete",
        total_rosters=10, avatar=None):
    return {"league_id": league_id, "season": season, "previous_league_id": prev,
            "name": name, "status": status, "total_rosters": total_rosters,
            "avatar": avatar}


def test_group_leagues_by_chain_links_across_seasons():
    """A league linked 2023 -> 2024 -> 2025 via previous_league_id collapses
    to one group listing all three years, even though each year has its own
    league_id (the real shape this bug report was about)."""
    raw_by_season = {
        "2025": [_lg("L25", "2025", prev="L24")],
        "2024": [_lg("L24", "2024", prev="L23")],
        "2023": [_lg("L23", "2023", prev=None)],
        "2022": [],
    }
    groups = app._group_leagues_by_chain(raw_by_season)
    assert len(groups) == 1
    g = groups[0]
    assert set(g["seasons"]) == {"2023", "2024", "2025"}
    assert g["latest_season"] == "2025"
    assert g["latest_league"]["league_id"] == "L25"


def test_group_leagues_by_chain_separates_unrelated_leagues():
    raw_by_season = {
        "2025": [_lg("A25", "2025", prev=None, name="League A"),
                  _lg("B25", "2025", prev=None, name="League B")],
    }
    groups = app._group_leagues_by_chain(raw_by_season)
    assert len(groups) == 2
    names = {g["latest_league"]["name"] for g in groups}
    assert names == {"League A", "League B"}


def test_group_leagues_by_chain_historical_only_league_redirects_to_last_season():
    """A user who was in a league in 2022-2023 but not since: the group's
    latest_season is 2023 (their last real season in it), not the league's
    own current season -- since a later season never appeared in this user's
    per-season sweep at all, there is nothing newer to (wrongly) redirect
    to."""
    raw_by_season = {
        "2025": [],
        "2024": [],
        "2023": [_lg("L23", "2023", prev="L22", status="complete")],
        "2022": [_lg("L22", "2022", prev=None, status="complete")],
    }
    groups = app._group_leagues_by_chain(raw_by_season)
    assert len(groups) == 1
    g = groups[0]
    assert g["latest_season"] == "2023"
    assert g["latest_league"]["league_id"] == "L23"
    assert g["current"] is False


def test_group_leagues_by_chain_current_member_flag():
    raw_by_season = {
        "2026": [_lg("L26", "2026", prev="L25", status="in_season")],
        "2025": [_lg("L25", "2025", prev=None, status="complete")],
    }
    groups = app._group_leagues_by_chain(raw_by_season)
    g = groups[0]
    assert g["latest_season"] == "2026"
    assert g["current"] is True


def test_user_leagues_route_ignores_season_param_and_sweeps_all(monkeypatch):
    """The route takes no `season` query param at all -- the search is keyed
    on the user handle alone, regardless of whatever season a caller's form
    happens to still submit (the header form's season selector rides along
    even in User mode; FastAPI drops params the route doesn't declare)."""
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "656711573536088064", "display_name": "LuckyHarm",
        "username": "luckyharm", "avatar": None})
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    calls = []

    def _fake_many(paths):
        calls.extend(paths)
        out = []
        for p in paths:
            if p.endswith("/2025"):
                out.append([_lg("L25", "2025", prev=None)])
            else:
                out.append([])
        return out

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", _fake_many)

    resp = app.user_leagues(_Req(), user="luckyharm")
    assert resp.template.name == "_user_leagues.html"
    ctx = resp.context
    assert ctx["leagues"], "a league found only in 2025 must still surface"
    assert ctx["leagues"][0]["years"] == "2025"
    # Swept the full 8-season range, not just one season.
    assert len(calls) == 8


def test_user_leagues_link_is_a_real_query_string(monkeypatch):
    """Regression test for a real bug: the row link used to be built as
    `/league=<id>&season=<year>` with no `?` before `season` -- since
    /league={league} is a PATH route, the whole "&season=..." tail was
    silently swallowed into the {league} path segment itself instead of
    becoming a query param, so clicking a league loaded a garbage id and
    never passed a season at all ("the live redirect... is not working").
    The fix routes through /dashboard's query-string form instead, the same
    shape tab_season_history.html/tab_testing.html already use. Renders the
    real template (not just the route's context) since the bug was purely in
    the markup, invisible to a context-only assertion."""
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "656711573536088064", "display_name": "LuckyHarm",
        "username": "luckyharm", "avatar": None})
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    import sleepermetrics.api as sm_api

    def _fake_many(paths):
        return [[_lg("L25", "2025", prev=None)] if p.endswith("/2025") else []
                for p in paths]
    monkeypatch.setattr(sm_api, "sleeper_api_many", _fake_many)

    resp = app.user_leagues(_Req(), user="luckyharm")
    body = resp.body.decode()
    assert 'href="/dashboard?league=L25&season=2025&tab=overview"' in body
    assert "/league=L25&season=2025" not in body


def test_user_leagues_route_no_leagues_found(monkeypatch):
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "1", "display_name": "Nobody", "username": "nobody", "avatar": None})
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", lambda paths: [[] for _ in paths])

    resp = app.user_leagues(_Req(), user="nobody")
    assert resp.context["leagues"] == []


def test_user_leagues_route_blank_handle():
    resp = app.user_leagues(_Req(), user="   ")
    assert "error" in resp.context
