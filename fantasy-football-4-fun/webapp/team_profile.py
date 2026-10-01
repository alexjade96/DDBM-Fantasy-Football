"""Single-team aggregator: everything known about one real NFL team, across
every league-free data source this app touches.

Mirrors `webapp.player_profile` in shape (a private `_build_profile` plus a
cached public `team_profile()` entry point, `clear_profile_cache()`,
`is_cached()`), but scoped to an NFL club abbreviation (see
`nflref.summary.TEAMS`) instead of a Sleeper `player_id`. There is no
fantasy-league identity for an NFL team, so unlike `player_profile()` this
module takes no `league_id` and has no league-scoped section -- it is
reached the same way the NFL Stats tab is, fully league-free.

Every section degrades independently: a data source that errors, has no
snapshot, or simply doesn't cover this team leaves that section empty
rather than failing the whole call, mirroring the same discipline
`nflref.base.NflDataset.fetch()` / `ffadp.board.combine()` /
`player_profile.py` already follow.
"""
from __future__ import annotations

import time

import pandas as pd


def _norm_name(name: str | None) -> str:
    """Shared join key for every name-based match in this module (PFR-
    extra attachment, offense/defense position grouping): a thin wrapper
    around nflref.summary._norm_name, the SAME normalised-name key
    stat_reconcile.reconcile_metric already joins its own cross-source
    rows on. One top-level definition so every caller in this file shares
    it rather than each doing its own local import."""
    try:
        from webapp.sources.nflref.summary import _norm_name as _impl
        return _impl(name)
    except Exception:
        return (name or "").strip().lower()


def roster_name_index(roster: list[dict]) -> dict[str, str]:
    """`{normalised_name: player_id}` for this season's own roster leaderboard
    (`profile["roster"]`, already carries a real Sleeper `player_id` for
    every row -- `_roster_leaderboard`'s own Sleeper-sourced pull, see that
    function's docstring) -- the FIRST thing `resolve_row_player_id` tries,
    ahead of the generic cross-source `ffadp.identity` index.

    Built once per page render (a Jinja global function, called by
    `webapp.app` with `profile["roster"]`) rather than inside
    `resolve_row_player_id` itself, since that function is called once per
    TABLE ROW and rebuilding this map every call would be real, needless
    per-row work across a whole season's tables."""
    out: dict[str, str] = {}
    for r in roster:
        pid = r.get("player_id")
        name = r.get("player")
        if pid and name:
            out[_norm_name(name)] = pid
    return out


def resolve_row_player_id(row: dict, roster_index: dict[str, str] | None = None) -> str | None:
    """Best-effort Sleeper `player_id` for one row of ANY of this module's
    per-stat tables (Season totals' reconciled/single-source tables, the
    Game log's per-game position groups -- both now live under one
    Schedule & results section, see _team_season_sections.html's own
    header comment) -- the id
    `_ident.html`'s `player_link()`/`headshot()` need to hyperlink a name,
    which none of these rows carry natively (they come from nflverse/PFR,
    keyed on `gsis_id`/`pfr_player_id`/plain name, never a Sleeper id).

    A Jinja global (see webapp.app's own `tpl.env.globals` registration)
    rather than something attached to every row ahead of time at each of
    this module's several call sites (`_grouped_metric_stats`,
    `_offense_players_via_shared`/`_defense_players_via_shared`, both
    per-game and season-wide) -- one shared resolver called from the three
    template
    macros themselves (`_teamstat_macros.html`) is less to keep in sync
    than four separate attach-points, and `ffadp.identity`'s own in-process
    index makes a per-row call cheap after the first.

    Priority:
    1. `roster_index` (see `roster_name_index`'s own docstring) -- this
       team's own current-season roster, matched by normalised name. Tried
       FIRST and unconditionally (even when the row has a gsis_id) because
       it's the one path that resolves `reconciled_table`'s rows at all:
       those carry ONLY a plain name, no position (`stat_reconcile.
       reconcile_metric` never attaches one -- see this module's own
       header comment on that function), and `ffadp.identity.resolve`'s
       name-only branch is keyed `f"{name}|{position or ''}"` -- with no
       position it degrades to a `"name|"` key that essentially never
       matches (confirmed live: even "Jared Goff" resolved to None through
       that path alone). A team's own roster reliably has a name+id for
       most of its skill-position players regardless of which stat table
       is asking, which is exactly the gap this closes.
    2. `gsis_id` (nflverse-derived rows -- injuries, player_stats/ngs_*
       buckets) -- a real id match via `ffadp.identity`, which bridges
       Sleeper's own `gsis_id` column. Falls through here only when the
       roster lookup missed (a player who left the roster, a defense/
       special-teams player the offense-scoped roster never carried).
    3. name + position (PFR-derived rows -- snap_counts/pfr_*, which carry
       no gsis_id at all, plus `position_group_table`'s merged rows, which
       always compute a `position` even when the raw source didn't -- see
       `_offense_players_via_shared`'s own docstring) -- no cross-id exists
       for PFR, so this is the only path for those.
    4. name alone, no position -- kept as a final attempt (matches
       `ffadp.identity`'s own signature) but rarely resolves anything per
       the explanation in (1); real coverage for `reconciled_table` comes
       from the roster lookup, not this tier.

    Returns None (never raises) on any resolution failure -- the caller
    macro already renders plain text for a None id, same "best-effort,
    degrades to no link" contract `idm.player_link` always had.
    """
    name = row.get("player") or row.get("pfr_player_name") or row.get("name")
    if roster_index and name:
        hit = roster_index.get(_norm_name(name))
        if hit:
            return hit

    try:
        from webapp.sources.ffadp import identity
    except Exception:
        return None

    gsis_id = row.get("gsis_id")
    position = row.get("position")

    try:
        if gsis_id:
            sid = identity.resolve("nflref", gsis_id=gsis_id)
            if sid:
                return sid
        if name:
            return identity.resolve("nflref", name=name, position=position)
    except Exception:
        pass
    return None


# Canonical fantasy-position order, matching sleepermetrics.nflstats._POSITIONS
# / ddbmFF.R's own sortPosition -- the roster section groups by this order
# rather than one flat list, so a reader can scan "the QBs" then "the RBs"
# etc. A position outside this set (a data-quality gap, not expected in
# practice since player_leaderboard(source="sleeper") only ever returns
# these six) falls into a trailing "Other" bucket rather than being dropped.
_ROSTER_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Real-NFL datasets pulled team-wide (not per-player). Each dataset's own
# "team" column name differs -- normalised here, once, the same way
# player_profile._GSIS_COL/_NAME_COL normalise per-dataset id/name columns.
#
# "player_stats" is the COMPREHENSIVE box-score baseline (every rostered
# player, every week, zero-filled when they didn't touch the ball) --
# added specifically because ngs_passing/ngs_receiving/ngs_rushing only
# publish a row for players NFL's Next Gen Stats tracking system covers
# that week, which is NOT every real pass-catcher/rusher/passer (verified
# live: a real week where 8 SF players had a reception, only 2 had an
# ngs_receiving row -- McCaffrey, with 9 catches, was completely absent).
# player_stats (and pfr_rec/pfr_rush, which are already complete) fill
# that gap so the per-game drilldown never implies "only these N players
# did anything" when more players actually did.
_TEAM_DATASETS = ["snap_counts", "player_stats", "ngs_passing",
                   "ngs_receiving", "ngs_rushing", "pfr_pass", "pfr_rec",
                   "pfr_rush", "pfr_def", "injuries"]
_TEAM_COL = {
    "snap_counts": "team",
    "player_stats": "recent_team",
    "ngs_passing": "team_abbr",
    "ngs_receiving": "team_abbr",
    "ngs_rushing": "team_abbr",
    "pfr_pass": "team",
    "pfr_rec": "team",
    "pfr_rush": "team",
    "pfr_def": "team",
    "injuries": "team",
}

# "route_participation" is NOT in _TEAM_DATASETS/_TEAM_COL above -- unlike
# every other nflref dataset, its rows (exploded from pbp_participation's
# own offense_players list) carry no team column at all (a real play's
# on-field list doesn't repeat which side of the ball it's for; that's
# implicit in which team's schedule the game belongs to). Filtered
# separately in `_team_datasets` below by cross-referencing `player_stats`
# (already team-filtered, already fetched) on the shared gsis_id/player_id
# space both datasets use -- see that function's own comment.

# team_profile() calls nflref.summary.player_leaderboard/schedule_grid plus
# up to 9 nflref.board.load() datasets and a multi-season schedule loop --
# same "cold call is expensive, cache the whole result" rationale as
# player_profile.py. Same {key: {"data","at"}} + TTL shape.
_PROFILE_CACHE: dict[tuple[str, str], dict] = {}
_PROFILE_TTL = 900  # 15 min, matches player_profile.py's own window

# How many recent seasons of history to summarise when no season is pinned.
# Matches player_profile._DEFAULT_WINDOW's rationale: bounds the number of
# schedule_grid calls for the common case rather than walking back to 1999.
_DEFAULT_WINDOW = 5


def _clean_records(df: pd.DataFrame) -> list[dict]:
    """`df.to_dict("records")` with every missing value as `None`, not NaN.

    Mirrors `webapp.app.records()` (kept as a local copy rather than an
    import to avoid coupling this data-layer module to the route module) --
    see that function's own docstring for why this matters: an `is not
    None` guard (in `_season_record` below, and throughout
    team_profile.html) does NOT catch pandas NaN, so an in-progress or
    future game whose score/margin columns are NaN (a real, common shape --
    a mixed played/unplayed schedule forces the whole score column to
    float64, with NaN standing in for the unplayed rows) would otherwise
    read as "played" with poisoned NaN stats cascading through every
    downstream sum. Scrubbing at this one boundary, where every DataFrame
    in this module turns into plain dicts, is what makes every later
    `is not None` check mean what it reads as.
    """
    def clean(v):
        if v is None:
            return None
        try:
            return None if pd.isna(v) else v
        except (TypeError, ValueError):
            return v
    return [{k: clean(v) for k, v in row.items()} for row in df.to_dict("records")]


def _current_season() -> str:
    """The current NFL season -- same `/state/nfl` `league_season` read
    `player_profile._recent_seasons` uses, falling back to a hardcoded
    recent year on any network failure so this never blocks the page."""
    try:
        from sleepermetrics.league import nfl_state
        return str(nfl_state()["league_season"])
    except Exception:
        return "2026"


def _recent_seasons(n: int = _DEFAULT_WINDOW) -> list[str]:
    """The last `n` NFL seasons, most recent first, ending at the current
    season (see `_current_season`)."""
    current = int(_current_season())
    return [str(y) for y in range(current, current - n, -1)]


def _team_identity(abbr: str) -> dict:
    """{'abbr'} for a normalised team abbreviation -- validated against
    `nflref.summary.TEAMS` when that module resolves, but never raises: an
    abbreviation not in the hardcoded list (a relocation, a typo) still
    renders a page, just with `known=False` so the template can flag it."""
    tm = (abbr or "").upper().strip()
    try:
        from webapp.sources.nflref import summary as nflref_summary
        known = tm in nflref_summary.TEAMS and tm != "ALL"
    except Exception:
        known = None  # nflref itself unavailable -- don't claim "unknown"
    return {"abbr": tm, "known": known}


