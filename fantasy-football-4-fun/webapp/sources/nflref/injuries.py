"""nflverse weekly official injury reports.

One row per player per team-week they appeared on the injury report (not
every player every week -- only those actually listed). Carries the
SPECIFIC injury (`report_primary_injury`/`report_secondary_injury`, e.g.
"Knee", "Hamstring", "Concussion", "Illness" -- 20+ distinct categories, not
just a generic flag), the final game-status designation
(`report_status`: Out / Doubtful / Questionable / NaN when untagged), and
the daily practice-report detail (`practice_status` / `practice_primary_
injury` / `practice_secondary_injury`), which can differ from the final
report earlier in the week.

Context data, not a rankable stat: the value here is explaining a bad
week ("was this a real decline or a hamstring") or tracking a recurring
injury across a season, not ranking players against each other.
`gsis_id` is the join key (verified: zero nulls across this league's real
seasons 2022-2025), same id space `player_stats`/`nextgen_stats`/
`pfr_advstats` all already use.

Covers regular season through Super Bowl (`game_type`: REG/WC/DIV/CON/SB),
weeks 1-22 depending on season.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2009

_KEEP = [
    "season", "game_type", "week", "team", "gsis_id", "position", "full_name",
    "report_primary_injury", "report_secondary_injury", "report_status",
    "practice_primary_injury", "practice_secondary_injury", "practice_status",
    "date_modified",
]


class Injuries(NflDataset):
    name = "injuries"
    label = "nflverse weekly injury reports"

    def _asset(self, season: str) -> str:
        return f"injuries/injuries_{season}.parquet"

    def _tidy(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = [c for c in _KEEP if c in df.columns]
        return df[cols].reset_index(drop=True)
