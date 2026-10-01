"""HTTP access to nflverse's public data releases.

nflverse publishes every dataset as a versioned GitHub release on
`nflverse/nflverse-data`; each season's file is a plain release asset at a
predictable URL. No auth, no cookies, no rate limit. One place for the
outbound call so a test can monkeypatch a single function and the suite stays
network-free.

Verified directly fetchable (HEAD 200, application/octet-stream):
  player_stats/player_stats_<year>.parquet   ~330 KB
  snap_counts/snap_counts_<year>.parquet     ~240 KB
  schedules/games.parquet                    ~520 KB (all seasons in one file)
  nextgen_stats/ngs_{passing,receiving,rushing}.parquet   ~350 KB-1.1 MB
                                              (all seasons in one file each)
  pfr_advstats/advstats_week_{pass,rec,rush,def}_<year>.parquet   ~20-160 KB
  injuries/injuries_<year>.parquet           ~85 KB
  pbp/play_by_play_<year>.parquet            ~20 MB
"""
from __future__ import annotations

import os
from io import BytesIO

import pandas as pd
import requests

_UA = "sleepermetrics-nflref/1.0 (+https://github.com/alexjade96/DDBM-Fantasy-Football)"
_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def head_release(asset: str, validators: dict | None = None) -> tuple[str, dict | None]:
    """Has one release asset changed since `validators` were recorded?

    A conditional HEAD (`If-None-Match` / `If-Modified-Since`): GitHub's asset
    host answers `304 Not Modified` with no body when nothing changed. Returns
    `("unchanged", validators)`, `("changed", {"etag", "last_modified"})`, or
    `("error", None)` when the host can't be reached. Never raises.
    """
    headers = {"User-Agent": _UA}
    if validators:
        if validators.get("etag"):
            headers["If-None-Match"] = validators["etag"]
        if validators.get("last_modified"):
            headers["If-Modified-Since"] = validators["last_modified"]
    try:
        resp = requests.head(f"{_BASE}/{asset}", headers=headers, timeout=20,
                             allow_redirects=True)
    except Exception:
        return "error", None
    if resp.status_code == 304:
        return "unchanged", validators
    if resp.status_code >= 400:
        return "error", None
    new = {"etag": resp.headers.get("ETag"),
           "last_modified": resp.headers.get("Last-Modified")}
    # A host that ignores the conditional headers answers 200 every time;
    # an identical ETag still means unchanged.
    if validators and new["etag"] and new["etag"] == validators.get("etag"):
        return "unchanged", validators
    return "changed", new


def on_render() -> bool:
    """True only on a Render host (Render sets `RENDER=true`). Memory-saving
    behaviour that exists for Render's 512MB instances is gated on this, so a
    dev/test server behaves exactly as before."""
    return os.environ.get("RENDER", "").lower() == "true"


def read_release_parquet(asset: str, columns: list[str] | None = None) -> pd.DataFrame:
    """Download one nflverse-data release asset and parse it.

    `asset` is the release path, e.g. `"player_stats/player_stats_2024.parquet"`
    (the first segment is the release tag, the rest the file name). Raises on a
    non-2xx or an unparseable body so the caller (NflDataset.fetch) can fall
    back to its on-disk snapshot.

    `columns` limits the parse to those columns (any not in the file are
    ignored), so a wide asset such as play-by-play (372 columns) does not
    materialise every column.
    """
    url = f"{_BASE}/{asset}"
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=60,
                        allow_redirects=True)
    resp.raise_for_status()
    buf = BytesIO(resp.content)
    del resp
    if columns is None:
        return pd.read_parquet(buf)
    import pyarrow.parquet as pq
    present = set(pq.ParquetFile(buf).schema_arrow.names)
    buf.seek(0)
    return pd.read_parquet(buf, columns=[c for c in columns if c in present])
