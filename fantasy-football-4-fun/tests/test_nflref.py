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
        "player_stats", "schedules", "player_games", "snap_counts",
        "ngs_passing", "ngs_receiving", "ngs_rushing",
        "pfr_pass", "pfr_rec", "pfr_rush", "pfr_def",
        "injuries", "route_participation", "pass_plays",
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


def test_percentile_profile_drops_snap_share_for_qbs_only(monkeypatch):
    """A QB plays essentially every snap, so snap share carries no signal on
    his radar; every other position keeps it."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    qb = nflref.percentile_profile("2024", "QB", "1", source="sleeper")
    wr = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    assert "snap_share" not in {c["key"] for c in qb["columns"]}
    assert "snap_share" in {c["key"] for c in wr["columns"]}


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


def test_percentile_profile_axis_ticks_are_evenly_spaced_between_field_bounds(monkeypatch):
    """The rings step evenly in VALUE from the field's min to its max (the
    field only sets the bounds), so a stat where much of the field is tied or
    zero no longer prints repeated ring values."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    prof = nflref.percentile_profile("2024", "WR", "1", source="sleeper")
    ticks = next(c for c in prof["columns"] if c["key"] == "rec_yards")["axis_ticks"]
    # rec_yards field: 200 / 700 / 1200 -> lo 200, hi 1200
    assert [t["value"] for t in ticks] == pytest.approx([400, 600, 800, 1000, 1200])
    steps = [b["value"] - a["value"] for a, b in zip(ticks, ticks[1:])]
    assert steps == pytest.approx([200] * 4)


def test_percentile_profile_lower_is_better_ticks_are_evenly_spaced_descending(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    prof = nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")
    ticks = next(c for c in prof["columns"] if c["key"] == "pts_allow")["axis_ticks"]
    # pts_allow field: 280 (best) / 450 (worst); outer rim is the best (280)
    assert [t["value"] for t in ticks] == pytest.approx([416, 382, 348, 314, 280])


def test_percentile_profile_scaled_matches_the_ring_scale(monkeypatch):
    """`scaled` is the dot's radius on the same linear scale as the rings:
    the field max reads 100, the field min 0, and the middle value sits
    proportionally (NOT at its rank percentile)."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    top = next(c for c in nflref.percentile_profile("2024", "WR", "1", source="sleeper")["columns"]
               if c["key"] == "rec_yards")
    mid = next(c for c in nflref.percentile_profile("2024", "WR", "2", source="sleeper")["columns"]
               if c["key"] == "rec_yards")
    low = next(c for c in nflref.percentile_profile("2024", "WR", "3", source="sleeper")["columns"]
               if c["key"] == "rec_yards")
    assert (top["scaled"], mid["scaled"], low["scaled"]) == (100.0, 50.0, 0.0)
    # rank percentile for the middle of three is NOT 50 -- the two differ
    assert mid["percentile"] != mid["scaled"]


def test_percentile_profile_lower_is_better_scaled_puts_best_at_the_rim(monkeypatch):
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    best = next(c for c in nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")["columns"]
                if c["key"] == "pts_allow")
    worst = next(c for c in nflref.percentile_profile("2024", "DEF", "BBB", source="sleeper")["columns"]
                 if c["key"] == "pts_allow")
    assert (best["scaled"], worst["scaled"]) == (100.0, 0.0)


def test_percentile_profile_position_rank_and_ties(monkeypatch):
    """`rank` is 1 = best among players with a value; tied players share the
    best rank and are flagged `tied`. A lower-is-better stat ranks the
    smallest value first."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    cols = {c["key"]: c for c in
            nflref.percentile_profile("2024", "WR", "2", source="sleeper")["columns"]}
    assert (cols["rec_yards"]["rank"], cols["rec_yards"]["rank_of"]) == (2, 3)
    assert cols["rec_yards"]["tied"] is False
    # all three WRs have rush_td == 0: a three-way tie shares rank 1
    assert (cols["rush_td"]["rank"], cols["rush_td"]["tied"]) == (1, True)

    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    best = next(c for c in nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")["columns"]
                if c["key"] == "pts_allow")
    assert best["rank"] == 1


