import os

import pandas as pd
import pytest

from sleepermetrics import metrics, plots, summaries
from sleepermetrics.discord_bot import _render_command
from sleepermetrics.league import starter_slots
from sleepermetrics.season import optimal_points
from sleepermetrics.weekly import summary_week

from conftest import make_season


def test_boom_bust_has_avg_and_spread():
    d = metrics.boom_bust(make_season())
    assert set(["user_name", "avg", "sd", "floor", "ceiling"]).issubset(d.columns)
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["avg"] == 115.0                      # mean(100, 130)
    assert al["ceiling"] == 130.0 and al["floor"] == 100.0


def test_strength_of_schedule_uses_opponent_ppg():
    d = metrics.strength_of_schedule(make_season())
    # Al faced Bo both weeks; Bo's season PPG = mean(90, 70) = 80.
    assert d[d["user_name"] == "Al"].iloc[0]["sos"] == 80.0
    assert list(d["rank"]) == sorted(d["rank"])


def test_schedule_swap_diagonal_is_the_real_record():
    d = metrics.schedule_swap(make_season())
    # Al under Al's own schedule = the real record: beat Bo twice.
    al = d[(d["team"] == "Al") & (d["schedule_of"] == "Al")].iloc[0]
    assert al["wins"] == 2 and al["losses"] == 0
    # Al under Cy's schedule: Cy had no opponent, so no games are counted.
    alcy = d[(d["team"] == "Al") & (d["schedule_of"] == "Cy")].iloc[0]
    assert alcy["wins"] == 0 and alcy["losses"] == 0


def test_head_to_head_is_symmetric_and_named():
    d = metrics.head_to_head({"2025": make_season()})
    ab = d[(d["user_name"] == "Al") & (d["opp_name"] == "Bo")].iloc[0]
    ba = d[(d["user_name"] == "Bo") & (d["opp_name"] == "Al")].iloc[0]
    assert ab["wins"] == 2 and ab["losses"] == 0    # Al beat Bo twice
    assert ba["wins"] == 0 and ba["losses"] == 2    # ...and the mirror


def test_record_book_reports_superlatives():
    recs = metrics.record_book({"2025": make_season()})
    labels = {r["label"]: r for r in recs}
    assert labels["Highest score"]["holder"] == "Al"       # 130 in wk2
    assert labels["Highest score"]["value"] == "130.0"


def test_undrafted_standouts_excludes_drafted_and_ranks_by_started_points(monkeypatch):
    """The best players who went undrafted, ranked by roster-accumulated points
    -- drafted players are excluded, and a churned pickup is attributed to
    whoever got the most out of him. Seeds a fake draft board so 'undrafted' is
    well defined."""
    import dataclasses

    import pandas as pd
    from sleepermetrics import draft, metrics as _metrics
    # undrafted_standouts also computes true-season total/pos_rank via
    # metrics.season_position_ranks, and a trend sparkline via
    # draft._season_trend -- both price every real NFL stat line, a real
    # network call this fixture's fake league_id can't serve. Not what this
    # test is checking, so stub both out rather than pull in the whole
    # scoring/players mocking chain test_playoffs.py uses for that.
    # (_attach_team_splits' per-team pos_steal/pos_adj -- a multi-team player
    # here, Waiver Ace -- is priced purely off season_position_ranks()'s own
    # output now, no separate network-backed primitive, so no extra stub
    # is needed for it.)
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: {})
    monkeypatch.setattr(draft, "_season_trend", lambda s, ids: {})
    s = make_season()
    # A populated pl_wk: pDraft was drafted; pFA and pStash were not.
    pl = pd.DataFrame({
        "week":       [1, 1, 2, 2, 1, 2],
        "roster_id":  [1, 2, 1, 3, 2, 2],
        "player_id":  ["pDraft", "pFA", "pDraft", "pFA", "pStash", "pStash"],
        "points":     [30.0, 25.0, 20.0, 40.0, 5.0, 3.0],
        "is_starter": [True, True, True, True, True, True],
        "player_name": ["Drafted Guy", "Waiver Ace", "Drafted Guy",
                        "Waiver Ace", "Deep Stash", "Deep Stash"],
        "position":   ["RB", "WR", "RB", "WR", "TE", "TE"],
    })
    # pl_wk_all defaults to whatever pl_wk WAS at construction time
    # (Season.__post_init__ only fires once, in make_season()'s own call) --
    # dataclasses.replace() doesn't re-run that default, so it must be passed
    # explicitly here too, or draft.py's pl_wk_all-based reads (weeks/teams/
    # activity, now postseason-inclusive) see the ORIGINAL empty frame
    # instead of this fixture's real one.
    s = dataclasses.replace(s, pl_wk=pl, pl_wk_all=pl)
    # Seed the draft cache so pDraft is the only drafted player.
    board = pd.DataFrame([{c: None for c in draft._COLS}])
    board.loc[0, ["player_id", "pick_no", "round"]] = ["pDraft", 1, 1]
    draft._cache[f"{s.league_id}:{s.season}"] = board

    out = draft.undrafted_standouts(s)
    names = list(out["player_name"])
    assert "Drafted Guy" not in names            # drafted -> excluded
    assert names[0] == "Waiver Ace"              # 25+40 = 65, ranks first
    ace = out.iloc[0]
    assert ace["points"] == 65.0 and ace["teams"] == 2   # started for rosters 2 and 3
    assert ace["user_name"] == "Cy"              # roster 3 got 40 > roster 2's 25
    draft._cache.clear()


