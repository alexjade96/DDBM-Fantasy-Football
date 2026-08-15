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


# --- the unified game log (round groups -> lineups + byes + toilet) ---------
class _S:
    """Minimal Season stand-in for game_log: no frames/network needed. `slots`
    empty means assign_slots degrades to plain position labels; team_wk_all None
    means reference_scores (bye points) is empty."""
    slots: dict = {}
    team_wk_all = None


def test_game_log_groups_by_round_winner_first_with_lineups():
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(_S(), p, toilet={"games": []})
    assert [g["label"] for g in log] == ["Semi", "Final"]     # bracket order
    semi = log[0]
    assert semi["weeks"] == "14" and len(semi["games"]) == 2
    g = semi["games"][0]
    assert g["sides"][0]["result"] == "W"                     # winner reads first
    assert g["winner"] == g["sides"][0]["team"]
    assert all(sd["lineup"] for sd in g["sides"])             # both lineups carried
    assert g["margin"] == round(abs(g["sides"][0]["points"]
                                    - g["sides"][1]["points"]), 2)


def test_game_log_folds_in_byes_and_the_toilet_bowl():
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][1] = {"id": "R1M2", "bye": "Dee"}
    p = playoffs.playoff(cfg, validate=False)
    toilet = {"games": [{"week": 15, "sides": [
        {"team": "X", "points": 100.0, "result": "W", "lineup": []},
        {"team": "Y", "points": 90.0, "result": "L", "lineup": []}]}]}
    log = playoffs.game_log(_S(), p, toilet=toilet)
    semi = next(g for g in log if g["label"] == "Semi")
    assert [b["team"] for b in semi["byes"]] == ["Dee"]       # bye rides its round
    tb = log[-1]                                              # toilet is its own group
    assert tb["kind"] == "toilet" and tb["label"] == "Toilet bowl"
    assert tb["games"][0]["winner"] == "X" and tb["games"][0]["margin"] == 10.0


def test_toilet_bowl_carries_each_missed_teams_own_postseason_record():
    """The combined Postseason-results board fills a missed team's G/W/L/PPG/
    High/Low/Margin from the toilet-bowl games it actually played, not blanks --
    the po_* fields are what let that team sit in the same table as a bracket
    team instead of reading as pure dashes."""
    class S:
        standings = pd.DataFrame({
            "user_name": ["Al", "Bo"], "final_position": [3, 4],
            "wins": [5, 4], "losses": [7, 8], "points": [1400.0, 1300.0]})
        team_wk_all = pd.DataFrame({
            "week": [15, 15], "roster_id": [1, 2], "matchup_id": [9, 9],
            "points": [100.0, 90.0], "result": ["W", "L"],
            "user_name": ["Al", "Bo"]})

    class P:
        # Only the bracket's own team ("Cy") and its round week -- po_start
        # comes from here, so Al/Bo (absent) are read as having missed it.
        results = pd.DataFrame({"team": ["Cy"], "weeks": ["15"]})

    t = playoffs.toilet_bowl(S(), p=P())
    al = next(x for x in t["teams"] if x["user_name"] == "Al")
    bo = next(x for x in t["teams"] if x["user_name"] == "Bo")
    assert (al["po_games"], al["po_wins"], al["po_losses"]) == (1, 1, 0)
    assert al["po_ppg"] == al["po_high"] == al["po_low"] == 100.0
    assert al["po_avg_margin"] == 10.0
    assert (bo["po_games"], bo["po_wins"], bo["po_losses"]) == (1, 0, 1)
    assert bo["po_avg_margin"] == -10.0
    assert t["last"] == "Bo" and t["basis"] == "game"


def test_toilet_bowl_po_fields_are_none_without_a_toilet_game():
    """A team that missed the bracket but never got a toilet-bowl game (no
    opponent pool) must show blank po_* fields, not a stray 0 beside a dash."""
    class S:
        standings = pd.DataFrame({
            "user_name": ["Al"], "final_position": [4],
            "wins": [3], "losses": [9], "points": [1200.0]})
        team_wk_all = None

    t = playoffs.toilet_bowl(S(), p=None)
    al = t["teams"][0]
    assert al["po_games"] is None and al["po_wins"] is None
    assert al["po_ppg"] is None and al["po_avg_margin"] is None


# --- brackets belong to a league, not to a season number --------------------
def _write_cfg(tmp, league_id):
    """The standard test bracket (Dee wins), stored as league `league_id`'s
    2025 -- under <tmp>/<league_id>/2025.json, the same league-id-subfolder
    layout config_paths() reads for real (see season/<league_id>/*.json)."""
    import json
    sub = tmp / str(league_id)
    sub.mkdir(parents=True, exist_ok=True)
    p = sub / "2025.json"
    p.write_text(json.dumps(_cfg(league_id=league_id, roster_positions=["QB"])))
    return p


def test_config_paths_filters_by_league(tmp_path):
    _write_cfg(tmp_path, "111")
    d = str(tmp_path)
    assert list(playoffs.config_paths(d)) == ["2025"]              # unfiltered
    assert list(playoffs.config_paths(d, ["111"])) == ["2025"]     # its own league
    # Another league's 2025 is NOT this bracket: it must not be handed over.
    assert playoffs.config_paths(d, ["222"]) == {}
    assert playoffs.load_playoffs(d, league_ids=["222"]) == {}


def test_config_paths_skips_non_league_subfolders(tmp_path):
    """adp/ and fixtures/ are siblings of the league subfolders under
    season/, not league folders themselves -- a non-numeric-named subfolder
    (and anything malformed inside it) must never surface as a bracket."""
    _write_cfg(tmp_path, "111")
    (tmp_path / "adp").mkdir()
    (tmp_path / "adp" / "2025.json").write_text('{"not": "a bracket"}')
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "2025-sleeper-bracket.json").write_text("{}")
    assert list(playoffs.config_paths(str(tmp_path))) == ["2025"]


def test_apply_playoffs_does_not_stamp_another_leagues_champion(tmp_path):
    _write_cfg(tmp_path, "111")

    class S:                       # minimal stand-in for a Season
        def __init__(self, lid):
            self.season, self.league_id = "2025", lid
            self.standings = pd.DataFrame({"user_name": ["Dee", "Al"],
                                           "champion": [False, False]})

    same = {"2025": S("111")}
    playoffs.apply_playoffs(same, str(tmp_path))
    assert same["2025"].standings["champion"].tolist() == [True, False]

    other = {"2025": S("222")}     # different league, same season number
    playoffs.apply_playoffs(other, str(tmp_path))
    assert other["2025"].standings["champion"].tolist() == [False, False]
