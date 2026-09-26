"""Real routes-run per offensive skill player, per game.

No nflverse release gives this pre-aggregated the way `player_stats`/
`snap_counts`/`pfr_advstats` do -- confirmed live (2026-09): `ftn_charting`
is play-level charting with NO player id column at all (motion/play-action/
blitzer flags on the play itself, not attributable to a receiver without a
separate join); `pbp_participation` carries the on-field player lists per
play but no play-type flag of its own. Building this means joining TWO full
play-level releases and exploding one of them -- genuinely heavier than
every other dataset in this package, which is why it was passed over twice
before (see CLAUDE.md's own "found and rejected for now on exactly that
cost" note) until asked for directly.

Pipeline (`_build(season)`):
  1. `pbp/play_by_play_<season>.parquet` (~20MB) for `play_type` (to filter
     to real pass plays -- `pbp_participation` has no such flag of its own)
     and `receiver_player_id`/`receiver_player_name` (to attribute a
     TARGETED play's `route` to the actual player, not just the play).
  2. `pbp_participation/pbp_participation_<season>.parquet` for the on-field
     player lists (`offense_players`/`offense_names`/`offense_positions`,
     semicolon-delimited parallel arrays) and the play's own `route` (the
     type of route the TARGETED receiver ran -- SLANT/GO/HITCH.../etc, blank
     when nobody was targeted or the route wasn't charted).
  3. Join on (game_id, play_id) -- verified live, 100% match rate on a real
     2024 season (45919/45919 rows). Filter to `play_type == "pass"`.
  4. Explode `offense_players`/`offense_positions` in lockstep (one row per
     player who was on the field for that pass play) and count per
     (game, player) -- that count IS routes run: every pass-play appearance
     on offense, not just a play where the player was targeted. Filtered to
     WR/RB/TE/FB (offensive skill positions -- the O-line/QB rows explode
     out of the same list but aren't routes).
  5. Separately, targets-by-route-type comes from the UNexploded pass-play
     rows keyed on `receiver_player_id` -- `route` only describes the
     targeted receiver's own route, so this is the one place a player-level
     route TYPE can be attached at all; a route run without being targeted
     has no charted type anywhere in free nflverse data.

Output grain: one row per (game_id, gsis_id) -- `routes_run` (every
qualifying pass-play snap), `targets`, and one flat `route_<slug>` column
per charted route type (`route_go`, `route_slant`, ... -- see `_ROUTE_COLS`)
counting how many of THIS player's own targets came on that route.
Deliberately flat columns, not a nested `{route: count}` dict per row: a
dict-valued column silently CORRUPTS on the parquet round trip this
module's cache already uses (verified live -- pyarrow unions every row's
keys into every OTHER row too, None-padding a sparse per-player dict into
the full leaguewide vocabulary on every single row, not just widening the
schema); flat columns sidestep that entirely and match every other
dataset's column-per-stat convention in this package (also easier for a
template to render as sortable table columns). A player who ran routes but
was never targeted still gets a `routes_run` row with `targets == 0` and
every `route_*` column 0.

**`EARLIEST = 2016`** for BOTH source releases (verified live: 2015 and
earlier both 404 on `pbp_participation`; `pbp` itself goes back further but
is gated by the newer, narrower release here). **2026 (the current live
season, as of this writing) is not yet published** (verified live: 404) --
degrades to an empty frame like any other pre-EARLIEST or offline case, not
a bug; check back once nflverse publishes the season's file.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2016

_SKILL_POS = {"WR", "RB", "TE", "FB"}

_PBP_COLS = [
    "game_id", "play_id", "week", "season", "play_type",
    "receiver_player_id", "receiver_player_name",
]

# Every charted route value seen live in pbp_participation (2016-2025;
# verified against a real season, not assumed) -- a NEW value nflverse adds
# later simply won't get its own route_* column until this list is updated
# (it will still count toward `targets`, just not broken out by type).
# `_slug` turns "SHALLOW CROSS/DRAG" into "route_shallow_cross_drag" for a
# valid, stable column name.
_ROUTE_TYPES = [
    "GO", "SLANT", "SCREEN", "QUICK OUT", "DEEP OUT", "HITCH/CURL",
    "IN/DIG", "SHALLOW CROSS/DRAG", "CORNER", "POST", "SWING",
    "TEXAS/ANGLE", "WHEEL",
]


def _slug(route: str) -> str:
    return "route_" + route.lower().replace("/", "_").replace(" ", "_")


_ROUTE_COLS = {r: _slug(r) for r in _ROUTE_TYPES}


def _explode_routes(pass_plays: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, gsis_id, name, pos) offensive-skill player who
    was on the field for a real pass play -- see this module's own
    docstring for why this, not a pre-built nflverse column, is what
    "routes run" actually is here."""
    ids = pass_plays["offense_players"].fillna("").str.split(";")
    names = pass_plays["offense_names"].fillna("").str.split(";")
    pos = pass_plays["offense_positions"].fillna("").str.split(";")
    ex = pd.DataFrame({
        "game_id": pass_plays["nflverse_game_id"].values,
        "week": pass_plays["week"].values,
        "season": pass_plays["season"].values,
        "gsis_id": ids, "name": names, "pos": pos,
    })
    ex = ex.explode(["gsis_id", "name", "pos"])
    ex = ex[ex["pos"].isin(_SKILL_POS)]
    ex = ex[ex["gsis_id"] != ""]
    return ex


