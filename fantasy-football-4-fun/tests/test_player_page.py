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
    test_player_profile.py's job)."""
    def _fake(player_id, league_id=None, fresh=False):
        league_section = None
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
        return {
            "identity": {"player_id": player_id, "player_name": "Justice Hill",
                         "position": "RB", "team": "BAL", "gsis_id": "00-0034975"},
            "seasons_covered": ["2025", "2024"],
            "real_nfl": {
                "player_stats": {"rows": [
                    {"player_id": "00-0034975", "player_display_name": "Justice Hill",
                     "position": "RB", "recent_team": "BAL", "season": "2025",
                     "week": 1, "targets": 2},
                ], "best_effort": False},
                "snap_counts": {"rows": [
                    {"pfr_player_id": "X", "player": "Justice Hill",
                     "position": "RB", "season": "2025"},
                ], "best_effort": True},
            },
            "adp_history": [
                {"season": "2025", "sleeper_id": player_id, "consensus": 40.0,
                 "final": 55, "diff": -15.0},
            ],
            "league": league_section,
        }
    monkeypatch.setattr(pp, "player_profile", _fake)
    return _fake


def test_player_page_without_league(_fake_profile):
    resp = app.player_page(_Req(), player_id="5995")
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


def test_player_page_back_link_carries_league_and_season(monkeypatch, _fake_profile):
    monkeypatch.setattr(
        app, "pick",
        lambda league, season: (
            {"resolved_league_id": "999"},
            type("S", (), {"name": "Test League"})(),
            season or "2025",
        ))
    resp = app.player_page(_Req(), player_id="5995", league="123", season="2025")
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
    resp = app.player_page(_Req(), player_id="5995", league="123", season="2025")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Test League" in body
    assert "Roster history by season" in body
    assert "rezzu" in body
    assert "Waiver / free-agent activity" in body


def test_player_page_league_pick_failure_degrades_to_no_league(monkeypatch, _fake_profile):
    def _boom(league, season):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(app, "pick", _boom)
    resp = app.player_page(_Req(), player_id="5995", league="bad_league")
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
    resp = app.player_page(_Req(), player_id="999999999")
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
    app.player_page(_Req(), player_id="5995", refresh=1)
    assert calls == [True]


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