def test_percentile_profile_exposes_field_bounds_and_direction(monkeypatch):
    """`bounds` ([lo, hi] of the field) and `higher_is_better` let a caller
    widen the radar scale without recomputing the field."""
    from sleepermetrics import nflstats
    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_wr_board())
    col = next(c for c in nflref.percentile_profile("2024", "WR", "2", source="sleeper")["columns"]
               if c["key"] == "rec_yards")
    assert col["bounds"] == [200.0, 1200.0]
    assert col["higher_is_better"] is True

    monkeypatch.setattr(nflstats, "player_leaderboard",
                        lambda *a, **k: _fake_sleeper_def_board())
    d = next(c for c in nflref.percentile_profile("2024", "DEF", "AAA", source="sleeper")["columns"]
             if c["key"] == "pts_allow")
    assert d["bounds"] == [280.0, 450.0]
    assert d["higher_is_better"] is False


def test_axis_ticks_empty_when_field_has_no_range():
    """Every player identical (or no data) -> no scale to draw; the dot sits
    at 0 rather than dividing by zero."""
    from webapp.sources.nflref import summary
    assert summary._axis_ticks(pd.Series([0.0, 0.0, 0.0]), True) == []
    assert summary._axis_ticks(pd.Series([], dtype=float), True) == []
    assert summary._scaled_position(pd.Series([3.0, 3.0]), 3.0, True) == 0.0


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


# --- raw layer: the complete release file is kept before anything is derived ---

def _parquet_bytes(df):
    import io
    b = io.BytesIO()
    df.to_parquet(b, index=False)
    return b.getvalue()


def _fake_http(monkeypatch, payloads):
    """Replace requests.get inside api; `payloads` maps asset -> bytes."""
    calls = []

    class _Resp:
        def __init__(self, content):
            self.content = content
        def raise_for_status(self):
            pass

    def _get(url, **kw):
        calls.append(url)
        asset = url.split("/releases/download/")[1]
        return _Resp(payloads[asset])

    monkeypatch.setattr(api.requests, "get", _get)
    return calls


def test_download_keeps_the_complete_raw_file_then_derives(monkeypatch):
    wide = pd.DataFrame({"season": [2024], "week": [1], "player_id": ["x"],
                         "player_display_name": ["A B"], "position": ["WR"],
                         "recent_team": ["DET"], "targets": [7],
                         "an_unused_column": [1.5]})
    calls = _fake_http(monkeypatch, {"player_stats/player_stats_2024.parquet":
                                     _parquet_bytes(wide)})
    df = nflref.load("player_stats", "2024")
    assert len(calls) == 1
    assert "an_unused_column" not in df.columns                  # derived is trimmed
    raw = cache.load_raw("player_stats/player_stats_2024.parquet")
    assert "an_unused_column" in raw.columns                      # raw is complete
    assert cache.raw_path("player_stats/player_stats_2024.parquet").read_bytes() \
        == _parquet_bytes(wide)                                   # byte for byte


def test_missing_derived_is_rebuilt_from_raw_without_the_network(monkeypatch):
    wide = pd.DataFrame({"season": [2024], "week": [1], "player_id": ["x"],
                         "player_display_name": ["A B"], "position": ["WR"],
                         "recent_team": ["DET"], "targets": [7]})
    calls = _fake_http(monkeypatch, {"player_stats/player_stats_2024.parquet":
                                     _parquet_bytes(wide)})
    nflref.load("player_stats", "2024")
    cache._path("player_stats", "2024").unlink()                  # lose the derived file
    cache.clear()
    df = nflref.load("player_stats", "2024")
    assert len(calls) == 1 and len(df) == 1                       # no second download


def test_reload_downloads_again_and_replaces_raw(monkeypatch):
    a = pd.DataFrame({"season": [2024], "week": [1], "player_id": ["x"],
                      "player_display_name": ["A B"], "position": ["WR"],
                      "recent_team": ["DET"], "targets": [1]})
    b = a.assign(targets=9)
    pay = {"player_stats/player_stats_2024.parquet": _parquet_bytes(a)}
    calls = _fake_http(monkeypatch, pay)
    nflref.load("player_stats", "2024")
    pay["player_stats/player_stats_2024.parquet"] = _parquet_bytes(b)
    nflref.load("player_stats", "2024", reload=True)
    assert len(calls) == 2
    assert cache.load_raw("player_stats/player_stats_2024.parquet")["targets"].iloc[0] == 9