def test_all_players_impact_gates_on_real_rank_membership(monkeypatch):
    """The merged draft-and-wire view: every drafted pick survives regardless
    of output (a zero-point pick is still a real, notable pick -- often the
    whole point of looking at it). Every OTHER real player is included if he
    has at least one real stat-line week this season (i.e. is a member of
    `season_position_ranks`) -- REGARDLESS of whether any DDBM manager ever
    rostered him at all (so the position-rank sequence stays gapless), with
    `user_name` reading "FA" for one nobody ever added. A real player who
    simply never recorded a stat line at all (absent from `ranks`, never
    drafted either) is excluded -- there's no real season to report on him.
    Default order is TOTAL POINTS descending (drafted and undrafted mixed
    into one ranked list), not draft order."""
    import dataclasses

    import pandas as pd
    from sleepermetrics import draft, metrics as _metrics
    # `ranks` is now the gate: pRostered and pNeverAdded both have real
    # entries (so both survive); pNoStatLine has none (so it's excluded
    # despite being a real, if practice-squad-level, player_id).
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: {
        "pRostered": {"points": 65.0, "rank": 12, "position": "WR"},
        "pNeverAdded": {"points": 30.0, "rank": 40, "position": "WR"},
    })
    monkeypatch.setattr(draft, "_season_trend", lambda s, ids: {})
    # draft.py calls the imported `players` name directly (`from .players
    # import players`), so the patch target is draft.players, not the
    # sleepermetrics.players module.
    monkeypatch.setattr(draft, "players", lambda *a, **k: pd.DataFrame({
        "player_id": ["pRostered", "pNeverAdded", "pNoStatLine"],
        "player_name": ["Rostered Find", "Never Added", "No Stat Line"],
        "position": ["WR", "WR", "WR"],
    }))
    s = make_season()
    pl = pd.DataFrame({
        "week":       [1, 2],
        "roster_id":  [2, 2],
        "player_id":  ["pRostered", "pRostered"],
        "points":     [25.0, 40.0],
        "is_starter": [True, True],
        "player_name": ["Rostered Find", "Rostered Find"],
        "position":   ["WR", "WR"],
    })
    # See the equivalent comment in test_undrafted_standouts_... above --
    # pl_wk_all must be passed explicitly alongside pl_wk on a replace().
    s = dataclasses.replace(s, pl_wk=pl, pl_wk_all=pl)
    board = pd.DataFrame([{c: None for c in draft._COLS}])
    # `rostered_weeks`/`rostered_ppg` (all-teams, what all_players_impact()
    # actually renames to the outward `weeks`/`ppg`) must be seeded too, not
    # just the drafting-team-only `ppg` -- a real draft_board() call always
    # populates both from pl_wk_all, but this hand-built board bypasses that
    # computation, and leaving them at the {c: None} default (object dtype)
    # concatenates against the undrafted half's real float `ppg` column and
    # trips a pandas FutureWarning on an all-NA column.
    board.loc[0, ["player_id", "player_name", "position", "round", "pick_no",
                  "pick_in_round", "draft_slot", "roster_id", "total",
                  "pos_repl_ppg", "user_name", "ppg", "rostered_weeks",
                  "rostered_ppg", "pos_adj", "pos_steal",
                  "pos_rank"]] = ["pDraft", "Drafted Bust", "RB", 1, 1, 1, 1,
                                   1, 0.0, 0.0, "Al", 0.0, 0, 0.0, 0.0, 0, 0]
    draft._cache[f"{s.league_id}:{s.season}"] = board

    out = draft.all_players_impact(s)
    names = list(out["player_name"])
    assert "Drafted Bust" in names            # drafted, 0 total -> still included
    assert "No Stat Line" not in names        # never in ranks, never drafted -> excluded
    assert "Rostered Find" in names           # undrafted but in ranks, rostered here -> included
    assert "Never Added" in names             # undrafted, in ranks, NOBODY rostered him -> included
    # Default sort = total pts descending: Rostered Find (65.0) > Never
    # Added (30.0) > Drafted Bust (0.0).
    assert names == ["Rostered Find", "Never Added", "Drafted Bust"]
    assert (out["pick"] == "UDFA").sum() == 2          # Rostered Find, Never Added
    rostered = out[out["player_name"] == "Rostered Find"].iloc[0]
    assert rostered["pick"] == "UDFA"
    assert rostered["user_name"] == "Bo"      # roster_id 2 -> real manager
    never_added = out[out["player_name"] == "Never Added"].iloc[0]
    assert never_added["pick"] == "UDFA"
    assert never_added["user_name"] == "FA"   # nobody in this league ever rostered him
    assert never_added["teams"] == 0
    draft._cache.clear()