def _roster_leaderboard(abbr: str, season: str) -> list[dict]:
    """This team's real-NFL stat leaderboard for `season`, Sleeper-sourced
    (matches what `percentile_profile`/the player-profile radar already
    assume). This pulls `pos="ALL"`, which -- confirmed live, a PRE-
    EXISTING characteristic of `player_leaderboard` unrelated to this
    function's own fix below -- never actually includes DEF rows at all
    ("ALL" stays offense/kicker-only by design, see that function's own
    docstring); the `is_def`/team-abbreviation branch below is therefore
    presently dead code, kept only because it's cheap and correct IF a
    caller ever passes a `pos` that includes DEF.

    NOT ranked via `player_leaderboard`'s own `team=` filter -- a real,
    confirmed bug: that filter reads Sleeper's own `team` column, which is
    `sleepermetrics.players()`'s CURRENT-snapshot team assignment, not a
    per-season historical one (`sleepermetrics.nflstats._leaderboard_pool`
    builds it straight off that static dump). For a PAST season this is
    wrong in both directions -- verified live, DET 2025: David Montgomery
    (real 2025 DET RB, since traded to Houston) was excluded entirely,
    while Isiah Pacheco (a real KC player, since traded TO Detroit) showed
    up as a DET RB for a season he never played for that team. The team-
    profile page's own Schedule drilldown never hits this (it reads
    `player_stats`' own `recent_team`, a genuinely per-season/per-week
    historical column -- see `_TEAM_COL`), which is exactly why the roster
    section disagreed with it.

    Fixed by pulling the FULL leaderboard unfiltered (`team="ALL"`) and
    keeping only the players `player_stats` itself says were on this team
    THAT season, matched primarily on `gsis_id` (the id both frames
    actually share -- Sleeper's own `player_id` and nflverse's `player_id`
    are different id spaces entirely) and falling back to normalised name
    when `gsis_id` is missing on the Sleeper side -- a real, separately-
    documented gap (see player_profile.py's own "majority of Sleeper's
    dump has no gsis_id" finding): dropping those rows outright, rather
    than falling back, left DET's real 2025 roster at 5 players instead
    of ~55, since most of a real team's own skill players hit exactly this
    gap. DEF rows have no `gsis_id` OR a real name to match on at all and
    are kept by team abbreviation directly instead.
    """
    try:
        from webapp.sources.nflref import board as nflref_board
        from webapp.sources.nflref import summary as nflref_summary
    except Exception:
        return []

    try:
        lb = nflref_summary.player_leaderboard(
            season, pos="ALL", source="sleeper", team="ALL", limit=10_000)
    except Exception:
        return []
    if lb.empty:
        return []

    try:
        ps = nflref_board.load("player_stats", str(season))
    except Exception:
        ps = pd.DataFrame()
    real_gsis: set[str] = set()
    real_names: set[str] = set()
    if not ps.empty and {"player_id", "recent_team"}.issubset(ps.columns):
        team_rows = ps.loc[ps["recent_team"] == abbr]
        # `.dropna()` before `.astype(str)` is required, not cosmetic -- a
        # real, confirmed bug: DET's own 2025 player_stats has one genuine
        # NaN `player_id` row (an unresolved-player stub, same class of gap
        # player_profile.py's own `_norm_name` docstring documents for
        # `player_display_name`). `str(nan)` is the literal string "nan"
        # on EITHER side of this join, so without dropping it first,
        # `real_gsis` contains "nan" and `.isin()` then matches every
        # Sleeper leaderboard row with a missing `gsis_id` (the MAJORITY
        # of them -- verified live, this alone pulled in ~500 players
        # leaguewide instead of one team's real roster).
        real_gsis = set(team_rows["player_id"].dropna().astype(str))
        if "player_display_name" in team_rows.columns:
            real_names = {_norm_name(n) for n in team_rows["player_display_name"].dropna()}

    is_def = lb["position"] == "DEF" if "position" in lb.columns else pd.Series(False, index=lb.index)
    # `.str.strip()` matters: ~22% of Sleeper's own `gsis_id` values carry a
    # stray leading space (the same defect `player_profile._player_identity`
    # already strips) -- confirmed live, David Montgomery's row here read
    # " 00-0035685" against player_stats' clean "00-0035685", so without
    # this the two never matched despite both genuinely being his id.
    gsis_hit = lb["gsis_id"].dropna().astype(str).str.strip().isin(real_gsis) if "gsis_id" in lb.columns \
        else pd.Series(dtype=bool)
    gsis_hit = gsis_hit.reindex(lb.index, fill_value=False)
    no_gsis = lb["gsis_id"].isna() if "gsis_id" in lb.columns else pd.Series(True, index=lb.index)
    name_hit = lb["player"].apply(_norm_name).isin(real_names) if "player" in lb.columns \
        else pd.Series(False, index=lb.index)
    on_team = gsis_hit | (no_gsis & name_hit)
    keep = on_team | (is_def & (lb["team"] == abbr)) if "team" in lb.columns else on_team
    out = lb[keep].reset_index(drop=True)
    if "rank" in out.columns:
        out["rank"] = range(1, len(out) + 1)
    return _clean_records(out) if not out.empty else []


def _roster_by_position(roster: list[dict]) -> list[dict]:
    """Group a flat roster-leaderboard list into `[{"position", "players"},
    ...]` ordered `_ROSTER_POSITIONS` first (QB, RB, WR, TE, K, DEF), then
    any other position value found (data-quality edge case, not expected
    from the Sleeper-sourced leaderboard in practice) appended after,
    sorted alphabetically for a stable order. Each group's players keep
    the leaderboard's own rank order (already sorted by PPR points
    descending). A group with no players for this team is simply absent,
    not rendered empty."""
    by_pos: dict[str, list[dict]] = {}
    for r in roster:
        pos = r.get("position") or "Other"
        by_pos.setdefault(pos, []).append(r)

    ordered = [p for p in _ROSTER_POSITIONS if p in by_pos]
    extra = sorted(p for p in by_pos if p not in _ROSTER_POSITIONS)
    return [{"position": p, "players": by_pos[p]} for p in ordered + extra]


# Roster-leaderboard columns are cumulative REAL production (games/attempts/
# yards/TDs/etc), not fantasy scoring (user request: the Roster section used
# to show every position's table with the same "PPR pts"/"PPR/G" columns
# regardless of position, which said nothing about WHAT that player actually
# did on the field). `_roster_leaderboard` is hardcoded to
# `source="sleeper"` (see that function's own docstring), so this always
# reads `nflref.summary.leaderboard_columns(pos, "sleeper")` -- the SAME
# per-position column spec (`_SLEEPER_QB_COLS`/`_SLEEPER_SKILL_COLS`/
# `_SLEEPER_DEF_COLS`) already used elsewhere in the app (the NFL Stats
# tab's own leaderboard table), rather than a second, hand-maintained column
# list that could drift from it -- just with the trailing fantasy pair
# (`fpts_ppr`/`ppg_ppr`) dropped. `games` is KEPT (unlike the radar's own
# `_RADAR_EXCLUDED_KEYS`, which also drops it): it's real context for
# reading a cumulative total, not a derived score, and this table has no
# per-game rate column of its own the way the radar's percentile axis does.
_ROSTER_EXCLUDED_KEYS = {"fpts_ppr", "ppg_ppr"}


def _roster_position_columns(position: str) -> list[tuple[str, str]]:
    """The (df_key, header) column spec for ONE roster position group --
    see `_ROSTER_EXCLUDED_KEYS`'s own comment for why this exists instead
    of the flat "PPR pts"/"PPR/G" pair every group used to show.

    "K" gets its own real spec, `_KICKER_KEYS` (FGM/FGA/FG%/distance
    buckets/Long/Blocked/XPM/XPA) -- the roster LEADERBOARD row itself
    carries no kicking columns at all (Sleeper's `player_leaderboard`
    pool is built for skill positions, see `nflstats`'s own docstring), so
    falling through to `leaderboard_columns("K", ...)` used to hand a
    kicker's row the WR/RB "Tgt/Rec/Car/..." column set, every cell
    correctly reading zero -- a real, previously-shipped gap (user
    request: "adjust k to relevant stats"), now fixed by giving K its own
    column set AND (see `_kicker_season_totals`/`_build_profile`) real
    aggregated values to fill it with.

    "DEF" gets its own real spec too, `_DEF_TEAM_KEYS` (Sack/QB hit/INT/
    FF/FR/TD/Safety/Tkl/.../Pts allowed/Yds allowed) -- NOT `nflref.
    summary.leaderboard_columns("DEF", ...)`'s own `_SLEEPER_DEF_COLS`,
    which is a DIFFERENT column-naming convention (`sacks`/`ints`/
    `forced_fumbles`/...) built for a completely separate data pull
    (`sleepermetrics.nflstats.player_leaderboard`, not this module's own
    `_sleeper_def_rows`/`team_datasets["sleeper_def"]`, which
    `_def_season_totals`/`_build_profile` actually populate this group
    from). `_roster_leaderboard`'s own `pos="ALL"` pull never returns a
    real DEF row at all (see that function's own docstring), so there is
    no leaderboard row to key columns off in the first place -- the DEF
    group's one row is synthesized entirely in `_build_profile`, this
    spec just says what to show on it. The "TD" column still appears in
    the header (the spec is unchanged, matching the existing per-game
    drilldown panel's own columns) but always reads a dash here --
    `_def_season_totals` deliberately excludes it from the season sum
    pending confirmation of what the raw stat actually measures, see that
    function's own docstring.

    Every other position still falls through to `nflref.summary.
    leaderboard_columns`, unchanged; the rare "Other" bucket
    `_roster_by_position` can produce also falls through there, same as
    before."""
    p = (position or "").upper()
    if p == "K":
        return list(_KICKER_KEYS)
    if p == "DEF":
        return list(_DEF_TEAM_KEYS)
    try:
        from webapp.sources.nflref import summary as nflref_summary
        cols = nflref_summary.leaderboard_columns(position, "sleeper")
    except Exception:
        return []
    return [(k, label) for k, label in cols if k not in _ROSTER_EXCLUDED_KEYS]


def _schedule(abbr: str, season: str) -> list[dict]:
    """This team's real games for `season` (via `schedule_grid`'s existing
    `team=` filter). An unplayed/future game's score/margin columns come
    back as pandas NaN once the frame has ANY played game mixed in (see
    `_clean_records`), scrubbed to `None` here so every downstream
    `is not None` check (`_season_record`, the schedule template) actually
    treats it as "not played" rather than as a poisoned result."""
    try:
        from webapp.sources.nflref import summary as nflref_summary
        sch = nflref_summary.schedule_grid(season, team=abbr)
        return _clean_records(sch) if not sch.empty else []
    except Exception:
        return []


# `snap_counts` is the one dataset that mixes three roles' columns
# (offense_pct/defense_pct/st_pct) into a single row per player, regardless
# of which side of the ball that player actually plays -- unlike NGS/PFR,
# which are already split into one dataset per role (ngs_passing vs
# ngs_rushing, pfr_rec vs pfr_def, etc). Showing all three columns for every
# row is misleading: a WR's row carries a meaningless defense_pct, a DL's
# row carries a meaningless offense_pct. Segmented by which snap-pct
# columns actually have a nonzero value on that row, NOT by a hardcoded
# position whitelist -- PFR's position abbreviations vary a lot (T/G/C/OL,
# DE/DT/NT, CB/S/FS/SS/DB, ...) and a row-by-row value check naturally
# handles a two-way player or a pure special-teamer without needing to
# maintain that taxonomy. A row can land in more than one bucket (a
# offense/ST or defense/ST snap-share split is real, not a data error).
_SNAP_BUCKETS = [
    ("offense", ("offense_snaps", "offense_pct")),
    ("defense", ("defense_snaps", "defense_pct")),
    ("special_teams", ("st_snaps", "st_pct")),
]


def _split_snap_counts(rows: list[dict]) -> dict[str, list[dict]]:
    """Split `snap_counts` rows into `{"offense": [...], "defense": [...],
    "special_teams": [...]}`, each row trimmed to just that bucket's own
    columns (plus identity: player/team/week/position/etc, handled by the
    template's own id_cols exclusion, so trimming here only drops the
    OTHER buckets' pct/snap columns). A bucket a row doesn't belong to
    (value is None, NaN, or 0) is simply not included for that row."""
    out: dict[str, list[dict]] = {}
    for bucket, (snaps_key, pct_key) in _SNAP_BUCKETS:
        picked = []
        for r in rows:
            pct = r.get(pct_key)
            if pct is None or (isinstance(pct, float) and pd.isna(pct)) or pct == 0:
                continue
            trimmed = {k: v for k, v in r.items()
                      if k not in (sk for b, (sk, pk) in _SNAP_BUCKETS if b != bucket)
                      and k not in (pk for b, (sk, pk) in _SNAP_BUCKETS if b != bucket)}
            picked.append(trimmed)
        if picked:
            out[bucket] = picked
    return out


# `player_stats` is nflverse's COMPREHENSIVE weekly box score: one row per
# ROSTERED player per week, zero-filled for every stat they didn't record
# (a punter, an offensive lineman) -- unlike ngs_passing/ngs_receiving/
# ngs_rushing, which only publish a row for players NFL's Next Gen Stats
# tracking system covers that week (verified: a real week where 8 SF
# players caught a pass, ngs_receiving had rows for only 2 of them).
# Split into passing/rushing/receiving buckets by real volume (an
# attempt/carry/target actually recorded, not a snap-share percentage, so
# the bucket key differs from _SNAP_BUCKETS above), same "bucket by
# nonzero value, never a position whitelist" convention -- a two-way
# player (a scrambling QB with real carries, a gadget-play WR who threw a
# pass) correctly lands in more than one bucket.
_PLAYER_STATS_BUCKETS = [
    ("passing", "attempts"),
    ("rushing", "carries"),
    ("receiving", "targets"),
]
# Every column belonging to one role, dropped from every OTHER role's
# bucket (a rushing row has no business showing 0 pass attempts).
_PLAYER_STATS_ROLE_COLS = {
    "passing": ("attempts", "completions", "passing_yards", "passing_tds",
               "interceptions", "passing_air_yards", "pacr"),
    "rushing": ("carries", "rushing_yards", "rushing_tds"),
    "receiving": ("targets", "receptions", "receiving_yards", "receiving_tds",
                 "receiving_air_yards", "target_share", "air_yards_share",
                 "wopr", "racr"),
}


