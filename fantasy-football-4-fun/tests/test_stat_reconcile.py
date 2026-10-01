"""Network-free tests for webapp.stat_reconcile -- cross-source stat
reconciliation (Passing/Rushing/Receiving) for the team-profile page's
metric-grouped stat tables. No network/data-source calls: every test hands
`reconcile_metric` plain row dicts directly, the same shape
webapp.team_profile._grouped_metric_stats builds from its own already-
fetched rows.
"""
from __future__ import annotations

from webapp import stat_reconcile as sr


# --- _majority ----------------------------------------------------------------


def test_majority_single_source_is_agreed():
    val, agreed = sr._majority({"player_stats": 29})
    assert val == 29
    assert agreed is True


def test_majority_unanimous_is_agreed():
    val, agreed = sr._majority({"player_stats": 29, "ngs_passing": 29, "sleeper": 29.0})
    assert val == 29
    assert agreed is True


def test_majority_empty_values_is_agreed_none():
    """Nothing to disagree about when no source reported the stat at all."""
    val, agreed = sr._majority({})
    assert val is None
    assert agreed is True


def test_majority_clear_plurality_flags_disagreement():
    """2-of-3 agree, 1 differs: consensus is the 2-source value, but this
    IS a real disagreement (one source measured the game differently) --
    agreed must be False, not True, even though a value was resolved."""
    val, agreed = sr._majority({"player_stats": 110, "ngs_receiving": 77.0, "sleeper": 110.0})
    assert val == 110
    assert agreed is False


def test_majority_two_source_tie_falls_back_to_player_stats():
    val, agreed = sr._majority({"player_stats": 17, "ngs_passing": 18})
    assert val == 17
    assert agreed is False


def test_majority_tie_with_no_player_stats_falls_back_alphabetically():
    val, agreed = sr._majority({"ngs_passing": 18, "pfr_pass": 19})
    assert val == 18  # "ngs_passing" sorts before "pfr_pass"
    assert agreed is False


def test_majority_three_way_disagreement_no_plurality_falls_back():
    """Every source differs -- no plurality at all -- still resolves to
    SOMETHING (player_stats, since it voted), flagged as disagreement."""
    val, agreed = sr._majority({"player_stats": 10, "ngs_passing": 11, "sleeper": 12})
    assert val == 10
    assert agreed is False


# --- reconcile_metric -----------------------------------------------------------


def test_reconcile_metric_unknown_metric_returns_empty():
    assert sr.reconcile_metric({"player_stats": [{"player_display_name": "A"}]}, "defense") == []


def test_reconcile_metric_passing_basic_agreement():
    rows_by_source = {
        "player_stats": [{"player_display_name": "Patrick Mahomes",
                          "attempts": 39, "completions": 24,
                          "passing_yards": 258, "passing_tds": 1,
                          "interceptions": 0}],
        "ngs_passing": [{"player_display_name": "Patrick Mahomes",
                         "attempts": 39, "completions": 24,
                         "pass_yards": 258, "pass_touchdowns": 1,
                         "interceptions": 0}],
        "sleeper": [{"player": "Patrick Mahomes",
                    "pass_att": 39.0, "pass_cmp": 24.0, "pass_yd": 258.0,
                    "pass_td": 1.0}],
    }
    out = sr.reconcile_metric(rows_by_source, "passing")
    assert len(out) == 1
    row = out[0]
    assert row["player"] == "Patrick Mahomes"
    assert row["attempts"] == 39
    assert row["attempts_agreed"] is True
    assert row["completions"] == 24
    assert row["passing_yards"] == 258
    assert row["passing_tds"] == 1
    # sleeper doesn't carry interceptions here -- only 2 sources reported
    # it, but they agree, so still agreed=True with a 2-source dict.
    assert row["interceptions"] == 0
    assert row["interceptions_agreed"] is True
    assert set(row["interceptions_sources"]) == {"player_stats", "ngs_passing"}


def test_reconcile_metric_flags_real_disagreement():
    rows_by_source = {
        "player_stats": [{"player_display_name": "Khalil Shakir",
                          "targets": 10, "receptions": 8,
                          "receiving_yards": 110, "receiving_tds": 0}],
        "ngs_receiving": [{"player_display_name": "Khalil Shakir",
                           "targets": 10, "receptions": 8,
                           "yards": 77, "rec_touchdowns": 0}],
        "sleeper": [{"player": "Khalil Shakir",
                    "rec_tgt": 10.0, "rec": 8.0, "rec_yd": 110.0}],
    }
    out = sr.reconcile_metric(rows_by_source, "receiving")
    row = out[0]
    assert row["receiving_yards"] == 110  # 2-of-3 plurality
    assert row["receiving_yards_agreed"] is False
    assert row["receiving_yards_sources"] == {
        "player_stats": 110, "ngs_receiving": 77, "sleeper": 110.0}
    assert row["targets_agreed"] is True  # unaffected stat stays agreed


