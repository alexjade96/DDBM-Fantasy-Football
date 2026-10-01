"""Cross-source stat reconciliation: given several real-NFL data sources'
own rows for the same player-week, produce ONE consensus value per stat.

Built for the team-profile page's Passing/Rushing/Receiving sections, which
used to show one full table PER SOURCE (Next Gen Stats: Passing, PFR
advanced: Passing, Box score: Passing, ...) for the same handful of
overlapping counting stats (attempts, completions, yards, TDs, ...) --
grouped by SOURCE rather than by METRIC, so the same real fact (Mahomes
threw 29 passes) was repeated across several tables with no indication
whether the sources actually agreed. This module answers that question:
for a canonical stat like "attempts", pull the value from every source
that reports it, and reconcile by MAJORITY VOTE (exact match required for
a counting stat -- these are raw counts from the same real game, so any
difference is a genuine pipeline disagreement, not rounding noise).

Four sources feed this, at the per-team-per-week grain team_profile.py
already fetches:
  - "player_stats" (nflverse's comprehensive weekly box score)
  - "ngs_passing" / "ngs_receiving" / "ngs_rushing" (NFL Next Gen Stats)
  - "pfr_pass" / "pfr_rec" / "pfr_rush" (Pro-Football-Reference advanced)
  - "sleeper" (Sleeper's own weekly feed, via sleepermetrics.nflstats.raw_week
    -- NOT previously part of team_profile.py's dataset list; added here
    specifically to serve as a real 4th source and majority-vote tiebreaker,
    matching this module's own genesis request: "add sleeper statlines as
    an actual data source, then when reconciling go by majority vote.")

Only three metric families have genuine cross-source overlap on counting
volume: Passing, Rushing, Receiving (see `_METRIC_MAPS`). PFR's own
passing/receiving/rushing datasets carry mostly PFR-EXCLUSIVE advanced
stats (pressure rate, broken tackles, yards after contact) with no
equivalent on any other source -- those are NOT reconciled, since there is
nothing to reconcile against; they stay as PFR's own single-source figures,
surfaced separately. Defense (pfr_def) and Snap counts (snap_counts) have
no second source at all, so this module has no defense/snap-count map.

The join key is NORMALISED NAME (`webapp.sources.nflref.summary._norm_name`,
the same helper `compare_sources()` already uses for its own season-wide
cross-source join) -- safe here specifically because every source's rows
handed to `reconcile_metric()` are already filtered to one team's one game
by the caller (team_profile.py), so the join pool is a handful of players,
not a whole league's roster where a name collision would be a real risk.

Two strategies exist for a SEASON total, not one: `aggregate_weeks` (sums
each SOURCE's own raw weeks first, THEN votes among sources' own season
sums -- two independent reconciliation passes) and `reconcile_season`
(votes ONCE, per week, then sums the already-reconciled weekly values --
"per-week is ground truth, a season total is just arithmetic on top of it";
see that function's own docstring for the full rationale and how the two
differ in practice). `aggregate_weeks` has no live caller today (see
`team_profile._grouped_metric_stats`'s own `multi_week` flag); `reconcile_
season` is a standalone proof-of-concept, not yet wired into either
profile page, added as the first step toward a single shared reconciled-
row builder both team_profile.py and player_profile.py would consume
(planned, not yet built -- player_profile.py currently does its own
separate, non-reconciling per-dataset collection, see `_real_nfl_history`).
"""
from __future__ import annotations

from webapp.sources.nflref.summary import _norm_name

# Per metric family: canonical_stat_key -> {source_name: source_column}.
# A source absent from a stat's inner dict simply doesn't carry that stat
# (e.g. pfr_pass has no passing-volume columns at all -- see this module's
# own docstring) and is skipped for that stat, not treated as a "0" vote.
_METRIC_MAPS = {
    "passing": {
        "attempts": {"player_stats": "attempts", "ngs_passing": "attempts",
                     "sleeper": "pass_att"},
        "completions": {"player_stats": "completions", "ngs_passing": "completions",
                        "sleeper": "pass_cmp"},
        "passing_yards": {"player_stats": "passing_yards", "ngs_passing": "pass_yards",
                          "sleeper": "pass_yd"},
        "passing_tds": {"player_stats": "passing_tds", "ngs_passing": "pass_touchdowns",
                        "sleeper": "pass_td"},
        "interceptions": {"player_stats": "interceptions", "ngs_passing": "interceptions",
                          "sleeper": "pass_int"},
    },
    "rushing": {
        "carries": {"player_stats": "carries", "ngs_rushing": "rush_attempts",
                    "pfr_rush": "carries", "sleeper": "rush_att"},
        "rushing_yards": {"player_stats": "rushing_yards", "ngs_rushing": "rush_yards",
                          "sleeper": "rush_yd"},
        "rushing_tds": {"player_stats": "rushing_tds", "ngs_rushing": "rush_touchdowns",
                        "sleeper": "rush_td"},
    },
    "receiving": {
        "targets": {"player_stats": "targets", "ngs_receiving": "targets",
                    "sleeper": "rec_tgt"},
        "receptions": {"player_stats": "receptions", "ngs_receiving": "receptions",
                       "sleeper": "rec"},
        "receiving_yards": {"player_stats": "receiving_yards", "ngs_receiving": "yards",
                            "sleeper": "rec_yd"},
        "receiving_tds": {"player_stats": "receiving_tds", "ngs_receiving": "rec_touchdowns",
                          "sleeper": "rec_td"},
    },
}