def _split_player_stats(rows: list[dict]) -> dict[str, list[dict]]:
    """Split `player_stats` rows into `{"passing": [...], "rushing": [...],
    "receiving": [...]}`, each row trimmed to just that role's own columns
    (plus identity and the shared `fantasy_points`/`fantasy_points_ppr`,
    which aren't role-specific enough to drop). A player with 0 for that
    role's volume column (the common case -- most rostered players never
    attempt/carry/target in a given week) is simply not included in that
    bucket, mirroring `_split_snap_counts`'s own "bucket by nonzero value"
    rule."""
    out: dict[str, list[dict]] = {}
    for bucket, vol_key in _PLAYER_STATS_BUCKETS:
        picked = []
        for r in rows:
            vol = r.get(vol_key)
            if vol is None or (isinstance(vol, float) and pd.isna(vol)) or vol == 0:
                continue
            other_cols = {c for b, cols in _PLAYER_STATS_ROLE_COLS.items()
                         if b != bucket for c in cols}
            trimmed = {k: v for k, v in r.items() if k not in other_cols}
            picked.append(trimmed)
        if picked:
            out[bucket] = picked
    return out


# Sleeper's raw weekly line (`_sleeper_week_rows`) uses its own volume-key
# names (pass_att/rush_att/rec_tgt), already the exact column names
# stat_reconcile's own "sleeper" source mapping expects -- so, unlike
# `_split_player_stats`, no column renaming happens here, only bucketing.
# A player with 0 (or missing) for a role's volume key is simply not
# included in that bucket, same "bucket by nonzero value" rule.
_SLEEPER_STATS_BUCKETS = [
    ("passing", "pass_att"), ("rushing", "rush_att"), ("receiving", "rec_tgt"),
]


def _split_sleeper_stats(rows: list[dict]) -> dict[str, list[dict]]:
    """Split Sleeper's own weekly rows (see `_sleeper_week_rows`) into
    `{"passing": [...], "rushing": [...], "receiving": [...]}` by real
    volume, the Sleeper-native counterpart to `_split_player_stats` --
    Sleeper's line already carries every role's keys on one flat row (it
    has no role-specific column families to trim between roles the way
    player_stats does), so every bucket a row qualifies for gets the FULL
    row, unmodified."""
    out: dict[str, list[dict]] = {}
    for bucket, vol_key in _SLEEPER_STATS_BUCKETS:
        picked = [r for r in rows if (r.get(vol_key) or 0) > 0]
        if picked:
            out[bucket] = picked
    return out


# PFR's own passing/receiving/rushing datasets carry columns with NO
# cross-source overlap (pressure rate, broken tackles, yards after contact
# -- see stat_reconcile's own docstring), so they are never fed into
# reconcile_metric(); they still belong under the same metric heading
# (per user request: "next gen stats: passing and pfr advanced: passing
# should lay strictly under Passing"). Originally shown as PFR's own
# separate, un-reconciled table under the reconciled one; per a later user
# request ("i don't want multiple tables, i prefer the source table with
# the flyout" -- prompted by a real example: DET 2026 wk1, Jahmyr Gibbs'
# reconciled Rushing row read 29 Car/156 Yds/2 TD with the yardage
# breakdown, 112 before contact + 44 after contact, sitting in a second
# table below it) PFR's extra columns are now JOINED ONTO the reconciled
# row itself (`_attach_pfr_extra`, below) instead.
_PFR_METRIC_DS = {"passing": "pfr_pass", "rushing": "pfr_rush", "receiving": "pfr_rec"}

# PFR's join key on its own passing/receiving/rushing rows is
# "pfr_player_name" (see _NAME_COL's own PFR entries in stat_reconcile.py);
# the reconciled row's own key is "player". Same normalised-name join key
# stat_reconcile.reconcile_metric() itself already uses to fold multiple
# sources' rows into one player -- safe here for the identical reason that
# module's own docstring gives: both sides are already scoped to one
# team's one metric's one game/season slice, a handful of players, not a
# whole-league pool where a name collision is a real risk.
def _attach_pfr_extra(reconciled: list[dict], pfr_rows: list[dict] | None) -> None:
    """Mutates `reconciled` in place, adding `row["_pfr_extra"] = {stat: value,
    ...}` (PFR's own raw columns, minus identity/game-scope columns) to
    whichever rows have a matching PFR row for this game/season. A player
    PFR didn't cover simply gets no `_pfr_extra` key at all (the template's
    own per-column lookup already treats a missing key as "no data" --
    same convention every other stat here follows)."""
    if not pfr_rows:
        return
    drop = {"season", "week", "game_type", "team", "opponent",
            "pfr_player_name", "pfr_player_id"}
    pfr_by_name = {}
    for pr in pfr_rows:
        key = _norm_name(pr.get("pfr_player_name"))
        if key:
            pfr_by_name[key] = {k: v for k, v in pr.items() if k not in drop}
    for row in reconciled:
        extra = pfr_by_name.get(_norm_name(row.get("player")))
        if extra:
            row["_pfr_extra"] = extra


def _grouped_metric_stats(role_rows: dict[str, list[dict]]) -> dict[str, dict]:
    """Build the metric-grouped `stats["passing"/"rushing"/"receiving"]`
    shape from already-role-split rows (`role_rows` keys: "player_stats_
    passing", "ngs_passing", "pfr_pass", "sleeper_passing", ... -- whatever
    of these are present for this slice, per-game or season-wide alike).

    `{"reconciled": [...], "pfr": [...], "sources": [...]}` per metric:
    `reconciled` is `stat_reconcile.reconcile_metric`'s consensus-per-player
    rows (empty list, not absent, when no contributing source had data --
    lets the template tell "no data" apart from "not attempted yet"); `pfr`
    is PFR's own un-reconciled table for that metric (absent entirely, not
    an empty list, when PFR has no rows for this slice -- matches every
    other single-source table's own "absent means nothing to show"
    convention elsewhere in this module); `sources` is the plain list of
    source keys (e.g. `["player_stats", "ngs_passing", "sleeper"]`) that
    actually had rows feeding `reconciled` for THIS slice -- computed here,
    once, rather than reverse-engineered from the reconciled rows'
    themselves in the template, so the "which sources fed this" note stays
    trivially correct even as a reconciled row's own per-stat `_sources`
    dict can differ player to player. Look up display labels via
    `stat_reconcile.SOURCE_LABELS`.

    Expects ONE week's rows per player per source (the per-game grain).
    There is no multi-week mode: the season-wide caller that needed one
    was removed, and season totals now come from per-week reconciliation
    (`stat_reconcile.reconcile_season`).
    """
    from webapp import stat_reconcile

    out: dict[str, dict] = {}
    for metric in ("passing", "rushing", "receiving"):
        rows_by_source: dict[str, list[dict]] = {}
        for src in stat_reconcile.METRIC_SOURCES[metric]:
            key = f"player_stats_{metric}" if src == "player_stats" else (
                f"sleeper_{metric}" if src == "sleeper" else src)
            hit = role_rows.get(key)
            if hit:
                rows_by_source[src] = hit
        reconciled = stat_reconcile.reconcile_metric(rows_by_source, metric)
        entry = {
            "reconciled": reconciled, "sources": sorted(rows_by_source),
            # Per-stat source breakdown (e.g. rushing's "carries" pulling
            # from one more source than "rushing_yards"/"rushing_tds") --
            # see stat_source_groups's own docstring for why the flat
            # "sources" list above overstates this. Restricted to sources
            # that actually had rows THIS slice (rows_by_source's own
            # keys), not stat_reconcile's full theoretical map.
            "source_groups": stat_reconcile.stat_source_groups(
                metric, present=set(rows_by_source)),
        }
        pfr_rows = role_rows.get(_PFR_METRIC_DS[metric])
        if pfr_rows:
            entry["pfr"] = pfr_rows
            _attach_pfr_extra(reconciled, pfr_rows)
        out[metric] = entry
    return out


# Kicker and team-defense stats are Sleeper-ONLY in this app's data
# pipeline -- verified live: nflverse's player_stats/ngs_*/pfr_* datasets
# have zero FG/XP columns and no team-level defensive stat line at all
# (this codebase's other sources are built around individual skill-
# position players). There is nothing to reconcile against, so both
# `_sleeper_kicker_rows`/`_sleeper_def_rows` (below, near the other
# `_sleeper_*` data-pull functions) read Sleeper's raw weekly feed
# directly (`sleepermetrics.scoring.nfl_stats`, the UNTRIMMED stat line --
# deliberately NOT `nflstats.raw_week`, whose own `_USAGE_KEYS` filter
# drops every kicking/team-defense key, built as it is for skill-position
# usage tracking) rather than going through `_sleeper_week_rows`'s own
# player_stats cross-check, which would drop every row here (player_stats
# has no kicker/DEF rows to verify against in the first place). Column
# specs live here, ahead of the pull functions, since `_OFF_POSITION_COLS`/
# `_DEF_TEAM_COLS` (below) reference them.
_KICKER_KEYS = [
    ("fgm", "FGM"), ("fga", "FGA"), ("fgm_pct", "FG%"),
    ("fgm_20_29", "20-29"), ("fgm_30_39", "30-39"), ("fgm_40_49", "40-49"),
    ("fgm_50_59", "50-59"), ("fgm_60p", "60+"), ("fgm_lng", "Long"),
    ("fg_blkd", "Blocked"), ("xpm", "XPM"), ("xpa", "XPA"),
]
_DEF_TEAM_KEYS = [
    ("sack", "Sack"), ("qb_hit", "QB hit"), ("int", "INT"), ("ff", "FF"),
    ("fum_rec", "FR"), ("td", "TD"), ("safe", "Safety"),
    ("tkl", "Tkl"), ("tkl_solo", "Solo"), ("tkl_ast", "Ast"),
    ("tkl_loss", "TFL"), ("def_pass_def", "Pass def"),
    ("def_3_and_out", "3-and-out"), ("def_forced_punts", "Forced punts"),
    ("pts_allow", "Pts allowed"), ("yds_allow", "Yds allowed"),
]


# Real defensive position values seen in snap_counts across several teams
# (verified live: CB, DB, DE, DL, DT, LB, S) collapse to three groups per
# user request ("dl, lb, db (cb & s)") -- DE/DT are both a flavor of
# defensive lineman, CB/S are both a flavor of defensive back. A position
# outside this map (a data-quality gap -- not seen in practice) falls into
# a trailing "Other" group rather than being dropped. "DEF" (Sleeper's own
# team-defense stat line -- see `_sleeper_def_rows`) is a FOURTH group,
# user-requested, added alongside DL/LB/DB and placed FIRST (user's own
# follow-up: "shift the sleeper DEF group to be the first subsection in
# the defense section") -- it is a team-level row, not a per-player one,
# so it is built and rendered separately (see `_defense_position_groups`'s
# own handling), never fed through `_DEF_GROUP_OF`/`_defense_players_via_shared`.
_DEF_GROUP_OF = {
    "DL": "DL", "DE": "DL", "DT": "DL",
    "LB": "LB",
    "DB": "DB", "CB": "DB", "S": "DB",
}
_DEF_GROUP_ORDER = ("DEF", "DL", "LB", "DB")

# Offense position groups, in display order (user's own example). OL was
# DROPPED per user request (2026-09 follow-up -- linemen only ever had
# snap-share data, no box-score stats at all, and were judged not worth
# their own section). K was ALSO dropped from here in the very next
# follow-up: kicker stats moved to replace the Special-teams pill's own
# snap-share table (_team_game_detail.html) rather than living as a
# separate offense group, so it is not double-shown -- see
# `_sleeper_kicker_rows`/`_KICKER_KEYS` for the data itself, still built
# here in team_profile.py, just consumed by the Special-teams panel now.
_OFF_GROUP_ORDER = ("QB", "RB", "WR", "TE")

