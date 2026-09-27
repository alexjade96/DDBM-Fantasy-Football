#!/usr/bin/env python
"""One-off refresh of every locally cached/stored data source this repo's
Python instance reads: re-fetches each dataset live and overwrites its
on-disk snapshot, so a stale cache doesn't silently serve last month's
numbers.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/refresh_data.py [--dry-run] [--only NAME ...]

**Refreshes what's already ON DISK, does not backfill new historical
range.** For every source below, the seasons (and, where relevant,
scoring-format variants) to refresh are DISCOVERED by scanning
`data/sources/` for existing snapshot files, not hardcoded to a fixed
list -- so if a later, separate effort backfills a source's earlier
history (e.g. route_participation's real EARLIEST is 2016 but only
2024-2025 are on disk as of this writing), just re-running this same
script picks up the new files automatically with no edit needed here.
This was a deliberate user choice over also backfilling every source's
full EARLIEST range in the same run (much slower, and re-fetches years
that may have been left out on purpose).

Every dataset in this codebase already follows a "degrade, don't raise"
contract (`nflref.base.NflDataset.fetch`, `ffadp.base.AdpProvider.fetch`,
`sleepermetrics.nflstats.raw_week`, `sleepermetrics.draft._fetch_adp_raw`
-- see each module's own docstring) -- a live pull that fails for any
reason (network, a changed/removed endpoint, a season with nothing to
report) just leaves the existing snapshot untouched rather than erroring.
This script leans on that: it calls each `reload=True` and reports what
came back, it does not need its own try/except around every call, though
one is still used per (source, season) unit so one bad combination can't
abort the whole run.

**`data/sources/default_scoring.json` is deliberately NOT touched.** It
is a static, hand-verified file (see that file's own `_comment`/`_source`
fields and `data/sources/README.md`) with no fetch function at all -- see
CLAUDE.md's own description of how it was built. Nothing here writes to
it.

**In-process TTL caches are out of scope by construction.** `webapp.
player_profile._PROFILE_CACHE` / `webapp.team_profile._PROFILE_CACHE` and
every `_mem`-style dict inside `ffadp.cache` / `nflref.cache` /
`sleepermetrics.draft` / `sleepermetrics.nflstats` / `sleepermetrics.
scoring` are plain in-memory dicts that start empty in ANY fresh Python
process -- including this script's own -- and rebuild from the disk
snapshots this script writes. There is nothing for a one-shot script to
clear.

Run from the REPO ROOT (matches tools/dev/render_examples.py's own
convention) so repo_paths.py's default SEASON_DIR/SOURCES_DIR (relative
to the repo root) resolve correctly with no env vars to set by hand.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, "fantasy-football-4-fun")

from repo_paths import SOURCES_DIR  # noqa: E402

import sleepermetrics as sm  # noqa: E402
from sleepermetrics import draft, nflstats  # noqa: E402

from webapp.sources import ffadp  # noqa: E402
from webapp.sources.ffadp import finish as ffadp_finish  # noqa: E402
from webapp.sources.nflref.base import DATASETS as NFLREF_DATASETS  # noqa: E402


def _seasons_in(dir_path: Path) -> list[str]:
    """Every 4-digit season a `<season>.<ext>` (or `<season>-<suffix>.<ext>`,
    e.g. ffadp.finish's own `<season>-<fmt>.json`) file under `dir_path`
    names, deduped and sorted -- the "what's already on disk" discovery
    this whole script is built around. Not recursive on purpose: each
    caller passes the exact leaf directory a season file actually lives in
    (a source's own root, or its `<variant>/` subdir), never a directory
    that ALSO holds other sources' own season files a season-only glob
    would wrongly pick up."""
    if not dir_path.is_dir():
        return []
    seasons: set[str] = set()
    for p in dir_path.iterdir():
        if not p.is_file():
            continue
        stem = p.stem.split("-")[0]
        if stem.isdigit() and len(stem) == 4:
            seasons.add(stem)
    return sorted(seasons)


def _weeks_in(season_dir: Path) -> list[int]:
    """Every `week_<n>.json` under a sleeper_stats/<season>/ directory."""
    if not season_dir.is_dir():
        return []
    weeks: set[int] = set()
    for p in season_dir.glob("week_*.json"):
        try:
            weeks.add(int(p.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(weeks)


class _Tally:
    """Print-and-count helper so every section reports the same shape
    (attempted / refreshed / failed) without each one hand-rolling it."""

    def __init__(self, label: str):
        self.label = label
        self.attempted = 0
        self.refreshed = 0
        self.failed = 0
        self._t0 = time.time()

    def ok(self) -> None:
        self.attempted += 1
        self.refreshed += 1

    def empty(self) -> None:
        # A degrade-to-empty result is NOT a failure (see module docstring)
        # -- it just means this particular (season, ...) combo has nothing
        # to report right now (an upcoming season, an offline endpoint).
        self.attempted += 1

    def fail(self, exc: Exception) -> None:
        self.attempted += 1
        self.failed += 1
        print(f"    ! {exc.__class__.__name__}: {exc}")

    def summary(self) -> str:
        secs = time.time() - self._t0
        return (f"{self.label}: {self.refreshed}/{self.attempted} refreshed, "
                f"{self.failed} failed ({secs:.1f}s)")


def refresh_nflref(dry_run: bool) -> _Tally:
    """`webapp.sources.nflref` -- 12 datasets, each a flat
    `data/sources/nflverse/<dataset>/<year>.parquet` snapshot. Season
    range discovered per dataset (not assumed uniform -- route_participation
    genuinely has a narrower range on disk than player_stats)."""
    t = _Tally("nflref")
    root = SOURCES_DIR / "nflverse"
    for name, dataset in NFLREF_DATASETS.items():
        seasons = _seasons_in(root / name)
        if not seasons:
            print(f"  {name}: nothing on disk, skipping")
            continue
        print(f"  {name}: {seasons[0]}-{seasons[-1]} ({len(seasons)} seasons)")
        for season in seasons:
            if dry_run:
                t.empty()
                continue
            try:
                df = dataset.fetch(season, reload=True)
                (t.ok() if not df.empty else t.empty())
            except Exception as exc:  # noqa: BLE001 - report and continue
                t.fail(exc)
    return t


def refresh_ffadp(dry_run: bool) -> _Tally:
    """`webapp.sources.ffadp` -- one provider per real-world ADP source.
    Season range discovered per provider; every one of a provider's own
    `formats` is looped (a source with one true format just rewrites the
    same file each time -- see AdpProvider.fetch's own contract, cheap
    and harmless). `data/sources/adp/<name>.json` (Sleeper's OWN
    season-scoped ADP, sleepermetrics.draft, NOT one of these per-provider
    folders) is refreshed separately, below."""
    t = _Tally("ffadp")
    root = SOURCES_DIR / "adp"
    for provider in ffadp.board.PROVIDERS:
        # SleeperAdp is the one provider with NO snapshot folder of its own
        # under adp/<name>/ -- it reads/writes the SHARED, top-level
        # data/sources/adp/<year>.json (see webapp.sources.ffadp.sleeper's
        # own header comment: "the committed Sleeper snapshot lives one
        # level up ... shared with sleepermetrics.draft"), which
        # refresh_sleeper_adp (below) already refreshes via the identical
        # underlying call (sleepermetrics.draft._fetch_adp_raw). Looping it
        # here too would just re-read that same freshly-written file
        # through this provider's own cache layer -- harmless, but
        # redundant and confusing ("nothing on disk" would print even
        # though the shared file is very much there).
        if provider.name == "sleeper":
            print("  sleeper: shares data/sources/adp/<year>.json with "
                  "sleepermetrics.draft -- refreshed below, not here")
            continue
        # A provider's own snapshots can sit directly under
        # adp/<name>/<year>.json OR nested one level deeper per format
        # (adp/<name>/<variant>/<year>.json, e.g. ffc/std/, rotowire/PPR/)
        # -- cache._path() decides which shape per call, so discovery here
        # just unions every season found at either depth rather than
        # guessing which shape this provider uses.
        base = root / provider.name
        seasons = set(_seasons_in(base))
        if base.is_dir():
            for sub in base.iterdir():
                if sub.is_dir():
                    seasons.update(_seasons_in(sub))
        seasons = sorted(seasons)
        if not seasons:
            print(f"  {provider.name}: nothing on disk, skipping")
            continue
        print(f"  {provider.name}: {seasons[0]}-{seasons[-1]} "
              f"({len(seasons)} seasons x {len(provider.formats)} format(s))")
        for season in seasons:
            for fmt in provider.formats:
                if dry_run:
                    t.empty()
                    continue
                try:
                    rows = provider.fetch(season, scoring=fmt, reload=True)
                    (t.ok() if rows else t.empty())
                except Exception as exc:  # noqa: BLE001
                    t.fail(exc)
    return t


def refresh_ffadp_finish(dry_run: bool) -> _Tally:
    """`ffadp.finish` -- the ADP board's Final/Diff end-of-season value
    ranks, `data/sources/adp/finish/<season>-<fmt>.json`. Season range
    discovered from the filename prefix (`_seasons_in` already splits on
    "-" for this exact shape). `rebuild_season` only WRITES a snapshot for
    a season the NFL has fully finished (see that function's own
    docstring) -- calling it for an in-progress season is safe, it just
    won't persist anything for that one, which is correct, not a bug to
    work around here."""
    t = _Tally("ffadp.finish")
    seasons = _seasons_in(SOURCES_DIR / "adp" / "finish")
    if not seasons:
        print("  nothing on disk, skipping")
        return t
    print(f"  {seasons[0]}-{seasons[-1]} ({len(seasons)} seasons)")
    for season in seasons:
        if dry_run:
            t.empty()
            continue
        try:
            out = ffadp_finish.rebuild_season(season)
            (t.ok() if any(out.values()) else t.empty())
        except Exception as exc:  # noqa: BLE001
            t.fail(exc)
    return t


def refresh_sleeper_adp(dry_run: bool) -> _Tally:
    """sleepermetrics.draft's OWN ADP snapshot (Sleeper's native per-season
    endpoint, `data/sources/adp/<season>.json` -- a SIBLING of the
    per-provider folders refresh_ffadp walks, not one of them; also the
    file webapp.sources.ffadp.sleeper.py itself reads). `_fetch_adp_raw`
    has no `reload` kwarg (see that function's own docstring) -- it always
    live-fetches first in a process where its `_adp_cache` entry is still
    cold, which is every entry in this script's own fresh process, so
    calling it plainly already forces a live pull."""
    t = _Tally("sleepermetrics.draft (Sleeper ADP)")
    seasons = _seasons_in(SOURCES_DIR / "adp")
    if not seasons:
        print("  nothing on disk, skipping")
        return t
    print(f"  {seasons[0]}-{seasons[-1]} ({len(seasons)} seasons)")
    for season in seasons:
        if dry_run:
            t.empty()
            continue
        try:
            out = draft._fetch_adp_raw(season)
            (t.ok() if out else t.empty())
        except Exception as exc:  # noqa: BLE001
            t.fail(exc)
    return t


def refresh_sleeper_stats(dry_run: bool) -> _Tally:
    """sleepermetrics.nflstats's own weekly usage-stat cache,
    `data/sources/sleeper_stats/<season>/week_<n>.json`. Season AND week
    range both discovered from disk (a season with only weeks 1-13 present
    -- e.g. this league's own 2022/2023 seasons -- stays refreshed to just
    those 13 weeks, not force-extended to 18; that's a backfill decision,
    out of scope per this script's own stated scope)."""
    t = _Tally("sleepermetrics.nflstats")
    root = SOURCES_DIR / "sleeper_stats"
    if not root.is_dir():
        print("  nothing on disk, skipping")
        return t
    seasons = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name.isdigit())
    if not seasons:
        print("  nothing on disk, skipping")
        return t
    for season in seasons:
        weeks = _weeks_in(root / season)
        if not weeks:
            continue
        print(f"  {season}: weeks {weeks[0]}-{weeks[-1]} ({len(weeks)} weeks)")
        for week in weeks:
            if dry_run:
                t.empty()
                continue
            try:
                out = nflstats.raw_week(season, week, reload=True)
                (t.ok() if out else t.empty())
            except Exception as exc:  # noqa: BLE001
                t.fail(exc)
    return t


_SECTIONS = {
    "nflref": refresh_nflref,
    "ffadp": refresh_ffadp,
    "ffadp-finish": refresh_ffadp_finish,
    "sleeper-adp": refresh_sleeper_adp,
    "sleeper-stats": refresh_sleeper_stats,
}


def main() -> None:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    only: set[str] | None = None
    if "--only" in args:
        i = args.index("--only")
        only = set(args[i + 1:])
        if not only:
            print("--only needs at least one section name: "
                  f"{', '.join(_SECTIONS)}")
            sys.exit(1)
        unknown = only - set(_SECTIONS)
        if unknown:
            print(f"Unknown section(s): {', '.join(sorted(unknown))}. "
                  f"Valid: {', '.join(_SECTIONS)}")
            sys.exit(1)

    if dry_run:
        print("DRY RUN -- discovering what would be refreshed, no live "
              "fetches, no files written.\n")

    tallies = []
    for name, fn in _SECTIONS.items():
        if only and name not in only:
            continue
        print(f"== {name} ==")
        tallies.append(fn(dry_run))
        print()

    print("=" * 60)
    for t in tallies:
        print(" ", t.summary())
    total_failed = sum(t.failed for t in tallies)
    if total_failed:
        print(f"\n{total_failed} combination(s) failed -- see ! lines above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