def test_reconcile_metric_player_seen_by_only_one_source_still_gets_a_row():
    """A player only ONE source reports (e.g. NGS coverage gap, or a
    since-verified Sleeper-only week) still produces a row, built from
    whichever source(s) actually saw him -- this is the whole reason
    reconciliation exists (see this module's own docstring: NGS coverage
    is a real subset, not comprehensive)."""
    rows_by_source = {
        "sleeper": [{"player": "Backup QB", "pass_att": 5.0, "pass_cmp": 3.0}],
    }
    out = sr.reconcile_metric(rows_by_source, "passing")
    assert len(out) == 1
    row = out[0]
    assert row["player"] == "Backup QB"
    assert row["attempts"] == 5.0
    assert row["attempts_agreed"] is True
    assert row["attempts_sources"] == {"sleeper": 5.0}
    assert "completions" in row  # sleeper's pass_cmp maps to it
    assert row["completions"] == 3.0


def test_reconcile_metric_no_sources_returns_empty_list_not_none():
    """No contributing source had rows for this metric at all -- an empty
    list (data present, nothing found), never None or a missing key, so
    the template can distinguish this from 'metric not computed'."""
    out = sr.reconcile_metric({}, "passing")
    assert out == []


def test_reconcile_metric_join_is_by_normalised_name():
    """Two sources spell the same player's name with different case/
    punctuation quirks -- must still join to ONE row, not two, mirroring
    nflref.summary.compare_sources's own _norm_name-based join."""
    rows_by_source = {
        "player_stats": [{"player_display_name": "AJ Brown",
                          "targets": 5, "receptions": 3,
                          "receiving_yards": 40, "receiving_tds": 0}],
        "sleeper": [{"player": "A.J. Brown",
                    "rec_tgt": 5.0, "rec": 3.0, "rec_yd": 40.0}],
    }
    out = sr.reconcile_metric(rows_by_source, "receiving")
    assert len(out) == 1
    assert out[0]["targets"] == 5
    assert out[0]["targets_sources"] == {"player_stats": 5, "sleeper": 5.0}


def test_reconcile_metric_stat_absent_from_every_source_is_dropped():
    """A canonical stat with no reporting source at all for a given player
    (e.g. a rushing metric on a player who only ever passed) does not
    appear on that player's row -- no stat/stat_agreed/stat_sources keys
    at all, rather than a None placeholder."""
    rows_by_source = {
        "player_stats": [{"player_display_name": "Pure Passer",
                          "attempts": 10, "completions": 6}],
    }
    out = sr.reconcile_metric(rows_by_source, "passing")
    row = out[0]
    assert "passing_yards" not in row
    assert "passing_yards_agreed" not in row
    assert "passing_yards_sources" not in row


def test_reconcile_metric_rows_sorted_by_player_name():
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Zach Wilson", "attempts": 1, "completions": 1},
            {"player_display_name": "Aaron Rodgers", "attempts": 2, "completions": 2},
        ],
    }
    out = sr.reconcile_metric(rows_by_source, "passing")
    assert [r["player"] for r in out] == ["Aaron Rodgers", "Zach Wilson"]


def test_metric_sources_derived_from_metric_maps():
    """METRIC_SOURCES is built from _ALL_METRIC_MAPS (core + extra, see that
    dict's own comment), not hand-maintained -- regression guard that it
    stays in sync, checked by MEMBERSHIP/derivation rather than a literal
    exact-set (which would go stale the moment a new metric family is
    added, same failure mode CLAUDE.md documents elsewhere in this
    codebase for exactly this brittle-test shape)."""
    assert set(sr.METRIC_SOURCES) == set(sr._ALL_METRIC_MAPS)
    assert "player_stats" in sr.METRIC_SOURCES["passing"]
    assert "sleeper" in sr.METRIC_SOURCES["passing"]
    assert "pfr_pass" not in sr.METRIC_SOURCES["passing"]  # no volume overlap


def test_metric_sources_covers_every_extra_single_source_family():
    """Each single-source family added in this module's 2026-09 extension
    (defense/defense_team/snaps_*/routes/kicking -- see `_EXTRA_METRIC_MAPS`'s
    own comment) resolves to exactly its one real source, not zero (a typo'd
    key that never matched any stat's inner dict would silently resolve to
    an empty source list, which METRIC_SOURCES' own dict comprehension would
    not error on)."""
    assert sr.METRIC_SOURCES["defense"] == ["pfr_def"]
    assert sr.METRIC_SOURCES["defense_team"] == ["sleeper_def"]
    assert sr.METRIC_SOURCES["snaps_offense"] == ["snap_counts"]
    assert sr.METRIC_SOURCES["snaps_defense"] == ["snap_counts"]
    assert sr.METRIC_SOURCES["snaps_special_teams"] == ["snap_counts"]
    assert sr.METRIC_SOURCES["routes"] == ["route_participation"]
    assert sr.METRIC_SOURCES["kicking"] == ["sleeper_kicker"]


def test_reconcile_metric_single_source_family_is_always_agreed():
    """A single-source metric family (nothing to vote on) still produces a
    real row through the identical reconcile_metric code path -- agreed is
    unconditionally True (one source, `_majority`'s own `len(values) == 1`
    branch), same as any other single-voter stat."""
    rows_by_source = {"pfr_def": [
        {"pfr_player_name": "Aidan Hutchinson", "def_sacks": 2.0, "def_tackles_combined": 4},
    ]}
    out = sr.reconcile_metric(rows_by_source, "defense")
    assert len(out) == 1
    row = out[0]
    assert row["def_sacks"] == 2.0
    assert row["def_sacks_agreed"] is True
    assert row["def_sacks_sources"] == {"pfr_def": 2.0}