# FIXED column sets per offense position group (user's own choice: same
# shape every week regardless of whether a given player actually used
# every category, e.g. a WR who never ran the ball this game still gets
# rushing columns, all dashes -- predictable table shape over tightest
# possible table). Each entry is (category, cols) where `cols` is the
# SAME (key, label) shape `reconciled_cols`/`pfr_extra_cols` already use in
# _teamstat_macros.html; `category` says which of a merged player's
# `passing`/`rushing`/`receiving`/`snap`/`kicker` sub-dicts to read `key`
# from.
#
# 2026-09: extended with several real PFR-extra columns (times_pressured_pct/
# times_blitzed/times_hurried/times_hit/passing_bad_throw_pct for QB;
# rushing_yards_before/after_contact_avg for RB; receiving_drop_pct/
# receiving_int/receiving_rat for RB/WR/TE) that were previously shown
# ONLY in the season-wide reconciled table (removed this same session, see
# _team_season_sections.html's own header comment) -- a real, confirmed
# gap: this fixed spec was already a CURATED subset of what PFR/reconciled
# tables actually carry (pre-dating this session, untouched by the
# season-totals removal itself), so removing the season-wide table's own
# dynamic full-column rendering left these values with nowhere left to
# show at all. Diffed directly against the old season-wide table's own
# `reconciled_cols`+`pfr_extra_cols` union (webapp.stat_reconcile /
# _teamstat_macros.html, as last committed) before adding anything here,
# so this now covers every real column that table used to show.
# Each category below can appear MORE THAN ONCE in a row, and NOT always
# consecutively (e.g. QB is passing/rushing/passing/passing/snap -- the two
# categories interleave) -- position_group_table (_teamstat_macros.html)
# keys strictly off the STRING per entry, not a deduped set, reading the
# SAME underlying sub-dict (p.get("passing")) every time that string
# appears; the only effect of a NEW entry (whether same category as the
# last one or not) is that the macro's own per-entry `.grp-divider` rule (a
# vertical line before the first column of every entry after the first)
# fires there too. This is how a single logical category (e.g. Passing)
# gets internal sub-group dividers -- box score | pressure | accuracy --
# AND how a different category can be interleaved between them (e.g. QB's
# Rushing block sitting between Passing's box-score and pressure blocks)
# without the macro needing a second grouping concept: entry boundaries ARE
# the divider boundaries, in whatever order the list itself is written
# (2026-09, user request: each position's block order, alongside pulling
# each category's core box-score columns to the FRONT of its own block --
# QB: Passing box score, Rushing, Passing pressure, Passing accuracy, Snap;
# RB: Rushing box score, Receiving box score, Rushing contact, Receiving
# quality, Snap, Route; WR: Receiving box score, Rushing, Receiving
# quality, Snap, Route; TE unchanged, its own receiving categories were
# already adjacent with no other category to interleave).
_OFF_POSITION_COLS = {
    "QB": [
        ("passing", [("attempts", "Att"), ("completions", "Cmp"),
                     ("passing_yards", "Yds"), ("passing_tds", "TD"),
                     ("interceptions", "INT")]),
        ("rushing", [("carries", "Car"), ("rushing_yards", "Yds"), ("rushing_tds", "TD")]),
        ("passing", [("times_pressured", "Prss"), ("times_pressured_pct", "Prss%"),
                     ("times_blitzed", "Blitz"), ("times_hurried", "Hrd"),
                     ("times_hit", "Hit"), ("times_sacked", "Sack")]),
        ("passing", [("passing_bad_throws", "Bad thr"),
                     ("passing_bad_throw_pct", "Bad thr%")]),
        ("snap", [("offense_snaps", "Snaps"), ("offense_pct", "Snap%")]),
    ],
    "RB": [
        ("rushing", [("carries", "Car"), ("rushing_yards", "Yds"), ("rushing_tds", "TD")]),
        ("receiving", [("targets", "Tgt"), ("receptions", "Rec"),
                       ("receiving_yards", "Yds"), ("receiving_tds", "TD")]),
        ("rushing", [("rushing_yards_before_contact", "YBC"),
                     ("rushing_yards_before_contact_avg", "YBC/att"),
                     ("rushing_yards_after_contact", "YAC"),
                     ("rushing_yards_after_contact_avg", "YAC/att"),
                     ("rushing_broken_tackles", "Broken tkl")]),
        ("receiving", [("receiving_drop", "Drop"), ("receiving_drop_pct", "Drop%"),
                       ("receiving_int", "Int"), ("receiving_rat", "Rtg targeted")]),
        ("snap", [("offense_snaps", "Snaps"), ("offense_pct", "Snap%")]),
        ("route", [("routes_run", "Routes")]),
    ],
    "WR": [
        ("receiving", [("targets", "Tgt"), ("receptions", "Rec"),
                       ("receiving_yards", "Yds"), ("receiving_tds", "TD")]),
        ("rushing", [("carries", "Car"), ("rushing_yards", "Yds"), ("rushing_tds", "TD")]),
        ("receiving", [("receiving_drop", "Drop"), ("receiving_drop_pct", "Drop%"),
                       ("receiving_int", "Int"), ("receiving_rat", "Rtg targeted"),
                       ("receiving_broken_tackles", "Broken tkl")]),
        ("snap", [("offense_snaps", "Snaps"), ("offense_pct", "Snap%")]),
        ("route", [("routes_run", "Routes")]),
    ],
    "TE": [
        ("receiving", [("targets", "Tgt"), ("receptions", "Rec"),
                       ("receiving_yards", "Yds"), ("receiving_tds", "TD")]),
        ("receiving", [("receiving_drop", "Drop"), ("receiving_drop_pct", "Drop%"),
                       ("receiving_int", "Int"), ("receiving_rat", "Rtg targeted"),
                       ("receiving_broken_tackles", "Broken tkl")]),
        ("snap", [("offense_snaps", "Snaps"), ("offense_pct", "Snap%")]),
        ("route", [("routes_run", "Routes")]),
    ],
}

# `("route", [("routes_run", "Routes")])` above is deliberately ONE column,
# not all 14 fields `route_participation` actually carries (targets +
# 13 route-type counts, see nflref.route_participation._ROUTE_TYPES) --
# the fixed-column convention this table already follows (every group gets
# the SAME columns every week) means adding all 13 route-type breakdowns
# would repeat mostly-zero columns on every single row (a player who ran a
# SLANT once this game still gets 12 other "0" cells). `routes_run` is the
# one number that answers "how much of this game did they play as a
# route-runner" at a glance, matching the compact-headline convention every
# other category here follows (e.g. `receiving`'s own Tgt/Rec/Yds/TD over
# its dataset's full column list). The full per-route-type breakdown (and
# `targets` from route_participation itself, distinct from the reconciled
# `receiving.targets` above -- see `_route_summary_rows` for how the two are
# cross-checked) is exposed via `_route_summary_rows`'s own single-game
# summary card instead, not this per-player table.


def _off_position_cols_for_game(stats: dict) -> dict:
    """`_OFF_POSITION_COLS`, trimmed of the "route" category for THIS game
    when `route_participation` has nothing for it at all (2026-09 fix, real
    user-reported bug: the "Routes" column rendered on every RB/WR/TE table
    for every week of the current 2026 season, always blank -- upstream
    nflverse doesn't publish `pbp_participation` for an in-progress season
    yet, see nflref.route_participation's own EARLIEST/gap note, so
    `stats["route_participation"]` is genuinely `[]` for every 2026 game,
    not a data-quality miss for one player).

    The fixed-column convention (`_OFF_POSITION_COLS` itself, a static
    module-level dict, same shape every week -- see that dict's own header
    comment) is preserved at the PLAYER level: a player who didn't run a
    route still shows a dash in the Routes column when OTHER players that
    game did. This only drops the column when NO player on this team has
    ANY route_participation row for this game, i.e. the whole dataset is
    empty for this game -- the same "nothing to report" bar
    `_route_summary_rows` already uses for its own card (`stats.get(
    "route_participation") or []`, identical check, so the column and the
    card disappear together rather than one outliving the other).

    Returns a fresh dict (never mutates the shared `_OFF_POSITION_COLS`
    module constant) so every OTHER game's render -- most of which DO have
    route data -- is unaffected."""
    if stats.get("route_participation"):
        return _OFF_POSITION_COLS
    return {
        group: [(cat, cols) for cat, cols in spec if cat != "route"]
        for group, spec in _OFF_POSITION_COLS.items()
    }

# Kicker stats -- a plain column spec (Sleeper's the only source, nothing
# to reconcile -- see `_KICKER_KEYS`'s own header comment), used by
# `_team_game_detail.html` for the Special-teams pill's replacement table,
# NOT part of `_OFF_POSITION_COLS` (kicker stats moved OUT of Offense's
# own K group in the very next follow-up after first landing there -- see
# `_OFF_GROUP_ORDER`'s own comment for the full history).
_KICKER_COLS = [("kicker", _KICKER_KEYS)]

# FIXED column set for the three PER-PLAYER defensive groups (DL/LB/DB
# alike) -- PFR's defensive stat line is ONE dataset covering both
# pass-rush/tackle stats (relevant mostly to DL/LB) and coverage stats
# (relevant mostly to DB), so rather than hand-splitting which columns
# "belong" to which group (PFR itself draws no such line -- a coverage LB
# or a blitzing DB are both real), every group gets the same full set; a
# player with nothing in a given column shows a dash, same as any other
# absent-stat cell elsewhere in this module. The "DEF" group (Sleeper's
# team-level stat line) is NOT part of this dict -- it has its own single
# "player" (the team itself) and its own column spec, handled separately
# by `_defense_position_groups`.
#
# 2026-09: extended with 8 real pfr_def columns (def_missed_tackle_pct,
# def_times_hitqb, def_completion_pct, def_yards_allowed_per_cmp,
# def_yards_allowed_per_tgt, def_adot, def_air_yards_completed,
# def_yards_after_catch) that were only ever reachable via the season-wide
# section's own dynamic stat_table() (every real column, not a curated
# subset) -- see _OFF_POSITION_COLS's own comment just above for the full
# rationale, same gap, same fix. Most of these read NaN for a non-coverage
# player (a DL/LB with no targets thrown his way has no completion%/aDOT/
# YAC-allowed to report) and dash out via cell()'s existing NaN guard,
# same as any other absent-stat cell -- real, non-null values were
# confirmed live for DBs who saw real targets before adding these.
# Split into several same-named "pfr_def" entries so core box-score stats
# (Sack/Tkl) lead the row, with everything else following as sub-grouped
# blocks, each getting its own `.grp-divider` -- see _OFF_POSITION_COLS's
# own header comment for why repeating a category name is what creates a
# sub-group boundary in position_group_table.
_DEF_PLAYER_COLS = [
    ("pfr_def", [("def_sacks", "Sack"), ("def_tackles_combined", "Tkl")]),
    ("pfr_def", [("def_missed_tackles", "Missed tkl"),
                 ("def_missed_tackle_pct", "Missed tkl%"),
                 ("def_pressures", "Prss"), ("def_times_blitzed", "Blitz"),
                 ("def_times_hurried", "Hrd"), ("def_times_hitqb", "Hit QB")]),
    ("pfr_def", [("def_ints", "INT"), ("def_targets", "Tgt"),
                 ("def_completions_allowed", "Cmp allowed"),
                 ("def_completion_pct", "Cmp% allowed")]),
    ("pfr_def", [("def_yards_allowed", "Yds allowed"),
                 ("def_yards_allowed_per_cmp", "Yds/cmp allowed"),
                 ("def_yards_allowed_per_tgt", "Yds/tgt allowed"),
                 ("def_receiving_td_allowed", "TD allowed")]),
    ("pfr_def", [("def_passer_rating_allowed", "Rtg allowed"),
                 ("def_adot", "aDOT allowed"),
                 ("def_air_yards_completed", "Air yds allowed"),
                 ("def_yards_after_catch", "YAC allowed")]),
    ("snap", [("defense_snaps", "Snaps"), ("defense_pct", "Snap%")]),
]

# The "DEF" group (Sleeper's own team-defense stat line -- see
# _sleeper_def_rows/_DEF_TEAM_KEYS) reads from a merged player's own
# "team_def" sub-dict, a shape unique to that one group (a team-level row,
# not a per-player one -- see _defense_position_groups's own docstring).
_DEF_TEAM_COLS = [("team_def", _DEF_TEAM_KEYS)]

# DEF_COLS (the Jinja global registered in app.py, fed to
# _teamstat_macros.position_group_table as `cols_by_group`) is a dict
# keyed by group name -- DEF gets its own team-level column spec, DL/LB/DB
# all share the identical per-player one (`_DEF_PLAYER_COLS`, see that
# constant's own comment for why one shared set covers all three).
_DEF_COLS = {"DEF": _DEF_TEAM_COLS, "DL": _DEF_PLAYER_COLS,
            "LB": _DEF_PLAYER_COLS, "DB": _DEF_PLAYER_COLS}

