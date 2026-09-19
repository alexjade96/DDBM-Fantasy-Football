"""nflref -- nflverse-derived data layer.

Network-free: `nflref.api.read_release_parquet` is monkeypatched, and the
snapshot dir is redirected to tmp so nothing touches data/sources/nflverse/.
"""
import pandas as pd
import pytest

import webapp.sources.nflref as nflref
from webapp.sources.nflref import api, cache
from webapp.sources.nflref.base import DATASETS
from webapp.sources.nflref.player_stats import PlayerStats
from webapp.sources.nflref.schedules import Schedules


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "_NFLVERSE_DIR", tmp_path / "nflverse")
    cache.clear()
    yield


def _fake_player_stats():
    return pd.DataFrame({
        "player_id": ["00-1", "00-2"],
        "player_display_name": ["A B", "C D"],
        "position": ["WR", "RB"],
        "recent_team": ["AAA", "BBB"],
        "season": [2024, 2024],
        "week": [1, 1],
        "season_type": ["REG", "POST"],       # POST row must be dropped
        "targets": [10, 3],
        "receptions": [7, 2],
        "receiving_yards": [88, 15],
        "target_share": [0.28, 0.09],
        "air_yards_share": [0.4, 0.05],
        "wopr": [0.71, 0.14],
        "carries": [0, 14],
        "rushing_yards": [0, 76],
        "fantasy_points_ppr": [16.8, 11.1],
        "some_unused_col": [1, 2],            # not in _KEEP -> dropped
    })


def _fake_schedules():
    return pd.DataFrame({
        "game_id": ["2023_01_X", "2024_01_Y", "2024_02_Z"],
        "season": [2023, 2024, 2024],
        "game_type": ["REG", "REG", "REG"],
        "week": [1, 1, 2],
        "away_team": ["AAA", "CCC", "AAA"],
        "home_team": ["BBB", "DDD", "CCC"],
        "away_score": [17, 20, 24],
        "home_score": [20, 13, 21],
        "result": [-3, 7, 3],
        "spread_line": [-2.5, 3.0, 1.0],
        "roof": ["outdoors", "dome", "outdoors"],
        "junk": [0, 0, 0],
    })


def test_registry_lists_the_datasets():
    assert set(DATASETS) == {
        "player_stats", "schedules", "snap_counts",
        "ngs_passing", "ngs_receiving", "ngs_rushing",
        "pfr_pass", "pfr_rec", "pfr_rush", "pfr_def",
        "injuries",
    }


def test_player_stats_tidies_and_filters_regular_season(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_player_stats())
    df = nflref.load("player_stats", "2024")
    assert list(df["position"]) == ["WR"]              # POST row gone
    assert "season_type" not in df.columns
    assert "some_unused_col" not in df.columns
    assert "target_share" in df.columns and "wopr" in df.columns
    assert df.iloc[0]["target_share"] == pytest.approx(0.28)


def test_player_stats_2025_uses_stats_player_release_and_normalises_renames(monkeypatch):
    # nflverse retired the `player_stats` release after 2024; 2025+ comes from
    # `stats_player/stats_player_week_<year>.parquet`, which renamed two cols.
    seen = {}

    def _fake(asset):
        seen["asset"] = asset
        return pd.DataFrame({
            "player_id": ["00-9"],
            "player_display_name": ["New Guy"],
            "position": ["WR"],
            "team": ["ZZZ"],                       # was `recent_team`
            "season": [2025],
            "week": [1],
            "season_type": ["REG"],
            "targets": [8],
            "receptions": [6],
            "receiving_yards": [70],
            "passing_interceptions": [0],          # was `interceptions`
            "target_share": [0.22],
            "wopr": [0.55],
            "fantasy_points_ppr": [13.0],
        })

    monkeypatch.setattr(api, "read_release_parquet", _fake)
    df = nflref.load("player_stats", "2025")
    assert seen["asset"] == "stats_player/stats_player_week_2025.parquet"
    assert "recent_team" in df.columns and "team" not in df.columns
    assert df.iloc[0]["recent_team"] == "ZZZ"
    assert "interceptions" in df.columns and "passing_interceptions" not in df.columns
    # 2024 and earlier still route to the legacy asset
    assert PlayerStats()._asset("2024") == "player_stats/player_stats_2024.parquet"


def test_player_stats_before_earliest_is_empty(monkeypatch):
    called = {"n": 0}

    def _boom(asset):
        called["n"] += 1
        raise AssertionError("should not fetch before EARLIEST")

    monkeypatch.setattr(api, "read_release_parquet", _boom)
    assert nflref.load("player_stats", "2010").empty
    assert called["n"] == 0


def _fake_snap_counts():
    return pd.DataFrame({
        "game_id": ["2024_01_A_B", "2024_01_A_B"],
        "season": [2024, 2024], "game_type": ["REG", "REG"], "week": [1, 1],
        "player": ["Off Guy", "ST Guy"], "pfr_player_id": ["p1", "p2"],
        "position": ["WR", "LB"], "team": ["AAA", "AAA"], "opponent": ["BBB", "BBB"],
        "offense_snaps": [60, 0], "offense_pct": [0.9, 0.0],
        "defense_snaps": [0, 55], "defense_pct": [0.0, 0.85],
        "st_snaps": [5, 20], "st_pct": [0.2, 0.7],
        "junk": [1, 2],
    })


