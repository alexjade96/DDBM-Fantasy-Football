"""Generate a standalone HTML season report (Python instance).

    python launch.py report                     # latest season, default league
    python launch.py report <league_id>
    python launch.py report <league_id> --season 2024
    python launch.py report <league_id> --out my_report.html
    python launch.py report <league_id> --all   # one file per season

Run via launch.py (which sets the venv + season dir), or directly from python/.
"""
from __future__ import annotations

import argparse
import os
import sys

import sleepermetrics as sm

DEFAULT_LEAGUE = os.environ.get("SLEEPERMETRICS_LEAGUE", "1252770181306929152")
SEASON_DIR = os.environ.get("SLEEPERMETRICS_SEASON_DIR", "season")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="make_report")
    ap.add_argument("league", nargs="?", default=DEFAULT_LEAGUE)
    ap.add_argument("--season", help="season to report (default: latest)")
    ap.add_argument("--out", help="output path (default: report_<league>_<season>.html)")
    ap.add_argument("--all", action="store_true", help="one report per season")
    a = ap.parse_args(argv)

    ss = sm.apply_playoffs(sm.seasons(a.league), SEASON_DIR)
    pos = sm.load_playoffs(SEASON_DIR, league_ids=[s.league_id for s in ss.values()])
    if not ss:
        sys.exit(f"No scored seasons found for league {a.league}.")

    targets = list(ss) if a.all else [a.season if a.season in ss else list(ss)[-1]]
    for key in targets:
        out = a.out if (a.out and not a.all) else f"report_{a.league}_{key}.html"
        sm.season_report(ss[key], out, seasons=ss, playoffs=pos)
        print(f"wrote {out}  ({ss[key].name} {key})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
