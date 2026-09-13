"""Presentation views over the raw nflref datasets, for the NFL Stats tab.

These are thin: `load()` a dataset, aggregate / filter to something a table
can render, hand back a tidy `pd.DataFrame`. No `Season`, no league context --
the NFL Stats landing tab is season-only, like the ADP Comparison tab next to
it. Kept here rather than in the webapp so `nflref` stays the whole data
layer and the route is a one-liner.

Two sources feed the player leaderboard: `"nflverse"` (this module's own
aggregation of nflverse's weekly player-stats release) and `"sleeper"`
(delegated to `sleepermetrics.nflstats.player_leaderboard`, which walks
Sleeper's own weekly stat feed). `compare_sources()` lines the two up
player-by-player and reports every stat they disagree on -- a cross-platform
verification, since Sleeper and nflverse ingest the same NFL games from
different pipelines.
"""
from __future__ import annotations

import re

import pandas as pd

from .board import load

#: fantasy positions the player leaderboard offers, in menu order.
POSITIONS = ("ALL", "QB", "RB", "WR", "TE")

#: NFL team abbreviations for the Team filter, in menu order ("ALL" first).
#: nflverse's `recent_team` and Sleeper's `players()` `team` both use these.
TEAMS = (
    "ALL",
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
)

#: which sources the leaderboard / comparison understand.
SOURCES = ("nflverse", "sleeper")

# When a Team filter is active we need the whole ranked board before trimming,
# or a team's players get cut off by the top-N cap. Pull this many, filter,
# then re-apply the caller's `limit`.
_TEAM_FILTER_POOL = 10_000


def _norm_team(team) -> str:
    """Uppercase/trim a team arg; empty or "ALL" means no filter. Any other
    value is used as-is for an equality match -- the webapp route does its own
    strict `TEAMS` check for the dropdown, but a direct caller may pass an
    abbreviation not in the hardcoded list (a relocation, a stale list) and
    should still get a filter."""
    t = (str(team) if team is not None else "").upper().strip()
    return "ALL" if t in ("", "ALL") else t

# Per-position column sets for the NFLVERSE leaderboard: (df_key, header).
# Volume + the nflverse-derived usage rates Sleeper's own feed does not
# publish (air_yards_share / WOPR / RACR / PACR).
_NFLVERSE_SKILL_COLS = [
    ("games", "G"), ("targets", "Tgt"), ("receptions", "Rec"),
    ("rec_yards", "Rec yds"), ("rec_td", "Rec TD"),
    ("carries", "Car"), ("rush_yards", "Rush yds"), ("rush_td", "Rush TD"),
    ("tgt_share", "Tgt share"), ("air_yards_share", "Air share"),
    ("wopr", "WOPR"), ("racr", "RACR"),
    ("fpts_ppr", "PPR pts"), ("ppg_ppr", "PPR/G"),
]
_NFLVERSE_QB_COLS = [
    ("games", "G"), ("attempts", "Att"), ("completions", "Cmp"),
    ("pass_yards", "Pass yds"), ("pass_td", "Pass TD"), ("interceptions", "INT"),
    ("carries", "Car"), ("rush_yards", "Rush yds"), ("rush_td", "Rush TD"),
    ("pacr", "PACR"),
    ("fpts_ppr", "Fantasy pts"), ("ppg_ppr", "Pts/G"),
]
# The SLEEPER leaderboard's own columns -- it has snap share / aDOT / RZ
# touches that nflverse's weekly release does not break out, and no
# WOPR/RACR (those are nflverse-computed).
_SLEEPER_SKILL_COLS = [
    ("games", "G"), ("targets", "Tgt"), ("receptions", "Rec"),
    ("rec_yards", "Rec yds"), ("rec_td", "Rec TD"),
    ("carries", "Car"), ("rush_yards", "Rush yds"), ("rush_td", "Rush TD"),
    ("snap_share", "Snap share"), ("tgt_share", "Tgt share"),
    ("rz_touches", "RZ touch"), ("adot", "aDOT"),
    ("fpts_ppr", "PPR pts"), ("ppg_ppr", "PPR/G"),
]
_SLEEPER_QB_COLS = [
    ("games", "G"), ("pass_att", "Att"), ("pass_cmp", "Cmp"),
    ("pass_yards", "Pass yds"), ("pass_td", "Pass TD"), ("pass_int", "INT"),
    ("carries", "Car"), ("rush_yards", "Rush yds"), ("rush_td", "Rush TD"),
    ("snap_share", "Snap share"),
    ("fpts_ppr", "Fantasy pts"), ("ppg_ppr", "Pts/G"),
]