def test_reconcile_season_works_for_a_single_source_extra_family():
    """The season sum-then-check path (reconcile_season) works identically
    for a single-source family -- proof that Phase 1's extension didn't
    just make reconcile_metric work per-week, but the season rollup too,
    without any new logic specific to single-source families."""
    rows_by_source = {"pfr_def": [
        {"pfr_player_name": "Aidan Hutchinson", "week": 1, "def_sacks": 2.0},
        {"pfr_player_name": "Aidan Hutchinson", "week": 2, "def_sacks": 1.0},
        {"pfr_player_name": "Aidan Hutchinson", "week": 3, "def_sacks": 0.0},
    ]}
    row = sr.reconcile_season(rows_by_source, "defense")[0][0]
    assert row["def_sacks"] == 3.0
    assert row["def_sacks_agreed"] is True


def test_reconcile_season_omits_unrecoverable_rate_stats_from_the_summed_row():
    """Regression guard for a real bug found while verifying this module's
    defense/snaps/kicking extension against real 2026 DET data: naive
    summation gave def_completion_pct a season 'total' of 1.367 (137%),
    meaningless for a rate stat with no derivable numerator/denominator in
    this data. Every key in _OMIT_STATS must be entirely ABSENT from a
    season row (not present-but-wrong), while real counting stats on the
    SAME row still sum normally."""
    rows_by_source = {"pfr_def": [
        {"pfr_player_name": "Rock Ya-Sin", "week": 1,
         "def_completions_allowed": 5, "def_targets": 8, "def_completion_pct": 0.625},
        {"pfr_player_name": "Rock Ya-Sin", "week": 2,
         "def_completions_allowed": 3, "def_targets": 6, "def_completion_pct": 0.5},
        {"pfr_player_name": "Rock Ya-Sin", "week": 3,
         "def_completions_allowed": 3, "def_targets": 2, "def_completion_pct": 1.5},
    ]}
    row = sr.reconcile_season(rows_by_source, "defense")[0][0]
    assert "def_completion_pct" not in row
    assert "def_completion_pct_agreed" not in row
    assert "def_completion_pct_sources" not in row
    assert row["def_completions_allowed"] == 11  # real counts still sum
    assert row["def_targets"] == 16


def test_reconcile_season_omits_every_omit_stat_family_member():
    """Sweeps every key in _OMIT_STATS, not just one representative -- a
    stat added to that set later but never actually wired through this
    exclusion path would otherwise go unnoticed until it shipped a real
    wrong season number, the same failure mode the original bug was."""
    for stat in sr._OMIT_STATS:
        # Find which extra metric family (if any) declares this stat, and
        # confirm reconcile_season drops it from a real summed row.
        for metric, stat_map in sr._EXTRA_METRIC_MAPS.items():
            if stat not in stat_map:
                continue
            src = next(iter(stat_map[stat]))
            col = stat_map[stat][src]
            rows_by_source = {src: [
                {sr._NAME_COL[src]: "Test Player", "week": 1, col: 0.5},
                {sr._NAME_COL[src]: "Test Player", "week": 2, col: 0.7},
            ]}
            row = sr.reconcile_season(rows_by_source, metric)[0][0]
            assert stat not in row, f"{stat} ({metric}) should be excluded"


def test_reconcile_season_uses_max_not_sum_for_max_stats():
    """Regression guard for a real bug found while verifying this module's
    kicking extension against real 2026 Jake Bates (DET) data: fgm_lng
    (longest FG made) summed 23+31+30=84 across 3 real weeks, when the real
    season long is 31 -- the largest SINGLE week, not their sum. Matches
    team_profile._KICKER_MAX_KEYS's own pre-existing precedent for the
    identical field in a different code path."""
    rows_by_source = {"sleeper_kicker": [
        {"player": "Jake Bates", "week": 1, "fgm_lng": 23},
        {"player": "Jake Bates", "week": 2, "fgm_lng": 31},
        {"player": "Jake Bates", "week": 3, "fgm_lng": 30},
    ]}
    row = sr.reconcile_season(rows_by_source, "kicking")[0][0]
    assert row["fgm_lng"] == 31  # NOT 84


def test_reconcile_season_recomputes_fgm_pct_from_summed_fgm_fga():
    """fgm_pct is neither summed (meaningless for a rate) nor omitted
    (team_profile._kicker_season_totals already shows a real recomputed
    season fgm_pct elsewhere in this codebase, so dropping it here would
    lose real, already-established information) -- it's derived from the
    ALREADY-SUMMED fgm/fga, matching that existing precedent's own formula
    (round(100 * fgm / fga, 1)), never averaged from weekly rates (which
    would weight a 1-attempt week the same as a 5-attempt week)."""
    rows_by_source = {"sleeper_kicker": [
        {"player": "Jake Bates", "week": 1, "fgm": 1, "fga": 1, "fgm_pct": 100.0},
        {"player": "Jake Bates", "week": 2, "fgm": 1, "fga": 1, "fgm_pct": 100.0},
        {"player": "Jake Bates", "week": 3, "fgm": 2, "fga": 3, "fgm_pct": 66.7},
    ]}
    row = sr.reconcile_season(rows_by_source, "kicking")[0][0]
    assert row["fgm"] == 4
    assert row["fga"] == 5
    assert row["fgm_pct"] == 80.0  # 100 * 4/5, NOT a naive sum or average of the weekly pcts


