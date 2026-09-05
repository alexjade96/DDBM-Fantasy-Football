"""Per-(source, season) JSON snapshots under season/adp/<source>/<year>.json.

Mirrors sleepermetrics.draft's own season/adp/<year>.json contract: a live
fetch writes the trimmed result to disk on success; a later run with no
network (or after an undocumented endpoint changes) falls back to that
snapshot. Committed to the repo on purpose -- the snapshot IS the fallback.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Same root + override as sleepermetrics.draft, so all durable season data
# lives in one tree.
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_ADP_DIR = _SEASON_DIR / "adp"

_mem: dict[str, list] = {}   # f"{source}:{variant}:{season}" -> rows (list[dict])


def _path(source: str, season: str, variant: str | None = None) -> Path:
    """season/adp/<source>/<year>.json, or season/adp/<source>/<variant>/<year>.json
    when a source keeps a separate snapshot per scoring format (FFC does)."""
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
        p.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass


def clear() -> None:
    _mem.clear()