def test_all_seasons_file_is_downloaded_once_for_a_refresh_loop(monkeypatch):
    games = _fake_games()
    calls = _fake_http(monkeypatch, {"schedules/games.parquet": _parquet_bytes(games)})
    seasons = sorted({str(s) for s in games["season"]})
    for s in seasons:
        nflref.load("schedules", s, reload=True)
    assert len(calls) == 1 and len(seasons) >= 1
    cache.clear()                                                 # a new process / window
    nflref.load("schedules", seasons[0], reload=True)
    assert len(calls) == 2


def test_play_by_play_is_kept_raw_like_everything_else(monkeypatch):
    df = pd.DataFrame({"a": [1]})
    _fake_http(monkeypatch, {"pbp/play_by_play_2024.parquet": _parquet_bytes(df)})
    api.read_release_parquet("pbp/play_by_play_2024.parquet")
    assert cache.raw_path("pbp/play_by_play_2024.parquet").exists()
    assert cache.wants_raw("pbp_participation/pbp_participation_2024.parquet")


def test_store_release_keeps_the_file_without_parsing_it(monkeypatch):
    payload = _parquet_bytes(pd.DataFrame({"a": [1, 2]}))
    _fake_http(monkeypatch, {"pbp/play_by_play_2024.parquet": payload})
    monkeypatch.setattr(api.pd, "read_parquet",
                        lambda *a, **k: pytest.fail("store_release must not parse"))
    assert api.store_release("pbp/play_by_play_2024.parquet") == len(payload)
    assert cache.raw_path("pbp/play_by_play_2024.parquet").read_bytes() == payload


def _fake_route_inputs():
    pbp = pd.DataFrame({
        "game_id": ["G1", "G1", "G1"], "play_id": [1, 2, 3], "week": [1, 1, 1],
        "season": [2024, 2024, 2024], "play_type": ["pass", "pass", "run"],
        "receiver_player_id": ["00-W", None, None],
        "receiver_player_name": ["Wide R", None, None],
        "never_used_column": [9, 9, 9],
    })
    part = pd.DataFrame({
        "nflverse_game_id": ["G1", "G1", "G1"], "play_id": [1, 2, 3],
        "offense_players": ["00-W;00-Q", "00-W;00-Q", "00-W;00-Q"],
        "offense_names": ["Wide R;Quarter B", "Wide R;Quarter B", "Wide R;Quarter B"],
        "offense_positions": ["WR;QB", "WR;QB", "WR;QB"],
        "route": ["GO", None, None],
        "another_unused": [1, 1, 1],
    })
    return pbp, part


def test_route_participation_builds_from_raw_without_the_network(monkeypatch):
    pbp, part = _fake_route_inputs()
    calls = _fake_http(monkeypatch, {
        "pbp/play_by_play_2024.parquet": _parquet_bytes(pbp),
        "pbp_participation/pbp_participation_2024.parquet": _parquet_bytes(part)})
    monkeypatch.delenv("RENDER", raising=False)
    out = nflref.load("route_participation", "2024")
    assert len(calls) == 2 and not out.empty
    row = out[out["gsis_id"] == "00-W"].iloc[0]
    assert row["routes_run"] == 2 and row["targets"] == 1 and row["route_go"] == 1
    # the complete files are kept, including columns the build never reads
    assert "never_used_column" in cache.load_raw("pbp/play_by_play_2024.parquet").columns
    assert "another_unused" in cache.load_raw(
        "pbp_participation/pbp_participation_2024.parquet").columns
    cache._path("route_participation", "2024").unlink()      # lose the derived table
    cache.clear()
    again = nflref.load("route_participation", "2024")
    assert len(calls) == 2 and len(again) == len(out)          # rebuilt from raw


def test_route_participation_reads_only_the_columns_it_uses(monkeypatch):
    pbp, part = _fake_route_inputs()
    _fake_http(monkeypatch, {
        "pbp/play_by_play_2024.parquet": _parquet_bytes(pbp),
        "pbp_participation/pbp_participation_2024.parquet": _parquet_bytes(part)})
    nflref.load("route_participation", "2024")
    seen = []
    real = cache.load_raw
    monkeypatch.setattr(cache, "load_raw",
                        lambda asset, columns=None: seen.append((asset, columns)) or real(asset, columns))
    cache._path("route_participation", "2024").unlink()
    cache.clear()
    nflref.load("route_participation", "2024")
    assert all(cols is not None for _, cols in seen) and len(seen) == 2
    assert not any("never_used_column" in cols or "another_unused" in cols for _, cols in seen)


