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

#: group-by menu: key -> label
GROUPS = {
    "opponent": "Opponent", "season": "Season", "home_away": "Home or away",
    "game_type": "Game type", "week": "Week",
}

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
    "fantasy_points_ppr": ("PPR pts", "fantasy_points_ppr"),
    "fantasy_points": ("Std pts", "fantasy_points"),
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
    "fg_pct": ("FG %", "fg_made", "fg_att"),
    "pat_pct": ("PAT %", "pat_made", "pat_att"),
}
_PERCENT = {"catch_rate", "completion_rate", "fg_pct", "pat_pct"}

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
    "reset": "Clear every measure, filter and grouping back to this player's defaults.",
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
                 "interceptions", "completion_rate", "yards_per_attempt"]),
    ("Rushing", ["carries", "rushing_yards", "rushing_tds", "yards_per_carry"]),
    ("Receiving", ["targets", "receptions", "receiving_yards", "receiving_tds",
                   "receiving_air_yards", "yards_per_target", "yards_per_reception",
                   "catch_rate"]),
    ("Kicking", ["fg_made", "fg_att", "fg_missed", "fg_made_0_19", "fg_made_20_29",
                 "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_",
                 "pat_made", "pat_att", "pat_missed", "fg_pct", "pat_pct", "fg_long"]),
    ("Fantasy", ["fantasy_points_ppr", "fantasy_points"]),
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
              + ["role", "weeks"])


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
    return {"measures": measures, "agg": agg, "group_by": group,
            "filters": {"opponent": opp, "seasons": seasons, "home_away": ha,
                        "game_types": gts, **_clean_extras(f)}}


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


def run_query(games: pd.DataFrame, spec: dict) -> dict:
    """Run one spec over one player's games.

    Returns `{"columns": [{"key","label"}...], "rows": [...], "total": {...},
    "games": n, "spec": cleaned_spec}`.  Each row has the group value under
    `"group"` (None for an ungrouped query), a game count under `"games"`, and
    one entry per measure.  Raises ValueError on a spec outside the menus.
    """
    spec = _clean(spec)
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
           "efficiency": ["completion_rate", "yards_per_attempt", "yards_per_carry"]},
    "RB": {"volume": ["carries", "targets", "receptions"],
           "yardage": ["rushing_yards", "receiving_yards"],
           "scoring": ["rushing_tds", "receiving_tds"],
           "efficiency": ["yards_per_carry", "yards_per_reception", "catch_rate",
                          "yards_per_target"]},
    "WR": {"volume": ["targets", "receptions", "carries"],
           "yardage": ["receiving_yards", "receiving_air_yards", "rushing_yards"],
           "scoring": ["receiving_tds", "rushing_tds"],
           "efficiency": ["yards_per_target", "yards_per_reception", "catch_rate"]},
}
_FAMILIES["TE"] = {                    # no rushing: a tight end's carries are noise
    "volume": ["targets", "receptions"],
    "yardage": ["receiving_yards", "receiving_air_yards"],
    "scoring": ["receiving_tds"],
    "efficiency": ["yards_per_target", "yards_per_reception", "catch_rate"]}
_FAMILIES["FB"] = _FAMILIES["RB"]
_FAMILIES["K"] = {
    "volume": ["fg_att", "fg_made", "pat_att", "pat_made"],
    "yardage": ["fg_long", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59", "fg_made_60_"],
    "scoring": ["fg_made", "pat_made"],
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
    fill = {"measures": _family_measures(families, games, position), "agg": agg,
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


def table_view(result: dict) -> dict:
    """A `run_query` result as display strings for the templates."""
    group = result["spec"]["group_by"]
    keys = [c["key"] for c in result["columns"]]

    def cells(r: dict) -> list[str]:
        return [format_value(k, r.get(k)) for k in keys]

    rows = [{"label": group_label(group, r["group"]), "games": r["games"],
             "cells": cells(r)} for r in result["rows"]]
    total = None
    if result.get("total"):
        total = {"label": "Total", "games": result["total"]["games"],
                 "cells": cells(result["total"])}
    return {"group_label": GROUPS.get(group, "Career") if group else "Career",
            "columns": [c["label"] for c in result["columns"]],
            "rows": rows, "total": total, "games": result["games"]}