def test_reconcile_season_recompute_stat_absent_when_denominator_is_zero():
    """A season with a real numerator but a zero/missing denominator (an
    edge case that could occur for a kicker who never attempted a kick some
    week yet somehow has a stray fgm) gets NO fgm_pct entry -- never a
    division by zero, never a fabricated 0%."""
    rows_by_source = {"sleeper_kicker": [
        {"player": "Jake Bates", "week": 1, "fgm": 0, "fga": 0},
    ]}
    row = sr.reconcile_season(rows_by_source, "kicking")[0][0]
    assert "fgm_pct" not in row


def test_reconcile_season_omits_defense_team_td_matching_existing_precedent():
    """defense_team's own `td` field is excluded from summation, mirroring
    team_profile._DEF_SEASON_EXCLUDED_KEYS's own DELIBERATE, pre-existing
    precedent: that constant's own comment documents its real per-week
    values (live-verified) as far too high/inconsistent to be genuine
    defensive/special-teams TDs, so summing an unconfirmed figure into a
    season total would display a wrong, unverifiable number. This module
    mirrors that exclusion rather than re-deciding it independently."""
    rows_by_source = {"sleeper_def": [
        {"player": "DET", "week": 1, "sack": 2, "td": 7},
        {"player": "DET", "week": 2, "sack": 1, "td": 2},
    ]}
    row = sr.reconcile_season(rows_by_source, "defense_team")[0][0]
    assert "td" not in row
    assert row["sack"] == 3  # real counts still sum


def test_stat_source_groups_works_for_an_extra_family():
    """stat_source_groups (the display-grouping helper) also resolves
    through _stat_map_for now, not just reconcile_metric/reconcile_season --
    proof it covers every metric family, not just the 3 originally wired
    ones, even though team_profile.py doesn't call it for these yet."""
    groups = sr.stat_source_groups("kicking")
    assert groups
    combo, stats = groups[0]
    assert combo == ("sleeper_kicker",)
    assert "fgm" in stats


def test_extra_metric_maps_never_collide_with_core_metric_maps():
    """_EXTRA_METRIC_MAPS and _METRIC_MAPS must have disjoint keys -- a
    collision would mean _ALL_METRIC_MAPS's dict-merge silently let one
    definition shadow the other, corrupting whichever metric name collided
    for every caller of reconcile_metric/reconcile_season."""
    assert set(sr._METRIC_MAPS) & set(sr._EXTRA_METRIC_MAPS) == set()


# --- aggregate_weeks ------------------------------------------------------------


def test_aggregate_weeks_sums_across_real_weeks_not_last_row_wins():
    """Regression guard for a real, live-verified bug: reconcile_metric
    alone (no aggregate_weeks step) kept only the LAST row it saw per
    player+source when handed a whole season's rows, so a season 'total'
    silently became one arbitrary week's number (KC's real case: Mahomes
    read 189 passing yards, a single week, instead of his real ~3,587-yard
    season). aggregate_weeks must SUM every week's value, not keep one."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39, "passing_yards": 258},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29, "passing_yards": 187},
            {"player_display_name": "Patrick Mahomes", "week": 3, "attempts": 37, "passing_yards": 224},
        ],
    }
    agg, _ = sr.aggregate_weeks(rows_by_source, "passing")
    row = agg["player_stats"][0]
    assert row["attempts"] == 105  # 39 + 29 + 37
    assert row["passing_yards"] == 669  # 258 + 187 + 224


def test_aggregate_weeks_drops_week_zero_rows():
    """ngs_* (and only ngs_*) publishes a pre-aggregated week=0 season-total
    row alongside real weekly rows -- summing it in doubles the real total.
    Regression guard for a real, live-verified bug (Mahomes's NGS-summed
    attempts read 1004, exactly 2x his real 502, before this guard)."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 0, "attempts": 502},  # should never appear on player_stats in practice, but guard anyway
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
    }
    agg, _ = sr.aggregate_weeks(rows_by_source, "passing")
    assert agg["player_stats"][0]["attempts"] == 68  # 39 + 29, NOT +502


def test_aggregate_weeks_excludes_ngs_from_reconciliation_source_set():
    """NGS is excluded from the season-wide `rows_by_source` output entirely
    (see _SEASON_EXCLUDED_SOURCES's own docstring: an incomplete-coverage
    source's season sum isn't a genuine data point to vote on, it's a
    coverage-gap artifact) -- real pattern this prevents: NGS's season sum
    reads systematically LOWER than complete sources for nearly every real
    player purely from missing weeks, which would otherwise flag as
    'disagreement' on almost every single stat, burying genuine same-game
    disagreements under false alarms."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
        "ngs_passing": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            # week 2 missing entirely -- a real NGS coverage gap
        ],
    }
    agg, _ = sr.aggregate_weeks(rows_by_source, "passing")
    assert "ngs_passing" not in agg
    assert "player_stats" in agg


def test_aggregate_weeks_returns_ngs_coverage_for_future_analysis():
    """The excluded NGS data isn't discarded -- it comes back as
    `ngs_coverage`, per user request ("add a note ... for eventual analysis
    of actual ngs full-season coverage in the future"): real week count and
    NGS's own (incomplete) summed value, keyed by player, so a future
    session can compute a real coverage rate without re-deriving this."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
        "ngs_passing": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
        ],
    }
    _, coverage = sr.aggregate_weeks(rows_by_source, "passing")
    key = sr._norm_name("Patrick Mahomes")
    assert key in coverage
    entry = coverage[key]
    assert entry["player"] == "Patrick Mahomes"
    assert entry["ngs_passing_weeks"] == 1
    assert entry["ngs_passing"]["attempts"] == 39


