"""Per-(dataset, season) parquet snapshots under data/sources/nflverse/<dataset>/.

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

from repo_paths import SOURCES_DIR, on_render

# Same root + override as the rest of the durable source-scoped data
# (data/sources/, a sibling of data/seasons/).
_NFLVERSE_DIR = SOURCES_DIR / "nflverse"

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
        if on_render():
            return df     # Render: re-read from disk rather than hold ~40MB of frames
        _mem[key] = df
        return df.copy()
    except Exception:
        return None


def save(dataset: str, season: str, df: pd.DataFrame) -> None:
    """Write the snapshot (best-effort; a read-only FS is not fatal)."""
    if not on_render():
        _mem[f"{dataset}:{season}"] = df
    try:
        p = _path(dataset, season)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Temp file + replace, so a reader never sees a half-written snapshot
        # while a background refresh is swapping it in.
        tmp = p.with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, p)
    except Exception:
        pass


# -- raw layer ---------------------------------------------------------------
# The release file exactly as downloaded, kept so a change to what we derive
# from it never needs another download.  Lives at
# data/sources/nflverse/raw/<release>/<asset file>, e.g.
# raw/player_stats/player_stats_2024.parquet, raw/schedules/games.parquet.
# Never read by the app at request time except to build a missing derived
# snapshot; see docs/data-loading-refactor-plan.md.

#: assets NOT kept raw.  Empty: play-by-play (about 20 MB a season) and its
#: participation file are kept too, by decision (2026-10-10).
NO_RAW_PREFIXES: tuple = ()


def raw_path(asset: str) -> Path:
    return _NFLVERSE_DIR / "raw" / asset


def wants_raw(asset: str) -> bool:
    return not asset.startswith(NO_RAW_PREFIXES)


def load_raw(asset: str, columns: list[str] | None = None) -> pd.DataFrame | None:
    """The stored raw release file as a frame, or None if absent/unreadable."""
    p = raw_path(asset)
    if not p.is_file():
        return None
    try:
        if columns is None:
            return pd.read_parquet(p)
        import pyarrow.parquet as pq
        present = set(pq.ParquetFile(p).schema_arrow.names)
        return pd.read_parquet(p, columns=[c for c in columns if c in present])
    except Exception:
        return None


def save_raw(asset: str, content: bytes) -> None:
    """Write the downloaded bytes untouched (best-effort, atomic)."""
    if on_render() or not wants_raw(asset):
        return
    try:
        p = raw_path(asset)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, p)
    except Exception:
        pass


_reloaded: dict[str, float] = {}   # asset -> when this process last downloaded it

#: an all-seasons file re-downloaded within this window is read from raw
#: instead, so a refresh loop over N seasons costs one download, not N
RELOAD_MEMO_SECONDS = 600


def note_download(asset: str) -> None:
    import time
    _reloaded[asset] = time.time()


def recently_downloaded(asset: str) -> bool:
    import time
    return time.time() - _reloaded.get(asset, 0.0) < RELOAD_MEMO_SECONDS


def clear() -> None:
    _mem.clear()
    _reloaded.clear()
