"""One row per rushing play with the defense's look, for Player Analytics.

`player_games` is one row per player per game, so it cannot answer "against a
stacked box" or "on runs to the left": those are facts about a single carry.  This
is the rushing counterpart of `pass_plays`.

Built from two stored raw nflverse files per season:

  * `pbp/play_by_play_<season>.parquet`: the rusher, the result, the situation;
  * `pbp_participation/pbp_participation_<season>.parquet`: what the defense and
    offense lined up in (defenders in the box, both personnel groupings, the
    formation).

Kept: every rushing play (`rush_attempt`), including quarterback scrambles
(flagged) and kneel-downs (flagged, so a total can include or leave them out);
two-point tries and deleted plays are left out.  The run direction and gap come
from play-by-play.  Only the columns the builder reads are stored.

Facts this depends on (checked against the stored files):

  * Defenders in the box and the formation are filled on about 100% of 2016 to
    2025 carries, and both personnel groupings on 100%.  Run direction is about
    99% filled and the gap about 74%: a blank is stored as blank, never guessed.
  * The season has no participation file until nflverse publishes it (it is
    frozen until the postseason ends).  Such a season is stored with its carries
    and a blank defense look, so it matches no filter that uses one.
  * Offense personnel is stored as the usual two digits, running backs then tight
    ends ("11" is one back, one tight end, three receivers).  A package that is
    not five eligible-plus-line shapes the usual way (a sixth lineman, two
    quarterbacks) is stored as "Other", not folded into a standard code.

Snapshots are committed under `data/sources/nflverse/rush_plays/<season>.parquet`.
On Render a missing snapshot is NOT rebuilt (no raw parsing there): the frame is
empty.
"""
from __future__ import annotations

import re

import pandas as pd

from .base import NflDataset

EARLIEST = 2016

_PBP_COLS = [
    "game_id", "play_id", "week", "season", "posteam", "defteam", "rush_attempt",
    "rusher_player_id", "qb_scramble", "qb_kneel", "two_point_attempt", "play_deleted",
    "rushing_yards", "rush_touchdown", "first_down", "run_location", "run_gap",
    "qtr", "down", "ydstogo", "yardline_100", "quarter_seconds_remaining",
    "score_differential", "fumble_lost",
]
_PART_BASE = [
    "nflverse_game_id", "play_id", "defenders_in_box", "offense_personnel",
    "defense_personnel", "offense_formation",
]
#: 2023 on also carries the position of every player on the field.  The personnel
#: strings change shape that year (detailed positions, and the offense string can
#: even list defenders), so from then on the groupings are counted from these lists.
_PART_POS = ["offense_positions", "defense_positions"]
_PART_COLS = _PART_BASE + _PART_POS

#: stored columns, in order
COLUMNS = ["season", "week", "game_id", "play_id", "team", "opponent", "rusher_id",
           "scramble", "kneel", "yards", "td", "first_down", "fumble_lost", "box",
           "off_personnel", "def_personnel", "formation", "run_location", "run_gap",
           "qtr", "down", "ydstogo", "yardline", "clock", "score_diff"]

_GROUP = re.compile(r"(\d+)\s*(OL|RB|TE|WR|QB|DL|LB|DB)")
_OL = ("T", "G", "C", "OL", "OT", "OG")
_DL = ("DE", "DT", "NT", "DL")
_LB = ("MLB", "ILB", "OLB", "LB")
_DB = ("CB", "S", "FS", "SS", "DB")


def _counts(text) -> dict:
    return {pos: int(n) for n, pos in _GROUP.findall(text)} if isinstance(text, str) else {}


def offense_code(text) -> str | None:
    """"1 RB, 1 TE, 3 WR" -> "11".  None when there is no grouping, "Other" when
    the package does not add up to the usual five eligible receivers and backs
    (so a sixth lineman is not read as a standard code)."""
    c = _counts(text)
    if not c:
        return None
    rb, te, wr = c.get("RB", 0), c.get("TE", 0), c.get("WR", 0)
    if c.get("OL", 5) != 5 or c.get("QB", 1) != 1 or rb + te + wr != 5:
        return "Other"
    return f"{rb}{te}"


def _tally(positions) -> dict:
    out: dict = {}
    if isinstance(positions, str) and positions:
        for tok in positions.split(";"):
            out[tok] = out.get(tok, 0) + 1
    return out


