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


def search_players(query: str, limit: int = 12) -> list[dict]:
    """Players whose name contains every word of `query`, most recent and most
    games first.  Needs at least two characters."""
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
    hit = idx[mask].sort_values(["last_season", "games"], ascending=False).head(limit)
    return [{"player_id": r.player_id, "name": r.name, "position": r.position,
             "team": r.team, "first_season": int(r.first_season),
             "last_season": int(r.last_season), "games": int(r.games)}
            for r in hit.itertuples()]


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
    ("Kicking", ["fg_made", "fg_att", "fg_missed", "fg_pct", "fg_long", "fg_made_0_19",
                 "fg_made_20_29", "fg_made_30_39", "fg_made_40_49", "fg_made_50_59",
                 "fg_made_60_", "pat_made", "pat_att", "pat_missed", "pat_pct"]),
    ("Fantasy", ["fantasy_points_ppr", "fantasy_points"]),
]


def grouped_measures(games: pd.DataFrame, position: str | None = None) -> list[dict]:
    """Every measure under Passing / Rushing / Receiving / Fantasy headings, as
    [{label, items: [(key, label, used)]}].  `used` is False for a measure the
    player has no production in, so the builder can grey it out instead of
    hiding it.  The position's own group comes first (a receiver sees Receiving
    before Rushing)."""
    have = set(available_measures(games))
    groups = [{"label": name, "items": [(k, MEASURES[k], k in have) for k in keys]}
              for name, keys in MEASURE_GROUPS]
    lead = {"QB": "Passing", "RB": "Rushing", "FB": "Rushing",
            "WR": "Receiving", "TE": "Receiving", "K": "Kicking"}.get(position or "")
    groups.sort(key=lambda g: g["label"] != lead)   # stable: lead group first
    return groups


def default_measures(position: str | None, games: pd.DataFrame) -> list[str]:
    have = set(available_measures(games))
    base = [m for m in _DEFAULT_MEASURES.get(position or "", []) if m in have]
    return base or [m for m in MEASURES if m in have][:6]


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
                        "game_types": gts}}


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
    return df


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
    return fill


def preset_chips(games: pd.DataFrame, position: str | None) -> list[dict]:
    """Every preset with its fill, ready to put on a chip."""
    return [{"id": p["id"], "label": p["label"],
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
