#!/usr/bin/env python
"""Generate a playoff bracket config for a league (thin CLI wrapper).

The generators now live in `sleepermetrics.playoffs` (sleeper_bracket /
scaffold_bracket) so the webapp can call them directly; this stays as the
command-line front end.

    # replicate Sleeper's own bracket (the "default" a user rolls back to)
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


if __name__ == "__main__":
    main()
