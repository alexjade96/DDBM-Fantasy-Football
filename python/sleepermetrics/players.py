"""Player metadata lookup, cached daily (mirrors R players.R)."""
from __future__ import annotations

import datetime
import os
import pickle

import pandas as pd

from .api import sleeper_api

_cache: pd.DataFrame | None = None


def players(refresh: bool = False, cache_path: str = "sleeperPlayerData_py.pkl") -> pd.DataFrame:
    """Return a DataFrame: player_id, player_name, position, gsis_id.

    DEF "players" are team defenses; their name is the team abbreviation.
    The full player dump is cached on disk (refetched at most once/day) and
    memoised for the process.
    """
    global _cache
    if _cache is not None and not refresh:
        return _cache
    fresh = (
        os.path.exists(cache_path)
        and datetime.date.fromtimestamp(os.path.getmtime(cache_path)) == datetime.date.today()
    )
    if fresh and not refresh:
        with open(cache_path, "rb") as fh:
            raw = pickle.load(fh)
    else:
        raw = sleeper_api("/players/nfl")
        with open(cache_path, "wb") as fh:
            pickle.dump(raw, fh)
    rows = []
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        pos = p.get("position")
        rows.append({
            "player_id": pid,
            "player_name": pid if pos == "DEF" else p.get("full_name"),
            "position": pos,
            "gsis_id": p.get("gsis_id"),
        })
    _cache = pd.DataFrame(rows)
    return _cache