# Full-name text for every abbreviated column header `position_group_table`
# renders (`_OFF_POSITION_COLS`/`_DEF_PLAYER_COLS`/`_KICKER_COLS`/
# `_DEF_TEAM_COLS`, above) -- user request: "add a hover over that displays
# what the full header is (e.g. yac = Yards after contact, etc.)". Keyed by
# the real STAT KEY (e.g. "rushing_yards_after_contact"), not by the
# abbreviation text itself: several distinct keys legitimately share the
# same short label ("TD" appears on passing_tds/rushing_tds/receiving_tds/
# def_receiving_td_allowed; "Snaps"/"Snap%" appear on both the offense and
# defense snap-share columns) with genuinely different real meanings, so a
# label-keyed map would either collide or need per-context overrides. Every
# key already carries its own category in its name (rushing_/receiving_/
# passing_/def_/...), which is what keeps a flat, single dict unambiguous
# here -- confirmed by checking every real key in the four column-spec
# constants above before writing this, not assumed. Covers every key that
# actually appears in one of those four specs; a key not in this dict falls
# back to a readable version of its own name (`_full_name`, below), never a
# blank tooltip.
_STAT_FULL_NAMES = {
    # Passing (QB box score + pressure/accuracy blocks)
    "attempts": "Pass attempts", "completions": "Completions",
    "passing_yards": "Passing yards", "passing_tds": "Passing touchdowns",
    "interceptions": "Interceptions thrown",
    "times_pressured": "Times pressured", "times_pressured_pct": "Pressure rate",
    "times_blitzed": "Times blitzed", "times_hurried": "Times hurried",
    "times_hit": "Times hit", "times_sacked": "Times sacked",
    "passing_bad_throws": "Bad throws", "passing_bad_throw_pct": "Bad throw rate",
    # Rushing (box score + contact block)
    "carries": "Rush attempts", "rushing_yards": "Rushing yards",
    "rushing_tds": "Rushing touchdowns",
    "rushing_yards_before_contact": "Rushing yards before contact",
    "rushing_yards_before_contact_avg": "Rushing yards before contact per attempt",
    "rushing_yards_after_contact": "Rushing yards after contact",
    "rushing_yards_after_contact_avg": "Rushing yards after contact per attempt",
    "rushing_broken_tackles": "Broken tackles (rushing)",
    # Receiving (box score + quality block)
    "targets": "Targets", "receptions": "Receptions",
    "receiving_yards": "Receiving yards", "receiving_tds": "Receiving touchdowns",
    "receiving_drop": "Drops", "receiving_drop_pct": "Drop rate",
    "receiving_int": "Interceptions on targets", "receiving_rat": "Passer rating when targeted",
    "receiving_broken_tackles": "Broken tackles (receiving)",
    # Snaps (offense/defense/special-teams -- distinct keys, same real meaning per side)
    "offense_snaps": "Offensive snaps played", "offense_pct": "Offensive snap share",
    "defense_snaps": "Defensive snaps played", "defense_pct": "Defensive snap share",
    "st_snaps": "Special-teams snaps played", "st_pct": "Special-teams snap share",
    # Routes
    "routes_run": "Routes run",
    # Per-player defense (PFR advanced)
    "def_sacks": "Sacks", "def_tackles_combined": "Total tackles",
    "def_missed_tackles": "Missed tackles", "def_missed_tackle_pct": "Missed tackle rate",
    "def_pressures": "Pressures generated", "def_times_blitzed": "Times blitzed",
    "def_times_hurried": "Times generated a hurry", "def_times_hitqb": "QB hits",
    "def_ints": "Interceptions", "def_targets": "Targets faced in coverage",
    "def_completions_allowed": "Completions allowed",
    "def_completion_pct": "Completion rate allowed",
    "def_yards_allowed": "Yards allowed in coverage",
    "def_yards_allowed_per_cmp": "Yards allowed per completion",
    "def_yards_allowed_per_tgt": "Yards allowed per target",
    "def_receiving_td_allowed": "Touchdowns allowed in coverage",
    "def_passer_rating_allowed": "Passer rating allowed when targeted",
    "def_adot": "Average depth of target allowed",
    "def_air_yards_completed": "Air yards allowed on completions",
    "def_yards_after_catch": "Yards after catch allowed",
    # Team defense (Sleeper's own weekly line)
    "sack": "Sacks", "qb_hit": "QB hits", "int": "Interceptions",
    "ff": "Forced fumbles", "fum_rec": "Fumble recoveries", "td": "Touchdowns",
    "safe": "Safeties", "tkl": "Total tackles", "tkl_solo": "Solo tackles",
    "tkl_ast": "Assisted tackles", "tkl_loss": "Tackles for loss",
    "def_pass_def": "Passes defended", "def_3_and_out": "3-and-outs forced",
    "def_forced_punts": "Punts forced", "pts_allow": "Points allowed",
    "yds_allow": "Yards allowed",
    # Kicking (Sleeper's own weekly line)
    "fgm": "Field goals made", "fga": "Field goals attempted",
    "fgm_pct": "Field goal percentage",
    "fgm_20_29": "Field goals made, 20-29 yards",
    "fgm_30_39": "Field goals made, 30-39 yards",
    "fgm_40_49": "Field goals made, 40-49 yards",
    "fgm_50_59": "Field goals made, 50-59 yards",
    "fgm_60p": "Field goals made, 60+ yards",
    "fgm_lng": "Longest field goal made", "fg_blkd": "Field goals blocked",
    "xpm": "Extra points made", "xpa": "Extra points attempted",
}


def _full_name(key: str) -> str:
    """The hover-tooltip text for one column key -- `_STAT_FULL_NAMES`'s own
    entry when it has one, else a readable fallback (underscores to spaces,
    title-cased) so a column added to a spec above without a matching
    dictionary entry still gets SOME tooltip rather than none. Registered
    as a Jinja global (`full_name` in app.py) for `position_group_table`'s
    own header-cell `title=` attribute."""
    return _STAT_FULL_NAMES.get(key) or key.replace("_", " ").strip().title()


def _position_of(name: str, roster_pos: dict[str, str],
                 snap_pos: dict[str, str]) -> str:
    """A player's position for grouping: snap_counts' own value first (the
    most granular real-position source, and the only one that distinguishes
    OL/T from a skill position), falling back to the Sleeper roster
    leaderboard (fantasy positions only -- QB/RB/WR/TE/K, no OL/defensive
    granularity, but covers a player snap_counts might have missed), then
    "Other" if neither resolves (not expected in practice)."""
    key = _norm_name(name)
    return snap_pos.get(key) or roster_pos.get(key) or "Other"


def _offense_players_via_shared(role_rows: dict, roster: list[dict]) -> dict[str, dict]:
    """Adapter: `stat_reconcile.player_week_rows`'s generic per-role output,
    translated into `{name: {"position":..., "passing": row|None,
    "rushing": row|None, "receiving": row|None, "snap": row|None,
    "route": row|None}}` -- one entry per offensive player who appears in
    ANY of passing/rushing/receiving/offensive-snaps/routes this game, so
    it can feed `_build_position_groups` (OL-fold, group ordering,
    per-group name sort). A player active in more than one metric (a QB
    who rushed, a RB who caught passes -- both real and common, verified
    live) correctly ends up as ONE entry with more than one sub-key
    filled, not duplicated across several.

    LIVE as of 2026-09 -- called by `team_profile._offense_position_groups`
    (Phase 3) AND `player_profile._game_log` (Phase 4). Verified against
    the real current-season league for Phase 3 (96 real team-weeks, all 32
    teams, 0 unexplained mismatches once two real bugs the comparison
    itself caught were fixed against the former hand-written merge this
    function replaced -- see `player_week_rows`'s own header comment for
    the position-resolution ordering fix, and this module's own
    `_attach_pfr_extra` mirror in `stat_reconcile.py` for the
    PFR-exclusive-column fix), and again independently for Phase 4
    (~2,100 real player-weeks across 33 real active players spanning
    every offense/defense position group, 0 unexplained mismatches). The
    former hand-written merge function (`_merge_offense_players`) this
    adapter replaced was deleted 2026-09 once both migrations landed and
    a repo-wide grep confirmed zero remaining callers.

    Kicker stats do NOT go through this merge (a kicker never shares a
    row with a QB/RB/WR/TE metric anyway) -- they replace the
    Special-teams pill's own content directly in `_team_game_detail.html`,
    see `_KICKER_COLS`/`_sleeper_kicker_rows`.

    `role_rows` is one GAME's rows only (the same per-game slice
    `_attach_week_stats` already builds) -- `player_week_rows` itself is
    grain-agnostic, but this adapter assumes exactly one week's worth of
    rows in, at most one row per player out.
    """
    from webapp import stat_reconcile as sr

    roster_pos = {_norm_name(r["player"]): r["position"] for r in roster}
    snap_rows = role_rows.get("snap_counts_offense") or []
    snap_pos = {_norm_name(r.get("player")): r.get("position") for r in snap_rows}

    def position_of(name: str, role: str) -> str | None:
        return _position_of(name, roster_pos, snap_pos)

    player_rows, _team_rows = sr.player_week_rows(role_rows, position_of=position_of)
    out: dict[str, dict] = {}
    for row in player_rows:
        # An offensive player never has defense/kicking rows on the SAME
        # row (a real two-way player is not modeled by this app at all,
        # same scope this whole module already has) -- filtering to rows
        # with real offense-relevant content mirrors _merge_offense_
        # players's own implicit scope (it never even LOOKS at defense/
        # kicking role_rows keys, so a defensive player's row there was
        # already invisible to it; this filter makes that same exclusion
        # explicit rather than accidental).
        if not any(row[role] for role in ("passing", "rushing", "receiving", "snap_offense", "route")):
            continue
        key = _norm_name(row["player"])
        out[key] = {
            "name": row["player"], "position": row["position"] or "Other",
            "passing": row["passing"], "rushing": row["rushing"],
            "receiving": row["receiving"], "snap": row["snap_offense"],
            "route": row["route"],
        }
    return out


def _defense_players_via_shared(role_rows: dict, abbr: str = "") -> dict[str, dict]:
    """Adapter: the defense counterpart to `_offense_players_via_shared`.
    One entry per player appearing in PFR's defensive stat line OR the
    defensive snap-share table, keyed `name`/`position` (already folded to
    DL/LB/DB via `_DEF_GROUP_OF`)/`pfr_def`/`snap`. LIVE as of 2026-09 --
    see `_offense_players_via_shared`'s own docstring for the migration
    rationale/verification (the same real-league comparison covered both
    functions together).

    `player_week_rows`'s own position resolution already tries `snap_
    counts_defense` first (via `_ROLE_POSITION_KEY["defense"]`); this
    adapter's `position_of` fallback supplies a second tier,
    `_sleeper_position_map(abbr)` (Sleeper's current-roster player pool --
    see that function's own docstring for the real gap this fallback
    fixes: a team can have zero `snap_counts` rows for a whole season, the
    real, verified KC 2026 case), then "Other" if neither resolves."""
    from webapp import stat_reconcile as sr

    fallback_pos = _sleeper_position_map(abbr) if abbr else {}

    def position_of(name: str, role: str) -> str | None:
        return fallback_pos.get(_norm_name(name))

    player_rows, _team_rows = sr.player_week_rows(role_rows, position_of=position_of)
    out: dict[str, dict] = {}
    for row in player_rows:
        if not any(row[role] for role in ("defense", "snap_defense")):
            continue
        key = _norm_name(row["player"])
        raw_pos = row["position"] or "Other"
        out[key] = {
            "name": row["player"], "position": _DEF_GROUP_OF.get(raw_pos, "Other"),
            "pfr_def": row["defense"], "snap": row["snap_defense"],
        }
    return out


def _sleeper_position_map(abbr: str) -> dict[str, str]:
    """{normalised_name: real_position} for every player on `abbr`'s
    CURRENT Sleeper roster (sleepermetrics.players(), the same pool
    `_sleeper_week_rows` already reads elsewhere in this module) -- the
    fallback position source for defense (see `_defense_players_via_shared`).
    Real, live-verified gap this exists for: KC 2026 had ZERO
    `snap_counts` rows for the entire season so far (not just one game),
    which used to put all 15+ of a team's real defensive players into an
    unmappable "Other" bucket with no column spec -- silently dropping
    real PFR defensive-stat data from view entirely, not just mislabeling
    it. Sleeper's own player pool has no such gap (it's not sourced from
    nflverse's per-game snap tracking at all) and already carries real
    non-fantasy positions (DL/DE/DT/LB/CB/S/DB), unlike the Sleeper
    ROSTER LEADERBOARD (`_roster_leaderboard`) used for offense, which
    only ever returns fantasy positions (QB/RB/WR/TE/K) and would be
    useless here. Keyed on the player's CURRENT team, not the team as of
    this specific game -- a mid-season trade could misattribute a
    fallback lookup, an accepted tradeoff since this is fallback-only
    (snap_counts, when present, is still tried first and is real-game
    accurate). Degrades to `{}` on any failure (no sleepermetrics import,
    no network, no snapshot)."""
    try:
        from sleepermetrics.players import players as _players
        pool = _players()
        team_rows = pool[pool["team"] == abbr]
        return {_norm_name(n): p for n, p in
               zip(team_rows["player_name"], team_rows["position"])}
    except Exception:
        return {}


def _build_position_groups(players: dict[str, dict], group_order: tuple[str, ...],
                           group_of: dict[str, str] | None = None) -> list[dict]:
    """Bucket `players` (from `_offense_players_via_shared`/
    `_defense_players_via_shared`) into `[{"group": "QB", "players": [...]}]`,
    `group_order` first, any
    other position value found appended after (data-quality edge case, not
    expected from real snap_counts/roster data). `group_of`, when given
    (offense only -- OL's several real positions, T/G/C/etc., all fold to
    one "OL" bucket), maps a raw position to its display group; absent
    means the player's own `position` field IS already the group (defense
    -- `_defense_players_via_shared` already resolved DL/LB/DB via
    `_DEF_GROUP_OF`). A group with no players this game is simply absent,
    not rendered empty, same convention every other section here follows."""
    by_group: dict[str, list[dict]] = {}
    for p in players.values():
        raw = p["position"]
        grp = (group_of.get(raw, "Other") if group_of and raw not in group_order
               else raw)
        by_group.setdefault(grp, []).append(p)
    ordered = [g for g in group_order if g in by_group]
    extra = sorted(g for g in by_group if g not in group_order)
    out = []
    for g in ordered + extra:
        rows = sorted(by_group[g], key=lambda p: p["name"])
        out.append({"group": g, "players": rows})
    return out


