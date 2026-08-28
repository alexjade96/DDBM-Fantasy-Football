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


# --- Sleeper-bracket bye inference (`_sleeper_byes`) -------------------------
# Sleeper's winners_bracket has no explicit bye node: a first-round-bye team
# just isn't listed until the round it enters, where its slot is a raw roster
# id with NO `t1_from`/`t2_from` ref. These fixtures mirror the real shape
# (Coin Flip and FF / Liberty Boys / DDBM 2022-23: 6- and 8-team brackets,
# seeds 1-2 bye round 1).
_NAME_OF = {1: "S1", 2: "S2", 3: "S3", 4: "S4", 5: "S5", 6: "S6", 7: "S7", 8: "S8"}

# 6-team: R1 = 3v6, 4v5; R2 pulls seeds 1 and 2 in as raw ids (no _from).
_WB_6TM = [
    {"m": 1, "r": 1, "t1": 3, "t2": 6, "w": 3, "l": 6},
    {"m": 2, "r": 1, "t1": 4, "t2": 5, "w": 5, "l": 4},
    {"m": 3, "r": 2, "t1": 1, "t2": 3, "w": 1, "l": 3, "t2_from": {"w": 1}},
    {"m": 4, "r": 2, "t1": 2, "t2": 5, "w": 2, "l": 5, "t2_from": {"w": 2}},
    {"p": 5, "m": 5, "r": 2, "t1": 6, "t2": 4, "w": 6, "l": 4,
     "t1_from": {"l": 1}, "t2_from": {"l": 2}},
    {"p": 1, "m": 6, "r": 3, "t1": 1, "t2": 2, "w": 1, "l": 2,
     "t1_from": {"w": 3}, "t2_from": {"w": 4}},
]


def test_sleeper_byes_infers_first_round_byes_from_raw_id_slots():
    byes = playoffs._sleeper_byes(_WB_6TM, _NAME_OF, {})
    assert byes == {"S1": 2, "S2": 2}      # both enter at round 2 -> idle round 1


def test_sleeper_byes_ignores_teams_that_played_round_one():
    byes = playoffs._sleeper_byes(_WB_6TM, _NAME_OF, {})
    for t in ("S3", "S4", "S5", "S6"):
        assert t not in byes


def test_sleeper_byes_ignores_consolation_reentrants():
    # S4/S6 reappear in the R2 placement game via `L:` refs -- a loser drop-in,
    # not a bye. A `_from` ref on the slot is the tell.
    byes = playoffs._sleeper_byes(_WB_6TM, _NAME_OF, {})
    assert "S4" not in byes and "S6" not in byes


def test_sleeper_byes_none_when_every_team_plays_round_one():
    wb = [
        {"m": 1, "r": 1, "t1": 1, "t2": 4, "w": 1, "l": 4},
        {"m": 2, "r": 1, "t1": 2, "t2": 3, "w": 3, "l": 2},
        {"p": 1, "m": 3, "r": 2, "t1": 1, "t2": 3, "w": 1, "l": 3,
         "t1_from": {"w": 1}, "t2_from": {"w": 2}},
    ]
    assert playoffs._sleeper_byes(wb, _NAME_OF, {}) == {}


def test_sleeper_byes_presumption_fallback_when_no_from_refs():
    # A malformed bracket with no `_from` anywhere: fall back to "seeded field
    # minus round-1 participants", ordered by seed.
    wb = [
        {"m": 1, "r": 1, "t1": 3, "t2": 6, "w": 3, "l": 6},
        {"m": 2, "r": 1, "t1": 4, "t2": 5, "w": 5, "l": 4},
        {"m": 3, "r": 2, "t1": 1, "t2": 3, "w": 1, "l": 3},
        {"m": 4, "r": 2, "t1": 2, "t2": 5, "w": 2, "l": 5},
        {"p": 1, "m": 5, "r": 3, "t1": 1, "t2": 2, "w": 1, "l": 2},
    ]
    seed_map = {1: "S1", 2: "S2", 3: "S3", 4: "S4", 5: "S5", 6: "S6"}
    assert playoffs._sleeper_byes(wb, _NAME_OF, seed_map) == {"S1": 2, "S2": 2}


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


