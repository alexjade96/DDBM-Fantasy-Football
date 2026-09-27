"""Single-player aggregator: everything known about one player, across every
data source this app touches.

No function anywhere else in the codebase takes a player_id and returns a
single-player view -- every existing source (draft board, roster detail,
honors, ledgers, every nflref dataset, the ADP board) returns a whole
season/board and leaves filtering to the caller. This module is that
filter, done once, in one place.

Player identifier spaces are NOT unified across sources:
  - Sleeper `player_id` (numeric) -- the anchor id for this whole module,
    and what every league-scoped function (`sleepermetrics.draft`/`metrics`)
    already keys on.
  - nflverse `gsis_id` (format "00-00xxxxx") -- bridges `player_stats`,
    `nextgen_stats`, `injuries`. `sleepermetrics.players()` already carries
    a `gsis_id` column, and `ffadp.identity.resolve(gsis_id=...)` (added
    for player-profile Phase 0) does the id->id lookup.
  - PFR `pfr_player_id` -- bridges `snap_counts`, `pfr_pass/rec/rush/def`.
    No real crosswalk exists anywhere in this codebase (live or cached);
    those two datasets are matched by normalised name + position instead,
    which is lossy (the existing ffadp fallback documents ~2-3% misses in
    practice) and every row sourced this way is labeled best-effort.

Every section degrades independently: a data source that errors, has no
snapshot, or simply doesn't cover this player leaves that section empty
rather than failing the whole call. This mirrors the "never raises" degrade
discipline `nflref.base.NflDataset.fetch()` and `ffadp.board.combine()`
already follow.
"""
from __future__ import annotations

import re
import time

import pandas as pd

from sleepermetrics import draft, metrics
from sleepermetrics.players import players as sleeper_players

# player_profile() calls into 10+ nflref datasets and loops
# ffadp.board.combine() per season, none of which cache a single-player
# result themselves (only the whole-board/whole-dataset fetch underneath is
# snapshot-cached) -- a cold call took 17-30s in practice, measured against
# a real league. Same {key: {"data", "at"}} + TTL shape webapp.app's own
# `_bracket_cache` uses (simpler than league_data()'s stale-while-revalidate
# machinery, appropriate here since this isn't an always-hit-first path the
# whole dashboard depends on). Keyed on (player_id, league_id) since the
# league-scoped section changes the result.
_PROFILE_CACHE: dict[tuple[str, str | None], dict] = {}
_PROFILE_TTL = 900  # 15 min, matches webapp.app.TTL's season-cache window

# How many recent seasons of real-NFL data to pull when there is no league
# history to scope the search from (a bare NFL-Stats-tab lookup, or a
# player this league never rostered). Bounds the number of nflref.load /
# ffadp.board.combine calls for the common case (an active player) rather
# than looping every season back to each dataset's own EARLIEST (2016-2018
# depending on dataset), most of which would return empty for a player who
# has only played a few years.
_DEFAULT_WINDOW = 5

# Real-NFL datasets bridged by the real gsis_id (an exact id match).
_GSIS_DATASETS = ["player_stats", "ngs_passing", "ngs_receiving",
                   "ngs_rushing", "injuries"]
# Datasets only bridged by name + position (no id crosswalk exists).
_PFR_DATASETS = ["snap_counts", "pfr_pass", "pfr_rec", "pfr_rush", "pfr_def"]

# nflverse's three Next Gen Stats releases each carry a genuine `week == 0`
# row per player -- confirmed live (2025/2026): its counting stats (e.g. a
# real case, A.J. Brown 2025: 78 receptions/121 targets/1003 yards) are far
# too large for one game and don't match any single real week's box score,
# and it's the ONLY week nflverse marks a player absent from every other
# real week for (e.g. Chase 2026 week 1 has no ngs_receiving row at all,
# only week 0 and week 2) -- a SEASON-TO-DATE aggregate, not a game. Every
# other real-NFL dataset here (player_stats/injuries/snap_counts/pfr_*) has
# zero week-0 rows in the same live check. `team_profile.py` never hits
# this: it slices a real per-team SCHEDULE by week rather than trusting
# "which weeks exist in the raw data" the way `_game_log`'s week-detection
# does -- filtered out at THIS boundary (not in `_game_log` itself) so
# every downstream reader (the game log AND the flat "Real-NFL history"
# section) sees the same, correct row set.
_NGS_DATASETS = {"ngs_passing", "ngs_receiving", "ngs_rushing"}

# Each dataset's own gsis-id column name differs (see the module docstring
# in nflref/injuries.py vs nflref/nextgen_stats.py) -- this is the one place
# that difference is normalised away.
_GSIS_COL = {
    "player_stats": "player_id",  # nflverse's OWN player_id IS a gsis id
    "ngs_passing": "player_gsis_id",
    "ngs_receiving": "player_gsis_id",
    "ngs_rushing": "player_gsis_id",
    "injuries": "gsis_id",
}
_NAME_COL = {
    "player_stats": "player_display_name",
    "ngs_passing": "player_display_name",
    "ngs_receiving": "player_display_name",
    "ngs_rushing": "player_display_name",
    "injuries": "full_name",
    "snap_counts": "player",
    "pfr_pass": "pfr_player_name",
    "pfr_rec": "pfr_player_name",
    "pfr_rush": "pfr_player_name",
    "pfr_def": "pfr_player_name",
}
# Position column name differs per dataset too (ngs_* uses "player_position",
# every other dataset uses plain "position") -- normalised here for the same
# reason _GSIS_COL/_NAME_COL exist. A dataset absent from this map (PFR's
# own four) has no position column at all; the name-fallback loop below
# only filters by position when this map names a REAL column, same guard
# style the rest of this module already uses.
_POS_COL = {
    "player_stats": "position", "injuries": "position",
    "ngs_passing": "player_position", "ngs_receiving": "player_position",
    "ngs_rushing": "player_position",
}


def _norm_name(name: str | None) -> str:
    """Loose name key, same normalisation ffadp.identity/_norm and
    nflref.summary._norm_name already use independently -- mirrored here
    rather than imported, since neither of those modules exports it as a
    stable public helper.

    `name` can arrive as a pandas NaN (a real float, not None) from a raw
    DataFrame column with missing values -- `(name or "")` does NOT catch
    that (NaN is truthy), and `.lower()` on a float raises. Confirmed live:
    `player_stats`'s own `player_display_name` column has real nulls for
    2025/2026 (18 and 3 rows respectively, an unresolved-player stub in
    nflverse's newer release format), which crashed this function's own
    name-fallback caller (`_real_nfl_history`) the first time that season
    range was actually exercised end to end."""
    if not isinstance(name, str):
        name = ""
    n = name.lower().strip()
    n = re.sub(r"[.’']", "", n)
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _recent_seasons(n: int = _DEFAULT_WINDOW) -> list[str]:
    """The last `n` NFL seasons, most recent first, ending at the current
    league season (`/state/nfl`'s `league_season`, which -- unlike `week`
    -- stays put through the offseason). Falls back to a hardcoded recent
    year on any network failure so this never blocks the rest of the
    profile from rendering."""
    try:
        from sleepermetrics.league import nfl_state
        current = int(nfl_state()["league_season"])
    except Exception:
        current = 2026
    return [str(y) for y in range(current, current - n, -1)]


