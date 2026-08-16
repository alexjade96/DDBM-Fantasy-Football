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


def test_stamp_slot_cmp_marks_up_down_even_by_matching_slot():
    sides = [
        {"lineup": [{"slot": "QB", "points": 12.0}, {"slot": "RB", "points": 5.0}]},
        {"lineup": [{"slot": "QB", "points": 7.0}, {"slot": "RB", "points": 5.0}]},
    ]
    playoffs._stamp_slot_cmp(sides)
    assert sides[0]["lineup"][0]["cmp"] == "up"
    assert sides[1]["lineup"][0]["cmp"] == "down"
    assert sides[0]["lineup"][1]["cmp"] == "even"
    assert sides[1]["lineup"][1]["cmp"] == "even"


def test_stamp_slot_cmp_leaves_rows_unstamped_without_two_sides():
    """A bye or a game missing its opponent has no "other side" to compare
    against -- rows must stay unmarked rather than crash or fabricate up/down."""
    sides = [{"lineup": [{"slot": "QB", "points": 12.0}]}]
    playoffs._stamp_slot_cmp(sides)
    assert "cmp" not in sides[0]["lineup"][0]


def test_game_log_bracket_lineups_get_slot_cmp_highlight():
    """Two starters at the SAME slot (same idiom draft.redraft_playoff already
    highlights) must be marked up/down against each other, mirroring the
    weekly tab's own per-slot highlight in a bracket game's drilldown."""
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][0] = {
        "id": "R1M1",
        "home": {"team": "Al", "starters": ["1"]},    # QB, 12.0 in wk14
        "away": {"team": "Bo", "starters": ["3"]}}     # QB, 6.0 in wk14 -- same slot
    p = playoffs.playoff(cfg, validate=False)
    log = playoffs.game_log(_S(), p, toilet={"games": []})
    g = next(gm for gm in log[0]["games"] if gm["id"] == "R1M1")
    row_by_team = {sd["team"]: sd["lineup"][0] for sd in g["sides"]}
    assert row_by_team["Al"]["cmp"] == "up"
    assert row_by_team["Bo"]["cmp"] == "down"


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
    # `player_id` rides along on every lineup row now (not just the name),
    # and `pos_rank` degrades to None rather than crashing the whole log --
    # `_S` has none of the league_id/season/last_week_all season_position_ranks
    # needs to actually price a season, same best-effort contract headshots/
    # avatars already use elsewhere in this app.
    assert all(r["player_id"] and r["pos_rank"] is None
               for sd in g["sides"] for r in sd["lineup"])
    # `season_rank` (the MANAGER's own final standing, distinct from a
    # player's `pos_rank`) degrades the same way -- `_S` has no `standings`.
    assert all(sd["season_rank"] is None for sd in g["sides"])


def test_game_log_sides_carry_manager_season_rank_when_available():
    """Each side's `season_rank` is the manager's OWN final regular-season
    standing (s.standings.final_position) -- shown next to the team name in
    the matchup summary the same way a weekly game shows a W-L record."""
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(S(), p, toilet={"games": []})
    semi = log[0]
    rank_by_team = {sd["team"]: sd["season_rank"]
                    for g in semi["games"] for sd in g["sides"]}
    assert rank_by_team == {"Al": 1, "Bo": 4, "Cy": 2, "Dee": 3}


def test_game_log_bye_carries_manager_season_rank():
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][1] = {"id": "R1M2", "bye": "Dee"}
    p = playoffs.playoff(cfg, validate=False)
    log = playoffs.game_log(S(), p, toilet={"games": []})
    semi = next(g for g in log if g["label"] == "Semi")
    assert semi["byes"][0]["team"] == "Dee" and semi["byes"][0]["season_rank"] == 3


def test_game_log_toilet_sides_pass_through_season_rank_and_bench():
    """Toilet-bowl games are handed to game_log already-built (by
    toilet_bowl()); game_log's own transcoding of them must carry
    `season_rank` and `bench` through rather than dropping them, same as
    `lineup`."""
    p = playoffs.playoff(_cfg(), validate=False)
    toilet = {"games": [{"week": 15, "sides": [
        {"team": "X", "points": 100.0, "result": "W", "season_rank": 5, "lineup": [],
         "bench": [{"player_id": "9", "player_name": "Ike", "position": "TE", "points": 3.0}]},
        {"team": "Y", "points": 90.0, "result": "L", "season_rank": 2, "lineup": []}]}]}
    log = playoffs.game_log(_S(), p, toilet=toilet)
    tb = log[-1]
    sides = {sd["team"]: sd for sd in tb["games"][0]["sides"]}
    assert sides["X"]["season_rank"] == 5 and sides["Y"]["season_rank"] == 2
    assert sides["X"]["bench"][0]["player_id"] == "9"
    assert sides["Y"]["bench"] == []


