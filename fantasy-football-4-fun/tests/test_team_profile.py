"""Network-free tests for webapp.team_profile -- the single-team aggregator.
Every external call this module makes (nflref.summary.player_leaderboard/
schedule_grid, nflref.board.load, sleepermetrics.league.nfl_state) is
monkeypatched at its own module boundary, matching the convention
test_player_profile.py/test_nflref.py already use.
"""
from __future__ import annotations

import pathlib

import pandas as pd
import pytest

from webapp import team_profile as tp

try:
    from webapp.app import tpl as _tpl
except Exception:  # pragma: no cover -- app.py import chain unavailable in some envs
    _tpl = None


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    tp.clear_profile_cache()
    yield
    tp.clear_profile_cache()


# --- _clean_records -----------------------------------------------------------

def test_clean_records_converts_nan_to_none():
    df = pd.DataFrame([{"week": 1, "score": 24.0}, {"week": 2, "score": float("nan")}])
    out = tp._clean_records(df)
    assert out[0]["score"] == 24.0
    assert out[1]["score"] is None


def test_clean_records_leaves_real_values_and_none_alone():
    df = pd.DataFrame([{"a": 1, "b": "x", "c": None}])
    out = tp._clean_records(df)
    assert out == [{"a": 1, "b": "x", "c": None}]


def test_clean_records_empty_frame():
    assert tp._clean_records(pd.DataFrame()) == []


# --- _current_season / _recent_seasons --------------------------------------

def test_current_season_uses_nfl_state(monkeypatch):
    import sys
    league_mod = sys.modules["sleepermetrics.league"]
    monkeypatch.setattr(league_mod, "nfl_state", lambda: {"league_season": "2026"})
    assert tp._current_season() == "2026"


def test_current_season_falls_back_on_network_failure(monkeypatch):
    import sys
    league_mod = sys.modules["sleepermetrics.league"]

    def _boom():
        raise RuntimeError("network access blocked in tests")
    monkeypatch.setattr(league_mod, "nfl_state", _boom)
    assert isinstance(tp._current_season(), str)


def test_recent_seasons_counts_back_from_current(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2026")
    assert tp._recent_seasons(3) == ["2026", "2025", "2024"]


# --- _team_identity ----------------------------------------------------------

def test_team_identity_normalises_and_validates(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "TEAMS", ("ALL", "SF", "DAL"))
    ident = tp._team_identity(" sf ")
    assert ident == {"abbr": "SF", "known": True}


def test_team_identity_unknown_abbreviation(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "TEAMS", ("ALL", "SF", "DAL"))
    ident = tp._team_identity("ZZZ")
    assert ident == {"abbr": "ZZZ", "known": False}


def test_team_identity_degrades_when_nflref_unavailable(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if "nflref" in name:
            raise ImportError("simulated")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)

    ident = tp._team_identity("SF")
    assert ident["abbr"] == "SF"
    assert ident["known"] is None  # unable to check, not claimed unknown


# --- _roster_leaderboard ------------------------------------------------------

def test_roster_leaderboard_delegates_to_nflref(monkeypatch):
    calls = []

    def _fake_leaderboard(season, pos="ALL", source="nflverse", team="ALL", limit=200):
        calls.append((season, pos, source, team, limit))
        return pd.DataFrame([{"rank": 1, "player": "Brock Purdy", "position": "QB",
                              "fpts_ppr": 300.0, "ppg_ppr": 20.0}])

    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "player_leaderboard", _fake_leaderboard)

    out = tp._roster_leaderboard("SF", "2025")
    assert len(out) == 1
    assert calls == [("2025", "ALL", "sleeper", "SF", 100)]


def test_roster_leaderboard_degrades_on_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("simulated failure")
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "player_leaderboard", _boom)
    assert tp._roster_leaderboard("SF", "2025") == []


def test_roster_leaderboard_empty_frame(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "player_leaderboard",
                        lambda *a, **k: pd.DataFrame())
    assert tp._roster_leaderboard("SF", "2025") == []


def test_roster_leaderboard_scrubs_nan_stats_to_none(monkeypatch):
    df = pd.DataFrame([
        {"rank": 1, "player": "Brock Purdy", "position": "QB", "fpts_ppr": 300.0, "ppg_ppr": 20.0},
        {"rank": 2, "player": "Backup QB", "position": "QB", "fpts_ppr": float("nan"), "ppg_ppr": float("nan")},
    ])
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "player_leaderboard", lambda *a, **k: df)
    out = tp._roster_leaderboard("SF", "2025")
    assert out[1]["fpts_ppr"] is None
    assert out[1]["ppg_ppr"] is None


