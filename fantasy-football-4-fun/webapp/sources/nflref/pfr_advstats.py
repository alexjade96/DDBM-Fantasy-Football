"""Pro-Football-Reference's advanced weekly stats, via nflverse's own scrape.

Four roles, each its own release asset per season (`advstats_week_<role>_
<year>.parquet`), each with a genuinely different column set -- registered
as four separate dataset names (`pfr_pass`/`pfr_rec`/`pfr_rush`/`pfr_def`)
rather than one, since a "passing" row and a "rushing" row share almost no
columns.

This is the best value-to-effort PFF-comparable data available: already
player-level and per-game (no play-level explode/join needed, unlike
`ftn_charting`/`pbp_participation`), covering exactly the kind of thing PFF
charges for -- broken tackles, pressure rate, yards before/after contact,
drop rate, missed tackles. `EARLIEST = 2018` for all four (PFR's advanced-
stats era; verified live, no earlier release assets exist).

  pfr_pass: times_pressured / times_pressured_pct / times_blitzed /
            passing_bad_throw_pct -- QB performance under duress, independent
            of the box-score line.
  pfr_rec:  receiving_drop / receiving_drop_pct / receiving_rat -- separates
            an unlucky/unreliable WR from a badly-thrown-to one.
  pfr_rush: rushing_yards_before_contact / rushing_yards_after_contact /
            rushing_broken_tackles -- separates RB talent from O-line push.
  pfr_def:  def_missed_tackles / def_pressures / def_passer_rating_allowed --
            IDP-relevant coverage/tackling detail.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset

EARLIEST = 2018

_KEEP = {
    "pass": [
        "season", "week", "game_type", "team", "opponent",
        "pfr_player_name", "pfr_player_id",
        "passing_bad_throws", "passing_bad_throw_pct",
        "times_sacked", "times_blitzed", "times_hurried", "times_hit",
        "times_pressured", "times_pressured_pct",
    ],
    "rec": [
        "season", "week", "game_type", "team", "opponent",
        "pfr_player_name", "pfr_player_id",
        "rushing_broken_tackles", "receiving_broken_tackles",
        "receiving_drop", "receiving_drop_pct",
        "receiving_int", "receiving_rat",
    ],
    "rush": [
        "season", "week", "game_type", "team", "opponent",
        "pfr_player_name", "pfr_player_id",
        "carries",
        "rushing_yards_before_contact", "rushing_yards_before_contact_avg",
        "rushing_yards_after_contact", "rushing_yards_after_contact_avg",
        "rushing_broken_tackles", "receiving_broken_tackles",
    ],
    "def": [
        "season", "week", "game_type", "team", "opponent",
        "pfr_player_name", "pfr_player_id",
        "def_ints", "def_targets", "def_completions_allowed",
        "def_completion_pct", "def_yards_allowed",
        "def_yards_allowed_per_cmp", "def_yards_allowed_per_tgt",
        "def_receiving_td_allowed", "def_passer_rating_allowed",
        "def_adot", "def_air_yards_completed", "def_yards_after_catch",
        "def_times_blitzed", "def_times_hurried", "def_times_hitqb",
        "def_sacks", "def_pressures",
        "def_tackles_combined", "def_missed_tackles", "def_missed_tackle_pct",
    ],
}


class _PfrRole(NflDataset):
    """One PFR advanced-stats role. Subclassed below per role since each has
    its own asset filename and column set."""

    role: str = ""
    EARLIEST = EARLIEST

    def _asset(self, season: str) -> str:
        return f"pfr_advstats/advstats_week_{self.role}_{season}.parquet"

    def _tidy(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = [c for c in _KEEP[self.role] if c in df.columns]
        return df[cols].reset_index(drop=True)


class PfrPass(_PfrRole):
    name = "pfr_pass"
    label = "PFR advanced: passing"
    role = "pass"


class PfrRec(_PfrRole):
    name = "pfr_rec"
    label = "PFR advanced: receiving"
    role = "rec"


class PfrRush(_PfrRole):
    name = "pfr_rush"
    label = "PFR advanced: rushing"
    role = "rush"


class PfrDef(_PfrRole):
    name = "pfr_def"
    label = "PFR advanced: defense"
    role = "def"