def test_render_does_not_write_raw_files(monkeypatch):
    monkeypatch.setattr(cache, "on_render", lambda: True)
    cache.save_raw("player_stats/player_stats_2024.parquet", b"x")
    assert not cache.raw_path("player_stats/player_stats_2024.parquet").exists()


# -- player_games: player rows joined to the schedule ---------------------------

def _pg_players():
    return pd.DataFrame({
        "player_id": ["00-1", "00-2", "00-3", "00-4"],
        "player_display_name": ["A B", "C D", "E F", "G H"],
        "position": ["WR", "RB", "WR", "WR"],
        "recent_team": ["LV", "DDD", "AAA", "AAA"],     # LV: current code for OAK
        "opponent_team": ["AAA", "DDD", "CCC", "BBB"],  # 00-2 is its own team (bad)
        "season": [2016, 2016, 2016, 2016],
        "week": [1, 1, 2, 22],
        "season_type": ["REG", "REG", "REG", "POST"],
        "targets": [5, 0, 7, 9],
        "receiving_yards": [60, 0, 80, 101],
        "carries": [0, 3, 0, 0],                        # 00-2 needs a stat to be kept
    })


def _pg_schedule():
    return pd.DataFrame({
        "game_id": ["g1", "g2", "g3", "g4"],
        "season": [2016] * 4,
        "week": [1, 1, 2, 22],
        "game_type": ["REG", "REG", "REG", "SB"],
        "gameday": ["2016-09-11"] * 4,
        "away_team": ["AAA", "CCC", "AAA", "AAA"],
        "home_team": ["OAK", "DDD", "CCC", "BBB"],      # OAK on the schedule
        "away_score": [20, 10, 3, 24],
        "home_score": [17, 10, 9, 24],
        "location": ["Home", "Home", "Home", "Neutral"],
        "spread_line": [3.0, -1.0, 2.5, -4.0],
        "roof": ["outdoors"] * 4, "surface": ["grass"] * 4,
    })


def test_player_games_joins_schedule_and_maps_old_team_codes():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule(), 2016)
    assert len(df) == 4                                  # the join never multiplies rows
    r1 = df[df.player_id == "00-1"].iloc[0]
    assert (r1.team, r1.opponent, r1.home_away) == ("LV", "AAA", "Home")
    assert r1.result == "L" and r1.team_score == 17 and r1.opp_score == 20
    assert r1.spread == -3.0                             # home favoured => negative for home


def test_player_games_takes_opponent_from_schedule_not_source():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule(), 2016).set_index("player_id")
    assert df.loc["00-2", "opponent"] == "CCC"           # source said its own team
    assert df.loc["00-2", "opponent_src"] == "DDD"


def test_player_games_keeps_playoffs_and_marks_neutral_sites():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule(), 2016).set_index("player_id")
    assert df.loc["00-4", "season_type"] == "POST"
    assert df.loc["00-4", "game_type"] == "SB"
    assert df.loc["00-4", "home_away"] == "Neutral"
    assert df.loc["00-3", "home_away"] == "Away"
    assert df.loc["00-4", "result"] == "T"


def test_player_games_falls_back_to_source_opponent_without_a_game():
    from webapp.sources.nflref import player_games as pg
    players = _pg_players()
    players.loc[0, "week"] = 9                           # no scheduled game that week
    df = pg.build(players, _pg_schedule(), 2016)
    row = df[df.player_id == "00-1"].iloc[0]
    assert row.opponent == "AAA" and pd.isna(row.home_away)


def test_player_games_renames_the_2025_team_columns():
    from webapp.sources.nflref import player_games as pg
    players = _pg_players().rename(columns={"recent_team": "team"})
    df = pg.build(players, _pg_schedule(), 2016)
    assert "team" in df.columns and df.player_id.tolist().count("00-1") == 1


def test_player_games_fetch_snapshots_and_serves_it(monkeypatch):
    def fake(asset, columns=None):
        return _pg_schedule() if asset.endswith("games.parquet") else _pg_players()
    monkeypatch.setattr(api, "read_release_parquet", fake)
    first = nflref.load("player_games", "2016")
    assert len(first) == 4
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    cache._mem.clear()
    assert len(nflref.load("player_games", "2016")) == 4        # from the snapshot


def test_player_games_before_earliest_is_empty():
    assert nflref.load("player_games", "1998").empty


