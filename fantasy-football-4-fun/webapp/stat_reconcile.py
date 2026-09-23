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
}

#: Name column per source (mirrors team_profile.html's own name_cols list --
#: each source only ever populates one of these).
_NAME_COL = {
    "player_stats": "player_display_name", "ngs_passing": "player_display_name",
    "ngs_receiving": "player_display_name", "ngs_rushing": "player_display_name",
    "pfr_pass": "pfr_player_name", "pfr_rec": "pfr_player_name",
    "pfr_rush": "pfr_player_name", "sleeper": "player",
}

#: Which dataset(s) actually feed each metric family (the source keys
#: `_METRIC_MAPS[metric]`'s stat dicts reference) -- used by team_profile.py
#: to know which raw rows to hand `reconcile_metric()`.
METRIC_SOURCES = {
    metric: sorted({src for stat_map in stats.values() for src in stat_map})
    for metric, stats in _METRIC_MAPS.items()
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
    `_METRIC_MAPS` in principle but absent this particular game/season is
    dropped from that stat's group rather than claimed. Passing `None`
    (the default) uses every source the map declares, unfiltered.
    """
    stat_map = _METRIC_MAPS.get(metric)
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

    Unknown `metric` (not "passing"/"rushing"/"receiving") returns [].
    """
    stat_map = _METRIC_MAPS.get(metric)
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