def _offense_position_groups(stats: dict, roster: list[dict],
                             role_rows: dict | None = None) -> list[dict]:
    """The Offense panel's position-grouped view: QB/RB/WR/TE/K, one row
    per player with everything they did this game merged onto it -- replaces
    the earlier Passing/Rushing/Receiving-as-separate-tables layout, where a
    player active in more than one metric (common: a rushing QB, a
    pass-catching RB) appeared split across several tables instead of once.
    `[]` if there is nothing to group (no offensive data this game).

    2026-09: built on `_offense_players_via_shared` (the shared
    `stat_reconcile.player_week_rows` assembler, adapted to this exact
    shape) -- verified equivalent to the former hand-written merge it
    replaced (`_merge_offense_players`, since deleted; see
    `_offense_players_via_shared`'s own docstring) across
    the whole real current-season league (96 real
    team-weeks, all 32 teams, 0 unexplained mismatches after fixing two
    real bugs the comparison itself caught: PFR-exclusive columns weren't
    being attached, and a rare two-way player's position could resolve
    from a fallback guess before a real per-game source got a chance --
    see `player_week_rows`'s own header comment for the ordering fix, and
    `_offense_players_via_shared`'s own docstring for the migration
    rationale). Two small, deliberate, reviewed behavior changes came with
    it: snap-count cells and PFR-def cells now carry the same
    hover-flyout metadata every other reconciled stat already has (they
    are single-source, so never a disagreement warning, just a consistent
    "which source" tooltip); and a player resolved via a non-offense role's
    real position source (e.g. a punter's real `snap_counts_special_teams`
    row) now shows that real position instead of falling through to
    "Other".

    `role_rows` is the per-game slice `_attach_week_stats` already builds
    before calling this function -- required now (`stats` alone is no
    longer enough, since the new path reads role_rows directly rather than
    stats' own already-grouped-by-metric shape); `None` only for a caller
    with no such data (degrades to `[]`, matching the "no offensive data
    this game" case).

    Every real offensive-line position (OL/T/G/C/LT/RT/LG/RG -- linemen
    only ever have snap data, no box-score or kicker stats) is explicitly
    folded into one shared "Other" bucket via `group_of`, rather than
    passing no mapping at all: `_build_position_groups`'s own default
    (raw position IS the group) would otherwise surface T/G/C/etc as
    SEPARATE named groups of their own (a real bug caught while verifying
    an earlier version of this change -- "OL" and "T" both showed up as
    their own sections after OL was dropped from `_OFF_GROUP_ORDER`).
    "Other" has no entry in `_OFF_POSITION_COLS`, so `position_group_table`
    silently skips rendering it -- the net effect is what "remove the OL
    section" asked for, without linemen leaking back out as several
    smaller ones."""
    if not role_rows:
        return []
    players = _offense_players_via_shared(role_rows, roster)
    if not players:
        return []
    ol_positions = {"OL", "T", "G", "C", "LT", "RT", "LG", "RG"}
    raw_positions = {p["position"] for p in players.values()}
    group_of = {pos: ("Other" if pos in ol_positions else pos) for pos in raw_positions}
    return _build_position_groups(players, _OFF_GROUP_ORDER, group_of)


def _defense_position_groups(stats: dict, roster: list[dict], abbr: str = "",
                             role_rows: dict | None = None) -> list[dict]:
    """The Defense panel's position-grouped view: DEF/DL/LB/DB. DL/LB/DB are
    one row per PLAYER, their PFR stat line + defensive snap share merged;
    "DEF" is a DIFFERENT SHAPE entirely -- one row for the TEAM itself
    (Sleeper's own team-defense stat line, `stats["sleeper_def"]` -- see
    `_sleeper_def_rows`), single source, nothing to merge across metrics.
    Built separately and PREPENDED (user request: "shift the sleeper DEF
    group to be the first subsection in the defense section") rather than
    folded into the per-player merge, which has no concept of a team-level
    row.

    2026-09: built on `_defense_players_via_shared` -- see
    `_offense_position_groups`'s own docstring for the full migration
    rationale/verification (the same real-league comparison covered both
    functions together).

    `abbr` feeds `_defense_players_via_shared`'s Sleeper-roster position
    fallback (see `_sleeper_position_map`) -- required whenever
    `snap_counts_defense` is thin or entirely absent for this game/season,
    or every defensive player falls into an unmappable "Other" group.
    `role_rows` is the per-game slice `_attach_week_stats` already builds
    -- required now for the per-player half (the team-level "DEF" row is
    unaffected, still read from `stats["sleeper_def"]`). `[]` if there is
    nothing to group at all (no DEF row and no players)."""
    out: list[dict] = []
    def_rows = stats.get("sleeper_def") or []
    if def_rows:
        out.append({"group": "DEF", "players": [
            {"name": abbr or "DEF", "position": "DEF", "team_def": def_rows[0]}]})

    players = _defense_players_via_shared(role_rows or {}, abbr)
    if players:
        out.extend(_build_position_groups(players, _DEF_GROUP_ORDER[1:]))
    return out


def _kicker_groups(stats: dict) -> list[dict]:
    """The Special-teams pill's replacement content (2026-09 follow-up,
    user request: "replace special teams subsections with kicker stats
    (e.g. remove the snap shares)"): one row per kicker, Sleeper's own
    weekly stat line (`stats["sleeper_kicker"]` -- see
    `_sleeper_kicker_rows`), shaped as a single `[{"group": "Kickers",
    "players": [...]}]` list so `_teamstat_macros.position_group_table`
    (already built to render a list of groups) can render this without a
    second, parallel table macro. `[]` if this team had no kicker activity
    this game (a bye, or a kicker who didn't attempt anything)."""
    rows = stats.get("sleeper_kicker") or []
    if not rows:
        return []
    players = [{"name": r.get("player"), "position": "K", "kicker": r} for r in rows]
    return [{"group": "Kickers", "players": sorted(players, key=lambda p: p["name"])}]


# Display label per `route_participation` raw column -- readable route
# names, matching the same `(key, label)` shape every other column spec in
# this module uses, so this table renders through `_teamstat_macros.
# stat_table`'s own generic id_cols-exclusion path rather than a bespoke
# template loop. Order is roughly short-to-deep (screens/quick game first,
# verticals last), not alphabetical, matching how a reader would actually
# scan "what did this player's game look like."
_ROUTE_TYPE_LABELS = [
    ("route_screen", "Screen"), ("route_swing", "Swing"),
    ("route_slant", "Slant"), ("route_quick_out", "Quick out"),
    ("route_hitch_curl", "Hitch/curl"), ("route_shallow_cross_drag", "Shallow cross/drag"),
    ("route_texas_angle", "Texas/angle"), ("route_in_dig", "In/dig"),
    ("route_deep_out", "Deep out"), ("route_corner", "Corner"),
    ("route_post", "Post"), ("route_wheel", "Wheel"), ("route_go", "Go"),
]


def _route_summary_rows(stats: dict) -> list[dict]:
    """Single-game route-participation summary: one row per offensive skill
    player (WR/RB/TE) who ran a real route this game -- `routes_run` (every
    qualifying pass-play snap, see `nflref.route_participation`'s own
    docstring for exactly what counts), `targets` (from route_participation
    itself -- see the cross-check note below), `tgt_per_route` (targets per
    route, a real efficiency read distinct from raw target share -- two
    players can share the same target COUNT while running a very different
    number of routes to get there), and the route-TYPE breakdown for
    whichever of his own targets were charted (see `_ROUTE_TYPE_LABELS`).

    Route-type columns with ZERO across every row THIS GAME are dropped for
    the whole table (most games only see a handful of the 13 real types
    actually charted at all), but kept UNIFORMLY across every row that
    remains -- `_teamstat_macros.stat_table` derives its column list from
    `rows[0].keys()` alone and reads `row[k]` for every other row
    unconditionally, so a per-ROW sparse key set (an earlier version of
    this function) would KeyError the moment two rows disagreed on which
    columns they carried. Trimming by COLUMN instead of by row keeps every
    row's key set identical, which is what that macro actually requires.

    `targets` here is route_participation's OWN count (targeted plays with
    a charted route), deliberately kept SEPARATE from the reconciled
    `receiving.targets` cross-source vote elsewhere on this same player's
    row in `_OFF_POSITION_COLS` -- the two datasets don't always agree
    (route_participation only counts a target when `route` was actually
    charted; a target can exist in the box score with no charted route,
    e.g. a badly-thrown-away pass). Not reconciled against each other here;
    both numbers are real, just answering slightly different questions,
    same "different sources, different questions" precedent this module's
    `roster_detail`/`bench_pts` split already established (see CLAUDE.md)."""
    rows = stats.get("route_participation") or []
    played = [r for r in rows if r.get("routes_run")]
    if not played:
        return []

    used_cols = [(key, label) for key, label in _ROUTE_TYPE_LABELS
                 if any(r.get(key) for r in played)]

    # Dict keys here double as this table's column HEADERS -- stat_table()
    # renders any non-id_cols key verbatim (only "_".join()->" " replaced),
    # so "player"/"routes" (below) is the actual header text, not a raw
    # snake_case field name like _teamstat_macros.stat_table's other
    # callers show (e.g. an injuries row's own `report_primary_injury`).
    # "player" itself is the one exception that CANNOT be renamed -- the
    # macro's own <td> reads row.get("player") by that literal key to
    # render the name cell at all (see stat_table's own template code).
    out = []
    for r in played:
        routes_run = r["routes_run"]
        targets = r.get("targets") or 0
        row = {
            "player": r.get("name"), "Pos": r.get("pos"),
            "Routes": routes_run, "Targets": targets,
            "Tgt/route": round(targets / routes_run, 2) if routes_run else 0,
        }
        for key, label in used_cols:
            row[label] = r.get(key) or 0
        out.append(row)
    return sorted(out, key=lambda r: r["Routes"], reverse=True)


def _attach_week_stats(schedule: list[dict], team_datasets: dict,
                       roster: list[dict] | None = None, abbr: str = "",
                       season: str = "") -> list[dict]:
    """Attach `game["stats"]` to each schedule row, for the "advanced stats
    for this game" dropdown. Also attaches `game["game_type"]` (REG/WC/DIV/
    CON/SB, nflverse's own convention) pulled out of whichever advanced-stat
    dataset carries it -- `schedule_grid()` itself has no `game_type`
    column, only the snap_counts/pfr_* datasets do.

    `team_datasets` is already loaded team-wide for the season (see
    `_team_datasets`) -- this only SLICES those already-fetched rows by
    `week`, no additional dataset loads. `roster` is the season's own
    `_roster_leaderboard(abbr, season)` result, already fetched once by
    `_build_profile` -- passed through rather than re-fetched, purely to
    resolve an offensive player's fantasy position as a fallback (see
    `_offense_position_groups`). `abbr` feeds `_defense_position_groups`'
    own Sleeper-roster position fallback (`_sleeper_position_map`) --
    needed for a team/season where `snap_counts` is thin or absent
    entirely (a real, verified case: KC 2026 had zero snap_counts rows
    for the whole season, which without this fallback put every real
    defensive player into an unmappable "Other" group).

    `game["stats"]` is grouped BY METRIC, not by source (2026-09 redesign,
    user request: "unify the stat categories by metric measured instead of
    segmenting by source"):
      - `stats["passing"/"rushing"/"receiving"]` = `{"reconciled": [...],
        "pfr": [...]}` -- see `_grouped_metric_stats`. `player_stats` is
        role-split first (`_split_player_stats`, every rostered player,
        zero-filled -- fills the real coverage gap `ngs_*` leaves, see that
        function's own docstring) and Sleeper's own weekly lines are
        role-split the SAME way (`_split_player_stats` works on any rows
        carrying `attempts`/`carries`/`targets`-equivalent volume, and
        Sleeper's raw keys are pre-mapped to those names via
        `_sleeper_role_rows` below) before either feeds the reconciler.
      - `stats["snap_counts_offense"/"_defense"/"_special_teams"]` --
        unchanged, single source, no metric family to unify under (a snap
        share has no cross-source equivalent at all).
      - `stats["pfr_def"]` -- unchanged, PFR is the only defense-advanced
        source, so there is nothing to reconcile.
      - `stats["injuries"]` -- unchanged, single source.
      - `stats["offense_by_position"]` / `stats["defense_by_position"]`
        (2026-09, THIRD pass at this template's Offense/Defense panels --
        superseding the metric-per-card layout above, which is now used
        only to FEED this grouping, not rendered directly on the per-game
        drilldown any more): `[{"group": "QB", "players": [...]}, ...]`,
        one row per player with everything they did this game merged onto
        it (a rushing QB, a pass-catching RB) -- see
        `_offense_position_groups`/`_defense_position_groups`.
      - `stats["route_summary"]` -- see `_route_summary_rows`: one row per
        offensive skill player who ran a real route this game (routes run,
        targets, targets-per-route, route-type breakdown). `stats["route_
        participation"]` itself (the raw per-player rows, same key every
        other `extra_key` above uses) stays attached too, for anything that
        wants gsis-level detail rather than the display-ready summary.
      - `stats["off_position_cols"]` -- see `_off_position_cols_for_game`:
        `_OFF_POSITION_COLS` with the "route" category dropped for THIS
        game when `route_participation` has nothing at all for it (a real,
        user-reported bug otherwise: the current 2026 season's Routes
        column rendered on every offense table every week, always blank,
        since nflverse doesn't publish `pbp_participation` for an
        in-progress season yet). The TEMPLATE reads this per-game value
        for the Offense panel, not the static `OFF_POSITION_COLS` Jinja
        global (still used as-is for Defense/Special-teams, which have no
        such gap).
      - `stats["route_unavailable"]` -- True when THIS WHOLE SEASON's
        `route_participation` dataset came back empty (see
        `_team_route_rows`'s own `unavailable_seasons` return), distinct
        from a plain "no data this game" -- lets the template show an
        explicit "not yet available" note (2026-09 follow-up: silently
        omitting the column/card read as broken, not as "nothing to show
        yet" -- real user report: "routes are blank / listing '-'").
        `season` (this function's own new param) selects which entry of
        `team_datasets["route_participation_unavailable_seasons"]`
        applies; every game in one `_attach_week_stats` call shares the
        SAME season (see `_build_profile`'s one call site), so this is
        computed once before the loop, not per game.
    A dataset/week combination with no rows for this team simply leaves
    that key/sub-key absent (or, for `reconciled`, an empty list -- see
    `_grouped_metric_stats`), so the template can render "no advanced
    stats" once rather than once per dataset.
    """
    route_unavailable = str(season) in (
        team_datasets.get("route_participation_unavailable_seasons") or set())
    out = []
    for g in schedule:
        wk = g.get("week")
        role_rows: dict[str, list[dict]] = {}
        game_type = None
        if wk is not None:
            for ds, rows in team_datasets.items():
                if ds == "route_participation_unavailable_seasons":
                    continue
                hit = [r for r in rows if r.get("week") == wk]
                if not hit:
                    continue
                if game_type is None:
                    game_type = next(
                        (r.get("game_type") for r in hit if r.get("game_type")), None)
                if ds == "snap_counts":
                    for bucket, rows_b in _split_snap_counts(hit).items():
                        role_rows[f"snap_counts_{bucket}"] = rows_b
                elif ds == "player_stats":
                    for bucket, rows_b in _split_player_stats(hit).items():
                        role_rows[f"player_stats_{bucket}"] = rows_b
                elif ds == "sleeper":
                    for bucket, rows_b in _split_sleeper_stats(hit).items():
                        role_rows[f"sleeper_{bucket}"] = rows_b
                else:
                    role_rows[ds] = hit
        stats = _grouped_metric_stats(role_rows)
        for extra_key in ("snap_counts_offense", "snap_counts_defense",
                         "snap_counts_special_teams", "pfr_def", "injuries",
                         "sleeper_kicker", "sleeper_def", "route_participation"):
            if extra_key in role_rows:
                stats[extra_key] = role_rows[extra_key]
        stats["offense_by_position"] = _offense_position_groups(stats, roster or [], role_rows)
        stats["defense_by_position"] = _defense_position_groups(stats, roster or [], abbr, role_rows)
        stats["kicker_groups"] = _kicker_groups(stats)
        stats["route_summary"] = _route_summary_rows(stats)
        stats["route_unavailable"] = route_unavailable
        stats["off_position_cols"] = _off_position_cols_for_game(stats)
        out.append({**g, "stats": stats, "game_type": game_type})
    return out