# --- the unified game log (round groups -> lineups + byes + consolation) ---------
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
    log = playoffs.game_log(_S(), p, consolation={"games": []})
    g = next(gm for gm in log[0]["games"] if gm["id"] == "R1M1")
    row_by_team = {sd["team"]: sd["lineup"][0] for sd in g["sides"]}
    assert row_by_team["Al"]["cmp"] == "up"
    assert row_by_team["Bo"]["cmp"] == "down"


def test_game_log_groups_by_round_winner_first_with_lineups():
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(_S(), p, consolation={"games": []})
    # bracket order; label now carries the round's matchups in parens, e.g.
    # "Semi (TBD vs TBD, ...)" -- _S has no standings, so seeds show as TBD.
    assert [g["label"].split(" (")[0] for g in log] == ["Semi", "Final"]
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
    log = playoffs.game_log(S(), p, consolation={"games": []})
    semi = log[0]
    rank_by_team = {sd["team"]: sd["season_rank"]
                    for g in semi["games"] for sd in g["sides"]}
    assert rank_by_team == {"Al": 1, "Bo": 4, "Cy": 2, "Dee": 3}


def test_game_log_label_carries_seeded_matchups_and_blurb_is_bye_only():
    """The round header (`label`) names each game by seed, e.g. "Semi (#1 vs
    #4, #2 vs #3)" -- `blurb` is now JUST the bye callout, since matchups
    moved into the bolded title."""
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(S(), p, consolation={"games": []})
    semi = log[0]
    # Each game's own sides are already winner-first (`_sort_sides`), so the
    # seed order within a "#N vs #M" pair follows who won, not raw seed order.
    assert semi["label"] == "Semi (#1 vs #4, #3 vs #2)"
    assert semi["blurb"] is None                              # no byes this round


def test_game_log_bye_blurb_collapses_consecutive_seeds_into_a_range():
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    cfg = _cfg()
    cfg["rounds"][0]["matchups"] = [
        {"id": "R1M1", "home": {"team": "Al", "starters": ["1"]},
         "away": {"team": "Bo", "starters": ["2"]}},
        {"id": "R1B1", "bye": "Cy"}, {"id": "R1B2", "bye": "Dee"}]
    p = playoffs.playoff(cfg, validate=False)
    log = playoffs.game_log(S(), p, consolation={"games": []})
    semi = next(g for g in log if g["label"].startswith("Semi"))
    assert semi["label"] == "Semi (#1 vs #4)"
    assert semi["blurb"] == "Seeds 2-3 on a bye."


def test_game_log_pick_round_names_the_chooser_and_the_leftover():
    """A round whose display name says "pick" (this league's own
    choose-your-opponent bracket) gets a blurb naming who picked whom,
    higher seed first, the last pick stated as the automatic leftover."""
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [3, 8, 4, 7]})
    cfg = _cfg(rounds=[
        {"id": "R2", "name": "Round 2 (seeds 3-4 pick)", "weeks": [16], "matchups": [
            {"id": "R2M1", "home": {"team": "Al", "starters": ["1"]},
             "away": {"team": "Bo", "starters": ["2"]}},
            {"id": "R2M2", "home": {"team": "Cy", "starters": ["3"]},
             "away": {"team": "Dee", "starters": ["4"]}},
        ]}], final="R2M1")
    p = playoffs.playoff(cfg, validate=False)
    log = playoffs.game_log(S(), p, consolation={"games": []})
    rd = log[0]
    assert rd["blurb"] == "Seed 3 chooses #8, leaving seed 4 to take on #7."
    # The config's own "(seeds 3-4 pick)" suffix is stripped from the title --
    # it's now redundant with the seeded matchups AND the blurb's own pick
    # sentence, even though "pick" detection still reads the raw config name.
    assert rd["label"] == "Round 2 (#3 vs #8, #4 vs #7)"


def test_game_log_non_pick_round_has_no_pick_blurb():
    """A round without "pick" in its display name (the ordinary case) never
    gets pick phrasing, even if season_rank happens to be available."""
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    p = playoffs.playoff(_cfg(), validate=False)
    log = playoffs.game_log(S(), p, consolation={"games": []})
    assert log[0]["blurb"] is None


