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
  pbp/play_by_play_<year>.parquet            ~20 MB
"""
from __future__ import annotations

from io import BytesIO

import pandas as pd
import requests

_UA = "sleepermetrics-nflref/1.0 (+https://github.com/alexjade96/DDBM-Fantasy-Football)"
_BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def read_release_parquet(asset: str) -> pd.DataFrame:
    """Download one nflverse-data release asset and parse it.

    `asset` is the release path, e.g. `"player_stats/player_stats_2024.parquet"`
    (the first segment is the release tag, the rest the file name). Raises on a
    non-2xx or an unparseable body so the caller (NflDataset.fetch) can fall
    back to its on-disk snapshot.
    """
    url = f"{_BASE}/{asset}"
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=60,
                        allow_redirects=True)
    resp.raise_for_status()
    return pd.read_parquet(BytesIO(resp.content))