def test_mixed_flags_pos_steal_vs_pos_adj_not_steal_vs_pos_steal(monkeypatch):
    """`mixed` compares the two columns actually shown on the Draft-finds
    table -- `pos_steal` (+/-, a RANK read: draft-slot rank vs. true finish
    rank at the position) and `pos_adj` (a MAGNITUDE read: true points vs.
    replacement level) -- NOT `steal` vs `pos_steal` (an earlier version).
    `steal` isn't even a displayed column, and comparing it against
    `pos_steal` conflated two different-sized comparison pools: `steal`
    ranks only within the players actually DRAFTED at a position, while
    `pos_steal` ranks against the full real-NFL universe at that position.
    That pool-size gap alone could flip the sign even at IDENTICAL points
    (2025's Jerry Jeudy, the case that prompted this fix) -- a false "mixed"
    with no real value disagreement behind it.

    Two players, two positions (independent replacement levels, s.slots ==
    {} except a TE slot below), each with team-realized `points` equal to
    their true total (single team, full season -- so this isn't about
    roster/trade scope at all):

    - pA (WR): drafted 2nd among 3 WRs but out-produces the other two
      drafted WRs (steal = +1, a "team-realized win"). Six additional real
      (never-drafted) WRs outscore him, though, so his TRUE finish is only
      7th overall -- capped at drafted_n=3, pos_steal = 2-3 = -1. `steal`
      and `pos_steal` disagree in sign (the OLD definition would flag this).
      But pA's true points (40) sit well below the position's replacement
      level (100, the league's best real WR, since WR's pool_size is 1 with
      no WR slot configured) -- pos_adj is ALSO negative, agreeing with
      pos_steal. Correctly NOT mixed under the new definition: he's a
      straightforward bust by both the rank read and the magnitude read,
      once `steal` (an unrelated comparison pool) is taken out of it.
    - pT2 (TE): drafted 1st among 3 TEs (pos_pick_rank=1) but finishes 2nd
      of 4 real TEs (one undrafted TE narrowly outscores him) -- pos_steal
      = 1-2 = -1 (negative, a real if mild rank miss). With a TE slot
      configured (pool_size=3 for a 3-team league), replacement level is
      the 3rd-best real TE's 10 points -- pT2's own 55 clears that by a
      wide margin, so pos_adj = +45 (positive). pos_steal/pos_adj
      genuinely disagree in sign here -- correctly flagged mixed.
    """
    from sleepermetrics import draft

    ranks = {
        "pA": {"position": "WR", "rank": 7, "points": 40.0},
        "pB": {"position": "WR", "rank": 8, "points": 20.0},
        "pC": {"position": "WR", "rank": 9, "points": 10.0},
        "pX1": {"position": "WR", "rank": 1, "points": 100.0},
        "pX2": {"position": "WR", "rank": 2, "points": 90.0},
        "pX3": {"position": "WR", "rank": 3, "points": 80.0},
        "pX4": {"position": "WR", "rank": 4, "points": 70.0},
        "pX5": {"position": "WR", "rank": 5, "points": 60.0},
        "pX6": {"position": "WR", "rank": 6, "points": 50.0},
        "pT1": {"position": "TE", "rank": 1, "points": 60.0},
        "pT2": {"position": "TE", "rank": 2, "points": 55.0},
        "pT3": {"position": "TE", "rank": 3, "points": 10.0},
        "pTX": {"position": "TE", "rank": 4, "points": 5.0},
    }
    monkeypatch.setattr(draft.metrics, "season_position_ranks", lambda s: ranks)
    monkeypatch.setattr(draft, "players", lambda: pd.DataFrame({
        "player_id": ["pB", "pA", "pC", "pT2", "pT1", "pT3"],
        "player_name": ["WR Two", "WR Ay", "WR Cee", "TE Two", "TE One", "TE Three"],
        "position": ["WR", "WR", "WR", "TE", "TE", "TE"],
    }))

    s = make_season()
    import dataclasses

    # make_season() itself pre-seeds an EMPTY board at this cache key (so
    # other, unrelated tests never hit the network) -- clear it or
    # draft_board() below short-circuits on the stale empty entry instead of
    # calling the stubbed sleeper_api.
    draft._cache.pop(f"{s.league_id}:{s.season}", None)
    s = dataclasses.replace(
        s, slots={"TE": 1},
        user_map=pd.DataFrame({"roster_id": [1, 2, 3], "user_id": ["1", "2", "3"],
                                "user_name": ["Al", "Bo", "Cy"]}))
    pl_wk = pd.DataFrame({
        "week": [1, 1, 1, 1, 1, 1],
        "roster_id": [1, 1, 1, 1, 1, 1],
        "player_id": ["pB", "pA", "pC", "pT2", "pT1", "pT3"],
        "points": [20.0, 40.0, 10.0, 55.0, 60.0, 10.0],
        "position": ["WR", "WR", "WR", "TE", "TE", "TE"],
        "player_name": ["WR Two", "WR Ay", "WR Cee", "TE Two", "TE One", "TE Three"],
    })
    s = dataclasses.replace(s, pl_wk=pl_wk, pl_wk_all=pl_wk)

    # Raw shape of Sleeper's own /draft/{id}/picks response -- see
    # draft_board()'s own parsing loop for the fields it reads.
    picks = [
        {"round": 1, "pick_no": 1, "draft_slot": 1, "roster_id": 1, "player_id": "pB"},
        {"round": 1, "pick_no": 2, "draft_slot": 1, "roster_id": 1, "player_id": "pA"},
        {"round": 1, "pick_no": 3, "draft_slot": 1, "roster_id": 1, "player_id": "pC"},
        {"round": 1, "pick_no": 4, "draft_slot": 1, "roster_id": 1, "player_id": "pT2"},
        {"round": 1, "pick_no": 5, "draft_slot": 1, "roster_id": 1, "player_id": "pT1"},
        {"round": 1, "pick_no": 6, "draft_slot": 1, "roster_id": 1, "player_id": "pT3"},
    ]
    monkeypatch.setattr(draft, "sleeper_api", lambda path: (
        [{"draft_id": "d1", "settings": {"rounds": 6}}] if path.endswith("/drafts")
        else picks))

    d = draft.draft_board(s)
    pa = d[d["player_id"] == "pA"].iloc[0]
    pt2 = d[d["player_id"] == "pT2"].iloc[0]

    assert pa["steal"] == 1 and pa["pos_steal"] == -1     # old definition WOULD flag (signs differ)
    assert pa["pos_adj"] < 0                               # true magnitude also negative -- agrees w/ pos_steal
    assert pa["mixed"] == False                            # correctly NOT mixed: no real disagreement

    assert pt2["pos_steal"] == -1 and pt2["pos_adj"] > 0   # rank read negative, magnitude read positive
    assert pt2["mixed"] == True                            # genuinely disagree -- correctly flagged
    draft._cache.clear()


def test_value_ranks_are_cross_position_normalized(monkeypatch):
    """`_value_ranks` -- the primitive behind the Draft tab's round-based
    highlight and its Actual/Redraft toggle -- ranks by points ABOVE
    POSITION REPLACEMENT (pos_adj), not raw points, so a lower-scoring
    player at a shallower position can rank above a bigger-volume player at
    a deeper one once each is measured against his own position's bar (the
    same cross-position normalization pos_adj already uses; ranking on raw
    points would reintroduce the Cam Ward bug -- see draft.py). With
    s.slots == {} (make_season's fixture), _replacement_level's pool size
    is 1 at every position, so replacement = that position's own top
    scorer. `redraft_board()` no longer uses this ranking itself (see the
    points-first/reach-trigger tests below) -- this only covers
    `draft_board()`'s own dv-highlight, which still does.
    """
    from sleepermetrics import draft, metrics as _metrics

    s = make_season()
    ranks = {
        "pQB": {"position": "QB", "rank": 1, "points": 200.0},   # = QB replacement (top QB)
        "pQB2": {"position": "QB", "rank": 2, "points": 150.0},  # 50 below replacement
        "pTE": {"position": "TE", "rank": 1, "points": 80.0},    # = TE replacement (top TE)
        "pTE2": {"position": "TE", "rank": 2, "points": 70.0},   # 10 below replacement
    }
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: ranks)

    vranks = draft._value_ranks(s, ranks)
    # pQB2 outscores pTE2 in raw points (150 > 70) but is worse relative to
    # his OWN position's bar (-50 vs -10) -- the cross-position-normalized
    # ranking must prefer pTE2.
    assert vranks["pQB2"] > vranks["pTE2"]
    assert {vranks["pQB"], vranks["pTE"]} == {1, 2}   # both AT their own replacement level


def test_redraft_board_defaults_to_points_when_no_position_is_in_crunch(monkeypatch):
    """`redraft_board()`'s DEFAULT pick (no unmet dedicated requirement in
    play) is the single highest raw-points remaining player, full stop --
    NOT `_value_ranks`'/pos_adj's points-above-replacement. This is exactly
    the case the old pos_adj-based ranking got backwards: a Kicker with a
    huge pos_adj gap off modest raw points (a compressed-scoring position)
    used to outrank a bigger raw-points player at a deeper position purely
    on that math artifact, not because taking a K early is a plausible
    strategy -- see the function's own docstring.

    `s.slots == {}` here (make_season's fixture, one team) means no
    position has a dedicated requirement, so the reach trigger never fires
    and every pick is pure highest-points-remaining -- see the sibling test
    below for what happens once a requirement IS in play.
    """
    from sleepermetrics import draft, metrics as _metrics

    s = make_season()
    ranks = {
        "pK": {"position": "K", "rank": 1, "points": 189.0},    # huge pos_adj gap (compressed
                                                                  # K scoring), but fewer raw pts
        "pTE": {"position": "TE", "rank": 6, "points": 200.1},  # more raw points, modest pos_adj
    }
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: ranks)

    board = pd.DataFrame([{c: None for c in draft._COLS} for _ in range(2)])
    board.loc[:, ["player_id", "pick_no", "round", "pick_in_round",
                  "draft_slot", "roster_id", "user_name"]] = [
        ["pK", 1, 1, 1, 1, 1, "Al"],
        ["pTE", 2, 1, 1, 1, 1, "Al"],
    ]
    draft._cache[f"{s.league_id}:{s.season}"] = board
    monkeypatch.setattr(draft, "players", lambda: pd.DataFrame({
        "player_id": ["pK", "pTE"], "player_name": ["Kicker Guy", "TE Guy"],
        "position": ["K", "TE"],
    }))

    rdb = draft.redraft_board(s)
    # Points-first: the TE (more raw points) goes at pick 1, not the K --
    # the opposite of what pos_adj-based ranking would have done.
    assert rdb.sort_values("pick_no")["player_id"].tolist() == ["pTE", "pK"]
    draft._cache.clear()