def test_game_log_lineups_carry_season_pos_rank_when_available(monkeypatch):
    """When `metrics.season_position_ranks` CAN be priced (a real Season),
    each side's lineup rows show the player's FINAL season-long position
    finish -- the decoration that lets the Playoffs tab show "RB #4" next to
    a name the same way the weekly report shows a this-week rank."""
    from sleepermetrics import metrics as _metrics
    ranks = {"1": {"position": "QB", "rank": 2, "points": 300.0},
             "2": {"position": "WR", "rank": 5, "points": 150.0}}
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: ranks)
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(_S(), p, toilet={"games": []})
    g = log[0]["games"][0]
    row_by_pid = {r["player_id"]: r for sd in g["sides"] for r in sd["lineup"]}
    assert row_by_pid["1"]["pos_rank"] == 2
    assert row_by_pid["2"]["pos_rank"] == 5


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


def test_toilet_bowl_lineups_and_sides_carry_player_and_manager_ranks(monkeypatch):
    """The toilet bowl is a plain Sleeper matchup, so its lineups come from
    `pl_wk` (via `_lineup_of`), not the bracket engine's `players` frame --
    a separate code path from game_log's own bracket lineups, so it needs
    its own check that player_id/pos_rank ride along here too. Its own
    `sides` must also carry the MANAGER's `season_rank` (from `standings`),
    the same decoration game_log's bracket sides get."""
    from sleepermetrics import metrics as _metrics
    ranks = {"5": {"position": "RB", "rank": 3, "points": 220.0}}
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: ranks)

    class S:
        standings = pd.DataFrame({
            "user_name": ["Al", "Bo"], "final_position": [3, 4],
            "wins": [5, 4], "losses": [7, 8], "points": [1400.0, 1300.0]})
        team_wk_all = pd.DataFrame({
            "week": [15, 15], "roster_id": [1, 2], "matchup_id": [9, 9],
            "points": [100.0, 90.0], "result": ["W", "L"],
            "user_name": ["Al", "Bo"]})
        pl_wk_all = pd.DataFrame({
            "week": [15, 15], "roster_id": [1, 2], "player_id": ["5", "6"],
            "player_name": ["Ed", "Fay"], "position": ["RB", "WR"],
            "points": [100.0, 90.0], "is_starter": [True, True]})
        slots: dict = {}

    class P:
        results = pd.DataFrame({"team": ["Cy"], "weeks": ["15"]})

    t = playoffs.toilet_bowl(S(), p=P())
    game = next(g for g in t["games"] if g["week"] == 15)
    al_side = next(sd for sd in game["sides"] if sd["team"] == "Al")
    assert al_side["lineup"][0]["player_id"] == "5"
    assert al_side["lineup"][0]["pos_rank"] == 3
    assert al_side["season_rank"] == 3


def test_toilet_bowl_sides_carry_bench_and_slot_cmp():
    """Unlike a bracket game (commissioner-submitted starters only), the
    toilet bowl reads a real `pl_wk` roster -- so its own `bench` (everyone
    NOT started that week) is genuinely knowable, and its starters get the
    same per-slot win/loss `cmp` highlight as a bracket game's."""
    class S:
        standings = pd.DataFrame({
            "user_name": ["Al", "Bo"], "final_position": [3, 4],
            "wins": [5, 4], "losses": [7, 8], "points": [1400.0, 1300.0]})
        team_wk_all = pd.DataFrame({
            "week": [15, 15], "roster_id": [1, 2], "matchup_id": [9, 9],
            "points": [100.0, 90.0], "result": ["W", "L"],
            "user_name": ["Al", "Bo"]})
        pl_wk_all = pd.DataFrame({
            "week": [15, 15, 15, 15],
            "roster_id": [1, 1, 2, 2],
            "player_id": ["5", "6", "7", "8"],
            "player_name": ["Ed", "Fitz", "Gio", "Hank"],
            "position": ["RB", "WR", "RB", "TE"],
            "points": [100.0, 30.0, 90.0, 20.0],
            "is_starter": [True, False, True, False]})
        slots: dict = {}

    class P:
        results = pd.DataFrame({"team": ["Cy"], "weeks": ["15"]})

    t = playoffs.toilet_bowl(S(), p=P())
    game = next(g for g in t["games"] if g["week"] == 15)
    al = next(sd for sd in game["sides"] if sd["team"] == "Al")
    bo = next(sd for sd in game["sides"] if sd["team"] == "Bo")
    assert al["bench"][0]["player_id"] == "6" and al["bench"][0]["points"] == 30.0
    assert bo["bench"][0]["player_id"] == "8" and bo["bench"][0]["points"] == 20.0
    # Both starters are RB -- the same fallback slot (slots={}) -- so they're
    # directly comparable: Al's 100 beats Bo's 90.
    assert al["lineup"][0]["cmp"] == "up"
    assert bo["lineup"][0]["cmp"] == "down"


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
