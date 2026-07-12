#!/usr/bin/env python
"""Generate a playoff bracket config for a league.

The playoff engine needs only ROSTER INPUTS per elimination matchup; this
scaffolds the rest (rounds, weeks, matchup wiring, and a snapshot of the
league's scoring chart) and pre-fills each side's starters from whatever Sleeper
recorded, as a baseline you then overwrite with the lineups actually submitted
to the commissioner.

    # replicate Sleeper's own bracket (used to validate the engine)
    python playoffs/scaffold.py sleeper  <league_id> playoffs/2025-sleeper.json

    # scaffold a custom bracket over your own week range, seeded by standings
    python playoffs/scaffold.py custom <league_id> playoffs/2025.json --weeks 14 15 16 17 18 --teams 8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import sleepermetrics as sm  # noqa: E402
from sleepermetrics.api import sleeper_api  # noqa: E402


def _context(league_id: str, season: str | None):
    chain = sm.league_chain(league_id)
    key = season or list(chain)[-1]
    link = chain[str(key)]
    lid = link["league_id"]
    lg = sleeper_api(f"/league/{lid}")
    rosters = sleeper_api(f"/league/{lid}/rosters")
    users = {u["user_id"]: u.get("display_name") for u in sleeper_api(f"/league/{lid}/users")}
    name_of = {r["roster_id"]: users.get(r.get("owner_id")) for r in rosters}
    return link, lid, lg, name_of


def _starters(lid: str, week: int) -> dict:
    """roster_id -> starters actually recorded by Sleeper that week."""
    return {m["roster_id"]: [p for p in (m.get("starters") or []) if p and p != "0"]
            for m in sleeper_api(f"/league/{lid}/matchups/{week}")}


def _base(link, lid, lg, name):
    return {
        "name": name,
        "season": link["season"],
        "league_id": lid,
        "roster_positions": lg["roster_positions"],
        "_comment": ("Starters are pre-filled from Sleeper as a baseline. Replace each "
                     "side's `starters` with the lineup submitted to the commissioner. "
                     "Ids or player names both work. Winners advance via 'W:<matchup_id>'."),
        "scoring_settings": lg["scoring_settings"],
        "rounds": [],
    }


def from_sleeper(league_id: str, season: str | None) -> dict:
    """Rebuild Sleeper's own bracket as a config (ground truth for validation)."""
    link, lid, lg, name_of = _context(league_id, season)
    wb = sleeper_api(f"/league/{lid}/winners_bracket")
    start = int(lg["settings"]["playoff_week_start"])
    cfg = _base(link, lid, lg, f"{lg['name']} {link['season']} (Sleeper bracket)")
    rounds = sorted({m["r"] for m in wb})
    starters = {}
    for r in rounds:
        wk = start + r - 1
        starters[wk] = _starters(lid, wk)
        games = [m for m in wb if m["r"] == r and m.get("t1") and m.get("t2")]
        mus = []
        for m in sorted(games, key=lambda x: x["m"]):
            mus.append({
                "id": f"M{m['m']}",
                "home": {"team": name_of[m["t1"]], "starters": starters[wk].get(m["t1"], [])},
                "away": {"team": name_of[m["t2"]], "starters": starters[wk].get(m["t2"], [])},
                "_sleeper_winner": name_of[m["w"]] if m.get("w") else None,
            })
        cfg["rounds"].append({"id": f"R{r}", "name": f"Round {r}", "weeks": [wk],
                              "matchups": mus})
    # Sleeper marks the title game with p == 1; the rest of the last round is
    # consolation/placement, so name the final explicitly.
    title = next((m for m in wb if m.get("p") == 1), None)
    if title:
        cfg["final"] = f"M{title['m']}"
    return cfg


def custom(league_id: str, season: str | None, weeks: list, teams: int) -> dict:
    """Seeded single-elim scaffold across an arbitrary week range."""
    link, lid, lg, name_of = _context(league_id, season)
    s = sm.season(league_id, season)
    seeds = (s.standings.sort_values("final_position")["user_name"].tolist())[:teams]
    cfg = _base(link, lid, lg, f"{lg['name']} {link['season']} Playoffs (custom)")

    alive = [f"{i + 1}:{n}" for i, n in enumerate(seeds)]  # keep seed order
    rnum = 0
    for wk in weeks:
        if len(alive) < 2:
            break
        rnum += 1
        starters = _starters(lid, wk)
        rid_of = {n: r for r, n in name_of.items()}
        mus, nxt = [], []
        # highest seed vs lowest seed; odd team out gets a bye
        while len(alive) > 1:
            hi, lo = alive.pop(0), alive.pop(-1)
            mid = f"R{rnum}M{len(mus) + 1}"
            def side(tag):
                nm = tag.split(":", 1)[1] if ":" in tag and not tag.startswith("W:") else tag
                return {"team": nm,
                        "starters": starters.get(rid_of.get(nm), []) if not nm.startswith("W:") else []}
            mus.append({"id": mid, "home": side(hi), "away": side(lo)})
            nxt.append(f"W:{mid}")
        if alive:  # bye for the leftover team
            mid = f"R{rnum}M{len(mus) + 1}"
            nm = alive[0].split(":", 1)[1] if ":" in alive[0] else alive[0]
            mus.append({"id": mid, "bye": nm})
            nxt.append(f"W:{mid}")
        cfg["rounds"].append({"id": f"R{rnum}", "name": f"Round {rnum}",
                              "weeks": [int(wk)], "matchups": mus})
        alive = nxt
    if cfg["rounds"]:
        cfg["final"] = cfg["rounds"][-1]["matchups"][-1]["id"]
    return cfg


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["sleeper", "custom"])
    ap.add_argument("league_id")
    ap.add_argument("out")
    ap.add_argument("--season", default=None)
    ap.add_argument("--weeks", nargs="+", type=int, default=[14, 15, 16, 17, 18])
    ap.add_argument("--teams", type=int, default=8)
    a = ap.parse_args()

    cfg = (from_sleeper(a.league_id, a.season) if a.mode == "sleeper"
           else custom(a.league_id, a.season, a.weeks, a.teams))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    print(f"wrote {a.out}: {len(cfg['rounds'])} rounds, "
          f"{sum(len(r['matchups']) for r in cfg['rounds'])} matchups")


if __name__ == "__main__":
    main()
