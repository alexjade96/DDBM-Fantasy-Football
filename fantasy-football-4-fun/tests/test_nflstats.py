"""sleepermetrics.nflstats -- advanced usage off the Sleeper weekly feed.

Network-free: `scoring.nfl_stats` and `players()` are both monkeypatched, and
the snapshot dir is redirected to a tmp path so nothing touches the repo's
data/sources/sleeper_stats/ tree.
"""
import json

import pandas as pd
import pytest

from sleepermetrics import nflstats
from sleepermetrics.season import Season


def _mini_season(season="2025", last_week=2):
    tw = pd.DataFrame({
        "week": [1, 2], "roster_id": [1, 1], "user_id": ["1", "1"],
        "user_name": ["Al", "Al"], "matchup_id": [1, 1], "opp": [2, 2],
        "points": [100.0, 110.0], "pa": [90.0, 95.0], "result": ["W", "W"],
        "allplay_w": [1, 1], "allplay_l": [0, 0], "is_high": [True, True],
    })
    st = pd.DataFrame({
        "roster_id": [1], "user_id": ["1"], "user_name": ["Al"],
        "wins": [2], "losses": [0], "points": [210.0], "pa": [185.0],
        "allplay_w": [2], "allplay_l": [0], "highs": [2],
        "final_position": [1], "season": season, "champion": [True],
    })
    um = pd.DataFrame({"roster_id": [1], "user_id": ["1"], "user_name": ["Al"]})
    return Season(season, "Test", "0", last_week, {}, tw, pd.DataFrame(),
                  pd.DataFrame(), st, um)


# One WR (targets + air yards + RZ), one dual-threat RB (carries + a few
# targets + snaps), one never-played stub (metadata only -> must be dropped),
# one team defense (pid == team abbreviation, per players.py's own convention).
_POOL = pd.DataFrame({
    "player_id":   ["w1", "r1", "stub", "k1", "AAA"],
    "player_name": ["Wide One", "Run One", "Ghost", "Kick One", "AAA"],
    "position":    ["WR", "RB", "WR", "K", "DEF"],
    "team":        ["AAA", "AAA", "BBB", "AAA", "AAA"],
    "gsis_id":     [None, None, None, None, None],
})

_WK = {
    1: {
        "w1":   {"off_snp": 60.0, "tm_off_snp": 70.0, "rec_tgt": 10.0,
                 "rec": 7.0, "rec_yd": 90.0, "rec_air_yd": 120.0,
                 "rec_rz_tgt": 2.0, "pts_ppr": 16.0, "pts_std": 9.0},
        "r1":   {"off_snp": 40.0, "tm_off_snp": 70.0, "rush_att": 15.0,
                 "rush_yd": 80.0, "rush_rz_att": 3.0, "rec_tgt": 4.0,
                 "rec": 3.0, "rec_air_yd": 8.0, "pts_ppr": 14.0},
        "stub": {"gms_active": 1.0, "pos_rank_ppr": 999.0},   # never played
        "AAA":  {"sack": 3.0, "int": 1.0, "tkl": 40.0, "pts_allow": 10.0,
                 "yds_allow": 300.0, "pts_ppr": 8.0,
                 "pos_rank_ppr": 999.0},   # DEF pos_rank is always Sleeper's stub
    },
    2: {
        "w1":   {"off_snp": 65.0, "tm_off_snp": 70.0, "rec_tgt": 8.0,
                 "rec": 6.0, "rec_yd": 70.0, "rec_air_yd": 100.0,
                 "rec_rz_tgt": 1.0, "pts_ppr": 13.0},
        "r1":   {"off_snp": 45.0, "tm_off_snp": 70.0, "rush_att": 12.0,
                 "rush_yd": 55.0, "rush_rz_att": 1.0, "pts_ppr": 9.0},
        "AAA":  {"sack": 1.0, "int": 2.0, "tkl": 35.0, "pts_allow": 20.0,
                 "yds_allow": 350.0, "pts_ppr": 6.0},
    },
}


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: _POOL.copy())
    monkeypatch.setattr(nflstats.scoring, "nfl_stats",
                        lambda season, week: _WK.get(int(week), {}))
    monkeypatch.setattr(nflstats, "_STATS_DIR", tmp_path / "stats")
    nflstats.clear_cache()
    return _mini_season()


def test_raw_week_trims_to_usage_keys_and_drops_never_played(wired):
    got = nflstats.raw_week("2025", 1)
    assert set(got) == {"w1", "r1", "AAA"}           # stub dropped, K absent wk1
    assert "gms_active" not in got["w1"]            # only listed usage keys
    assert got["w1"]["rec_tgt"] == 10.0
    assert got["r1"]["rush_rz_att"] == 3.0


def test_raw_week_trims_def_to_its_own_key_set(wired):
    """A DEF pid is trimmed against `_DEF_USAGE_KEYS`, not the offense
    `_USAGE_KEYS` -- the two vocabularies share no keys (see nflstats.py's
    own comment on `_DEF_USAGE_KEYS` for why)."""
    got = nflstats.raw_week("2025", 1)
    assert got["AAA"]["sack"] == 3.0
    assert got["AAA"]["pts_allow"] == 10.0
    assert "rec_tgt" not in got["AAA"]              # offense-only key excluded
    assert "sack" not in got["w1"]                  # DEF-only key excluded