def _current_season() -> str:
    """The current NFL season alone -- `_recent_seasons(1)[0]`, i.e. the same
    "today's real season" reference `_recent_seasons` already resolves, not
    "whichever season happens to have the most recent row" (an offseason or
    a since-retired player would otherwise mislabel an old season as
    current). Used to split a data source's rows into "this season" (shown
    directly on the profile) vs "past seasons" (behind a drilldown)."""
    return _recent_seasons(1)[0]


def _scope_to_season(rows: list[dict], season: str) -> list[dict]:
    """`rows` (each carrying a `"season"` key, any type Sleeper/nflverse
    happens to use -- int or str) filtered to exactly ONE requested season,
    comparing as strings so `2025 == "2025"`. Order preserved from the
    input. The general form of what used to be a fixed current/past SPLIT
    (`_split_current`, now removed) -- the page's whole "follow-up
    sections" block is re-scoped to whichever season a shared dropdown
    picks (see `scope_profile`), not just today's real NFL season."""
    return [r for r in rows if str(r.get("season")) == str(season)]


def _player_identity(player_id: str) -> dict:
    """{'player_id','player_name','position','team','gsis_id'} for one
    Sleeper player, or a mostly-empty dict (still carrying player_id) for
    an id not in the Sleeper dump -- the profile still assembles from
    whatever league-scoped history exists even then."""
    df = sleeper_players()
    row = df[df["player_id"].astype(str) == str(player_id)]
    if row.empty:
        return {"player_id": str(player_id), "player_name": None,
                "position": None, "team": None, "gsis_id": None}
    r = row.iloc[0]
    # ~22% of Sleeper's own gsis_id values carry a stray leading space
    # (same defect ffadp.identity._build() strips) -- strip here too, since
    # this reads sleepermetrics.players() directly rather than going
    # through that index.
    gsis = str(r["gsis_id"]).strip() if pd.notna(r["gsis_id"]) else None
    return {"player_id": str(player_id), "player_name": r["player_name"],
            "position": r["position"], "team": r["team"], "gsis_id": gsis}


def _real_nfl_history(gsis_id: str | None, name: str | None,
                       position: str | None, seasons: list[str]) -> dict:
    """Real-NFL data across `seasons`, keyed by dataset name -> list of row
    dicts for this player only. gsis-bridged datasets match on the real id
    when available; PFR-bridged ones always fall back to normalised name +
    position (best-effort, flagged as such in the returned shape).

    A GSIS-bridged dataset ALSO falls back to the same name+position match
    when `gsis_id` itself is missing -- a real, confirmed gap: a MAJORITY
    of Sleeper's own player dump has no `gsis_id` at all (verified live:
    3893 of 12229 rows have one; even an active star, Ja'Marr Chase, had
    none in this session's own snapshot), and without this fallback
    `player_stats`/`ngs_*`/`injuries` were ALWAYS empty for any such
    player -- silently dropping TDs/interceptions (neither PFR's datasets
    nor Sleeper's own trimmed usage feed carry those) from the per-game
    game log (`_game_log`) for a majority of players, even though
    `team_profile.py` resolves the identical rows correctly for the same
    player/game via a team+week filter that never needs a gsis_id at all.
    A row found this way is marked `best_effort` too, same as the
    PFR-bridged ones -- it's the identical lossy join, just applied one
    tier higher, only engaged when the real id lookup found nothing."""
    try:
        from webapp.sources.nflref import board as nflref_board
    except Exception:
        return {}

    out: dict[str, dict] = {}
    norm_target = _norm_name(name)
    pos_target = (position or "").upper()

    for ds in _GSIS_DATASETS:
        rows: list[dict] = []
        best_effort = False
        if gsis_id:
            for season in seasons:
                try:
                    df = nflref_board.load(ds, season)
                except Exception:
                    continue
                if ds in _NGS_DATASETS and "week" in df.columns:
                    df = df[df["week"] != 0]
                col = _GSIS_COL.get(ds)
                if col not in df.columns:
                    continue
                hit = df[df[col].astype(str) == str(gsis_id)]
                if not hit.empty:
                    rows.extend(hit.to_dict("records"))
        if not rows and norm_target:
            best_effort = True
            for season in seasons:
                try:
                    df = nflref_board.load(ds, season)
                except Exception:
                    continue
                if ds in _NGS_DATASETS and "week" in df.columns:
                    df = df[df["week"] != 0]
                name_col = _NAME_COL.get(ds)
                if name_col not in df.columns:
                    continue
                cand = df[df[name_col].apply(
                    lambda v: _norm_name(v) == norm_target)]
                pos_col = _POS_COL.get(ds)
                if pos_target and pos_col and pos_col in cand.columns:
                    cand = cand[cand[pos_col].str.upper() == pos_target]
                if not cand.empty:
                    rows.extend(cand.to_dict("records"))
        out[ds] = {"rows": rows, "best_effort": best_effort}

    for ds in _PFR_DATASETS:
        rows = []
        if norm_target:
            for season in seasons:
                try:
                    df = nflref_board.load(ds, season)
                except Exception:
                    continue
                name_col = _NAME_COL.get(ds)
                if name_col not in df.columns:
                    continue
                cand = df[df[name_col].apply(
                    lambda v: _norm_name(v) == norm_target)]
                if pos_target and "position" in cand.columns:
                    cand = cand[cand["position"].str.upper() == pos_target]
                if not cand.empty:
                    rows.extend(cand.to_dict("records"))
        # No id crosswalk exists for PFR data (see module docstring) -- every
        # row here is a name+position guess, never an exact id match.
        out[ds] = {"rows": rows, "best_effort": True}

    return out


# Dataset -> (metric category, display label) for the game-log's raw
# per-category breakdown (see `_game_log`). "injuries" has no metric
# category (it's not a box-score stat) and is handled as its own top-level
# section, same as the flat "Real-NFL history" section always has.
_RAW_SOURCE_LABELS = {
    "ngs_passing": "Next Gen Stats: Passing",
    "ngs_receiving": "Next Gen Stats: Receiving",
    "ngs_rushing": "Next Gen Stats: Rushing",
    "pfr_pass": "PFR advanced: Passing",
    "pfr_rec": "PFR advanced: Receiving",
    "pfr_rush": "PFR advanced: Rushing",
    "pfr_def": "PFR advanced: Defense",
    "snap_counts": "Snap counts",
}
_RAW_SOURCE_CATEGORY = {
    "ngs_passing": "passing", "pfr_pass": "passing",
    "ngs_receiving": "receiving", "pfr_rec": "receiving",
    "ngs_rushing": "rushing", "pfr_rush": "rushing",
    "pfr_def": "defense", "snap_counts": "snap",
}

