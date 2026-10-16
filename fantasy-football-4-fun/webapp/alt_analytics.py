"""Alternative Analytics: answer a specified question about one player's NFL history.

A question is a small spec (measures, filters, a group-by) run by ONE generic
function over the `player_games` table, so a new question is a new menu entry
and not a new function.  The menus below are fixed; nothing here takes free
text into a query.

    spec = {
        "measures": ["targets", "receiving_yards"],
        "agg": "total",                 # total | per_game
        "filters": {"opponent": "KC", "seasons": [2018, 2024],
                    "home_away": "Away", "game_types": ["REG"]},
        "group_by": "season",           # None | opponent | season | home_away | game_type | week
    }

League-free and Python-webapp-only; no `Season` or Sleeper league is needed.
"""
from __future__ import annotations

import pandas as pd

from webapp.sources import nflref

FIRST_SEASON = nflref.DATASETS["player_games"].EARLIEST

GAME_TYPES = ["REG", "WC", "DIV", "CON", "SB"]
GAME_TYPE_LABELS = {"REG": "Regular season", "WC": "Wild card", "DIV": "Divisional",
                    "CON": "Conference championship", "SB": "Super Bowl"}
HOME_AWAY = ["Home", "Away", "Neutral"]

#: group-by menu: key -> label (one row per game column value)
GAME_GROUPS = {
    "opponent": "Opponent", "season": "Season", "home_away": "Home or away",
    "game_type": "Game type", "week": "Week",
}

# -- play-level filters ----------------------------------------------------------
# Facts about a single pass play (the defense's scheme, pressure, the route the
# targeted receiver ran), from the `pass_plays` dataset (2016 on; coverage 2018
# on).  A play filter splits the player's PASS plays, so only the passing and
# receiving measures can be answered under one; every other measure is a dash.
# A play with a blank value never matches a filter or a group.

#: key -> (label, column, {menu label: stored value})
PLAY_EQ = {
    "man_zone": ("Man or zone", "man_zone",
                 {"Man": "MAN_COVERAGE", "Zone": "ZONE_COVERAGE"}),
    "coverage": ("Coverage type", "coverage",
                 {"Cover 0": "COVER_0", "Cover 1": "COVER_1", "Cover 2": "COVER_2",
                  "2-man": "2_MAN", "Cover 3": "COVER_3", "Cover 4": "COVER_4",
                  "Cover 6": "COVER_6", "Cover 9": "COVER_9", "Combo": "COMBO",
                  "Blown": "BLOWN"}),
    "formation": ("Formation", "formation",
                  {"Shotgun": "SHOTGUN", "Under center": "UNDER CENTER",
                   "Pistol": "PISTOL"}),
    "route": ("Route (on targets)", "route",
              {"Go": "GO", "Slant": "SLANT", "Screen": "SCREEN",
               "Quick out": "QUICK OUT", "Deep out": "DEEP OUT",
               "Hitch/curl": "HITCH/CURL", "In/dig": "IN/DIG",
               "Shallow cross/drag": "SHALLOW CROSS/DRAG", "Corner": "CORNER",
               "Post": "POST", "Swing": "SWING", "Texas/angle": "TEXAS/ANGLE",
               "Wheel": "WHEEL"}),
}
#: yes/no filters on a 0/1 play column
PLAY_YESNO = {"pressure": ("Pressure", "pressure")}
#: banded numeric play filters: key -> (label, column, {band: (low, high)}), low
#: inclusive, high exclusive, None = open ended
PLAY_BANDS = {
    "box": ("Defenders in the box", "box", {"6 or fewer": (None, 7), "7": (7, 8),
                                            "8 or more": (8, None)}),
    "rushers": ("Pass rushers", "rushers", {"3 or fewer": (None, 4), "4": (4, 5),
                                            "5 or more (blitz)": (5, None)}),
    "ttt": ("Time to throw", "ttt", {"Under 2.5 s": (None, 2.5), "2.5 to 3.5 s": (2.5, 3.5),
                                     "3.5 s or more": (3.5, None)}),
}
PASS_KEYS = list(PLAY_EQ) + list(PLAY_YESNO) + list(PLAY_BANDS)

# -- run-play filters --------------------------------------------------------------
# Facts about a single carry (the box, the personnel, the formation, which way the
# run went), from the `rush_plays` dataset (2016 on; the defense's look is blank in a
# season nflverse has not published its participation file for).  They share the
# menus above, so the picker, the cleaning and the grouping treat them the same way,
# but they read the rush table: a query uses the pass table or the rush table, never
# both, and only the carry measures can be answered under a run filter.
RUSH_EQ = {
    "run_location": ("Run direction", "run_location",
                     {"Left": "Left", "Middle": "Middle", "Right": "Right"}),
    "run_gap": ("Run gap", "run_gap", {"End": "End", "Tackle": "Tackle", "Guard": "Guard"}),
    "rush_formation": ("Rush formation", "formation",
                       {"Shotgun": "SHOTGUN", "Singleback": "SINGLEBACK",
                        "Under center": "UNDER CENTER", "I-form": "I_FORM",
                        "Pistol": "PISTOL", "Jumbo": "JUMBO", "Wildcat": "WILDCAT",
                        "Empty": "EMPTY"}),
    "off_personnel": ("Offense personnel", "off_personnel",
                      {"11 (1 RB, 1 TE)": "11", "12 (1 RB, 2 TE)": "12",
                       "21 (2 RB, 1 TE)": "21", "13 (1 RB, 3 TE)": "13",
                       "22 (2 RB, 2 TE)": "22", "10 (1 RB, no TE)": "10",
                       "20 (2 RB, no TE)": "20", "Other": "Other"}),
    "def_personnel": ("Defense personnel", "def_personnel",
                      {"4-2-5": "4-2-5", "4-3-4": "4-3-4", "3-4-4": "3-4-4",
                       "3-3-5": "3-3-5", "2-4-5": "2-4-5", "2-3-6": "2-3-6",
                       "4-1-6": "4-1-6", "5-2-4": "5-2-4"}),
    "carry_type": ("Carry type", "carry_type",
                   {"Designed run": "Run", "Scramble": "Scramble", "Kneel": "Kneel"}),
}
RUSH_BANDS = {
    "rush_box": ("Defenders in the box (runs)", "box",
                 {"6 or fewer (light)": (None, 7), "7": (7, 8),
                  "8 or more (stacked)": (8, None)}),
}
PLAY_EQ.update(RUSH_EQ)
PLAY_BANDS.update(RUSH_BANDS)
RUSH_KEYS = list(RUSH_EQ) + list(RUSH_BANDS)
PLAY_KEYS = list(PLAY_EQ) + list(PLAY_YESNO) + list(PLAY_BANDS)
#: which table each play key reads
PLAY_TABLE = {**{k: "pass" for k in PASS_KEYS}, **{k: "rush" for k in RUSH_KEYS}}
PLAY_COLUMN = {**{k: v[1] for k, v in PLAY_EQ.items()},
               **{k: v[1] for k, v in PLAY_YESNO.items()},
               **{k: v[1] for k, v in PLAY_BANDS.items()}}
PLAY_LABELS = {**{k: v[0] for k, v in PLAY_EQ.items()},
               **{k: v[0] for k, v in PLAY_YESNO.items()},
               **{k: v[0] for k, v in PLAY_BANDS.items()}}
#: group-by values that read the play table
PLAY_GROUPS = {k: PLAY_LABELS[k] for k in PLAY_KEYS}
PASS_GROUPS = {k: PLAY_LABELS[k] for k in PASS_KEYS}
RUSH_GROUPS = {k: PLAY_LABELS[k] for k in RUSH_KEYS}
GROUPS = {**GAME_GROUPS, **PLAY_GROUPS}

#: Measures a pass-play query can answer (the rest read the whole game).
PLAY_MEASURES = {"attempts", "completions", "passing_yards", "passing_tds",
                 "interceptions", "completion_rate", "yards_per_attempt",
                 "targets", "receptions", "receiving_yards", "receiving_tds",
                 "receiving_air_yards", "yards_per_target", "yards_per_reception",
                 "catch_rate"}
#: What a run-play query can answer: carries only (a quarterback's scrambles count).
RUSH_PLAY_MEASURES = {"carries", "rushing_yards", "rushing_tds", "yards_per_carry"}
#: the measures each table can answer
TABLE_MEASURES = {"pass": PLAY_MEASURES, "rush": RUSH_PLAY_MEASURES}
#: Passer measures versus receiver measures: a quarterback is read as a passer,
#: everyone else as a receiver.
_PASSER_MEASURES = {"attempts", "completions", "passing_yards", "passing_tds",
                    "interceptions", "completion_rate", "yards_per_attempt"}
#: A season counts toward a play query only when at least this share of its pass
#: plays has a value in every column the query uses.
MIN_PLAY_COVERAGE = 0.5