def test_player_games_on_render_never_rebuilds(monkeypatch):
    monkeypatch.setattr(api, "on_render", lambda: True)
    monkeypatch.setattr(api, "read_release_parquet",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download")))
    assert nflref.load("player_games", "2016").empty


def test_player_games_probes_the_player_stats_asset_for_refresh():
    # one source for every season: only the combined release carries kicker data
    assert DATASETS["player_games"]._asset("2000") == "stats_player/stats_player_week_2000.parquet"
    assert DATASETS["player_games"]._asset("2024") == "stats_player/stats_player_week_2024.parquet"
    assert DATASETS["player_games"]._asset("2025") == "stats_player/stats_player_week_2025.parquet"


def _pg_wide():
    """A season in the combined release's shape: a receiver, a zero-stat receiver,
    a kicker, a kicker who did not kick, and a defender."""
    n = 5
    base = {"player_id": [f"00-{i}" for i in range(n)],
            "player_display_name": list("ABCDE"),
            "position": ["WR", "WR", "K", "K", "LB"],
            "recent_team": ["AAA"] * n, "opponent_team": ["BBB"] * n,
            "season": [2016] * n, "week": [1] * n, "season_type": ["REG"] * n,
            "targets": [6, 0, 0, 0, 0], "receptions": [4, 0, 0, 0, 0],
            "receiving_yards": [50, 0, 0, 0, 0],
            "fg_att": [0, 0, 3, 0, 0], "fg_made": [0, 0, 2, 0, 0],
            "fg_long": [float("nan"), float("nan"), 48, float("nan"), float("nan")],
            "pat_att": [0, 0, 2, 0, 0], "pat_made": [0, 0, 2, 0, 0],
            "fg_pct": [0.0, 0.0, 0.667, 0.0, 0.0], "def_tackles": [0, 0, 0, 0, 9]}
    return pd.DataFrame(base)


def test_player_games_keeps_only_offense_and_kickers_with_a_stat():
    from webapp.sources.nflref import player_games as pg
    sched = pd.DataFrame({
        "game_id": ["g1"], "season": [2016], "week": [1], "game_type": ["REG"],
        "gameday": ["2016-09-11"], "away_team": ["AAA"], "home_team": ["BBB"],
        "away_score": [10], "home_score": [7], "location": ["Home"], "spread_line": [1.0],
        "roof": ["outdoors"], "surface": ["grass"]})
    df = pg.build(_pg_wide(), sched, 2016)
    assert sorted(df.player_display_name) == ["A", "C"]      # receiver and the kicker who kicked
    assert "fg_made" in df.columns and "fg_long" in df.columns
    assert "def_tackles" not in df.columns and "fg_pct" not in df.columns


def test_player_games_blanks_targets_for_a_season_with_none_recorded():
    from webapp.sources.nflref import player_games as pg
    df = _pg_wide()
    out = pg._blank_unrecorded(df[df.position == "WR"])      # 6 targets league-wide
    assert out["targets"].isna().all()                       # not recorded, not zero
    assert out["receiving_yards"].tolist() == [50, 0]        # other stats untouched
    full = df.copy()
    full["targets"] = [150, 0, 0, 0, 0]
    assert pg._blank_unrecorded(full)["targets"].tolist() == [150, 0, 0, 0, 0]


def _pg_schedule_with_context():
    s = _pg_schedule()
    s["home_coach"] = ["HC1", "HC2", "HC3", "HC4"]
    s["away_coach"] = ["AC1", "AC2", "AC3", "AC4"]
    s["home_qb_id"] = ["hq1", "hq2", "hq3", "hq4"]
    s["away_qb_id"] = ["aq1", "aq2", "aq3", "aq4"]
    s["home_qb_name"] = ["Hq1", "Hq2", "Hq3", "Hq4"]
    s["away_qb_name"] = ["Aq1", "Aq2", "Aq3", "Aq4"]
    s["home_rest"] = [7, 7, 10, 14]
    s["away_rest"] = [6, 7, 7, 8]
    s["referee"] = ["Ref1", None, "Ref3", "Ref4"]
    s["weekday"] = ["Sunday", "Sunday", "Thursday", "Sunday"]
    s["temp"] = [float("nan"), 50.0, float("nan"), 40.0]
    s["wind"] = [float("nan"), 5.0, float("nan"), 3.0]
    s["div_game"] = [0, 1, 0, 0]
    s["overtime"] = [0.0, 0.0, 0.0, 1.0]
    s["surface"] = ["grass ", "fieldturf", "", "dessograss"]   # stray space, blank
    return s


def test_player_games_adds_own_side_game_context():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule_with_context(), 2016).set_index("player_id")
    home = df.loc["00-1"]          # LV is the home team (OAK on the schedule)
    assert (home.coach, home.opp_coach) == ("HC1", "AC1")
    assert (home.qb_id, home.qb, home.opp_qb_id, home.opp_qb) == ("hq1", "Hq1", "aq1", "Aq1")
    assert home.rest == 7 and home.referee == "Ref1" and home.weekday == "Sunday"
    away = df.loc["00-3"]          # AAA is the away team in game 3
    assert (away.coach, away.opp_coach, away.qb, away.rest) == ("AC3", "HC3", "Aq3", 7)


