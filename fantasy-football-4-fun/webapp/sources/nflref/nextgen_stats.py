"""NFL Next Gen Stats: real player-tracking-derived metrics.

Three releases, each ALL-SEASONS in one file (not per-year, like
`schedules`'s `games.parquet`): `ngs_passing.parquet`, `ngs_receiving.parquet`,
`ngs_rushing.parquet`. `fetch` slices each to the requested season BEFORE
snapshotting, so `data/sources/nflverse/ngs_<role>/<year>.parquet` holds just
that year.

This is the closest free equivalent to PFF's tracking-derived grades: real
chip-tracking numbers (separation, cushion, time to throw), not box-score
derivatives. `week == 0` in the raw release is nflverse's own season-aggregate
row (one row per player per season, alongside the per-week rows) -- kept
as-is rather than dropped, since a caller may want either grain.

Passing: avg_time_to_throw, aggressiveness, completion_percentage_above_
expectation (CPOE) -- QB decision-making/accuracy independent of receivers.
Receiving: avg_cushion, avg_separation, avg_yac_above_expectation -- route/
release quality independent of the QB's placement.
Rushing: rush_yards_over_expected, efficiency -- RB vision/burst independent
of the O-line's blocking (percent_attempts_gte_eight_defenders flags stacked
boxes).

**`ngs_rushing` is missing 2023 entirely** in the upstream release (verified:
every other season 2016-2026 has real rows; 2023 has zero, sandwiched
between working years on both sides -- a genuine nflverse-side gap, not a
fetch bug here). `ngs_passing`/`ngs_receiving` have no such gap.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2016

_KEEP = {
    "passing": [
        "season", "season_type", "week", "player_display_name",
        "player_position", "team_abbr", "player_gsis_id",
        "attempts", "completions", "completion_percentage",
        "pass_yards", "pass_touchdowns", "interceptions", "passer_rating",
        "avg_time_to_throw", "avg_completed_air_yards",
        "avg_intended_air_yards", "avg_air_yards_differential",
        "aggressiveness", "avg_air_yards_to_sticks",
        "expected_completion_percentage",
        "completion_percentage_above_expectation",
    ],
    "receiving": [
        "season", "season_type", "week", "player_display_name",
        "player_position", "team_abbr", "player_gsis_id",
        "receptions", "targets", "catch_percentage", "yards",
        "rec_touchdowns",
        "avg_cushion", "avg_separation", "avg_intended_air_yards",
        "percent_share_of_intended_air_yards",
        "avg_yac", "avg_expected_yac", "avg_yac_above_expectation",
    ],
    "rushing": [
        "season", "season_type", "week", "player_display_name",
        "player_position", "team_abbr", "player_gsis_id",
        "rush_attempts", "rush_yards", "avg_rush_yards", "rush_touchdowns",
        "efficiency", "percent_attempts_gte_eight_defenders",
        "avg_time_to_los",
        "expected_rush_yards", "rush_yards_over_expected",
        "rush_yards_over_expected_per_att", "rush_pct_over_expected",
    ],
}


class _NgsRole(NflDataset):
    """One NGS role (passing/receiving/rushing). Subclassed below per role
    since each has its own asset filename and column set."""

    role: str = ""
    EARLIEST = EARLIEST

    def _asset(self, season: str) -> str:
        return f"nextgen_stats/ngs_{self.role}.parquet"

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

        if "season" in raw.columns:
            try:
                raw = raw[raw["season"] == int(season)]
            except (TypeError, ValueError):
                pass
        cols = [c for c in _KEEP[self.role] if c in raw.columns]
        out = raw[cols].reset_index(drop=True)
        cache.save(self.name, season, out)
        return out


class NgsPassing(_NgsRole):
    name = "ngs_passing"
    label = "Next Gen Stats: passing"
    role = "passing"


class NgsReceiving(_NgsRole):
    name = "ngs_receiving"
    label = "Next Gen Stats: receiving"
    role = "receiving"


class NgsRushing(_NgsRole):
    name = "ngs_rushing"
    label = "Next Gen Stats: rushing"
    role = "rushing"
