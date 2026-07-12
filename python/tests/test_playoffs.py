"""Playoff engine tests (network-free: stats + player db are stubbed)."""
import pandas as pd
import pytest

from sleepermetrics import playoffs, scoring

RULES = {"pass_td": 4.0, "rec": 1.0, "rush_yd": 0.1}

# Two 1-man "lineups" per side keeps the arithmetic checkable by hand.
STATS = {
    14: {"1": {"pass_td": 3},           # 12.0
         "2": {"rec": 5, "rush_yd": 20},  # 7.0
         "3": {"pass_td": 1, "rec": 2},   # 6.0
         "4": {"rush_yd": 100}},          # 10.0
    15: {"1": {"pass_td": 1},           # 4.0
         "4": {"rush_yd": 300}},        # 30.0
}

PINFO = pd.DataFrame({
    "player_id": ["1", "2", "3", "4"],
    "player_name": ["Ace", "Bo", "Cy", "Dee"],
    "position": ["QB", "WR", "QB", "RB"],
})


@pytest.fixture(autouse=True)
def _stub(monkeypatch):
    monkeypatch.setattr(scoring, "nfl_stats", lambda season, week: STATS.get(int(week), {}))
    monkeypatch.setattr(playoffs, "_players", lambda: PINFO)


def _cfg(**kw):
    cfg = {
        "season": "2025", "league_id": "0", "name": "Test",
        "scoring_settings": RULES,
        "rounds": [
            {"id": "R1", "name": "Semi", "weeks": [14], "matchups": [
                {"id": "R1M1", "home": {"team": "Al", "starters": ["1"]},
                 "away": {"team": "Bo", "starters": ["2"]}},
                {"id": "R1M2", "home": {"team": "Cy", "starters": ["3"]},
                 "away": {"team": "Dee", "starters": ["4"]}},
            ]},
            {"id": "R2", "name": "Final", "weeks": [15], "matchups": [
                {"id": "R2M1", "home": {"team": "W:R1M1", "starters": ["1"]},
                 "away": {"team": "W:R1M2", "starters": ["4"]}},
            ]},
        ],
        "final": "R2M1",
    }
    cfg.update(kw)
    return cfg


def test_scores_lineups_and_advances_winners():
    p = playoffs.playoff(_cfg(), validate=False)
    r = p.results.set_index(["matchup_id", "team"])
    # Ace: 3 pass_td * 4 = 12.0 beats Bo: 5 rec + 20*0.1 = 7.0
    assert r.loc[("R1M1", "Al"), "points"] == 12.0
    assert r.loc[("R1M1", "Bo"), "points"] == 7.0
    assert r.loc[("R1M1", "Al"), "result"] == "W"
    # Dee (10.0) beats Cy (6.0); both winners advance into the final by reference
    assert r.loc[("R1M2", "Dee"), "result"] == "W"
    assert set(p.results[p.results["matchup_id"] == "R2M1"]["team"]) == {"Al", "Dee"}
    # Final in week 15: Ace 4.0 vs Dee 30.0
    assert r.loc[("R2M1", "Dee"), "points"] == 30.0
    assert p.champion == "Dee"


def test_multi_week_round_sums_weeks():
    cfg = _cfg()
    cfg["rounds"][0]["weeks"] = [14, 15]          # Ace: 12 + 4 = 16
    p = playoffs.playoff(cfg, validate=False)
    r = p.results.set_index(["matchup_id", "team"])
    assert r.loc[("R1M1", "Al"), "points"] == 16.0


def test_pending_when_lineup_not_submitted():
    cfg = _cfg()
    cfg["rounds"][1]["matchups"][0]["home"]["starters"] = []   # not handed in yet
    p = playoffs.playoff(cfg, validate=False)
    fin = p.results[p.results["matchup_id"] == "R2M1"]
    assert set(fin["result"]) == {"PENDING"}
    assert p.champion is None       # nothing is awarded on an unplayed final


def test_bye_advances_unscored():
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][1] = {"id": "R1M2", "bye": "Dee"}
    p = playoffs.playoff(cfg, validate=False)
    bye = p.results[p.results["matchup_id"] == "R1M2"].iloc[0]
    assert bye["result"] == "BYE" and pd.isna(bye["points"])
    assert p.champion == "Dee"      # byes still advance into the final


def test_names_resolve_like_ids():
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][0]["home"]["starters"] = ["Ace"]   # by name
    p = playoffs.playoff(cfg, validate=False)
    r = p.results.set_index(["matchup_id", "team"])
    assert r.loc[("R1M1", "Al"), "points"] == 12.0


def test_check_lineup_flags_illegal_submissions():
    rp = ["QB", "RB", "WR", "FLEX", "BN"]        # 4 starting slots
    short = playoffs.check_lineup(["1"], rp, PINFO)             # too few starters
    assert short and any("starters" in c for c in short)
    # A legal QB / RB / WR / flex submission raises nothing.
    assert playoffs.check_lineup(["1", "4", "2", "3"], rp, PINFO) == []
    # Missing the RB entirely -> called out by position.
    probs = playoffs.check_lineup(["1", "2", "3"], rp, PINFO)
    assert any("RB" in p for p in probs)