# Per-dataset raw-column-name -> canonical-stat-name, derived from
# `stat_reconcile._METRIC_MAPS` (the SAME map that already tells the
# reconciled `merged_row` table which raw columns are the same real fact --
# see that module's own docstring) rather than a second, hand-maintained
# alias list that could silently drift from it. Real, confirmed case this
# fixes: `ngs_receiving`'s own raw column for receiving yards is bare
# "yards" (not "receiving_yards"), so before this rename the game log's raw
# "Receiving: raw source data" table showed BOTH a "receiving yards" column
# (Box score's row) AND a separate "yards" column (Next Gen Stats' row),
# each blank for the other source, when they are the identical stat.
# `ngs_passing`/`ngs_rushing` have the same problem (`pass_yards`/
# `pass_touchdowns`, `rush_attempts`/`rush_yards`/`rush_touchdowns`).
# `pfr_*`'s own raw columns (pressure rate, broken tackles, yards before/
# after contact) have no equivalent in any other source at all (see
# stat_reconcile's own docstring: "PFR ... carry mostly PFR-EXCLUSIVE
# advanced stats"), so PFR contributes no aliases here -- only `ngs_*` does.
# Built once at import time, not hardcoded, so a future edit to
# `_METRIC_MAPS` (e.g. a new source column) is picked up automatically
# rather than needing a second manual update here.
def _build_raw_col_aliases() -> dict[str, dict[str, str]]:
    from webapp.stat_reconcile import _METRIC_MAPS
    out: dict[str, dict[str, str]] = {}
    for stats in _METRIC_MAPS.values():
        for canonical, src_cols in stats.items():
            for src, col in src_cols.items():
                if col != canonical:
                    out.setdefault(src, {})[col] = canonical
    return out


_RAW_COL_ALIASES = _build_raw_col_aliases()

# Columns that are pure player IDENTITY (not a stat to compare across
# sources) but use a DIFFERENT key name per dataset, so they don't land in
# `_teamstat_macros.id_cols`/`name_cols` (which key on the exact string
# "position") and so leak through as a second, redundant column -- e.g.
# `player_stats`/`snap_counts` both call it "position" while `ngs_*` calls
# it "player_position", so a game with both a Box-score row and an NGS row
# showed TWO position columns, each blank for the other source, even though
# this whole panel is already scoped to one known player whose position is
# shown in the page header (same repetition `hide_player=true` already
# exists to avoid for the Player name column, immediately above this
# table -- see `_player_game_detail.html`). Renamed to "position" (not
# dropped outright) so it still shows once, since a game log entry can span
# a position change and there's no other single place on this panel stating
# it per-game.
_RAW_IDENTITY_ALIASES = {"player_position": "position"}


def _canonicalize_raw_row(ds: str, row: dict) -> dict:
    """`row` (one dataset's raw columns) with any column this dataset names
    differently from its canonical stat (`_RAW_COL_ALIASES`) or from its
    canonical identity field (`_RAW_IDENTITY_ALIASES`) renamed to that
    canonical key -- so `source_stat_table`/`season_source_table`'s own
    union-of-columns render (_teamstat_macros.html) lines up the same real
    fact under ONE column regardless of which source's row is naming it. A
    row already using the canonical name for a given stat is untouched
    (nothing to rename).

    Also scrubs pandas NaN to `None`, same fix `_week_rows` already applies
    on the per-game reconciliation path -- real, confirmed case: PFR's
    `pfr_rush`/`pfr_rec` rows carry the OTHER role's own broken-tackle
    column (`receiving_broken_tackles` on a rushing row, `rushing_broken_
    tackles` on a receiving row) as NaN when a player has no line in that
    other role, and `_teamstat_macros.cell()`'s own `v is none` guard does
    NOT catch a pandas NaN float (`nan is not None` is True), rendering the
    literal text "nan". `_game_log`'s own per-game path happened to dodge
    this by calling `_week_rows` (which already scrubs) BEFORE this
    function, but `real_nfl_by_category`'s season-wide path canonicalizes
    directly off `real_nfl`'s raw, un-scrubbed rows with no such step first
    -- scrubbing HERE instead of relying on caller order fixes both paths
    at their one shared choke point rather than duplicating the scrub in
    two places (and fixes a real, pre-existing bug in the OLD flat
    per-dataset "Real-NFL history" table too, which read this exact NaN
    unguarded before this function's rename step even existed)."""
    def clean(v):
        try:
            return None if v is not None and pd.isna(v) else v
        except (TypeError, ValueError):
            return v
    aliases = {**_RAW_IDENTITY_ALIASES, **_RAW_COL_ALIASES.get(ds, {})}
    return {aliases.get(k, k): clean(v) for k, v in row.items()}


# Which raw categories share real cross-source overlap, for the season-wide
# "Real-NFL history" section's own reconciliation (see
# `real_nfl_by_category`) -- the SAME split `_RAW_SOURCE_CATEGORY` already
# encodes per dataset, grouped the other way round (category -> its
# datasets) since this function builds one merged table PER CATEGORY rather
# than iterating per dataset. `injuries` and `snap_counts` are deliberately
# absent: `injuries` has exactly one source in this pipeline (nothing to
# merge against) and `snap_counts` likewise (see `stat_reconcile`'s own
# docstring: "Defense (pfr_def) and Snap counts (snap_counts) have no
# second source at all") -- both stay as their own single, un-merged
# section, unchanged from before this function existed.
_REAL_NFL_CATEGORY_DATASETS = {
    "passing": ["player_stats", "ngs_passing", "pfr_pass"],
    "rushing": ["player_stats", "ngs_rushing", "pfr_rush"],
    "receiving": ["player_stats", "ngs_receiving", "pfr_rec"],
}