def test_game_log_bye_carries_manager_season_rank():
    class S(_S):
        standings = pd.DataFrame({"user_name": ["Al", "Bo", "Cy", "Dee"],
                                  "final_position": [1, 4, 2, 3]})
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][1] = {"id": "R1M2", "bye": "Dee"}
    p = playoffs.playoff(cfg, validate=False)
    log = playoffs.game_log(S(), p, consolation={"games": []})
    semi = next(g for g in log if g["label"].startswith("Semi"))
    assert semi["byes"][0]["team"] == "Dee" and semi["byes"][0]["season_rank"] == 3


def test_game_log_consolation_sides_pass_through_season_rank_and_bench():
    """Consolation bracket games are handed to game_log already-built (by
    consolation_bracket()); game_log's own transcoding of them must carry
    `season_rank` and `bench` through rather than dropping them, same as
    `lineup`."""
    p = playoffs.playoff(_cfg(), validate=False)
    consolation = {"games": [{"week": 15, "sides": [
        {"team": "X", "points": 100.0, "result": "W", "season_rank": 5, "lineup": [],
         "bench": [{"player_id": "9", "player_name": "Ike", "position": "TE", "points": 3.0}]},
        {"team": "Y", "points": 90.0, "result": "L", "season_rank": 2, "lineup": []}]}]}
    log = playoffs.game_log(_S(), p, consolation=consolation)
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
    log = playoffs.game_log(_S(), p, consolation={"games": []})
    g = log[0]["games"][0]
    row_by_pid = {r["player_id"]: r for sd in g["sides"] for r in sd["lineup"]}
    assert row_by_pid["1"]["pos_rank"] == 2
    assert row_by_pid["2"]["pos_rank"] == 5


def test_game_log_folds_in_byes_and_the_consolation_bracket():
    cfg = _cfg()
    cfg["rounds"][0]["matchups"][1] = {"id": "R1M2", "bye": "Dee"}
    p = playoffs.playoff(cfg, validate=False)
    consolation = {"games": [{"week": 15, "sides": [
        {"team": "X", "points": 100.0, "result": "W", "lineup": []},
        {"team": "Y", "points": 90.0, "result": "L", "lineup": []}]}]}
    log = playoffs.game_log(_S(), p, consolation=consolation)
    semi = next(g for g in log if g["label"].startswith("Semi"))
    assert [b["team"] for b in semi["byes"]] == ["Dee"]       # bye rides its round
    tb = log[-1]                                              # consolation bracket -- one group per week
    assert tb["kind"] == "consolation" and tb["label"].startswith("Consolation bracket, Round 1")
    assert tb["weeks"] == "15" and tb["is_final"]
    assert tb["games"][0]["winner"] == "X" and tb["games"][0]["margin"] == 10.0


def test_game_log_splits_the_consolation_bracket_into_one_round_per_week():
    """A multi-week consolation bracket reads round-by-round like the bracket above it:
    one `kind == "consolation"` group per postseason week, week number carried in
    `weeks`, the "missed the bracket" framing on the first and the last-place
    callout on the final round only."""
    p = playoffs.playoff(_cfg(), validate=False)
    consolation = {"basis": "game", "last": "Y", "games": [
        {"week": 15, "sides": [
            {"team": "X", "points": 100.0, "result": "W", "lineup": []},
            {"team": "Y", "points": 90.0, "result": "L", "lineup": []}]},
        {"week": 16, "sides": [
            {"team": "X", "points": 80.0, "result": "L", "lineup": []},
            {"team": "Y", "points": 95.0, "result": "W", "lineup": []}]}]}
    log = playoffs.game_log(_S(), p, consolation=consolation)
    tgrps = [g for g in log if g["kind"] == "consolation"]
    assert [g["weeks"] for g in tgrps] == ["15", "16"]
    assert tgrps[0]["label"].startswith("Consolation bracket, Round 1")
    assert tgrps[1]["label"].startswith("Consolation bracket, Round 2")
    assert "missed the championship bracket" in tgrps[0]["blurb"]
    assert tgrps[0]["blurb"] and "finishes last" not in tgrps[0]["blurb"]
    assert not tgrps[0]["is_final"] and tgrps[1]["is_final"]
    assert "Y lost the final game and finishes last." in tgrps[1]["blurb"]