# Single-source metric families, added so EVERY metric family this app
# tracks goes through the identical reconcile_metric/reconcile_season
# machinery -- not because there is anything to vote on yet (each has
# exactly one real source today, confirmed live against the real column
# names each dataset actually carries, see this module's own git history
# for the verification), but so a future second source for any of these
# needs no new code path, and so a "one row per player-week, every stat"
# assembler (planned, not yet built -- see this module's own header
# comment) can treat every family the same way. `reconcile_metric`/
# `_majority` already handle a single-source stat correctly on their own
# (`len(values) == 1` returns `agreed=True` unconditionally) -- these maps
# add no new voting logic, only new entries.
#
# Kept OUT of `_METRIC_MAPS` itself (a separate dict, below) rather than
# merged into it, since `METRIC_SOURCES`/`stat_source_groups` are built by
# comprehension straight off `_METRIC_MAPS`'s own keys, and `METRIC_LABELS`
# (this module's OWN docstring: "the single source of truth for 'Passing'/
# 'Rushing'/'Receiving' as a metric list") is a registered Jinja global
# already consumed by team_profile.html/_team_game_detail.html/
# webapp.app.team_game_detail() -- extending it here would silently change
# what those LIVE templates iterate, before any page migration has
# actually happened. `_EXTRA_METRIC_MAPS` stays separate until Phase 3/4
# (migrating team_profile.py/player_profile.py) deliberately decide how
# defense/snaps/routes/kicking should surface, rather than that decision
# being made as a side effect of adding stat-map entries.
_EXTRA_METRIC_MAPS = {
    # PFR's own per-PLAYER defensive stat line (pfr_def) -- the only source
    # for individual defensive players' advanced stats, see team_profile.py's
    # own `_DEF_PLAYER_COLS` (the real column names this mirrors exactly,
    # confirmed live against pfr_def's own real 2026 columns).
    "defense": {
        "def_sacks": {"pfr_def": "def_sacks"},
        "def_tackles_combined": {"pfr_def": "def_tackles_combined"},
        "def_missed_tackles": {"pfr_def": "def_missed_tackles"},
        "def_missed_tackle_pct": {"pfr_def": "def_missed_tackle_pct"},
        "def_pressures": {"pfr_def": "def_pressures"},
        "def_times_blitzed": {"pfr_def": "def_times_blitzed"},
        "def_times_hurried": {"pfr_def": "def_times_hurried"},
        "def_times_hitqb": {"pfr_def": "def_times_hitqb"},
        "def_ints": {"pfr_def": "def_ints"},
        "def_targets": {"pfr_def": "def_targets"},
        "def_completions_allowed": {"pfr_def": "def_completions_allowed"},
        "def_completion_pct": {"pfr_def": "def_completion_pct"},
        "def_yards_allowed": {"pfr_def": "def_yards_allowed"},
        "def_yards_allowed_per_cmp": {"pfr_def": "def_yards_allowed_per_cmp"},
        "def_yards_allowed_per_tgt": {"pfr_def": "def_yards_allowed_per_tgt"},
        "def_receiving_td_allowed": {"pfr_def": "def_receiving_td_allowed"},
        "def_passer_rating_allowed": {"pfr_def": "def_passer_rating_allowed"},
        "def_adot": {"pfr_def": "def_adot"},
        "def_air_yards_completed": {"pfr_def": "def_air_yards_completed"},
        "def_yards_after_catch": {"pfr_def": "def_yards_after_catch"},
    },
    # Sleeper's own TEAM-level defense stat line (sleeper_def) -- a
    # DIFFERENT grain from "defense" above (one row per TEAM per week, not
    # per player), see team_profile.py's own `_DEF_TEAM_KEYS`/
    # `_sleeper_def_rows`. Kept as its own metric family, never merged with
    # the per-player "defense" map above -- reconcile_metric's own player-
    # name join would be meaningless applied to a team-level row.
    "defense_team": {
        "sack": {"sleeper_def": "sack"}, "qb_hit": {"sleeper_def": "qb_hit"},
        "int": {"sleeper_def": "int"}, "ff": {"sleeper_def": "ff"},
        "fum_rec": {"sleeper_def": "fum_rec"}, "td": {"sleeper_def": "td"},
        "safe": {"sleeper_def": "safe"}, "tkl": {"sleeper_def": "tkl"},
        "tkl_solo": {"sleeper_def": "tkl_solo"}, "tkl_ast": {"sleeper_def": "tkl_ast"},
        "tkl_loss": {"sleeper_def": "tkl_loss"},
        "def_pass_def": {"sleeper_def": "def_pass_def"},
        "def_3_and_out": {"sleeper_def": "def_3_and_out"},
        "def_forced_punts": {"sleeper_def": "def_forced_punts"},
        "pts_allow": {"sleeper_def": "pts_allow"}, "yds_allow": {"sleeper_def": "yds_allow"},
    },
    # snap_counts, split by role the same way team_profile._SNAP_BUCKETS
    # already does (one player can have real snaps in more than one role,
    # e.g. an offense/special-teams split) -- three separate metric
    # families rather than one, since a player's offense_pct and
    # defense_pct are unrelated facts, not alternate readings of "snaps".
    "snaps_offense": {"offense_snaps": {"snap_counts": "offense_snaps"},
                      "offense_pct": {"snap_counts": "offense_pct"}},
    "snaps_defense": {"defense_snaps": {"snap_counts": "defense_snaps"},
                      "defense_pct": {"snap_counts": "defense_pct"}},
    "snaps_special_teams": {"st_snaps": {"snap_counts": "st_snaps"},
                            "st_pct": {"snap_counts": "st_pct"}},
    # route_participation -- confirmed live against a real season with data
    # (2024; the current in-progress season has none yet, a known upstream
    # gap, see team_profile._off_position_cols_for_game's own docstring).
    "routes": {
        "routes_run": {"route_participation": "routes_run"},
        "targets": {"route_participation": "targets"},
        "route_go": {"route_participation": "route_go"},
        "route_slant": {"route_participation": "route_slant"},
        "route_screen": {"route_participation": "route_screen"},
        "route_quick_out": {"route_participation": "route_quick_out"},
        "route_deep_out": {"route_participation": "route_deep_out"},
        "route_hitch_curl": {"route_participation": "route_hitch_curl"},
        "route_in_dig": {"route_participation": "route_in_dig"},
        "route_shallow_cross_drag": {"route_participation": "route_shallow_cross_drag"},
        "route_corner": {"route_participation": "route_corner"},
        "route_post": {"route_participation": "route_post"},
        "route_swing": {"route_participation": "route_swing"},
        "route_texas_angle": {"route_participation": "route_texas_angle"},
        "route_wheel": {"route_participation": "route_wheel"},
    },
    # Sleeper's own weekly kicker line (sleeper_kicker) -- see
    # team_profile.py's own `_KICKER_KEYS`/`_sleeper_kicker_rows`.
    "kicking": {
        "fgm": {"sleeper_kicker": "fgm"}, "fga": {"sleeper_kicker": "fga"},
        "fgm_pct": {"sleeper_kicker": "fgm_pct"},
        "fgm_20_29": {"sleeper_kicker": "fgm_20_29"},
        "fgm_30_39": {"sleeper_kicker": "fgm_30_39"},
        "fgm_40_49": {"sleeper_kicker": "fgm_40_49"},
        "fgm_50_59": {"sleeper_kicker": "fgm_50_59"},
        "fgm_60p": {"sleeper_kicker": "fgm_60p"},
        "fgm_lng": {"sleeper_kicker": "fgm_lng"},
        "fg_blkd": {"sleeper_kicker": "fg_blkd"},
        "xpm": {"sleeper_kicker": "xpm"}, "xpa": {"sleeper_kicker": "xpa"},
    },
}

#: Every metric family this module knows how to reconcile, core (multi-
#: source, `_METRIC_MAPS`) and extra (single-source today, `_EXTRA_METRIC_
#: MAPS`) combined -- the map `reconcile_metric`/`reconcile_season`
#: actually read from (see `_stat_map_for`), so a caller doesn't need to
#: know which of the two dicts a given metric name lives in.
_ALL_METRIC_MAPS = {**_METRIC_MAPS, **_EXTRA_METRIC_MAPS}