def real_nfl_by_category(real_nfl: dict) -> dict[str, list[dict]]:
    """The season-scoped `real_nfl` dict (see `scope_profile`), regrouped
    for the "Real-NFL history" section into ONE table per overlapping
    category (passing/rushing/receiving -- see `_REAL_NFL_CATEGORY_DATASETS`)
    instead of one table per SOURCE, matching what `_game_log`'s own
    `raw_by_category` already does for a single game, just at the whole-
    season, multiple-week grain instead of one week. User request: the same
    "integrate all major metrics into a single table... add a column
    stating the data source... leave blank for non-comparable columns"
    treatment already applied to the per-game drilldown, extended to this
    flat season-wide section.

    Returns `{category: [{"week": w, "source": label, "best_effort": bool,
    **canonicalized_row}, ...]}`, sorted by week then by each category's own
    dataset declaration order (`_REAL_NFL_CATEGORY_DATASETS[category]`, so
    "Box score" always leads a given week's group, matching the per-game
    table's own "Box score" first convention) -- a flat list of rows rather
    than nested per-week groups, since the template's own `season_source_
    table` macro (_teamstat_macros.html) already knows how to union columns
    and render one row per entry; the "week" key rides along as an ordinary
    column so it appears in the rendered table (unlike the per-game
    version, where the week is stated once by the parent game row and so is
    dropped via `game_scoped`). `best_effort` carries over PER ROW from
    that row's own source dataset (`real_nfl[ds]["best_effort"]`, see
    `_real_nfl_history`'s own docstring) -- a category can genuinely mix
    id-verified rows (player_stats/ngs_*, when this player has a gsis_id)
    with name-matched ones (pfr_*, always best-effort; or any dataset when
    this player has no gsis_id at all), so the flag is a per-row fact here,
    not a whole-category one, unlike the old per-dataset table's single
    caption note.

    `player_stats` rows are split into passing/rushing/receiving buckets
    first (`team_profile._split_player_stats`, the SAME function
    `_game_log` already uses for this) since one `player_stats` row spans
    all three metric families -- a receiving table must not show a
    passing-only player's zeroed-out targets/receptions row, the same
    "bucket by nonzero value" rule that function already documents.

    Each dataset's own columns are renamed to their canonical name first
    (`_canonicalize_raw_row`) -- the exact fix this function exists for:
    without it, Next Gen Stats' `rush_yards`/`yards`/`pass_yards` and its
    own `player_position` would each render as a SEPARATE, mostly-blank
    column instead of lining up under `player_stats`'s "rushing_yards"/
    "receiving_yards"/"passing_yards"/"position"."""
    from webapp import team_profile as tp

    player_stats_by_bucket: dict[str, dict[int, dict]] = {}
    ps_data = real_nfl.get("player_stats") or {}
    ps_rows = ps_data.get("rows", [])
    ps_best_effort = bool(ps_data.get("best_effort"))
    if ps_rows:
        canon_rows = [_canonicalize_raw_row("player_stats", r) for r in ps_rows]
        for bucket, rows_b in tp._split_player_stats(canon_rows).items():
            player_stats_by_bucket[bucket] = {r["week"]: r for r in rows_b if r.get("week") is not None}

    out: dict[str, list[dict]] = {}
    for category, datasets in _REAL_NFL_CATEGORY_DATASETS.items():
        # (source_rank, week, row) so the final sort (below) can order by
        # week first and then by each dataset's OWN declared position in
        # `datasets` (Box score always leads a given week's group) without
        # a second reverse lookup from label back to dataset name.
        tagged: list[tuple[int, int, dict]] = []
        for rank, ds in enumerate(datasets):
            if ds == "player_stats":
                by_week = player_stats_by_bucket.get(category, {})
                label, best_effort = "Box score", ps_best_effort
            else:
                d = real_nfl.get(ds) or {}
                rows = [_canonicalize_raw_row(ds, r) for r in d.get("rows", [])]
                by_week = {r["week"]: r for r in rows if r.get("week") is not None}
                label, best_effort = _RAW_SOURCE_LABELS.get(ds, ds), bool(d.get("best_effort"))
            for week, row in by_week.items():
                tagged.append((rank, week, {"week": week, "source": label,
                                            "best_effort": best_effort, **row}))
        if tagged:
            tagged.sort(key=lambda t: (t[1], t[0]))
            out[category] = [entry for _rank, _week, entry in tagged]
    return out


# A SELECT FEW position-relevant columns for the game log's own `.dt-head`
# (user request) -- deliberately a small subset of team_profile's own full
# `_OFF_POSITION_COLS`/`_DEF_PLAYER_COLS` (the game's expandable detail
# already renders that full breakdown via the same `merged_row` -- see
# `_player_game_detail.html`), just enough for a quick-glance row: (merged_
# row category, key, header label). Reads straight off `game["merged_row"]`
# (the SAME reconciled dict `_player_game_detail.html` already renders),
# not a second data pull. A key absent from a game's own `merged_row` (the
# player didn't play, or that source didn't resolve) shows a dash, same
# convention as every other absent-stat cell on this page. Kickers/`K` and
# any other position `_game_log` doesn't build a real `merged_row` for get
# no extra columns at all -- Season/Week/Opp is all they show.
#
# Deliberately REAL box-score stats only, no fantasy-derived number
# (points, PPG) -- a `ppr_pts` column (off player_stats' own
# fantasy_points_ppr) briefly lived here and was removed on user request:
# fantasy scoring is a SEPARATE concern (this section is "what actually
# happened in the game"), and belongs in its own dedicated
# fantasy-comparison section later, not folded into the real-stat game
# log. Don't reintroduce a fantasy_points/fantasy_points_ppr column here.
_LOG_STAT_COLS = {
    "QB": [("passing", "completions", "Cmp"), ("passing", "attempts", "Att"),
           ("passing", "passing_yards", "Yds"), ("passing", "passing_tds", "TD"),
           ("passing", "interceptions", "INT")],
    "RB": [("rushing", "carries", "Car"), ("rushing", "rushing_yards", "Rush Yds"),
           ("rushing", "rushing_tds", "TD"), ("receiving", "targets", "Tgt"),
           ("receiving", "receptions", "Rec"), ("receiving", "receiving_yards", "Rec Yds")],
    "WR": [("receiving", "targets", "Tgt"), ("receiving", "receptions", "Rec"),
           ("receiving", "receiving_yards", "Yds"), ("receiving", "receiving_tds", "TD")],
    "TE": [("receiving", "targets", "Tgt"), ("receiving", "receptions", "Rec"),
           ("receiving", "receiving_yards", "Yds"), ("receiving", "receiving_tds", "TD")],
}
# Defense (DL/LB/DB alike, same shared column set `team_profile._DEF_PLAYER_
# COLS` uses -- PFR draws no line between "pass rush" and "coverage" stats
# per position, see that constant's own comment) reads off `pfr_def`
# instead of a passing/rushing/receiving category.
_LOG_DEF_STAT_COLS = [
    ("pfr_def", "def_sacks", "Sack"), ("pfr_def", "def_tackles_combined", "Tkl"),
    ("pfr_def", "def_ints", "INT"),
]


def _log_stat_cols(position: str | None) -> list[tuple[str, str, str]]:
    """The game log's own header-column spec for this player's position --
    see `_LOG_STAT_COLS`/`_LOG_DEF_STAT_COLS` above. Empty for a position
    with no spec (K, or anything `_game_log` doesn't build a real
    `merged_row` for)."""
    if position in ("DL", "LB", "DB", "DE", "DT", "CB", "S"):
        return _LOG_DEF_STAT_COLS
    return _LOG_STAT_COLS.get(position or "", [])


def _log_stat_values(merged_row: dict, cols: list[tuple[str, str, str]]) -> list:
    """Pull each `(category, key, label)` column's value out of a game's own
    `merged_row` (see `_LOG_STAT_COLS`) -- `None` when that category never
    resolved for this game (e.g. a QB's `passing` sub-dict is `None` on a
    week he didn't play) or the specific key is absent from it."""
    out = []
    for cat, key, _label in cols:
        src = merged_row.get(cat) if merged_row else None
        out.append(src.get(key) if src else None)
    return out


# Sleeper's own team abbreviation diverges from nflverse's for exactly one
# still-active franchise (verified live: Sleeper's player dump uses "LAR"
# for the Rams, every nflverse dataset here -- player_stats/snap_counts/
# schedules alike -- uses "LA"); Sleeper's legacy "OAK" (pre-Las-Vegas
# Raiders) never appears in a current player's `team` field, only in old
# roster history this module doesn't read. Only applied to `identity["team"
# ]`, the LAST-resort fallback in `_game_opponent`'s team lookup below (see
# that call site) -- player_stats'/snap_counts' own team columns are
# already in nflverse's own format and need no translation.
_SLEEPER_TEAM_ALIAS = {"LAR": "LA"}