def test_snap_counts_tidies_and_keeps_all_three_sides(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_snap_counts())
    df = nflref.load("snap_counts", "2024")
    assert "junk" not in df.columns
    assert {"offense_pct", "defense_pct", "st_pct"}.issubset(df.columns)
    off, st = df.iloc[0], df.iloc[1]
    assert off["offense_pct"] == 0.9 and off["defense_pct"] == 0.0
    assert st["defense_pct"] == 0.85 and st["st_pct"] == 0.7


def test_snap_counts_before_earliest_is_empty(monkeypatch):
    def _boom(asset):
        raise AssertionError("should not fetch before EARLIEST")
    monkeypatch.setattr(api, "read_release_parquet", _boom)
    assert nflref.load("snap_counts", "2011").empty


def _fake_ngs_receiving():
    return pd.DataFrame({
        "season": [2023, 2024, 2024],
        "season_type": ["REG", "REG", "REG"], "week": [0, 0, 1],
        "player_display_name": ["Old Guy", "New Guy", "New Guy"],
        "player_position": ["WR", "WR", "WR"], "team_abbr": ["AAA", "BBB", "BBB"],
        "player_gsis_id": ["g1", "g2", "g2"],
        "receptions": [50, 60, 6], "targets": [80, 90, 9],
        "catch_percentage": [62.5, 66.7, 66.7], "yards": [600, 700, 70],
        "rec_touchdowns": [4, 5, 1],
        "avg_cushion": [6.5, 5.9, 5.9], "avg_separation": [3.1, 2.8, 2.8],
        "avg_intended_air_yards": [9.0, 8.5, 8.5],
        "percent_share_of_intended_air_yards": [0.2, 0.22, 0.22],
        "avg_yac": [4.5, 5.0, 5.0], "avg_expected_yac": [4.0, 4.6, 4.6],
        "avg_yac_above_expectation": [0.5, 0.4, 0.4],
        "junk": [1, 2, 3],
    })


def test_ngs_receiving_slices_the_all_seasons_file_before_snapshotting(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_ngs_receiving())
    df = nflref.load("ngs_receiving", "2024")
    assert set(df["season"]) == {2024}
    assert list(df["player_display_name"]) == ["New Guy", "New Guy"]
    assert "junk" not in df.columns
    assert "avg_separation" in df.columns and "avg_cushion" in df.columns
    # snapshot on disk is the sliced 2024 frame, not the all-seasons file
    snap = cache.load("ngs_receiving", "2024")
    assert set(snap["season"]) == {2024} and len(snap) == 2


def test_ngs_receiving_asset_is_one_flat_file_not_per_season():
    from webapp.sources.nflref.nextgen_stats import NgsReceiving
    assert NgsReceiving()._asset("2016") == NgsReceiving()._asset("2024")
    assert NgsReceiving()._asset("2024") == "nextgen_stats/ngs_receiving.parquet"


def test_ngs_before_earliest_is_empty(monkeypatch):
    def _boom(asset):
        raise AssertionError("should not fetch before EARLIEST")
    monkeypatch.setattr(api, "read_release_parquet", _boom)
    assert nflref.load("ngs_passing", "2015").empty
    assert nflref.load("ngs_receiving", "2015").empty
    assert nflref.load("ngs_rushing", "2015").empty


def _fake_pfr_rush():
    return pd.DataFrame({
        "season": [2024], "week": [1], "game_type": ["REG"],
        "team": ["AAA"], "opponent": ["BBB"],
        "pfr_player_name": ["Runner Guy"], "pfr_player_id": ["r1"],
        "carries": [18],
        "rushing_yards_before_contact": [40], "rushing_yards_before_contact_avg": [2.2],
        "rushing_yards_after_contact": [60], "rushing_yards_after_contact_avg": [3.3],
        "rushing_broken_tackles": [3], "receiving_broken_tackles": [0],
        "junk": [1],
    })


def test_pfr_rush_tidies_role_specific_columns(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_pfr_rush())
    df = nflref.load("pfr_rush", "2024")
    assert "junk" not in df.columns
    assert df.iloc[0]["rushing_yards_after_contact"] == 60
    assert df.iloc[0]["rushing_broken_tackles"] == 3
    from webapp.sources.nflref.pfr_advstats import PfrRush
    assert PfrRush()._asset("2024") == "pfr_advstats/advstats_week_rush_2024.parquet"


def test_pfr_roles_have_distinct_asset_paths():
    from webapp.sources.nflref.pfr_advstats import PfrPass, PfrRec, PfrRush, PfrDef
    assets = {cls()._asset("2024") for cls in (PfrPass, PfrRec, PfrRush, PfrDef)}
    assert len(assets) == 4   # pass/rec/rush/def each hit a different file


def test_pfr_before_earliest_is_empty(monkeypatch):
    def _boom(asset):
        raise AssertionError("should not fetch before EARLIEST")
    monkeypatch.setattr(api, "read_release_parquet", _boom)
    assert nflref.load("pfr_pass", "2017").empty
    assert nflref.load("pfr_rec", "2017").empty
    assert nflref.load("pfr_rush", "2017").empty
    assert nflref.load("pfr_def", "2017").empty


def _fake_injuries():
    return pd.DataFrame({
        "season": [2024, 2024], "game_type": ["REG", "REG"], "week": [1, 1],
        "team": ["AAA", "AAA"], "gsis_id": ["p1", "p2"],
        "position": ["WR", "RB"], "full_name": ["Hurt Guy", "Fine Guy"],
        "report_primary_injury": ["Hamstring", None],
        "report_secondary_injury": [None, None],
        "report_status": ["Questionable", None],
        "practice_primary_injury": ["Hamstring", None],
        "practice_secondary_injury": [None, None],
        "practice_status": ["Limited Participation in Practice", "Full Participation in Practice"],
        "date_modified": pd.to_datetime(["2024-09-06", "2024-09-06"]),
        "junk": [1, 2],
    })


