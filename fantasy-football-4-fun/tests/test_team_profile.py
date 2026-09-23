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
# 2026-09: stats["passing"/"rushing"/"receiving"] are ALWAYS-present dict
# entries ({"reconciled": [...], "sources": [...], optionally "pfr": [...]})
# now that stats are grouped BY METRIC (see webapp.stat_reconcile / this
# module's _grouped_metric_stats) rather than by source. A single-source
# dataset with no metric family (pfr_def, snap_counts_*, injuries) still
# appears as its own flat top-level list, exactly as before.

def test_attach_week_stats_slices_by_week():
    schedule = [{"week": 1}, {"week": 2}]
    team_datasets = {
        "pfr_def": [{"pfr_player_name": "E", "week": 1}],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["stats"]["pfr_def"] == [{"pfr_player_name": "E", "week": 1}]
    assert "pfr_def" not in out[1]["stats"]
    assert out[0]["week"] == 1  # original game fields preserved
    # passing/rushing/receiving are always present, even with no data.
    for metric in ("passing", "rushing", "receiving"):
        assert out[0]["stats"][metric] == {"reconciled": [], "sources": [], "source_groups": []}


def test_attach_week_stats_extracts_game_type():
    """game_type (REG/WC/DIV/CON/SB) isn't a schedule_grid() column -- it
    only exists inside the advanced-stat datasets, constant across every
    row of a single game. _attach_week_stats pulls it up onto the game
    dict itself so the template can show it once in the row header instead
    of repeating it per stat row."""
    schedule = [{"week": 1}, {"week": 20}]
    team_datasets = {
        "pfr_def": [
            {"pfr_player_name": "A", "week": 1, "game_type": "REG"},
            {"pfr_player_name": "A", "week": 20, "game_type": "DIV"},
        ],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] == "REG"
    assert out[1]["game_type"] == "DIV"


def test_attach_week_stats_game_type_none_when_no_datasets_carry_it():
    schedule = [{"week": 1}]
    team_datasets = {"pfr_def": [{"pfr_player_name": "A", "week": 1}]}  # no game_type key
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] is None


