"""nflverse weekly snap counts, split by offense/defense/special-teams.

Sourced from Pro-Football-Reference's own snap-count tables (nflverse's
`snap_counts` release). One row per player per game, with `offense_pct` /
`defense_pct` / `st_pct` -- the snap share for each side of the ball that
game.

Genuinely new versus `sleepermetrics.nflstats.raw_week` (Sleeper's own
weekly feed): Sleeper's `off_snp`/`tm_off_snp` gives OFFENSIVE snap share
only. This adds defensive and special-teams snap share, useful for IDP
context and for catching a role change special-teams-first (a depth WR
gaining offensive snaps while losing ST ones, etc).
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

# The 2012 release asset exists but is genuinely empty (verified: 200 OK,
# 0 rows) -- same shape as ffadp.espn's 2004 gap. Real usable data starts
# 2013; EARLIEST stays 2012 since the guard degrades to an empty frame
# either way, and this preserves "the release's own claimed floor."
EARLIEST = 2012

_KEEP = [
    "game_id", "season", "game_type", "week", "player", "pfr_player_id",
    "position", "team", "opponent",
    "offense_snaps", "offense_pct", "defense_snaps", "defense_pct",
    "st_snaps", "st_pct",
]


class SnapCounts(NflDataset):
    name = "snap_counts"
    label = "nflverse snap counts (off/def/ST)"

    def _asset(self, season: str) -> str:
        return f"snap_counts/snap_counts_{season}.parquet"

    def _tidy(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = [c for c in _KEEP if c in df.columns]
        return df[cols].reset_index(drop=True)
