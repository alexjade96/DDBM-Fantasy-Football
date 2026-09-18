"""Network-free tests for the /player/{player_id} route and its template
(player-profile Phase 2). Follows the same direct-call convention
test_nflref.py uses for other page routes -- no ASGI/TestClient layer, just
a minimal fake Request and a call straight into the route function.
"""
from __future__ import annotations

import pandas as pd
import pytest

from webapp import app, player_profile as pp


class _Req:
    """Minimal stand-in for starlette's Request -- TemplateResponse only
    needs `.scope` / attribute access."""
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    pp.clear_profile_cache()
    yield
    pp.clear_profile_cache()


@pytest.fixture
def _fake_profile(monkeypatch):
    """Stub webapp.player_profile.player_profile itself, so this test file
    exercises only the route + template, not the aggregator (that's
    test_player_profile.py's job). Everything here is dated "2025" and
    `current_season` is set to match, so the template's current-vs-past
    split (see _build_profile's `_split_current`) puts it all in the
    always-visible "current season" area, matching this fixture's
    historical pre-split shape."""
    def _fake(player_id, league_id=None, fresh=False):
        league_section = None
        league_current = None
        league_past = None
        if league_id:
            league_section = {
                "draft_picks": [{"season": "2025", "round": 4, "pick_in_round": 2,
                                  "user_name": "rezzu", "total": 111.2, "ppg": 6.5,
                                  "pos_steal": 5}],
                "honors": [{"season": "2025", "totw_weeks": 1,
                            "player_of_week_weeks": 0, "managers": ["rezzu"]}],
                "trade_stints": [],
                "waiver_rows": [{"season": "2025", "week": 3, "user_name": "rezzu",
                                  "via": "waiver", "points": 24.1}],
                "roster_splits": {"2025": [{"user_name": "rezzu", "weeks": 9,
                                             "points": 24.1, "ppg": 2.7}]},
            }
            league_current = {
                "draft_picks": league_section["draft_picks"],
                "roster": league_section["roster_splits"]["2025"],
                "trade_stints": [], "waiver_rows": league_section["waiver_rows"],
            }
            league_past = {"draft_picks": [], "roster_splits": {},
                           "trade_stints": [], "waiver_rows": []}
        real_nfl = {
            "player_stats": {
                "rows": [{"player_id": "00-0034975", "player_display_name": "Justice Hill",
                         "position": "RB", "recent_team": "BAL", "season": "2025",
                         "week": 1, "targets": 2}],
                "current_rows": [{"player_id": "00-0034975", "player_display_name": "Justice Hill",
                                  "position": "RB", "recent_team": "BAL", "season": "2025",
                                  "week": 1, "targets": 2}],
                "past_rows": [], "best_effort": False},
            "snap_counts": {
                "rows": [{"pfr_player_id": "X", "player": "Justice Hill",
                         "position": "RB", "season": "2025"}],
                "current_rows": [{"pfr_player_id": "X", "player": "Justice Hill",
                                  "position": "RB", "season": "2025"}],
                "past_rows": [], "best_effort": True},
        }
        adp_history = [{"season": "2025", "sleeper_id": player_id, "consensus": 40.0,
                        "final": 55, "diff": -15.0}]
        return {
            "identity": {"player_id": player_id, "player_name": "Justice Hill",
                         "position": "RB", "team": "BAL", "gsis_id": "00-0034975"},
            "seasons_covered": ["2025", "2024"],
            "real_nfl": real_nfl,
            "adp_history": adp_history,
            "adp_current": adp_history, "adp_past": [],
            "current_season": "2025",
            "league": league_section,
            "league_current": league_current, "league_past": league_past,
        }
    monkeypatch.setattr(pp, "player_profile", _fake)
    return _fake