# Not every stat sums cleanly across weeks -- three real, LIVE-VERIFIED
# categories exist alongside the plain counting stats (attempts, yards,
# TDs, ...) that `reconcile_season` sums by default:
#
#   "sum" (the default, needs no entry here) -- a genuine season total,
#     e.g. sacks, tackles, snaps, yards allowed.
#
#   "max" -- a season "best single instance" figure, not a total. Found via
#     real 2026 Jake Bates (DET) data: `fgm_lng` (longest FG made) summed
#     23+31+30 = 84 across 3 weeks, when the real season long is 31 (the
#     largest single week, not their sum -- kicking a 23-yarder one week
#     and a 31-yarder another doesn't make an 84-yard kick real). Matches
#     `team_profile._KICKER_MAX_KEYS`'s own pre-existing precedent for the
#     identical field, in a different (currently dead) season-total code
#     path (`_kicker_season_totals`) -- this module's own set is built to
#     agree with that one, not invent a second convention for the same key.
#
#   "recompute" -- a rate that CAN be correctly re-derived from other
#     already-summed stats on the same row, rather than either summed
#     (wrong) or silently dropped (loses real information the page already
#     shows elsewhere -- e.g. `team_profile._kicker_season_totals` already
#     computes a real season `fgm_pct` this way and displays it). Handled
#     as its own explicit dict (`_RECOMPUTE_STATS`, below) rather than a
#     flag here, since each one needs its own formula, not just a marker.
#
#   "omit" -- neither a sum, a max, nor a recomputable rate: EXCLUDED from
#     the season row entirely, dropped rather than shown wrong. Two real
#     reasons this applies, both confirmed against actual code/data rather
#     than assumed:
#       - a genuine rate with NO derivable numerator/denominator pair in
#         this data at all (`def_adot`, `def_passer_rating_allowed`,
#         `def_yards_allowed_per_cmp`, `def_yards_allowed_per_tgt`,
#         `def_missed_tackle_pct`, `offense_pct`/`defense_pct`/`st_pct` --
#         a snap share has no "total snaps available" companion stat in
#         this app's data to divide back out of) -- summing any of these
#         across weeks produces a meaningless number (live-verified:
#         `def_completion_pct` read 1.367, i.e. "137%", after 3 weeks of
#         naive summation).
#       - `defense_team`'s own `td` field: EXCLUDED per existing, deliberate
#         precedent in `team_profile._DEF_SEASON_EXCLUDED_KEYS` -- that
#         constant's own comment explains why (its real per-week values,
#         live-verified, are far too high/inconsistent to be genuine
#         defensive/special-teams TDs, and summing an unconfirmed figure
#         into a season total would display a wrong, unverifiable number).
#         This module mirrors that exclusion rather than re-deciding it.
#
# `reconcile_metric` (the per-WEEK reconciler) is UNAFFECTED by any of
# this -- a single week's own raw value (a rate, a max-shaped stat) is
# still a real, meaningful number at that grain, and the existing
# `_pct_keys` display convention in _teamstat_macros.html already formats
# several of these for exactly that per-game reading. These sets are the
# season-SUMMATION counterpart to that display list, not a replacement for
# it -- different layers (these gate what `reconcile_season` computes;
# `_pct_keys` gates how a single week's raw fraction renders as "N%").
_MAX_STATS = {"fgm_lng"}
_OMIT_STATS = {
    "offense_pct", "defense_pct", "st_pct",
    "def_missed_tackle_pct", "def_completion_pct",
    "def_yards_allowed_per_cmp", "def_yards_allowed_per_tgt",
    "def_passer_rating_allowed", "def_adot",
    "td",  # defense_team only -- see this block's own comment
}
#: `{recomputed_stat: (numerator_stat, denominator_stat, round_ndigits,
#: scale)}` -- computed AFTER every other stat has been summed, from the
#: summed numerator/denominator (never averaged from weekly rates, which
#: would weight a 1-attempt week the same as a 10-attempt week -- the exact
#: reasoning `_kicker_season_totals`'s own comment already gives for
#: `fgm_pct`). `scale=100` matches Sleeper's own `fgm_pct` convention
#: (0-100, not 0-1 -- see _teamstat_macros.html's own `_pct_keys` comment
#: for the same live-verified distinction). A season with a zero
#: denominator gets no entry for that stat (never a division by zero, never
#: a fabricated 0%).
_RECOMPUTE_STATS = {
    "fgm_pct": ("fgm", "fga", 1, 100),
}


def _stat_map_for(metric: str) -> dict | None:
    return _ALL_METRIC_MAPS.get(metric)

#: (metric_key, display_label) pairs in display order -- the single source
#: of truth for "Passing"/"Rushing"/"Receiving" as a metric list, so
#: team_profile.html, _team_game_detail.html, and webapp.app's
#: team_game_detail() route all iterate the exact same list rather than
#: each hand-typing their own copy (a real drift risk this codebase's own
#: convention warns against -- see CLAUDE.md's "computed twice, drifted"
#: caution). Registered as a Jinja global (tpl.env.globals) in app.py, same
#: precedent CHART_META already sets for sharing a Python constant with
#: templates.
METRIC_LABELS = [("passing", "Passing"), ("rushing", "Rushing"),
                 ("receiving", "Receiving")]

#: Human labels for the sources this module knows about, for template display.
SOURCE_LABELS = {
    "player_stats": "Box score", "ngs_passing": "Next Gen Stats",
    "ngs_receiving": "Next Gen Stats", "ngs_rushing": "Next Gen Stats",
    "pfr_pass": "PFR advanced", "pfr_rec": "PFR advanced",
    "pfr_rush": "PFR advanced", "sleeper": "Sleeper",
    "pfr_def": "PFR advanced", "sleeper_def": "Sleeper",
    "snap_counts": "Snap counts", "route_participation": "Route participation",
    "sleeper_kicker": "Sleeper",
}

#: Name column per source (mirrors team_profile.html's own name_cols list --
#: each source only ever populates one of these). "sleeper_def" is a
#: TEAM-level row (see `_EXTRA_METRIC_MAPS["defense_team"]`'s own comment),
#: but `team_profile._sleeper_def_rows` already keys each row's join field
#: as `"player": <team abbreviation>` (confirmed live in that function's
#: own real implementation) -- reused as this source's `_NAME_COL` entry
#: too, so `reconcile_metric`'s generic name-keyed join works unmodified
#: for a team-level row, joining on team abbreviation instead of a player
#: name. `reconcile_season`'s own docstring already treats "player" as a
#: generic join-key label, not literally "a human", so this is consistent
#: with the rest of the module rather than a special case.
_NAME_COL = {
    "player_stats": "player_display_name", "ngs_passing": "player_display_name",
    "ngs_receiving": "player_display_name", "ngs_rushing": "player_display_name",
    "pfr_pass": "pfr_player_name", "pfr_rec": "pfr_player_name",
    "pfr_rush": "pfr_player_name", "sleeper": "player",
    "pfr_def": "pfr_player_name", "snap_counts": "player",
    "route_participation": "name", "sleeper_kicker": "player",
    "sleeper_def": "player",
}