def test_player_games_normalises_surface_and_keeps_blanks_blank():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule_with_context(), 2016).set_index("player_id")
    assert df.loc["00-1", "surface"] == "Grass"          # "grass " with a trailing space
    assert df.loc["00-3", "surface"] is None or pd.isna(df.loc["00-3", "surface"])
    assert df.loc["00-4", "surface"] == "Grass"          # dessograss
    assert pd.isna(df.loc["00-1", "temp"]) and pd.isna(df.loc["00-1", "wind"])
    assert pd.isna(df.loc["00-3", "referee"]) is False   # present for game 3
    assert pg._surface_type("fieldturf") == "Turf" and pg._surface_type("") is None
    assert pg._surface_type(float("nan")) is None


def test_player_games_still_builds_from_a_schedule_without_context_columns():
    from webapp.sources.nflref import player_games as pg
    df = pg.build(_pg_players(), _pg_schedule(), 2016)
    assert len(df) == 4 and df["coach"].isna().all() and df["qb_id"].isna().all()


# -- pass_plays: play-level rows with the defensive scheme ------------------------

def _pp_pbp():
    return pd.DataFrame({
        "game_id": ["g1"] * 6, "play_id": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "week": [1] * 6, "season": [2018] * 6,
        "posteam": ["AAA"] * 6, "defteam": ["BBB"] * 6,
        # nflverse's pass_attempt includes sacks; play 5 is a two-point try,
        # play 6 a deleted play
        "pass_attempt": [1.0, 1.0, 1.0, 0.0, 1.0, 1.0],
        "sack": [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
        "two_point_attempt": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "play_deleted": [0.0, 0.0, 0.0, 0.0, 0.0, 1.0],
        "passer_player_id": ["00-Q"] * 6, "receiver_player_id": ["00-A", None, None, None, "00-A", "00-A"],
        "complete_pass": [1.0, 0.0, 0.0, 0.0, 1.0, 1.0],
        "yards_gained": [12.0, 0.0, -7.0, 3.0, 2.0, 5.0],
        "air_yards": [8.0, 15.0, None, None, 2.0, 5.0],
        "pass_touchdown": [0.0, 0.0, 0.0, 0.0, 1.0, 0.0], "interception": [0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
    })


def _pp_part():
    return pd.DataFrame({
        "nflverse_game_id": ["g1", "g1", "g1"], "play_id": [1.0, 2.0, 3.0],
        "route": ["SLANT", "", None], "defense_man_zone_type": ["MAN_COVERAGE", "ZONE_COVERAGE", None],
        "defense_coverage_type": ["COVER_1", "COVER_3", None],
        "defenders_in_box": [6.0, 7.0, 8.0], "number_of_pass_rushers": [4.0, 5.0, 4.0],
        "was_pressure": [False, True, True], "time_to_throw": [2.1, 3.0, None],
        "offense_formation": ["SHOTGUN", "UNDER CENTER", " "],
    })


def test_pass_plays_keeps_attempts_and_sacks_and_drops_two_point_and_deleted_plays():
    from webapp.sources.nflref import pass_plays as pp
    df = pp.build(_pp_pbp(), _pp_part(), 2018)
    assert df["play_id"].tolist() == [1, 2, 3]
    assert df["attempt"].tolist() == [1, 1, 0]            # a sack is a dropback, not an attempt
    assert df["sack"].tolist() == [0, 0, 1]
    assert list(df.columns) == pp.COLUMNS


def test_pass_plays_joins_the_scheme_and_leaves_missing_values_blank():
    from webapp.sources.nflref import pass_plays as pp
    df = pp.build(_pp_pbp(), _pp_part(), 2018)
    assert df["man_zone"].tolist()[:2] == ["MAN_COVERAGE", "ZONE_COVERAGE"]
    assert df["man_zone"].isna().tolist() == [False, False, True]
    assert df["route"].iloc[0] == "SLANT" and pd.isna(df["route"].iloc[1])     # "" is not a route
    assert pd.isna(df["formation"].iloc[2])                                      # blank text -> None
    assert df["pressure"].tolist() == [0.0, 1.0, 1.0]                             # 0 / 1 / (blank stays NaN)
    assert pd.isna(df["ttt"].iloc[2])
    assert df["yards"].tolist() == [12.0, 0.0, -7.0] and df["td"].tolist() == [0, 0, 0]


def test_pass_plays_without_a_participation_file_has_plays_and_blank_scheme():
    from webapp.sources.nflref import pass_plays as pp
    df = pp.build(_pp_pbp(), None, 2026)
    assert len(df) == 3 and df["season"].eq(2026).all()
    for c in ("route", "man_zone", "coverage", "box", "rushers", "pressure", "ttt", "formation"):
        assert df[c].isna().all(), c


def test_pass_plays_blank_pressure_stays_blank_not_false():
    from webapp.sources.nflref import pass_plays as pp
    part = _pp_part()
    part["was_pressure"] = [True, None, False]
    df = pp.build(_pp_pbp(), part, 2018)
    assert df["pressure"].iloc[0] == 1.0 and pd.isna(df["pressure"].iloc[1])


def test_pass_plays_fetch_snapshots_and_serves_it(monkeypatch):
    def fake(asset, columns=None, reload=False):
        return _pp_pbp() if asset.startswith("pbp/") else _pp_part()
    monkeypatch.setattr(api, "fetch_release_parquet", fake)
    assert len(nflref.load("pass_plays", "2018")) == 3
    monkeypatch.setattr(api, "fetch_release_parquet",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")))
    cache._mem.clear()
    assert len(nflref.load("pass_plays", "2018")) == 3        # from the snapshot


def test_pass_plays_is_built_when_participation_is_unavailable(monkeypatch):
    def fake(asset, columns=None, reload=False):
        if asset.startswith("pbp_participation/"):
            raise RuntimeError("404")
        return _pp_pbp()
    monkeypatch.setattr(api, "fetch_release_parquet", fake)
    df = nflref.load("pass_plays", "2026")
    assert len(df) == 3 and df["man_zone"].isna().all()


def test_pass_plays_before_earliest_is_empty():
    assert nflref.load("pass_plays", "2015").empty


def test_pass_plays_on_render_never_rebuilds(monkeypatch):
    monkeypatch.setattr(api, "on_render", lambda: True)
    monkeypatch.setattr(api, "fetch_release_parquet",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no download")))
    assert nflref.load("pass_plays", "2018").empty


def test_pass_plays_probes_the_play_by_play_asset_for_refresh():
    assert DATASETS["pass_plays"]._asset("2024") == "pbp/play_by_play_2024.parquet"


def test_pass_plays_keeps_the_situation_columns_and_blanks_a_missing_one():
    from webapp.sources.nflref import pass_plays as pp
    pbp = _pp_pbp()
    pbp["qtr"] = [1.0, 2.0, 5.0, 3.0, 3.0, 3.0]
    pbp["down"] = [1.0, 3.0, None, 2.0, 2.0, 2.0]
    pbp["ydstogo"] = [10.0, 7.0, 2.0, 5.0, 5.0, 5.0]
    pbp["yardline_100"] = [75.0, 40.0, 9.0, 50.0, 50.0, 50.0]
    pbp["quarter_seconds_remaining"] = [861.0, 100.0, 65.0, 30.0, 30.0, 30.0]
    df = pp.build(pbp, _pp_part(), 2018)
    assert df["qtr"].tolist() == [1.0, 2.0, 5.0] and df["ydstogo"].tolist() == [10.0, 7.0, 2.0]
    assert df["yardline"].tolist() == [75.0, 40.0, 9.0] and df["clock"].tolist() == [861.0, 100.0, 65.0]
    assert df["down"].iloc[:2].tolist() == [1.0, 3.0] and pd.isna(df["down"].iloc[2])
    # a file without the columns (an older snapshot source) still builds, blank
    bare = pp.build(_pp_pbp(), _pp_part(), 2018)
    assert bare[["qtr", "down", "ydstogo", "yardline", "clock"]].isna().all().all()