# The stats compare_sources() checks. Each is present in BOTH leaderboards
# under the same df key, and is a season total (a raw count, so a difference
# is a real ingestion disagreement, not a rounding one). (label, key, atol).
_COMPARE_STATS = [
    ("Games", "games", 0),
    ("Targets", "targets", 0),
    ("Receptions", "receptions", 0),
    ("Rec yds", "rec_yards", 0),
    ("Rec TD", "rec_td", 0),
    ("Carries", "carries", 0),
    ("Rush yds", "rush_yards", 0),
    ("Rush TD", "rush_td", 0),
    ("Pass yds", "pass_yards", 0),
    ("Pass TD", "pass_td", 0),
    ("PPR pts", "fpts_ppr", 0.5),
]


def _norm_name(name: str) -> str:
    """Loose name key for the cross-source join: lowercased, punctuation and
    common generational suffixes stripped (mirrors ffadp.identity._norm)."""
    n = (name or "").lower().strip()
    n = re.sub(r"[.’']", "", n)
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _sleeper_leaderboard(season: str, pos: str, limit: int,
                         reload: bool) -> pd.DataFrame:
    """Delegate to sleepermetrics.nflstats for the Sleeper-fed leaderboard."""
    try:
        from sleepermetrics import nflstats
    except Exception:
        return pd.DataFrame()
    return nflstats.player_leaderboard(season, pos=pos, limit=limit, reload=reload)


def _apply_team_filter(lb: pd.DataFrame, team: str, limit: int) -> pd.DataFrame:
    """Restrict an already-ranked leaderboard frame to one NFL team, re-rank
    among that team's players, and re-apply `limit`. A no-op when `team` is
    "ALL" or the frame has no `team` column."""
    if team == "ALL" or lb.empty or "team" not in lb.columns:
        return lb
    out = lb[lb["team"] == team].head(int(limit)).reset_index(drop=True)
    if "rank" in out.columns:
        out["rank"] = range(1, len(out) + 1)
    return out