def offense_code_from_positions(positions) -> str | None:
    """The same code counted from a list of the on-field players' positions
    ("QB;RB;TE;WR;WR;WR;T;T;G;G;C").  A back is an RB or FB.  Anything that is not
    one quarterback, five linemen and five backs, tight ends and receivers is
    "Other"."""
    c = _tally(positions)
    if not c:
        return None
    rb, te, wr = c.get("RB", 0) + c.get("FB", 0), c.get("TE", 0), c.get("WR", 0)
    if sum(c.get(k, 0) for k in _OL) != 5 or c.get("QB", 0) != 1 or rb + te + wr != 5:
        return "Other"
    return f"{rb}{te}"


def defense_code_from_positions(positions) -> str | None:
    """"4-2-5" counted from the defenders' positions; None when there is no list."""
    c = _tally(positions)
    if not c:
        return None
    return "-".join(str(sum(c.get(k, 0) for k in grp)) for grp in (_DL, _LB, _DB))


def defense_code(text) -> str | None:
    """"4 DL, 2 LB, 5 DB" -> "4-2-5"; None when there is no grouping."""
    c = _counts(text)
    if not c or not {"DL", "LB", "DB"} <= set(c):
        return None
    return f"{c['DL']}-{c['LB']}-{c['DB']}"


def _flag(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce").fillna(0).astype("int8")


def _personnel(positions: pd.Series, strings: pd.Series, from_positions, from_string) -> pd.Series:
    """The grouping from the position list where the file has one (2023 on), else
    from the personnel string (2016 to 2022)."""
    a = positions.map(from_positions)
    b = strings.map(from_string)
    return a.where(a.notna(), b)


def build(pbp: pd.DataFrame, part: pd.DataFrame | None, season: int) -> pd.DataFrame:
    """The rushing plays of one season.  `part` may be None or empty (no
    participation file yet): the defense look is then blank."""
    if pbp is None or pbp.empty:
        return pd.DataFrame(columns=COLUMNS)
    p = pbp.copy()
    keep = pd.to_numeric(p["rush_attempt"], errors="coerce").fillna(0).eq(1)
    if "two_point_attempt" in p.columns:
        keep &= pd.to_numeric(p["two_point_attempt"], errors="coerce").fillna(0).ne(1)
    if "play_deleted" in p.columns:
        keep &= pd.to_numeric(p["play_deleted"], errors="coerce").fillna(0).ne(1)
    p = p[keep & p["rusher_player_id"].notna()]
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
        "rusher_id": p["rusher_player_id"].values,
        "scramble": _flag(col("qb_scramble")).values,
        "kneel": _flag(col("qb_kneel")).values,
        "yards": pd.to_numeric(p["rushing_yards"], errors="coerce").values,
        "td": _flag(col("rush_touchdown")).values,
        "first_down": _flag(col("first_down")).values,
        "fumble_lost": _flag(col("fumble_lost")).values,
        "box": pd.to_numeric(col("defenders_in_box"), errors="coerce").values,
        "off_personnel": _personnel(col("offense_positions"), col("offense_personnel"),
                                    offense_code_from_positions, offense_code).values,
        "def_personnel": _personnel(col("defense_positions"), col("defense_personnel"),
                                    defense_code_from_positions, defense_code).values,
        "formation": text("offense_formation").values,
        "run_location": text("run_location").str.title().values,
        "run_gap": text("run_gap").str.title().values,
        "qtr": pd.to_numeric(col("qtr"), errors="coerce").values,
        "down": pd.to_numeric(col("down"), errors="coerce").values,
        "ydstogo": pd.to_numeric(col("ydstogo"), errors="coerce").values,
        "yardline": pd.to_numeric(col("yardline_100"), errors="coerce").values,
        "clock": pd.to_numeric(col("quarter_seconds_remaining"), errors="coerce").values,
        "score_diff": pd.to_numeric(col("score_differential"), errors="coerce").values,
    })
    return out[COLUMNS].reset_index(drop=True)


class RushPlays(NflDataset):
    name = "rush_plays"
    label = "nflverse rushing plays with the defense's look"
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
        part = None                         # not published yet: carries with a blank look
        for cols in (_PART_COLS, _PART_BASE):   # older files have no position lists
            try:
                part = api.fetch_release_parquet(
                    f"pbp_participation/pbp_participation_{season}.parquet",
                    columns=cols, reload=reload)
                break
            except Exception:
                continue

        out = build(pbp, part, yr) if pbp is not None else pd.DataFrame()
        if out.empty:
            if reload:
                cached = cache.load(self.name, season)
                if cached is not None:
                    return cached
            return pd.DataFrame()
        cache.save(self.name, season, out)
        return out