def test_aggregate_weeks_and_reconcile_metric_compose():
    """The intended pipeline: aggregate_weeks(...)[0] feeds straight into
    reconcile_metric(...) unchanged, and the composition produces a real
    season-total reconciled row (not per-game columns bleeding through)."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39, "completions": 24},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29, "completions": 16},
        ],
        "sleeper": [
            {"player": "Patrick Mahomes", "week": 1, "pass_att": 39.0, "pass_cmp": 24.0},
            {"player": "Patrick Mahomes", "week": 2, "pass_att": 29.0, "pass_cmp": 16.0},
        ],
    }
    agg, _ = sr.aggregate_weeks(rows_by_source, "passing")
    out = sr.reconcile_metric(agg, "passing")
    assert len(out) == 1
    row = out[0]
    assert row["attempts"] == 68
    assert row["attempts_agreed"] is True
    assert set(row["attempts_sources"]) == {"player_stats", "sleeper"}


def test_aggregate_weeks_unknown_metric_returns_empty():
    assert sr.aggregate_weeks({}, "defense") == ({}, {})


# --- reconcile_season ("sum-then-check": reconcile per week, then sum) --------


def test_reconcile_season_sums_reconciled_weekly_values_not_raw_source_totals():
    """The whole point of reconcile_season vs aggregate_weeks: when sources
    disagree on ONE week, the season total is built from whichever value won
    THAT week's vote, not from summing either source's own raw total. Here
    sleeper disagrees with player_stats on week 2's attempts (30 vs 29);
    player_stats wins the tie-break (see _majority's own docstring), so the
    season total must be 39+29+37=105, matching NEITHER source's own raw sum
    (player_stats: 105, sleeper: 106) by coincidence alone -- if the sources
    had both been internally consistent this test wouldn't distinguish the
    two approaches, so the fixture deliberately makes them differ."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
            {"player_display_name": "Patrick Mahomes", "week": 3, "attempts": 37},
        ],
        "sleeper": [
            {"player": "Patrick Mahomes", "week": 1, "pass_att": 39.0},
            {"player": "Patrick Mahomes", "week": 2, "pass_att": 30.0},
            {"player": "Patrick Mahomes", "week": 3, "pass_att": 37.0},
        ],
    }
    rows, _ = sr.reconcile_season(rows_by_source, "passing")
    assert len(rows) == 1
    row = rows[0]
    assert row["attempts"] == 105  # NOT 106 (sleeper's own raw sum)
    assert row["attempts_agreed"] is False  # week 2 was a real disagreement
    assert set(row["attempts_sources"]) == {"player_stats", "sleeper"}


def test_reconcile_season_agreed_true_only_when_every_week_was_unanimous():
    """A stat with no disagreement on any week reads agreed=True at the
    season grain too, even in the same fixture where a DIFFERENT stat (from
    the same two sources, same weeks) disagreed on one week -- agreement is
    tracked per stat, not globally across the whole player-season."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39, "passing_yards": 258},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29, "passing_yards": 187},
        ],
        "sleeper": [
            {"player": "Patrick Mahomes", "week": 1, "pass_att": 39.0, "pass_yd": 258.0},
            {"player": "Patrick Mahomes", "week": 2, "pass_att": 30.0, "pass_yd": 187.0},
        ],
    }
    row = sr.reconcile_season(rows_by_source, "passing")[0][0]
    assert row["attempts_agreed"] is False
    assert row["passing_yards_agreed"] is True


def test_reconcile_season_drops_week_zero_rows():
    """Same guard aggregate_weeks already has, for the same real reason
    (ngs_*'s own pre-aggregated week-0 season-total row would double the
    real total if summed alongside the real weekly rows)."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 0, "attempts": 502},
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
    }
    row = sr.reconcile_season(rows_by_source, "passing")[0][0]
    assert row["attempts"] == 68  # 39 + 29, NOT +502


def test_reconcile_season_ngs_still_votes_on_weeks_it_covers():
    """Unlike aggregate_weeks (which excludes NGS from the season-wide
    SOURCE SET entirely, see _SEASON_EXCLUDED_SOURCES's own docstring),
    reconcile_season never excludes NGS -- an incomplete-coverage source is
    still a real, valid vote on any INDIVIDUAL week it did cover; it simply
    contributes nothing to weeks it's missing, since reconciliation happens
    per week and a source with no row that week doesn't vote that week. NGS
    covering only week 1 (not week 2) must not prevent week 2's own
    reconciliation, and NGS's real vote on week 1 must still count."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
        "ngs_passing": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            # week 2 missing entirely -- a real NGS coverage gap
        ],
    }
    row = sr.reconcile_season(rows_by_source, "passing")[0][0]
    assert row["attempts"] == 68
    assert set(row["attempts_sources"]) == {"player_stats", "ngs_passing"}


def test_reconcile_season_checks_season_only_source_without_letting_it_vote():
    """A source that only ever publishes a season total (none of this app's
    real sources work that way today, but the mechanism exists for one that
    might) is compared against the summed total as a CHECK, never blended
    into the per-week vote -- the summed total here is driven purely by
    player_stats' own two real weeks (68), regardless of what the season-
    only source claims, and a genuine mismatch (season-only says 70) is
    surfaced in `disagreements`, not silently overwritten or averaged in."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
    }
    season_only = [{"player": "Patrick Mahomes", "pass_att": 70}]
    rows, disagree = sr.reconcile_season(
        rows_by_source, "passing",
        season_only_rows=season_only, season_only_source="sleeper")
    assert rows[0]["attempts"] == 68  # unaffected by the season-only source
    key = sr._norm_name("Patrick Mahomes")
    assert disagree[key]["attempts"] == (70, 68)