def player_leaderboard(season: str, pos: str = "ALL", source: str = "nflverse",
                       limit: int = 200, team: str = "ALL",
                       reload: bool = False) -> pd.DataFrame:
    """Season-total player stats, one row per player, ranked by fantasy points.

    `source`: `"nflverse"` (default) aggregates nflverse's weekly
    player-stats release; `"sleeper"` delegates to
    `sleepermetrics.nflstats.player_leaderboard` (Sleeper's own weekly feed).
    `team`: an NFL abbreviation (see `TEAMS`) restricts the board to that
    club's players, ranked among themselves; `"ALL"` (default) is every team.
    Empty frame when the chosen source does not resolve.
    """
    tm = _norm_team(team)
    # A team filter needs the whole board first (or a club's players are cut
    # off by the cap); pull deep, filter, then re-rank + re-apply `limit`.
    fetch_limit = _TEAM_FILTER_POOL if tm != "ALL" else limit

    if (source or "nflverse").lower() == "sleeper":
        lb = _sleeper_leaderboard(str(season), (pos or "ALL").upper(),
                                  fetch_limit, reload)
        return _apply_team_filter(lb, tm, limit)

    ps = load("player_stats", str(season), reload=reload)
    if ps.empty:
        return ps

    p = (pos or "ALL").upper()
    if p != "ALL" and "position" in ps.columns:
        ps = ps[ps["position"] == p]
    if tm != "ALL" and "recent_team" in ps.columns:
        ps = ps[ps["recent_team"] == tm]
    if ps.empty:
        return ps

    sums = {
        "targets": "targets", "receptions": "receptions",
        "rec_yards": "receiving_yards", "rec_td": "receiving_tds",
        "carries": "carries", "rush_yards": "rushing_yards",
        "rush_td": "rushing_tds",
        "attempts": "attempts", "completions": "completions",
        "pass_yards": "passing_yards", "pass_td": "passing_tds",
        "interceptions": "interceptions",
        "fpts_ppr": "fantasy_points_ppr",
    }
    means = {
        "tgt_share": "target_share", "air_yards_share": "air_yards_share",
        "wopr": "wopr", "racr": "racr", "pacr": "pacr",
    }
    agg = {out: (src, "sum") for out, src in sums.items() if src in ps.columns}
    agg.update({out: (src, "mean") for out, src in means.items() if src in ps.columns})
    agg["games"] = ("week", "nunique")

    keys = ["player_id", "player_display_name", "position", "recent_team"]
    keys = [k for k in keys if k in ps.columns]
    g = ps.groupby(keys, as_index=False, dropna=False).agg(**agg)

    g = g.rename(columns={"player_display_name": "player", "recent_team": "team"})
    if "fpts_ppr" in g.columns:
        g["ppg_ppr"] = (g["fpts_ppr"] / g["games"].clip(lower=1)).round(2)
        g["fpts_ppr"] = g["fpts_ppr"].round(1)
    for c in ("tgt_share", "air_yards_share", "wopr", "racr", "pacr"):
        if c in g.columns:
            g[c] = g[c].round(3)
    for c in ("rec_yards", "rush_yards", "pass_yards"):
        if c in g.columns:
            g[c] = g[c].round(0).astype("Int64")

    sort_col = "fpts_ppr" if "fpts_ppr" in g.columns else keys[0]
    g = g.sort_values(sort_col, ascending=False).head(int(limit)).reset_index(drop=True)
    g.insert(0, "rank", range(1, len(g) + 1))
    return g


def leaderboard_columns(pos: str, source: str = "nflverse") -> list[tuple[str, str]]:
    """The (df_key, header) list for a leaderboard view of `pos` + `source`.

    QB gets a passing-stat set; every other position the skill set. The
    Sleeper source swaps nflverse's WOPR / RACR / air-yards-share for its own
    snap share / aDOT / RZ touches.
    """
    qb = (pos or "").upper() == "QB"
    if (source or "nflverse").lower() == "sleeper":
        return _SLEEPER_QB_COLS if qb else _SLEEPER_SKILL_COLS
    return _NFLVERSE_QB_COLS if qb else _NFLVERSE_SKILL_COLS


