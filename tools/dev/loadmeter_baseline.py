#!/usr/bin/env python
"""Measure the network cost of the app's main data-building actions.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/loadmeter_baseline.py [--out FILE] [--only NAME ...] [--league ID] [--skip-warm]

Runs each action twice under `webapp.loadmeter`: a COLD pass (`fresh=True`
where the function takes it) and a WARM pass straight after.  A warm pass
that still shows network calls is an ad-hoc pull that stored data should
have answered; that is what docs/data-loading-refactor-plan.md is about.

MAKES REAL NETWORK CALLS (Sleeper, nflverse, ADP providers) and may write
snapshot files under data/sources/ exactly as the app would.  Check
`git status` afterwards.  The refresher is switched off for the run
(DISABLE_REFRESH=1) so it does not add its own traffic.

Record results as MEASURED, with the date, and compare the same actions after
each refactor step.  Only metadata is stored, never payloads or query strings.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from datetime import date
from pathlib import Path

os.environ.setdefault("DISABLE_REFRESH", "1")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fantasy-football-4-fun"))

from webapp import loadmeter  # noqa: E402

PLAYER_ID = "4034"      # a long-career RB, present in the Sleeper dump
TEAM = "DET"


def _actions(league: str, season: str):
    """name -> (cold callable, warm callable).  Imports are lazy so a failing
    import only breaks its own action."""
    def league_load(fresh):
        from webapp import app
        return app.league_data(league, fresh=fresh)

    def player(fresh):
        from webapp import player_profile
        return player_profile.player_profile(PLAYER_ID, None, fresh=fresh)

    def player_with_league(fresh):
        from webapp import player_profile
        return player_profile.player_profile(PLAYER_ID, league, fresh=fresh)

    def team(fresh):
        from webapp import team_profile
        return team_profile.team_profile(TEAM, season, fresh=fresh)

    def adp_board(fresh):
        from webapp.sources.ffadp import board
        return board.combine(season, scoring="ppr", reload=False)

    def compare(fresh):
        from webapp import player_compare
        ids = [PLAYER_ID]
        player_compare.player_field_compare(season, "RB", ids)
        return player_compare.player_trend(ids, season, "RB")

    return {
        "league_load": league_load,
        "player_profile": player,
        "player_profile_with_league": player_with_league,
        "team_profile": team,
        "adp_board": adp_board,
        "player_compare": compare,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", help="write the full results as JSON to this file")
    ap.add_argument("--only", nargs="*", help="run just these actions")
    ap.add_argument("--league", help="default: the app's own default league")
    ap.add_argument("--season", default="2025")
    ap.add_argument("--skip-warm", action="store_true")
    args = ap.parse_args()

    if not args.league:
        from webapp import app as _app       # the one place the default lives
        args.league = _app.DEFAULT_LEAGUE
    actions = _actions(args.league, args.season)
    names = args.only or list(actions)
    unknown = [n for n in names if n not in actions]
    if unknown:
        print(f"unknown action(s): {unknown}; choose from {list(actions)}")
        return 2

    results = []
    for name in names:
        passes = [("cold", True)] + ([] if args.skip_warm else [("warm", False)])
        for kind, fresh in passes:
            label = f"{name} [{kind}]"
            error = None
            with loadmeter.session(label) as m:
                try:
                    actions[name](fresh)
                except Exception:
                    error = traceback.format_exc(limit=3)
            print(m.report(top=8))
            if error:
                print("  ERROR (partial numbers):\n" + error)
            print()
            rec = m.to_dict()
            rec.update(action=name, pass_=kind, error=error,
                       measured_on=date.today().isoformat())
            results.append(rec)

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2),
                                  encoding="utf-8")
        print(f"wrote {args.out}")
    print("Check `git status`: this run may have rewritten snapshot files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