_TB_TWO_WEEK = {"basis": "game", "last": "Y", "games": [
    {"week": 15, "sides": [
        {"team": "X", "points": 110.0, "result": "W", "lineup": [
            {"player_id": "p1", "player_name": "Ann", "position": "QB", "points": 30.0},
            {"player_id": "p2", "player_name": "Bo", "position": "RB", "points": 20.0}]},
        {"team": "Y", "points": 90.0, "result": "L", "lineup": [
            {"player_id": "p3", "player_name": "Cy", "position": "WR", "points": 15.0}]}]},
    {"week": 16, "sides": [
        {"team": "X", "points": 70.0, "result": "L", "lineup": [
            {"player_id": "p1", "player_name": "Ann", "position": "QB", "points": 25.0}]},
        {"team": "Y", "points": 95.0, "result": "W", "lineup": [
            {"player_id": "p3", "player_name": "Cy", "position": "WR", "points": 40.0}]}]}]}


def test_consolation_performances_is_one_row_per_started_player_week():
    d = playoffs.consolation_performances(_TB_TWO_WEEK)
    assert list(d.columns) == ["week", "team", "player_id", "player_name",
                               "position", "points"]
    assert len(d) == 5                       # 2 + 1 + 1 + 1 starters
    assert set(d["week"]) == {15, 16}
    assert d.iloc[0]["points"] == 40.0        # sorted points-descending
    assert playoffs.consolation_performances({"games": []}).empty


def test_consolation_players_aggregates_per_player_with_ppg():
    d = playoffs.consolation_players(_TB_TWO_WEEK)
    ann = d[d["player_id"] == "p1"].iloc[0]
    assert ann["games"] == 2 and ann["points"] == 55.0 and ann["ppg"] == 27.5
    cy = d[d["player_id"] == "p3"].iloc[0]
    assert cy["games"] == 2 and cy["points"] == 55.0 and cy["best"] == 40.0
    # No rings / seasons columns -- the consolation bracket has no title.
    assert "rings" not in d.columns and "seasons" not in d.columns
    assert playoffs.consolation_players({"games": []}).empty


def test_sleeper_losers_bracket_resolves_a_consolation_tree(monkeypatch):
    """`sleeper_losers_bracket` turns Sleeper's `/losers_bracket` (same node
    shape as the winners bracket) into an engine config: round-2 raw-id
    entrants are byes, `p == 1` is the final, other `p` values are
    placements.  Modelled on Coin Flip and FF 2025's real 7-node bracket."""
    LB = [
        {"r": 1, "m": 1, "t1": 3, "t2": 2, "w": 2, "l": 3, "t1_from": None, "t2_from": None, "p": None},
        {"r": 1, "m": 2, "t1": 7, "t2": 6, "w": 7, "l": 6, "t1_from": None, "t2_from": None, "p": None},
        {"r": 2, "m": 3, "t1": 11, "t2": 2, "w": 11, "l": 2, "t1_from": None, "t2_from": {"w": 1}, "p": None},
        {"r": 2, "m": 4, "t1": 10, "t2": 7, "w": 7, "l": 10, "t1_from": None, "t2_from": {"w": 2}, "p": None},
        {"r": 2, "m": 5, "t1": 3, "t2": 6, "w": 3, "l": 6, "t1_from": {"l": 1}, "t2_from": {"l": 2}, "p": 5},
        {"r": 3, "m": 6, "t1": 11, "t2": 7, "w": 7, "l": 11, "t1_from": {"w": 3}, "t2_from": {"w": 4}, "p": 1},
        {"r": 3, "m": 7, "t1": 2, "t2": 10, "w": 10, "l": 2, "t1_from": {"l": 3}, "t2_from": {"l": 4}, "p": 3},
    ]
    names = {2: "Bea", 3: "Cal", 6: "Fox", 7: "Gil", 10: "Jan", 11: "Kai"}
    monkeypatch.setattr(playoffs, "_bracket_context",
                        lambda lid, season=None: (
                            {"season": "2025"}, "L", {"name": "TestLg",
                             "roster_positions": ["QB"], "scoring_settings": RULES,
                             "settings": {"playoff_week_start": 15}}, names))
    monkeypatch.setattr(playoffs, "sleeper_api",
                        lambda path: LB if path.endswith("losers_bracket") else [])
    monkeypatch.setattr(playoffs, "_week_starters", lambda lid, wk: {})
    playoffs._gen_cache.clear()
    cfg = playoffs.sleeper_losers_bracket("L", "2025")
    assert cfg is not None
    rounds = {r["id"]: r for r in cfg["rounds"]}
    assert set(rounds) == {"R1", "R2", "R3"}
    # Round 1: two games + two byes (roster ids 11 and 10 enter fresh in R2).
    r1_byes = sorted(m["bye"] for m in rounds["R1"]["matchups"] if m.get("bye"))
    assert r1_byes == ["Jan", "Kai"]
    assert cfg["final"] == "M6"
    assert cfg["_placements"] == {"M5": 5, "M7": 3}
    # The config runs through the engine and crowns the best consolation finish.
    p = playoffs.playoff(cfg, validate=False)
    assert (p.results["result"] == "BYE").sum() == 2