def _season_record(abbr: str, season: str) -> dict | None:
    """Reduce one season's `schedule_grid` rows to a small W-L-T + points
    summary for this team. `None` when there are no played games for that
    season (future/unscheduled, or a bad abbreviation) rather than a
    misleading all-zero row.

    A game only counts once results exist (`home_score`/`away_score` both
    present, matching `schedule_grid`'s own `margin` computation) -- a
    future/unscheduled game is excluded, not counted as a tie.
    """
    games = _schedule(abbr, season)
    played = [g for g in games
              if g.get("home_score") is not None and g.get("away_score") is not None]
    if not played:
        return None

    wins = losses = ties = pf = pa = 0
    for g in played:
        is_home = g.get("home_team") == abbr
        team_pts = g["home_score"] if is_home else g["away_score"]
        opp_pts = g["away_score"] if is_home else g["home_score"]
        pf += team_pts
        pa += opp_pts
        if team_pts > opp_pts:
            wins += 1
        elif team_pts < opp_pts:
            losses += 1
        else:
            ties += 1

    return {
        "season": season, "wins": wins, "losses": losses, "ties": ties,
        "games": len(played), "points_for": pf, "points_against": pa,
        "point_diff": pf - pa,
    }


def _season_history(abbr: str, seasons: list[str]) -> list[dict]:
    """Every season in `seasons` with at least one played game, most recent
    first -- a season with no results (future, or before the schedule
    dataset's own EARLIEST) is simply absent, not a blank row."""
    out = []
    for season in seasons:
        rec = _season_record(abbr, season)
        if rec:
            out.append(rec)
    return out


def _sleeper_week_rows(abbr: str, seasons: list[str],
                       player_stats_rows: list[dict]) -> list[dict]:
    """This team's roster's per-week stat lines from Sleeper's own weekly
    feed (`sleepermetrics.nflstats.raw_week`), reshaped to the same
    {"player", "week", "season", <stat keys>} row shape every other source
    in `_team_datasets` already returns, so `stat_reconcile.reconcile_metric`
    can treat it identically to `player_stats`/`ngs_*`/`pfr_*`.

    `raw_week` returns {player_id: {stat: value}} with NO name/team of its
    own (unlike the nflref datasets, which already carry both). A player's
    CURRENT roster team (from `sleepermetrics.players()`) is NOT enough to
    attribute a given past WEEK to `abbr` -- a real bug this fixed: a
    player traded mid-season (verified live: Justin Fields, on KC's CURRENT
    roster but on the Jets for every real 2025 game per player_stats) would
    otherwise have his OLD team's entire game line misattributed to his
    CURRENT team for every week, since nothing here previously checked
    whether he was actually on `abbr` for that specific week.

    Fixed by requiring the SAME player+week to appear on `player_stats_rows`
    (already fetched, team-filtered, for this exact abbr+season -- ground
    truth for "who really played for this team this week") before trusting
    Sleeper's line for it. A player `player_stats` has no row for that week
    (a bye, or player_stats coverage gap) is excluded rather than guessed --
    a missing data point is preferable to a wrongly-attributed one. This
    does mean Sleeper coverage is now bounded by player_stats's own
    coverage; that's an accepted tradeoff for correctness over completeness
    (Sleeper is the 4th, most best-effort source here, not the anchor).

    Walks every week 1..18 for each season (`raw_week` itself is cheap --
    snapshot-first, see its own docstring) rather than trying to intersect
    with the schedule first, mirroring how `_team_datasets` below just pulls
    every week of every requested season and lets the per-game slice in
    `_attach_week_stats` pick out what it needs. Degrades to `[]` on any
    failure (no sleepermetrics import, no network, no snapshot)."""
    try:
        from sleepermetrics.nflstats import raw_week
        from sleepermetrics.players import players
    except Exception:
        return []

    try:
        pool = players()
        roster = pool[pool["team"] == abbr]
        name_by_pid = dict(zip(roster["player_id"].astype(str),
                               roster["player_name"]))
    except Exception:
        return []
    if not name_by_pid:
        return []

    verified_weeks = {
        (r.get("player_display_name"), r.get("season"), r.get("week"))
        for r in player_stats_rows if r.get("player_display_name")
    }

    out: list[dict] = []
    for season in seasons:
        for wk in range(1, 19):
            try:
                lines = raw_week(season, wk)
            except Exception:
                continue
            for pid, line in (lines or {}).items():
                name = name_by_pid.get(str(pid))
                if not name:
                    continue
                if (name, int(season), wk) not in verified_weeks:
                    continue
                out.append({"player": name, "week": wk, "season": season,
                           "team": abbr, **line})
    return out


def _sleeper_kicker_rows(abbr: str, seasons: list[str]) -> list[dict]:
    """This team's kicker(s), Sleeper's own weekly stat line (FG made/
    attempted, FG% by distance bucket, XP made/attempted -- see
    `_KICKER_KEYS`), one row per kicker per week. Kickers are matched by
    their CURRENT roster team (sleepermetrics.players()) same as
    `_sleeper_week_rows`, without that function's player_stats cross-check
    (there is no player_stats row for a kicker to verify against -- see
    this section's own header comment). Each row carries `player_id` (the
    Sleeper id, same value the roster leaderboard's own K rows carry) so
    `_kicker_roster_totals` can join a season's worth of these weekly rows
    back onto the Roster section's kicker rows by EXACT id, not name --
    added alongside the existing `player` name, not in place of it (the
    per-game drilldown's own `_kicker_groups`/`position_group_table` path
    reads named keys off `_KICKER_KEYS` and ignores anything extra, so this
    is a purely additive change for that existing consumer). Degrades to
    `[]` on any failure."""
    try:
        from sleepermetrics import scoring
        from sleepermetrics.players import players as _players
    except Exception:
        return []
    try:
        pool = _players()
        kickers = pool[(pool["team"] == abbr) & (pool["position"] == "K")]
        name_by_pid = dict(zip(kickers["player_id"].astype(str), kickers["player_name"]))
    except Exception:
        return []
    if not name_by_pid:
        return []

    out: list[dict] = []
    for season in seasons:
        for wk in range(1, 19):
            try:
                lines = scoring.nfl_stats(season, wk)
            except Exception:
                continue
            for pid, name in name_by_pid.items():
                line = (lines or {}).get(pid)
                if not line or not any(k in line for k, _ in _KICKER_KEYS):
                    continue
                out.append({"player": name, "player_id": pid, "week": wk,
                           "season": season, "team": abbr, **line})
    return out


# `_KICKER_KEYS` itself already carries only real production (no fantasy
# points) -- reused directly as the Roster section's K column spec (see
# `_roster_position_columns`). Of those keys, only `fgm_lng` is NOT a
# counting stat: a season's "long" is the single BEST make, not a sum of
# weekly bests (summing would double/triple count the same real distance).
# Every other key sums across weeks; `fgm_pct` is then RECOMPUTED from the
# summed fgm/fga rather than averaged (averaging weekly percentages would
# weight a 1-attempt week the same as a 5-attempt week).
_KICKER_MAX_KEYS = {"fgm_lng"}


def _kicker_season_totals(kicker_rows: list[dict]) -> dict[str, dict]:
    """`_sleeper_kicker_rows`' weekly rows (already scoped to one season by
    the caller -- see `_build_profile`) collapsed to ONE row per kicker,
    keyed by Sleeper `player_id` -- the Roster section's own season-
    cumulative counterpart to the per-game drilldown's weekly rows (which
    stay exactly as they are; this is a NEW aggregation, not a replacement).
    `games` counts real weeks with a row (mirrors every other position
    group's own `games` column, from `player_leaderboard`'s `nunique` week
    count). A kicker with zero real weekly rows this season simply has no
    entry here -- the caller degrades that the same way an absent stat
    degrades everywhere else on this page."""
    totals: dict[str, dict] = {}
    for row in kicker_rows:
        pid = str(row.get("player_id") or "")
        if not pid:
            continue
        slot = totals.setdefault(pid, {"games": 0})
        slot["games"] += 1
        for key, _label in _KICKER_KEYS:
            v = row.get(key)
            if v is None:
                continue
            if key in _KICKER_MAX_KEYS:
                slot[key] = max(slot.get(key, v), v)
            elif key != "fgm_pct":
                slot[key] = slot.get(key, 0) + v
    for slot in totals.values():
        fga = slot.get("fga") or 0
        slot["fgm_pct"] = round(100 * (slot.get("fgm") or 0) / fga, 1) if fga else None
    return totals


#: `_DEF_TEAM_KEYS`'s own raw "td" field is EXCLUDED from the season total
#: -- confirmed live (2025 wk2), its per-week values (DET 7, KC 2, BUF 3,
#: SF 3, no correlation to `pts_allow`) are far too high and inconsistent
#: to be real defensive/special-teams touchdowns (which would almost
#: always read 0, rarely 1, essentially never above 2 in a single week);
#: `def_td` (a DIFFERENT key, not in `_DEF_TEAM_KEYS`) is the one Sleeper
#: actually scores 6 points for in `data/sources/default_scoring.json`.
#: Whatever raw "td" measures is not yet confirmed, so summing 17 weeks of
#: an unverified figure into a season "TD" total would very likely display
#: a wrong, embarrassingly-large number with no source to check it against
#: -- left out of the total per explicit direction, pending that
#: confirmation. The pre-existing per-game drilldown panel is UNCHANGED
#: and still shows this field labelled "TD" -- only this NEW season-total
#: aggregation omits it.
_DEF_SEASON_EXCLUDED_KEYS = {"td"}