# --- _roster_by_position -----------------------------------------------------

def test_roster_by_position_orders_canonically():
    roster = [
        {"player": "A", "position": "WR"},
        {"player": "B", "position": "QB"},
        {"player": "C", "position": "RB"},
        {"player": "D", "position": "WR"},
        {"player": "E", "position": "DEF"},
    ]
    out = tp._roster_by_position(roster)
    assert [g["position"] for g in out] == ["QB", "RB", "WR", "DEF"]
    wr = next(g for g in out if g["position"] == "WR")
    assert [p["player"] for p in wr["players"]] == ["A", "D"]  # rank order preserved


def test_roster_by_position_absent_position_not_rendered():
    roster = [{"player": "A", "position": "QB"}]
    out = tp._roster_by_position(roster)
    assert [g["position"] for g in out] == ["QB"]  # no empty RB/WR/... groups


def test_roster_by_position_unknown_position_goes_to_extra_bucket():
    roster = [{"player": "A", "position": "QB"}, {"player": "B", "position": None}]
    out = tp._roster_by_position(roster)
    assert [g["position"] for g in out] == ["QB", "Other"]


def test_roster_by_position_empty_roster():
    assert tp._roster_by_position([]) == []


# --- _split_snap_counts --------------------------------------------------------

def test_split_snap_counts_buckets_by_nonzero_pct():
    rows = [
        {"player": "Deebo Samuel", "position": "WR", "offense_snaps": 60,
         "offense_pct": 0.92, "defense_snaps": 0, "defense_pct": 0.0,
         "st_snaps": 5, "st_pct": 0.15},
        {"player": "Fred Warner", "position": "LB", "offense_snaps": 0,
         "offense_pct": 0.0, "defense_snaps": 65, "defense_pct": 0.98,
         "st_snaps": 0, "st_pct": 0.0},
    ]
    out = tp._split_snap_counts(rows)
    assert [r["player"] for r in out["offense"]] == ["Deebo Samuel"]
    assert [r["player"] for r in out["defense"]] == ["Fred Warner"]
    assert [r["player"] for r in out["special_teams"]] == ["Deebo Samuel"]


def test_split_snap_counts_trims_other_buckets_columns():
    rows = [{"player": "X", "position": "WR", "offense_snaps": 60,
             "offense_pct": 0.92, "defense_snaps": 0, "defense_pct": 0.0,
             "st_snaps": 5, "st_pct": 0.15}]
    out = tp._split_snap_counts(rows)
    off_row = out["offense"][0]
    assert "offense_pct" in off_row and "offense_snaps" in off_row
    assert "defense_pct" not in off_row and "defense_snaps" not in off_row
    assert "st_pct" not in off_row and "st_snaps" not in off_row
    # identity fields survive the trim
    assert off_row["player"] == "X" and off_row["position"] == "WR"


def test_split_snap_counts_bucket_absent_when_nobody_qualifies():
    rows = [{"player": "X", "offense_pct": 0.5, "defense_pct": 0.0, "st_pct": 0.0}]
    out = tp._split_snap_counts(rows)
    assert list(out.keys()) == ["offense"]  # no "defense"/"special_teams" keys at all


def test_split_snap_counts_treats_none_and_nan_as_not_qualifying():
    import math
    rows = [{"player": "X", "offense_pct": None, "defense_pct": math.nan, "st_pct": 0.4}]
    out = tp._split_snap_counts(rows)
    assert list(out.keys()) == ["special_teams"]


def test_split_snap_counts_empty_input():
    assert tp._split_snap_counts([]) == {}


# --- _split_player_stats --------------------------------------------------------

def _player_stats_row(**overrides):
    """A player_stats row with every volume/rate column zeroed, like a
    real player_stats row for a non-skill player -- overrides supply
    whatever this test actually wants nonzero."""
    row = {
        "player_display_name": "Nobody", "recent_team": "SF", "week": 1, "season": 2025,
        "targets": 0, "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
        "receiving_air_yards": 0, "target_share": 0.0, "air_yards_share": 0.0,
        "wopr": 0.0, "racr": None,
        "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
        "attempts": 0, "completions": 0, "passing_yards": 0, "passing_tds": 0,
        "interceptions": 0, "passing_air_yards": 0, "pacr": None,
        "fantasy_points": 0.0, "fantasy_points_ppr": 0.0,
    }
    row.update(overrides)
    return row


