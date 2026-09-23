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
    """METRIC_SOURCES is built from _METRIC_MAPS, not hand-maintained --
    regression guard that it stays in sync (same self-updating-test
    discipline CLAUDE.md documents for team_profile's own dataset-label
    coverage test)."""
    assert set(sr.METRIC_SOURCES) == {"passing", "rushing", "receiving"}
    assert "player_stats" in sr.METRIC_SOURCES["passing"]
    assert "sleeper" in sr.METRIC_SOURCES["passing"]
    assert "pfr_pass" not in sr.METRIC_SOURCES["passing"]  # no volume overlap


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