def test_injuries_tidies_and_keeps_injury_type_detail(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_injuries())
    df = nflref.load("injuries", "2024")
    assert "junk" not in df.columns
    assert "report_primary_injury" in df.columns
    hurt = df[df["full_name"] == "Hurt Guy"].iloc[0]
    assert hurt["report_primary_injury"] == "Hamstring"
    assert hurt["report_status"] == "Questionable"
    fine = df[df["full_name"] == "Fine Guy"].iloc[0]
    assert pd.isna(fine["report_status"])   # listed on practice report only


def test_injuries_before_earliest_is_empty(monkeypatch):
    def _boom(asset):
        raise AssertionError("should not fetch before EARLIEST")
    monkeypatch.setattr(api, "read_release_parquet", _boom)
    assert nflref.load("injuries", "2008").empty


def test_schedules_slices_to_the_season_before_snapshotting(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_schedules())
    df = nflref.load("schedules", "2024")
    assert set(df["season"]) == {2024}
    assert list(df["week"]) == [1, 2]
    assert "junk" not in df.columns
    # snapshot on disk is the sliced 2024 frame, not the all-seasons file
    snap = cache.load("schedules", "2024")
    assert set(snap["season"]) == {2024} and len(snap) == 2


def test_snapshot_serves_when_network_gone(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_player_stats())
    first = nflref.load("player_stats", "2024")        # live -> writes snapshot
    assert not first.empty
    cache.clear()                                      # drop the mem cache

    def _no_net(asset):
        raise RuntimeError("offline")

    monkeypatch.setattr(api, "read_release_parquet", _no_net)
    again = nflref.load("player_stats", "2024")        # must come from disk
    assert list(again["position"]) == ["WR"]


def test_reload_bypasses_snapshot(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_player_stats())
    nflref.load("player_stats", "2024")

    hits = {"n": 0}

    def _count(asset):
        hits["n"] += 1
        return _fake_player_stats()

    monkeypatch.setattr(api, "read_release_parquet", _count)
    nflref.load("player_stats", "2024")               # snapshot hit, no fetch
    assert hits["n"] == 0
    nflref.load("player_stats", "2024", reload=True)  # forced live
    assert hits["n"] == 1


def test_unknown_dataset_returns_empty():
    assert nflref.load("not_a_dataset", "2024").empty


def test_upstream_failure_degrades_to_empty(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: (_ for _ in ()).throw(RuntimeError("500")))
    assert nflref.load("player_stats", "2024").empty
    assert nflref.load("schedules", "2024").empty


# --- nflref.summary (the NFL Stats tab's view helpers) -------------------

def _fake_weekly_player_stats():
    rows = []
    # 2 weeks x 3 players (WR, RB, QB)
    for wk in (1, 2):
        rows += [
            {"player_id": "00-W", "player_display_name": "W Rex", "position": "WR",
             "recent_team": "AAA", "season": 2024, "week": wk, "season_type": "REG",
             "targets": 10, "receptions": 7, "receiving_yards": 90, "receiving_tds": 1,
             "target_share": 0.30, "air_yards_share": 0.35, "wopr": 0.72, "racr": 1.1,
             "carries": 0, "rushing_yards": 0, "rushing_tds": 0,
             "attempts": 0, "completions": 0, "passing_yards": 0, "passing_tds": 0,
             "interceptions": 0, "pacr": None, "fantasy_points_ppr": 16.0},
            {"player_id": "00-R", "player_display_name": "R Back", "position": "RB",
             "recent_team": "AAA", "season": 2024, "week": wk, "season_type": "REG",
             "targets": 3, "receptions": 2, "receiving_yards": 12, "receiving_tds": 0,
             "target_share": 0.08, "air_yards_share": 0.05, "wopr": 0.15, "racr": 0.9,
             "carries": 18, "rushing_yards": 85, "rushing_tds": 1,
             "attempts": 0, "completions": 0, "passing_yards": 0, "passing_tds": 0,
             "interceptions": 0, "pacr": None, "fantasy_points_ppr": 20.0},
            {"player_id": "00-Q", "player_display_name": "Q Slinger", "position": "QB",
             "recent_team": "BBB", "season": 2024, "week": wk, "season_type": "REG",
             "targets": 0, "receptions": 0, "receiving_yards": 0, "receiving_tds": 0,
             "target_share": None, "air_yards_share": None, "wopr": None, "racr": None,
             "carries": 4, "rushing_yards": 20, "rushing_tds": 0,
             "attempts": 35, "completions": 24, "passing_yards": 280, "passing_tds": 2,
             "interceptions": 1, "pacr": 0.85, "fantasy_points_ppr": 22.0},
        ]
    return pd.DataFrame(rows)


