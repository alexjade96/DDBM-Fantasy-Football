#!/usr/bin/env python
"""Download the complete Sleeper weekly stat feed for every week already
derived on disk, and keep it under data/sources/sleeper_stats/raw/.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/backfill_sleeper_raw.py [--dry-run] [--seasons 2024 2025] [--force]

Each week is stored as raw/<season>/week_<week>.json.gz: the whole response
(about 0.6 MB of JSON per week, roughly 85 keys per player), gzip-compressed.
The trimmed usage files next to it are derived from these.  See
docs/data-loading-refactor-plan.md, steps 6 and 8a.

* Weeks come from the trimmed files already on disk (the same set the app
  uses), so nothing new is fetched for a week the app does not have.
* A week already in raw/ is skipped unless `--force`.
* Weeks are fetched one at a time, with a short pause, to be kind to Sleeper.
* Derived (trimmed) files are not touched.

MAKES REAL NETWORK CALLS (about 200 downloads for the seasons on disk at the
time of writing).  Check `git status` afterwards.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fantasy-football-4-fun"))

from repo_paths import SOURCES_DIR  # noqa: E402
from sleepermetrics import scoring  # noqa: E402


def weeks_on_disk(seasons: list[str] | None) -> list[tuple[str, int]]:
    base = SOURCES_DIR / "sleeper_stats"
    out: list[tuple[str, int]] = []
    for sdir in sorted(p for p in base.iterdir() if p.is_dir() and p.name.isdigit()):
        if seasons and sdir.name not in seasons:
            continue
        for f in sdir.glob("week_*.json"):
            try:
                out.append((sdir.name, int(f.stem.split("_")[1])))
            except (IndexError, ValueError):
                continue
    return sorted(out, key=lambda x: (x[0], x[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--seasons", nargs="*")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--pause", type=float, default=0.2)
    a = ap.parse_args()

    todo = weeks_on_disk(a.seasons)
    print(f"{len(todo)} weeks on disk")
    done = skipped = failed = 0
    for season, week in todo:
        p = scoring._raw_stats_path(season, week)
        if p.is_file() and not a.force:
            skipped += 1
            continue
        if a.dry_run:
            print(f"  would download {season} week {week}")
            continue
        lines = scoring.nfl_stats(season, week, reload=True)
        if lines and p.is_file():
            done += 1
            print(f"  ok {season} week {week} ({p.stat().st_size / 1e6:.2f} MB gz, "
                  f"{len(lines)} players)")
        else:
            failed += 1
            print(f"  FAILED {season} week {week}: empty answer or nothing written")
        time.sleep(a.pause)
    raw = SOURCES_DIR / "sleeper_stats" / "raw"
    total = sum(f.stat().st_size for f in raw.rglob("*.gz")) if raw.exists() else 0
    print(f"downloaded {done}, already there {skipped}, failed {failed}; "
          f"raw folder now {total / 1e6:.1f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
