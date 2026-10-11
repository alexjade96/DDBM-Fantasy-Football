#!/usr/bin/env python
"""Download the complete ADP response for every provider and season already
derived on disk, and keep it under data/sources/adp/<provider>/raw/.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/backfill_adp_raw.py [--dry-run] [--only espn ffc ...] [--seasons 2024 2025] [--force]

Each response is stored exactly as received, gzip-compressed, as
raw_<season>.json.gz (CBS: .html.gz; FFC and RotoWire add a format folder;
Yahoo is a JSON list of its page bodies).  The trimmed snapshots next to them
are NOT rewritten.  See docs/data-loading-refactor-plan.md, step 7.

* Seasons come from the snapshot files already on disk.
* CBS and RotoWire serve only the current season: they are fetched once now and
  that copy is kept (it cannot be fetched again for an earlier year).
* A raw file that already exists is skipped unless `--force`.
* ESPN is about 4 MB gzipped per season, over 20 seasons.  Use `--only` to do
  it separately.

MAKES REAL NETWORK CALLS (ESPN is about 25 MB per season downloaded).  Check
`git status` afterwards.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fantasy-football-4-fun"))

from repo_paths import SOURCES_DIR  # noqa: E402
from sleepermetrics import api as sapi  # noqa: E402
from webapp.sources.ffadp import api, cache  # noqa: E402

ADP = SOURCES_DIR / "adp"
FFC_FORMATS = ("std", "half_ppr", "ppr", "2qb")


def _years(folder: Path) -> list[str]:
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.json") if p.stem.isdigit() and len(p.stem) == 4)


def plan(only: list[str] | None, seasons: list[str] | None):
    """[(label, raw_path, callable)]"""
    jobs = []

    def want(name):
        return not only or name in only

    def yrs(folder):
        ys = _years(folder)
        return [y for y in ys if not seasons or y in seasons]

    if want("sleeper"):
        for y in yrs(ADP):
            jobs.append((f"sleeper {y}", ADP / "sleeper" / "raw" / f"raw_{y}.json.gz",
                         lambda y=y: sapi.sleeper_adp(y)))
    if want("espn"):
        for y in yrs(ADP / "espn"):
            jobs.append((f"espn {y}", cache.raw_path("espn", y), lambda y=y: api.espn_players(y)))
    if want("ffc"):
        for fmt in FFC_FORMATS:
            for y in yrs(ADP / "ffc" / fmt):
                jobs.append((f"ffc {fmt} {y}", cache.raw_path("ffc", y, fmt),
                             lambda y=y, fmt=fmt: api.ffc_adp(y, fmt)))
    if want("yahoo"):
        for y in yrs(ADP / "yahoo"):
            jobs.append((f"yahoo {y}", cache.raw_path("yahoo", y), lambda y=y: api.yahoo_adp(y)))
    cur = cache.current_season()
    if want("cbs") and (not seasons or cur in seasons):
        jobs.append((f"cbs {cur}", cache.raw_path("cbs", cur, ext="html"), api.cbs_adp))
    if want("rotowire") and (not seasons or cur in seasons):
        for slug in ("PPR", "Standard"):
            jobs.append((f"rotowire {slug} {cur}", cache.raw_path("rotowire", cur, slug),
                         lambda slug=slug: api.rotowire_adp(slug)))
    return jobs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", choices=["sleeper", "espn", "ffc", "yahoo", "cbs", "rotowire"])
    ap.add_argument("--seasons", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pause", type=float, default=0.5)
    a = ap.parse_args()

    jobs = plan(a.only, a.seasons)
    print(f"{len(jobs)} responses")
    done = skipped = failed = 0
    for label, path, fetch in jobs:
        if path.is_file() and not a.force:
            skipped += 1
            continue
        if a.dry_run:
            print(f"  would download {label}")
            continue
        try:
            fetch()                       # the api function stores the raw file
        except Exception as exc:          # a year the provider cannot serve
            failed += 1
            print(f"  FAILED {label}: {type(exc).__name__}: {exc}")
            continue
        if path.is_file():
            done += 1
            print(f"  ok {label} ({path.stat().st_size / 1e6:.2f} MB gz)")
        else:
            failed += 1
            print(f"  FAILED {label}: fetched but no raw file was written")
        time.sleep(a.pause)
    total = sum(f.stat().st_size for f in ADP.rglob("raw_*.gz"))
    print(f"downloaded {done}, already there {skipped}, failed {failed}; "
          f"ADP raw files now {total / 1e6:.1f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
