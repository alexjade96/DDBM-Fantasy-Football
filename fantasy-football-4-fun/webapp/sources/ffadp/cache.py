"""Per-(source, season) JSON snapshots under data/sources/adp/<source>/<year>.json.

Mirrors sleepermetrics.draft's own data/sources/adp/<year>.json contract: a
live fetch writes the trimmed result to disk on success; a later run with no
network (or after an undocumented endpoint changes) falls back to that
snapshot. Committed to the repo on purpose -- the snapshot IS the fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from repo_paths import SOURCES_DIR, on_render

# Same root + override as sleepermetrics.draft, so all durable source-scoped
# data lives in one tree (data/sources/, a sibling of data/seasons/).
_ADP_DIR = SOURCES_DIR / "adp"

_mem: dict[str, list] = {}   # f"{source}:{variant}:{season}" -> rows (list[dict])


def _path(source: str, season: str, variant: str | None = None) -> Path:
    """data/sources/adp/<source>/<year>.json, or
    data/sources/adp/<source>/<variant>/<year>.json when a source keeps a
    separate snapshot per scoring format (FFC does)."""
    base = _ADP_DIR / source
    if variant:
        base = base / variant
    return base / f"{season}.json"


def _key(source: str, season: str, variant: str | None) -> str:
    return f"{source}:{variant or '-'}:{season}"


def load(source: str, season: str, force: bool = False,
         variant: str | None = None) -> list[dict] | None:
    """The stored snapshot as a list of plain dicts, or None if absent.

    Checks the in-process cache first, then the on-disk snapshot. `force=True`
    skips both -- the caller wants a fresh live fetch (the "reload" path).
    `variant` selects a per-scoring-format snapshot subdir when the source
    keeps one.
    """
    if force:
        return None
    key = _key(source, season, variant)
    if key in _mem:
        return _mem[key]
    try:
        rows = json.loads(_path(source, season, variant).read_text(encoding="utf-8"))
        if isinstance(rows, list):
            _mem[key] = rows
            return rows
    except Exception:
        pass
    return None


def save(source: str, season: str, rows: list[dict],
         variant: str | None = None) -> None:
    """Write the snapshot (best-effort; a read-only FS is not fatal)."""
    _mem[_key(source, season, variant)] = rows
    try:
        p = _path(source, season, variant)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Temp file + replace, so a background refresh never exposes a
        # half-written snapshot to a concurrent read.
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    except Exception:
        pass


def clear() -> None:
    _mem.clear()


# -- raw layer ---------------------------------------------------------------
# The provider's response exactly as received, gzip-compressed, kept before it
# is trimmed:  data/sources/adp/<provider>/raw/[<variant>/]raw_<season>.<ext>.gz
# (Sleeper's own: data/sources/adp/sleeper/raw/).  The "raw_" prefix keeps the
# season scanners (which read four-digit file names) from mistaking these for
# snapshots.  A source that serves only the current season (CBS, RotoWire) keeps
# the latest copy per season: it cannot be fetched again for an earlier year.
# Yahoo's raw file is a JSON list of its page bodies (it is fetched in pages).


def current_season() -> str:
    """The NFL season whose draft is under way: the calendar year from March,
    the previous one in January and February."""
    from datetime import date
    d = date.today()
    return str(d.year if d.month >= 3 else d.year - 1)


def raw_path(source: str, season, variant: str | None = None, ext: str = "json") -> Path:
    base = _ADP_DIR / source / "raw"
    if variant:
        base = base / variant
    return base / f"raw_{season}.{ext}.gz"


def save_raw(source: str, season, content: bytes, variant: str | None = None,
             ext: str = "json") -> None:
    """Keep the response bytes untouched.  Not on Render (its disk is discarded;
    the committed files ship in the image)."""
    if on_render():
        return
    from sleepermetrics.rawfile import save_gz
    save_gz(raw_path(source, season, variant, ext), content)


def load_raw(source: str, season, variant: str | None = None,
             ext: str = "json") -> bytes | None:
    from sleepermetrics.rawfile import load_gz
    return load_gz(raw_path(source, season, variant, ext))


def from_raw(source: str, season, parse, variant: str | None = None,
             ext: str = "json") -> list[dict] | None:
    """Rebuild a missing snapshot from the stored raw response, with no network.

    `parse(bytes)` returns the trimmed rows.  Writes the snapshot and returns
    the rows; None when there is no raw copy, it cannot be parsed, or it trims
    to nothing.  Skipped on Render, where a 28 MB ESPN response should not be
    parsed on a 512 MB instance (the committed snapshots are there instead)."""
    if on_render():
        return None
    blob = load_raw(source, season, variant, ext)
    if blob is None:
        return None
    try:
        rows = parse(blob)
    except Exception:
        return None
    if not rows:
        return None
    save(source, season, rows, variant=variant)
    return rows
