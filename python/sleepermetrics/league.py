"""League metadata and the multi-season chain (mirrors R league.R)."""
from __future__ import annotations

from .api import sleeper_api


def league(league_id):
    """Fetch a single league object."""
    return sleeper_api(f"/league/{league_id}")


def league_chain(league_id) -> dict:
    """Walk previous_league_id -> {season: link}, oldest first.

    Each link has league_id, season, name, last_scored_leg, roster_positions.
    last_scored_leg is the correct week-loop cap (live-safe; unlike state.week
    it does not reset to 0 in the offseason).
    """
    chain: dict = {}
    lid = str(league_id)
    while lid and lid not in ("None", "none"):
        lg = sleeper_api(f"/league/{lid}")
        chain[lg["season"]] = {
            "league_id": lg["league_id"],
            "season": lg["season"],
            "name": lg.get("name"),
            "last_scored_leg": (lg.get("settings") or {}).get("last_scored_leg") or 0,
            "roster_positions": lg.get("roster_positions") or [],
            # Phase signals, straight from Sleeper: status tells you whether the
            # season is still being played, playoff_week_start where the regular
            # season ends. Both are needed to say "currently 3rd" instead of
            # "finished 3rd" -- and to keep postseason weeks out of the record.
            "status": lg.get("status"),
            "playoff_week_start": (lg.get("settings") or {}).get("playoff_week_start") or 0,
        }
        lid = lg.get("previous_league_id")
    return dict(sorted(chain.items(), key=lambda kv: int(kv[0])))


def starter_slots(roster_positions) -> dict:
    """Starter-slot counts from roster_positions (drops bench/IR/taxi)."""
    slots: dict = {}
    for p in roster_positions:
        if p in ("BN", "IR", "TAXI"):
            continue
        slots[p] = slots.get(p, 0) + 1
    return slots
