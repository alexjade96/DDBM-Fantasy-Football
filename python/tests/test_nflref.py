"""nflref -- nflverse-derived data layer.

Network-free: `nflref.api.read_release_parquet` is monkeypatched, and the
snapshot dir is redirected to tmp so nothing touches season/nflverse/.
"""
import pandas as pd
import pytest

import nflref
from nflref import api, cache
from nflref.base import DATASETS
from nflref.player_stats import PlayerStats
from nflref.schedules import Schedules


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
    assert set(DATASETS) == {"player_stats", "schedules"}


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


def test_nflstats_players_row_has_portrait(monkeypatch):
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


def test_attach_sleeper_ids_resolves_and_passes_through():
    from webapp.app import _attach_sleeper_ids
    rows = [
        {"player": "Ja'Marr Chase", "position": "WR", "player_id": "00-0036900"},
        {"player": "Nobody At All", "position": "WR", "player_id": None},
        {"player": "Sleeper Native", "position": "RB", "player_id": "1234"},
    ]
    _attach_sleeper_ids(rows)
    assert rows[0]["sleeper_id"] and rows[0]["sleeper_id"].isdigit()   # name-resolved
    assert rows[1]["sleeper_id"] is None                              # unknown
    assert rows[2]["sleeper_id"] == "1234"                            # digit id passes through


def test_nflstats_data_route_schedule(monkeypatch):
    monkeypatch.setattr(api, "read_release_parquet", lambda asset: _fake_games())
    from webapp import app
    resp = app.nflstats_data(_Req(), view="schedule", season="2024", week="1")
    body = resp.body.decode()
    assert "2 games" in body and "Margin" in body


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