def test_redraft_board_reach_trigger_fills_an_unmet_requirement_before_running_out(monkeypatch):
    """Once a team is down to its LAST chance to fill a dedicated (non-FLEX)
    roster requirement, the reach trigger overrides the points-first default
    even for a much bigger points gap -- otherwise a team could spend every
    pick on skill positions and simply never field a legal K, which the
    original pos_adj system never had to guard against (it always drafted
    every position's own best-ranked player somewhere in the grid).
    """
    import dataclasses

    from sleepermetrics import draft, metrics as _metrics

    s = make_season()
    s = dataclasses.replace(
        s, slots={"K": 1},   # one required, dedicated K slot per team
        user_map=pd.DataFrame({"roster_id": [1], "user_id": ["1"], "user_name": ["Al"]}))
    ranks = {
        "pWR": {"position": "WR", "rank": 1, "points": 150.0},
        "pRB": {"position": "RB", "rank": 1, "points": 120.0},
        "pK": {"position": "K", "rank": 1, "points": 50.0},
    }
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: ranks)

    # Al's whole draft: exactly 2 picks, only 1 of which can be spent on
    # anything other than the mandatory K without leaving it unfilled.
    board = pd.DataFrame([{c: None for c in draft._COLS} for _ in range(2)])
    board.loc[:, ["player_id", "pick_no", "round", "pick_in_round",
                  "draft_slot", "roster_id", "user_name"]] = [
        ["pWR", 1, 1, 1, 1, 1, "Al"],
        ["pRB", 2, 2, 1, 1, 1, "Al"],
    ]
    draft._cache[f"{s.league_id}:{s.season}"] = board
    monkeypatch.setattr(draft, "players", lambda: pd.DataFrame({
        "player_id": ["pWR", "pRB", "pK"],
        "player_name": ["WR Guy", "RB Guy", "K Guy"],
        "position": ["WR", "RB", "K"],
    }))

    rdb = draft.redraft_board(s)
    picks = rdb.sort_values("pick_no")["player_id"].tolist()
    # Pick 1: no urgency yet (2 picks left, 1 unmet requirement) -- pure
    # points-first, the WR (150) over the RB (120) or K (50).
    assert picks[0] == "pWR"
    # Pick 2 (Al's LAST pick): the reach trigger forces the K even though
    # the RB (120 pts) scores far more -- the only way Al ends up with a
    # legal roster at all.
    assert picks[1] == "pK"
    draft._cache.clear()


def test_redraft_side_score_bench_is_not_capped():
    """A leftover redrafted roster used to be capped at the top 6 by points
    -- silently dropping the bottom of the bench off the drilldown entirely
    on any week with more than 6 unpicked players. That's exactly backwards
    on a bye/IR/injury week: a 0-point (or merely low) scorer sorts to the
    BOTTOM, so a cap hid precisely the players a manager would want an
    explanation for (shipped: DDBM 2025 LuckyHarm's Drake London vanished
    from Round 3's bench entirely on an 8-unpicked week). `plist` here is
    scoped to one team's own redrafted roster (roster-sized, not the
    league-wide pool), so there's no risk of an unbounded list -- the fix
    is simply to stop truncating it."""
    from sleepermetrics.draft import _redraft_side_score

    plist = [(str(i), "WR") for i in range(1, 9)]      # 8 same-position players
    pts_by_pw = {(str(i), 1): float(10 - i) for i in range(1, 9)}  # 9.0 .. 2.0
    names = {str(i): f"Player{i}" for i in range(1, 9)}
    opt_lineup, opt_points, bench_rows = _redraft_side_score(
        plist, [1], pts_by_pw, names, {"WR": 1})
    assert [x.player_id for x in bench_rows] == [str(i) for i in range(2, 9)]


def test_week_matchups_bench_is_not_capped():
    """The Weekly tab's own matchup drilldown -- a REAL team's actual and
    optimal bench that week -- had the identical bug (see
    test_redraft_side_score_bench_is_not_capped): both `bench` and
    `opt_bench` were capped at the top 6 by points, so a roster with more
    than 6 non-starters that week silently lost whoever scored least --
    exactly the bye/IR/injury player a manager would want explained, not
    hidden."""
    import dataclasses

    s = make_season()
    pl_wk = pd.DataFrame({
        "week": [1] * 9,
        "roster_id": [1] * 9,
        "player_id": [str(i) for i in range(1, 10)],
        "player_name": [f"Player{i}" for i in range(1, 10)],
        "position": ["WR"] * 9,
        "points": [50.0] + [float(9 - i) for i in range(1, 9)],
        "is_starter": [True] + [False] * 8,
    })
    s = dataclasses.replace(s, pl_wk=pl_wk, slots={"WR": 1})
    games = metrics.week_matchups(s, 1)
    g = next(g for g in games if any(sd["user_name"] == "Al" for sd in g["sides"]))
    al = next(sd for sd in g["sides"] if sd["user_name"] == "Al")
    assert len(al["bench"]) == 8
    assert len(al["opt_bench"]) == 8


def test_validate_config_catches_structural_errors():
    """A custom bracket must be checked before it's scored: missing rounds,
    duplicate ids, and unresolved W:/final references are hard errors; a
    league-id mismatch is a soft warning. Kept roster_positions out so the
    lineup slot-check (which needs the player DB) doesn't run offline."""
    from sleepermetrics import validate_config

    good = {"season": "2026", "league_id": "0", "rounds": [
        {"id": "R1", "weeks": [15], "matchups": [
            {"id": "R1M1", "home": {"team": "A", "starters": []},
             "away": {"team": "B", "starters": []}},
            {"id": "R1B1", "bye": "C"}]},
        {"id": "R2", "weeks": [16], "matchups": [
            {"id": "R2M1", "home": {"team": "W:R1M1", "starters": []},
             "away": {"team": "W:R1B1", "starters": []}}]}],
        "final": "R2M1"}
    assert validate_config(good, league_id="0")["errors"] == []

    assert "missing or empty 'rounds'" in validate_config({"season": "2026"})["errors"]

    bad = {"season": "2026", "final": "NOPE", "rounds": [
        {"id": "R1", "weeks": [15], "matchups": [
            {"id": "M1", "home": {"team": "A", "starters": []},
             "away": {"team": "W:GHOST", "starters": []}},
            {"id": "M1", "bye": "B"}]}]}   # duplicate id
    errs = validate_config(bad)["errors"]
    assert any("duplicate matchup id 'M1'" in e for e in errs)
    assert any("unknown matchup 'GHOST'" in e for e in errs)
    assert any("unknown matchup 'NOPE'" in e for e in errs)

    warns = validate_config(good, league_id="999")["warnings"]
    assert any("!= current league 999" in w for w in warns)