#: Additive measures: key -> (label, source column)
_COUNTS = {
    "passing_yards": ("Pass yds", "passing_yards"),
    "passing_tds": ("Pass TD", "passing_tds"),
    "interceptions": ("INT", "interceptions"),
    "attempts": ("Pass att", "attempts"),
    "completions": ("Cmp", "completions"),
    "carries": ("Carries", "carries"),
    "rushing_yards": ("Rush yds", "rushing_yards"),
    "rushing_tds": ("Rush TD", "rushing_tds"),
    "targets": ("Targets", "targets"),
    "receptions": ("Rec", "receptions"),
    "receiving_yards": ("Rec yds", "receiving_yards"),
    "receiving_tds": ("Rec TD", "receiving_tds"),
    "receiving_air_yards": ("Air yds", "receiving_air_yards"),
    "touches": ("Touches", "touches"),
    "scrimmage_yards": ("Scrim yds", "scrimmage_yards"),
    "scrimmage_tds": ("Scrim TD", "scrimmage_tds"),
    "fantasy_points_ppr": ("PPR pts", "fantasy_points_ppr"),
    "fantasy_points": ("Std pts", "fantasy_points"),
    "kick_points": ("Kick pts", "kick_points"),
    "fg_made": ("FG made", "fg_made"),
    "fg_att": ("FG att", "fg_att"),
    "fg_missed": ("FG missed", "fg_missed"),
    "fg_made_0_19": ("FG 0-19", "fg_made_0_19"),
    "fg_made_20_29": ("FG 20-29", "fg_made_20_29"),
    "fg_made_30_39": ("FG 30-39", "fg_made_30_39"),
    "fg_made_40_49": ("FG 40-49", "fg_made_40_49"),
    "fg_made_50_59": ("FG 50-59", "fg_made_50_59"),
    "fg_made_60_": ("FG 60+", "fg_made_60_"),
    "pat_made": ("PAT made", "pat_made"),
    "pat_att": ("PAT att", "pat_att"),
    "pat_missed": ("PAT missed", "pat_missed"),
}

#: Best-single-game measures: key -> (label, source column).  The value is the
#: maximum over the games in the group, whatever "Show" says.
_MAXES = {
    "fg_long": ("Long FG", "fg_long"),
}

#: Ratio measures: key -> (label, numerator, denominator).  Always sum / sum.
_RATIOS = {
    "yards_per_target": ("Yds/tgt", "receiving_yards", "targets"),
    "catch_rate": ("Catch %", "receptions", "targets"),
    "yards_per_reception": ("Yds/rec", "receiving_yards", "receptions"),
    "yards_per_carry": ("Yds/carry", "rushing_yards", "carries"),
    "yards_per_attempt": ("Yds/att", "passing_yards", "attempts"),
    "completion_rate": ("Cmp %", "completions", "attempts"),
    "yards_per_completion": ("Yds/cmp", "passing_yards", "completions"),
    "pass_td_rate": ("Pass TD %", "passing_tds", "attempts"),
    "int_rate": ("INT %", "interceptions", "attempts"),
    "rush_td_rate": ("Rush TD %", "rushing_tds", "carries"),
    "rec_td_rate": ("Rec TD %", "receiving_tds", "targets"),
    "adot": ("aDOT", "receiving_air_yards", "targets"),
    "yards_per_air_yard": ("Yds/air yd", "receiving_yards", "receiving_air_yards"),
    "yards_per_touch": ("Yds/touch", "scrimmage_yards", "touches"),
    "ppr_per_touch": ("PPR/touch", "fantasy_points_ppr", "touches"),
    "fg_pct": ("FG %", "fg_made", "fg_att"),
    "pat_pct": ("PAT %", "pat_made", "pat_att"),
}
_PERCENT = {"catch_rate", "completion_rate", "fg_pct", "pat_pct", "pass_td_rate", "int_rate",
            "rush_td_rate", "rec_td_rate"}

MEASURES = {**{k: v[0] for k, v in _COUNTS.items()},
            **{k: v[0] for k, v in _MAXES.items()},
            **{k: v[0] for k, v in _RATIOS.items()}}

#: Hover text for every measure (what it counts, in plain words).
MEASURE_HINTS = {
    "attempts": "Pass attempts",
    "completions": "Pass completions",
    "passing_yards": "Passing yards",
    "passing_tds": "Passing touchdowns",
    "interceptions": "Interceptions thrown",
    "completion_rate": "Completions per pass attempt",
    "yards_per_attempt": "Passing yards per attempt",
    "carries": "Rushing attempts",
    "rushing_yards": "Rushing yards",
    "rushing_tds": "Rushing touchdowns",
    "yards_per_carry": "Rushing yards per carry",
    "targets": "Times targeted with a pass",
    "receptions": "Catches",
    "receiving_yards": "Receiving yards",
    "receiving_tds": "Receiving touchdowns",
    "receiving_air_yards": "Yards the ball traveled in the air on his targets, caught or not",
    "yards_per_target": "Receiving yards per target",
    "yards_per_reception": "Receiving yards per catch",
    "catch_rate": "Catches per target",
    "fg_made": "Field goals made",
    "fg_att": "Field goals attempted",
    "fg_missed": "Field goals missed",
    "fg_made_0_19": "Field goals made from 0 to 19 yards",
    "fg_made_20_29": "Field goals made from 20 to 29 yards",
    "fg_made_30_39": "Field goals made from 30 to 39 yards",
    "fg_made_40_49": "Field goals made from 40 to 49 yards",
    "fg_made_50_59": "Field goals made from 50 to 59 yards",
    "fg_made_60_": "Field goals made from 60 yards or more",
    "pat_made": "Extra points made",
    "pat_att": "Extra points attempted",
    "pat_missed": "Extra points missed",
    "fg_pct": "Field goals made per attempt",
    "pat_pct": "Extra points made per attempt",
    "fg_long": "Longest field goal made (a maximum, not a total)",
    "touches": "Carries plus catches",
    "scrimmage_yards": "Rushing yards plus receiving yards",
    "scrimmage_tds": "Rushing plus receiving touchdowns",
    "kick_points": "Points from kicking: 3 per field goal and 1 per extra point",
    "yards_per_completion": "Passing yards per completion",
    "pass_td_rate": "Passing touchdowns per pass attempt",
    "int_rate": "Interceptions per pass attempt (lower is better)",
    "rush_td_rate": "Rushing touchdowns per carry",
    "rec_td_rate": "Receiving touchdowns per target",
    "adot": "Average depth of target: air yards per target",
    "yards_per_air_yard": "Receiving yards per air yard on his targets (above 1 means he gained more than the ball traveled)",
    "yards_per_touch": "Scrimmage yards per touch",
    "ppr_per_touch": "Full-PPR fantasy points per touch",
    "fantasy_points_ppr": "Fantasy points with one point per catch (full PPR)",
    "fantasy_points": "Fantasy points with no points for catches (standard)",
}

#: Hover text for the form controls.
CONTROL_HINTS = {
    "agg": "Total adds the numbers up.  Per game divides by the games that recorded the stat.",
    "group_by": "One row per opponent, season, site, game type or week.  Career gives a single row.",
    "opponent": "Only games against this team.  Oakland, San Diego and St. Louis count as LV, LAC and LA.",
    "home_away": "Home, Away, or Neutral (Super Bowls and international games).",
    "season_from": "First season to include.",
    "season_to": "Last season to include.",
    "game_types": "None ticked means all games.",
    "clear_filters": "Back to every opponent, site, season and game type.",
    "filter_picker": "Tick what you want on the form: measure groups, how to show them, and filters.  Only ticked items show; unticking one clears it.  Games with no recorded value, such as temperature in a dome, never match a band.",
    "add_card": "Adds a card with the stats and grouping ticked above.  It follows the filters on this page, and Run refreshes it.",
    "reset": "Clear every measure, filter and grouping back to this player's defaults.",
    "run": "Looks at this player's carries only (2016 on; the defense's look is missing for a season nflverse has not published it for).  Carries, rushing yards, touchdowns and yards per carry answer it; other measures show a dash.  A carry with no recorded value never matches.  Cannot be combined with a Play filter.",
    "play": "Looks at this player's pass plays only (2016 on; coverage 2018 on).  Passing and receiving measures answer it; other measures show a dash.  A play with no recorded value never matches.",
    "man_zone": "Whether the defense played man or zone coverage on the play.  Recorded from 2018.",
    "coverage": "The coverage the defense ran (Cover 0, 1, 2, 3, 4, 6, 2-man and the like).  Recorded from 2018.",
    "box": "Defenders lined up in the box at the snap.",
    "rushers": "Defenders who rushed the passer.  5 or more is a blitz.",
    "pressure": "Whether the passer was pressured on the play.",
    "ttt": "Seconds from the snap to the throw.",
    "route": "The route the targeted receiver ran.  Only the target's route is recorded, so this reads targets.",
    "formation": "The offense's formation at the snap.",
}


#: what each position cares about first
_DEFAULT_MEASURES = {
    "QB": ["attempts", "completions", "passing_yards", "passing_tds", "interceptions",
           "rushing_yards"],
    "RB": ["carries", "rushing_yards", "rushing_tds", "targets", "receptions",
           "receiving_yards", "receiving_tds"],
    "WR": ["targets", "receptions", "receiving_yards", "receiving_tds",
           "yards_per_target", "catch_rate"],
    "TE": ["targets", "receptions", "receiving_yards", "receiving_tds",
           "yards_per_target", "catch_rate"],
    "K": ["fg_made", "fg_att", "fg_pct", "fg_long", "pat_made", "pat_att"],
}

AGGS = {"total": "Total", "per_game": "Per game"}


# -- the player table -----------------------------------------------------------

_index_cache: pd.DataFrame | None = None
_player_cache: dict[str, pd.DataFrame] = {}
_PLAYER_CACHE_MAX = 8


def seasons_available() -> list[int]:
    """Seasons with a snapshot, oldest first."""
    from webapp.sources.nflref import cache
    root = cache._NFLVERSE_DIR / "player_games"
    out = []
    if root.is_dir():
        for p in root.glob("*.parquet"):
            if p.stem.isdigit():
                out.append(int(p.stem))
    return sorted(out)


def clear_cache() -> None:
    global _index_cache
    _index_cache = None
    _player_cache.clear()
    _play_cache.clear()
    _play_coverage.clear()
    _rush_coverage.clear()