def _game_opponent(team: str | None, season: str, week: int) -> str | None:
    """The real opposing team abbreviation for `team` in this (season,
    week), off the actual NFL schedule (`nflref.schedule_grid`) -- NOT
    `snap_counts`'/`pfr_*`'s own `opponent` column, which is only as
    reliable as those two PFR-bridged, name-matched datasets themselves
    (a real, confirmed gap: KC 2026 had zero snap_counts rows for the whole
    season, see `team_profile._defense_position_groups`'s own docstring).
    The real schedule resolves for ANY team/week regardless of which
    per-player datasets happened to have rows, so this works even when
    every other per-game stat is a dash. `team` should be the player's OWN
    team for this specific week (a traded player's team can change
    mid-season), not `identity["team"]` (that's only his CURRENT team).
    None when the schedule doesn't resolve or `team` itself is unknown."""
    if not team:
        return None
    try:
        from webapp.sources.nflref import schedule_grid
    except Exception:
        return None
    try:
        grid = schedule_grid(season, week=week, team=team)
    except Exception:
        return None
    if grid.empty:
        return None
    row = grid.iloc[0]
    away, home = row.get("away_team"), row.get("home_team")
    if away == team:
        return home
    if home == team:
        return away
    return None


def _week_rows(rows: list[dict], season: str, week: int) -> list[dict]:
    """`rows` filtered to one exact (season, week) -- both compared, not
    week alone, since two different seasons share week numbers (a player's
    real week-1-2024 and week-1-2025 rows would otherwise collide into one
    bucket). Also scrubs pandas NaN to `None` (`_real_nfl_history`'s own
    `.to_dict("records")` calls do NOT do this -- unlike `team_profile.
    _clean_records`, which every row team_profile.py's own reconciliation
    pipeline flows through -- so a row reaching THIS module's reconciliation
    functions for the first time here would otherwise carry a raw NaN
    straight into `stat_reconcile`/`_merge_offense_players`'s output,
    confirmed live: PFR's `pfr_rec` rows carry `rushing_broken_tackles` as
    NaN for a receiver with no rushing PFR line that game, which
    `_attach_pfr_extra` flattens verbatim with no `is not None` guard of its
    own to catch it. Scrubbing here, not in `_real_nfl_history` itself,
    keeps the EXISTING raw tables' own display unchanged -- this function
    is only used on the reconciliation path, not the raw-table path."""
    def clean(v):
        try:
            return None if v is not None and pd.isna(v) else v
        except (TypeError, ValueError):
            return v
    return [{k: clean(v) for k, v in r.items()} for r in rows
           if str(r.get("season")) == str(season) and str(r.get("week")) == str(week)]


def _player_week_role_rows(season: str, week: int, real_nfl: dict) -> dict[str, list[dict]]:
    """This player's own already-pulled `real_nfl[ds]["rows"]` (see
    `_real_nfl_history`), sliced down to ONE game and bucketed into the
    `role_rows` shape `team_profile._grouped_metric_stats` expects
    (`"player_stats_passing"`, `"ngs_passing"`, `"pfr_pass"`, ...) --
    mirrors exactly how `team_profile._attach_week_stats` builds the same
    shape for a whole team, just starting from this player's own
    single-player rows instead of a team-wide pull.

    `player_stats` is role-split via `team_profile._split_player_stats`
    (it's ONE comprehensive box-score row per week covering all three
    metric families, same as it is for a team); every other dataset in
    `real_nfl` already IS one metric family (`ngs_passing` is only ever
    passing, etc.), so those pass straight through under their own dataset
    name -- the same "everything else passes through unchanged" rule
    `_attach_week_stats`'s own `else: role_rows[ds] = hit` branch follows."""
    from webapp import team_profile as tp

    role_rows: dict[str, list[dict]] = {}
    player_stats_rows = _week_rows(
        (real_nfl.get("player_stats") or {}).get("rows", []), season, week)
    if player_stats_rows:
        for bucket, rows_b in tp._split_player_stats(player_stats_rows).items():
            role_rows[f"player_stats_{bucket}"] = rows_b

    for ds in ("ngs_passing", "ngs_receiving", "ngs_rushing",
              "pfr_pass", "pfr_rec", "pfr_rush", "pfr_def"):
        hit = _week_rows((real_nfl.get(ds) or {}).get("rows", []), season, week)
        if hit:
            role_rows[ds] = hit

    snap_rows = _week_rows(
        (real_nfl.get("snap_counts") or {}).get("rows", []), season, week)
    if snap_rows:
        for bucket, rows_b in tp._split_snap_counts(snap_rows).items():
            role_rows[f"snap_counts_{bucket}"] = rows_b

    return role_rows


def _sleeper_player_weeks(player_id: str, name: str, seasons: list[str],
                          verified_weeks: set[tuple[str, int]]) -> list[dict]:
    """This ONE player's per-week stat lines from Sleeper's own weekly feed
    (`sleepermetrics.nflstats.raw_week`), reshaped to the same
    `{"player", "week", "season", <stat keys>}` row shape every other
    source here uses -- the single-player sibling of
    `team_profile._sleeper_week_rows`. Simpler than that team-wide version:
    `raw_week` is already keyed by Sleeper `player_id`, so no roster-wide
    name lookup is needed, just a direct dict `.get(player_id)` per week.

    `verified_weeks` (the caller's own union of every OTHER dataset's real
    (season, week) pairs for this player -- see `_game_log`) gates which
    weeks Sleeper's line is trusted for -- same mid-season-accuracy guard
    `team_profile._sleeper_week_rows` uses (a week Sleeper reports that no
    other source corroborates has no independently-verified ground truth
    this player actually took the field, so it's excluded rather than
    trusted blind). Deliberately NOT scoped to `player_stats` alone (an
    earlier version of this function was, and it silently produced ZERO
    verified weeks -- and so an EMPTY game log -- for any player whose
    Sleeper record has no `gsis_id`, which `player_stats`/`ngs_*` require
    for that player to resolve at all; a real, confirmed gap affecting a
    majority of Sleeper's own player dump, e.g. Ja'Marr Chase). Any
    dataset this player's OWN rows resolved through (PFR name-matched
    included) counts as corroboration. Degrades to `[]` on any failure."""
    try:
        from sleepermetrics.nflstats import raw_week
    except Exception:
        return []
    if not verified_weeks:
        return []

    out: list[dict] = []
    for season in seasons:
        for wk in range(1, 19):
            if (str(season), wk) not in verified_weeks:
                continue
            try:
                lines = raw_week(season, wk)
            except Exception:
                continue
            line = (lines or {}).get(str(player_id))
            if not line:
                continue
            out.append({"player": name, "week": wk, "season": season, **line})
    return out