def test_player_page_without_league(_fake_profile):
    resp = app.player_page(_Req(), player_id="5995", render=1)
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Justice Hill" in body
    assert "RB" in body and "BAL" in body
    assert "Opened without a league" in body
    assert "player_stats" not in body  # dataset KEY never leaks, only its label
    assert "Weekly stats" in body
    assert "best-effort name match" in body  # snap_counts is flagged
    # no league -> the back link's href fallback has no league/season to carry
    assert 'href="/dashboard"' in body


def test_player_page_shows_no_current_season_message_when_only_past_data_exists(monkeypatch):
    """Regression test: `{% set flags.any_real_nfl = true %}` inside the
    Real-NFL history {% for %} loop must actually reach the check AFTER the
    loop (a bare {% set %} there would be scoped to the loop iteration and
    silently reset, always reporting "no data at all" even when past-season
    rows exist -- see player_profile.html's `namespace(...)` comment). A
    player with real data, none of it dated the current season, must show
    the "no data THIS season" message, never the "no data AT ALL" one."""
    monkeypatch.setattr(
        pp, "player_profile",
        lambda player_id, league_id=None, fresh=False: {
            "identity": {"player_id": player_id, "player_name": "Old Timer",
                         "position": "RB", "team": "BAL", "gsis_id": "00-1"},
            "seasons_covered": ["2026", "2025", "2024"],
            "real_nfl": {
                "player_stats": {
                    "rows": [{"season": "2024", "week": 1}],
                    "current_rows": [], "past_rows": [{"season": "2024", "week": 1}],
                    "best_effort": False},
            },
            "adp_history": [], "adp_current": [], "adp_past": [],
            "current_season": "2026",
            "league": None, "league_current": None, "league_past": None,
        })
    resp = app.player_page(_Req(), player_id="5995", render=1)
    body = resp.body.decode()
    assert "No real-NFL data found for this player in 2026 -- see past seasons below." in body
    assert "No real-NFL data found for this player over" not in body
    assert "past seasons (1 rows)" in body


def test_player_page_back_link_carries_league_and_season(monkeypatch, _fake_profile):
    monkeypatch.setattr(
        app, "pick",
        lambda league, season: (
            {"resolved_league_id": "999"},
            type("S", (), {"name": "Test League"})(),
            season or "2025",
        ))
    resp = app.player_page(_Req(), player_id="5995", league="123", season="2025", render=1)
    body = resp.body.decode()
    assert 'href="/dashboard?league=999&season=2025"' in body


def test_player_page_with_league(monkeypatch, _fake_profile):
    monkeypatch.setattr(
        app, "pick",
        lambda league, season: (
            {"resolved_league_id": league},
            type("S", (), {"name": "Test League"})(),
            season or "2025",
        ))
    resp = app.player_page(_Req(), player_id="5995", league="123", season="2025", render=1)
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Test League" in body
    # This season's (2025) roster/waiver activity is shown directly, no
    # expansion needed -- "Roster history by season" is the PAST-seasons
    # heading (see _split_current), which doesn't apply here since this
    # fixture's data is all dated the current season.
    assert "rezzu" in body
    assert "Waiver / free-agent activity" in body
    assert "Roster history by season" not in body


def test_player_page_league_pick_failure_degrades_to_no_league(monkeypatch, _fake_profile):
    def _boom(league, season):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(app, "pick", _boom)
    resp = app.player_page(_Req(), player_id="5995", league="bad_league", render=1)
    assert resp.status_code == 200
    body = resp.body.decode()
    # a failed pick() must not crash the page -- falls back to no-league view
    assert "Opened without a league" in body


def test_player_page_unknown_player_renders_short_page(monkeypatch):
    monkeypatch.setattr(
        pp, "player_profile",
        lambda player_id, league_id=None, fresh=False: {
            "identity": {"player_id": player_id, "player_name": None,
                         "position": None, "team": None, "gsis_id": None},
            "seasons_covered": [], "real_nfl": {}, "adp_history": [],
            "league": None,
        })
    resp = app.player_page(_Req(), player_id="999999999", render=1)
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Unknown player" in body
    assert "No Sleeper record found" in body