def test_raw_week_writes_and_reads_snapshot(wired, monkeypatch):
    nflstats.raw_week("2025", 1)                    # live -> writes snapshot
    p = nflstats._snapshot_path("2025", 1)
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert set(on_disk) == {"w1", "r1", "AAA"}
    # now break the "network" and clear the mem cache: snapshot must serve it
    nflstats.clear_cache()
    monkeypatch.setattr(nflstats.scoring, "nfl_stats",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))
    again = nflstats.raw_week("2025", 1)
    assert set(again) == {"w1", "r1", "AAA"}


def test_player_usage_shares_and_rates(wired):
    df = nflstats.player_usage(_mini_season())
    assert list(df["source"].unique()) == ["sleeper"]
    w = df.set_index("player_id").loc["w1"]
    r = df.set_index("player_id").loc["r1"]

    # snap_share = sum(off_snp) / sum(tm_off_snp)
    assert w["snap_share"] == pytest.approx((60 + 65) / (70 + 70), abs=1e-3)
    assert r["snap_share"] == pytest.approx((40 + 45) / (70 + 70), abs=1e-3)

    # tgt_share denominator is the NFL team's targets that same window:
    # AAA targets = w1 (10+8) + r1 (4+0) = 22; w1 share = 18/22
    assert w["tgt_share"] == pytest.approx(18 / 22, abs=1e-3)
    assert r["tgt_share"] == pytest.approx(4 / 22, abs=1e-3)

    # rz_touches = rec_rz_tgt + rush_rz_att + pass_rz_att
    assert w["rz_touches"] == 3          # 2 + 1
    assert r["rz_touches"] == 4          # 3 + 1

    # adot = rec_air_yd / targets, receivers only
    assert w["adot"] == pytest.approx((120 + 100) / 18, abs=1e-2)

    # ppg_ppr ties back to the raw pts_ppr we fed in
    assert w["ppg_ppr"] == pytest.approx((16 + 13) / 2, abs=1e-2)
    assert r["games"] == 2


def test_player_usage_week_subset(wired):
    df = nflstats.player_usage(_mini_season(), weeks=[1])
    w = df.set_index("player_id").loc["w1"]
    assert w["games"] == 1
    assert w["snap_share"] == pytest.approx(60 / 70, abs=1e-3)


def test_player_usage_excludes_def(wired):
    """player_usage's columns (snap_share/tgt_share/adot) have no team-
    defense equivalent, so a DEF row is skipped entirely rather than
    appearing with all-zero/meaningless values."""
    df = nflstats.player_usage(_mini_season())
    assert "AAA" not in set(df["player_id"])


def test_player_usage_empty_when_no_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: _POOL.copy())
    monkeypatch.setattr(nflstats.scoring, "nfl_stats", lambda *a, **k: {})
    monkeypatch.setattr(nflstats, "_STATS_DIR", tmp_path / "stats")
    nflstats.clear_cache()
    df = nflstats.player_usage(_mini_season())
    assert df.empty
    assert list(df.columns)[:3] == ["source", "player_id", "player_name"]


# --- player_leaderboard (league-free) ---------------------------------------

def test_player_leaderboard_offense_excludes_def(wired):
    df = nflstats.player_leaderboard("2025", pos="ALL", weeks=[1, 2])
    assert "AAA" not in set(df["player_id"])
    assert set(df["player_id"]) == {"w1", "r1"}


def test_player_leaderboard_def_returns_its_own_columns(wired):
    df = nflstats.player_leaderboard("2025", pos="DEF", weeks=[1, 2])
    assert list(df["player_id"]) == ["AAA"]
    row = df.iloc[0]
    assert row["sacks"] == 4        # 3 + 1
    assert row["ints"] == 3         # 1 + 2
    assert row["tackles"] == 75     # 40 + 35
    assert row["pts_allow"] == 30   # 10 + 20
    assert row["yds_allow"] == 650  # 300 + 350
    assert row["fpts_ppr"] == pytest.approx(14.0)     # 8 + 6
    assert row["ppg_ppr"] == pytest.approx(7.0)        # 14 / 2
    # offense-only columns never appear on the DEF leaderboard
    assert "snap_share" not in df.columns
    assert "tgt_share" not in df.columns
    assert "adot" not in df.columns


def test_player_leaderboard_def_ranked_by_fpts_ppr(monkeypatch, tmp_path):
    pool = pd.DataFrame({
        "player_id":   ["AAA", "BBB"],
        "player_name": ["AAA", "BBB"],
        "position":    ["DEF", "DEF"],
        "team":        ["AAA", "BBB"],
        "gsis_id":     [None, None],
    })
    wk = {1: {
        "AAA": {"pts_ppr": 20.0, "sack": 1.0},
        "BBB": {"pts_ppr": 8.0, "sack": 3.0},
    }}
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: pool.copy())
    monkeypatch.setattr(nflstats.scoring, "nfl_stats",
                        lambda season, week: wk.get(int(week), {}))
    monkeypatch.setattr(nflstats, "_STATS_DIR", tmp_path / "stats")
    nflstats.clear_cache()

    df = nflstats.player_leaderboard("2025", pos="DEF", weeks=[1])
    assert list(df["player_id"]) == ["AAA", "BBB"]     # ranked by fpts_ppr
    assert list(df["rank"]) == [1, 2]


def test_player_leaderboard_def_empty_when_no_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: _POOL.copy())
    monkeypatch.setattr(nflstats.scoring, "nfl_stats", lambda *a, **k: {})
    monkeypatch.setattr(nflstats, "_STATS_DIR", tmp_path / "stats")
    nflstats.clear_cache()
    df = nflstats.player_leaderboard("2025", pos="DEF")
    assert df.empty