def _targets_by_route(pass_plays: pd.DataFrame) -> pd.DataFrame:
    """One row per (game_id, gsis_id) target, pivoted to a flat `route_*`
    count column per charted type (see `_ROUTE_COLS`) plus a `targets`
    total -- `route` only describes the TARGETED player's own route (see
    module docstring); a route run without a target has no charted type in
    this data at all. A route value outside `_ROUTE_TYPES` (a new one
    nflverse starts charting later) still counts toward `targets`, just not
    broken out by its own column -- future-proofing over a silent drop."""
    tgt = pass_plays[pass_plays["receiver_player_id"].notna()].copy()
    tgt = tgt[tgt["route"].fillna("").str.strip() != ""]
    tgt = tgt.rename(columns={
        "nflverse_game_id": "game_id",
        "receiver_player_id": "gsis_id",
        "receiver_player_name": "name",
    })
    targets = (tgt.groupby(["game_id", "gsis_id"])
               .size().reset_index(name="targets"))
    pivot = (tgt.groupby(["game_id", "gsis_id", "route"])
             .size().unstack(fill_value=0))
    pivot = pivot.rename(columns=_ROUTE_COLS)
    known = [c for c in _ROUTE_COLS.values() if c in pivot.columns]
    pivot = pivot[known].reset_index()
    out = targets.merge(pivot, on=["game_id", "gsis_id"], how="left")
    for col in _ROUTE_COLS.values():
        if col not in out.columns:
            out[col] = 0
        out[col] = out[col].fillna(0).astype(int)
    return out


def _build(season: str) -> pd.DataFrame:
    from . import api

    pbp = api.read_release_parquet(f"pbp/play_by_play_{season}.parquet")
    part = api.read_release_parquet(
        f"pbp_participation/pbp_participation_{season}.parquet")
    if pbp is None or pbp.empty or part is None or part.empty:
        return pd.DataFrame()

    pbp_cols = [c for c in _PBP_COLS if c in pbp.columns]
    merged = part.merge(
        pbp[pbp_cols], left_on=["nflverse_game_id", "play_id"],
        right_on=["game_id", "play_id"], how="inner")
    # `right_on="game_id"` leaves pbp's OWN game_id column sitting alongside
    # part's own nflverse_game_id (both hold the identical value, joined
    # on) -- drop it so downstream helpers renaming nflverse_game_id ->
    # game_id don't collide with a second, already-real game_id column
    # (a real bug this hit: "Grouper for 'game_id' not 1-dimensional",
    # pandas refusing to group on two same-named columns at once).
    merged = merged.drop(columns=["game_id"])
    pass_plays = merged[merged["play_type"] == "pass"].copy()
    if pass_plays.empty:
        return pd.DataFrame()

    routes = _explode_routes(pass_plays)
    route_counts = (routes.groupby(["game_id", "week", "season", "gsis_id", "name", "pos"])
                    .size().reset_index(name="routes_run"))

    targets = _targets_by_route(pass_plays)

    out = route_counts.merge(targets, on=["game_id", "gsis_id"], how="left")
    out["targets"] = out["targets"].fillna(0).astype(int)
    for col in _ROUTE_COLS.values():
        out[col] = out[col].fillna(0).astype(int)
    return out.reset_index(drop=True)


class RouteParticipation(NflDataset):
    name = "route_participation"
    label = "Routes run (real, play-level)"
    EARLIEST = EARLIEST

    def _asset(self, season: str) -> str:
        # Two assets are actually needed (see module docstring) -- fetch()
        # is overridden below rather than forced through the base
        # contract's single-asset shape, same precedent `Schedules.fetch`
        # already set for its own all-seasons-file case.
        return f"pbp_participation/pbp_participation_{season}.parquet"

    def fetch(self, season: str, reload: bool = False) -> pd.DataFrame:
        from . import cache

        season = str(season)
        try:
            if int(season) < self.EARLIEST:
                return pd.DataFrame()
        except (TypeError, ValueError):
            pass

        if not reload:
            cached = cache.load(self.name, season)
            if cached is not None:
                return cached

        try:
            out = _build(season)
        except Exception:
            out = pd.DataFrame()

        if out.empty:
            if reload:
                cached = cache.load(self.name, season)
                if cached is not None:
                    return cached
            return pd.DataFrame()

        cache.save(self.name, season, out)
        return out
