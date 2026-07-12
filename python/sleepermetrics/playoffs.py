"""Manual / custom playoff engine (mirrors R playoffs.R).

Sleeper can only express its own bracket shape (fixed playoff_week_start, team
count, and lineups locked to what the app had). When a league runs its playoff
by hand -- a different week range, a custom bracket, and starters collected by
the commissioner -- none of that fits.

This engine takes a bracket config (rounds -> matchups -> each side's submitted
starters) and prices every lineup under the league's own scoring chart (see
scoring.py), so the ONLY input needed per elimination matchup is the rosters.
Winners advance automatically via "W:<matchup_id>" references.
"""
from __future__ import annotations

import json
import re
import warnings

import pandas as pd

from .api import sleeper_api
from .league import starter_slots
from .players import players as _players
from .scoring import rules_from, score_lineup

BYE = "BYE"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def playoff_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_players(x, pinfo: pd.DataFrame) -> list:
    """Accept starters as player ids OR player names; return ids."""
    out = []
    by_name = {n.lower(): i for n, i in
               zip(pinfo["player_name"].fillna(""), pinfo["player_id"])}
    for v in [str(v) for v in x]:
        if re.fullmatch(r"[0-9]+", v) or re.fullmatch(r"[A-Z]{2,3}", v):
            out.append(v)
        else:
            hit = by_name.get(v.lower())
            if hit is None:
                raise ValueError(f"Unknown player in lineup: '{v}'")
            out.append(hit)
    return out


def check_lineup(player_ids, roster_positions, pinfo: pd.DataFrame) -> list:
    """Problems with a submitted lineup vs the league's starting slots ([] = legal)."""
    slots = starter_slots(roster_positions)
    pos = (pinfo.set_index("player_id")["position"]
           .reindex([str(p) for p in player_ids]).dropna().tolist())
    probs = []
    need_total = sum(slots.values())
    if len(player_ids) != need_total:
        probs.append(f"lineup has {len(player_ids)} starters, league starts {need_total}")
    left = {p: pos.count(p) for p in POSITIONS}
    for p in POSITIONS:
        need = slots.get(p, 0)
        if need > 0:
            have = min(left[p], need)
            if have < need:
                probs.append(f"{need - have} {p} short")
            left[p] -= have
    flex = sum(slots.get(k, 0) for k in ("FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"))
    spare = sum(left.values())
    if spare != flex:
        probs.append(f"{spare} players for {flex} flex slot(s)")
    return probs


class Playoff:
    def __init__(self, results, players, champion, season, name, config):
        self.results = results
        self.players = players
        self.champion = champion
        self.season = season
        self.name = name
        self.config = config

    def __repr__(self):
        return (f"<Playoff {self.name} {self.season} | rounds: "
                f"{self.results['round_id'].nunique()} | "
                f"champion: {self.champion or '(undecided)'}>")


def playoff(config, rules: dict | None = None, validate: bool = True) -> Playoff:
    """Run a manual/custom playoff bracket from a config."""
    if isinstance(config, str):
        config = playoff_config(config)
    season = str(config["season"])
    lid = config.get("league_id")
    if rules is None:
        rules = config.get("scoring_settings") or rules_from(lid)
    pinfo = _players()
    rposi = config.get("roster_positions")
    if rposi is None and lid:
        try:
            rposi = sleeper_api(f"/league/{lid}")["roster_positions"]
        except Exception:
            rposi = None

    winners: dict = {}
    losers: dict = {}
    res, det = [], []

    def resolve_team(nm):
        """Resolve a team or a W:/L: reference; None if it isn't decided yet."""
        nm = str(nm)
        if nm.startswith("W:"):
            return winners.get(nm[2:])
        if nm.startswith("L:"):
            return losers.get(nm[2:])
        return nm

    def score_side(side, weeks, team, mid, rid):
        starters = _resolve_players(side["starters"], pinfo)
        if validate and rposi:
            probs = check_lineup(starters, rposi, pinfo)
            if probs:
                warnings.warn(f"[{mid}] {team}: {'; '.join(probs)}")
        d = score_lineup(starters, season, weeks, rules).merge(
            pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
        d["team"], d["matchup_id"], d["round_id"] = team, mid, rid
        return round(float(d["points"].sum()), 2), len(starters), d

    for rd in config["rounds"]:
        weeks = [int(w) for w in rd["weeks"]]
        wk_lbl = "+".join(str(w) for w in weeks)
        for mu in rd["matchups"]:
            mid = mu["id"]
            if mu.get("bye"):
                team = resolve_team(mu["bye"])
                if team is not None:
                    winners[mid] = team
                res.append({"round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                            "matchup_id": mid, "team": team, "starters": None,
                            "points": None, "opponent": BYE, "opp_points": None,
                            "result": "BYE" if team else "PENDING", "margin": None})
                continue
            sides = [mu["home"], mu["away"]]
            nms = [resolve_team(s["team"]) for s in sides]
            # A round only becomes playable once both teams are known AND both
            # lineups have been submitted -- otherwise it is simply not yet run.
            if any(n is None for n in nms) or any(not s.get("starters") for s in sides):
                for i in range(2):
                    res.append({
                        "round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                        "matchup_id": mid, "team": nms[i] or str(sides[i]["team"]),
                        "starters": len(sides[i].get("starters") or []), "points": None,
                        "opponent": nms[1 - i] or str(sides[1 - i]["team"]),
                        "opp_points": None, "result": "PENDING", "margin": None})
                continue
            scored = [score_side(sides[i], weeks, nms[i], mid, rd["id"]) for i in range(2)]
            pts = [s[0] for s in scored]
            wi = None if pts[0] == pts[1] else int(pts[1] > pts[0])
            if wi is None:
                warnings.warn(f"[{mid}] tie at {pts[0]} -- no winner advanced.")
            else:
                winners[mid] = nms[wi]
                losers[mid] = nms[1 - wi]
            for i in range(2):
                res.append({
                    "round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                    "matchup_id": mid, "team": nms[i], "starters": scored[i][1],
                    "points": pts[i], "opponent": nms[1 - i], "opp_points": pts[1 - i],
                    "result": "T" if wi is None else ("W" if i == wi else "L"),
                    "margin": round(pts[i] - pts[1 - i], 2)})
                det.append(scored[i][2])

    results = pd.DataFrame(res)
    playersdf = pd.concat(det, ignore_index=True) if det else pd.DataFrame()
    # The championship must be named: a final round can also hold consolation
    # and placement games, so "last matchup" is not the title game.
    final_id = config.get("final") or config["rounds"][-1]["matchups"][-1]["id"]
    champion = winners.get(final_id)
    return Playoff(results, playersdf, champion, season,
                   config.get("name", "Playoffs"), config)


def playoff_summary(p: Playoff) -> pd.DataFrame:
    """Per-team run through the bracket."""
    d = p.results

    def elim(g):
        l_ = g.loc[g["result"] == "L", "round"]
        return l_.iloc[-1] if len(l_) else None

    rows = []
    for team, g in d.groupby("team"):
        rows.append({
            "team": team,
            "games": int(g["result"].isin(["W", "L", "T"]).sum()),
            "wins": int((g["result"] == "W").sum()),
            "losses": int((g["result"] == "L").sum()),
            "points": round(float(pd.to_numeric(g["points"], errors="coerce").sum()), 2),
            "eliminated_in": elim(g)})
    out = pd.DataFrame(rows)
    return out.sort_values(["wins", "points"], ascending=False).reset_index(drop=True)