def compare_sources(season: str, pos: str = "ALL", limit: int = 200,
                    team: str = "ALL", reload: bool = False) -> dict:
    """Line the two source leaderboards up player-by-player and report every
    season-total stat they disagree on.

    `team` restricts both feeds to one NFL club before the join (see `TEAMS`).

    Both feeds ingest the same NFL games; a difference is a real pipeline
    disagreement (a stat corrected on one side, a game counted differently, a
    fantasy-scoring nuance). Players are matched on normalised name +
    position (neither release carries the other's id).

    Returns::

        {"season", "pos",
         "stats":  [(label, key), ...],           # the columns compared
         "rows":   [{player, position, team,
                     <key>_sleeper, <key>_nflverse, <key>_delta, ...,
                     total_abs_delta}],            # only players that differ,
                                                   # biggest disagreement first
         "summary": {"matched", "sleeper_only", "nflverse_only",
                     "in_agreement", "differing"}}

    Empty `rows` (and a summary) when a source does not resolve.
    """
    p = (pos or "ALL").upper()
    nv = player_leaderboard(season, pos=p, source="nflverse", limit=limit,
                            team=team, reload=reload)
    sl = player_leaderboard(season, pos=p, source="sleeper", limit=limit,
                            team=team, reload=reload)

    stats = [(lbl, key) for lbl, key, _ in _COMPARE_STATS]
    empty = {"season": str(season), "pos": p, "stats": stats, "rows": [],
             "summary": {"matched": 0, "sleeper_only": 0, "nflverse_only": 0,
                         "in_agreement": 0, "differing": 0}}
    if nv.empty or sl.empty:
        return empty

    def _key(df):
        k = df["player"].map(_norm_name) + "|" + df["position"].fillna("").str.upper()
        return df.assign(_k=k)

    nv, sl = _key(nv), _key(sl)
    nv_ix = nv.drop_duplicates("_k").set_index("_k")
    sl_ix = sl.drop_duplicates("_k").set_index("_k")
    common = nv_ix.index.intersection(sl_ix.index)

    rows = []
    differing = 0
    for k in common:
        rnv, rsl = nv_ix.loc[k], sl_ix.loc[k]
        # team: prefer whichever source has one (a traded player is often NaN
        # on the side that keyed him to his latest roster). pandas NaN is
        # truthy in Jinja, so coerce to None here.
        team = rsl.get("team")
        if team is None or (isinstance(team, float) and pd.isna(team)):
            team = rnv.get("team")
        if team is None or (isinstance(team, float) and pd.isna(team)):
            team = None
        row = {"player": rsl["player"], "position": rsl["position"], "team": team}
        tot = 0.0
        any_diff = False
        for lbl, key, atol in _COMPARE_STATS:
            a = rsl.get(key)
            b = rnv.get(key)
            va = None if a is None or pd.isna(a) else float(a)
            vb = None if b is None or pd.isna(b) else float(b)
            row[f"{key}_sleeper"] = va
            row[f"{key}_nflverse"] = vb
            if va is None or vb is None:
                row[f"{key}_delta"] = None
                continue
            d = round(va - vb, 2)
            row[f"{key}_delta"] = d
            if abs(d) > atol:
                any_diff = True
                tot += abs(d)
        row["total_abs_delta"] = round(tot, 2)
        if any_diff:
            differing += 1
            rows.append(row)

    rows.sort(key=lambda r: -r["total_abs_delta"])
    return {
        "season": str(season), "pos": p, "stats": stats, "rows": rows,
        "summary": {
            "matched": len(common),
            "sleeper_only": len(sl_ix.index.difference(nv_ix.index)),
            "nflverse_only": len(nv_ix.index.difference(sl_ix.index)),
            "in_agreement": len(common) - differing,
            "differing": differing,
        },
    }


def schedule_grid(season: str, week: str | int | None = None,
                  team: str = "ALL", reload: bool = False) -> pd.DataFrame:
    """Real game results for a season (optionally one week).

    From `nflref.load("schedules", season)`: away/home, final score, margin,
    O/U line, roof/surface/rest. `week` filters to a single week; None returns
    the whole season. `team` (see `TEAMS`) keeps only that club's games, home
    or away. Empty frame when the dataset does not resolve.
    """
    sch = load("schedules", str(season), reload=reload)
    if sch.empty:
        return sch
    if week not in (None, "", "ALL", "all"):
        try:
            sch = sch[sch["week"] == int(week)]
        except (TypeError, ValueError):
            pass
    tm = _norm_team(team)
    if tm != "ALL" and {"away_team", "home_team"}.issubset(sch.columns):
        sch = sch[(sch["away_team"] == tm) | (sch["home_team"] == tm)]
    keep = [c for c in (
        "week", "gameday", "weekday", "away_team", "away_score",
        "home_team", "home_score", "result", "total", "total_line",
        "overtime", "roof", "surface", "away_rest", "home_rest", "stadium",
    ) if c in sch.columns]
    out = sch[keep].copy()
    if {"away_score", "home_score"}.issubset(out.columns):
        out["margin"] = (out["home_score"] - out["away_score"]).abs()
    sort_keys = [c for c in ("week", "gameday") if c in out.columns]
    return out.sort_values(sort_keys).reset_index(drop=True)


def schedule_weeks(season: str) -> list[int]:
    """The week numbers present in the season's schedule (for the week menu)."""
    sch = load("schedules", str(season))
    if sch.empty or "week" not in sch.columns:
        return []
    return sorted(int(w) for w in sch["week"].dropna().unique())
