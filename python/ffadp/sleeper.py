"""Sleeper ADP provider.

Snapshot-first: a committed / previously-fetched season/adp/<year>.json is
used as-is unless it is missing or a `reload` is asked for, in which case it
delegates to sleepermetrics.draft._fetch_adp_raw() (which does the live pull
and rewrites that same file). So the tab does not re-hit Sleeper's endpoint on
every request, and there is still ONE Sleeper ADP snapshot on disk.

REDRAFT only. Sleeper's projections endpoint also carries adp_dynasty*,
adp_rookie and adp_idp* fields; this provider maps the board's scoring key
onto the redraft fields (`adp_std` / `adp_half_ppr` / `adp_ppr` / `adp_2qb`)
exclusively. There is no TE-premium ADP field to expose.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sleepermetrics import draft as _draft

from .base import AdpProvider, AdpRow

# Board scoring key -> the REDRAFT field in a season/adp/<year>.json row.
_FIELD = {
    "std": "adp_std",
    "half_ppr": "adp_half_ppr",
    "ppr": "adp_ppr",
    "2qb": "adp_2qb",
}

# Sleeper's ADP endpoint returns usable data from 2020 on (thin in 2020,
# solid 2022+); 2019 and earlier come back with every ADP zeroed.
EARLIEST = 2020

# The committed Sleeper snapshot lives one level up from the per-source dirs
# (season/adp/<year>.json, shared with sleepermetrics.draft).
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_SNAPSHOT_DIR = _SEASON_DIR / "adp"


def _snapshot(season: str) -> dict | None:
    """The committed season/adp/<year>.json as {sleeper_id: {...}}, or None."""
    try:
        d = json.loads((_SNAPSHOT_DIR / f"{season}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) and d else None
    except Exception:
        return None


class SleeperAdp(AdpProvider):
    name = "sleeper"
    label = "Sleeper"
    group = "apps"
    formats = ("std", "half_ppr", "ppr", "2qb")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        try:
            if int(season) < EARLIEST:
                return []
        except (TypeError, ValueError):
            pass

        raw = None if reload else _snapshot(str(season))
        if raw is None:
            # Missing snapshot, or an explicit reload: live pull, which
            # rewrites season/adp/<year>.json. Degrades to {} offline.
            raw = _draft._fetch_adp_raw(season)

        field = _FIELD[self._format_or_fallback(scoring)]
        rows: list[AdpRow] = []
        for pid, d in (raw or {}).items():
            v = d.get(field)
            if v is None or v >= 999:          # Sleeper's "no ADP here" sentinel
                continue
            rows.append(AdpRow(
                source=self.name,
                name=d.get("player_name") or str(pid),
                position=d.get("position"),
                adp=float(v),
                sleeper_id=str(pid),
            ))
        rows.sort(key=lambda r: r.adp)
        for i, r in enumerate(rows, 1):
            r.overall_rank = i
        return rows
