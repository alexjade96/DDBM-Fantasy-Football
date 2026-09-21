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
    assume, and DEF rows only exist on the Sleeper source) -- ranked among
    the team's own players via `player_leaderboard`'s existing `team=`
    filter, no new data code needed."""
    try:
        from webapp.sources.nflref import summary as nflref_summary
        lb = nflref_summary.player_leaderboard(
            season, pos="ALL", source="sleeper", team=abbr, limit=100)
        return _clean_records(lb) if not lb.empty else []
    except Exception:
        return []


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


def _attach_week_stats(schedule: list[dict], team_datasets: dict) -> list[dict]:
    """Attach `game["stats"] = {dataset: [rows for this team, this week]}`
    to each schedule row, for the "advanced stats for this game" dropdown.
    Also attaches `game["game_type"]` (REG/WC/DIV/CON/SB, nflverse's own
    convention) pulled out of whichever advanced-stat dataset carries it --
    `schedule_grid()` itself has no `game_type` column, only the
    snap_counts/pfr_* datasets do.

    `team_datasets` is already loaded team-wide for the season (see
    `_team_datasets`) -- this only SLICES those already-fetched rows by
    `week`, no additional dataset loads. A dataset/week combination with no
    rows for this team is simply absent from that game's `stats` dict
    (never an empty-list placeholder), so the template can render "no
    advanced stats for this game" once rather than once per dataset.

    `snap_counts` is special-cased: instead of one mixed offense/defense/ST
    row set under the key `"snap_counts"`, it's split into
    `"snap_counts_offense"` / `"snap_counts_defense"` /
    `"snap_counts_special_teams"` (see `_split_snap_counts`) so each
    sub-table only shows the columns relevant to that role. `player_stats`
    is split the same way into `"player_stats_passing"` /
    `"player_stats_rushing"` / `"player_stats_receiving"` (see
    `_split_player_stats`) -- it's the comprehensive box-score baseline
    (every rostered player, zero-filled), included specifically because
    the ngs_passing/ngs_receiving/ngs_rushing datasets only cover players
    NFL's Next Gen Stats tracking system published for that week, which is
    NOT every real passer/rusher/receiver.

    `game_type` (along with `game_id`/`opponent`/`season_type`) is
    otherwise constant across every row of a single game's advanced-stat
    tables -- repeating it per stat row is pure duplication once it's
    pulled up here, which is why the template's per-game drilldown tables
    drop those columns entirely (see team_profile.html's `game_extra_cols`)
    rather than just deduping them visually.
    """
    out = []
    for g in schedule:
        wk = g.get("week")
        stats = {}
        game_type = None
        if wk is not None:
            for ds, rows in team_datasets.items():
                hit = [r for r in rows if r.get("week") == wk]
                if not hit:
                    continue
                if game_type is None:
                    game_type = next(
                        (r.get("game_type") for r in hit if r.get("game_type")), None)
                if ds == "snap_counts":
                    for bucket, rows_b in _split_snap_counts(hit).items():
                        stats[f"snap_counts_{bucket}"] = rows_b
                elif ds == "player_stats":
                    for bucket, rows_b in _split_player_stats(hit).items():
                        stats[f"player_stats_{bucket}"] = rows_b
                else:
                    stats[ds] = hit
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


def _team_datasets(abbr: str, seasons: list[str]) -> dict:
    """Real-NFL advanced/usage data for this team's roster, keyed by
    dataset name -> list of row dicts, across `seasons`. Filtered by each
    dataset's own team column (see `_TEAM_COL`), not by player id -- this
    is a team-wide pull, mirroring `player_profile._real_nfl_history`'s
    per-dataset try/except-continue discipline but scoped by team instead
    of by player."""
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
    return out


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

    return {
        "identity": identity,
        "current_season": current_season,
        "seasons_covered": seasons,
        "roster": roster,
        "roster_by_position": _roster_by_position(roster),
        "schedule": _attach_week_stats(schedule, team_datasets),
        "season_history": _season_history(tm, seasons),
        "team_datasets": team_datasets,
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