def test_player_page_refresh_param_forces_fresh_rebuild(monkeypatch):
    calls = []

    def _fake(player_id, league_id=None, fresh=False):
        calls.append(fresh)
        return {
            "identity": {"player_id": player_id, "player_name": "X",
                         "position": None, "team": None, "gsis_id": None},
            "seasons_covered": [], "real_nfl": {}, "adp_history": [],
            "league": None,
        }
    monkeypatch.setattr(pp, "player_profile", _fake)
    app.player_page(_Req(), player_id="5995", refresh=1, render=1)
    assert calls == [True]


# --- loading page (cold vs. warm) ------------------------------------------

def test_player_page_cold_shows_loader_not_the_real_page(_fake_profile):
    """A cold request (nothing cached yet) must return the instant loading
    page, not pay the full aggregation cost inline -- a real page
    navigation has no elapsed-time indicator the way an htmx tab switch
    does, so a slow inline render would look like a hung/blank page."""
    resp = app.player_page(_Req(), player_id="5995")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Loading player profile" in body
    assert "location.replace" in body
    assert "/player/5995?render=1" in body


def test_player_page_loader_carries_league_season_refresh(_fake_profile):
    resp = app.player_page(_Req(), player_id="5995", league="123",
                           season="2025", refresh=1)
    body = resp.body.decode()
    assert "Loading player profile" in body
    assert "league=123" in body
    assert "season=2025" in body
    assert "refresh=1" in body


def test_player_page_warm_cache_skips_loader(monkeypatch, _fake_profile):
    """Once a profile is cached, a plain (non-render=1) request should
    render straight through -- the loader-then-redirect round trip is only
    for the cold case, so a warm hit shouldn't pay it."""
    monkeypatch.setattr(pp, "is_cached", lambda player_id, league_id=None: True)
    resp = app.player_page(_Req(), player_id="5995")
    body = resp.body.decode()
    assert "Loading player profile" not in body
    assert "Justice Hill" in body


def test_player_page_refresh_shows_loader_even_when_warm(monkeypatch, _fake_profile):
    """refresh=1 must force the loader (and the eventual fresh=True
    rebuild) even when a cached copy already exists -- it's an explicit
    request to discard the cache, not just a normal warm view."""
    monkeypatch.setattr(pp, "is_cached", lambda player_id, league_id=None: True)
    resp = app.player_page(_Req(), player_id="5995", refresh=1)
    body = resp.body.decode()
    assert "Loading player profile" in body
    assert "refresh=1" in body


# --- season pills / htmx percentile swap ------------------------------------