def test_player_leaderboard_aggregates_to_season_totals(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    lb = nflref.player_leaderboard("2024", pos="ALL")
    assert list(lb["player"]) == ["Q Slinger", "R Back", "W Rex"]   # by PPR pts
    r = lb.set_index("player").loc["R Back"]
    assert r["games"] == 2
    assert r["carries"] == 36 and r["rush_yards"] == 170       # summed
    assert r["fpts_ppr"] == pytest.approx(40.0)                # summed
    assert r["ppg_ppr"] == pytest.approx(20.0)                 # total / games
    assert r["tgt_share"] == pytest.approx(0.08)               # season MEAN, not sum
    assert lb.iloc[0]["rank"] == 1


def test_player_leaderboard_position_filter(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    lb = nflref.player_leaderboard("2024", pos="QB")
    assert list(lb["player"]) == ["Q Slinger"]
    assert lb.iloc[0]["pass_yards"] == 560


def test_player_leaderboard_team_filter(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    # AAA has W Rex + R Back; BBB has Q Slinger only.
    aaa = nflref.player_leaderboard("2024", pos="ALL", team="AAA")
    assert set(aaa["player"]) == {"W Rex", "R Back"}
    assert list(aaa["team"].unique()) == ["AAA"]
    assert list(aaa["rank"]) == [1, 2]                 # re-ranked among AAA
    bbb = nflref.player_leaderboard("2024", pos="ALL", team="BBB")
    assert list(bbb["player"]) == ["Q Slinger"]
    # "ALL" / empty is a no-op
    assert len(nflref.player_leaderboard("2024", pos="ALL", team="ALL")) == 3
    assert len(nflref.player_leaderboard("2024", pos="ALL", team="")) == 3


def _fake_sleeper_wr_board():
    """Three WRs, ranked by fpts_ppr, for percentile_profile's sleeper-source
    path (bypasses nflref.player_leaderboard's nflverse aggregation)."""
    return pd.DataFrame([
        {"source": "sleeper", "rank": 1, "player_id": "1", "gsis_id": None,
         "player": "Top WR", "position": "WR", "team": "AAA", "games": 10,
         "targets": 120, "receptions": 90, "rec_yards": 1200, "rec_td": 10,
         "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
         "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
         "snap_share": 0.9, "tgt_share": 0.3, "rz_touches": 15, "air_yards": 900,
         "adot": 9.5, "fpts_ppr": 220.0, "ppg_ppr": 22.0},
        {"source": "sleeper", "rank": 2, "player_id": "2", "gsis_id": None,
         "player": "Mid WR", "position": "WR", "team": "BBB", "games": 10,
         "targets": 80, "receptions": 55, "rec_yards": 700, "rec_td": 4,
         "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
         "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
         "snap_share": 0.6, "tgt_share": 0.18, "rz_touches": 6, "air_yards": 500,
         "adot": 6.8, "fpts_ppr": 130.0, "ppg_ppr": 13.0},
        {"source": "sleeper", "rank": 3, "player_id": "3", "gsis_id": None,
         "player": "Low WR", "position": "WR", "team": "CCC", "games": 10,
         "targets": 30, "receptions": 18, "rec_yards": 200, "rec_td": 1,
         "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
         "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
         "snap_share": 0.3, "tgt_share": 0.07, "rz_touches": 1, "air_yards": 120,
         "adot": 4.0, "fpts_ppr": 40.0, "ppg_ppr": 4.0},
    ])


def test_percentile_profile_top_player_reads_100th(monkeypatch):
    """Uses rec_yards, not fpts_ppr -- fpts_ppr/ppg_ppr are fantasy-scoring
    outputs, excluded from radar profiles entirely (see
    test_percentile_profile_excludes_fantasy_scoring_columns below); this
    test is about the percentile-ranking mechanics, which any real stat
    column exercises identically."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    assert prof is not None
    assert prof["season"] == "2024" and prof["position"] == "WR"
    assert prof["n_population"] == 3
    pts = next(c for c in prof["columns"] if c["key"] == "rec_yards")
    assert pts["value"] == pytest.approx(1200.0)
    assert pts["percentile"] == 100.0                  # best of 3


def test_percentile_profile_mid_and_worst_player(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    mid = nflref.percentile_profile("2024", "WR", "2", source="sleeper")
    worst = nflref.percentile_profile("2024", "WR", "3", source="sleeper")
    mid_pts = next(c for c in mid["columns"] if c["key"] == "rec_yards")
    worst_pts = next(c for c in worst["columns"] if c["key"] == "rec_yards")
    assert 0 < worst_pts["percentile"] < mid_pts["percentile"] < 100  # never a hard 0


def test_percentile_profile_unknown_player_returns_none(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    assert nflref.percentile_profile("2024", "WR", "does-not-exist", source="sleeper") is None


def test_percentile_profile_empty_board_returns_none(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: pd.DataFrame())
    assert nflref.percentile_profile("2024", "WR", "1", source="sleeper") is None


def test_percentile_profile_default_stat_mode_is_total(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    assert prof["stat_mode"] == "total"
    rec_yds = next(c for c in prof["columns"] if c["key"] == "rec_yards")
    assert rec_yds["value"] == pytest.approx(1200.0)
    assert rec_yds["label"] == "Rec yds"


def test_percentile_profile_per_game_divides_counting_stats_by_games(monkeypatch):
    """Top WR: rec_yards=1200 over 10 games -> a per-game rate of 120, ranked
    against the field's own per-game rates, not the raw totals. The LABEL
    stays plain ("Rec yds", not "Rec yds/G") -- the total/per-game distinction
    is the toggle itself, not something every spoke name needs to restate."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper",
                                     stat_mode="per_game")
    assert prof["stat_mode"] == "per_game"
    rec_yds = next(c for c in prof["columns"] if c["key"] == "rec_yards")
    assert rec_yds["value"] == pytest.approx(120.0)
    assert rec_yds["label"] == "Rec yds"
    assert rec_yds["percentile"] == 100.0  # still the best of 3 on a per-game basis too


def test_percentile_profile_per_game_leaves_already_rate_columns_alone(monkeypatch):
    """snap_share/tgt_share/adot are already rates -- per_game mode must not
    divide them again by games. (ppg_ppr was also in _ALREADY_RATE_KEYS, but
    is now excluded from radar profiles entirely as a fantasy-scoring output
    -- see test_percentile_profile_excludes_fantasy_scoring_columns -- so
    it's dropped from this loop rather than asserting on a key that no
    longer appears in `columns` at all.)"""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    total = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    per_game = nflref.percentile_profile("2024", "WR", "1", source="sleeper",
                                         stat_mode="per_game")
    for key in ("snap_share", "tgt_share", "adot"):
        t = next(c for c in total["columns"] if c["key"] == key)
        p = next(c for c in per_game["columns"] if c["key"] == key)
        assert t["value"] == pytest.approx(p["value"])
        assert t["label"] == p["label"]  # no "/G" suffix added


def test_percentile_profile_per_game_drops_games_column(monkeypatch):
    """`games` itself isn't a performance stat -- excluded from per_game mode
    (every player's own "games per game" would be a trivial, meaningless 1.0)."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    per_game = nflref.percentile_profile("2024", "WR", "1", source="sleeper",
                                         stat_mode="per_game")
    assert all(c["key"] != "games" for c in per_game["columns"])


def test_percentile_profile_axis_ticks_present_for_pizza_chart(monkeypatch):
    """Every column carries axis_ticks -- 5 real-value reference points at
    20/40/60/80/100, the pizza-chart radar's own per-spoke scale."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    pts = next(c for c in prof["columns"] if c["key"] == "rec_yards")
    ticks = pts["axis_ticks"]
    assert [t["percentile"] for t in ticks] == [20, 40, 60, 80, 100]
    # 100th-percentile tick is the field's real max (1200.0, Top WR's own value)
    assert ticks[-1]["value"] == pytest.approx(1200.0)


def test_percentile_profile_excludes_fantasy_scoring_columns(monkeypatch):
    """A radar profile should only compare REAL on-field production, not a
    fantasy-scoring output derived from that same production (per user
    request). fpts_ppr/ppg_ppr are excluded entirely, in BOTH stat_modes --
    `games` is excluded too (metadata, not a stat -- it was already dropped
    in per_game mode via a separate mechanism, but now also in total mode).
    Real stats (rec_yards etc.) are unaffected and still present."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    for mode in ("total", "per_game"):
        prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper",
                                         stat_mode=mode)
        keys = {c["key"] for c in prof["columns"]}
        assert "fpts_ppr" not in keys
        assert "ppg_ppr" not in keys
        assert "games" not in keys
        assert "rec_yards" in keys


def test_percentile_profile_axis_ticks_ascend_for_higher_is_better_stat(monkeypatch):
    """A normal (higher-is-better) stat's ticks rise from the 20th to the
    100th percentile ring, matching "further out on the spoke = better"."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    ticks = next(c for c in prof["columns"] if c["key"] == "rec_yards")["axis_ticks"]
    values = [t["value"] for t in ticks]
    assert values == sorted(values)


def test_percentile_profile_axis_ticks_descend_for_lower_is_better_stat(monkeypatch):
    """pts_allow/yds_allow are LOWER-is-better -- the 100th-percentile ring
    (best defense, outermost point) must be the field's MINIMUM, not its
    maximum, so ticks descend outward instead of ascending."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    prof = nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")
    ticks = next(c for c in prof["columns"] if c["key"] == "pts_allow")["axis_ticks"]
    values = [t["value"] for t in ticks]
    assert values == sorted(values, reverse=True)


def test_schedule_grid_team_filter(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_games())
    # _fake_games: AAA@BBB (wk1), CCC@DDD (wk1), AAA@CCC (wk2)
    aaa = nflref.schedule_grid("2024", team="AAA")
    assert len(aaa) == 2                                # both AAA games, any side
    assert set(aaa["week"]) == {1, 2}
    ddd = nflref.schedule_grid("2024", team="DDD")
    assert len(ddd) == 1 and list(ddd["week"]) == [1]
    # combined with a week filter
    aaa_wk2 = nflref.schedule_grid("2024", week=2, team="AAA")
    assert len(aaa_wk2) == 1 and list(aaa_wk2["home_team"]) == ["CCC"]


def test_compare_sources_passes_team_through(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from sleepermetrics import nflstats
    sl = pd.DataFrame([{
        "source": "sleeper", "rank": 1, "player_id": "9", "gsis_id": None,
        "player": "W Rex", "position": "WR", "team": "AAA", "games": 2,
        "targets": 18, "receptions": 12, "rec_yards": 150, "rec_td": 1,
        "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0, "pass_cmp": 0,
        "pass_yards": 0, "pass_td": 0, "pass_int": 0, "snap_share": 0.9,
        "tgt_share": 0.3, "rz_touches": 2, "air_yards": 0, "adot": None,
        "fpts_ppr": 30.0, "ppg_ppr": 15.0,
    }])
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: sl.copy())
    # BBB has no WR in either feed -> nothing matches, still no crash
    cmp = nflref.compare_sources("2024", pos="WR", team="BBB")
    assert cmp["summary"]["matched"] == 0
    # AAA does line W Rex up on both sides
    cmp2 = nflref.compare_sources("2024", pos="WR", team="AAA")
    assert cmp2["summary"]["matched"] == 1


# The webapp route strict-validates `team` against nflref.summary.TEAMS
# (real NFL abbreviations), so the route-level fixture uses real ones.
def _fake_weekly_real_teams():
    df = _fake_weekly_player_stats()
    df["recent_team"] = df["recent_team"].map({"AAA": "KC", "BBB": "BUF"})
    return df


def test_nflstats_data_route_team_filter(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_real_teams())
    from webapp import app
    resp = app.nflstats_data(_Req(), view="players", season="2024",
                             pos="ALL", team="BUF")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "Q Slinger" in body and "W Rex" not in body
    assert "BUF &middot;" in body or "BUF ·" in body
    # an abbreviation NOT in TEAMS falls back to no filter (all 3 players)
    allr = app.nflstats_data(_Req(), view="players", season="2024",
                             pos="ALL", team="ZZZ").body.decode()
    assert "Q Slinger" in allr and "W Rex" in allr


def test_nflstats_export_csv_route_team_in_stem(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_real_teams())
    from webapp import app
    r = app.nflstats_export_csv(view="players", season="2024", pos="RB", team="KC")
    assert 'filename="nfl-players-nflverse-2024-rb-kc.csv"' in r.headers["content-disposition"]


def test_leaderboard_columns_switches_on_qb():
    skill = [k for k, _ in nflref.leaderboard_columns("WR")]
    qb = [k for k, _ in nflref.leaderboard_columns("QB")]
    assert "tgt_share" in skill and "wopr" in skill
    assert "pass_yards" in qb and "pass_td" in qb
    assert "tgt_share" not in qb


def test_leaderboard_columns_def_is_its_own_set():
    d = [k for k, _ in nflref.leaderboard_columns("DEF")]
    assert "sacks" in d and "pts_allow" in d and "yds_allow" in d
    # no offense-usage concept has a DEF equivalent
    assert "snap_share" not in d and "tgt_share" not in d and "adot" not in d
    # a DEF request against the nflverse source still gets the DEF (sleeper)
    # column set -- nflverse has no DEF rows to render at all, so the offense
    # skill-position default would be equally moot, and misleading besides.
    assert nflref.leaderboard_columns("DEF", source="nflverse") == \
        nflref.leaderboard_columns("DEF", source="sleeper")


def test_player_leaderboard_def_source_nflverse_is_empty():
    """nflverse's player_stats release has no team-defense row shape at all
    (see CLAUDE.md / the DEF-stats investigation) -- pos="DEF" against that
    source must degrade to empty, not error, same as any other no-match
    filter on this leaderboard."""
    assert nflref.player_leaderboard("2024", pos="DEF", source="nflverse").empty


def _fake_sleeper_def_board():
    return pd.DataFrame([
        {"source": "sleeper", "rank": 1, "player_id": "AAA", "gsis_id": None,
         "player": "AAA", "position": "DEF", "team": "AAA", "games": 10,
         "sacks": 40, "ints": 20, "forced_fumbles": 10, "fumble_rec": 8,
         "def_td": 3, "safeties": 1, "blk_kick": 2, "tackles": 900,
         "qb_hits": 100, "pts_allow": 280, "yds_allow": 5200,
         "fpts_ppr": 160.0, "ppg_ppr": 16.0},
        {"source": "sleeper", "rank": 2, "player_id": "BBB", "gsis_id": None,
         "player": "BBB", "position": "DEF", "team": "BBB", "games": 10,
         "sacks": 20, "ints": 8, "forced_fumbles": 4, "fumble_rec": 3,
         "def_td": 0, "safeties": 0, "blk_kick": 0, "tackles": 950,
         "qb_hits": 60, "pts_allow": 450, "yds_allow": 5900,
         "fpts_ppr": 60.0, "ppg_ppr": 6.0},
    ])


def test_percentile_profile_def_pts_allow_direction_is_lower_is_better(monkeypatch):
    """pts_allow/yds_allow must rank the OPPOSITE direction from every other
    column: fewer points/yards allowed is the better outcome, so the best
    defense (AAA, 280 pts allowed) must read a HIGH percentile there, not a
    low one -- the bug this test guards regressed once already before
    _LOWER_IS_BETTER was added."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    best = nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")
    worst = nflref.percentile_profile("2024", "DEF", "BBB", source="sleeper")
    best_pa = next(c for c in best["columns"] if c["key"] == "pts_allow")
    worst_pa = next(c for c in worst["columns"] if c["key"] == "pts_allow")
    assert best_pa["percentile"] == 100.0
    assert worst_pa["percentile"] < best_pa["percentile"]
    # an ordinary "higher is better" column keeps the normal direction
    best_sacks = next(c for c in best["columns"] if c["key"] == "sacks")
    assert best_sacks["percentile"] == 100.0


def _fake_games():
    return pd.DataFrame({
        "game_id": ["2024_01_A_B", "2024_01_C_D", "2024_02_A_C"],
        "season": [2024, 2024, 2024], "game_type": ["REG", "REG", "REG"],
        "week": [1, 1, 2],
        "gameday": ["2024-09-05", "2024-09-08", "2024-09-15"],
        "away_team": ["AAA", "CCC", "AAA"], "home_team": ["BBB", "DDD", "CCC"],
        "away_score": [17.0, 20.0, 24.0], "home_score": [20.0, 13.0, 21.0],
        "result": [3.0, -7.0, -3.0], "total": [37.0, 33.0, 45.0],
        "total_line": [44.5, 41.0, 47.5], "overtime": [0, 0, 1],
        "roof": ["outdoors", "dome", "outdoors"],
        "surface": ["grass", "fieldturf", "grass"],
        "away_rest": [7, 7, 7], "home_rest": [7, 10, 7],
        "stadium": ["X", "Y", "Z"],
    })


def test_schedule_grid_adds_margin_and_filters_week(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_games())
    full = nflref.schedule_grid("2024")
    assert len(full) == 3
    assert list(full["margin"]) == [3, 7, 3]                   # |home - away|
    wk1 = nflref.schedule_grid("2024", week=1)
    assert set(wk1["week"]) == {1} and len(wk1) == 2
    assert nflref.schedule_weeks("2024") == [1, 2]


def test_schedule_grid_empty_when_dataset_absent(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: (_ for _ in ()).throw(RuntimeError("x")))
    assert nflref.schedule_grid("2024").empty
    assert nflref.schedule_weeks("2024") == []


# --- the NFL Stats landing-tab routes (webapp) --------------------------

def test_nflstats_data_route_players(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from webapp import app
    resp = app.nflstats_data(_Req(), view="players", season="2024", pos="RB")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "R Back" in body and "Rush yds" in body
    assert "Q Slinger" not in body                # RB filter


_FAKE_SLEEPER_DUMP = {
    "4262921": {"full_name": "Ja'Marr Chase", "position": "WR", "team": "CIN",
                "gsis_id": "00-0036900"},
}


@pytest.fixture
def _fake_identity(monkeypatch):
    """identity._raw_players() reads straight off disk whenever a same-day
    sleeperPlayerData_py.pkl already exists, which is true on a dev machine
    that has run the app locally (not on a clean CI checkout). Stubbing only
    `sleeper_api` therefore silently no-ops on such a machine -- the disk
    branch never calls it at all. Patch `_raw_players` itself instead, so
    the fake dump is used unconditionally regardless of what's on disk."""
    from webapp.sources.ffadp import identity
    monkeypatch.setattr(identity, "_raw_players", lambda: dict(_FAKE_SLEEPER_DUMP))
    identity._idx = None
    yield
    identity._idx = None


def test_nflstats_players_row_has_portrait(monkeypatch, _fake_identity):
    # a real player name so ffadp.identity resolves it to a Sleeper id
    df = pd.DataFrame([{
        "player_id": "00-0036900", "player_display_name": "Ja'Marr Chase",
        "position": "WR", "recent_team": "CIN", "season": 2024, "week": 1,
        "season_type": "REG", "targets": 12, "receptions": 9,
        "receiving_yards": 120, "fantasy_points_ppr": 21.0,
    }])
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: df)
    from webapp import app
    resp = app.nflstats_data(_Req(), view="players", season="2024", pos="WR",
                             source="nflverse")
    body = resp.body.decode()
    assert 'class="pface" src="https://sleepercdn.com/content/nfl/players/' in body
    assert "Ja&#39;Marr Chase" in body or "Ja'Marr Chase" in body


def test_attach_sleeper_ids_resolves_and_passes_through(_fake_identity):
    from webapp.app import _attach_sleeper_ids
    rows = [
        {"player": "Ja'Marr Chase", "position": "WR", "player_id": "00-0036900"},
        {"player": "Nobody At All", "position": "WR", "player_id": None},
        {"player": "Sleeper Native", "position": "RB", "player_id": "1234"},
        # a name that would NOT resolve by name+position alone (only the
        # real gsis_id match should find this row)
        {"player": "Some Other Name", "position": "WR", "player_id": "00-0036900"},
    ]
    _attach_sleeper_ids(rows)
    assert rows[0]["sleeper_id"] == "4262921"                         # gsis-resolved
    assert rows[1]["sleeper_id"] is None                              # unknown
    assert rows[2]["sleeper_id"] == "1234"                            # digit id passes through
    assert rows[3]["sleeper_id"] == "4262921"                         # gsis wins over name mismatch


def test_nflstats_data_route_schedule(monkeypatch):
    # Week/Team are client-side filters on the schedule view now (see the
    # data-nfl-clientfilter note in _nflstats_compare.html): the route always
    # fetches the WHOLE season regardless of the submitted `week`, so the
    # browser can filter already-loaded rows with no further request. All 3
    # of _fake_games' games (2 in week 1, 1 in week 2) come back either way,
    # and each row carries data-week/data-team for the client filter to read.
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_games())
    from webapp import app
    resp = app.nflstats_data(_Req(), view="schedule", season="2024", week="1")
    body = resp.body.decode()
    assert "3 games" in body and "Margin" in body
    assert 'data-week="1"' in body and 'data-week="2"' in body


