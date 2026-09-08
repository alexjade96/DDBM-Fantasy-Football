"""Per-(dataset, season) parquet snapshots under season/nflverse/<dataset>/.

Same durable-fallback contract as ffadp.cache / sleepermetrics.draft's ADP
cache: a successful live fetch writes the tidy frame to disk; a later run
with no network falls back to it. Parquet, not JSON -- these frames are wide
(dozens of columns, hundreds of rows) and parquet keeps dtypes.

Committed to the repo on purpose where a snapshot is added: the file IS the
fallback for an offline / cold-host render.
"""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

# Same root + override as the rest of the durable season data.
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_NFLVERSE_DIR = _SEASON_DIR / "nflverse"

_mem: dict[str, pd.DataFrame] = {}   # f"{dataset}:{season}" -> frame


def _path(dataset: str, season: str) -> Path:
    return _NFLVERSE_DIR / dataset / f"{season}.parquet"


def load(dataset: str, season: str, force: bool = False) -> pd.DataFrame | None:
    """The stored snapshot, or None if absent. `force` skips both caches
    (the caller wants a live re-fetch)."""
    if force:
        return None
    key = f"{dataset}:{season}"
    if key in _mem:
        return _mem[key].copy()
    try:
        df = pd.read_parquet(_path(dataset, season))
        _mem[key] = df
        return df.copy()
    except Exception:
        return None


def save(dataset: str, season: str, df: pd.DataFrame) -> None:
    """Write the snapshot (best-effort; a read-only FS is not fatal)."""
    _mem[f"{dataset}:{season}"] = df
    try:
        p = _path(dataset, season)
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(p, index=False)
    except Exception:
        pass


def clear() -> None:
    _mem.clear()