#: Which dataset(s) actually feed each metric family (the source keys
#: `_METRIC_MAPS[metric]`'s stat dicts reference) -- used by team_profile.py
#: to know which raw rows to hand `reconcile_metric()`. Covers every metric
#: in `_ALL_METRIC_MAPS` (core + extra, see that dict's own comment), not
#: just the 3 live-wired families -- a pure derived lookup with no Jinja/
#: template consumer (unlike `METRIC_LABELS`), so extending its coverage
#: carries none of that risk; team_profile.py's own loop only ever indexes
#: the 3 it already knows about, unaffected by the extra entries existing.
METRIC_SOURCES = {
    metric: sorted({src for stat_map in stats.values() for src in stat_map})
    for metric, stats in _ALL_METRIC_MAPS.items()
}


def stat_source_groups(metric: str, present: set[str] | None = None) -> list[tuple[tuple[str, ...], list[str]]]:
    """Group a metric's own canonical stats (`_METRIC_MAPS[metric]`'s keys,
    in their declared display order) by which EXACT set of sources actually
    feeds each one, rather than the flat union `METRIC_SOURCES[metric]`
    collapses them into.

    Built because that flat union overstates a stat-level fact: within
    "rushing", `carries` is fed by player_stats/ngs_rushing/pfr_rush/sleeper
    (4 sources -- pfr_rush's one genuinely overlapping column) while
    `rushing_yards`/`rushing_tds` are only fed by player_stats/ngs_rushing/
    sleeper (3 -- PFR's rushing dataset has no yards/TD columns of its own,
    see this module's own docstring). A flat "Source: Box score, Next Gen
    Stats, PFR advanced, Sleeper" note on the whole Rushing table reads as
    if PFR voted on yards/TDs too, which it never does. "Passing" and
    "Receiving" happen to be uniform today (every stat in each of those two
    maps shares the identical source set) but this groups by the real map
    regardless, so a future asymmetric addition there is picked up
    automatically rather than needing a second manual fix.

    Returns an ordered list of `(source_keys, stat_labels)` pairs, one per
    DISTINCT source combination found, in the stats' own declared order
    (first stat to introduce a given combination determines where it sorts;
    a later stat sharing that exact combination is appended to the same
    group rather than starting a new one). `source_keys` is a sorted tuple
    (stable, hashable); `stat_labels` are the canonical stat keys
    (`"attempts"`, `"carries"`, ...) themselves, not display abbreviations
    -- the caller (the template) already has its own key -> abbreviation
    map (`reconciled_cols` in _teamstat_macros.html) and maps at render
    time so the two never need to be kept in step twice.

    `present`, if given, restricts each stat's source set to sources that
    actually had a row THIS slice (e.g. `entry["sources"]` from
    `team_profile._grouped_metric_stats`, itself already filtered to
    "actually had rows feeding `reconciled`") -- a source present in
    the metric's own map in principle but absent this particular game/
    season is dropped from that stat's group rather than claimed. Passing
    `None` (the default) uses every source the map declares, unfiltered.

    Works for any metric `_stat_map_for` resolves (core or extra, see
    `_ALL_METRIC_MAPS`), not just the 3 originally-wired families.
    """
    stat_map = _stat_map_for(metric)
    if not stat_map:
        return []
    groups: dict[tuple[str, ...], list[str]] = {}
    order: list[tuple[str, ...]] = []
    for stat, src_cols in stat_map.items():
        keys = set(src_cols)
        if present is not None:
            keys &= present
        if not keys:
            continue
        combo = tuple(sorted(keys))
        if combo not in groups:
            groups[combo] = []
            order.append(combo)
        groups[combo].append(stat)
    return [(combo, groups[combo]) for combo in order]


def _stat_value(row: dict, key: str):
    v = row.get(key)
    if v is None:
        return None
    try:
        if isinstance(v, float) and v != v:  # NaN
            return None
    except TypeError:
        return None
    return v


#: Sources excluded from SEASON-WIDE reconciliation (see `aggregate_weeks`)
#: because they don't cover every real game -- a season SUM built from an
#: incomplete source isn't comparable to one built from a complete source,
#: and including it here would flag "disagreement" on nearly every player's
#: season total, drowning out genuine same-game disagreements between
#: sources that ARE both complete. NGS only publishes a row for a player-
#: week its own tracking system actually covered (verified live and
#: documented at length elsewhere in this codebase -- see CLAUDE.md's
#: "NGS is NOT comprehensive" bullet); it stays a full voting source for
#: PER-GAME reconciliation (`reconcile_metric` called directly, no
#: `aggregate_weeks` step), where a missing row just means it doesn't vote
#: that week, which is fine.
_SEASON_EXCLUDED_SOURCES = {"ngs_passing", "ngs_receiving", "ngs_rushing"}


