"""One row per pass play with the defense's scheme, for Player Analytics.

`player_games` is one row per player per game, so it cannot answer "against man
coverage" or "when he was pressured": those are facts about a single play.  This
dataset is the play-level counterpart, limited to pass plays (dropbacks).

Built from two stored raw nflverse files per season:

  * `pbp/play_by_play_<season>.parquet`: passer, targeted receiver, result;
  * `pbp_participation/pbp_participation_<season>.parquet`: what the defense
    and offense did on the play (coverage, box, rushers, pressure, time to
    throw, formation, and the targeted receiver's route).

Also stored for each play: the quarter, down, yards to go, yards from the
opponent's goal line and the clock (seconds left in the quarter), so a play can be
shown in context.  Kept: every pass attempt and every sack (a dropback with no attempt; nflverse's
`pass_attempt` flag includes sacks, so `attempt` here is that flag minus sacks), with
two-point tries left out (the player stat files leave them out too).  Only the
columns the builder reads are stored, so a snapshot is small.

Facts this depends on (checked against the stored files, 2026-10-14):

  * Coverage fields (`man_zone`, `coverage`) are filled for about 92% of 2018 to
    2022 pass plays and 99% to 100% from 2023.  Box, rushers and formation are
    about 100%.  Pressure and time to throw are about 92% to 93% from 2018.
  * `route` describes the TARGETED receiver's route only (nobody else's), so a
    route filter applies to targets.
  * A value that is not recorded stays blank (None / NaN).  The builder's
    filters never match a blank, and nothing is inferred.
  * The season has no participation file until nflverse publishes it (the file
    is frozen until the postseason ends).  Such a season is stored with its
    plays and blank scheme fields, so it matches no scheme filter; the engine
    leaves those games out of any total that uses a scheme filter.

Snapshots are committed under `data/sources/nflverse/pass_plays/<season>.parquet`.
On Render a missing snapshot is NOT rebuilt (no raw parsing there): the frame is
empty.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2016

_PBP_COLS = [
    "game_id", "play_id", "week", "season", "posteam", "defteam", "pass_attempt",
    "sack", "two_point_attempt", "passer_player_id", "receiver_player_id",
    "complete_pass", "yards_gained", "air_yards", "pass_touchdown", "interception",
    "play_deleted", "qtr", "down", "ydstogo", "yardline_100", "quarter_seconds_remaining",
]
_PART_COLS = [
    "nflverse_game_id", "play_id", "route", "defense_man_zone_type",
    "defense_coverage_type", "defenders_in_box", "number_of_pass_rushers",
    "was_pressure", "time_to_throw", "offense_formation",
]

#: stored columns, in order
COLUMNS = ["season", "week", "game_id", "play_id", "team", "opponent", "passer_id",
           "receiver_id", "attempt", "sack", "complete", "yards", "air_yards", "td",
           "interception", "route", "man_zone", "coverage", "box", "rushers",
           "pressure", "ttt", "formation", "qtr", "down", "ydstogo", "yardline", "clock"]


def _flag(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype("int8")


def build(pbp: pd.DataFrame, part: pd.DataFrame | None, season: int) -> pd.DataFrame:
    """The pass plays of one season.  `part` may be None or empty (no
    participation file yet): the scheme columns are then blank."""
    if pbp is None or pbp.empty:
        return pd.DataFrame(columns=COLUMNS)
    p = pbp.copy()
    keep = (pd.to_numeric(p["pass_attempt"], errors="coerce").fillna(0).eq(1)
            | pd.to_numeric(p["sack"], errors="coerce").fillna(0).eq(1))
    if "two_point_attempt" in p.columns:
        keep &= pd.to_numeric(p["two_point_attempt"], errors="coerce").fillna(0).ne(1)
    if "play_deleted" in p.columns:
        keep &= pd.to_numeric(p["play_deleted"], errors="coerce").fillna(0).ne(1)
    p = p[keep]
    if p.empty:
        return pd.DataFrame(columns=COLUMNS)

    if part is not None and not part.empty:
        pc = [c for c in _PART_COLS if c in part.columns]
        p = p.merge(part[pc], left_on=["game_id", "play_id"],
                    right_on=["nflverse_game_id", "play_id"], how="left")

    def col(name: str) -> pd.Series:
        return p[name] if name in p.columns else pd.Series(None, index=p.index, dtype=object)

    def text(name: str) -> pd.Series:
        s = col(name).astype("object")
        s = s.where(s.notna(), None)
        return s.map(lambda v: v.strip() if isinstance(v, str) and v.strip() else None)

    out = pd.DataFrame({
        "season": int(season),
        "week": pd.to_numeric(p["week"], errors="coerce").astype("int16"),
        "game_id": p["game_id"].values,
        "play_id": pd.to_numeric(p["play_id"], errors="coerce").astype("int32"),
        "team": p["posteam"].values,
        "opponent": p["defteam"].values,
        "passer_id": p["passer_player_id"].values,
        "receiver_id": p["receiver_player_id"].values,
        # nflverse's pass_attempt includes sacks; a sack is a dropback, not an attempt
        "attempt": (_flag(p["pass_attempt"]) & (1 - _flag(p["sack"]))).astype("int8").values,
        "sack": _flag(p["sack"]).values,
        "complete": _flag(p["complete_pass"]).values,
        "yards": pd.to_numeric(p["yards_gained"], errors="coerce").values,
        "air_yards": pd.to_numeric(p["air_yards"], errors="coerce").values,
        "td": _flag(p["pass_touchdown"]).values,
        "interception": _flag(p["interception"]).values,
        "route": text("route").values,
        "man_zone": text("defense_man_zone_type").values,
        "coverage": text("defense_coverage_type").values,
        "box": pd.to_numeric(col("defenders_in_box"), errors="coerce").values,
        "rushers": pd.to_numeric(col("number_of_pass_rushers"), errors="coerce").values,
        "pressure": pd.to_numeric(col("was_pressure").astype("float64"), errors="coerce").values,
        "ttt": pd.to_numeric(col("time_to_throw"), errors="coerce").values,
        "formation": text("offense_formation").values,
        # situation: quarter, down (blank when not a normal down), yards to go,
        # yards from the opponent's goal line, seconds left in the quarter
        "qtr": pd.to_numeric(col("qtr"), errors="coerce").values,
        "down": pd.to_numeric(col("down"), errors="coerce").values,
        "ydstogo": pd.to_numeric(col("ydstogo"), errors="coerce").values,
        "yardline": pd.to_numeric(col("yardline_100"), errors="coerce").values,
        "clock": pd.to_numeric(col("quarter_seconds_remaining"), errors="coerce").values,
    })
    return out[COLUMNS].reset_index(drop=True)


class PassPlays(NflDataset):
    name = "pass_plays"
    label = "nflverse pass plays with defensive scheme"
    EARLIEST = EARLIEST

    def _asset(self, season: str) -> str:
        # In-season the play-by-play file is what changes (participation is
        # frozen), so it is the asset the refresher probes.
        return f"pbp/play_by_play_{season}.parquet"

    def fetch(self, season: str, reload: bool = False) -> pd.DataFrame:
        from . import api, cache

        season = str(season)
        try:
            yr = int(season)
        except (TypeError, ValueError):
            return pd.DataFrame()
        if yr < EARLIEST:
            return pd.DataFrame()

        if not reload:
            cached = cache.load(self.name, season)
            if cached is not None:
                return cached
        if api.on_render():
            return pd.DataFrame()           # committed snapshots only

        try:
            pbp = api.fetch_release_parquet(self._asset(season), columns=_PBP_COLS,
                                            reload=reload)
        except Exception:
            pbp = None
        try:
            part = api.fetch_release_parquet(
                f"pbp_participation/pbp_participation_{season}.parquet",
                columns=_PART_COLS, reload=reload)
        except Exception:
            part = None                     # not published yet: plays with blank scheme

        out = build(pbp, part, yr) if pbp is not None else pd.DataFrame()
        if out.empty:
            if reload:
                cached = cache.load(self.name, season)
                if cached is not None:
                    return cached
            return pd.DataFrame()
        cache.save(self.name, season, out)
        return out
