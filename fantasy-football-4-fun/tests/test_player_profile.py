"""Network-free tests for webapp.player_profile -- the single-player
aggregator (player-profile Phase 1). Every external call this module makes
(sleepermetrics.players, nflref.board.load, ffadp.board.combine,
draft/metrics functions, webapp.app.league_data) is monkeypatched at its own
module boundary, matching the convention test_ffadp.py/test_nflref.py use.
"""
from __future__ import annotations

import pandas as pd
import pytest

from webapp import player_profile as pp


# --- _norm_name --------------------------------------------------------

def test_norm_name_strips_punctuation_and_suffix():
    assert pp._norm_name("Ja'Marr Chase") == "jamarr chase"
    assert pp._norm_name("Odell Beckham Jr.") == "odell beckham"
    assert pp._norm_name(None) == ""


# --- _recent_seasons -----------------------------------------------------

def test_recent_seasons_uses_nfl_state(monkeypatch):
    # sleepermetrics/__init__.py does `from .league import league`, which
    # rebinds the `league` NAME in the package namespace to that FUNCTION --
    # so `sleepermetrics.league` (attribute access) resolves to the
    # function, not the `league` submodule, even via `import
    # sleepermetrics.league as x`. sys.modules still holds the real module
    # (Python's import machinery keys it there regardless), so pull it from
    # there instead of through attribute access.
    import sys
    league_mod = sys.modules["sleepermetrics.league"]
    monkeypatch.setattr(
        league_mod, "nfl_state", lambda: {"league_season": "2026"})
    assert pp._recent_seasons(3) == ["2026", "2025", "2024"]


def test_recent_seasons_falls_back_on_network_failure(monkeypatch):
    import sys
    league_mod = sys.modules["sleepermetrics.league"]

    def _boom():
        raise RuntimeError("network access blocked in tests")
    monkeypatch.setattr(league_mod, "nfl_state", _boom)
    out = pp._recent_seasons(3)
    assert len(out) == 3
    assert all(isinstance(y, str) for y in out)


# --- _player_identity ------------------------------------------------------

def _fake_players_df():
    return pd.DataFrame([
        {"player_id": "5995", "player_name": "Justice Hill", "position": "RB",
         "team": "BAL", "gsis_id": " 00-0034975"},  # stray leading space
        {"player_id": "7564", "player_name": "Ja'Marr Chase", "position": "WR",
         "team": "CIN", "gsis_id": None},
    ])