def aggregate_weeks(rows_by_source: dict[str, list[dict]],
                    metric: str) -> tuple[dict[str, list[dict]], dict]:
    """Collapse MULTIPLE WEEKS of rows per source into ONE summed row per
    player per source -- the season-total counterpart to `reconcile_metric`,
    which itself assumes at most one row per player per source (built for
    the per-GAME drilldown, where that's true by construction).

    Real bug this fixed: team_profile.py's season-wide "Advanced & usage
    stats" section hands `reconcile_metric` a WHOLE SEASON's rows per
    source (17+ weeks, one row per player per week) without this step
    first -- `reconcile_metric`'s own per-player dict slot keeps only the
    LAST row it sees for that player+source, so a season "total" silently
    became whatever ONE WEEK happened to be seen last (verified live: KC's
    season-wide Passing table showed Mahomes at 189 passing yards, a single
    week's number, not his real ~4,900-yard season).

    Sums every canonical stat's own source column (see `_METRIC_MAPS`) per
    player, across every row for that player+source -- NOT a mean, since
    these are counting stats (a season total is the sum of the weeks, not
    their average).

    Returns `(rows_by_source, ngs_coverage)`:
      - `rows_by_source` is the same `{source: [row, ...]}` shape
        `reconcile_metric` expects, so the two compose:
        `aggregate_weeks(...)[0]` -> `reconcile_metric(...)`. EXCLUDES
        `_SEASON_EXCLUDED_SOURCES` (NGS) entirely -- see that set's own
        docstring for why: an incomplete-coverage source's season sum
        isn't a genuine data point to vote alongside a complete source's,
        it's an artifact of missing weeks. Real pattern that prompted this
        (live-verified, all 4 real teams checked): NGS's season sum for
        nearly every real player reads systematically LOWER than
        player_stats/sleeper's, purely from missing weeks -- e.g. Travis
        Kelce's real 108 targets summed to only 97 on NGS alone, with NO
        single game actually in dispute.
      - `ngs_coverage` is `{norm_name: {"player": name, "weeks": N,
        <stat>: ngs_total, ...}}` for whichever players NGS's EXCLUDED
        rows covered -- kept, not discarded, specifically so a future
        session can analyze NGS's real week-by-week coverage rate (what
        fraction of a player's real games NGS actually published a row
        for) without re-deriving this aggregation. Not wired into any
        display yet; a data point for future work, per user request
        ("add a note ... for eventual analysis of actual ngs full-season
        coverage in the future").

    A row with `week == 0` is SKIPPED for every source -- a real, verified
    data shape: the `ngs_*` datasets (and only those; player_stats/pfr_*/
    sleeper do not) publish their own pre-aggregated SEASON-TOTAL row at
    week 0 alongside every real weekly row. Summing it in doubled every
    ngs_* season total before this guard existed (live-verified: Mahomes's
    season attempts read 1004, exactly 2x his real 502). Now moot for
    reconciliation itself (NGS is excluded from `rows_by_source` anyway),
    but still applied when building `ngs_coverage` so THAT figure is also
    a real weekly sum, not double-counted.
    """
    stat_map = _METRIC_MAPS.get(metric)
    if not stat_map:
        return {}, {}

    def _sum_source(src: str) -> dict[str, dict]:
        name_col = _NAME_COL.get(src)
        cols = {col for src_cols in stat_map.values() for s, col in src_cols.items() if s == src}
        # norm_name -> {name_col: name, col: total, ...} -- the summed row
        # keeps THIS source's own name-column key (name_col), not a
        # hardcoded "player", so reconcile_metric's own _NAME_COL lookup
        # (built for the raw per-source row shape) still finds the name on
        # an aggregated row exactly as it would on a raw one. A real bug
        # this fixed: an earlier version wrote "player" unconditionally,
        # which only happened to match sleeper's own name_col ("player"),
        # silently dropping player_stats/ngs_*'s aggregated rows from every
        # season-wide reconciliation (they use "player_display_name").
        sums: dict[str, dict] = {}
        weeks: dict[str, int] = {}
        for row in rows_by_source.get(src, []) or []:
            if row.get("week") == 0:
                continue
            name = row.get(name_col) if name_col else None
            if not name:
                continue
            key = _norm_name(name)
            if not key:
                continue
            slot = sums.setdefault(key, {name_col: name} if name_col else {})
            weeks[key] = weeks.get(key, 0) + 1
            for col in cols:
                v = _stat_value(row, col)
                if v is None:
                    continue
                slot[col] = slot.get(col, 0) + v
        for key, slot in sums.items():
            slot["_weeks"] = weeks.get(key, 0)
        return sums

    out: dict[str, list[dict]] = {}
    ngs_coverage: dict[str, dict] = {}
    for src in METRIC_SOURCES[metric]:
        sums = _sum_source(src)
        if not sums:
            continue
        if src in _SEASON_EXCLUDED_SOURCES:
            name_col = _NAME_COL.get(src)
            for key, slot in sums.items():
                entry = ngs_coverage.setdefault(key, {"player": slot.get(name_col)})
                entry[src] = {k: v for k, v in slot.items() if k not in (name_col, "_weeks")}
                entry[f"{src}_weeks"] = slot["_weeks"]
            continue
        out[src] = [{k: v for k, v in slot.items() if k != "_weeks"}
                    for slot in sums.values()]
    return out, ngs_coverage


def _majority(values: dict[str, float | int]) -> tuple[float | int | None, bool]:
    """`values`: {source: value} for one stat, sources that reported it only.

    Returns (consensus_value, agreed). `agreed=True` ONLY when every
    reporting source has the exact same value -- true unanimity, not just
    "a majority formed". Anything less than unanimous IS a real
    disagreement worth flagging (one or more sources measured this game
    differently), even when a majority/plurality resolves which value to
    actually show:
      - a clear plurality (one value strictly more common than any other)
        -> that value, agreed=False
      - a tie among the most-common values (including a straight 2-way
        split with only 2 sources reporting) -> "player_stats" (nflverse's
        box score, the comprehensive baseline this module already treats
        as ground truth elsewhere -- see team_profile.py's own "Box score"
        docstring) if it's one of the tied values or voted at all, else
        the first source's value in a stable (sorted) order -- either way,
        agreed=False, and the page always has SOMETHING to show rather
        than a blank cell on a genuine standoff.
    """
    if not values:
        return None, True  # nothing to disagree about
    if len(values) == 1:
        return next(iter(values.values())), True

    tally: dict = {}
    for v in values.values():
        tally[v] = tally.get(v, 0) + 1
    if len(tally) == 1:
        return next(iter(tally)), True  # unanimous

    best_count = max(tally.values())
    winners = [v for v, c in tally.items() if c == best_count]
    if len(winners) == 1:
        return winners[0], False  # clear plurality, but not unanimous

    # tie among the most-common values -- fall back to player_stats if it
    # voted at all, else the first source alphabetically.
    if "player_stats" in values:
        return values["player_stats"], False
    for src in sorted(values):
        return values[src], False
    return None, False  # unreachable, keeps type checkers happy


def _weeks_present(rows_by_source: dict[str, list[dict]]) -> list:
    """Every distinct `week` value across all sources' rows, sorted, week 0
    excluded (see `aggregate_weeks`'s own docstring for why: ngs_* publishes
    a pre-aggregated season-total row at week 0 alongside its real weekly
    rows -- including it here would double-count a player's season sum on
    top of the real weeks already covering that same production)."""
    weeks = {row.get("week") for rows in rows_by_source.values() for row in rows
             if row.get("week") not in (None, 0)}
    return sorted(weeks)