def _player_route_weeks(gsis_id: str | None,
                        seasons: list[str]) -> tuple[list[dict], set[str]]:
    """This ONE player's own rows from `route_participation`, plus which of
    `seasons` had NOTHING at all in that dataset (see
    `team_profile._team_route_rows`'s identical `unavailable_seasons`
    concept) -- simpler than the team-wide version since route rows are
    already keyed by `gsis_id`, no roster-gating needed.

    The "is this season's data even published yet" check runs regardless
    of whether `gsis_id` is known -- it's a fact about the SEASON
    (nflverse hasn't released `pbp_participation` for it), not about this
    player, so a player missing a gsis_id (a real, common gap -- see
    `_real_nfl_history`'s own header comment) still gets the correct "not
    yet available" note instead of silently showing nothing at all, which
    an earlier version of this function did (it returned `([], set())`
    outright for any player with no gsis_id, so `route_unavailable` was
    always False for such a player even in a season where the dataset was
    genuinely empty for EVERYONE). Only the per-player ROW lookup itself
    is skipped without a gsis_id, since route_participation has no
    name-matched fallback path (unlike the PFR-bridged datasets)."""
    try:
        from webapp.sources.nflref import board as nflref_board
    except Exception:
        return [], set()

    from webapp import team_profile as tp

    rows: list[dict] = []
    unavailable: set[str] = set()
    for season in seasons:
        try:
            df = nflref_board.load("route_participation", season)
        except Exception:
            df = None
        if df is None or df.empty:
            unavailable.add(str(season))
            continue
        if not gsis_id:
            continue
        hit = df[df["gsis_id"].astype(str) == str(gsis_id)]
        if not hit.empty:
            rows.extend(tp._clean_records(hit))
    return rows, unavailable


def _game_log(identity: dict, real_nfl: dict, seasons: list[str]) -> list[dict]:
    """One entry per week this player has real box-score data for, each a
    RECONCILED summary row -- the exact same shape/values
    `team_profile._merge_offense_players`/`_merge_defense_players` already
    produce for this player on the team page's own per-game drilldown,
    reused here unmodified (see this module's own header: same source data,
    same reconciliation code, just called for one player instead of one
    team). This is the player page's new primary per-game view; the
    existing flat `real_nfl` raw tables stay exactly as they are (see
    `_build_profile`), now also grouped per-game/per-category as
    `raw_by_category` on each entry here for the page's expandable detail.

    A defensive player (position in `team_profile._DEF_GROUP_OF`'s target
    set, i.e. resolves to DL/LB/DB) goes through `_merge_defense_players`
    instead -- PFR is defense's only source (see `stat_reconcile`'s own
    docstring: "Defense ... have no second source at all"), so there is no
    reconciliation step for a defensive player's game log, only the merge.
    """
    from webapp import team_profile as tp

    player_id = identity.get("player_id")
    gsis_id = identity.get("gsis_id")
    name = identity.get("player_name")
    position = identity.get("position")
    if not name:
        return []

    # Every (season, week) ANY of this player's own already-resolved
    # datasets has a real row for -- the game log's own row set. Built
    # from EVERY dataset in `real_nfl`, not just `player_stats`: a real,
    # confirmed gap is that `player_stats`/`ngs_*`/`injuries` require a
    # gsis_id to resolve at all, and a majority of Sleeper's own player
    # dump has none (verified live: Ja'Marr Chase, an active star, has
    # `gsis_id = None` in this session's own snapshot) -- for such a
    # player only the PFR-bridged datasets (`snap_counts`/`pfr_*`, name+
    # position matched) resolve anything, and an earlier version of this
    # function that only trusted `player_stats` for week-detection silently
    # produced an EMPTY game log for exactly these players. Same "union of
    # every source's weeks" idea `team_profile._attach_week_stats` gets for
    # free from iterating a team's SCHEDULE (no per-player schedule exists
    # here, so it's built directly from the data instead).
    weeks_seen: set[tuple[str, int]] = set()
    for ds_data in real_nfl.values():
        for r in ds_data.get("rows", []):
            if r.get("week") is not None:
                weeks_seen.add((str(r.get("season")), int(r["week"])))

    sleeper_rows = _sleeper_player_weeks(player_id, name, seasons, weeks_seen)
    weeks_seen |= {(str(r["season"]), r["week"]) for r in sleeper_rows}
    route_rows, route_unavailable_seasons = _player_route_weeks(gsis_id, seasons)

    is_defense = position in ("DL", "LB", "DB", "DE", "DT", "CB", "S")

    out: list[dict] = []
    for season, wk in sorted(weeks_seen, key=lambda sw: (sw[0], sw[1])):
        role_rows = _player_week_role_rows(season, wk, real_nfl)
        sleeper_hit = _week_rows(sleeper_rows, season, wk)
        if sleeper_hit:
            for bucket, rows_b in tp._split_sleeper_stats(sleeper_hit).items():
                role_rows[f"sleeper_{bucket}"] = rows_b
        route_hit = _week_rows(route_rows, season, wk)
        if route_hit:
            role_rows["route_participation"] = route_hit

        if is_defense:
            stats = {"pfr_def": role_rows.get("pfr_def") or [],
                     "snap_counts_defense": role_rows.get("snap_counts_defense") or []}
            players = tp._merge_defense_players(stats, [], abbr="")
        else:
            stats = tp._grouped_metric_stats(role_rows)
            stats["snap_counts_offense"] = role_rows.get("snap_counts_offense") or []
            stats["route_participation"] = role_rows.get("route_participation") or []
            players = tp._merge_offense_players(
                stats, [{"player": name, "position": position}] if position else [])
        merged_row = players.get(tp._norm_name(name))
        if not merged_row:
            continue

        # Each dataset's own rows are renamed to their CANONICAL column names
        # (`_canonicalize_raw_row`) before being stored here -- so
        # `source_stat_table`'s union-of-columns render
        # (_teamstat_macros.html) lines up e.g. Next Gen Stats' bare "yards"
        # under the same "receiving yards" column Box score's row uses,
        # instead of showing both as separate, half-blank columns. "Box
        # score" (player_stats) is already the canonical naming (see
        # `stat_reconcile._METRIC_MAPS`'s own "player_stats" columns, which
        # match every canonical key 1:1), so it needs no renaming, but is
        # still routed through the SAME function for the identity-column
        # alias (`player_position` -> `position` has no player_stats side to
        # rename, this is just "no-op for this dataset").
        raw_by_category: dict[str, list[tuple[str, list[dict]]]] = {}
        for ds, label in _RAW_SOURCE_LABELS.items():
            hit = _week_rows((real_nfl.get(ds) or {}).get("rows", []), season, wk)
            if hit:
                cat = _RAW_SOURCE_CATEGORY[ds]
                hit = [_canonicalize_raw_row(ds, r) for r in hit]
                raw_by_category.setdefault(cat, []).append((label, hit))
        box_hit = _week_rows(
            (real_nfl.get("player_stats") or {}).get("rows", []), season, wk)
        if box_hit:
            box_hit = [_canonicalize_raw_row("player_stats", r) for r in box_hit]
            for bucket, rows_b in tp._split_player_stats(box_hit).items():
                raw_by_category.setdefault(bucket, []).insert(0, ("Box score", rows_b))

        # This player's OWN team for THIS week -- not identity["team"]
        # (that's only his CURRENT team, wrong for a traded player's past
        # games) -- read off whichever source resolved for this week,
        # player_stats first (most reliably available, see the gsis-
        # fallback fix above), falling back to the PFR-bridged snap_counts
        # rows, and finally the player's current team as a last resort
        # (still usually right -- most players never change teams).
        team = None
        if box_hit:
            team = box_hit[0].get("recent_team")
        if not team:
            snap_hit = role_rows.get("snap_counts_offense") or role_rows.get("snap_counts_defense")
            if snap_hit:
                team = snap_hit[0].get("team")
        if not team:
            team = _SLEEPER_TEAM_ALIAS.get(identity.get("team"), identity.get("team"))
        opponent = _game_opponent(team, season, wk)

        stat_cols = _log_stat_cols(position)
        stat_values = _log_stat_values(merged_row, stat_cols)

        route_summary = None
        if route_hit:
            summarized = tp._route_summary_rows({"route_participation": route_hit})
            route_summary = summarized[0] if summarized else None

        out.append({
            "season": season, "week": wk, "position": position,
            "opponent": opponent,
            "stat_cols": stat_cols, "stat_values": stat_values,
            "merged_row": merged_row, "raw_by_category": raw_by_category,
            "route_summary": route_summary,
            "route_unavailable": season in route_unavailable_seasons,
        })
    return out