def _player_index() -> pd.DataFrame:
    """One row per player: id, name, position, last team, first and last season, games."""
    global _index_cache
    if _index_cache is not None:
        return _index_cache
    parts = []
    for yr in seasons_available():
        df = nflref.load("player_games", str(yr))
        if df.empty:
            continue
        parts.append(df[["player_id", "player_display_name", "position", "team",
                         "season", "week"]])
    if not parts:
        return pd.DataFrame(columns=["player_id", "name", "position", "team",
                                     "first_season", "last_season", "games"])
    allp = pd.concat(parts, ignore_index=True).sort_values(["season", "week"])
    g = allp.groupby("player_id", sort=False)
    idx = g.agg(name=("player_display_name", "last"), position=("position", "last"),
                team=("team", "last"), first_season=("season", "min"),
                last_season=("season", "max"), games=("week", "size")).reset_index()
    _index_cache = idx
    return idx


#: Search results per page.
PAGE_SIZE = 12

#: Search result columns that can be sorted: key -> (label, first direction).
SEARCH_SORTS = {
    "name": ("Player", "asc"), "position": ("Pos", "asc"), "team": ("Team", "asc"),
    "seasons": ("Seasons", "desc"), "games": ("Games", "desc"),
}
SEARCH_SORT_DEFAULT = ("seasons", "desc")

#: Fantasy order for the Pos column (anything else sorts after these).
_POS_ORDER = {p: i for i, p in enumerate(["QB", "RB", "FB", "WR", "TE", "K"])}


def search_players(query: str, limit: int | None = None) -> list[dict]:
    """Players whose name contains every word of `query`, most recent and most
    games first, all of them unless `limit` is given.  Needs at least two
    characters."""
    q = (query or "").strip().lower()
    if len(q) < 2:
        return []
    idx = _player_index()
    if idx.empty:
        return []
    names = idx["name"].fillna("").str.lower()
    mask = pd.Series(True, index=idx.index)
    for word in q.split():
        mask &= names.str.contains(word, regex=False)
    hit = idx[mask].sort_values(["last_season", "games"], ascending=False)
    if limit:
        hit = hit.head(limit)
    return [{"player_id": r.player_id, "name": r.name, "position": r.position,
             "team": r.team, "first_season": int(r.first_season),
             "last_season": int(r.last_season), "games": int(r.games)}
            for r in hit.itertuples()]


