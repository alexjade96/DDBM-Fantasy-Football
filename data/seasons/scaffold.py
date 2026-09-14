#!/usr/bin/env python
"""Generate a playoff bracket config for a league (thin CLI wrapper).

The generators now live in `sleepermetrics.playoffs` (sleeper_bracket /
scaffold_bracket) so the webapp can call them directly; this stays as the
command-line front end.

<league_id> is whichever season's id you have on hand (usually the current/
head one) -- it's just used to fetch live data. The FOLDER a config belongs
in is different: every season of a league gets its own distinct league_id
from Sleeper, so `out` should live under the chain's ROOT (oldest) id, not
necessarily <league_id> itself. This script prints that root id after
writing, so you don't have to work it out by hand.

The OUTPUT FILENAME matters too: `config_paths()` (the function every
dashboard/report/parity-check uses to find "the" bracket for a season) only
recognizes `<season>_season.json` as the authoritative config -- anything
else (a Sleeper-replay reference file, a rollback copy) is silently ignored
by that lookup, which is what lets one league folder hold more than one file
for the same season without them colliding.

    # replicate Sleeper's own bracket (a REFERENCE file, not "the" config --
    # name it something other than <season>_season.json or it will collide)
    python data/seasons/scaffold.py sleeper  <league_id> data/seasons/<root_league_id>/2025_bracket.json

    # scaffold a custom bracket over your own week range, seeded by standings
    # (the real, authoritative config: must be named <season>_season.json)
    python data/seasons/scaffold.py custom <league_id> data/seasons/<root_league_id>/2025_season.json --weeks 14 15 16 17 18 --teams 8
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# data/seasons/scaffold.py -> parents[1] = data/ -> parents[2] = repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fantasy-football-4-fun"))

from sleepermetrics.league import root_league_id  # noqa: E402
from sleepermetrics.playoffs import scaffold_bracket, sleeper_bracket  # noqa: E402


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

    cfg = (sleeper_bracket(a.league_id, a.season) if a.mode == "sleeper"
           else scaffold_bracket(a.league_id, a.season, a.weeks, a.teams))
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    print(f"wrote {a.out}: {len(cfg['rounds'])} rounds, "
          f"{sum(len(r['matchups']) for r in cfg['rounds'])} matchups")
    root = root_league_id(a.league_id)
    print(f"league root id (this league's whole history lives under "
          f"data/seasons/{root}/): {root}")


if __name__ == "__main__":
    main()