@pytest.fixture
def _fake_profile_with_seasons(monkeypatch):
    """Two seasons of percentile data, keyed for the season-overlay radar --
    the shape player_percentile_part() reads (season_profiles/
    available_seasons/focus_season), distinct from _fake_profile's league-
    history-focused fixture above."""
    def _profile(season, pct):
        return {"season": season, "position": "RB", "player_id": "5995",
               "n_population": 40,
               "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                           "value": 180.0, "percentile": pct}]}

    def _fake(player_id, league_id=None, fresh=False):
        season_profiles = {"2024": _profile("2024", 40.0), "2025": _profile("2025", 72.0)}
        return {
            "identity": {"player_id": player_id, "player_name": "Justice Hill",
                         "position": "RB", "team": "BAL", "gsis_id": "00-0034975"},
            "seasons_covered": ["2025", "2024"],
            "real_nfl": {}, "adp_history": [], "league": None,
            "percentile_profile": season_profiles["2025"],
            "season_profiles": season_profiles,
            "available_seasons": ["2025", "2024"],
            "focus_season": "2025",
        }
    monkeypatch.setattr(pp, "player_profile", _fake)
    return _fake


def test_player_page_renders_season_pills_as_htmx_buttons(_fake_profile_with_seasons):
    resp = app.player_page(_Req(), player_id="5995", render=1)
    body = resp.body.decode()
    assert '<button type="button" class="year on"' in body
    assert 'hx-get="/player/5995/percentile?focus=2025' in body
    assert 'hx-get="/player/5995/percentile?focus=2024' in body
    assert 'hx-target="#percentile-section"' in body
    # the pills, chart and table all live inside one swappable container
    assert '<div id="percentile-section">' in body


def test_player_percentile_part_switches_focus_season(_fake_profile_with_seasons):
    resp = app.player_percentile_part(_Req(), player_id="5995", focus="2024")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Percentile profile" in body and "(2024)" in body
    # the newly-focused pill is marked .on, the other is not
    assert '<button type="button" class="year on"\n     hx-get="/player/5995/percentile?focus=2024' in body
    assert '<button type="button" class="year"\n     hx-get="/player/5995/percentile?focus=2025' in body


def test_player_percentile_part_falls_back_to_default_focus_on_unknown_season(
        _fake_profile_with_seasons):
    """An unresolvable `focus` (stale bookmark, tampered query string) must
    not 500 or silently show blank data -- it degrades to the profile's own
    default focus season, same contract player_page() already has."""
    resp = app.player_percentile_part(_Req(), player_id="5995", focus="1999")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "(2025)" in body


def test_nflstats_table_links_only_rows_with_a_resolved_sleeper_id(monkeypatch):
    """The NFL Stats tab is the Phase-2 link's first wiring point -- a row
    WITH a resolved sleeper_id must link to /player/<id>; a row without one
    must render plain text, never a link to a page that would just show
    "no Sleeper record found". Mirrors test_nflref.py's own
    test_nflstats_players_row_has_portrait fixture pattern (patch
    identity._raw_players directly, not just sleeper_api -- see that
    fixture's own docstring for why a same-day on-disk pickle otherwise
    silently bypasses a sleeper_api-only stub)."""
    from webapp.app import nflstats_data
    from webapp.sources.ffadp import identity
    from webapp.sources.nflref import api

    monkeypatch.setattr(identity, "_raw_players", lambda: {
        "4262921": {"full_name": "Ja'Marr Chase", "position": "WR", "team": "CIN"},
    })
    identity._idx = None

    df = pd.DataFrame([
        {"player_id": "00-0036900", "player_display_name": "Ja'Marr Chase",
         "position": "WR", "recent_team": "CIN", "season": 2024, "week": 1,
         "season_type": "REG", "targets": 12, "receptions": 9,
         "receiving_yards": 120, "fantasy_points_ppr": 21.0},
        {"player_id": "00-0000000", "player_display_name": "Totally Unresolvable Player",
         "position": "WR", "recent_team": "SF", "season": 2024, "week": 1,
         "season_type": "REG", "targets": 1, "receptions": 1,
         "receiving_yards": 5, "fantasy_points_ppr": 1.0},
    ])
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: df)

    # reload=True is required to actually exercise the mock: `load()`
    # (nflref/board.py) is snapshot-first, and a real committed
    # data/sources/nflverse/player_stats/2024.parquet already exists on
    # disk with ~200 real rows -- without reload=True this test would
    # silently read THAT file instead of the fake df above (a real latent
    # gap also present in test_nflref.py's own
    # test_nflstats_players_row_has_portrait, which happens to still pass
    # only because its one row's player also exists for real in that
    # snapshot; not fixed here since it's a pre-existing test, out of scope
    # for this route-wiring test).
    resp = nflstats_data(_Req(), view="players", season="2024",
                         pos="WR", source="nflverse", reload=True)
    body = resp.body.decode()
    assert "/player/4262921" in body       # resolved row IS a link
    assert "Totally Unresolvable Player" in body  # unresolved row still renders
    # the profile is meant to be a side reference, not a navigate-away --
    # opens in a new tab rather than replacing the tab the click came from
    assert 'target="_blank"' in body
    identity._idx = None