def test_nflstats_data_route_degrades_to_message(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: (_ for _ in ()).throw(RuntimeError("down")))
    from webapp import app
    resp = app.nflstats_data(_Req(), view="players", season="2024")
    assert "No NFL data available" in resp.body.decode()


def test_nflstats_data_route_source_sleeper(monkeypatch):
    # the players view with source=sleeper delegates to nflstats -- stub its
    # leaderboard so no network is touched.
    from sleepermetrics import nflstats
    from webapp import app
    fake = pd.DataFrame([{
        "source": "sleeper", "rank": 1, "player_id": "1", "gsis_id": None,
        "player": "Sleeper Guy", "position": "WR", "team": "AAA", "games": 10,
        "targets": 90, "receptions": 60, "rec_yards": 800, "rec_td": 6,
        "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
        "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
        "snap_share": 0.8, "tgt_share": 0.25, "rz_touches": 8, "air_yards": 700,
        "adot": 7.8, "fpts_ppr": 140.0, "ppg_ppr": 14.0,
    }])
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: fake.copy())
    resp = app.nflstats_data(_Req(), view="players", season="2024", pos="WR",
                             source="sleeper")
    body = resp.body.decode()
    assert "Sleeper Guy" in body
    assert "Snap share" in body and "RZ touch" in body      # sleeper column set
    assert "Sleeper</strong>\n    feed" in body or "Sleeper</strong>" in body


