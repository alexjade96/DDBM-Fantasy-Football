"""Descriptive metric tables (pure compute; mirrors R metrics.R)."""
from __future__ import annotations

import pandas as pd

from .season import Season

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def standings(s: Season) -> pd.DataFrame:
    return s.standings


def luck(s: Season) -> pd.DataFrame:
    d = s.standings.copy()
    games = d["wins"] + d["losses"]
    exp = (d["allplay_w"] / (d["allplay_w"] + d["allplay_l"]).clip(lower=1) * games).round(1)
    out = pd.DataFrame({
        "user_name": d["user_name"], "wins": d["wins"],
        "exp_w": exp, "luck": (d["wins"] - exp).round(1),
    })
    return out.sort_values("luck", ascending=False).reset_index(drop=True)


def efficiency(s: Season) -> pd.DataFrame:
    g = s.lineup.groupby("user_name", as_index=False).agg(
        actual=("actual", "sum"), optimal=("optimal", "sum"), bench=("left_on_bench", "sum"))
    g["eff"] = (g["actual"] / g["optimal"] * 100).round(1)
    return g.sort_values("eff", ascending=False).reset_index(drop=True)


def consistency(s: Season) -> pd.DataFrame:
    g = s.team_wk.groupby("user_name", as_index=False).agg(
        median=("points", "median"), sd=("points", "std"),
        min=("points", "min"), max=("points", "max"))
    g["sd"] = g["sd"].round(1)
    return g.sort_values("sd").reset_index(drop=True)


def points_for_against(s: Season) -> pd.DataFrame:
    return s.standings[["user_name", "points", "pa", "wins"]].copy()


def high_scores(s: Season) -> pd.DataFrame:
    return (s.standings[["user_name", "highs"]]
            .sort_values("highs", ascending=False).reset_index(drop=True))


def _bind_standings(seasons: dict) -> pd.DataFrame:
    return pd.concat([s.standings for s in seasons.values()], ignore_index=True)


def _canonical_names(all_st: pd.DataFrame) -> pd.DataFrame:
    ordered = all_st.sort_values("season", ascending=False)
    return (ordered.groupby("user_id", as_index=False)
            .agg(user_name=("user_name", "first")))


def career(seasons: dict) -> pd.DataFrame:
    """Career standings across all seasons, aggregated by persistent user_id."""
    all_st = _bind_standings(seasons)
    canon = _canonical_names(all_st)
    g = all_st.groupby("user_id", as_index=False).agg(
        seasons=("season", "nunique"), wins=("wins", "sum"), losses=("losses", "sum"),
        points=("points", "sum"), titles=("champion", "sum"),
        best=("final_position", "min"))
    g["win_pct"] = (g["wins"] / (g["wins"] + g["losses"]).clip(lower=1) * 100).round(1)
    g["record"] = g["wins"].astype(str) + "-" + g["losses"].astype(str)
    g = g.merge(canon, on="user_id", how="left")
    return g.sort_values("win_pct", ascending=False).reset_index(drop=True)


def week_stats(s: Season, week: int | None = None) -> pd.DataFrame:
    """Per-team stats for one week (points, opponent, result, margin, bench)."""
    wk = week if week is not None else s.last_week
    lu = s.lineup[s.lineup["week"] == wk][["user_name", "optimal", "left_on_bench"]]
    tw = s.team_wk[s.team_wk["week"] == wk].merge(lu, on="user_name", how="left")
    out = pd.DataFrame({
        "week": wk, "user_name": tw["user_name"], "points": tw["points"],
        "opp_points": tw["pa"], "result": tw["result"],
        "margin": (tw["points"] - tw["pa"]).round(2),
        "optimal": tw["optimal"], "left_on_bench": tw["left_on_bench"].round(1),
    })
    return out.sort_values("points", ascending=False).reset_index(drop=True)


