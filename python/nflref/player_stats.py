"""nflverse weekly player stats.

One row per player per week, offensive box-score plus a few derived rates
(target share, air-yards share, wopr, fantasy points). The nflverse
counterpart to `sleepermetrics.nflstats` (which reads the same kind of data
from Sleeper's own feed) -- kept here so a later analytics layer can
cross-check the two or reach for nflverse-only columns (`target_share`,
`air_yards_share`, `wopr`, `pacr`, `racr`).

Real data from 2016 on (nflfastR's play-by-play, which this is aggregated
from, starts at 1999, but the weekly player-stats release begins 2016).

nflverse retired the old `player_stats` release after 2024; it publishes
`player_stats/player_stats_<year>.parquet` for 2016-2024 only. From 2025 the
same weekly frame lives in the `stats_player` release as
`stats_player_week_<year>.parquet` -- a superset with two columns renamed
(`recent_team` -> `team`, `interceptions` -> `passing_interceptions`), which
`_tidy` normalises back so the schema this codebase sees is stable across
both. `_LEGACY_LAST` is the cutover year.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2016

# Last season nflverse published under the old `player_stats` release naming;
# 2025+ comes from the `stats_player` release instead (see the module docstring).
_LEGACY_LAST = 2024

# The two columns the newer `stats_player_week` release renamed, mapped back to
# the names `_KEEP` (and the rest of this codebase) expect.
_RENAMES = {"team": "recent_team", "passing_interceptions": "interceptions"}

# Columns we keep from the raw release: identity + volume + the
# nflverse-derived usage rates that Sleeper's feed does NOT give us directly.
_KEEP = [
    "player_id", "player_display_name", "position", "recent_team", "season",
    "week", "season_type",
    "targets", "receptions", "receiving_yards", "receiving_tds",
    "receiving_air_yards", "target_share", "air_yards_share", "wopr", "racr",
    "carries", "rushing_yards", "rushing_tds",
    "attempts", "completions", "passing_yards", "passing_tds", "interceptions",
    "passing_air_yards", "pacr",
    "fantasy_points", "fantasy_points_ppr",
]


class PlayerStats(NflDataset):
    name = "player_stats"
    label = "nflverse weekly player stats"

    def _asset(self, season: str) -> str:
        try:
            legacy = int(season) <= _LEGACY_LAST
        except (TypeError, ValueError):
            legacy = False
        if legacy:
            return f"player_stats/player_stats_{season}.parquet"
        return f"stats_player/stats_player_week_{season}.parquet"

    def _tidy(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.rename(columns={k: v for k, v in _RENAMES.items()
                                if k in df.columns and v not in df.columns})
        cols = [c for c in _KEEP if c in df.columns]
        out = df[cols].copy()
        # regular season only, to match the rest of the codebase's default
        if "season_type" in out.columns:
            out = out[out["season_type"] == "REG"].drop(columns=["season_type"])
        return out.reset_index(drop=True)