def test_season_phase_leads_with_the_last_completed_round(monkeypatch):
    """Overview's lead must show the last COMPLETED postseason round, not
    whatever round `game_log()` last emitted a group for. `game_log()` appends
    a group for every configured round (future rounds carry only PENDING
    placeholder games), so a bare bracket config alone must still read as
    'regular', and a bracket with round 1 played must lead with round 1, not
    the final. See app._season_phase."""
    from webapp import app

    s = make_season()
    monkeypatch.setattr(app.sm, "consolation_bracket", lambda *a, **k: {})

    def phase_for(log):
        monkeypatch.setattr(app.sm, "game_log", lambda *a, **k: log)
        # `s.status` is None on the fixture (not "complete"), so this exercises
        # the mid-season branch; the `p` object is only passed through.
        return app._season_phase(s, {"playoffs": {"2025": object()}}, "2025")

    def rnd(key, played_games, pending_games=0, byes_resolved=0, byes_pending=0):
        games = ([{"pending": False}] * played_games
                 + [{"pending": True}] * pending_games)
        byes = ([{"pending": False}] * byes_resolved
                + [{"pending": True}] * byes_pending)
        return {"key": key, "kind": "title", "games": games, "byes": byes}

    # Bracket configured, nothing played: every round is a PENDING-only group,
    # plus a first-round bye that resolves structurally. Still "regular".
    ph = phase_for([rnd("R1", 0, pending_games=2, byes_resolved=1),
                    rnd("R2", 0, pending_games=1),
                    rnd("R3", 0, pending_games=1)])
    assert ph["phase"] == "regular"
    assert "current_round" not in ph

    # Round 1 decided, rounds 2-3 still PENDING: lead with round 1.
    ph = phase_for([rnd("R1", 2, byes_resolved=1),
                    rnd("R2", 0, pending_games=1),
                    rnd("R3", 0, pending_games=1)])
    assert ph["phase"] == "playoffs"
    assert ph["current_round"]["key"] == "R1"

    # Rounds 1-2 decided, round 3 PENDING: lead with round 2.
    ph = phase_for([rnd("R1", 2), rnd("R2", 1), rnd("R3", 0, pending_games=1)])
    assert ph["phase"] == "playoffs"
    assert ph["current_round"]["key"] == "R2"

    # No bracket resolved for this season at all -> regular, no game_log call.
    monkeypatch.setattr(app.sm, "game_log",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert app._season_phase(s, {"playoffs": {}}, "2025")["phase"] == "regular"


def test_season_phase_complete_recaps_every_round(monkeypatch):
    """A finished season's Overview lead recaps the WHOLE postseason run, so
    `title_rounds` there stays the full round list (not just the played
    subset), even for rounds `game_log()` only has PENDING placeholders for."""
    from webapp import app

    s = make_season()                      # status None...
    monkeypatch.setattr(s, "status", "complete", raising=False)
    monkeypatch.setattr(app.sm, "consolation_bracket", lambda *a, **k: {})
    log = [
        {"key": "R1", "kind": "title", "games": [{"pending": False}], "byes": []},
        {"key": "R2", "kind": "title", "games": [{"pending": False}], "byes": []},
        {"key": "R3", "kind": "title", "games": [{"pending": True}], "byes": []},
    ]
    monkeypatch.setattr(app.sm, "game_log", lambda *a, **k: log)

    class _P:
        champion = "Al"
    ph = app._season_phase(s, {"playoffs": {"2025": _P()}}, "2025")
    assert ph["phase"] == "complete"
    assert [g["key"] for g in ph["title_rounds"]] == ["R1", "R2", "R3"]
    assert ph["champion"] == "Al"


def test_playoff_tiles_are_all_superlatives_no_game_count():
    """The Overview postseason lead's tiles must each be a genuine standout --
    no 'N of M games decided' progress tile, no bare 'postseason games' count.
    A `lead` tile, when given (the complete-phase lead passes the champion), is
    placed FIRST and takes the gold accent. See app._playoff_tiles."""
    from webapp.app import _playoff_tiles

    def game(a, ap, b, bp, pending=False):
        sides = [{"team": a, "points": ap, "result": None if pending else ("W" if ap > bp else "L")},
                 {"team": b, "points": bp, "result": None if pending else ("W" if bp > ap else "L")}]
        return {"pending": pending, "margin": None if pending else abs(ap - bp), "sides": sides}

    games = [game("Al", 130, "Bo", 70), game("Cy", 99, "Di", 96)]
    tiles = _playoff_tiles(games)
    assert [t[0] for t in tiles] == ["Highest score", "Biggest blowout", "Closest game"]
    assert not any("decided" in t[0].lower() or "games" in t[0].lower() for t in tiles)
    # Each score tile is `{value, user_name, detail}` -- `detail` (the round
    # the record fell in) is None when no `game_round` map is passed.
    assert tiles[0] == ("Highest score",
                        {"value": "130.0", "user_name": "Al", "detail": None}, "gold")
    assert tiles[1][1] == {"value": "+60.0", "user_name": "Al", "detail": None}
    assert tiles[2][1] == {"value": "+3.0", "user_name": "Cy", "detail": None}

    # game_round names the round on the score tiles.
    gr = {id(games[0]): "Final", id(games[1]): "Round 1"}
    trd = _playoff_tiles(games, game_round=gr)
    assert trd[0][1]["detail"] == "Final" and trd[1][1]["detail"] == "Final"
    assert trd[2][1]["detail"] == "Round 1"

    # Champion leads and carries gold; the score tiles keep no accent then.
    champ = ("Champion", {"value": "\U0001F3C6", "user_name": "Al"}, "gold")
    tiles4 = _playoff_tiles(games, champ)
    assert tiles4[0] == champ
    assert [t[0] for t in tiles4] == ["Champion", "Highest score", "Biggest blowout", "Closest game"]
    assert tiles4[1][2] == ""          # "Highest score" no longer gold


def test_overview_insight_rows_are_ordered_standout_tiles(season_obj):
    """The regular-season takeaways come back as `.stat`-shaped standout
    tiles, ordered most important first. Every opposed metric (the table
    itself included) is ONE merged tile (label / rows) whose `rows` stack a
    good and a bad mini row; a flat single tile (label / value / holder /
    detail / tone) is still a valid shape. No wide table, no run-on markdown.
    The CHAMPION is NOT here (it belongs to the season-complete lead tiles).
    See app._overview_insight_rows."""
    from webapp.app import _overview_insight_rows

    tiles = _overview_insight_rows(season_obj)
    assert tiles, "expected at least the standings-derived tiles"
    for t in tiles:
        if "rows" in t:
            assert set(t) == {"label", "rows"}
            assert 1 <= len(t["rows"]) <= 2
            for r in t["rows"]:
                assert set(r) == {"tone", "holder", "value", "detail"}
                assert r["holder"] and isinstance(r["holder"], str)
                assert r["value"] and "**" not in r["detail"]     # no markdown bolding
                assert r["tone"] in ("good", "bad")
        else:
            assert set(t) == {"label", "value", "holder", "detail", "tone"}
            assert t["holder"] and isinstance(t["holder"], str)
            assert t["value"] and "**" not in t["detail"]
            assert t["tone"] in ("", "good", "bad")

    labels = [t["label"] for t in tiles]
    # The table leads, coaching comes before luck, opposed metrics are merged.
    assert labels[0] == "The table"
    assert "Champion" not in labels                        # belongs to the lead tiles
    assert labels.index("Coaching") < labels.index("Luck")
    # Dropped by request.
    for gone in ("Weekly high-score crowns", "Biggest mover", "Top of the table",
                 "Most left on the bench", "Luckiest", "Unluckiest"):
        assert gone not in labels
    # The table + Luck tiles each carry both a good and a bad mini row.
    for lbl in ("The table", "Luck"):
        t = next(x for x in tiles if x["label"] == lbl)
        assert {r["tone"] for r in t["rows"]} == {"good", "bad"}

    # Empty / degenerate season -> no tiles (template skips the section).
    empty = make_season()
    empty.standings = empty.standings.iloc[0:0]
    assert _overview_insight_rows(empty) == []


def test_member_seasons_are_newest_first_per_persistent_user_id():
    """The Current members table's Seasons column lists every season an account
    (keyed on the persistent user_id) has been in the league, current ->
    earliest. See app._member_seasons / _members_with_seasons."""
    from webapp.app import _member_seasons, _members_with_seasons

    def acc(pairs):
        return pd.DataFrame(
            [{"roster_id": i + 1, "user_id": uid, "user_name": nm,
              "team_name": None, "team": nm, "avatar_url": None, "team_avatar_url": None}
             for i, (uid, nm) in enumerate(pairs)])

    s22 = make_season("2022"); s22.accounts = acc([("u1", "Al"), ("u2", "Bo")])
    s23 = make_season("2023"); s23.accounts = acc([("u1", "Al"), ("u3", "Cy")])
    s25 = make_season("2025"); s25.accounts = acc([("u1", "Alan"), ("u3", "Cy"), ("u4", "Di")])
    # league_chain order: oldest first.
    chain = {"2022": s22, "2023": s23, "2025": s25}

    by_uid = _member_seasons(chain)
    assert by_uid["u1"] == ["2025", "2023", "2022"]     # newest first, all three
    assert by_uid["u3"] == ["2025", "2023"]
    assert by_uid["u4"] == ["2025"]
    assert "u2" in by_uid and by_uid["u2"] == ["2022"]

    # Attached to the current season's rows, keyed on user_id (name changed
    # u1 Al -> Alan across seasons; still one identity).
    rows = _members_with_seasons(s25, chain)
    got = {r["user_name"]: r["member_seasons"] for r in rows}
    assert got["Alan"] == ["2025", "2023", "2022"]
    assert got["Di"] == ["2025"]

    # No chain -> empty lists, not a crash.
    assert all(r["member_seasons"] == [] for r in _members_with_seasons(s25, None))


def test_weekly_preseason_slot_is_week_zero_and_only_when_allowed(season_obj):
    """The Weekly tab's synthetic "Pre-season" slot is week 0: it's in the
    `weeks` list and returns null KPI tiles only when `allow_zero` is set
    (which the tab passes only for a season that has a draft board). Without
    it, week 0 is not offered and a `week=0` param clamps up to week 1.
    See app._resolve_week / app._week_context."""
    from webapp.app import _resolve_week, _week_context

    s = season_obj                                   # last_week == 2 in the fixture

    # allow_zero off (the default): no week 0 anywhere.
    assert _resolve_week(s, "0") == 1                 # clamps up to the floor
    assert _resolve_week(s, None) == s.last_week
    assert _week_context(s)["weeks"] == [1, 2]

    # allow_zero on: week 0 is a real, selectable slot.
    assert _resolve_week(s, "0", allow_zero=True) == 0
    assert _resolve_week(s, "-3", allow_zero=True) == 0
    assert _resolve_week(s, None, allow_zero=True) == s.last_week   # default unchanged
    ctx = _week_context(s, "0", allow_zero=True)
    assert ctx["weeks"] == [0, 1, 2]
    assert ctx["week"] == 0 and ctx["is_current"] is False
    assert ctx["kpi_top"] is ctx["kpi_blow"] is ctx["kpi_close"] is ctx["kpi_bench"] is None

    # A normal week still resolves and carries real tiles under allow_zero.
    ctx1 = _week_context(s, "1", allow_zero=True)
    assert ctx1["week"] == 1 and ctx1["weeks"] == [0, 1, 2]
    assert ctx1["kpi_top"] is not None


def test_preseason_rosters_are_in_pick_order_with_per_position_counts(season_obj, monkeypatch):
    """The Weekly Week-0 view is one entry per member, ordered by DRAFT SLOT
    (manager pick order), each carrying a per-position drafted count and the
    picks in draft order (pick / pos / player / team / adp). No ranks, no
    season points -- it's pre-season. See app._preseason_rosters."""
    import pandas as pd
    from webapp import app
    from webapp.app import _preseason_rosters

    # Stub the two network-backed lookups the helper does for team / adp.
    monkeypatch.setattr(app.sm, "players", lambda *a, **k: pd.DataFrame(
        {"player_id": ["p1", "p2"], "team": ["PHI", "kc"]}))
    monkeypatch.setattr(app.draft, "_adp_field_for", lambda s: "adp_ppr")
    monkeypatch.setattr(app.draft, "_fetch_adp_raw", lambda season: {
        "p1": {"adp_ppr": 3.4}, "p3": {"adp_ppr": 999.0}})

    s = season_obj
    # Empty board -> no rows, not a crash.
    assert _preseason_rosters(s, pd.DataFrame()) == []

    # A 2-round, 3-team snake. Cy has slot 1, Al slot 2, Bo slot 3 -- the
    # output must be in that slot order regardless of standings.
    board = pd.DataFrame({
        "pick_no":       [1, 2, 3, 4, 5, 6],
        "round":         [1, 1, 1, 2, 2, 2],
        "pick_in_round": [1, 2, 3, 1, 2, 3],
        "draft_slot":    [1, 2, 3, 3, 2, 1],
        "user_name":     ["Cy", "Al", "Bo", "Bo", "Al", "Cy"],
        "player_id":     ["p1", "p2", "p3", "p4", "p5", "p6"],
        "player_name":   ["C one", "A one", "B one", "B two", "A two", "C two"],
        "position":      ["rb", "wr", "qb", "te", "rb", "dst"],   # "dst" -> OTHER
    })
    out = _preseason_rosters(s, board)
    assert [e["user_name"] for e in out] == ["Cy", "Al", "Bo"]     # slot order
    assert [e["slot"] for e in out] == [1, 2, 3]

    cy = out[0]
    assert cy["pos_counts"] == {"QB": 0, "RB": 1, "WR": 0, "TE": 0,
                                "K": 0, "DEF": 0, "OTHER": 1}       # rb + dst
    assert [p["pick"] for p in cy["picks"]] == ["1.01", "2.03"]
    assert cy["picks"][0] == {
        "pick": "1.01", "player_name": "C one", "player_id": "p1",
        "position": "RB", "team": "PHI", "adp": 3.4}
    # p6 has no team / adp entry -> both None; p3's 999 sentinel is dropped.
    assert cy["picks"][1]["team"] is None and cy["picks"][1]["adp"] is None
    # No leftover rank / points fields on a pick.
    assert "pos_rank" not in cy["picks"][0] and "total" not in cy["picks"][0]

    al = out[1]
    assert al["pos_counts"]["WR"] == 1 and al["pos_counts"]["RB"] == 1
    assert "OTHER" not in al["pos_counts"]                          # only added when used
    assert al["picks"][0]["team"] == "KC"                          # upper-cased


def test_bracket_token_is_stable_and_content_addressed():
    """The webapp keys an ad-hoc bracket by a hash of its config, so identical
    brackets share a token and an unknown token resolves to nothing."""
    from webapp.app import _bracket_from_token, _bracket_token
    cfg = {"season": "2026", "rounds": [{"id": "R1", "weeks": [15], "matchups": []}]}
    assert _bracket_token(cfg) == _bracket_token(dict(cfg))          # order-independent
    assert _bracket_token(cfg) != _bracket_token({**cfg, "season": "2025"})
    assert _bracket_from_token("deadbeef") is None                  # unknown token


def test_starter_slots():
    rp = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"]
    s = starter_slots(rp)
    assert s["QB"] == 1 and s["RB"] == 2 and s["FLEX"] == 1
    assert "BN" not in s


def test_optimal_points_with_flex():
    df = pd.DataFrame({
        "player_id": [str(i) for i in range(1, 9)],
        "position": ["QB", "RB", "RB", "RB", "WR", "WR", "TE", "K"],
        "points":   [20, 15, 12, 30, 10, 8, 5, 7],
    })
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "FLEX": 1}
    # QB20 + RB(30,15) + WR(10,8) + TE5 + K7 + FLEX(best leftover = RB12) = 107
    assert optimal_points(df, slots) == 107