def test_nflstats_data_route_compare(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from sleepermetrics import nflstats
    from webapp import app
    # a sleeper leaderboard that overlaps _fake_weekly_player_stats on "W Rex"
    # but disagrees on targets / rec_yards.
    sl = pd.DataFrame([{
        "source": "sleeper", "rank": 1, "player_id": "x", "gsis_id": None,
        "player": "W Rex", "position": "WR", "team": "AAA", "games": 2,
        "targets": 25, "receptions": 16, "rec_yards": 210, "rec_td": 2,
        "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
        "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
        "snap_share": None, "tgt_share": None, "rz_touches": 0,
        "air_yards": 0, "adot": None, "fpts_ppr": 42.0, "ppg_ppr": 21.0,
    }])
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: sl.copy())
    resp = app.nflstats_data(_Req(), view="compare", season="2024", pos="WR")
    body = resp.body.decode()
    assert "Sleeper vs nflverse" in body
    assert "W Rex" in body
    assert "matched" in body and "differ" in body


def test_compare_sources_join_and_delta(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from sleepermetrics import nflstats
    sl = pd.DataFrame([
        {"source": "sleeper", "rank": 1, "player_id": "a", "gsis_id": None,
         "player": "W Rex", "position": "WR", "team": "AAA", "games": 2,
         "targets": 22, "receptions": 14, "rec_yards": 190, "rec_td": 2,
         "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
         "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
         "snap_share": None, "tgt_share": None, "rz_touches": 0, "air_yards": 0,
         "adot": None, "fpts_ppr": 40.0, "ppg_ppr": 20.0},
        {"source": "sleeper", "rank": 2, "player_id": "b", "gsis_id": None,
         "player": "Only Sleeper", "position": "WR", "team": "BBB", "games": 1,
         "targets": 5, "receptions": 3, "rec_yards": 40, "rec_td": 0,
         "carries": 0, "rush_yards": 0, "rush_td": 0, "pass_att": 0,
         "pass_cmp": 0, "pass_yards": 0, "pass_td": 0, "pass_int": 0,
         "snap_share": None, "tgt_share": None, "rz_touches": 0, "air_yards": 0,
         "adot": None, "fpts_ppr": 8.0, "ppg_ppr": 8.0},
    ])
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: sl.copy())

    cmp = nflref.compare_sources("2024", pos="WR")
    # _fake_weekly_player_stats' W Rex: 20 tgt, 180 rec_yds over 2 wks.
    assert cmp["summary"]["matched"] == 1              # only W Rex overlaps
    assert cmp["summary"]["sleeper_only"] == 1         # "Only Sleeper"
    assert len(cmp["rows"]) == 1
    row = cmp["rows"][0]
    assert row["player"] == "W Rex"
    assert row["targets_sleeper"] == 22 and row["targets_nflverse"] == 20
    assert row["targets_delta"] == 2                   # SL - NV
    assert row["rec_yards_delta"] == 10               # 190 - 180
    # PPR pts: sleeper 40.0 vs nflverse 16.0/wk * 2wk = 32.0 -> delta 8.0
    assert row["fpts_ppr_delta"] == pytest.approx(8.0)
    assert row["total_abs_delta"] == pytest.approx(2 + 10 + 8.0)


