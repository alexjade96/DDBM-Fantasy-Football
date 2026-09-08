"""nflverse game schedules + results.

The `schedules` release is ONE file covering every season (not per-year). One
row per game: teams, kickoff, final score, spread/total, roof/surface, rest
days.

The intended first analytics use is a REAL strength-of-schedule: opponent
identity and actual game results per week, independent of Sleeper's fantasy
matchups (which `metrics.strength_of_schedule` currently proxies from league
PPG). Data goes back to 1999.

Because the upstream file is all-seasons, `fetch` slices it to the requested
year BEFORE snapshotting, so `season/nflverse/schedules/<year>.parquet` holds
just that year -- not a copy of the whole league's history per file.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 1999

_KEEP = [
    "game_id", "season", "game_type", "week", "gameday", "weekday",
    "away_team", "home_team", "away_score", "home_score", "result", "total",
    "overtime", "away_rest", "home_rest", "spread_line", "total_line",
    "roof", "surface", "temp", "wind", "stadium",
]


class Schedules(NflDataset):
    name = "schedules"
    label = "nflverse schedules & results"

    def _asset(self, season: str) -> str:
        # the "schedules" release publishes it as games.parquet, all seasons
        # in one file (maintained in Lee Sharpe's nfldata).
        return "schedules/games.parquet"

    def fetch(self, season: str, reload: bool = False) -> pd.DataFrame:
        from . import api, cache

        season = str(season)
        try:
            if int(season) < EARLIEST:
                return pd.DataFrame()
        except (TypeError, ValueError):
            pass

        if not reload:
            cached = cache.load(self.name, season)
            if cached is not None:
                return cached

        try:
            raw = api.read_release_parquet(self._asset(season))
        except Exception:
            raw = None

        if raw is None or raw.empty:
            if reload:
                cached = cache.load(self.name, season)
                if cached is not None:
                    return cached
            return pd.DataFrame()

        cols = [c for c in _KEEP if c in raw.columns]
        out = raw[cols].copy()
        if "season" in out.columns:
            try:
                out = out[out["season"] == int(season)]
            except (TypeError, ValueError):
                pass
        out = out.reset_index(drop=True)
        cache.save(self.name, season, out)
        return out