def test_split_player_stats_buckets_by_real_volume():
    rows = [
        _player_stats_row(player_display_name="Kyle Juszczyk", targets=2, receptions=2, receiving_yards=32),
        _player_stats_row(player_display_name="Thomas Morstead"),  # punter -- every volume col 0
        _player_stats_row(player_display_name="Brock Purdy", attempts=30, completions=22,
                          carries=3, rushing_yards=15),  # scrambling QB -- two buckets
    ]
    out = tp._split_player_stats(rows)
    assert [r["player_display_name"] for r in out["receiving"]] == ["Kyle Juszczyk"]
    assert [r["player_display_name"] for r in out["passing"]] == ["Brock Purdy"]
    assert [r["player_display_name"] for r in out["rushing"]] == ["Brock Purdy"]
    assert "Thomas Morstead" not in [r["player_display_name"] for b in out.values() for r in b]


def test_split_player_stats_trims_other_roles_columns():
    rows = [_player_stats_row(player_display_name="X", targets=2, receptions=2, receiving_yards=32)]
    out = tp._split_player_stats(rows)
    rec_row = out["receiving"][0]
    assert "targets" in rec_row and "receiving_yards" in rec_row
    assert "carries" not in rec_row and "attempts" not in rec_row
    # identity/shared columns survive the trim
    assert rec_row["player_display_name"] == "X"
    assert "fantasy_points_ppr" in rec_row


def test_split_player_stats_bucket_absent_when_nobody_qualifies():
    rows = [_player_stats_row(targets=2, receptions=2, receiving_yards=32)]
    out = tp._split_player_stats(rows)
    assert list(out.keys()) == ["receiving"]  # no "passing"/"rushing" keys at all


def test_split_player_stats_treats_none_and_nan_as_not_qualifying():
    import math
    rows = [_player_stats_row(attempts=None, carries=math.nan, targets=3, receptions=1)]
    out = tp._split_player_stats(rows)
    assert list(out.keys()) == ["receiving"]


def test_split_player_stats_empty_input():
    assert tp._split_player_stats([]) == {}


# --- _attach_week_stats -------------------------------------------------------

def test_attach_week_stats_slices_by_week():
    schedule = [{"week": 1}, {"week": 2}]
    team_datasets = {
        "pfr_rush": [{"player": "C", "week": 1}, {"player": "D", "week": 2}],
        "pfr_def": [{"player": "E", "week": 1}],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["stats"] == {"pfr_rush": [{"player": "C", "week": 1}],
                                "pfr_def": [{"player": "E", "week": 1}]}
    assert out[1]["stats"] == {"pfr_rush": [{"player": "D", "week": 2}]}
    assert out[0]["week"] == 1  # original game fields preserved


def test_attach_week_stats_extracts_game_type():
    """game_type (REG/WC/DIV/CON/SB) isn't a schedule_grid() column -- it
    only exists inside the advanced-stat datasets, constant across every
    row of a single game. _attach_week_stats pulls it up onto the game
    dict itself so the template can show it once in the row header instead
    of repeating it per stat row."""
    schedule = [{"week": 1}, {"week": 20}]
    team_datasets = {
        "pfr_def": [
            {"player": "A", "week": 1, "game_type": "REG"},
            {"player": "A", "week": 20, "game_type": "DIV"},
        ],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] == "REG"
    assert out[1]["game_type"] == "DIV"


def test_attach_week_stats_game_type_none_when_no_datasets_carry_it():
    schedule = [{"week": 1}]
    team_datasets = {"pfr_rush": [{"player": "A", "week": 1}]}  # no game_type key
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] is None