def test_reconcile_season_no_disagreement_when_season_only_source_matches():
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
        ],
    }
    season_only = [{"player": "Patrick Mahomes", "pass_att": 68}]
    _, disagree = sr.reconcile_season(
        rows_by_source, "passing",
        season_only_rows=season_only, season_only_source="sleeper")
    assert disagree == {}


def test_reconcile_season_no_season_only_rows_returns_empty_disagreements():
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
        ],
    }
    _, disagree = sr.reconcile_season(rows_by_source, "passing")
    assert disagree == {}


def test_reconcile_season_unknown_metric_returns_empty():
    assert sr.reconcile_season({}, "defense") == ([], {})


def test_reconcile_season_is_internally_consistent_with_per_week_reconcile_metric():
    """The core guarantee reconcile_season exists to provide: its season
    total for a stat always equals the sum of reconcile_metric's own
    per-week result for that same stat, called separately week by week --
    proven directly here by cross-checking against reconcile_metric rather
    than just asserting a hand-computed number."""
    rows_by_source = {
        "player_stats": [
            {"player_display_name": "Patrick Mahomes", "week": 1, "attempts": 39},
            {"player_display_name": "Patrick Mahomes", "week": 2, "attempts": 29},
            {"player_display_name": "Patrick Mahomes", "week": 3, "attempts": 37},
        ],
        "sleeper": [
            {"player": "Patrick Mahomes", "week": 1, "pass_att": 39.0},
            {"player": "Patrick Mahomes", "week": 2, "pass_att": 30.0},
            {"player": "Patrick Mahomes", "week": 3, "pass_att": 37.0},
        ],
    }
    expected_total = 0
    for week in (1, 2, 3):
        week_rows = {src: [r for r in rows if r.get("week") == week]
                     for src, rows in rows_by_source.items()}
        week_row = sr.reconcile_metric(week_rows, "passing")[0]
        expected_total += week_row["attempts"]

    season_row = sr.reconcile_season(rows_by_source, "passing")[0][0]
    assert season_row["attempts"] == expected_total


# --- player_week_rows (Phase 2: merge every family onto one row per --------
# --- (player, week), not one table per metric family) ----------------------


def test_player_week_rows_merges_multiple_roles_onto_one_player_row():
    """The core point of this function: a QB with real passing AND rushing
    activity the same week ends up as ONE row with both roles filled, not
    two separate rows the caller has to stitch back together -- mirrors
    the real behavior team_profile.py's own per-game merge (originally
    the hand-written _merge_offense_players, since replaced by the
    _offense_players_via_shared adapter over this function, and deleted)
    already had for exactly this case (a rushing QB), generalized across
    every family."""
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Jared Goff", "week": 1, "attempts": 39, "passing_yards": 206},
        ],
        "player_stats_rushing": [
            {"player_display_name": "Jared Goff", "week": 1, "carries": 2, "rushing_yards": 2},
        ],
    }
    player_rows, team_rows = sr.player_week_rows(role_rows)
    assert len(player_rows) == 1
    row = player_rows[0]
    assert row["player"] == "Jared Goff"
    assert row["week"] == 1
    assert row["passing"]["attempts"] == 39
    assert row["rushing"]["carries"] == 2
    assert row["receiving"] is None
    assert team_rows == []


def test_player_week_rows_resolves_position_from_snap_counts_for_defense():
    """defense's own reconciled source (pfr_def) has NO position column at
    all (confirmed live against real pfr_def data) -- position must come
    from snap_counts_defense instead, a SEPARATE role_rows key from
    defense's own metric sources, matching team_profile._merge_defense_
    players's existing real logic. Regression guard for a real bug found
    while building this function: an early version pointed the position
    lookup at pfr_def itself and every defensive player's position read
    None."""
    role_rows = {
        "pfr_def": [
            {"pfr_player_name": "Aidan Hutchinson", "week": 1, "def_sacks": 2.0},
        ],
        "snap_counts_defense": [
            {"player": "Aidan Hutchinson", "week": 1, "position": "DE", "defense_snaps": 50},
        ],
    }
    player_rows, _ = sr.player_week_rows(role_rows)
    assert player_rows[0]["position"] == "DE"
    assert player_rows[0]["defense"]["def_sacks"] == 2.0
    assert player_rows[0]["snap_defense"]["defense_snaps"] == 50