def test_luck_and_efficiency(season_obj):
    lk = metrics.luck(season_obj)
    assert set(["user_name", "wins", "exp_w", "luck"]).issubset(lk.columns)
    eff = metrics.efficiency(season_obj)
    cy = eff.loc[eff["user_name"] == "Cy", "eff"].iloc[0]
    assert cy == round(200 / 240 * 100, 1)


def test_allplay(season_obj):
    d = metrics.allplay(season_obj)
    assert set(["user_name", "allplay_pct", "allplay_rank", "rank_delta"]).issubset(d.columns)
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["allplay_pct"] == 1.0 and al["allplay_rank"] == 1
    # rank_delta is the gap between all-play rank and actual finish.
    assert (d["rank_delta"] == d["allplay_rank"] - d["final_position"]).all()


def test_power_rank(season_obj):
    d = metrics.power_rank(season_obj)
    assert list(d.columns) == ["user_name", "points", "allplay_pct", "form",
                               "eff", "power", "power_rank"]
    assert d.loc[d["power_rank"] == 1, "user_name"].iloc[0] == "Al"   # best team
    assert abs(d["power"].sum()) < 1e-9                               # z-scores centre at 0


def test_manager_profile(season_obj):
    d = metrics.manager_profile(season_obj)
    # No transactions in the fixture -> all move counts zero, lineup IQ from lineup.
    assert (d[["moves", "trades", "drops"]].sum().sum()) == 0
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["lineup_iq"] == pytest.approx((100 / 110 + 130 / 140) / 2 * 100)


