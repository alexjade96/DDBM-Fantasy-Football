"""nflverse-derived NFL data, for analytics not tied to a Sleeper league.

A webapp-only data layer, deliberately OUTSIDE the parity-gated
`sleepermetrics` package -- same rationale as `ffadp`: it has no `Season`
context, does third-party HTTP, and has no R counterpart (the R side would
call `nflreadr` directly). `verify.py` is unaffected.

It reads the nflverse project's own public data releases -- the `.parquet`
files nflverse publishes on GitHub, the same ones the R `nflreadr` and the
Python `nflreadpy` / `nfl_data_py` packages download. No auth, no API key, no
rate limit; CC-BY-4.0 data. We fetch the files directly (one `requests.get`
of a release asset) rather than take a library dependency, and snapshot each
to `season/nflverse/<dataset>/<year>.parquet` so a later offline / cold-host
run still has data -- the same durable-fallback pattern as `season/adp/`.

This layer is intentionally thin and dataset-oriented (not a single board
like `ffadp`): it is scaffolding for analytics built on top LATER --
strength-of-schedule off real game results, expected-points / usage models,
opponent-defense context. Each dataset is a `NflDataset` subclass returning a
tidy `pd.DataFrame`.

Public entry point: `load(dataset, season, reload=False) -> pd.DataFrame`.
"""
from . import summary
from .base import DATASETS, NflDataset
from .board import load
from .summary import (compare_sources, leaderboard_columns, player_leaderboard,
                      schedule_grid, schedule_weeks)

__all__ = [
    "load", "NflDataset", "DATASETS", "summary",
    "player_leaderboard", "leaderboard_columns", "compare_sources",
    "schedule_grid", "schedule_weeks",
]