def _adp_history(sleeper_id: str, seasons: list[str],
                  scoring: str = "ppr") -> list[dict]:
    """This player's row from ffadp.board.combine() for each season in
    `seasons` that has any ADP data at all -- multi-year draft-consensus
    history. League-agnostic (ADP is platform-wide, not per-league), though
    `scoring` should match the profile's league format when one is known."""
    try:
        from webapp.sources.ffadp import board as ffadp_board
    except Exception:
        return []
    out = []
    for season in seasons:
        try:
            combined = ffadp_board.combine(season, scoring=scoring)
        except Exception:
            continue
        for row in combined.get("rows", []):
            if str(row.get("sleeper_id")) == str(sleeper_id):
                out.append({"season": season, **row})
                break
    return out


def _percentile_profile_for(player_id: str, position: str | None,
                            season: str) -> dict | None:
    """One thin, patchable seam around `nflref.summary.percentile_profile`
    (module-level so tests can `monkeypatch.setattr(pp, ...)` it exactly like
    `_real_nfl_history`/`_adp_history` already are, rather than reaching
    through a function-local import) -- see those two for the established
    convention this mirrors. `source="sleeper"` since the leaderboard it
    reads already carries the real Sleeper `player_id` directly (no
    name/position fallback needed, unlike the PFR-bridged datasets
    elsewhere in this module). Never raises; `None` on any failure or when
    `position` is unknown.
    """
    if not position:
        return None
    try:
        from webapp.sources.nflref import summary as nflref_summary
        return nflref_summary.percentile_profile(
            season, position, player_id, source="sleeper")
    except Exception:
        return None


def _all_season_profiles(player_id: str, position: str | None,
                         seasons: list[str]) -> dict:
    """Every season's FULL percentile profile (all stat columns, not just
    points), keyed by season string -- the radar-overlay chart's input.
    A season with no leaderboard row for this player (never played, or the
    position is unknown) is simply absent from the returned dict rather
    than erroring; `plots.plot_player_radar` picks its focus season from
    whatever keys survive.

    League-free (Sleeper's own weekly-stat leaderboard, not this league's
    roster history), so it works even with no league loaded.
    """
    out = {}
    for season in seasons:
        prof = _percentile_profile_for(player_id, position, season)
        if prof:
            out[season] = prof
    return out


def _league_history(player_id: str, seasons_map: dict) -> dict:
    """This player's history within one league, across every season in
    `seasons_map` ({season_str: Season}, from webapp.app.league_data()).
    Each key degrades independently -- a season with no draft, no trades
    fought over this player, etc. contributes an empty entry rather than
    erroring the whole call."""
    draft_picks: list[dict] = []
    honors: list[dict] = []
    trade_stints: list[dict] = []
    waiver_rows: list[dict] = []
    splits_by_season: dict[str, list[dict]] = {}

    for season, s in seasons_map.items():
        try:
            db = draft.draft_board(s)
            hit = db[db["player_id"].astype(str) == str(player_id)]
            if not hit.empty:
                row = hit.iloc[0].to_dict()
                row["season"] = season
                draft_picks.append(row)
        except Exception:
            pass

        try:
            for h in metrics.player_honors(s):
                if str(h.get("player_id")) == str(player_id):
                    row = dict(h)
                    row["season"] = season
                    row["managers"] = sorted(row.get("managers", []) or [])
                    honors.append(row)
        except Exception:
            pass

        try:
            for t in metrics.trade_player_rates(s):
                if str(t.get("player_id")) == str(player_id):
                    row = dict(t)
                    row["season"] = season
                    trade_stints.append(row)
        except Exception:
            pass

        try:
            wl = metrics.waiver_ledger(s, top_n=None)
            hit = wl[wl["player_id"].astype(str) == str(player_id)]
            if not hit.empty:
                rows = hit.to_dict("records")
                for r in rows:
                    r["season"] = season
                waiver_rows.extend(rows)
        except Exception:
            pass

        try:
            splits = draft._player_team_splits(s, {player_id})
            rows = splits.get(str(player_id)) or splits.get(player_id) or []
            if rows:
                splits_by_season[season] = rows
        except Exception:
            pass

    return {
        "draft_picks": draft_picks,
        "honors": honors,
        "trade_stints": trade_stints,
        "waiver_rows": waiver_rows,
        "roster_splits": splits_by_season,
    }