def test_season_report_is_self_contained_html(tmp_path, season_obj):
    from sleepermetrics import season_report
    out = tmp_path / "report.html"
    season_report(season_obj, str(out))
    doc = out.read_text(encoding="utf-8")
    assert doc.lower().startswith("<!doctype html>")
    assert "Test League" in doc
    assert "class='tile'" in doc                      # KPI tiles rendered
    assert doc.count("<td class='rank'>") == 3        # one row per team
    assert "data:image/png" in doc                    # >=1 chart embedded inline
    # Self-contained: no external assets to fetch (charts are data URIs).
    assert 'src="http' not in doc and "<script" not in doc


def test_season_report_scopes_to_one_manager(tmp_path, season_obj):
    from sleepermetrics import season_report
    out = tmp_path / "mgr.html"
    season_report(season_obj, str(out), seasons={"2025": season_obj}, manager="Al")
    doc = out.read_text(encoding="utf-8")
    assert "Manager Report" in doc              # header reframed for the manager
    assert "class='me'" in doc                  # the manager's row is highlighted
    assert "wins vs merit" in doc               # manager-scoped narrative
    # An unknown manager falls back to the whole-league report, not an error.
    out2 = tmp_path / "unknown.html"
    season_report(season_obj, str(out2), manager="Nobody")
    assert "Manager Report" not in out2.read_text(encoding="utf-8")


def test_week_stats(season_obj):
    d = metrics.week_stats(season_obj, 2)
    assert len(d) == 3
    assert (d["week"] == 2).all()
    assert d.iloc[0]["user_name"] == "Al"  # top scorer week 2