def search_page(query: str, sort: str = "", direction: str = "", page: int = 1,
                per_page: int = PAGE_SIZE) -> dict:
    """One page of search results, sorted.  The sort covers the WHOLE result set
    before it is cut into pages, so page 2 continues page 1's order.

    `sort` is a key of SEARCH_SORTS (an unknown one falls back to the default)
    and `direction` is asc or desc (blank means that column's first direction).
    Ties never move: equal rows fall back to most games, then name A to Z, so
    two clicks on the same header show the same rows in the same places.

    Returns {rows, total, page, pages, per_page, first, last, sort, direction}
    with `first` and `last` the 1-based positions of the rows on this page.
    """
    found = search_players(query)
    if sort not in SEARCH_SORTS:
        sort, direction = SEARCH_SORT_DEFAULT
    if direction not in ("asc", "desc"):
        direction = SEARCH_SORTS[sort][1]

    def main_key(r: dict):
        if sort == "name":
            return (r["name"] or "").casefold()
        if sort == "position":
            return _POS_ORDER.get(r["position"], len(_POS_ORDER)), r["position"] or ""
        if sort == "team":
            return (r["team"] or "").casefold()
        if sort == "seasons":
            return r["last_season"], r["first_season"]
        return r["games"]

    rows = sorted(found, key=lambda r: (r["name"] or "").casefold())     # last tie-break
    rows.sort(key=lambda r: r["games"], reverse=True)                    # then most games
    rows.sort(key=main_key, reverse=(direction == "desc"))               # then the column
    total = len(rows)
    per_page = max(1, int(per_page))
    pages = max(1, -(-total // per_page))
    page = min(max(1, int(page or 1)), pages)
    start = (page - 1) * per_page
    return {"rows": rows[start:start + per_page], "total": total, "page": page,
            "pages": pages, "per_page": per_page,
            "first": start + 1 if total else 0, "last": min(start + per_page, total),
            "sort": sort, "direction": direction}


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Columns built from the stored ones so they can be summed and divided like any
    other: touches, scrimmage yards and touchdowns, and kicking points.  A value is
    missing only when every part is missing, so a year with no recorded targets is
    never read as zero."""
    if df.empty:
        return df
    df = df.copy()

    def num(col: str):
        return pd.to_numeric(df[col], errors="coerce") if col in df.columns else None

    def add(name: str, parts: list[tuple[str, float]]) -> None:
        cols = [(num(c), w) for c, w in parts]
        if any(c is None for c, _ in cols):
            return
        total = sum(c.fillna(0) * w for c, w in cols)
        total[pd.concat([c.isna() for c, _ in cols], axis=1).all(axis=1)] = float("nan")
        df[name] = total

    add("touches", [("carries", 1), ("receptions", 1)])
    add("scrimmage_yards", [("rushing_yards", 1), ("receiving_yards", 1)])
    add("scrimmage_tds", [("rushing_tds", 1), ("receiving_tds", 1)])
    add("kick_points", [("fg_made", 3), ("pat_made", 1)])
    return df


def load_player(player_id: str) -> pd.DataFrame:
    """Every game this player has in the table, oldest first."""
    pid = (player_id or "").strip()
    if not pid:
        return pd.DataFrame()
    if pid in _player_cache:
        return _player_cache[pid]
    parts = []
    for yr in seasons_available():
        df = nflref.load("player_games", str(yr))
        if df.empty:
            continue
        sub = df[df["player_id"] == pid]
        if not sub.empty:
            parts.append(sub)
    out = (pd.concat(parts, ignore_index=True).sort_values(["season", "week"])
           .reset_index(drop=True) if parts else pd.DataFrame())
    out = add_derived(out)
    if len(_player_cache) >= _PLAYER_CACHE_MAX:
        _player_cache.pop(next(iter(_player_cache)))
    _player_cache[pid] = out
    return out


# -- menus that depend on the player --------------------------------------------

def available_measures(games: pd.DataFrame) -> list[str]:
    """Measure keys this player has any production in, so a receiver is not
    offered passing yards.  Ratios need a nonzero denominator."""
    if games.empty:
        return []
    out = []
    for key, (_, col) in _COUNTS.items():
        if col in games.columns and pd.to_numeric(games[col], errors="coerce").fillna(0).abs().sum() > 0:
            out.append(key)
    for key, (_, col) in _MAXES.items():
        if col in games.columns and pd.to_numeric(games[col], errors="coerce").fillna(0).max() > 0:
            out.append(key)
    for key, (_, num, den) in _RATIOS.items():
        if key and all(c in games.columns for c in (num, den)) and \
                pd.to_numeric(games[den], errors="coerce").fillna(0).sum() > 0:
            out.append(key)
    return out


#: Measure headings for the builder, in display order.
MEASURE_GROUPS = [
    ("Passing", ["attempts", "completions", "passing_yards", "passing_tds",
                 "interceptions", "completion_rate", "yards_per_attempt",
                 "yards_per_completion", "pass_td_rate", "int_rate"]),
    ("Rushing", ["carries", "rushing_yards", "rushing_tds", "yards_per_carry",
                 "rush_td_rate"]),
    ("Receiving", ["targets", "receptions", "receiving_yards", "receiving_tds",
                   "receiving_air_yards", "yards_per_target", "yards_per_reception",
                   "catch_rate", "adot", "yards_per_air_yard", "rec_td_rate"]),
    ("Scrimmage", ["touches", "scrimmage_yards", "scrimmage_tds", "yards_per_touch"]),
    ("Kicking", ["fg_made", "fg_att", "fg_missed", "fg_made_0_19", "fg_made_20_29",
                 "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
                 "pat_made", "pat_att", "pat_missed", "kick_points", "fg_pct", "pat_pct",
                 "fg_long"]),
    ("Fantasy", ["fantasy_points_ppr", "fantasy_points", "ppr_per_touch"]),
]


def grouped_measures(games: pd.DataFrame, position: str | None = None) -> list[dict]:
    """Every measure under Passing / Rushing / Receiving / Kicking / Fantasy
    headings, as [{label, used, items: [(key, label, used)]}].  The order is the
    same for every player (so the form never moves around); counts come first
    in each group, then rates, then a maximum.  `used` is False for a measure
    the player has no production in (the builder greys it out instead of hiding
    it), and a group's `used` is True when any of its measures is.  `position`
    is accepted for callers that pass it and does not change the order."""
    have = set(available_measures(games))
    out = []
    for name, keys in MEASURE_GROUPS:
        items = [(k, MEASURES[k], k in have) for k in keys]
        out.append({"label": name, "used": any(u for _, _, u in items), "items": items})
    return out


def default_measures(position: str | None, games: pd.DataFrame) -> list[str]:
    have = set(available_measures(games))
    base = [m for m in _DEFAULT_MEASURES.get(position or "", []) if m in have]
    return base or [m for m in MEASURES if m in have][:6]


def reset_fill(games: pd.DataFrame, position: str | None) -> dict:
    """The builder control values when a player is first opened: the position's
    default measures, a total, no grouping and no filters.  Same shape as a
    preset's fill, so the Reset chip is applied by the same script."""
    return {"measures": default_measures(position, games), "agg": "total",
            "group_by": "", "opponent": "", "season_from": "", "season_to": "",
            "home_away": "", "game_types": [], "shown": default_shown(position, games)}


def opponents_faced(games: pd.DataFrame) -> list[str]:
    if games.empty or "opponent" not in games.columns:
        return []
    return sorted(games["opponent"].dropna().unique().tolist())


def coverage(games: pd.DataFrame) -> dict:
    """Which seasons and games the table holds for this player.  The latest
    season may be partial, so the last week is reported."""
    if games.empty:
        return {"first_season": None, "last_season": None, "last_week": None, "games": 0}
    last = int(games["season"].max())
    return {"first_season": int(games["season"].min()), "last_season": last,
            "last_week": int(games.loc[games["season"] == last, "week"].max()),
            "games": int(len(games))}


# -- game-context filters ("More filters") -------------------------------------------
# Each is a fixed menu or a name matched exactly against the data.  A blank
# value in the data (temperature in a dome, an unrecorded surface) never matches
# a band: unknown is not a number and not a category.

#: filter key -> (label, column, menu or None).  A None menu means a name
#: matched exactly (coach, referee, team) or a quarterback id.
EXTRA_EQ = {
    "team": ("Team", "team", None),
    "coach": ("Head coach", "coach", None),
    "opp_coach": ("Opponent head coach", "opp_coach", None),
    "qb_id": ("Starting QB", "qb_id", None),
    "opp_qb_id": ("Opponent starting QB", "opp_qb_id", None),
    "referee": ("Referee", "referee", None),
    "result": ("Result", "result", ["W", "L", "T"]),
    "roof": ("Roof", "roof", ["outdoors", "dome", "closed", "open"]),
    "surface": ("Surface", "surface", ["Grass", "Turf"]),
    "weekday": ("Day", "weekday", ["Sunday", "Monday", "Thursday", "Saturday",
                                   "Friday", "Wednesday", "Tuesday"]),
}
#: yes/no filters on 0/1 columns
EXTRA_YESNO = {"div_game": ("Division game", "div_game"),
               "overtime": ("Overtime", "overtime")}
#: banded numeric filters: key -> (label, column, {band: (low, high)}), low
#: inclusive and high exclusive, None = open ended
EXTRA_BANDS = {
    "temp": ("Temperature", "temp", {"Under 40": (None, 40), "40 to 70": (40, 70),
                                     "Over 70": (70, None)}),
    "wind": ("Wind", "wind", {"Under 10": (None, 10), "10 to 15": (10, 15),
                              "15 or more": (15, None)}),
    "rest": ("Rest", "rest", {"Short (6 days or fewer)": (None, 7),
                              "Normal (7 to 9)": (7, 10),
                              "Long (10 or more)": (10, None)}),
}
ROLES = ["Favorite", "Underdog"]
EXTRA_KEYS = (list(EXTRA_EQ) + list(EXTRA_YESNO) + list(EXTRA_BANDS)
              + ["role", "weeks"] + list(PLAY_KEYS))


#: The picker: every control the builder can show, grouped.  A control's field is
#: on screen only while its box is ticked; unticking it clears its value.  Presets
#: (Quick picks) are not in the picker.
def _measure_group_key(label: str) -> str:
    return "m_" + label.lower()


PICKER_MENU = [
    ("Stats", [(_measure_group_key(name), name) for name, _ in MEASURE_GROUPS]),
    ("Results", [("agg", "Total or per game"), ("group_by", "Group by")]),
    ("Game", [("opponent", "Opponent"), ("home_away", "Site"), ("seasons", "Seasons"),
              ("game_types", "Games"), ("weeks", "Weeks"), ("result", "Result"),
              ("role", "Favorite or underdog"), ("weekday", "Day"),
              ("div_game", "Division game"), ("overtime", "Overtime")]),
    ("People", [("team", "Team"), ("coach", "Head coach"), ("opp_coach", "Opp. head coach"),
                ("qb_id", "Starting QB"), ("opp_qb_id", "Opp. starting QB"),
                ("referee", "Referee")]),
    ("Conditions", [("roof", "Roof"), ("surface", "Surface"), ("temp", "Temperature"),
                    ("wind", "Wind"), ("rest", "Rest")]),
    ("Play", [("man_zone", "Man or zone"), ("coverage", "Coverage type"),
              ("box", "Defenders in the box"), ("rushers", "Pass rushers"),
              ("pressure", "Pressure"), ("ttt", "Time to throw"),
              ("route", "Route (on targets)"), ("formation", "Formation")]),
    ("Run", [("rush_box", "Defenders in the box"), ("off_personnel", "Offense personnel"),
             ("def_personnel", "Defense personnel"), ("rush_formation", "Formation"),
             ("run_location", "Run direction"), ("run_gap", "Run gap"),
             ("carry_type", "Carry type")]),
]
PICKER_KEYS = [k for _, items in PICKER_MENU for k, _ in items]
#: controls that are not filters: they never count toward the "filters in use" badge
PLAIN_KEYS = {k for g, items in PICKER_MENU if g in ("Stats", "Results") for k, _ in items}
#: shown the first time a player is opened: every measure group and both Show
#: controls, as before, plus the four everyday filters
DEFAULT_SHOWN = ([k for k in PICKER_KEYS if k in PLAIN_KEYS]
                 + ["opponent", "home_away", "seasons", "game_types"])


#: The everyday filters every position starts with.
_COMMON_FILTERS = ["opponent", "home_away", "seasons", "game_types"]
#: Extra filters that matter for a position, shown on first open.  A quarterback's
#: game is shaped by result and wind; a back's by result and whether he was the
#: favorite; a receiver's by who threw to him and by wind; a kicker's by the
#: conditions he kicks in.  Everything else is still one tick away in the picker.
_POSITION_FILTERS = {
    "QB": ["result", "wind"],
    "RB": ["result", "role"],
    "WR": ["qb_id", "wind"],
    "TE": ["qb_id", "wind"],
    "K": ["roof", "surface", "temp", "wind"],
}


def default_shown(position: str | None, games: pd.DataFrame | None = None) -> list[str]:
    """The controls on screen when a player is first opened, in picker order: the
    measure groups that hold the position's default measures, both Show controls,
    the everyday filters, and the position's own extra filters.  An unknown
    position gets every measure group."""
    wanted = _DEFAULT_MEASURES.get(position or "")
    if wanted:
        groups = {_measure_group_key(name) for name, keys in MEASURE_GROUPS
                  if any(k in wanted for k in keys)}
    else:
        groups = {k for k in PLAIN_KEYS if k.startswith("m_")}
    keep = (groups | {"agg", "group_by"} | set(_COMMON_FILTERS)
            | set(_POSITION_FILTERS.get(position or "", [])))
    return [k for k in PICKER_KEYS if k in keep]


def shown_fields(requested: list[str] | None, was_set: bool, active: set[str],
                 default: list[str] | None = None) -> list[str]:
    """Which control fields to draw.  `requested` is the ticked boxes from the
    form and `was_set` says the form had the picker at all (so an empty list means
    the user unticked everything); without it `default` (the position's defaults)
    applies.  A control that has a value is always shown, so a URL or a preset can
    never leave an applied choice hidden."""
    base = ([k for k in (requested or []) if k in PICKER_KEYS] if was_set
            else list(default if default is not None else DEFAULT_SHOWN))
    return [k for k in PICKER_KEYS if k in base or k in active]


def _clean_extras(f: dict) -> dict:
    out: dict = {}
    for key, (_, _, menu) in EXTRA_EQ.items():
        v = f.get(key)
        if v in (None, ""):
            continue
        v = str(v).strip()
        if key == "team":
            v = v.upper()
        if menu is not None and v not in menu:
            raise ValueError(f"unknown {key} value: {v}")
        if v:
            out[key] = v
    for key in EXTRA_YESNO:
        v = f.get(key)
        if v in (None, ""):
            continue
        if v not in ("Yes", "No"):
            raise ValueError(f"unknown {key} value: {v}")
        out[key] = v
    for key, (_, _, bands) in EXTRA_BANDS.items():
        v = f.get(key)
        if v in (None, ""):
            continue
        if v not in bands:
            raise ValueError(f"unknown {key} band: {v}")
        out[key] = v
    role = f.get("role")
    if role not in (None, ""):
        if role not in ROLES:
            raise ValueError(f"unknown role: {role}")
        out["role"] = role
    for key, (_, _, menu) in PLAY_EQ.items():
        v = f.get(key)
        if v in (None, ""):
            continue
        if v not in menu:
            raise ValueError(f"unknown {key} value: {v}")
        out[key] = v
    for key in PLAY_YESNO:
        v = f.get(key)
        if v in (None, ""):
            continue
        if v not in ("Yes", "No"):
            raise ValueError(f"unknown {key} value: {v}")
        out[key] = v
    for key, (_, _, bands) in PLAY_BANDS.items():
        v = f.get(key)
        if v in (None, ""):
            continue
        if v not in bands:
            raise ValueError(f"unknown {key} band: {v}")
        out[key] = v
    weeks = f.get("weeks")
    if weeks:
        if len(weeks) != 2:
            raise ValueError("weeks must be [first, last]")
        lo, hi = sorted((int(weeks[0]), int(weeks[1])))
        out["weeks"] = [lo, hi]
    return out


def _apply_extras(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    def col(name: str) -> pd.Series:
        return df[name] if name in df.columns else pd.Series(None, index=df.index, dtype=object)

    for key, (_, column, _) in EXTRA_EQ.items():
        if f.get(key):
            df = df[col(column).reindex(df.index) == f[key]]
    for key, (_, column) in EXTRA_YESNO.items():
        if f.get(key):
            v = pd.to_numeric(col(column), errors="coerce")
            df = df[v == (1 if f[key] == "Yes" else 0)]
    for key, (_, column, bands) in EXTRA_BANDS.items():
        if f.get(key):
            lo, hi = bands[f[key]]
            v = pd.to_numeric(col(column), errors="coerce")
            keep = v.notna()
            if lo is not None:
                keep &= v >= lo
            if hi is not None:
                keep &= v < hi
            df = df[keep]
    if f.get("role"):
        sp = pd.to_numeric(col("spread"), errors="coerce")
        df = df[(sp < 0) if f["role"] == "Favorite" else (sp > 0)]
    if f.get("weeks"):
        lo, hi = f["weeks"]
        df = df[(df["week"] >= lo) & (df["week"] <= hi)]
    return df


def context_options(games: pd.DataFrame) -> dict:
    """The names this player has actually played with or against, for the
    More filters menus.  Quarterbacks carry their id as the value."""
    def names(col: str) -> list[str]:
        if games.empty or col not in games.columns:
            return []
        return sorted(games[col].dropna().astype(str).unique().tolist())

    def qbs(id_col: str, name_col: str) -> list[dict]:
        if games.empty or id_col not in games.columns:
            return []
        d = games[[id_col, name_col]].dropna().drop_duplicates(id_col)
        return sorted(({"value": str(i), "label": str(n)} for i, n in zip(d[id_col], d[name_col])),
                      key=lambda o: o["label"])

    return {"team": names("team"), "coach": names("coach"), "opp_coach": names("opp_coach"),
            "referee": names("referee"), "qb_id": qbs("qb_id", "qb"),
            "opp_qb_id": qbs("opp_qb_id", "opp_qb")}


# -- the one generic query function ---------------------------------------------

def _clean(spec: dict) -> dict:
    measures = list(spec.get("measures") or [])
    for m in measures:
        if m not in MEASURES:
            raise ValueError(f"unknown measure: {m}")
    if not measures:
        raise ValueError("choose at least one measure")
    agg = spec.get("agg") or "total"
    if agg not in AGGS:
        raise ValueError(f"unknown aggregation: {agg}")
    group = spec.get("group_by") or None
    if group is not None and group not in GROUPS:
        raise ValueError(f"unknown grouping: {group}")
    f = dict(spec.get("filters") or {})
    ha = f.get("home_away") or None
    if ha is not None and ha not in HOME_AWAY:
        raise ValueError(f"unknown home or away value: {ha}")
    gts = f.get("game_types") or None
    if gts is not None:
        gts = list(gts)
        bad = [g for g in gts if g not in GAME_TYPES]
        if bad:
            raise ValueError(f"unknown game type: {bad[0]}")
    seasons = f.get("seasons") or None
    if seasons is not None:
        if len(seasons) != 2:
            raise ValueError("seasons must be [first, last]")
        seasons = [int(seasons[0]), int(seasons[1])]
        if seasons[0] > seasons[1]:
            seasons = [seasons[1], seasons[0]]
    opp = f.get("opponent") or None
    if opp is not None:
        opp = str(opp).strip().upper() or None
    filters = {"opponent": opp, "seasons": seasons, "home_away": ha,
               "game_types": gts, **_clean_extras(f)}
    tables = {PLAY_TABLE[k] for k in PLAY_KEYS if filters.get(k)}
    if group in PLAY_TABLE:
        tables.add(PLAY_TABLE[group])
    if len(tables) > 1:
        raise ValueError("pass-play and run-play choices cannot be combined")
    return {"measures": measures, "agg": agg, "group_by": group, "filters": filters}


def apply_filters(games: pd.DataFrame, filters: dict) -> pd.DataFrame:
    df = games
    if filters.get("opponent"):
        df = df[df["opponent"] == filters["opponent"]]
    if filters.get("seasons"):
        lo, hi = filters["seasons"]
        df = df[(df["season"] >= lo) & (df["season"] <= hi)]
    if filters.get("home_away"):
        df = df[df["home_away"] == filters["home_away"]]
    if filters.get("game_types"):
        df = df[df["game_type"].isin(filters["game_types"])]
    return _apply_extras(df, filters)


def _value(sub: pd.DataFrame, key: str, agg: str) -> float | None:
    """One measure over a group of games.  NaN means "not recorded" (for example
    targets before 2009) and is left out, never read as zero: a total over
    nothing recorded is None, a ratio uses only games where both parts exist,
    and a per-game rate divides by the games that have the stat."""
    if key in _RATIOS:
        _, num, den = _RATIOS[key]
        both = sub[[num, den]].apply(pd.to_numeric, errors="coerce").dropna()
        d = both[den].sum()
        if d == 0:
            return None
        v = float(both[num].sum() / d)
        return v * 100 if key in _PERCENT else v
    if key in _MAXES:
        best = pd.to_numeric(sub[_MAXES[key][1]], errors="coerce").max()
        return None if pd.isna(best) else float(best)
    col = pd.to_numeric(sub[_COUNTS[key][1]], errors="coerce")
    recorded = int(col.notna().sum())
    if recorded == 0:
        return None
    total = float(col.sum())
    if agg == "per_game":
        return total / recorded
    return total


# -- the play-level path ----------------------------------------------------------
# A query with a play filter or a play group-by reads the player's pass plays, not
# his game rows.  The game filters (opponent, seasons, site, ...) still pick the
# games; the play filters then pick the plays inside them.  A season counts only
# when enough of its plays have a value in every column the query uses.

_play_cache: dict[tuple, pd.DataFrame] = {}
_play_coverage: dict[int, dict[str, float]] = {}
_rush_coverage: dict[int, dict[str, float]] = {}      # the same, for the rush table


def play_seasons(table: str = "pass") -> list[int]:
    """Seasons with a pass-play (or, for "rush", a run-play) snapshot, oldest first."""
    from webapp.sources.nflref import cache
    root = cache._NFLVERSE_DIR / ("rush_plays" if table == "rush" else "pass_plays")
    out = []
    if root.is_dir():
        for p in root.glob("*.parquet"):
            if p.stem.isdigit():
                out.append(int(p.stem))
    return sorted(out)


def is_passer(games: pd.DataFrame) -> bool:
    """A quarterback is read as a passer; everyone else as a receiver."""
    return (not games.empty) and str(games["position"].iloc[-1]) == "QB"


def load_plays(player_id: str, passer: bool) -> pd.DataFrame:
    """This player's pass plays, oldest first: every dropback he threw (or was
    sacked on) as a passer, every play he was targeted on as a receiver."""
    key = (player_id, passer)
    if key in _play_cache:
        return _play_cache[key]
    col = "passer_id" if passer else "receiver_id"
    cols = sorted(set(PLAY_COLUMN.values()))
    parts = []
    for yr in play_seasons():
        df = nflref.load("pass_plays", str(yr))
        if df.empty:
            continue
        if yr not in _play_coverage:
            _play_coverage[yr] = {c: float(df[c].notna().mean()) for c in cols if c in df.columns}
        sub = df[df[col] == player_id]
        if not sub.empty:
            parts.append(sub)
    out = (pd.concat(parts, ignore_index=True).sort_values(["season", "week", "play_id"])
           .reset_index(drop=True) if parts else pd.DataFrame())
    if len(_play_cache) >= _PLAYER_CACHE_MAX:
        _play_cache.pop(next(iter(_play_cache)))
    _play_cache[key] = out
    return out


def load_rush_plays(player_id: str) -> pd.DataFrame:
    """Every carry this player had (a quarterback's scrambles and kneel-downs
    included, as the official stat lines count them), oldest first."""
    key = (player_id, "rusher")
    if key in _play_cache:
        return _play_cache[key]
    cols = sorted(set(PLAY_COLUMN.values()))
    parts = []
    for yr in play_seasons("rush"):
        df = nflref.load("rush_plays", str(yr))
        if df.empty:
            continue
        df = df.assign(carry_type=_carry_type(df))
        if yr not in _rush_coverage:
            _rush_coverage[yr] = {c: float(df[c].notna().mean()) for c in cols if c in df.columns}
        sub = df[df["rusher_id"] == player_id]
        if not sub.empty:
            parts.append(sub)
    out = (pd.concat(parts, ignore_index=True).sort_values(["season", "week", "play_id"])
           .reset_index(drop=True) if parts else pd.DataFrame())
    if len(_play_cache) >= _PLAYER_CACHE_MAX:
        _play_cache.pop(next(iter(_play_cache)))
    _play_cache[key] = out
    return out


def _carry_type(df: pd.DataFrame) -> pd.Series:
    """Designed run, scramble or kneel-down, from the two flags on each carry."""
    kneel = pd.to_numeric(df["kneel"], errors="coerce").fillna(0) == 1
    scramble = pd.to_numeric(df["scramble"], errors="coerce").fillna(0) == 1
    return pd.Series("Run", index=df.index, dtype=object).mask(scramble, "Scramble").mask(kneel, "Kneel")


def _rush_measure_frame(plays: pd.DataFrame) -> pd.DataFrame:
    """The additive carry measures, one numeric column each, per carry."""
    nan = pd.Series(float("nan"), index=plays.index)
    yards = pd.to_numeric(plays["yards"], errors="coerce") if "yards" in plays.columns else nan
    td = pd.to_numeric(plays["td"], errors="coerce").fillna(0.0) if "td" in plays.columns         else pd.Series(0.0, index=plays.index)
    return pd.DataFrame({"carries": pd.Series(1.0, index=plays.index),
                         "rushing_yards": yards, "rushing_tds": td})


def _play_values(plays: pd.DataFrame, key: str) -> pd.Series:
    """The label each play falls under for a play filter or group (None when the
    value is blank or outside every band): one definition for filtering and
    grouping."""
    col = plays[PLAY_COLUMN[key]]
    if key in PLAY_EQ:
        inv = {v: k for k, v in PLAY_EQ[key][2].items()}
        return col.map(inv)
    v = pd.to_numeric(col, errors="coerce")
    if key in PLAY_YESNO:
        return v.map({1.0: "Yes", 0.0: "No"})
    out = pd.Series([None] * len(plays), index=plays.index, dtype=object)
    for label, (lo, hi) in PLAY_BANDS[key][2].items():
        m = v.notna()
        if lo is not None:
            m &= v >= lo
        if hi is not None:
            m &= v < hi
        out[m] = label
    return out


def _play_order(key: str) -> list[str]:
    if key in PLAY_EQ:
        return list(PLAY_EQ[key][2])
    if key in PLAY_YESNO:
        return ["Yes", "No"]
    return list(PLAY_BANDS[key][2])


_PLAY_NUM = ["attempt", "complete", "yards", "td", "interception", "air_yards"]


def _play_measure_frame(plays: pd.DataFrame, passer: bool) -> pd.DataFrame:
    """The additive measures, one numeric column each, per play, for this role."""
    for c in _PLAY_NUM:
        if c not in plays.columns:
            plays = plays.assign(**{c: pd.Series(dtype=float)})
    att = plays["attempt"] == 1
    a = att.astype(float)
    cmp_ = (att & (plays["complete"] == 1)).astype(float)
    yds = pd.to_numeric(plays["yards"], errors="coerce").where(cmp_ == 1, 0.0)
    td = (att & (plays["td"] == 1)).astype(float)
    if passer:
        return pd.DataFrame({"attempts": a, "completions": cmp_, "passing_yards": yds,
                             "passing_tds": td,
                             "interceptions": (att & (plays["interception"] == 1)).astype(float)})
    return pd.DataFrame({"targets": a, "receptions": cmp_, "receiving_yards": yds,
                         "receiving_tds": td,
                         "receiving_air_yards": pd.to_numeric(plays["air_yards"],
                                                              errors="coerce").where(att)})


def _play_value(m: pd.DataFrame, n_games: int, key: str, agg: str,
                allowed: set | None = None) -> float | None:
    """One measure over a set of plays (`m` = their measure frame) and the games
    they came from.  A measure the role does not have, or one outside the play
    measures, is None (a dash).  A group with games but no matching play is a
    real zero for a count and None for a ratio."""
    if key not in (PLAY_MEASURES if allowed is None else allowed):
        return None
    if key in _RATIOS:
        _, num, den = _RATIOS[key]
        if num not in m.columns or den not in m.columns:
            return None
        d = m[den].sum()
        if d == 0:
            return None
        v = float(m[num].sum() / d)
        return v * 100 if key in _PERCENT else v
    if key not in m.columns or n_games <= 0:
        return None
    col = m[key]
    if len(col) and col.notna().sum() == 0:
        return None                      # not recorded (air yards), never zero
    total = float(col.sum())
    return total / n_games if agg == "per_game" else total


def _run_play_query(games: pd.DataFrame, spec: dict) -> dict:
    measures, agg, group, filters = (spec["measures"], spec["agg"], spec["group_by"],
                                     spec["filters"])
    columns = [{"key": m, "label": MEASURES[m] + (" /g" if agg == "per_game"
                                                  and m in _COUNTS else "")}
               for m in measures]
    empty = {"columns": columns, "rows": [], "total": None, "games": 0, "spec": spec,
             "play_seasons": None}
    if games.empty:
        return empty
    play_filters = {k: filters[k] for k in PLAY_KEYS if filters.get(k)}
    used = {PLAY_COLUMN[k] for k in play_filters}
    if group in PLAY_GROUPS:
        used.add(PLAY_COLUMN[group])
    passer = is_passer(games)
    tables = {PLAY_TABLE[k] for k in play_filters} | ({PLAY_TABLE[group]} if group in PLAY_TABLE
                                                      else set())
    table = "rush" if "rush" in tables else "pass"
    allowed = TABLE_MEASURES[table]
    pid = str(games["player_id"].iloc[0])
    plays = load_rush_plays(pid) if table == "rush" else load_plays(pid, passer)
    coverage = _rush_coverage if table == "rush" else _play_coverage
    g = apply_filters(games, filters)
    usable = {yr for yr, cov in coverage.items()
              if all(cov.get(c, 0.0) >= MIN_PLAY_COVERAGE for c in used)}
    g = g[g["season"].isin(usable)]
    if g.empty:
        return empty
    seasons_used = sorted(int(x) for x in g["season"].unique())
    note = (f"{seasons_used[0]}" if len(seasons_used) == 1
            else f"{seasons_used[0]} to {seasons_used[-1]}")
    if plays.empty:
        plays = pd.DataFrame({"season": pd.Series(dtype="int64"),
                              "week": pd.Series(dtype="int64"),
                              **{c: pd.Series(dtype=object) for c in PLAY_COLUMN.values()}})
    keys = g[["season", "week"]].copy()
    if group in GAME_GROUPS:
        keys["_grp"] = g[group].values
    pl = plays.merge(keys, on=["season", "week"], how="inner").reset_index(drop=True)
    for k, v in play_filters.items():
        pl = pl[_play_values(pl, k) == v]
    m = _rush_measure_frame(pl) if table == "rush" else _play_measure_frame(pl, passer)

    def row(label, idx, n):
        r = {"group": label, "games": int(n)}
        sub = m.loc[idx] if idx is not None else m
        for k in measures:
            r[k] = _play_value(sub, int(n), k, agg, allowed)
        return r

    rows: list[dict] = []
    total = None
    n_games = len(g)
    if group is None:
        rows = [row(None, None, len(g))]
    elif group in GAME_GROUPS:
        for key, gsub in g.groupby(group, sort=True):
            idx = pl.index[pl["_grp"] == key]
            rows.append(row(key.item() if hasattr(key, "item") else key, idx, len(gsub)))
        if group == "game_type":
            rank = {x: i for i, x in enumerate(GAME_TYPES)}
            rows.sort(key=lambda r: rank.get(r["group"], 99))
        total = row("Total", None, len(g))
    else:
        vals = _play_values(pl, group)
        for label in _play_order(group):
            idx = pl.index[vals == label]
            if len(idx) == 0:
                continue
            n = len(pl.loc[idx, ["season", "week"]].drop_duplicates())
            rows.append(row(label, idx, n))
        idx_all = pl.index[vals.notna()]
        n_games = len(pl.loc[idx_all, ["season", "week"]].drop_duplicates())
        total = row("Total", idx_all, n_games) if rows else None
    return {"columns": columns, "rows": rows, "total": total, "games": int(n_games),
            "spec": spec, "play_seasons": note}


def uses_plays(spec: dict) -> bool:
    """True when a cleaned spec needs the pass-play table."""
    f = spec.get("filters") or {}
    return any(f.get(k) for k in PLAY_KEYS) or spec.get("group_by") in PLAY_GROUPS


def run_query(games: pd.DataFrame, spec: dict) -> dict:
    """Run one spec over one player's games.

    Returns `{"columns": [{"key","label"}...], "rows": [...], "total": {...},
    "games": n, "spec": cleaned_spec}`.  Each row has the group value under
    `"group"` (None for an ungrouped query), a game count under `"games"`, and
    one entry per measure.  Raises ValueError on a spec outside the menus.
    """
    spec = _clean(spec)
    if uses_plays(spec):
        return _run_play_query(games, spec)
    df = apply_filters(games, spec["filters"]) if not games.empty else games
    measures, agg, group = spec["measures"], spec["agg"], spec["group_by"]
    columns = [{"key": m, "label": MEASURES[m] + (" /g" if agg == "per_game"
                                                  and m in _COUNTS else "")}
               for m in measures]

    def row(sub: pd.DataFrame, label) -> dict:
        r = {"group": label, "games": int(len(sub))}
        for m in measures:
            r[m] = _value(sub, m, agg)
        return r

    rows: list[dict] = []
    if not df.empty:
        if group is None:
            rows = [row(df, None)]
        else:
            for key, sub in df.groupby(group, sort=True):
                rows.append(row(sub, key.item() if hasattr(key, "item") else key))
            if group == "game_type":
                rank = {g: i for i, g in enumerate(GAME_TYPES)}
                rows.sort(key=lambda r: rank.get(r["group"], 99))
    total = row(df, "Total") if not df.empty and group is not None else None
    return {"columns": columns, "rows": rows, "total": total,
            "games": int(len(df)), "spec": spec}


# -- presets: shortcuts that FILL the builder's controls ---------------------------
# A preset never runs anything.  It is the set of control values the builder's
# form takes when its chip is clicked (applied in the browser, no request); the
# user can change any of them and then runs the query.  The opponent is left to
# the user, so every preset leaves it at Any.
#
# What a preset changes: the measure checkboxes (a family of related stats,
# chosen by position), Show (total or per game), Group by, the season range and
# the game type boxes.

#: Related measures by position.  A family is intersected with what the player
#: actually has, so a receiver's "volume" never lists passing attempts.
_FAMILIES = {
    "QB": {"volume": ["attempts", "completions", "carries"],
           "yardage": ["passing_yards", "rushing_yards"],
           "scoring": ["passing_tds", "rushing_tds", "interceptions"],
           "efficiency": ["completion_rate", "yards_per_attempt", "yards_per_completion",
                          "pass_td_rate", "int_rate", "yards_per_carry"]},
    "RB": {"volume": ["carries", "targets", "receptions"],
           "yardage": ["rushing_yards", "receiving_yards", "scrimmage_yards"],
           "scoring": ["rushing_tds", "receiving_tds", "scrimmage_tds"],
           "efficiency": ["yards_per_carry", "yards_per_reception", "catch_rate",
                          "yards_per_target", "yards_per_touch", "rush_td_rate"]},
    "WR": {"volume": ["targets", "receptions", "carries"],
           "yardage": ["receiving_yards", "receiving_air_yards", "rushing_yards"],
           "scoring": ["receiving_tds", "rushing_tds"],
           "efficiency": ["yards_per_target", "yards_per_reception", "catch_rate", "adot",
                          "yards_per_air_yard", "rec_td_rate"]},
}
_FAMILIES["TE"] = {                    # no rushing: a tight end's carries are noise
    "volume": ["targets", "receptions"],
    "yardage": ["receiving_yards", "receiving_air_yards"],
    "scoring": ["receiving_tds"],
    "efficiency": ["yards_per_target", "yards_per_reception", "catch_rate", "adot",
                   "yards_per_air_yard", "rec_td_rate"]}
_FAMILIES["FB"] = _FAMILIES["RB"]
_FAMILIES["K"] = {
    "volume": ["fg_att", "fg_made", "pat_att", "pat_made"],
    "yardage": ["fg_long", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_"],
    "scoring": ["fg_made", "pat_made", "kick_points"],
    "efficiency": ["fg_pct", "pat_pct"]}
_FANTASY = {"fantasy": ["fantasy_points_ppr", "fantasy_points"],
            "ppr": ["fantasy_points_ppr"]}
_PLAYOFF_TYPES = ["WC", "DIV", "CON", "SB"]

#: Hover text for each preset chip: what it fills in.
PRESET_HINTS = {
    "workload": "Volume per game, by season",
    "production": "Yards and scores, season totals by season",
    "efficiency": "Per-play rates (yards per carry, catch rate and the like), by season",
    "fantasy": "Fantasy points per game, by season",
    "recent": "Volume, yards and scores per game, last three seasons",
    "home_away": "Yards and scores per game, split by home, away and neutral",
    "by_opponent": "Yards and scores totals against each opponent",
    "playoffs": "Playoff games only, per game, split by round",
    "man_zone": "Pass plays split by man and zone coverage (2018 on)",
    "pressure": "Pass plays split by whether the passer was pressured (2016 on)",
}

#: id -> (label, measure families, Show, Group by, extra)
#: `extra` may set "recent" (last three seasons) or "game_types".
_PRESET_CFG = {
    "workload": ("Workload", ["volume"], "per_game", "season", {}),
    "production": ("Production", ["yardage", "scoring"], "total", "season", {}),
    "efficiency": ("Efficiency", ["efficiency"], "total", "season", {}),
    "fantasy": ("Fantasy output", ["fantasy"], "per_game", "season", {}),
    "recent": ("Recent form", ["volume", "yardage", "scoring"], "per_game", "season",
               {"recent": True}),
    "home_away": ("Home and away", ["yardage", "scoring"], "per_game", "home_away", {}),
    "by_opponent": ("By opponent", ["yardage", "scoring"], "total", "opponent", {}),
    "playoffs": ("Playoff run", ["yardage", "scoring", "ppr"], "per_game", "game_type",
                 {"game_types": _PLAYOFF_TYPES}),
    "man_zone": ("Man vs zone", ["volume", "yardage", "scoring"], "total", "man_zone",
                 {"play": True}),
    "pressure": ("Under pressure", ["volume", "yardage", "scoring"], "total", "pressure",
                 {"play": True}),
}

PRESETS = [{"id": k, "label": v[0]} for k, v in _PRESET_CFG.items()]


def _family_measures(families: list[str], games: pd.DataFrame, position: str | None) -> list[str]:
    have = set(available_measures(games))
    table = _FAMILIES.get(position or "", {})
    out: list[str] = []
    for fam in families:
        names = _FANTASY.get(fam) or table.get(fam, [])
        out.extend(m for m in names if m in have and m not in out)
    return out or default_measures(position, games)


def preset_fill(preset_id: str, games: pd.DataFrame, position: str | None) -> dict:
    """The builder control values for a preset, with the form's own field names:
    measures, agg, group_by, opponent, season_from, season_to, home_away,
    game_types.  Raises ValueError for an unknown preset."""
    if preset_id not in _PRESET_CFG:
        raise ValueError(f"unknown preset: {preset_id}")
    _, families, agg, group, extra = _PRESET_CFG[preset_id]
    measures = _family_measures(families, games, position)
    if extra.get("play"):
        # a pass-play split can only answer the passing and receiving measures
        measures = ([m for m in measures if m in PLAY_MEASURES]
                    or [m for m in default_measures(position, games) if m in PLAY_MEASURES])
    fill = {"measures": measures, "agg": agg,
            "group_by": group, "opponent": "", "season_from": "", "season_to": "",
            "home_away": "", "game_types": list(extra.get("game_types", []))}
    if extra.get("recent") and not games.empty:
        cov = coverage(games)
        fill["season_from"] = str(max(cov["first_season"], cov["last_season"] - 2))
    fill["shown"] = shown_for_fill(fill)
    return fill


def shown_for_fill(fill: dict) -> list[str]:
    """The picker boxes a fill implies: the measure groups holding its measures,
    both Show controls, and only the filters the fill sets.  A preset therefore
    ticks what it uses and unticks the rest (filters the user filled in
    themselves stay, which the page script adds)."""
    keep = {_measure_group_key(name) for name, keys in MEASURE_GROUPS
            if any(k in fill.get("measures", []) for k in keys)}
    keep |= {"agg", "group_by"}
    if fill.get("opponent"):
        keep.add("opponent")
    if fill.get("home_away"):
        keep.add("home_away")
    if fill.get("season_from") or fill.get("season_to"):
        keep.add("seasons")
    if fill.get("game_types"):
        keep.add("game_types")
    return [k for k in PICKER_KEYS if k in keep]


def preset_chips(games: pd.DataFrame, position: str | None) -> list[dict]:
    """Every preset with its fill, ready to put on a chip."""
    return [{"id": p["id"], "label": p["label"], "hint": PRESET_HINTS.get(p["id"], ""),
             "fill": preset_fill(p["id"], games, position)} for p in PRESETS]


# -- cards: ready-made layouts of the same engine --------------------------------
# A card is a fixed spec (measure families, Show, Group by) run with the filters
# the page shares across every card.  The page loads the first EAGER_CARDS when it
# opens and the rest one at a time afterwards (see _alt_builder.html).

EAGER_CARDS = 3

#: id -> (title, hint, measure families, Show, Group by)
_CARD_CFG = {
    "workload": ("Workload", "Volume per game, by season", ["volume"], "per_game", "season"),
    "production": ("Production", "Yards and scores, season totals", ["yardage", "scoring"],
                   "total", "season"),
    "efficiency": ("Efficiency", "Per-play rates, by season", ["efficiency"], "total", "season"),
    "home_away": ("Home vs away", "Yards and scores per game, by site", ["yardage", "scoring"],
                  "per_game", "home_away"),
    "by_opponent": ("By opponent", "Yards and score totals against each opponent",
                    ["yardage", "scoring"], "total", "opponent"),
    "coverage": ("Vs coverage", "Pass plays by the coverage the defense ran (2018 on)",
                 ["volume", "yardage", "scoring"], "total", "coverage"),
    "routes": ("By route", "Targets by the route the receiver ran (2016 on)",
               ["volume", "yardage", "scoring"], "total", "route"),
    "rush_box": ("Vs the box", "Carries by how many defenders were in the box: 6 or fewer is "
                 "light, 8 or more is stacked (2016 on)", [], "total", "rush_box"),
    "rush_direction": ("By run direction", "Carries by the side of the line the run went to (2016 on)",
                       [], "total", "run_location"),
    "rush_personnel": ("By personnel", "Carries by the offense's personnel group: 11 is one back "
                       "and one tight end (2016 on)", [], "total", "off_personnel"),
    "rush_formation": ("By formation", "Carries by the offense's formation (2016 on)",
                       [], "total", "rush_formation"),
}
CARD_ORDER = list(_CARD_CFG)
#: What a rush card shows: the only measures a run-play query can answer.
_RUSH_CARD_MEASURES = ["carries", "rushing_yards", "rushing_tds", "yards_per_carry"]
_RUSH_CARDS = ["rush_box", "rush_direction", "rush_personnel", "rush_formation"]

#: Cards every position can show, first and last.  The first EAGER_CARDS load together,
#: so they are the cheap game-level ones; the split cards follow, in the order that
#: matters for the position.
_HEAD_CARDS = ["workload", "production", "efficiency"]
_TAIL_CARDS = ["home_away", "by_opponent"]
#: The position's own cards, most relevant first.  A back is judged on how he runs, a
#: receiver on how he is covered, a quarterback on both (his scrambles are carries).
_POSITION_CARDS = {
    "QB": ["coverage"] + _RUSH_CARDS,
    "RB": _RUSH_CARDS + ["coverage", "routes"],
    "FB": _RUSH_CARDS + ["coverage", "routes"],
    "WR": ["coverage", "routes"] + _RUSH_CARDS,
    "TE": ["coverage", "routes"],
}
#: How much a player must have done before a card about it is shown: a handful of
#: carries or targets would give rows of one or two plays.
MIN_USAGE = {"rush": 20, "recv": 20, "pass": 50}


def _usage(games: pd.DataFrame, column: str) -> float:
    if games is None or games.empty or column not in games.columns:
        return 0.0
    return float(pd.to_numeric(games[column], errors="coerce").fillna(0).sum())


def _card_applies(cid: str, position: str | None, games: pd.DataFrame | None) -> bool:
    """Whether the player has done enough of what a position card is about.  With no
    games to look at (the position alone) every card the position can have applies."""
    if games is None:
        return True
    if cid in _RUSH_CARDS:
        return _usage(games, "carries") >= MIN_USAGE["rush"]
    if cid == "routes":
        return _usage(games, "targets") >= MIN_USAGE["recv"]
    if cid == "coverage":
        if position == "QB":
            return _usage(games, "attempts") >= MIN_USAGE["pass"]
        return _usage(games, "targets") >= MIN_USAGE["recv"]
    return True


def cards_for(position: str | None, games: pd.DataFrame | None = None) -> list[dict]:
    """The cards for a player, in display order: the cheap game-level cards, then the
    position's own (a back's run splits, a receiver's coverage and routes), then the
    splits by site and opponent.  With `games`, a position card appears only when the
    player has the usage it is about (carries for a run card, targets for routes);
    without, every card the position can have is listed."""
    order = _HEAD_CARDS + [c for c in _POSITION_CARDS.get(position or "", [])
                           if _card_applies(c, position, games)] + _TAIL_CARDS
    return [{"id": cid, "title": _CARD_CFG[cid][0], "hint": _CARD_CFG[cid][1]} for cid in order]


def cards_for_player(player_id: str, position: str | None) -> list[dict]:
    """`cards_for` for a chosen player, reading his games (cached) to apply the usage
    rules.  The builder page calls this."""
    return cards_for(position, load_player(player_id))


def card_spec(card_id: str, games: pd.DataFrame, position: str | None, filters: dict) -> dict:
    """The query spec for a card under the shared filters.  Raises ValueError for an
    unknown card."""
    if card_id not in _CARD_CFG:
        raise ValueError(f"unknown card: {card_id}")
    _, _, families, agg, group = _CARD_CFG[card_id]
    if group in RUSH_GROUPS:
        return {"measures": list(_RUSH_CARD_MEASURES), "agg": agg, "group_by": group,
                "filters": filters}
    measures = _family_measures(families, games, position)
    if group in PLAY_GROUPS:
        measures = ([m for m in measures if m in PLAY_MEASURES]
                    or [m for m in default_measures(position, games) if m in PLAY_MEASURES])
    return {"measures": measures, "agg": agg, "group_by": group, "filters": filters}


def run_card(games: pd.DataFrame, position: str | None, card_id: str, filters: dict) -> dict:
    spec = card_spec(card_id, games, position, filters)
    # The filters are shared, and a query reads the pass table or the rush table, never
    # both.  A card about the other table cannot be answered under them, so it has no
    # rows (and the page hides it) rather than failing.
    wants = PLAY_TABLE.get(spec["group_by"])
    active = {PLAY_TABLE[k] for k in PLAY_KEYS if filters.get(k)}
    if wants and active and wants not in active:
        labels = {m: MEASURES[m] for m in spec["measures"]}
        return {"columns": [{"key": m, "label": labels[m]} for m in spec["measures"]],
                "rows": [], "total": None, "games": 0, "spec": spec,
                "play_seasons": None}
    return run_query(games, spec)


#: Most cards a user can add on top of the default ones.
MAX_CUSTOM_CARDS = 6


def custom_title(spec: dict) -> str:
    """A short name for a card the user built: the first stats, then how they are shown,
    for example "Targets, Rec yds, Catch % +2 · per game, by season"."""
    labels = [MEASURES[m] for m in spec.get("measures") or [] if m in MEASURES]
    shown = ", ".join(labels[:3]) + (f" +{len(labels) - 3}" if len(labels) > 3 else "")
    group = GROUPS.get(spec.get("group_by") or "")
    how = "per game" if spec.get("agg") == "per_game" else "total"
    return f"{shown} \u00b7 {how}, {'by ' + group.lower() if group else 'career'}"


def parse_custom_cards(raw: list[str]) -> list[dict]:
    """Cards the page carries from one render to the next, as JSON strings in the query.
    Anything that is not valid JSON or falls outside the menus is dropped, repeats are
    kept once, and at most MAX_CUSTOM_CARDS survive.  Each is {"spec", "title"} with the
    spec holding only measures, agg and group_by."""
    import json
    out: list[dict] = []
    for text in raw or []:
        try:
            d = json.loads(text)
            spec = {"measures": list(d.get("measures") or []), "agg": d.get("agg") or "total",
                    "group_by": d.get("group_by") or None}
            clean = _clean({**spec, "filters": {}})
        except (ValueError, TypeError, AttributeError):
            continue
        spec = {"measures": clean["measures"], "agg": clean["agg"], "group_by": clean["group_by"]}
        if any(x["spec"] == spec for x in out):
            continue
        out.append({"spec": spec, "title": custom_title(spec)})
        if len(out) >= MAX_CUSTOM_CARDS:
            break
    return out


def has_data(result: dict) -> bool:
    """True when at least one row holds a recorded value.  A card with nothing to
    show is hidden rather than drawn empty."""
    keys = [c["key"] for c in result["columns"]]
    return any(r.get(k) is not None for r in result["rows"] for k in keys)


# -- display --------------------------------------------------------------------

def format_value(key: str, value) -> str:
    """Counts as whole numbers when they are whole, ratios to one or two decimals."""
    if value is None or (isinstance(value, float) and value != value):
        return "–"
    if key in _PERCENT:
        return f"{value:.1f}%"
    if key in _RATIOS:
        return f"{value:.2f}"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.1f}"


def group_label(group_by: str | None, value) -> str:
    if value is None:
        return "Career"
    if group_by == "game_type":
        return GAME_TYPE_LABELS.get(value, str(value))
    return str(value)


#: Stats where a lower number is the better one.
LOWER_IS_BETTER = {"interceptions", "int_rate", "fg_missed", "pat_missed"}
#: Groupings that read as a time series (trend arrows, "best season").
_SEASONAL = {"season", "week"}
#: Indicators need at least this many rows to mean anything.
_MIN_ROWS = 3
#: A season-over-season change smaller than this gets no arrow.
_TREND_MIN = 0.05
_HEAT_MAX = 30           # strongest tint, as a percent of the accent colour


def _trend(prev, cur, key: str):
    """(arrow, tone, pct) for a change from `prev` to `cur`, or None when it is
    small or undefined.  Tone is good or bad, flipped for lower-is-better stats."""
    if prev is None or cur is None or prev == 0:
        return None
    pct = (cur - prev) / abs(prev)
    if abs(pct) < _TREND_MIN:
        return None
    up = pct > 0
    good = up != (key in LOWER_IS_BETTER)
    return ("\u25b2" if up else "\u25bc", "good" if good else "bad", pct)


def indicators(result: dict) -> tuple[list[list[dict]], list[dict]]:
    """Per-cell marks and the card's header chips, judged against the player's own
    rows only (no league baseline).

    Marks, for each group row and measure column: `h` (a tint strength, percent of
    the accent, for the higher end of the column), `mark` ("best" or "worst"),
    `bar` (length against the column's largest row) and `share` (percent of the column
    total), for count columns grouped by something that is not a season, and `trend`
    (an arrow against the previous season, for per-game and rate columns grouped by
    season).  A column with fewer than _MIN_ROWS values
    or no spread gets none.  Unrecorded values are skipped, never read as zero."""
    spec = result["spec"]
    group, agg = spec["group_by"], spec["agg"]
    rows = result["rows"]
    keys = [c["key"] for c in result["columns"]]
    marks: list[list[dict]] = [[{} for _ in keys] for _ in rows]
    chips: list[dict] = []
    seasonal = group in _SEASONAL
    for j, k in enumerate(keys):
        have = [(i, r.get(k)) for i, r in enumerate(rows) if r.get(k) is not None]
        if len(have) < _MIN_ROWS:
            continue
        vals = [v for _, v in have]
        lo, hi = min(vals), max(vals)
        if hi == lo:
            continue
        lower = k in LOWER_IS_BETTER
        is_count = k in _COUNTS
        bar = (is_count and agg == "total" and group is not None and not seasonal
               and lo >= 0 and sum(vals) > 0)
        for i, v in have:
            m = marks[i][j]
            if bar:
                m["bar"] = round(100 * v / hi)               # longest row fills the cell
                m["share"] = round(100 * v / sum(vals))
                continue
            good = (v - lo) / (hi - lo)
            good = 1 - good if lower else good
            m["h"] = round(good * _HEAT_MAX)
            if v == (lo if lower else hi):
                m["mark"] = "best"
            elif v == (hi if lower else lo):
                m["mark"] = "worst"
        if group == "season" and (k in _RATIOS or (agg == "per_game" and k in _COUNTS)):
            prev = None
            for i, v in have:
                t = _trend(prev[1], v, k) if prev else None
                if t:
                    arrow, tone, pct = t
                    marks[i][j]["trend"] = {
                        "arrow": arrow, "tone": tone,
                        "title": f"{pct * 100:+.0f}% vs {group_label(group, rows[prev[0]]['group'])}"}
                prev = (i, v)
    if group == "season" and keys:
        first = keys[0]
        have = [(i, r.get(first)) for i, r in enumerate(rows) if r.get(first) is not None]
        if len(have) >= _MIN_ROWS and len({v for _, v in have}) > 1:
            lower = first in LOWER_IS_BETTER
            best = (min if lower else max)(have, key=lambda t: t[1])
            label = result["columns"][0]["label"]
            chips.append({"text": f"Best: {group_label(group, rows[best[0]]['group'])}",
                          "title": f"{label}: {format_value(first, best[1])}", "tone": ""})
            if first in _RATIOS or agg == "per_game":
                t = _trend(have[-2][1], have[-1][1], first)
                if t:
                    arrow, tone, pct = t
                    chips.append({"text": f"{arrow} {abs(pct) * 100:.0f}%",
                                  "title": f"{label}: {group_label(group, rows[have[-1][0]]['group'])}"
                                           f" vs {group_label(group, rows[have[-2][0]]['group'])}",
                                  "tone": tone})
    return marks, chips


def table_view(result: dict) -> dict:
    """A `run_query` result as display strings for the templates, plus the marks
    and chips from `indicators`."""
    group = result["spec"]["group_by"]
    keys = [c["key"] for c in result["columns"]]
    marks, chips = indicators(result)

    def cells(r: dict) -> list[str]:
        return [format_value(k, r.get(k)) for k in keys]

    rows = [{"label": group_label(group, r["group"]), "games": r["games"],
             "cells": cells(r), "marks": marks[n]} for n, r in enumerate(result["rows"])]
    total = None
    if result.get("total"):
        total = {"label": "Total", "games": result["total"]["games"],
                 "cells": cells(result["total"])}
    return {"group_label": GROUPS.get(group, "Career") if group else "Career",
            "columns": [c["label"] for c in result["columns"]],
            "rows": rows, "total": total, "games": result["games"],
            "play_seasons": result.get("play_seasons"), "chips": chips}
