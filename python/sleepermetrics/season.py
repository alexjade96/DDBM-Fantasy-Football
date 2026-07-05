"""Assemble one season into a tidy object (mirrors R season.R)."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .api import sleeper_api
from .league import league_chain, starter_slots
from .players import players

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def optimal_points(df: pd.DataFrame, slots: dict) -> float:
    """Best legal lineup points for one team-week given starter-slot counts."""
    d = df.dropna(subset=["position"]).sort_values("points", ascending=False)
    used: set = set()
    total = 0.0

    def take(elig, n):
        nonlocal total, used
        if not n:
            return
        avail = d[d["position"].isin(elig) & ~d["player_id"].isin(used)].head(int(n))
        used |= set(avail["player_id"])
        total += float(avail["points"].sum())

    for p in POSITIONS:
        take([p], slots.get(p, 0))
    take(["WR", "TE"], slots.get("REC_FLEX", 0))
    take(["RB", "WR", "TE"], slots.get("FLEX", 0))
    take(["RB", "WR", "TE"], slots.get("WRRB_FLEX", 0))
    take(["QB", "RB", "WR", "TE"], slots.get("SUPER_FLEX", 0))
    return total


@dataclass
class Season:
    season: str
    name: str
    league_id: str
    last_week: int
    slots: dict
    team_wk: pd.DataFrame
    pl_wk: pd.DataFrame
    lineup: pd.DataFrame
    standings: pd.DataFrame
    user_map: pd.DataFrame

    def __repr__(self):
        return (f"<Season {self.name} {self.season} | teams: "
                f"{len(self.standings)} | weeks 1:{self.last_week}>")


def _result(points, pa):
    if pd.isna(pa):
        return None
    if points > pa:
        return "W"
    if points < pa:
        return "L"
    return "T"


def assemble_season(link: dict) -> Season:
    lid = link["league_id"]
    lw = max(int(link["last_scored_leg"]), 1)
    slots = starter_slots(link["roster_positions"])
    pinfo = players()

    users_raw = sleeper_api(f"/league/{lid}/users")
    rosters_raw = sleeper_api(f"/league/{lid}/rosters")
    by_id = {u["user_id"]: {"user_name": u.get("display_name"),
                            "team_name": (u.get("metadata") or {}).get("team_name")}
             for u in users_raw}
    user_map = pd.DataFrame([
        {"roster_id": r["roster_id"], "user_id": r.get("owner_id"),
         "user_name": by_id.get(r.get("owner_id"), {}).get("user_name")}
        for r in rosters_raw
    ])

    tw_rows, pl_rows = [], []
    for wk in range(1, lw + 1):
        for m in sleeper_api(f"/league/{lid}/matchups/{wk}"):
            tw_rows.append({"week": wk, "roster_id": m["roster_id"],
                            "matchup_id": m.get("matchup_id"),
                            "points": m.get("points") or 0.0})
            pp = m.get("players_points") or {}
            starters = set(m.get("starters") or [])
            for pid in (m.get("players") or []):
                pts = pp.get(pid)
                pl_rows.append({"week": wk, "roster_id": m["roster_id"], "player_id": pid,
                                "points": 0.0 if pts is None else float(pts),
                                "is_starter": pid in starters})

    base = pd.DataFrame(tw_rows)
    # Opponent via self-merge on (week, matchup_id) EXCLUDING NaN matchup_id, so
    # eliminated/bye teams never get a phantom opponent (== R na_matches="never").
    opp = (base.dropna(subset=["matchup_id"])[["week", "matchup_id", "roster_id", "points"]]
           .rename(columns={"roster_id": "opp", "points": "pa"}))
    tw = base.merge(opp, on=["week", "matchup_id"], how="left")
    tw = tw[tw["opp"].isna() | (tw["roster_id"] != tw["opp"])].copy()
    tw["result"] = [_result(p, a) for p, a in zip(tw["points"], tw["pa"])]

    tw["allplay_w"] = 0
    tw["allplay_l"] = 0
    tw["is_high"] = False
    for _, g in tw.groupby("week"):
        pts = g["points"].values
        for idx in g.index:
            p = tw.at[idx, "points"]
            tw.at[idx, "allplay_w"] = int((pts < p).sum())
            tw.at[idx, "allplay_l"] = int((pts > p).sum())
            tw.at[idx, "is_high"] = bool(p == pts.max())
    tw = tw.merge(user_map, on="roster_id", how="left")

    pl = (pd.DataFrame(pl_rows)
          .merge(pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
          .merge(user_map[["roster_id", "user_name"]], on="roster_id", how="left"))
    lineup_rows = []
    for (un, wk), g in pl.groupby(["user_name", "week"]):
        actual = float(g.loc[g["is_starter"], "points"].sum())
        opt = optimal_points(g[["player_id", "position", "points"]], slots)
        lineup_rows.append({"user_name": un, "week": wk, "actual": actual,
                            "optimal": opt, "left_on_bench": max(opt - actual, 0.0)})
    lineup = pd.DataFrame(lineup_rows)

    st_rows = []
    for rid, g in tw.groupby("roster_id"):
        st_rows.append({
            "roster_id": rid, "user_id": g["user_id"].iloc[0],
            "user_name": g["user_name"].iloc[0],
            "wins": int((g["result"] == "W").sum()),
            "losses": int((g["result"] == "L").sum()),
            "points": float(g["points"].sum()), "pa": float(g["pa"].sum(skipna=True)),
            "allplay_w": int(g["allplay_w"].sum()), "allplay_l": int(g["allplay_l"].sum()),
            "highs": int(g["is_high"].sum()),
        })
    standings = (pd.DataFrame(st_rows)
                 .sort_values(["wins", "points"], ascending=False)
                 .reset_index(drop=True))
    standings["final_position"] = range(1, len(standings) + 1)

    champ = None
    try:
        for match in sleeper_api(f"/league/{lid}/winners_bracket"):
            if match.get("p") == 1:
                champ = match.get("w")
                break
    except Exception:
        champ = None
    standings["champion"] = standings["roster_id"] == champ
    standings["season"] = link["season"]

    return Season(link["season"], link.get("name"), lid, lw, slots,
                  tw, pl, lineup, standings, user_map)


def season(league_id, season: str | None = None) -> Season:
    """Assemble one season (default = most recent) of a league."""
    chain = league_chain(league_id)
    keys = list(chain.keys())
    link = chain[keys[-1]] if season is None else chain[str(season)]
    return assemble_season(link)


def seasons(league_id) -> dict:
    """Assemble every season in the chain -> {season: Season}."""
    chain = league_chain(league_id)
    return {s: assemble_season(link) for s, link in chain.items()}