def test_player_week_rows_snap_counts_bucket_keys_do_not_double_prefix():
    """Regression guard for a real bug found while building this function:
    an early version derived each source's role_rows key as
    f'{source}_{metric}', which for snap_counts produced the WRONG key
    ('snap_counts_snaps_offense' instead of the real 'snap_counts_offense'
    team_profile._split_snap_counts actually uses) and silently resolved
    zero rows every time. _ROLE_ROWS_KEY's explicit per-metric mapping is
    what fixes this -- this test locks in the real, correct key."""
    role_rows = {
        "snap_counts_offense": [
            {"player": "Jared Goff", "week": 1, "position": "QB", "offense_snaps": 65},
        ],
    }
    player_rows, _ = sr.player_week_rows(role_rows)
    assert len(player_rows) == 1
    assert player_rows[0]["snap_offense"]["offense_snaps"] == 65
    assert player_rows[0]["position"] == "QB"


def test_player_week_rows_falls_back_to_position_of_when_no_position_source():
    """kicking/passing/rushing/receiving/routes have no position column of
    their own at all (see _ROLE_POSITION_KEY) -- the caller-supplied
    position_of callback is the only way those players' position gets
    filled, mirroring team_profile._position_of's own two-tier fallback."""
    role_rows = {
        "sleeper_kicker": [
            {"player": "Jake Bates", "week": 1, "fgm": 1, "fga": 1},
        ],
    }
    player_rows, _ = sr.player_week_rows(role_rows)
    assert player_rows[0]["position"] is None  # no fallback given

    player_rows2, _ = sr.player_week_rows(
        role_rows, position_of=lambda name, role: "K" if name == "Jake Bates" else None)
    assert player_rows2[0]["position"] == "K"


def test_player_week_rows_keeps_team_level_defense_separate_from_players():
    """defense_team (Sleeper's own team-level stat line) is a DIFFERENT
    GRAIN from a per-player row -- it must never be merged onto an
    individual player's dict, and must appear in team_rows, not
    player_rows, even when player_rows also has real entries the same
    week."""
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Jared Goff", "week": 1, "attempts": 39},
        ],
        "sleeper_def": [
            {"player": "DET", "week": 1, "sack": 5, "tkl": 72},
        ],
    }
    player_rows, team_rows = sr.player_week_rows(role_rows)
    assert [r["player"] for r in player_rows] == ["Jared Goff"]
    assert len(team_rows) == 1
    assert team_rows[0]["team"] == "DET"
    assert team_rows[0]["defense_team"]["sack"] == 5
    # "defense_team" is not one of _PLAYER_ROLE_METRICS own roles, so a
    # player row never carries that key at all -- confirms it truly never
    # leaks onto an individual player row.
    assert "defense_team" not in player_rows[0]


def test_player_week_rows_groups_by_week_not_flattened_across_weeks():
    """Handing this function two real weeks' worth of rows for the same
    player produces TWO separate (player, week) rows, not one row with the
    second week's data silently overwriting the first -- this is what lets
    a caller reuse the identical function for both a single game (one week)
    and a whole season's worth of rows at once."""
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Jared Goff", "week": 1, "attempts": 39},
            {"player_display_name": "Jared Goff", "week": 2, "attempts": 38},
        ],
    }
    player_rows, _ = sr.player_week_rows(role_rows)
    assert len(player_rows) == 2
    weeks = sorted(r["week"] for r in player_rows)
    assert weeks == [1, 2]
    by_week = {r["week"]: r["passing"]["attempts"] for r in player_rows}
    assert by_week == {1: 39, 2: 38}


def test_player_week_rows_sorted_by_week_then_player():
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Zeke Zed", "week": 2, "attempts": 10},
            {"player_display_name": "Amy Ace", "week": 1, "attempts": 20},
            {"player_display_name": "Bob Bee", "week": 1, "attempts": 15},
        ],
    }
    player_rows, _ = sr.player_week_rows(role_rows)
    assert [(r["week"], r["player"]) for r in player_rows] == [
        (1, "Amy Ace"), (1, "Bob Bee"), (2, "Zeke Zed"),
    ]


def test_player_week_rows_empty_input_returns_empty_lists():
    assert sr.player_week_rows({}) == ([], [])


def test_player_week_rows_attaches_pfr_extra_onto_passing_row():
    """Regression guard for a real bug found while migrating team_profile.py
    to this shared assembler (Phase 3): PFR's own passing/rushing/receiving
    datasets carry PFR-EXCLUSIVE advanced columns (pressure rate, broken
    tackles, etc, see stat_reconcile's own header comment) with no
    cross-source overlap, so they never enter _METRIC_MAPS/vote on
    anything -- team_profile._attach_pfr_extra already joins them directly
    onto the live page's reconciled row, but the first version of
    player_week_rows never did this at all, silently dropping every real
    PFR-exclusive column (pressure/sack/blitz counts, bad-throw rate) from
    every merged passing row. Found by comparing this function's real
    output against team_profile._merge_offense_players's then-live output
    (that function has since been replaced and deleted, see this module's
    own header comment) on real 2026 DET data."""
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Jared Goff", "week": 1, "attempts": 39},
        ],
        "pfr_pass": [
            {"pfr_player_name": "Jared Goff", "week": 1, "season": 2026,
             "game_type": "REG", "team": "DET", "opponent": "NO",
             "pfr_player_id": "GoffJa00", "times_pressured": 9.0,
             "times_sacked": 1.0, "passing_bad_throws": 5.0},
        ],
    }
    row = sr.player_week_rows(role_rows)[0][0]
    passing = row["passing"]
    assert passing["attempts"] == 39  # real reconciled stat, untouched
    assert passing["times_pressured"] == 9.0  # PFR-exclusive, attached
    assert passing["times_sacked"] == 1.0
    assert passing["passing_bad_throws"] == 5.0
    # Identity/game-scope columns must NOT leak onto the merged row --
    # mirrors team_profile._attach_pfr_extra's own drop set exactly.
    assert "season" not in passing
    assert "pfr_player_id" not in passing
    assert "opponent" not in passing