def reconcile_season(rows_by_source: dict[str, list[dict]], metric: str,
                     season_only_rows: list[dict] | None = None,
                     season_only_source: str = "") -> tuple[list[dict], dict]:
    """Season total for one metric family, built by reconciling EACH WEEK
    first (majority vote across whichever sources reported that week, via
    the same `reconcile_metric` every per-game caller already uses) and
    THEN summing the reconciled weekly values -- per-week is the ground
    truth grain, a season total is just arithmetic on top of numbers
    already trusted.

    This is a DIFFERENT order of operations from `aggregate_weeks` (which
    sums each SOURCE's own raw weeks first, then votes among sources' own
    sums -- two independent reconciliation passes, one of which can pick a
    season total that isn't equal to the sum of what the weekly rows
    actually say). `reconcile_season` votes exactly ONCE, at the week
    grain; the season number is guaranteed by construction to equal
    `sum(week's reconciled value for every week)`.

    Not every stat is a plain sum -- see `_MAX_STATS`/`_OMIT_STATS`/
    `_RECOMPUTE_STATS`'s own shared comment block for the full rationale
    (each backed by either a real live-verified bug or an existing,
    deliberate precedent elsewhere in this codebase):
      - `_MAX_STATS` (e.g. `fgm_lng`) take the largest single week's value,
        not the sum -- a season "long" is one real kick, not several added
        together.
      - `_OMIT_STATS` (rates with no derivable numerator/denominator, plus
        `defense_team`'s own unconfirmed `td` field) are excluded from the
        season row entirely, never shown wrong.
      - `_RECOMPUTE_STATS` (currently just `fgm_pct`) are computed AFTER
        summation from their own already-summed numerator/denominator,
        never averaged from weekly rates and never a plain sum either.
    This only matters for the newer single-source families (defense/snaps/
    kicking) -- the original passing/rushing/receiving maps have no
    non-summable stats in them to begin with.

    A source that only ever publishes a season total (not a per-week
    breakdown -- none of this app's current sources work that way, but the
    mechanism exists for one that might) never gets a vote in the per-week
    pass at all, since it has no weekly rows to contribute. Pass it via
    `season_only_rows` (one row per player, whatever the source's own
    season-total shape is, keyed the same way `reconcile_metric` keys any
    row -- `_NAME_COL`) and it is compared AFTER the fact against the
    summed total as a cross-check, never blended into the vote: `disagree`
    in the returned dict lists `(stat, season_only_value, summed_value)`
    for every mismatch, keyed by normalised player name. Omitted entirely
    (`None`, the default) when there is no such source to check.

    Returns `(season_rows, disagreements)`:
      - `season_rows`: one row per player, same `{"player", <stat>,
        <stat>_agreed, <stat>_sources}` shape `reconcile_metric` returns for
        a single game, except here `<stat>` is a REAL SUM across every
        week reconciled (not one week's number) and `<stat>_sources` is the
        union of every source that voted on ANY week that fed the sum
        (which weeks/sources fed which player is not preserved at this
        grain -- a per-week breakdown is still available by calling
        `reconcile_metric` directly per week, same as before). `<stat>_
        agreed` is True only when EVERY week that contributed to the sum
        was itself unanimous -- one disagreed week is enough to flag the
        whole season total as "built from at least one real disagreement",
        even though the summed NUMBER itself is still exactly the sum of
        whichever value won each week's vote.
      - `disagreements`: `{norm_name: {stat: (season_only_value,
        summed_value)}}`, present only when a mismatch was found between a
        season-only source's own figure and the sum of the reconciled
        weekly values. Empty dict when no season-only rows were passed.

    Unknown `metric` returns `([], {})`, matching `aggregate_weeks`'s own
    convention for the same case. Works for any metric `_stat_map_for`
    resolves (core or extra, see `_ALL_METRIC_MAPS`) -- a single-source
    family (e.g. "defense", "snaps_offense") reconciles trivially (nothing
    to vote on, `agreed` always True) through the identical code path.
    """
    stat_map = _stat_map_for(metric)
    if not stat_map:
        return [], {}

    weeks = _weeks_present(rows_by_source)

    # {norm_name: {"player": display_name, stat: running_sum,
    #              f"{stat}_agreed": bool, f"{stat}_sources": set}}
    totals: dict[str, dict] = {}
    for week in weeks:
        week_rows_by_source = {
            src: [row for row in rows if row.get("week") == week]
            for src, rows in rows_by_source.items()
        }
        week_rows_by_source = {s: r for s, r in week_rows_by_source.items() if r}
        if not week_rows_by_source:
            continue
        for row in reconcile_metric(week_rows_by_source, metric):
            key = _norm_name(row["player"])
            slot = totals.setdefault(key, {"player": row["player"]})
            for stat in stat_map:
                if stat in _OMIT_STATS or stat in _RECOMPUTE_STATS or stat not in row:
                    continue
                value = row[stat]
                if stat in _MAX_STATS:
                    slot[stat] = max(slot.get(stat, value), value)
                else:
                    slot[stat] = slot.get(stat, 0) + value
                # One disagreed week is enough to flag the season total as
                # built from at least one real disagreement, even though
                # the summed/max figure is still exactly correct arithmetic.
                agreed_key = f"{stat}_agreed"
                slot[agreed_key] = slot.get(agreed_key, True) and row[agreed_key]
                sources_key = f"{stat}_sources"
                slot.setdefault(sources_key, set()).update(row[f"{stat}_sources"])

    season_rows = []
    for slot in totals.values():
        out_row = dict(slot)
        for stat in stat_map:
            sources_key = f"{stat}_sources"
            if sources_key in out_row:
                out_row[sources_key] = sorted(out_row[sources_key])
        # Recomputed stats (fgm_pct etc) are derived HERE, after every real
        # sum for this player is final -- never from a weekly average (see
        # `_RECOMPUTE_STATS`'s own comment: that would weight a 1-attempt
        # week the same as a 10-attempt week). No entry at all when the
        # denominator is zero/missing -- never a division by zero, never a
        # fabricated 0%.
        for stat, (num_key, den_key, ndigits, scale) in _RECOMPUTE_STATS.items():
            if stat not in stat_map:
                continue
            num = out_row.get(num_key)
            den = out_row.get(den_key)
            if num is None or not den:
                continue
            out_row[stat] = round(scale * num / den, ndigits)
        season_rows.append(out_row)
    season_rows.sort(key=lambda r: r["player"])

    disagreements: dict[str, dict] = {}
    if season_only_rows:
        name_col = _NAME_COL.get(season_only_source)
        summed_by_key = {_norm_name(r["player"]): r for r in season_rows}
        for row in season_only_rows:
            name = row.get(name_col) if name_col else row.get("player")
            if not name:
                continue
            key = _norm_name(name)
            summed = summed_by_key.get(key)
            if summed is None:
                continue
            for stat, src_cols in stat_map.items():
                col = src_cols.get(season_only_source, stat)
                season_val = _stat_value(row, col)
                summed_val = summed.get(stat)
                if season_val is None or summed_val is None:
                    continue
                if season_val != summed_val:
                    disagreements.setdefault(key, {})[stat] = (season_val, summed_val)

    return season_rows, disagreements


def reconcile_metric(rows_by_source: dict[str, list[dict]], metric: str) -> list[dict]:
    """Reconcile one metric family ("passing"/"rushing"/"receiving") across
    whichever of `rows_by_source` (the {source_name: [row, ...]} shape
    team_profile.py already builds per game) actually apply to it.

    Returns one row per player who appears in ANY contributing source:
    `{"player": name, "<stat>": consensus_value,
      "<stat>_agreed": bool, "<stat>_sources": {source: value}}` for every
    canonical stat in this metric's map. A player only some sources saw
    (e.g. Next Gen Stats missed a real target) still gets a row, built
    from whichever sources DID report him -- see this module's own
    docstring for why NGS coverage gaps are the reason this reconciliation
    exists in the first place.

    Works for any metric `_stat_map_for` resolves (core or extra, see
    `_ALL_METRIC_MAPS`) -- a single-source family (e.g. "defense",
    "snaps_offense") produces a row per player with `agreed=True`
    unconditionally (nothing to vote on), through this identical code path.
    Unknown `metric` returns [].
    """
    stat_map = _stat_map_for(metric)
    if not stat_map:
        return []

    # {norm_name: {"player": display_name, source: row}}
    by_player: dict[str, dict] = {}
    for src in METRIC_SOURCES[metric]:
        name_col = _NAME_COL.get(src)
        for row in rows_by_source.get(src, []) or []:
            name = row.get(name_col) if name_col else None
            if not name:
                continue
            key = _norm_name(name)
            if not key:
                continue
            slot = by_player.setdefault(key, {"player": name})
            slot[src] = row
            # Prefer a real display name over one source's own casing
            # quirks -- first-seen wins, same "don't second-guess a name
            # that already resolved" precedent identity.resolve() follows.

    out = []
    for key, slot in by_player.items():
        prow = {"player": slot["player"]}
        any_stat = False
        for stat, src_cols in stat_map.items():
            values = {}
            for src, col in src_cols.items():
                row = slot.get(src)
                if row is None:
                    continue
                v = _stat_value(row, col)
                if v is not None:
                    values[src] = v
            if not values:
                continue
            any_stat = True
            consensus, agreed = _majority(values)
            prow[stat] = consensus
            prow[f"{stat}_agreed"] = agreed
            prow[f"{stat}_sources"] = values
        if any_stat:
            out.append(prow)

    out.sort(key=lambda r: r["player"])
    return out