def _def_season_totals(def_rows: list[dict]) -> dict | None:
    """`_sleeper_def_rows`' weekly rows (already scoped to one season and
    one team by the caller -- see `_build_profile`) collapsed to ONE
    season-total row, the Roster section's DEF-group counterpart to
    `_kicker_season_totals`. Every `_DEF_TEAM_KEYS` field EXCEPT `td` (see
    `_DEF_SEASON_EXCLUDED_KEYS`) is a genuine straight sum -- `pts_allow`/
    `yds_allow` are season TOTALS by the same real-NFL convention a box
    score reports them (e.g. "allowed 411 points on the season"), not an
    average, confirmed against `nflref.summary.player_leaderboard(pos=
    "DEF")`'s own independently-computed season total for the same team
    (DET 2025: 411 pts / 5642 yds allowed, matched exactly). `games`
    counts real weeks with a row. Returns `None` (not an empty dict) when
    `def_rows` has nothing -- there is at most ONE team-defense entry
    (unlike kickers, never more than one per team), so the caller doesn't
    need a dict keyed by id, just "is there a real total or not"."""
    if not def_rows:
        return None
    totals: dict = {"games": 0}
    for row in def_rows:
        totals["games"] += 1
        for key, _label in _DEF_TEAM_KEYS:
            if key in _DEF_SEASON_EXCLUDED_KEYS:
                continue
            v = row.get(key)
            if v is None:
                continue
            totals[key] = totals.get(key, 0) + v
    return totals


def _sleeper_def_rows(abbr: str, seasons: list[str]) -> list[dict]:
    """This team's own team-defense stat line, Sleeper's own weekly feed --
    keyed on the team ABBREVIATION itself as the "player_id" (Sleeper's own
    convention for a DST entry, verified live: `nfl_stats(season, week)`
    returns a row under the literal key "DET"/"KC"/etc, not any individual
    player id). One row per week; see `_DEF_TEAM_KEYS` for the columns
    kept. Degrades to `[]` on any failure."""
    try:
        from sleepermetrics import scoring
    except Exception:
        return []

    out: list[dict] = []
    for season in seasons:
        for wk in range(1, 19):
            try:
                lines = scoring.nfl_stats(season, wk)
            except Exception:
                continue
            line = (lines or {}).get(abbr)
            if not line or not any(k in line for k, _ in _DEF_TEAM_KEYS):
                continue
            out.append({"player": abbr, "week": wk, "season": season,
                       "team": abbr, **line})
    return out


def _team_datasets(abbr: str, seasons: list[str]) -> dict:
    """Real-NFL advanced/usage data for this team's roster, keyed by
    dataset name -> list of row dicts, across `seasons`. Filtered by each
    dataset's own team column (see `_TEAM_COL`), not by player id -- this
    is a team-wide pull, mirroring `player_profile._real_nfl_history`'s
    per-dataset try/except-continue discipline but scoped by team instead
    of by player.

    Also includes `"sleeper"` (see `_sleeper_week_rows`) -- a genuine 4th
    real-NFL data source, added specifically to feed the passing/rushing/
    receiving reconciliation (`stat_reconcile.reconcile_metric`) a
    non-nflverse, non-PFR data point to vote alongside the others. Also
    `"sleeper_kicker"`/`"sleeper_def"` (see `_sleeper_kicker_rows`/
    `_sleeper_def_rows`) -- Sleeper is the ONLY source in this pipeline for
    kicking/team-defense stats at all, so these two are single-source, not
    reconciliation inputs. Also `"route_participation"` (see
    `nflref.route_participation`) -- filtered SEPARATELY from every other
    `_TEAM_DATASETS` entry below, since its own rows carry no team column
    to filter on at all (see that dict's own header comment); instead kept
    to whichever `gsis_id`s already surfaced in THIS team's own
    `player_stats` rows (same gsis_id/player_id space, already
    team-filtered a few lines above) for the same season -- a player who
    only ever suited up for a DIFFERENT team that season is excluded by
    construction, not by re-checking his team per row."""
    try:
        from webapp.sources.nflref import board as nflref_board
    except Exception:
        return {}

    out: dict[str, list[dict]] = {}
    for ds in _TEAM_DATASETS:
        rows: list[dict] = []
        col = _TEAM_COL.get(ds)
        for season in seasons:
            try:
                df = nflref_board.load(ds, season)
            except Exception:
                continue
            if df.empty or col not in df.columns:
                continue
            hit = df[df[col] == abbr]
            if not hit.empty:
                rows.extend(_clean_records(hit))
        out[ds] = rows
    out["sleeper"] = _sleeper_week_rows(abbr, seasons, out.get("player_stats", []))
    out["sleeper_kicker"] = _sleeper_kicker_rows(abbr, seasons)
    out["sleeper_def"] = _sleeper_def_rows(abbr, seasons)
    route_rows, unavailable_seasons = _team_route_rows(
        abbr, seasons, out.get("player_stats", []), nflref_board)
    out["route_participation"] = route_rows
    out["route_participation_unavailable_seasons"] = unavailable_seasons
    return out


def _team_route_rows(abbr: str, seasons: list[str], player_stats_rows: list[dict],
                     nflref_board) -> tuple[list[dict], set[str]]:
    """This team's own slice of `route_participation` -- see
    `_team_datasets`'s own comment for why this can't just be another
    `_TEAM_DATASETS`/`_TEAM_COL` entry (no team column on the source rows
    at all). `gsis_id`s already known to be on `abbr`'s roster for a given
    season (from `player_stats_rows`, already team-filtered) gate which
    route_participation rows are kept for that season -- cheap, since
    `player_stats_rows` is already in hand, and correct against a
    mid-season trade the same way `_sleeper_week_rows` already guards for
    (a player who only played for a DIFFERENT team a given week has no
    `player_stats` row for `abbr` that week and is excluded).

    Also returns `unavailable_seasons`: the subset of `seasons` where the
    WHOLE `route_participation` dataset came back empty for the SEASON
    (`nflref_board.load` returning an empty frame), not just "this team had
    no hits" -- distinguishes "nflverse hasn't published `pbp_participation`
    for this season yet" (the real, structural, current-2026-season gap;
    see `nflref.route_participation`'s own EARLIEST/degrade note, confirmed
    live: 0 rows for 2026 as of this writing since nflverse doesn't publish
    that release until after the postseason) from "this specific team
    genuinely had zero qualifying route rows this season" (would be
    unusual, but real for a team with no player_stats matches at all).
    `_off_position_cols_for_game`/`_route_summary_rows`'s callers use this
    to show an explicit "not yet available" note instead of just quietly
    omitting the section, which is what shipped here before and read as
    broken rather than "nothing to show yet" (real user report: "routes
    are blank / listing '-'")."""
    by_season: dict[str, set[str]] = {}
    for r in player_stats_rows:
        by_season.setdefault(str(r.get("season")), set()).add(r.get("player_id"))

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
        ids = by_season.get(str(season))
        if not ids or "gsis_id" not in df.columns:
            continue
        hit = df[df["gsis_id"].isin(ids)]
        if not hit.empty:
            rows.extend(_clean_records(hit))
    return rows, unavailable


def _season_grouped_stats(team_datasets: dict) -> dict:
    """The Injury reports section's own data (2026-09: the only survivor of
    what used to be a much bigger season-wide "Advanced & usage stats"
    section -- Passing/Rushing/Receiving reconciliation, snap-count splits,
    and PFR-defense all lived here too, until each was found to already be
    shown elsewhere and removed rather than kept as duplicate work: season
    totals belong to Roster's own per-position tables, and snap counts/PFR
    defense are already fully disseminated per-game in the schedule
    drilldown -- see _team_season_sections.html's own header comment for
    the full breakdown of where everything else went). Trimmed to just
    this one dataset ON PURPOSE: the old version ran the full multi-source
    reconciliation pipeline (a since-removed multi-week mode of `_grouped_metric_stats`)
    across every rostered player's whole season for output nothing reads
    any more -- confirmed via a full-repo search before trimming (this
    function's only call site is `_build_profile`, and `team_stats_grouped`
    -- what it returns -- has exactly one consumer, the Injury reports
    section's `.get("injuries")`). Kept as its own small function (rather
    than inlined into `_build_profile`) so a future second season-wide
    single-source need has an obvious place to grow into, the same role
    this function used to serve for `snap_counts`/`pfr_def` before those
    moved out."""
    return {"injuries": team_datasets.get("injuries") or []}


def _build_profile(abbr: str, season: str | None) -> dict:
    """The real aggregation logic -- see `team_profile()` (the cached
    public entry point) for the full contract."""
    identity = _team_identity(abbr)
    tm = identity["abbr"]

    seasons = _recent_seasons()
    current_season = season or _current_season()
    if current_season not in seasons:
        seasons = sorted(set(seasons) | {current_season}, reverse=True)

    roster = _roster_leaderboard(tm, current_season)
    team_datasets = _team_datasets(tm, [current_season])
    schedule = _schedule(tm, current_season)

    # The Roster section's K group needs REAL kicking stats (FGM/FGA/XPM/
    # XPA/...), which `_roster_leaderboard`'s own row shape simply doesn't
    # carry (see `_roster_position_columns`'s own docstring) -- merged in
    # here from `team_datasets["sleeper_kicker"]`, which `_team_datasets`
    # already fetched for this season regardless (the per-game drilldown's
    # Special-teams panel needs it too), so this is a free aggregation, not
    # a second data pull. Joined by Sleeper `player_id` (exact, not a
    # name-normalised match -- see `_sleeper_kicker_rows`'s own docstring
    # for why the id was added there specifically for this join). A K row
    # with no matching totals (a kicker who never actually recorded a
    # weekly stat line) is left as-is -- its real columns simply render as
    # dashes, same "absent means nothing to show" convention every other
    # stat here follows.
    kicker_totals = _kicker_season_totals(team_datasets.get("sleeper_kicker") or [])
    if kicker_totals:
        for r in roster:
            if r.get("position") == "K":
                totals = kicker_totals.get(str(r.get("player_id") or ""))
                if totals:
                    r.update(totals)

    # The Roster section has NO "DEF" group at all today -- `_roster_
    # leaderboard`'s own `pos="ALL"` pull never returns a real team-defense
    # row (see that function's own docstring: "a PRE-EXISTING
    # characteristic... `pos="ALL"` stays offense/kicker-only"), so unlike
    # K (a real row that just needed real columns merged onto it), DEF
    # needs a whole row SYNTHESIZED from `team_datasets["sleeper_def"]`
    # (user request: "add a def to the roster to represent the sleeper def
    # position"). No `player_id` -- a team defense is not a Sleeper player
    # id, and setting it to the team abbreviation would build a broken
    # `/player/<abbr>` link / a 404 headshot url (see `_ident.html`'s
    # `headshot`/`player_link`, which need a REAL Sleeper pid); leaving it
    # unset lets those macros degrade to plain text, the same "no id known"
    # path every other caller without one already falls into. No `rank`
    # either -- there is no leaguewide DEF ranking this pull produces (see
    # `_roster_position_columns`'s own docstring on why this isn't the
    # SAME `pos="DEF"` leaderboard nflref's own NFL Stats tab uses), so the
    # template's own rank cell shows a dash rather than a fabricated
    # number. Omitted entirely (not appended as an empty row) when this
    # team genuinely had no scored defensive week yet.
    def_totals = _def_season_totals(team_datasets.get("sleeper_def") or [])
    if def_totals:
        roster = roster + [{"player_id": None, "player": tm, "position": "DEF",
                            "team": tm, "rank": None, **def_totals}]

    return {
        "identity": identity,
        "current_season": current_season,
        "seasons_covered": seasons,
        "roster": roster,
        "roster_by_position": _roster_by_position(roster),
        "schedule": _attach_week_stats(schedule, team_datasets, roster, tm,
                                      season=current_season),
        "season_history": _season_history(tm, seasons),
        "team_datasets": team_datasets,
        "team_stats_grouped": _season_grouped_stats(team_datasets),
    }


def team_profile(abbr: str, season: str | None = None, fresh: bool = False) -> dict:
    """Everything known about one NFL team, cached for `_PROFILE_TTL`
    seconds. `season` pins the roster-leaderboard/schedule sections to one
    year (defaults to the current NFL season); `season_history` always
    spans the last `_DEFAULT_WINDOW` seasons regardless.

    A cold call loads a season leaderboard, a schedule, a multi-season
    schedule history loop, and up to 9 nflref datasets -- expensive enough
    to cache the whole result, same rationale as `player_profile()`.
    `fresh=True` bypasses the cache (the route's own refresh path).
    """
    tm = (abbr or "").upper().strip()
    sea = season or _current_season()
    key = (tm, sea)
    if not fresh:
        hit = _PROFILE_CACHE.get(key)
        if hit and time.time() - hit["at"] < _PROFILE_TTL:
            return hit["data"]
    data = _build_profile(tm, sea)
    _PROFILE_CACHE[key] = {"data": data, "at": time.time()}
    return data


def clear_profile_cache() -> None:
    """Drop every cached team profile (the webapp's refresh=1 path)."""
    _PROFILE_CACHE.clear()


def is_cached(abbr: str, season: str | None = None) -> bool:
    """True if a fresh (within `_PROFILE_TTL`) result already exists for
    this team+season, without building or refreshing anything -- lets the
    route decide whether a request will be fast or needs the loader page,
    same convention as `player_profile.is_cached`."""
    tm = (abbr or "").upper().strip()
    sea = season or _current_season()
    hit = _PROFILE_CACHE.get((tm, sea))
    return bool(hit and time.time() - hit["at"] < _PROFILE_TTL)