def test_table_position(season_obj):
    d = metrics.table_position(season_obj)
    assert len(d) == 6  # 3 teams x 2 weeks
    wk2 = d[d["week"] == 2]
    assert wk2.loc[wk2["table_position"] == 1, "user_name"].iloc[0] == "Al"  # 2-0
    assert wk2.loc[wk2["table_position"] == 3, "user_name"].iloc[0] == "Bo"  # 0-2
    assert list(wk2["table_position"]) == [1, 2, 3]


def test_season_metrics_and_charts_adapt_to_a_mid_season_week_cap(season_obj):
    """A mid-season run has its frames capped at the current week, so every
    season-so-far metric/chart must reflect only the scored weeks -- nothing may
    assume a full 14/17-week slate. Truncating the fixture to week 1 must leave
    strictly week-1 data, and the frame-derived charts must still render."""
    import dataclasses

    import matplotlib.pyplot as plt
    mid = dataclasses.replace(
        season_obj, last_week=1,
        team_wk=season_obj.team_wk[season_obj.team_wk["week"] == 1].copy(),
        lineup=season_obj.lineup[season_obj.lineup["week"] == 1].copy(),
    )
    assert mid.current_week == 1
    tp = metrics.table_position(mid)
    assert (tp["week"] == 1).all() and len(tp) == 3   # 3 teams, week 1 only
    # No minimum-week assumption: charts built from team_wk render on one week.
    for fn in (plots.plot_table_position, plots.plot_team_points):
        fig = fn(mid)
        assert fig is not None
        plt.close(fig)


def test_summary_week(season_obj):
    txt = summary_week(season_obj, 2)
    assert "Week 2 recap" in txt and "Top score" in txt


def test_summary_season(season_obj):
    txt = summaries.summary_season(season_obj)
    assert isinstance(txt, str) and "what the numbers say" in txt


def test_summary_career_ties():
    ss = {"2024": make_season("2024", champ_roster=1),
          "2025": make_season("2025", champ_roster=3)}  # two different champs -> tie
    txt = summaries.summary_career(ss)
    assert isinstance(txt, str) and "Most titles" in txt
    ct = metrics.career(ss)
    assert len(ct) == 3 and ct["titles"].max() == 1


def test_render_command_routes_and_renders(tmp_path, season_obj, monkeypatch):
    # text-only command (no fetch)
    content, path = _render_command("help", "x", out_dir=str(tmp_path))
    assert "Commands" in content and path is None
    # chart command: patch season() to avoid network
    import sleepermetrics.discord_bot as db
    monkeypatch.setattr(db, "season", lambda lid: season_obj)
    content, path = db._render_command("standings", "x", out_dir=str(tmp_path))
    assert path and os.path.exists(path)
    content, _ = db._render_command("weekly", "x", out_dir=str(tmp_path))
    assert "recap" in content


def test_plot_standings_renders(tmp_path, season_obj):
    p = plots.save(plots.plot_standings(season_obj), str(tmp_path / "s.png"))
    assert os.path.exists(p)


# --- per-account import: team names + icons ---------------------------------
def test_avatar_url_handles_both_sleeper_shapes():
    from sleepermetrics.season import avatar_url
    # An account avatar is a bare id and must be turned into a CDN url...
    assert avatar_url("abc") == "https://sleepercdn.com/avatars/abc"
    assert avatar_url("abc", thumb=True) == "https://sleepercdn.com/avatars/thumbs/abc"
    # ...but a custom TEAM avatar is already a url: don't double-prefix it.
    u = "https://sleepercdn.com/uploads/xyz.jpg"
    assert avatar_url(u) == u
    assert avatar_url(None) is None and avatar_url("") is None


def test_account_prefers_team_name_and_falls_back_to_display_name():
    from sleepermetrics.season import _account
    named = _account({"user_id": "1", "display_name": "Al",
                      "avatar": "a1", "metadata": {"team_name": "The Als"}})
    assert named["team"] == "The Als"
    assert named["avatar_url"].endswith("/avatars/a1")

    # No team name (and a blank one) -> show the manager's display name.
    for meta in ({}, {"team_name": "   "}):
        bare = _account({"user_id": "2", "display_name": "Bo", "metadata": meta})
        assert bare["team_name"] is None and bare["team"] == "Bo"
        assert bare["avatar_url"] is None


def test_league_accounts_keys_on_the_persistent_user_id():
    import pandas as pd
    from sleepermetrics.season import league_accounts

    def s(season, name, team, champ):
        o = type("S", (), {})()
        o.season = season
        o.accounts = pd.DataFrame([{
            "roster_id": 1, "user_id": "u1", "user_name": name,
            "team_name": team, "avatar_url": f"pic-{season}",
            "team_avatar_url": None, "team": team}])
        o.standings = pd.DataFrame({"user_name": [name],
                                    "champion": [champ]})
        return o

    # Same account, renamed between seasons: one row, not two.
    d = league_accounts({"2024": s("2024", "Old", "Old FC", True),
                         "2025": s("2025", "New", "New FC", False)})
    assert len(d) == 1
    row = d.iloc[0]
    assert row["user_name"] == "New"          # current identity wins
    assert row["avatar_url"] == "pic-2025"    # ...including the current picture
    assert row["seasons"] == 2 and row["titles"] == 1
    assert row["first_season"] == "2024" and row["last_season"] == "2025"


# --- player portraits -------------------------------------------------------
def test_headshot_url_uses_the_team_logo_for_a_team_defense():
    from sleepermetrics.headshots import headshot_url
    assert headshot_url("4034") == "https://sleepercdn.com/content/nfl/players/4034.jpg"
    # A team defense has no face -- its "player_id" IS its team.
    assert headshot_url("SF", "DEF") == "https://sleepercdn.com/images/team_logos/nfl/sf.png"
    assert headshot_url("NE") == "https://sleepercdn.com/images/team_logos/nfl/ne.png"


def test_portraits_are_off_and_degrade_to_none_when_disabled(monkeypatch):
    from sleepermetrics import headshots
    monkeypatch.setenv("SLEEPERMETRICS_NO_IMAGES", "1")
    assert headshots.disabled()
    # Charts must render offline: no image is a None, never an exception.
    assert headshots.headshot("4034") is None
    assert headshots.load("4034") is None


def test_a_player_with_no_photo_is_remembered_as_a_miss(monkeypatch):
    """Sleeper answers 403 + text/html (not 404) for a player with no photo, so
    status alone is not enough -- and 20 dead players must not mean 20 retries."""
    from sleepermetrics import headshots
    monkeypatch.delenv("SLEEPERMETRICS_NO_IMAGES", raising=False)
    headshots.clear_cache()
    calls = []

    class Resp:
        status_code = 403
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html>nope</html>"

    def fake_get(url, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr("requests.get", fake_get)
    assert headshots.headshot("99999999") is None
    assert headshots.headshot("99999999") is None      # asked twice...
    assert len(calls) == 1                             # ...fetched once