def test_attach_week_stats_game_type_none_when_week_missing():
    schedule = [{"week": None}]
    team_datasets = {"pfr_rush": [{"player": "A", "week": 1, "game_type": "REG"}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] is None


def test_attach_week_stats_dataset_absent_when_no_rows_for_week():
    schedule = [{"week": 3}]
    team_datasets = {"pfr_rush": [{"player": "A", "week": 1}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["stats"] == {}  # no pfr_rush key at all, not an empty list


def test_attach_week_stats_handles_missing_week_on_game():
    schedule = [{"week": None}]
    team_datasets = {"pfr_rush": [{"player": "A", "week": 1}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["stats"] == {}


def test_attach_week_stats_empty_inputs():
    assert tp._attach_week_stats([], {}) == []
    assert tp._attach_week_stats([{"week": 1}], {}) == [
        {"week": 1, "stats": {}, "game_type": None}]


def test_attach_week_stats_splits_snap_counts_by_role():
    schedule = [{"week": 1}]
    team_datasets = {
        "snap_counts": [
            {"player": "Deebo Samuel", "week": 1, "position": "WR",
             "offense_pct": 0.92, "defense_pct": 0.0, "st_pct": 0.15},
            {"player": "Fred Warner", "week": 1, "position": "LB",
             "offense_pct": 0.0, "defense_pct": 0.98, "st_pct": 0.0},
        ],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    stats = out[0]["stats"]
    assert "snap_counts" not in stats  # replaced entirely by the split keys
    assert [r["player"] for r in stats["snap_counts_offense"]] == ["Deebo Samuel"]
    assert [r["player"] for r in stats["snap_counts_defense"]] == ["Fred Warner"]
    assert [r["player"] for r in stats["snap_counts_special_teams"]] == ["Deebo Samuel"]


def test_attach_week_stats_snap_counts_bucket_absent_when_empty_that_week():
    schedule = [{"week": 1}]
    team_datasets = {
        "snap_counts": [{"player": "X", "week": 1, "offense_pct": 0.5,
                         "defense_pct": 0.0, "st_pct": 0.0}],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    stats = out[0]["stats"]
    assert "snap_counts_offense" in stats
    assert "snap_counts_defense" not in stats
    assert "snap_counts_special_teams" not in stats


def test_attach_week_stats_splits_player_stats_by_role():
    """Regression coverage for the real gap this feature fixed: NGS-only
    coverage silently dropped players from the drilldown (verified live --
    a real week where 8 SF players caught a pass, ngs_receiving had rows
    for only 2). player_stats is the comprehensive box-score fallback,
    special-cased the same way snap_counts already is."""
    schedule = [{"week": 1}]
    team_datasets = {
        "player_stats": [
            _player_stats_row(player_display_name="Kyle Juszczyk", targets=2,
                              receptions=2, receiving_yards=32),
            _player_stats_row(player_display_name="Brock Purdy", attempts=30,
                              carries=3),
        ],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    stats = out[0]["stats"]
    assert "player_stats" not in stats  # replaced entirely by the split keys
    assert [r["player_display_name"] for r in stats["player_stats_receiving"]] == ["Kyle Juszczyk"]
    assert [r["player_display_name"] for r in stats["player_stats_passing"]] == ["Brock Purdy"]
    assert [r["player_display_name"] for r in stats["player_stats_rushing"]] == ["Brock Purdy"]


def test_attach_week_stats_player_stats_bucket_absent_when_nobody_qualifies_that_week():
    schedule = [{"week": 1}]
    team_datasets = {
        "player_stats": [_player_stats_row(targets=2, receptions=2, receiving_yards=32)],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    stats = out[0]["stats"]
    assert "player_stats_receiving" in stats
    assert "player_stats_passing" not in stats
    assert "player_stats_rushing" not in stats


# --- _schedule / _season_record / _season_history -----------------------------

def _fake_schedule_grid(rows):
    def _f(season, team="ALL"):
        return pd.DataFrame(rows) if rows else pd.DataFrame()
    return _f


def test_schedule_delegates_to_nflref(monkeypatch):
    rows = [{"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL",
             "home_score": 20, "margin": 4}]
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "schedule_grid", _fake_schedule_grid(rows))
    out = tp._schedule("SF", "2025")
    assert len(out) == 1
    assert out[0]["away_team"] == "SF"


def test_schedule_degrades_on_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("simulated failure")
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "schedule_grid", _boom)
    assert tp._schedule("SF", "2025") == []


def test_schedule_scrubs_nan_scores_to_none(monkeypatch):
    """A REAL DataFrame (not a hand-built dict) mixing a played game with an
    unplayed one: pandas casts the whole away_score/home_score/margin
    columns to float64, and an unplayed row's score comes back as NaN, not
    None. _schedule() must scrub this -- a raw NaN defeats every downstream
    `is not none` guard (both here and in the template), so an unplayed
    game would otherwise silently count as played with poisoned NaN totals
    (the real bug this test guards against)."""
    df = pd.DataFrame([
        {"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL",
         "home_score": 20, "margin": 4.0},
        {"week": 2, "away_team": "SEA", "away_score": float("nan"),
         "home_team": "SF", "home_score": float("nan"), "margin": float("nan")},
    ])
    assert df["away_score"].dtype.kind == "f"  # sanity: mixed column IS float64

    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "schedule_grid", lambda season, team="ALL": df)

    out = tp._schedule("SF", "2025")
    assert out[0]["away_score"] == 24.0
    week2 = out[1]
    assert week2["away_score"] is None
    assert week2["home_score"] is None
    assert week2["margin"] is None


def test_season_record_excludes_a_game_whose_nan_score_came_from_a_real_dataframe(monkeypatch):
    """End-to-end regression: _season_record reading through the REAL
    _schedule() (not a hand-built list of dicts already using clean None)
    against a mixed played/unplayed DataFrame must not count the unplayed
    week or let its NaN poison the summed totals."""
    df = pd.DataFrame([
        {"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL", "home_score": 20},
        {"week": 2, "away_team": "SEA", "away_score": float("nan"),
         "home_team": "SF", "home_score": float("nan")},
    ])
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "schedule_grid", lambda season, team="ALL": df)

    rec = tp._season_record("SF", "2025")
    assert rec["games"] == 1
    assert rec["wins"] == 1 and rec["losses"] == 0 and rec["ties"] == 0
    assert rec["points_for"] == 24
    assert rec["points_against"] == 20
    assert not pd.isna(rec["point_diff"])  # never NaN-poisoned


def test_season_record_computes_win_loss_and_points(monkeypatch):
    rows = [
        {"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL", "home_score": 20},
        {"week": 2, "away_team": "SEA", "away_score": 10, "home_team": "SF", "home_score": 17},
        {"week": 3, "away_team": "SF", "away_score": 14, "home_team": "LA", "home_score": 21},
        {"week": 4, "away_team": "SF", "away_score": 20, "home_team": "ARI", "home_score": 20},
    ]
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: rows)
    rec = tp._season_record("SF", "2025")
    assert rec["wins"] == 2
    assert rec["losses"] == 1
    assert rec["ties"] == 1
    assert rec["games"] == 4
    assert rec["points_for"] == 24 + 17 + 14 + 20
    assert rec["points_against"] == 20 + 10 + 21 + 20
    assert rec["point_diff"] == rec["points_for"] - rec["points_against"]


def test_season_record_excludes_unplayed_games(monkeypatch):
    rows = [{"week": 5, "away_team": "SF", "away_score": None, "home_team": "DAL",
             "home_score": None}]
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: rows)
    assert tp._season_record("SF", "2025") is None


def test_season_record_none_when_no_games(monkeypatch):
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    assert tp._season_record("SF", "2025") is None


def test_season_history_skips_seasons_with_no_games(monkeypatch):
    def _fake_record(abbr, season):
        return None if season == "2024" else {"season": season, "wins": 1}
    monkeypatch.setattr(tp, "_season_record", _fake_record)
    out = tp._season_history("SF", ["2025", "2024", "2023"])
    assert [r["season"] for r in out] == ["2025", "2023"]


# --- _team_datasets ------------------------------------------------------------

def test_team_datasets_filters_by_team_column(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "snap_counts":
            return pd.DataFrame([
                {"player": "Deebo Samuel", "team": "SF", "season": season},
                {"player": "Someone Else", "team": "DAL", "season": season},
            ])
        if dataset == "ngs_passing":
            return pd.DataFrame([
                {"player_display_name": "Brock Purdy", "team_abbr": "SF", "season": season},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = tp._team_datasets("SF", ["2025"])
    assert len(out["snap_counts"]) == 1
    assert out["snap_counts"][0]["team"] == "SF"
    assert len(out["ngs_passing"]) == 1
    assert out["injuries"] == []  # no matching rows, still the empty shape


def test_team_datasets_scrubs_nan_to_none(monkeypatch):
    """A real advanced-stat cell can legitimately be NaN (a non-passer's
    avg_time_to_throw, a player who didn't play special teams that week) --
    must come through as None, not the literal float NaN, or it renders as
    the text "nan" in the advanced-stats table."""
    def _fake_load(dataset, season):
        if dataset == "ngs_passing":
            return pd.DataFrame([
                {"player_display_name": "Brock Purdy", "team_abbr": "SF",
                 "season": season, "avg_time_to_throw": float("nan")},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = tp._team_datasets("SF", ["2025"])
    assert out["ngs_passing"][0]["avg_time_to_throw"] is None


def test_team_datasets_degrades_on_nflref_import_failure(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if "nflref" in name:
            raise ImportError("simulated")
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", _boom)
    assert tp._team_datasets("SF", ["2025"]) == {}


def test_team_datasets_skips_a_dataset_that_errors(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "snap_counts":
            raise RuntimeError("simulated")
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)
    out = tp._team_datasets("SF", ["2025"])
    assert out["snap_counts"] == []  # errored dataset degrades, doesn't raise


# --- team_profile() end to end / caching ---------------------------------------

def test_team_profile_assembles_all_sections(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_recent_seasons", lambda n=5: ["2025", "2024"])
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_roster_leaderboard",
                        lambda abbr, season: [{"player": "X", "position": "QB"}])
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [{"week": 1}])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [{"season": "2025"}])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {"snap_counts": []})

    out = tp.team_profile("SF")
    assert out["identity"]["abbr"] == "SF"
    assert out["current_season"] == "2025"
    assert out["roster"] == [{"player": "X", "position": "QB"}]
    assert out["roster_by_position"] == [{"position": "QB", "players": [{"player": "X", "position": "QB"}]}]
    # schedule rows get "stats"/"game_type" attached (per-game advanced-stat
    # slices) -- both empty/None here since _team_datasets returns nothing
    # week-tagged.
    assert out["schedule"] == [{"week": 1, "stats": {}, "game_type": None}]
    assert out["season_history"] == [{"season": "2025"}]
    assert out["team_datasets"] == {"snap_counts": []}


def test_team_profile_caches_repeat_calls(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {})
    calls = []

    def _tracked(*a, **k):
        calls.append(1)
        return []
    monkeypatch.setattr(tp, "_roster_leaderboard", _tracked)

    first = tp.team_profile("SF")
    second = tp.team_profile("SF")
    assert len(calls) == 1
    assert first is second


def test_team_profile_fresh_bypasses_cache(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {})
    calls = []

    def _tracked(*a, **k):
        calls.append(1)
        return []
    monkeypatch.setattr(tp, "_roster_leaderboard", _tracked)

    tp.team_profile("SF")
    tp.team_profile("SF", fresh=True)
    assert len(calls) == 2


def test_team_profile_cache_keys_by_season_too(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_roster_leaderboard", lambda abbr, season: [{"season": season}])
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {})

    a = tp.team_profile("SF", season="2025")
    b = tp.team_profile("SF", season="2024")
    assert a["roster"][0]["season"] == "2025"
    assert b["roster"][0]["season"] == "2024"


def test_team_profile_cache_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {})
    calls = []

    def _tracked(*a, **k):
        calls.append(1)
        return []
    monkeypatch.setattr(tp, "_roster_leaderboard", _tracked)

    tp.team_profile("SF")
    key = ("SF", "2025")
    tp._PROFILE_CACHE[key]["at"] -= tp._PROFILE_TTL + 1
    tp.team_profile("SF")
    assert len(calls) == 2


def test_is_cached_false_before_any_call():
    assert tp.is_cached("SF") is False


def test_is_cached_true_after_a_real_call(monkeypatch):
    monkeypatch.setattr(tp, "_current_season", lambda: "2025")
    monkeypatch.setattr(tp, "_team_identity", lambda abbr: {"abbr": abbr, "known": True})
    monkeypatch.setattr(tp, "_roster_leaderboard", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_schedule", lambda abbr, season: [])
    monkeypatch.setattr(tp, "_season_history", lambda abbr, seasons: [])
    monkeypatch.setattr(tp, "_team_datasets", lambda abbr, seasons: {})
    tp.team_profile("SF")
    assert tp.is_cached("SF") is True
    assert tp.is_cached("SF", season="2020") is False


def test_is_cached_false_after_ttl_expiry():
    tp._PROFILE_CACHE[("SF", "2025")] = {"data": {}, "at": 0}
    assert tp.is_cached("SF", season="2025") is False


# --- team_profile.html rendering: no double-escaped HTML entities -----------

@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_never_double_escapes_ndash():
    """Jinja autoescapes {{ }} output, so `{{ x if x is not none else
    "&ndash;" }}` renders the LITERAL fallback string escaped too, producing
    "&amp;ndash;" (displays as the literal text "&ndash;" in a browser, not
    a dash). The fix is a block {% if %}...{% else %}&ndash;{% endif %} so
    the entity sits in raw template text, never inside {{ }}. This renders
    every code path that has a dash fallback -- an incomplete game (None
    score/margin), a roster row with None stats, and an advanced-stat cell
    with None values -- and asserts the escaped form never appears."""
    env = _tpl.env
    template = env.get_template("team_profile.html")

    schedule = [
        {"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL",
         "home_score": 20, "margin": 4, "stats": {}},
        {"week": 2, "away_team": "SEA", "away_score": None, "home_team": "SF",
         "home_score": None, "margin": None, "stats": {}},
    ]
    roster = [{"rank": 1, "player": "Nobody", "player_id": "1", "position": "QB",
              "fpts_ppr": None, "ppg_ppr": None}]
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": roster,
        "roster_by_position": [{"position": "QB", "players": roster}],
        "schedule": schedule,
        "season_history": [],
        "team_datasets": {"snap_counts": [
            {"player": None, "team": "SF", "offense_pct": None}]},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert "&amp;ndash;" not in html
    assert html.count("&ndash;") >= 4


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_condenses_constant_columns_in_game_drilldown():
    """The per-game drilldown's advanced-stat tables must NOT repeat
    game_id/game_type/opponent/season_type as their own columns -- every
    row in a single game's table shares the same value for all four (the
    drilldown is already scoped to one team + one week, and the opponent
    and week are already shown in the row's own summary line above), so
    showing them per-row is pure duplication. The season-wide Advanced
    stats section, by contrast, spans every game and must KEEP these
    columns, since they genuinely differ row to row there."""
    env = _tpl.env
    template = env.get_template("team_profile.html")

    stat_row = {
        "pfr_player_name": "Fred Warner", "team": "SF", "opponent": "DAL",
        "game_id": "2025_01_SF_DAL", "game_type": "REG", "week": 1,
        "season": 2025, "def_tackles_combined": 12,
    }
    schedule = [{"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL",
                "home_score": 20, "margin": 4, "stats": {"pfr_def": [stat_row]}}]
    team_datasets = {"pfr_def": [stat_row]}
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": schedule, "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)

    import re
    detail = re.search(r'<div class="dt-detail">(.*?)</div>\s*</details>', html, re.S).group(1)
    game_headers = re.findall(r"<th>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", detail, re.S).group(1))
    assert game_headers == ["Player", "def tackles combined"]

    season_section = html[html.find("Advanced &amp; usage stats"):]
    season_headers = re.findall(r"<th>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", season_section, re.S).group(1))
    assert "opponent" in season_headers
    assert "game id" in season_headers
    assert "game type" in season_headers


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_shows_game_type_in_row_header():
    """game_type is surfaced once in the game's own summary row (next to
    the week number), NOT repeated as a column in every drilldown stat
    table -- opponent/week are already implied by Away/Home + Wk, so only
    game_type carries genuinely new information worth showing at the row
    level."""
    env = _tpl.env
    template = env.get_template("team_profile.html")

    schedule = [
        {"week": 20, "away_team": "SF", "away_score": 24, "home_team": "DAL",
         "home_score": 20, "margin": 4, "stats": {}, "game_type": "DIV"},
        {"week": 1, "away_team": "SEA", "away_score": 10, "home_team": "SF",
         "home_score": 17, "margin": 7, "stats": {}, "game_type": None},
    ]
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": schedule, "season_history": [],
        "team_datasets": {},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert '<span class="q">DIV</span>' in html
    # a game with no resolved game_type shows no badge at all, not "None"
    assert "None" not in html


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_game_stat_labels_covers_every_team_dataset():
    """Regression guard for a real gap that shipped: _TEAM_DATASETS (the
    Python-side list of datasets actually fetched into team_datasets) had
    9 entries, but the template's game_stat_labels list -- the per-game
    drilldown's own dataset loop -- only covered 8, silently omitting
    "injuries" from every per-match dropdown even though the data was
    fully present in g.stats["injuries"]. Every dataset _attach_week_stats
    can surface under g.stats (every _TEAM_DATASETS entry, with
    "snap_counts"/"player_stats" replaced by their split-bucket keys) must
    have a corresponding game_stat_labels entry, or a future dataset
    addition will repeat this same silent-gap bug.

    Derives the expected key set from _TEAM_DATASETS/_SNAP_BUCKETS/
    _PLAYER_STATS_BUCKETS directly (not a hand-maintained literal) so this
    test itself can't go stale the next time a dataset is added -- it
    would have caught the player_stats addition automatically rather than
    needing a manual edit alongside it."""
    import re
    src = pathlib.Path(_tpl.env.loader.searchpath[0], "team_profile.html").read_text(encoding="utf-8")
    block = re.search(r"game_stat_labels\s*=\s*\[(.*?)\]\s*%\}", src, re.S).group(1)
    game_keys = set(re.findall(r'\("([\w]+)"', block))

    split_ds = {"snap_counts": [b for b, _ in tp._SNAP_BUCKETS],
               "player_stats": [b for b, _ in tp._PLAYER_STATS_BUCKETS]}
    expected = set()
    for ds in tp._TEAM_DATASETS:
        if ds in split_ds:
            expected.update(f"{ds}_{bucket}" for bucket in split_ds[ds])
        else:
            expected.add(ds)
    assert game_keys == expected


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_renders_injuries_in_game_drilldown():
    """End-to-end: an injuries row attached to a game's stats (via the real
    _attach_week_stats, not a hand-built stub) must actually appear in
    that game's rendered drilldown -- the bug this guards against had the
    data present in g.stats but nothing rendered because the template's
    label loop skipped the key entirely."""
    schedule_raw = [{"week": 1, "away_team": "SF", "away_score": 24,
                     "home_team": "DAL", "home_score": 20, "margin": 4}]
    team_datasets = {"injuries": [
        {"full_name": "Fred Warner", "team": "SF", "week": 1, "game_type": "REG",
         "report_primary_injury": "Knee", "report_status": "Questionable"}]}
    schedule = tp._attach_week_stats(schedule_raw, team_datasets)

    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": schedule, "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    import re
    detail = re.search(r'<div class="dt-detail">(.*?)</div>\s*</details>', html, re.S).group(1)
    assert "Injury reports" in detail
    assert "Fred Warner" in detail
    assert "Knee" in detail


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_renders_player_stats_box_score_in_game_drilldown():
    """End-to-end: player_stats rows (the comprehensive box-score fallback,
    added specifically because ngs_receiving/ngs_rushing/ngs_passing only
    cover players NFL's tracking system published that week) render as
    three separate "Box score: <role>" sections in the per-game drilldown,
    distinct from the narrower "Next Gen Stats" sections, via the real
    _attach_week_stats pipeline."""
    schedule_raw = [{"week": 1, "away_team": "SF", "away_score": 24,
                     "home_team": "DAL", "home_score": 20, "margin": 4}]
    team_datasets = {"player_stats": [
        _player_stats_row(player_display_name="Kyle Juszczyk", targets=2,
                          receptions=2, receiving_yards=32),
        _player_stats_row(player_display_name="Brock Purdy", attempts=30,
                          carries=3, rushing_yards=15),
    ]}
    schedule = tp._attach_week_stats(schedule_raw, team_datasets)

    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": schedule, "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    import re
    detail = re.search(r'<div class="dt-detail">(.*?)</div>\s*</details>', html, re.S).group(1)
    assert "Box score: Receiving" in detail
    assert "Box score: Passing" in detail
    assert "Box score: Rushing" in detail
    assert "Kyle Juszczyk" in detail
    assert "Brock Purdy" in detail


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_season_wide_shows_player_stats_as_box_score():
    """The season-wide Advanced & usage stats section (unsplit, unlike the
    per-game drilldown) must also surface player_stats, labelled "Box
    score" -- added to advanced_datasets alongside snap_counts."""
    team_datasets = {"player_stats": [
        _player_stats_row(player_display_name="Kyle Juszczyk", targets=2,
                          receptions=2, receiving_yards=32)]}
    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    season_section = html[html.find("Advanced &amp; usage stats"):]
    assert "Box score" in season_section
    assert "Kyle Juszczyk" in season_section


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_stat_table_excludes_recent_team_column():
    """Regression guard for a real bug caught while verifying a live DET
    render: player_stats's team column is named "recent_team" (every OTHER
    dataset uses "team"/"team_abbr"), which id_cols didn't originally
    include -- so every row in a Box score table repeated the team
    abbreviation as its own column, identical on every row, pure noise."""
    team_datasets = {"player_stats": [
        {"player_display_name": "Jahmyr Gibbs", "recent_team": "DET", "week": 1,
         "season": 2026, "position": "RB", "targets": 5, "receptions": 5,
         "receiving_yards": 30, "receiving_tds": 0, "receiving_air_yards": -4,
         "target_share": 0.1282051282051282, "air_yards_share": -0.01932367149758454,
         "wopr": 0.1787811222593831, "racr": -7.5,
         "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
         "attempts": 0, "completions": 0, "passing_yards": 0, "passing_tds": 0,
         "interceptions": 0, "passing_air_yards": 0, "pacr": None,
         "fantasy_points": 28.6, "fantasy_points_ppr": 33.6}]}
    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "DET", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "DET", "known": True},
        "current_season": "2026", "seasons_covered": ["2026"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert "<td>DET</td>" not in html
    assert "recent team" not in html


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_rounds_float_cells_to_one_decimal():
    """Regression guard for a real bug caught while verifying a live DET
    render: an unrounded NGS/PFR float (e.g. target_share) rendered with
    full double precision, "0.1282051282051282" instead of "0.1" -- the
    cell() macro rounds any non-integer float to 1dp at display time,
    leaves real integers (receptions=5) and whole-number floats (57.0,
    still rounded for consistency) alone otherwise."""
    team_datasets = {"snap_counts": [
        {"player": "Jahmyr Gibbs", "team": "DET", "week": 1, "position": "RB",
         "offense_snaps": 57.0, "offense_pct": 0.1282051282051282,
         "defense_snaps": 0.0, "defense_pct": 0.0, "st_snaps": 0.0, "st_pct": 0.0}]}
    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "DET", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "DET", "known": True},
        "current_season": "2026", "seasons_covered": ["2026"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert "0.1282051282051282" not in html
    assert "57.0" in html  # a whole-number float still shows (1dp, harmless)
    assert "0.1</td>" in html or "0.1<" in html