def _build_profile(player_id: str, league_id: str | None = None) -> dict:
    """The real aggregation logic -- see `player_profile()` (the cached
    public entry point) for the full contract."""
    identity = _player_identity(player_id)
    real_nfl_seasons = _recent_seasons()

    league_section = None
    if league_id:
        try:
            from webapp.app import league_data
            seasons_map = league_data(league_id).get("seasons", {})
        except Exception:
            seasons_map = {}
        league_section = _league_history(player_id, seasons_map)
        league_seasons = sorted(
            {p["season"] for p in league_section["draft_picks"]}
            | set(league_section["roster_splits"])
        )
        if league_seasons:
            real_nfl_seasons = sorted(
                set(real_nfl_seasons) | set(league_seasons), reverse=True)

    real_nfl = _real_nfl_history(
        identity.get("gsis_id"), identity.get("player_name"),
        identity.get("position"), real_nfl_seasons)
    adp = _adp_history(player_id, real_nfl_seasons)
    game_log = _game_log(identity, real_nfl, real_nfl_seasons)

    # Every season's full percentile profile, for the radar overlay -- the
    # chart itself defaults its focus to the most recent season with data
    # (same "most recent scoring season" convention already established for
    # the playoff-splice chart's rank badges), overridable via the page's
    # shared season dropdown (see `scope_profile`). `percentile_profile`
    # stays as the focused (most recent) season's own dict, for the stat
    # table rendered below the chart.
    season_profiles = _all_season_profiles(
        player_id, identity.get("position"), real_nfl_seasons)
    available_seasons = sorted(season_profiles, reverse=True)
    focus_season = available_seasons[0] if available_seasons else None
    percentile_profile = season_profiles.get(focus_season) if focus_season else None

    # This dict is the FULL, UNSCOPED aggregation -- cached as-is (see
    # `player_profile()`), no season split baked in. `scope_profile()`
    # (below) does the actual per-season filtering, called fresh on every
    # request (a cheap in-memory filter, not a data pull) so the whole
    # page's "follow-up sections" can re-scope to whatever season a single
    # shared dropdown picks, not just today's real NFL season.
    return {
        "identity": identity,
        "seasons_covered": real_nfl_seasons,
        "real_nfl": real_nfl,
        "game_log": game_log,
        # This player's own header-column spec (see `_log_stat_cols`) --
        # computed once here rather than read off `game_log[0]` per request,
        # since an EMPTY game log would otherwise have nothing to read the
        # spec from at all (and every entry carries the identical spec
        # regardless, so re-deriving it per game would be redundant).
        "game_log_stat_cols": _log_stat_cols(identity.get("position")),
        "adp_history": adp,
        "current_season": _current_season(),
        "league": league_section,
        "percentile_profile": percentile_profile,
        "season_profiles": season_profiles,
        "available_seasons": available_seasons,
        "focus_season": focus_season,
    }


def scope_profile(profile: dict, season: str | None) -> dict:
    """The `player_profile()` result, re-scoped to exactly ONE season for
    display -- the season dropdown's own filter, run fresh per request
    (cheap: this only filters already-fetched lists, no data pull) so
    every "follow-up section" (game log, real-NFL history, league history,
    ADP history) shows that one season's rows, all in lockstep, rather
    than each defaulting independently to today's real NFL season.

    `season=None` (or a season this player has no data for at all) falls
    back to `profile["current_season"]` -- the page's own default on first
    load, same as the old fixed "current season" split this replaced.
    Returns the SAME KEYS `player_profile.html` reads as flat top-level
    context (`real_nfl`, `real_nfl_categories`, `game_log`, `adp_history`,
    `league_history`), values replaced with this season's rows only --
    `real_nfl_categories` (see `real_nfl_by_category`) is the "Real-NFL
    history" section's own per-category reconciliation, built fresh here
    from the just-scoped `real_nfl` rather than cached on the unscoped
    profile, since it depends on the season filter having already run. The
    template's own per-dataset "current_rows"/"past_rows" and *_current/
    *_past drilldown reads are gone along with the drilldowns themselves
    (one dropdown now covers every season, so there's no separate "past
    seasons" list to render)."""
    seasons_covered = profile.get("seasons_covered") or []
    if not season or season not in seasons_covered:
        season = profile.get("current_season")

    real_nfl = {
        ds: {**ds_data, "rows": _scope_to_season(ds_data.get("rows", []), season)}
        for ds, ds_data in (profile.get("real_nfl") or {}).items()
    }
    # The "Real-NFL history" section's own per-category reconciliation (see
    # `real_nfl_by_category`'s own docstring) -- built fresh here, same as
    # everything else in this function, since it depends on `real_nfl`
    # already being scoped to this one season.
    real_nfl_categories = real_nfl_by_category(real_nfl)
    game_log = _scope_to_season(profile.get("game_log") or [], season)
    adp = _scope_to_season(profile.get("adp_history") or [], season)

    league_section = profile.get("league")
    league_scoped = None
    if league_section is not None:
        league_scoped = {
            "draft_picks": _scope_to_season(league_section["draft_picks"], season),
            "trade_stints": _scope_to_season(league_section["trade_stints"], season),
            "waiver_rows": _scope_to_season(league_section["waiver_rows"], season),
            "roster": league_section["roster_splits"].get(season) or [],
        }

    # The percentile radar's own per-season profile -- `available_seasons`
    # (this dict's own key set) can be a SUBSET of `seasons_covered` (a
    # season with real box-score/game-log data but no leaderboard row for
    # this player, e.g. a rookie season or a position Sleeper's own
    # leaderboard doesn't rank), so `season` here is simply whichever one
    # the dropdown picked -- `.get()` degrades to None (no radar/table for
    # that season, same as any other absent-data case) rather than forcing
    # a fallback to a DIFFERENT season than every other section is showing.
    percentile_profile = (profile.get("season_profiles") or {}).get(season)

    return {
        "season_scope": season,
        "real_nfl": real_nfl,
        "game_log": game_log,
        "real_nfl_categories": real_nfl_categories,
        "adp_history": adp,
        "league_scoped": league_scoped,
        "percentile_profile": percentile_profile,
    }


def player_profile(player_id: str, league_id: str | None = None,
                    fresh: bool = False) -> dict:
    """Everything known about one player, cached for `_PROFILE_TTL` seconds.

    Always includes identity + real-NFL history (recent seasons, or every
    season this league has rostered him in if `league_id` is given -- see
    `_build_profile`) + multi-year ADP consensus. Adds a `league` section
    (this league's draft slot, roster history, honors, trades, waiver
    activity) only when `league_id` is given, since that's the only section
    that needs a Sleeper Season object at all.

    A cold call is expensive (10+ nflref dataset loads and a
    ffadp.board.combine() call per season, plus, with a league_id, a
    draft_board/player_honors/etc. loop per league season -- measured
    17-30s against a real league). This is the first genuinely single-
    player page in the app (a real navigation, not an htmx panel swap), so
    there is no elapsed-time loading indicator available to it the way
    tab switches get one -- caching the whole result, not just the
    league-scoped half `league_data()` already caches, is what keeps a
    repeat view of the same player fast. `fresh=True` bypasses the cache
    (the route's own refresh path).
    """
    key = (str(player_id), str(league_id) if league_id else None)
    if not fresh:
        hit = _PROFILE_CACHE.get(key)
        if hit and time.time() - hit["at"] < _PROFILE_TTL:
            return hit["data"]
    data = _build_profile(player_id, league_id)
    _PROFILE_CACHE[key] = {"data": data, "at": time.time()}
    return data


def clear_profile_cache() -> None:
    """Drop every cached profile (the webapp's refresh=1 path)."""
    _PROFILE_CACHE.clear()


def is_cached(player_id: str, league_id: str | None = None) -> bool:
    """True if a fresh (within `_PROFILE_TTL`) result already exists for
    this player, without building or refreshing anything. Lets a caller
    (the /player route) decide whether a request will be fast or will pay
    the full cold-aggregation cost, so it can only show a loading page for
    the latter -- a warm hit costs nothing extra, unlike always routing
    through a loader-then-redirect page."""
    key = (str(player_id), str(league_id) if league_id else None)
    hit = _PROFILE_CACHE.get(key)
    return bool(hit and time.time() - hit["at"] < _PROFILE_TTL)
