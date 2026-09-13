"""Public dispatch: `load(dataset, season)`."""
from __future__ import annotations

import pandas as pd

from .base import DATASETS


def load(dataset: str, season: str, reload: bool = False) -> pd.DataFrame:
    """A tidy DataFrame for one nflverse dataset + season.

    `dataset` is a key of `nflref.DATASETS` ("player_stats", "schedules").
    Snapshot-first; `reload=True` forces a live re-fetch. Returns an empty
    DataFrame for an unknown dataset or when nothing resolves (before the
    dataset's EARLIEST, or no network + no snapshot) -- never raises.
    """
    d = DATASETS.get(dataset)
    if d is None:
        return pd.DataFrame()
    return d.fetch(str(season), reload=reload)