def test_attach_week_stats_game_type_none_when_week_missing():
    schedule = [{"week": None}]
    team_datasets = {"pfr_def": [{"pfr_player_name": "A", "week": 1, "game_type": "REG"}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert out[0]["game_type"] is None


def test_attach_week_stats_dataset_absent_when_no_rows_for_week():
    schedule = [{"week": 3}]
    team_datasets = {"pfr_def": [{"pfr_player_name": "A", "week": 1}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert "pfr_def" not in out[0]["stats"]  # no key at all, not an empty list
    for metric in ("passing", "rushing", "receiving"):
        assert out[0]["stats"][metric] == {"reconciled": [], "sources": [], "source_groups": []}


def test_attach_week_stats_handles_missing_week_on_game():
    schedule = [{"week": None}]
    team_datasets = {"pfr_def": [{"pfr_player_name": "A", "week": 1}]}
    out = tp._attach_week_stats(schedule, team_datasets)
    assert "pfr_def" not in out[0]["stats"]


def test_attach_week_stats_empty_inputs():
    assert tp._attach_week_stats([], {}) == []
    out = tp._attach_week_stats([{"week": 1}], {})
    assert out[0]["week"] == 1
    assert out[0]["game_type"] is None
    for metric in ("passing", "rushing", "receiving"):
        assert out[0]["stats"][metric] == {"reconciled": [], "sources": [], "source_groups": []}
    assert set(out[0]["stats"]) == {"passing", "rushing", "receiving"}


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


def test_attach_week_stats_player_stats_feeds_reconciled_passing_rushing_receiving():
    """Regression coverage for the real gap this feature originally fixed:
    NGS-only coverage silently dropped players from the drilldown (verified
    live -- a real week where 8 SF players caught a pass, ngs_receiving had
    rows for only 2). player_stats is the comprehensive box-score fallback;
    its role-split rows now feed straight into the RECONCILED
    passing/rushing/receiving tables (stat_reconcile.reconcile_metric) --
    not their own separate top-level table the way they used to, since
    stats are grouped by metric now, not by source."""
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
    receiving_players = [r["player"] for r in stats["receiving"]["reconciled"]]
    passing_players = [r["player"] for r in stats["passing"]["reconciled"]]
    rushing_players = [r["player"] for r in stats["rushing"]["reconciled"]]
    assert receiving_players == ["Kyle Juszczyk"]
    assert passing_players == ["Brock Purdy"]
    assert rushing_players == ["Brock Purdy"]
    assert "player_stats" in stats["receiving"]["sources"]
    assert "player_stats" in stats["passing"]["sources"]


def test_attach_week_stats_metric_stays_empty_when_nobody_qualifies_that_week():
    schedule = [{"week": 1}]
    team_datasets = {
        "player_stats": [_player_stats_row(targets=2, receptions=2, receiving_yards=32)],
    }
    out = tp._attach_week_stats(schedule, team_datasets)
    stats = out[0]["stats"]
    assert stats["receiving"]["reconciled"]
    assert stats["passing"]["reconciled"] == []
    assert stats["rushing"]["reconciled"] == []


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
    # slices) -- game_type is None and every metric is empty here since
    # _team_datasets returns nothing week-tagged. passing/rushing/receiving
    # are ALWAYS-present dict entries now (2026-09 metric-grouped redesign).
    empty_metric = {"reconciled": [], "sources": [], "source_groups": []}
    assert out["schedule"] == [{"week": 1, "game_type": None, "stats": {
        "passing": empty_metric, "rushing": empty_metric, "receiving": empty_metric}}]
    assert out["season_history"] == [{"season": "2025"}]
    assert out["team_datasets"] == {"snap_counts": []}
    # team_stats_grouped is the season-wide counterpart, built from the
    # same team_datasets via _season_grouped_stats -- also always carries
    # the three metric keys, empty here for the same reason.
    assert out["team_stats_grouped"] == {
        "passing": empty_metric, "rushing": empty_metric, "receiving": empty_metric}


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
        "team_stats_grouped": {}, "source_labels": {},
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
    columns, since they genuinely differ row to row there.

    The per-game detail is lazy-loaded (2026-09 -- see team_profile.html's
    own comment on the schedule section) via _team_game_detail.html, a
    separate TemplateResponse from the parent page; rendered directly
    here, same as webapp.app.team_game_detail() would build it."""
    env = _tpl.env

    stat_row = {
        "pfr_player_name": "Fred Warner", "team": "SF", "opponent": "DAL",
        "game_id": "2025_01_SF_DAL", "game_type": "REG", "week": 1,
        "season": 2025, "def_tackles_combined": 12,
    }
    empty_metric = {"reconciled": [], "sources": [], "source_groups": []}
    stats = {"pfr_def": [stat_row], "passing": empty_metric,
             "rushing": empty_metric, "receiving": empty_metric}

    detail_template = env.get_template("_team_game_detail.html")
    detail = detail_template.render(
        theme="light", game_key=1, stats=stats, source_labels={})

    import re
    game_headers = re.findall(r"<th>(.*?)</th>", re.search(r"<thead>(.*?)</thead>", detail, re.S).group(1))
    assert game_headers == ["Player", "def tackles combined"]

    template = env.get_template("team_profile.html")
    schedule = [{"week": 1, "away_team": "SF", "away_score": 24, "home_team": "DAL",
                "home_score": 20, "margin": 4, "stats": stats}]
    team_datasets = {"pfr_def": [stat_row]}
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": schedule, "season_history": [],
        "team_datasets": team_datasets,
        # pfr_def is single-source (no cross-source metric to group under),
        # so it still reaches the season-wide section straight from
        # team_stats_grouped, unaffected by the reconciliation redesign.
        "team_stats_grouped": {"pfr_def": [stat_row]}, "source_labels": {},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
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
        "team_datasets": {}, "team_stats_grouped": {}, "source_labels": {},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert '<span class="q">DIV</span>' in html
    # a game with no resolved game_type shows no badge at all, not "None"
    assert "None" not in html


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_stats_covers_every_real_top_level_key():
    """Regression guard for a real gap that shipped originally (pre-2026-09
    metric regroup): _TEAM_DATASETS had 9 entries, but the template's own
    dataset-label loop only covered 8, silently omitting "injuries" from
    every per-match dropdown even though the data was fully present in
    g.stats["injuries"].

    2026-09: stats are grouped BY METRIC now (webapp.stat_reconcile /
    _grouped_metric_stats), so the template no longer has one label per
    raw dataset -- it has `metric_labels` (passing/rushing/receiving,
    which absorb player_stats/ngs_*/sleeper/pfr_* role-split rows) plus
    `single_source_labels` (snap_counts_*/pfr_def/injuries, unchanged,
    single-source). This test re-derives the SAME invariant against the
    new shape: every real top-level key `_attach_week_stats` can actually
    put into `g.stats` (every _TEAM_DATASETS entry PLUS "sleeper" -- added
    separately in `_team_datasets()`, not in the static list -- run through
    the real role-split/grouping functions) must be covered by either
    metric_labels or single_source_labels, so a future dataset addition
    can't silently vanish from the per-game drilldown the same way
    "injuries" once did."""
    import re
    from webapp import stat_reconcile
    # metric_labels is now `{% set metric_labels = METRIC_LABELS %}` -- the
    # single Python source of truth (stat_reconcile.METRIC_LABELS,
    # registered as a Jinja global), so read it directly rather than
    # regex-parsing a literal that no longer lives in the template source.
    metric_keys = {key for key, _ in stat_reconcile.METRIC_LABELS}
    src = pathlib.Path(_tpl.env.loader.searchpath[0], "team_profile.html").read_text(encoding="utf-8")
    single_block = re.search(r"single_source_labels\s*=\s*\[(.*?)\]\s*%\}", src, re.S).group(1)
    single_keys = set(re.findall(r'\("([\w]+)"', single_block))

    # What top-level key does each real dataset ultimately surface under?
    # snap_counts/pfr_def/injuries -> themselves (single_source_labels).
    # player_stats/sleeper -> role-split into passing/rushing/receiving
    # (metric_labels). ngs_*/pfr_pass/pfr_rec/pfr_rush -> already named
    # for their own metric (metric_labels covers them via reconciliation
    # or the "pfr" sub-table).
    expected_metric_datasets = {
        "player_stats", "sleeper", "ngs_passing", "ngs_receiving", "ngs_rushing",
        "pfr_pass", "pfr_rec", "pfr_rush"}
    expected_single_datasets = {"snap_counts", "pfr_def", "injuries"}
    all_datasets = set(tp._TEAM_DATASETS) | {"sleeper"}
    assert all_datasets == expected_metric_datasets | expected_single_datasets

    # snap_counts itself splits into 3 role keys, all of which must be
    # covered by single_source_labels (it has no metric family).
    snap_keys = {f"snap_counts_{b}" for b, _ in tp._SNAP_BUCKETS}
    assert snap_keys <= single_keys
    assert {"pfr_def", "injuries"} <= single_keys
    # Every metric family (passing/rushing/receiving) must be covered.
    assert metric_keys == {"passing", "rushing", "receiving"}


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_renders_injuries_in_game_drilldown():
    """End-to-end: an injuries row attached to a game's stats (via the real
    _attach_week_stats, not a hand-built stub) must actually appear in
    that game's rendered drilldown -- the bug this guards against had the
    data present in g.stats but nothing rendered because the template's
    label loop skipped the key entirely.

    The per-game detail is lazy-loaded (2026-09) via _team_game_detail.html
    -- rendered directly here, same as webapp.app.team_game_detail() would
    build it for this game's `stats`."""
    schedule_raw = [{"week": 1, "away_team": "SF", "away_score": 24,
                     "home_team": "DAL", "home_score": 20, "margin": 4}]
    team_datasets = {"injuries": [
        {"full_name": "Fred Warner", "team": "SF", "week": 1, "game_type": "REG",
         "report_primary_injury": "Knee", "report_status": "Questionable"}]}
    schedule = tp._attach_week_stats(schedule_raw, team_datasets)

    template = _tpl.env.get_template("_team_game_detail.html")
    detail = template.render(theme="light", game_key=1,
                             stats=schedule[0]["stats"], source_labels={})
    assert "Injuries" in detail  # the sub-tab pill label
    assert "Fred Warner" in detail
    assert "Knee" in detail


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_renders_player_stats_in_reconciled_metric_tables():
    """End-to-end: player_stats rows (the comprehensive box-score fallback,
    added specifically because ngs_receiving/ngs_rushing/ngs_passing only
    cover players NFL's tracking system published that week) feed the
    RECONCILED Passing/Rushing/Receiving tables now (2026-09 metric
    regroup) rather than their own separate "Box score: <role>" sections --
    player_stats is the only source with data here, so each reconciled row
    shows player_stats as its sole source, via the real _attach_week_stats
    pipeline end to end.

    The per-game detail is lazy-loaded (2026-09) via _team_game_detail.html
    -- rendered directly here, same as webapp.app.team_game_detail() would
    build it for this game's `stats`."""
    schedule_raw = [{"week": 1, "away_team": "SF", "away_score": 24,
                     "home_team": "DAL", "home_score": 20, "margin": 4}]
    team_datasets = {"player_stats": [
        _player_stats_row(player_display_name="Kyle Juszczyk", targets=2,
                          receptions=2, receiving_yards=32),
        _player_stats_row(player_display_name="Brock Purdy", attempts=30,
                          carries=3, rushing_yards=15),
    ]}
    schedule = tp._attach_week_stats(schedule_raw, team_datasets)

    template = _tpl.env.get_template("_team_game_detail.html")
    detail = template.render(theme="light", game_key=1, stats=schedule[0]["stats"],
                             source_labels={"player_stats": "Box score (nflverse)"})
    assert "<strong>Receiving</strong>" in detail
    assert "<strong>Passing</strong>" in detail
    assert "<strong>Rushing</strong>" in detail
    assert "Source: Box score (nflverse)" in detail
    assert "Kyle Juszczyk" in detail
    assert "Brock Purdy" in detail
    # No stray "Box score: <role>" headings from the old source-segmented
    # layout -- the metric heading alone is the section title now.
    assert "Box score: Receiving" not in detail
    assert "Box score: Passing" not in detail
    assert "Box score: Rushing" not in detail


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_season_wide_reconciles_player_stats():
    """The season-wide Advanced & usage stats section must surface
    player_stats-sourced rows under the reconciled Receiving table (2026-09
    metric regroup -- player_stats no longer gets its own "Box score"
    section; its role-split rows feed reconciliation like every other
    source). Uses the real _season_grouped_stats pipeline end to end,
    including the source note naming player_stats by its display label."""
    from webapp import stat_reconcile
    team_datasets = {"player_stats": [
        _player_stats_row(player_display_name="Kyle Juszczyk", targets=2,
                          receptions=2, receiving_yards=32)]}
    team_stats_grouped = tp._season_grouped_stats(team_datasets)
    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "team_stats_grouped": team_stats_grouped,
        "source_labels": stat_reconcile.SOURCE_LABELS,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    season_section = html[html.find("Advanced &amp; usage stats"):]
    assert "<summary>Receiving" in season_section
    assert "Source: Box score" in season_section
    assert "Kyle Juszczyk" in season_section


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_metric_sources_note_lists_pfr_advanced_only_once():
    """Regression guard for a real bug: pfr_rush legitimately appears BOTH
    as a carries-voting source (stat_reconcile._METRIC_MAPS maps "carries"
    to pfr_rush too, so it's a real reconcile_metric() participant) AND
    supplies its own separate un-reconciled `entry.pfr` sub-table (its
    OTHER columns -- yards before/after contact -- have no cross-source
    overlap). The source note's macro appended "PFR advanced" once for
    each of those two reasons before this fix, rendering "Source: PFR
    advanced, Box score, Sleeper, PFR advanced" -- the same name twice.

    The note is a single flat, deduped "Source: X, Y" list (per user
    request: "don't need to split out which data is from which source,
    just coagulated together") -- this test only checks that flattening
    every source across every source_groups combination still dedupes
    PFR advanced correctly, not that it's split per stat."""
    from webapp import stat_reconcile
    team_datasets = {
        "player_stats": [_player_stats_row(player_display_name="Christian McCaffrey",
                                           carries=20, rushing_yards=90)],
        "pfr_rush": [{"pfr_player_name": "Christian McCaffrey", "team": "SF", "week": 1,
                      "carries": 20, "rushing_yards_before_contact": 40}],
    }
    team_stats_grouped = tp._season_grouped_stats(team_datasets)
    template = _tpl.env.get_template("team_profile.html")
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "team_stats_grouped": team_stats_grouped,
        "source_labels": stat_reconcile.SOURCE_LABELS,
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    season_section = html[html.find("Advanced &amp; usage stats"):]
    import re
    m = re.search(r"<summary>Rushing.*?Source: ([^<]+)</p>", season_section, re.S)
    assert m, "expected a Rushing source note"
    names = [n.strip() for n in m.group(1).split(",")]
    assert names.count("PFR advanced") == 1


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_teamstat_macros_stat_table_excludes_recent_team_column():
    """Regression guard for a real bug caught while verifying a live DET
    render: player_stats's team column is named "recent_team" (every OTHER
    dataset uses "team"/"team_abbr"), which id_cols didn't originally
    include -- so every row in a source-segmented table repeated the team
    abbreviation as its own column, identical on every row, pure noise.

    2026-09: player_stats itself no longer renders through stat_table() at
    all (its rows feed the reconciler, which uses a FIXED column list --
    see reconciled_table() -- so this specific bug class is now
    structurally impossible for player_stats). id_cols still excludes
    recent_team defensively for any OTHER dataset that might reuse that
    column name, and the guard is now tested directly against
    _teamstat_macros.html's stat_table() -- the real code path any
    single-source table (PFR advanced, snap counts, injuries) still uses --
    rather than through team_profile.html's now-moot player_stats route."""
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(pathlib.Path(_tpl.env.loader.searchpath[0]))))
    tpl = env.from_string(
        '{% import "_teamstat_macros.html" as tsm %}{{ tsm.stat_table(rows) }}')
    rows = [{"player_display_name": "Jahmyr Gibbs", "recent_team": "DET",
            "week": 1, "targets": 5}]
    html = tpl.render(rows=rows)
    assert "<td>DET</td>" not in html
    assert "recent team" not in html
    assert "Jahmyr Gibbs" in html


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_template_rounds_float_cells_to_one_decimal():
    """Regression guard for a real bug caught while verifying a live DET
    render: an unrounded NGS/PFR float (e.g. target_share) rendered with
    full double precision, "0.1282051282051282" instead of "0.1" -- the
    cell() macro rounds any non-integer float to 1dp at display time,
    leaves real integers (receptions=5) and whole-number floats (57.0,
    still rounded for consistency) alone otherwise. snap_counts is
    single-source (no metric family), so it's unaffected by the 2026-09
    metric regroup and still renders through stat_table() directly."""
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
        "team_stats_grouped": tp._season_grouped_stats(team_datasets),
        "source_labels": {},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert "0.1282051282051282" not in html
    assert "57.0" in html  # a whole-number float still shows (1dp, harmless)
    assert "0.1</td>" in html or "0.1<" in html


# --- _teamstat_macros.html (shared with the Testing-tab prototype) ------------


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_teamstat_macros_shared_file_renders_identically_to_inline_original():
    """_teamstat_macros.html was factored out of team_profile.html so a
    Testing-tab layout prototype could reuse the exact same cell()/
    stat_table() rendering without a copy that could drift from the real
    page's own (see tab_testing.html's schedule-drilldown restyle mockup).
    This locks
    in that team_profile.html's real per-game and season-wide tables still
    render through the shared macros with identical output shape -- a
    header row, one data row, values matching cell()'s own float-rounding/
    None-dash rules -- rather than silently reverting to a local copy."""
    template = _tpl.env.get_template("team_profile.html")
    stat_row = {"pfr_player_name": "Fred Warner", "team": "SF", "week": 1,
                "def_tackles_combined": 12, "missed_tackle_pct": 0.128205}
    team_datasets = {"pfr_def": [stat_row]}
    ctx = {
        "abbr": "SF", "asset_v": "1", "theme": "light",
        "identity": {"abbr": "SF", "known": True},
        "current_season": "2025", "seasons_covered": ["2025"],
        "roster": [], "roster_by_position": [],
        "schedule": [], "season_history": [],
        "team_datasets": team_datasets,
        "team_stats_grouped": tp._season_grouped_stats(team_datasets),
        "source_labels": {},
        "avatars": {}, "league": None, "season": None,
    }
    html = template.render(**ctx)
    assert "Fred Warner" in html
    assert "<th>def tackles combined</th>" in html
    assert "12" in html
    assert "0.1</td>" in html or "0.1<" in html  # cell() rounding still applies
    assert "0.128205" not in html


@pytest.mark.skipif(_tpl is None, reason="webapp.app import chain unavailable")
def test_team_profile_reconciled_table_renders_flyout_on_every_cell():
    """End-to-end: the per-source hover flyout, shipped to the real
    /team/{abbr} page (2026-09 -- trialled first as a Testing-tab mockup,
    reconciled_table's default flipped to `flyout=true` once that mockup
    was reviewed). EVERY reconciled cell, not just a disagreeing one, is
    wrapped in a hoverable `.stat-cell` carrying its own `.stat-flyout`
    breakdown of every contributing source's own value, with the
    disagreement flag `.stat-flag` still present on a disagreeing cell.

    The per-game detail is lazy-loaded (2026-09) via _team_game_detail.html
    -- rendered directly here, same as webapp.app.team_game_detail() would
    build it for this game's `stats`."""
    schedule_raw = [{"week": 1, "away_team": "SF", "away_score": 24,
                     "home_team": "DAL", "home_score": 20, "margin": 4}]
    team_datasets = {
        "player_stats": [_player_stats_row(player_display_name="Patrick Mahomes",
                                           attempts=29)],
        "sleeper": [{"player": "Patrick Mahomes", "team": "KC", "week": 1,
                    "pass_att": 28}],
    }
    schedule = tp._attach_week_stats(schedule_raw, team_datasets)

    template = _tpl.env.get_template("_team_game_detail.html")
    detail = template.render(theme="light", game_key=1, stats=schedule[0]["stats"],
                             source_labels={"player_stats": "Box score", "sleeper": "Sleeper"})

    assert '<span class="stat-cell" tabindex="0">' in detail
    assert 'class="stat-flyout"' in detail
    assert "stat-flyout-src\">Box score" in detail
    assert "stat-flyout-src\">Sleeper" in detail
    assert 'class="stat-flyout-val">29' in detail  # player_stats's own value
    assert 'class="stat-flyout-val">28' in detail  # sleeper's own value
    assert 'class="stat-flag">' in detail  # disagreement flag, still present
    assert "Patrick Mahomes" in detail
    # The old flag+title-only rendering (flyout=false) is gone from the
    # real page's own output -- no bare `title="Sources disagree` tooltip.
    assert 'title="Sources disagree' not in detail