def test_sleeper_losers_bracket_none_when_empty(monkeypatch):
    monkeypatch.setattr(playoffs, "_bracket_context",
                        lambda lid, season=None: (
                            {"season": "2025"}, "L",
                            {"name": "X", "roster_positions": [], "scoring_settings": {},
                             "settings": {}}, {}))
    monkeypatch.setattr(playoffs, "sleeper_api", lambda path: [])
    playoffs._gen_cache.clear()
    assert playoffs.sleeper_losers_bracket("L", "2025") is None


def test_playoff_performances_folds_the_consolation_bracket_in_only_for_all_scope():
    """`consolation=` merges the consolation bracket player-weeks into the bracket frame,
    tagged `bracket == "consolation"` -- but only surfaces when `scope == "all"`
    (the Postseason view); `scope == "title"` filters them straight back out."""
    p = playoffs.playoff(_cfg(), validate=False)
    tb = {"games": [{"week": 15, "sides": [
        {"team": "Zz", "points": 88.0, "result": "W", "lineup": [
            {"player_id": "p9", "player_name": "Zed", "position": "K", "points": 9.0}]},
        {"team": "Yy", "points": 80.0, "result": "L", "lineup": []}]}]}
    d_title = playoffs.playoff_performances({"2025": p}, "title", consolation=[tb])
    assert "consolation" not in set(d_title["bracket"])          # scoped out
    d_all = playoffs.playoff_performances({"2025": p}, "all", consolation=[tb])
    trow = d_all[d_all["bracket"] == "consolation"]
    assert len(trow) == 1 and trow.iloc[0]["player_id"] == "p9"
    assert pd.isna(trow.iloc[0]["round_id"])                # no bracket round


def test_clutch_with_consolation_pools_bracket_and_consolation_team_weeks():
    """The Postseason clutch chart's data: `consolation=` + `scope="all"` counts a
    team's bracket games AND its consolation bracket games toward its postseason PPG."""
    class S:
        team_wk = pd.DataFrame({"user_name": ["Al", "Zz"], "points": [100.0, 100.0]})
    p = playoffs.playoff(_cfg(), validate=False)
    tb = {"games": [{"week": 15, "sides": [
        {"team": "Zz", "points": 120.0, "result": "W", "lineup": []},
        {"team": "Al", "points": 60.0, "result": "L", "lineup": []}]}]}
    d = playoffs.clutch({"2025": S()}, {"2025": p}, "all", consolation=[tb])
    # Zz played no bracket game, so its only postseason game is the consolation one.
    zz = d[d["user_name"] == "Zz"].iloc[0]
    assert zz["games"] == 1 and zz["po_ppg"] == 120.0
    # Without consolation= Zz would not appear at all (never in the bracket).
    d_no = playoffs.clutch({"2025": S()}, {"2025": p}, "all")
    assert "Zz" not in set(d_no["user_name"])