def player_loyalty(seasons: dict, min_seasons: int = 3) -> pd.DataFrame:
    """Players a manager re-rostered in >= min_seasons seasons."""
    from .players import players as _players
    pinfo = _players()
    frames = []
    for s in seasons.values():
        r = (s.pl_wk.merge(s.user_map[["roster_id", "user_id"]], on="roster_id", how="left")
             [["user_id", "player_id"]].drop_duplicates())
        r["season"] = s.season
        frames.append(r)
    rostered = pd.concat(frames, ignore_index=True)
    canon = _canonical_names(_bind_standings(seasons))
    g = rostered.groupby(["user_id", "player_id"], as_index=False).agg(
        seasons_kept=("season", "nunique"),
        season_list=("season", lambda x: ", ".join(sorted(set(x)))))
    g = g[g["seasons_kept"] >= min_seasons]
    g = (g.merge(pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
         .merge(canon, on="user_id", how="left"))
    g = g[g["player_name"].notna()]
    return g.sort_values(["seasons_kept", "user_name", "player_name"],
                         ascending=[False, True, True]).reset_index(drop=True)


# --- Roster & position analytics (ported from ddbmFF.R) -------------------

def _pos_cat(df):
    df = df.copy()
    df["position"] = pd.Categorical(df["position"], categories=POSITIONS, ordered=True)
    return df


def position_scoring(s: Season) -> pd.DataFrame:
    """Total started points by position + each position's share of scoring."""
    d = s.pl_wk[s.pl_wk["is_starter"] & s.pl_wk["position"].isin(POSITIONS)]
    g = d.groupby("position", as_index=False).agg(points=("points", "sum"))
    g["share"] = (g["points"] / g["points"].sum() * 100).round(1)
    return _pos_cat(g).sort_values("position").reset_index(drop=True)


def roster(s: Season) -> pd.DataFrame:
    """Player-weeks rostered, total and average points per team per position."""
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d[d["position"].isin(POSITIONS)]
    g = d.groupby(["user_name", "position"], as_index=False).agg(
        spots=("points", "size"), points=("points", "sum"))
    g["avg"] = g["points"] / g["spots"]
    return _pos_cat(g).sort_values(["user_name", "position"]).reset_index(drop=True)


def starter_bench(s: Season) -> pd.DataFrame:
    """Average points, starters vs bench, per team and position."""
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d[d["position"].isin(POSITIONS)].copy()
    d["status"] = d["is_starter"].map({True: "Starters", False: "Bench"})
    g = d.groupby(["user_name", "position", "status"], as_index=False).agg(avg=("points", "mean"))
    return _pos_cat(g).sort_values(["user_name", "position", "status"]).reset_index(drop=True)


def table_position(s: Season) -> pd.DataFrame:
    """Weekly table-position trajectory (cumulative record then points)."""
    d = s.team_wk.sort_values(["user_name", "week"]).copy()
    d["is_w"] = (d["result"] == "W").fillna(False).astype(int)
    d["is_l"] = (d["result"] == "L").fillna(False).astype(int)
    g = d.groupby("user_name")
    d["wins"] = g["is_w"].cumsum()
    d["losses"] = g["is_l"].cumsum()
    d["points"] = g["points"].cumsum()
    d = d.sort_values(["week", "wins", "points", "user_name"],
                      ascending=[True, False, False, True])
    d["table_position"] = d.groupby("week").cumcount() + 1
    return (d[["week", "user_name", "wins", "losses", "points", "table_position"]]
            .sort_values(["week", "table_position"]).reset_index(drop=True))


def roster_counts(s: Season) -> pd.DataFrame:
    """Average roster slots per position per team-week, starters vs bench."""
    denom = len(s.standings) * s.last_week
    d = s.pl_wk[s.pl_wk["position"].isin(POSITIONS)].copy()
    d["status"] = d["is_starter"].map({True: "Starters", False: "Bench"})
    g = d.groupby(["position", "status"], as_index=False).agg(avg_count=("points", "size"))
    g["avg_count"] = g["avg_count"] / denom
    return _pos_cat(g).sort_values(["position", "status"]).reset_index(drop=True)


# --- Transaction analytics (ported from ddbmFF.R) -------------------------

def transactions(s: Season) -> pd.DataFrame:
    """The season's unnested add/drop transactions frame."""
    return s.transactions


def _rostered_perf(s: Season, keep: pd.DataFrame, on: list) -> pd.DataFrame:
    """Points scored while rostered, by player x manager (from pl_wk).

    `on` sets the join grain: ["player_id"] (trades -> every team that held the
    player) or ["player_id", "roster_id"] (waivers -> the acquiring team only).
    """
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d.merge(keep, on=on, how="inner")
    d = d[d["position"].isin(POSITIONS) & d["player_name"].notna()]
    # player_id rides along: it is the only safe key for a portrait (names are
    # neither unique nor stable).
    g = d.groupby(["player_id", "player_name", "position", "user_name"],
                  as_index=False).agg(
        weeks=("week", "nunique"), points=("points", "sum"))
    g["avg"] = g["points"] / g["weeks"]
    g["total"] = g.groupby("player_name")["points"].transform("sum")
    return g


def trade_performance(s: Season) -> pd.DataFrame:
    """Traded players' points on each team that rostered them (movers only)."""
    tx = s.transactions
    keep = (tx[(tx["type"] == "trade") & (tx["transaction"] == "add")
               & (tx["status"] != "failed")][["player_id"]].drop_duplicates())
    g = _rostered_perf(s, keep, ["player_id"])
    g = g[g.groupby("player_name")["user_name"].transform("nunique") > 1]
    return _pos_cat(g).sort_values(["total", "player_name", "user_name"],
                                   ascending=[False, True, True]).reset_index(drop=True)


def waiver_performance(s: Season) -> pd.DataFrame:
    """Waiver / free-agent pickups' points while on the acquiring roster."""
    tx = s.transactions
    keep = (tx[(tx["type"].isin(["waiver", "free_agent"])) & (tx["transaction"] == "add")
               & (tx["status"] != "failed")][["player_id", "roster_id"]]
            .drop_duplicates())
    g = _rostered_perf(s, keep, ["player_id", "roster_id"])
    return _pos_cat(g).sort_values(["total", "player_name", "user_name"],
                                   ascending=[False, True, True]).reset_index(drop=True)