def test_player_identity_strips_padded_gsis_id(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("5995")
    assert ident["player_name"] == "Justice Hill"
    assert ident["gsis_id"] == "00-0034975"  # stray space stripped


def test_player_identity_handles_missing_gsis(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("7564")
    assert ident["gsis_id"] is None


def test_player_identity_unknown_player_id(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("999999")
    assert ident["player_id"] == "999999"
    assert ident["player_name"] is None


# --- _real_nfl_history -----------------------------------------------------

def test_real_nfl_history_matches_gsis_and_name_fallback(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "player_stats":
            return pd.DataFrame([
                {"player_id": "00-0034975", "player_display_name": "Justice Hill",
                 "position": "RB", "season": season},
                {"player_id": "00-0000000", "player_display_name": "Someone Else",
                 "position": "RB", "season": season},
            ])
        if dataset == "pfr_rush":
            return pd.DataFrame([
                {"pfr_player_id": "HillJu00", "pfr_player_name": "Justice Hill",
                 "position": "RB", "season": season},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = pp._real_nfl_history("00-0034975", "Justice Hill", "RB", ["2025"])
    assert len(out["player_stats"]["rows"]) == 1
    assert out["player_stats"]["best_effort"] is False
    assert len(out["pfr_rush"]["rows"]) == 1
    assert out["pfr_rush"]["best_effort"] is True
    # a dataset with no matching rows still reports the (empty) shape
    assert out["injuries"] == {"rows": [], "best_effort": False}


def test_real_nfl_history_no_gsis_id_still_tries_name_fallback(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "snap_counts":
            return pd.DataFrame([
                {"pfr_player_id": "X", "player": "Nobody Special",
                 "position": "RB", "season": season},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = pp._real_nfl_history(None, "Nobody Special", "RB", ["2025"])
    # gsis-bridged datasets get nothing without a gsis_id
    assert out["player_stats"]["rows"] == []
    # name-fallback datasets still work without one
    assert len(out["snap_counts"]["rows"]) == 1


def test_real_nfl_history_degrades_on_nflref_import_failure(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if "nflref" in name:
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert pp._real_nfl_history("00-0034975", "X", "RB", ["2025"]) == {}


# --- _adp_history ------------------------------------------------------

def test_adp_history_filters_to_one_player(monkeypatch):
    def _fake_combine(season, scoring="ppr", **kw):
        return {"rows": [
            {"sleeper_id": "5995", "player": "Justice Hill", "consensus": 40.0},
            {"sleeper_id": "7564", "player": "Ja'Marr Chase", "consensus": 1.0},
        ]}

    import webapp.sources.ffadp.board as ffadp_board
    monkeypatch.setattr(ffadp_board, "combine", _fake_combine)

    out = pp._adp_history("5995", ["2025", "2024"])
    assert len(out) == 2
    assert all(r["sleeper_id"] == "5995" for r in out)
    assert out[0]["season"] == "2025"


def test_adp_history_skips_seasons_with_no_match(monkeypatch):
    def _fake_combine(season, scoring="ppr", **kw):
        return {"rows": [{"sleeper_id": "7564", "player": "Someone Else"}]}

    import webapp.sources.ffadp.board as ffadp_board
    monkeypatch.setattr(ffadp_board, "combine", _fake_combine)

    assert pp._adp_history("5995", ["2025"]) == []


# --- _league_history / player_profile (end to end, all sources stubbed) ----

def test_league_history_degrades_when_no_league_data(monkeypatch):
    out = pp._league_history("5995", {})
    assert out == {
        "draft_picks": [], "honors": [], "trade_stints": [],
        "waiver_rows": [], "roster_splits": {},
    }


def test_player_profile_without_league_id_has_no_league_section(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2025"])

    out = pp.player_profile("5995")
    assert out["identity"]["player_name"] == "Justice Hill"
    assert out["league"] is None


def test_player_profile_with_league_id_builds_league_section(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])

    fake_season = object()  # never inspected directly -- draft/metrics are stubbed
    monkeypatch.setattr(
        "webapp.app.league_data",
        lambda league_id: {"seasons": {"2025": fake_season}})
    monkeypatch.setattr(
        "sleepermetrics.draft.draft_board",
        lambda s: pd.DataFrame([{"player_id": "5995", "round": 4,
                                  "pick_in_round": 2, "user_name": "rezzu"}]))
    monkeypatch.setattr(
        "sleepermetrics.metrics.player_honors",
        lambda s: [{"player_id": "5995", "managers": {"rezzu"}}])
    monkeypatch.setattr(
        "sleepermetrics.metrics.trade_player_rates", lambda s: [])
    monkeypatch.setattr(
        "sleepermetrics.metrics.waiver_ledger",
        lambda s, top_n=None: pd.DataFrame(
            [{"player_id": "5995", "user_name": "rezzu", "points": 24.1}]))
    monkeypatch.setattr(
        "sleepermetrics.draft._player_team_splits",
        lambda s, ids: {"5995": [{"user_name": "rezzu", "points": 24.1}]})

    out = pp.player_profile("5995", league_id="fake_league")
    lg = out["league"]
    assert len(lg["draft_picks"]) == 1 and lg["draft_picks"][0]["season"] == "2025"
    assert len(lg["honors"]) == 1 and lg["honors"][0]["managers"] == ["rezzu"]
    assert len(lg["waiver_rows"]) == 1
    assert lg["roster_splits"] == {"2025": [{"user_name": "rezzu", "points": 24.1}]}
    # league seasons should widen seasons_covered even past the default window
    assert "2025" in out["seasons_covered"]


def test_player_profile_league_section_degrades_on_league_data_failure(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])

    def _boom(league_id):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr("webapp.app.league_data", _boom)

    out = pp.player_profile("5995", league_id="fake_league")
    # a failed league_data() call should not crash the whole profile --
    # league section comes back as the all-empty shape, not None, since
    # league_id WAS given (None means "no league_id passed" specifically)
    assert out["league"] == {
        "draft_picks": [], "honors": [], "trade_stints": [],
        "waiver_rows": [], "roster_splits": {},
    }