def test_consolation_clutch_sets_consolation_ppg_against_regular_season_ppg():
    class S:
        team_wk = pd.DataFrame({"user_name": ["X", "X", "Y", "Y"],
                                "points": [100.0, 120.0, 80.0, 80.0]})
    d = playoffs.consolation_clutch(S(), _TB_TWO_WEEK)
    x = d[d["user_name"] == "X"].iloc[0]
    assert x["reg_ppg"] == 110.0 and x["to_ppg"] == 90.0    # (110+70)/2
    assert round(x["clutch"], 1) == -20.0
    y = d[d["user_name"] == "Y"].iloc[0]
    assert y["to_ppg"] == 92.5 and round(y["clutch"], 1) == 12.5
    # Sorted clutch-descending: Y (better in the consolation bracket) leads.
    assert d.iloc[0]["user_name"] == "Y"
    assert playoffs.consolation_clutch(S(), {"games": []}).empty


def test_consolation_bracket_carries_each_missed_teams_own_postseason_record():
    """The combined Postseason-results board fills a missed team's G/W/L/PPG/
    High/Low/Margin from the consolation bracket games it actually played, not blanks --
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

    t = playoffs.consolation_bracket(S(), p=P())
    al = next(x for x in t["teams"] if x["user_name"] == "Al")
    bo = next(x for x in t["teams"] if x["user_name"] == "Bo")
    assert (al["po_games"], al["po_wins"], al["po_losses"]) == (1, 1, 0)
    assert al["po_ppg"] == al["po_high"] == al["po_low"] == 100.0
    assert al["po_avg_margin"] == 10.0
    assert (bo["po_games"], bo["po_wins"], bo["po_losses"]) == (1, 0, 1)
    assert bo["po_avg_margin"] == -10.0
    # The final game settles both ends: its WINNER (Al, 100 > 90) tops the
    # consolation bracket; its loser (Bo) is last. `winner` must be the
    # actual match winner, not the last-place team.
    assert t["last"] == "Bo" and t["winner"] == "Al" and t["basis"] == "game"


def test_consolation_bracket_lineups_and_sides_carry_player_and_manager_ranks(monkeypatch):
    """The consolation bracket is a plain Sleeper matchup, so its lineups come from
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

    t = playoffs.consolation_bracket(S(), p=P())
    game = next(g for g in t["games"] if g["week"] == 15)
    al_side = next(sd for sd in game["sides"] if sd["team"] == "Al")
    assert al_side["lineup"][0]["player_id"] == "5"
    assert al_side["lineup"][0]["pos_rank"] == 3
    assert al_side["season_rank"] == 3


def test_consolation_bracket_sides_carry_bench_and_slot_cmp():
    """Unlike a bracket game (commissioner-submitted starters only), the
    consolation bracket reads a real `pl_wk` roster -- so its own `bench` (everyone
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

    t = playoffs.consolation_bracket(S(), p=P())
    game = next(g for g in t["games"] if g["week"] == 15)
    al = next(sd for sd in game["sides"] if sd["team"] == "Al")
    bo = next(sd for sd in game["sides"] if sd["team"] == "Bo")
    assert al["bench"][0]["player_id"] == "6" and al["bench"][0]["points"] == 30.0
    assert bo["bench"][0]["player_id"] == "8" and bo["bench"][0]["points"] == 20.0
    # Both starters are RB -- the same fallback slot (slots={}) -- so they're
    # directly comparable: Al's 100 beats Bo's 90.
    assert al["lineup"][0]["cmp"] == "up"
    assert bo["lineup"][0]["cmp"] == "down"


def test_consolation_bracket_po_fields_are_none_without_a_consolation_game():
    """A team that missed the bracket but never got a consolation bracket game (no
    opponent pool) must show blank po_* fields, not a stray 0 beside a dash."""
    class S:
        standings = pd.DataFrame({
            "user_name": ["Al"], "final_position": [4],
            "wins": [3], "losses": [9], "points": [1200.0]})
        team_wk_all = None

    t = playoffs.consolation_bracket(S(), p=None)
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
