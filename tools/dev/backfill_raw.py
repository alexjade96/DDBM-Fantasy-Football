#!/usr/bin/env python
"""Download the complete nflverse release file for every season already
derived on disk, and keep it under data/sources/nflverse/raw/.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/backfill_raw.py [--dry-run] [--only NAME ...] [--force]

Why: derived snapshots (data/sources/nflverse/<dataset>/<year>.parquet) are
trimmed to the columns the app uses.  Keeping the file as released means a
later change to what is derived needs no download.  See
docs/data-loading-refactor-plan.md, steps 2 to 4.

* Seasons come from the derived files already on disk, the same discovery
  `refresh_data.py` uses, so nothing new is fetched for a season the app
  does not have.
* An all-seasons file (schedules, Next Gen Stats) is one download, not one
  per season.
* A file already in raw/ is skipped unless `--force`.
* `route_participation` is skipped by default.  Its sources, play-by-play
  (about 20 MB a season) and the participation file (about 5 MB), are fetched
  only with `--include-pbp`, for every season from 2016 on (the participation
  file for the current season does not exist yet and is reported as failed).
  They are stored without parsing.
* Derived files are not touched.
* Writes raw/manifest.json: for each file its URL, fetch time and size.

MAKES REAL NETWORK CALLS.  Check `git status` afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fantasy-football-4-fun"))

from repo_paths import SOURCES_DIR  # noqa: E402
from webapp.sources.nflref import api, cache  # noqa: E402
from webapp.sources.nflref.base import DATASETS  # noqa: E402

SKIP = {"route_participation"}


def _seasons_on_disk(name: str) -> list[str]:
    d = SOURCES_DIR / "nflverse" / name
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.parquet") if p.stem.isdigit())


def plan(only: list[str] | None) -> dict[str, list[str]]:
    """asset -> the datasets/seasons that need it (one download per asset)."""
    assets: dict[str, list[str]] = {}
    for name, ds in DATASETS.items():
        if name in SKIP or (only and name not in only):
            continue
        for season in _seasons_on_disk(name):
            assets.setdefault(ds._asset(season), []).append(f"{name} {season}")
    return assets


def pbp_assets() -> list[str]:
    from datetime import date
    EARLIEST = 2016          # the files exist from 2016, even though routes build from 2023
    d = date.today()
    current = d.year if d.month >= 3 else d.year - 1
    out = []
    for y in range(EARLIEST, current + 1):
        out.append(f"pbp/play_by_play_{y}.parquet")
        out.append(f"pbp_participation/pbp_participation_{y}.parquet")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--force", action="store_true",
                    help="download again even if the raw file exists")
    ap.add_argument("--include-pbp", action="store_true",
                    help="also fetch play-by-play and participation (about 280 MB)")
    a = ap.parse_args()

    assets = plan(a.only)
    if a.include_pbp:
        for asset in pbp_assets():
            assets.setdefault(asset, []).append("route_participation")
    print(f"{len(assets)} release files for "
          f"{sum(len(v) for v in assets.values())} dataset-seasons")
    manifest_path = cache.raw_path("manifest.json")
    manifest = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    done = skipped = failed = 0
    for asset in sorted(assets):
        p = cache.raw_path(asset)
        if p.is_file() and not a.force:
            skipped += 1
            manifest.setdefault(asset, {"url": f"{api._BASE}/{asset}",
                                        "fetched": "before manifest",
                                        "bytes": p.stat().st_size})
            continue
        if a.dry_run:
            print(f"  would download {asset}")
            continue
        try:
            if asset.startswith(("pbp/", "pbp_participation/")):
                api.store_release(asset)          # large: stored without parsing
            else:
                api.read_release_parquet(asset)   # stores the raw file as it arrives
        except Exception as exc:                  # 404 for an unpublished season, etc.
            failed += 1
            print(f"  FAILED {asset}: {type(exc).__name__}: {exc}")
            continue
        if p.is_file():
            done += 1
            manifest[asset] = {
                "url": f"{api._BASE}/{asset}",
                "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "bytes": p.stat().st_size,
            }
            print(f"  ok {asset} ({p.stat().st_size / 1e6:.2f} MB)")
        else:
            failed += 1
            print(f"  FAILED {asset}: downloaded but no raw file was written")

    if not a.dry_run and manifest:
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True),
                                 encoding="utf-8")
    total = sum(f.stat().st_size for f in cache.raw_path("").rglob("*")
                if f.is_file()) if cache.raw_path("").exists() else 0
    print(f"downloaded {done}, already there {skipped}, failed {failed}; "
          f"raw folder now {total / 1e6:.1f} MB")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