# --- player_week_rows: one merged row per (player, week), every metric ------
#
# Phase 2 of the planned shared reconciled-row builder (see this module's
# own header comment). Phase 1 (above) made every metric family this app
# tracks reconcilable through one engine; this is the actual "collect all
# player data into one row" step -- merging passing/rushing/receiving/
# defense/snaps/routes/kicking onto ONE dict per real player per real week,
# rather than one table per metric family (what `reconcile_metric` alone
# still returns). `team_profile._merge_offense_players`/`_merge_defense_
# players` (hand-written, page-specific, limited to their own 5 offense /
# 2 defense sub-keys) already did a version of this idea when this module
# was built; both have since been replaced by the adapters this module's
# output feeds (`_offense_players_via_shared`/`_defense_players_via_
# shared`) and deleted entirely (2026-09, zero remaining callers). This
# generalizes the idea to every family at once, driven by
# `_PLAYER_ROLE_METRICS` (data), so a new metric family needs a new map
# entry here, not a new merge function.
#
# A team-level row (Sleeper's own `defense_team` family -- see
# `_EXTRA_METRIC_MAPS["defense_team"]`'s own comment: no individual player
# identity at all) is a DIFFERENT GRAIN from a per-player row and is
# returned in its own separate list, never merged onto an arbitrary
# player's dict.
#: `role -> metric name` -- which reconciled metric family fills which slot
#: on a merged player row. Declared as data so a new family needs only a
#: new entry here, not a new merge function.
_PLAYER_ROLE_METRICS = {
    "passing": "passing", "rushing": "rushing", "receiving": "receiving",
    "defense": "defense", "snap_offense": "snaps_offense",
    "snap_defense": "snaps_defense", "snap_special_teams": "snaps_special_teams",
    "route": "routes", "kicking": "kicking",
}
#: Which of a role's own sources carries a `position` column, when any does
#: (see `_POS_COL`-style per-dataset gaps documented elsewhere in this
#: codebase) -- `None` means this role's own sources never carry position
#: at all, and a caller-supplied `position_of` fallback is the only way to
#: fill it (mirrors `team_profile._position_of`'s existing two-tier chain).
#: `role -> role_rows key` to consult for that role's position (not a bare
#: source name -- `defense`'s own reconciled source, pfr_def, carries NO
#: position column at all; confirmed live against pfr_def's real columns.
#: `snap_counts_defense`, a SEPARATE role_rows key from defense's own
#: metric sources, is the real position source there, matching
#: `team_profile._defense_players_via_shared`'s real resolution logic
#: (originally matched the former `_merge_defense_players`, since
#: deleted). `None` means this role's own data never carries position at
#: all, and a caller-supplied `position_of` fallback is the only way to
#: fill it.
_ROLE_POSITION_KEY = {
    "passing": None, "rushing": None, "receiving": None,
    "defense": "snap_counts_defense", "snap_offense": "snap_counts_offense",
    "snap_defense": "snap_counts_defense", "snap_special_teams": "snap_counts_special_teams",
    "route": None, "kicking": None,
}


#: `metric -> {source: role_rows_key}` -- how to find each metric's own
#: sources inside `role_rows` (the shape `team_profile._attach_week_stats`
#: already builds). NOT one universal formula: `role_rows`'s real key
#: convention genuinely differs per source, confirmed against
#: `team_profile.py`'s own real bucketing functions rather than guessed --
#: `player_stats`/`sleeper` (multi-role sources, split by
#: `_split_player_stats`/`_split_sleeper_stats`) key as `"{source}_
#: {metric}"` (e.g. "player_stats_passing", "sleeper_receiving");
#: `snap_counts` (split by `_split_snap_counts`) keys as
#: `"snap_counts_{bucket}"` where `bucket` DROPS the "snaps_" metric-name
#: prefix ("snap_counts_offense", not "snap_counts_snaps_offense"); every
#: other source (ngs_*, pfr_*, route_participation, sleeper_kicker,
#: sleeper_def) is already single-role by construction and keyed bare.
#: Explicit per metric rather than a derived formula, since a fourth
#: naming convention showing up later is a real possibility this table
#: makes easy to add without touching the lookup function itself.
_ROLE_ROWS_KEY = {
    "passing": {"player_stats": "player_stats_passing", "ngs_passing": "ngs_passing",
                "sleeper": "sleeper_passing"},
    "rushing": {"player_stats": "player_stats_rushing", "ngs_rushing": "ngs_rushing",
                "pfr_rush": "pfr_rush", "sleeper": "sleeper_rushing"},
    "receiving": {"player_stats": "player_stats_receiving", "ngs_receiving": "ngs_receiving",
                  "sleeper": "sleeper_receiving"},
    "defense": {"pfr_def": "pfr_def"},
    "defense_team": {"sleeper_def": "sleeper_def"},
    "snaps_offense": {"snap_counts": "snap_counts_offense"},
    "snaps_defense": {"snap_counts": "snap_counts_defense"},
    "snaps_special_teams": {"snap_counts": "snap_counts_special_teams"},
    "routes": {"route_participation": "route_participation"},
    "kicking": {"sleeper_kicker": "sleeper_kicker"},
}


def _role_rows_for_metric(role_rows: dict[str, list[dict]], metric: str) -> dict[str, list[dict]]:
    """`role_rows` narrowed to the `{source: rows}` shape `reconcile_metric`
    wants for ONE metric family, via `_ROLE_ROWS_KEY`'s own explicit
    per-source key convention (see that dict's own docstring for why this
    isn't one universal formula)."""
    out: dict[str, list[dict]] = {}
    for src, key in _ROLE_ROWS_KEY.get(metric, {}).items():
        hit = role_rows.get(key)
        if hit:
            out[src] = hit
    return out