def test_compare_sources_empty_when_a_source_missing(monkeypatch):
    # nflverse is dead, but compare_sources still builds the Sleeper side of
    # the join internally (via sleepermetrics.nflstats.player_leaderboard() ->
    # players()), which falls through to a live sleeper_api() call with no
    # same-day pkl on disk. nflstats.py binds `players` as a bare name
    # (`from .players import players`), so patch that name directly rather
    # than sleepermetrics.players -- the package's own `from .players import
    # players` in __init__.py shadows the submodule with the function there.
    from sleepermetrics import nflstats
    import pandas as pd
    nflstats._lb_cache.clear()  # a cache hit would skip players() entirely
    empty_pool = pd.DataFrame(columns=["player_id", "position", "team", "player_name"])
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: empty_pool)
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: (_ for _ in ()).throw(RuntimeError("x")))
    cmp = nflref.compare_sources("2024", pos="WR")
    assert cmp["rows"] == []
    assert cmp["summary"]["matched"] == 0


def test_nflstats_export_csv_route(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from webapp import app
    r = app.nflstats_export_csv(view="players", season="2024", pos="WR")
    assert r.status_code == 200 and r.media_type == "text/csv"
    assert 'filename="nfl-players-nflverse-2024-wr.csv"' in r.headers["content-disposition"]
    assert "W Rex" in r.body.decode()


def test_nflstats_export_csv_route_compare(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda asset: _fake_weekly_player_stats())
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: pd.DataFrame())      # -> empty compare
    from webapp import app
    r = app.nflstats_export_csv(view="compare", season="2024", pos="WR")
    assert r.status_code == 200
    assert 'filename="nfl-compare-2024-wr.csv"' in r.headers["content-disposition"]


class _Req:
    """Minimal stand-in for starlette's Request -- TemplateResponse only needs
    `.scope` / attribute access, and the fragment templates use neither."""
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None
