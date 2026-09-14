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

import pandas as pd

from sleepermetrics import draft, metrics
from sleepermetrics.players import players as sleeper_players

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


def _norm_name(name: str | None) -> str:
    """Loose name key, same normalisation ffadp.identity/_norm and
    nflref.summary._norm_name already use independently -- mirrored here
    rather than imported, since neither of those modules exports it as a
    stable public helper."""
    n = (name or "").lower().strip()
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
    dicts for this player only. gsis-bridged datasets match on the real id;
    PFR-bridged ones fall back to normalised name + position (best-effort,
    flagged as such in the returned shape)."""
    try:
        from webapp.sources.nflref import board as nflref_board
    except Exception:
        return {}

    out: dict[str, dict] = {}
    norm_target = _norm_name(name)
    pos_target = (position or "").upper()

    for ds in _GSIS_DATASETS:
        rows: list[dict] = []
        if gsis_id:
            for season in seasons:
                try:
                    df = nflref_board.load(ds, season)
                except Exception:
                    continue
                col = _GSIS_COL.get(ds)
                if col not in df.columns:
                    continue
                hit = df[df[col].astype(str) == str(gsis_id)]
                if not hit.empty:
                    rows.extend(hit.to_dict("records"))
        out[ds] = {"rows": rows, "best_effort": False}

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


def player_profile(player_id: str, league_id: str | None = None) -> dict:
    """Everything known about one player.

    Always includes identity + real-NFL history (recent seasons, or every
    season this league has rostered him in if `league_id` is given -- see
    below) + multi-year ADP consensus. Adds a `league` section (this
    league's draft slot, roster history, honors, trades, waiver activity)
    only when `league_id` is given, since that's the only section that
    needs a Sleeper Season object at all.

    Real-NFL data is scoped to `_DEFAULT_WINDOW` recent seasons by default;
    when `league_id` is given and this player has league-scoped seasons on
    record, the union of those seasons (deduplicated with the recent
    window) is used instead, so a player's real-NFL stats line up with the
    seasons this league actually saw him play.
    """
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

    return {
        "identity": identity,
        "seasons_covered": real_nfl_seasons,
        "real_nfl": real_nfl,
        "adp_history": adp,
        "league": league_section,
    }