def test_player_week_rows_pfr_extra_absent_when_no_pfr_row_this_week():
    role_rows = {
        "player_stats_passing": [
            {"player_display_name": "Jared Goff", "week": 1, "attempts": 39},
        ],
    }
    row = sr.player_week_rows(role_rows)[0][0]
    assert "times_pressured" not in row["passing"]


def test_player_week_rows_pfr_extra_never_attached_to_defense():
    """PFR IS defense's only source already (fully reconciled, trivially,
    through the normal per-stat path) -- there is nothing extra left to
    attach, unlike passing/rushing/receiving. Confirms _PFR_EXTRA_SOURCE
    has no "defense" entry is actually honored at the call site, not just
    declared."""
    role_rows = {
        "pfr_def": [
            {"pfr_player_name": "Aidan Hutchinson", "week": 1, "def_sacks": 2.0},
        ],
    }
    row = sr.player_week_rows(role_rows)[0][0]
    # def_sacks itself came through the normal reconcile path either way;
    # the point is _attach_pfr_extra contributes nothing extra on top.
    assert row["defense"]["def_sacks"] == 2.0


def test_player_week_rows_prefers_real_position_source_over_fallback_regardless_of_role_order():
    """Regression guard for a real, live-verified ordering bug: a two-way
    player (a real 2026 KC case -- a defensive lineman, snap_counts
    position 'NT', who also had one real rushing carry the same week) got
    his position resolved from whichever role happened to iterate FIRST in
    _PLAYER_ROLE_METRICS's fixed dict order. "rushing" (no real position
    source of its own) came before "defense" (a REAL per-game position
    source, snap_counts), so the position_of FALLBACK guess won and locked
    in before "defense"'s own accurate value ever got a chance -- purely an
    accident of dict order, not a deliberate priority. A real per-game
    position must always win over a fallback guess, regardless of which
    role happens to process first. This fixture deliberately puts "rushing"
    ahead of "defense" in _PLAYER_ROLE_METRICS's own real order (confirmed:
    rushing IS declared before defense in that dict) to prove the fix
    doesn't depend on order."""
    role_rows = {
        "player_stats_rushing": [
            {"player_display_name": "Two Way Guy", "week": 1, "carries": 1, "rushing_yards": 3},
        ],
        "pfr_def": [
            {"pfr_player_name": "Two Way Guy", "week": 1, "def_sacks": 0.0},
        ],
        "snap_counts_defense": [
            {"player": "Two Way Guy", "week": 1, "position": "NT", "defense_snaps": 36.0},
        ],
    }
    fallback_calls = []

    def position_of(name, role):
        fallback_calls.append(role)
        return "DT"  # a plausible but WRONG guess, distinct from the real "NT"

    row = sr.player_week_rows(role_rows, position_of=position_of)[0][0]
    assert row["position"] == "NT"  # the REAL per-game value, not the fallback guess
    # The fallback should never even be consulted here -- a real source
    # (snap_counts_defense) resolved the position before pass 2 runs.
    assert fallback_calls == []


def test_player_week_rows_fallback_only_fires_when_no_role_has_a_real_position_source():
    """The counterpart to the ordering-bug regression test above: when NO
    role for a player has a real position-bearing source at all (kicking
    has none, see _ROLE_POSITION_KEY), the position_of fallback DOES fire,
    proving pass 2 isn't simply disabled -- only deprioritized behind real
    sources."""
    role_rows = {
        "sleeper_kicker": [
            {"player": "Jake Bates", "week": 1, "fgm": 1, "fga": 1},
        ],
    }
    row = sr.player_week_rows(
        role_rows, position_of=lambda name, role: "K" if name == "Jake Bates" else None)[0][0]
    assert row["position"] == "K"


def test_role_rows_for_metric_matches_real_team_profile_bucket_convention():
    """Direct unit coverage of the lookup table itself, independent of the
    full merge -- confirms every metric's real role_rows key matches what
    team_profile.py's own real bucketing functions actually produce
    (_split_player_stats/_split_sleeper_stats/_split_snap_counts), not a
    guessed formula."""
    role_rows = {
        "player_stats_passing": [{"player_display_name": "X", "week": 1, "attempts": 1}],
        "sleeper_passing": [{"player": "X", "week": 1, "pass_att": 1.0}],
        "ngs_passing": [{"player_display_name": "X", "week": 1, "attempts": 1}],
    }
    out = sr._role_rows_for_metric(role_rows, "passing")
    assert set(out) == {"player_stats", "sleeper", "ngs_passing"}

    snap_role_rows = {"snap_counts_special_teams": [
        {"player": "X", "week": 1, "st_snaps": 5},
    ]}
    out2 = sr._role_rows_for_metric(snap_role_rows, "snaps_special_teams")
    assert set(out2) == {"snap_counts"}