_PFR_EXTRA_SOURCE = {"passing": "pfr_pass", "rushing": "pfr_rush", "receiving": "pfr_rec"}
_PFR_EXTRA_DROP = {"season", "week", "game_type", "team", "opponent",
                   "pfr_player_name", "pfr_player_id"}


def _attach_pfr_extra(role_rows_full: dict, week, metric: str) -> dict[str, dict]:
    """`{norm_name: {stat: value, ...}}` for players with a real PFR row
    this week, for metrics PFR contributes extra non-reconciled columns to.
    Mirrors `team_profile._attach_pfr_extra`'s own real, pre-existing
    per-game logic exactly. `{}` for "defense" (PFR is already defense's
    only source) or any metric with no PFR-extra source."""
    src = _PFR_EXTRA_SOURCE.get(metric)
    if not src:
        return {}
    pfr_rows = [r for r in (role_rows_full.get(src) or []) if r.get("week") == week]
    out: dict[str, dict] = {}
    for pr in pfr_rows:
        key = _norm_name(pr.get(_NAME_COL.get(src)))
        if key:
            out[key] = {k: v for k, v in pr.items() if k not in _PFR_EXTRA_DROP}
    return out


def player_week_rows(role_rows: dict[str, list[dict]],
                     position_of=None) -> tuple[list[dict], list[dict]]:
    """Merge every metric family's per-week reconciled rows into ONE row per
    (player, week) -- the shared assembler both team_profile.py and
    player_profile.py are planned to consume in place of their own separate
    per-page merge logic (not yet wired into either; see this module's
    header comment).

    `role_rows` is the same shape `team_profile._attach_week_stats` already
    builds per game before calling `_grouped_metric_stats` -- see
    `_role_rows_for_metric`'s own docstring for the exact key convention.
    Every row handed in must carry a `week` value (rows with none are
    grouped under the literal key `None`, not dropped) -- this function has
    no opinion on grain: call it once per real week for a per-game merged
    row (matching `team_profile.py`'s own per-game slicing), or hand it a
    whole season's rows at once for a season-spanning merge keyed by
    (player, week) pairs.

    `position_of(name, role) -> str | None`, if given, is consulted for any
    player whose own role sources carry no position column at all (passing/
    rushing/receiving/routes/kicking -- see `_ROLE_POSITION_KEY`); the
    caller's own fallback chain (e.g. a roster lookup), mirroring
    `team_profile._position_of`'s existing two-tier convention rather than
    reimplementing one here. Omitted (the default) leaves `position` as
    whatever a defense/snap row could resolve on its own, `None` otherwise.

    Returns `(player_rows, team_rows)`:
      - `player_rows`: one dict per (player, week) -- `{"player": name,
        "week": w, "position": str | None, <role>: row | None, ...}` for
        every key in `_PLAYER_ROLE_METRICS`, `None` for any role this
        player had no row for that week. Sorted by (week, player).
      - `team_rows`: one dict per (team abbreviation, week) for the
        "defense_team" family -- `{"team": abbr, "week": w,
        "defense_team": row}`. Empty when `role_rows` has no defense_team
        source rows at all. Sorted by (week, team).
    """
    player_slots: dict[tuple[str, object], dict] = {}
    team_slots: dict[tuple[str, object], dict] = {}

    def player_slot(name: str, week) -> dict:
        key = (_norm_name(name), week)
        if key not in player_slots:
            player_slots[key] = {"player": name, "week": week, "position": None,
                                 **{role: None for role in _PLAYER_ROLE_METRICS}}
        return player_slots[key]

    # Two passes, deliberately -- NOT a single pass through
    # _PLAYER_ROLE_METRICS in dict order. A real, live-verified bug in an
    # earlier version: a rare two-way player (a real 2026 KC case, a
    # defensive lineman who also had one real rushing carry that same
    # week) got his position resolved from whichever role happened to
    # iterate FIRST in _PLAYER_ROLE_METRICS -- "rushing" (no real position
    # source of its own, see _ROLE_POSITION_KEY) came before "defense" (a
    # REAL per-game position source, snap_counts), so the caller's
    # `position_of` FALLBACK guess ("DT", his current roster listing) won
    # and locked in before "defense"'s own accurate per-game value ("NT")
    # ever got a chance -- purely an accident of dict insertion order, not
    # a deliberate priority. Pass 1 fills every role's row data AND every
    # position a REAL source can supply (snap_counts/pfr_def, via
    # `_ROLE_POSITION_KEY`), for every role, before any fallback is
    # consulted at all. Pass 2 only then calls `position_of` for whichever
    # players still have no position after every real source had its turn
    # -- so a real per-game position always wins over a fallback guess,
    # regardless of which role happens to appear first in the dict.
    pending_fallback: list[tuple[dict, str, str]] = []  # (player_slot, name, role)
    for role, metric in _PLAYER_ROLE_METRICS.items():
        rows_by_source = _role_rows_for_metric(role_rows, metric)
        if not rows_by_source:
            continue
        pos_key = _ROLE_POSITION_KEY.get(role)
        pos_rows_by_week: dict = {}
        if pos_key:
            for r in role_rows.get(pos_key) or []:
                pos_rows_by_week.setdefault(r.get("week"), {})[_norm_name(r.get("player"))] = r.get("position")
        for week in _weeks_present(rows_by_source):
            week_rows = {src: [r for r in rows if r.get("week") == week]
                        for src, rows in rows_by_source.items()}
            week_rows = {s: r for s, r in week_rows.items() if r}
            if not week_rows:
                continue
            pfr_extra = _attach_pfr_extra(role_rows, week, metric)
            for row in reconcile_metric(week_rows, metric):
                if pfr_extra:
                    extra = pfr_extra.get(_norm_name(row["player"]))
                    if extra:
                        row.update(extra)
                p = player_slot(row["player"], week)
                p[role] = row
                if p["position"] is None:
                    target = _norm_name(row["player"])
                    resolved = pos_rows_by_week.get(week, {}).get(target)
                    if resolved:
                        p["position"] = resolved
                    elif position_of:
                        pending_fallback.append((p, row["player"], role))

    if position_of:
        for p, name, role in pending_fallback:
            if p["position"] is None:
                p["position"] = position_of(name, role)

    def_team_rows = _role_rows_for_metric(role_rows, "defense_team")
    if def_team_rows:
        for week in _weeks_present(def_team_rows):
            week_rows = {src: [r for r in rows if r.get("week") == week]
                        for src, rows in def_team_rows.items()}
            week_rows = {s: r for s, r in week_rows.items() if r}
            if not week_rows:
                continue
            for row in reconcile_metric(week_rows, "defense_team"):
                key = (row["player"], week)
                team_slots.setdefault(key, {"team": row["player"], "week": week})
                team_slots[key]["defense_team"] = row

    player_rows = sorted(player_slots.values(),
                         key=lambda r: (r["week"] is None, r["week"], r["player"]))
    team_rows = sorted(team_slots.values(),
                       key=lambda r: (r["week"] is None, r["week"], r["team"]))
    return player_rows, team_rows


