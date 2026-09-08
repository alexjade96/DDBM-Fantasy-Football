"""sleepermetrics.nflstats -- advanced usage off the Sleeper weekly feed.

Network-free: `scoring.nfl_stats` and `players()` are both monkeypatched, and
the snapshot dir is redirected to a tmp path so nothing touches the repo's
season/stats/ tree.
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
# targets + snaps), one never-played stub (metadata only -> must be dropped).
_POOL = pd.DataFrame({
    "player_id":   ["w1", "r1", "stub", "k1"],
    "player_name": ["Wide One", "Run One", "Ghost", "Kick One"],
    "position":    ["WR", "RB", "WR", "K"],
    "team":        ["AAA", "AAA", "BBB", "AAA"],
    "gsis_id":     [None, None, None, None],
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
    },
    2: {
        "w1":   {"off_snp": 65.0, "tm_off_snp": 70.0, "rec_tgt": 8.0,
                 "rec": 6.0, "rec_yd": 70.0, "rec_air_yd": 100.0,
                 "rec_rz_tgt": 1.0, "pts_ppr": 13.0},
        "r1":   {"off_snp": 45.0, "tm_off_snp": 70.0, "rush_att": 12.0,
                 "rush_yd": 55.0, "rush_rz_att": 1.0, "pts_ppr": 9.0},
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
    assert set(got) == {"w1", "r1"}                 # stub dropped, K absent wk1
    assert "gms_active" not in got["w1"]            # only listed usage keys
    assert got["w1"]["rec_tgt"] == 10.0
    assert got["r1"]["rush_rz_att"] == 3.0


def test_raw_week_writes_and_reads_snapshot(wired, monkeypatch):
    nflstats.raw_week("2025", 1)                    # live -> writes snapshot
    p = nflstats._snapshot_path("2025", 1)
    assert p.exists()
    on_disk = json.loads(p.read_text(encoding="utf-8"))
    assert set(on_disk) == {"w1", "r1"}
    # now break the "network" and clear the mem cache: snapshot must serve it
    nflstats.clear_cache()
    monkeypatch.setattr(nflstats.scoring, "nfl_stats",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))
    again = nflstats.raw_week("2025", 1)
    assert set(again) == {"w1", "r1"}


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


def test_player_usage_empty_when_no_lines(monkeypatch, tmp_path):
    monkeypatch.setattr(nflstats, "players", lambda *a, **k: _POOL.copy())
    monkeypatch.setattr(nflstats.scoring, "nfl_stats", lambda *a, **k: {})
    monkeypatch.setattr(nflstats, "_STATS_DIR", tmp_path / "stats")
    nflstats.clear_cache()
    df = nflstats.player_usage(_mini_season())
    assert df.empty
    assert list(df.columns)[:3] == ["source", "player_id", "player_name"]
