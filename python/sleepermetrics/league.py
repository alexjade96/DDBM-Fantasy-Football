"""League metadata and the multi-season chain (mirrors R league.R)."""
from __future__ import annotations

from .api import sleeper_api


def league(league_id):
    """Fetch a single league object."""
    return sleeper_api(f"/league/{league_id}")


def nfl_state() -> dict:
    """Sleeper's `/state/nfl` object: current phase + season.

    `league_season` is the season leagues are currently being played/drafted
    for (stays put through the offseason, unlike `week`), which is what the
    user-league lookup below defaults to.
    """
    return sleeper_api("/state/nfl")


def user(handle):
    """Resolve a Sleeper user by numeric user_id OR by username.

    Sleeper's `/user/<x>` endpoint accepts either form and returns the same
    object (`user_id`, `username`, `display_name`, `avatar`). Returns None if
    no such user (Sleeper answers 200 with a null body in that case).
    """
    return sleeper_api(f"/user/{handle}")


def user_leagues(user_id, season, sport: str = "nfl") -> list:
    """Every league `user_id` is a member of for a given season.

    One Sleeper call per season (the endpoint is season-scoped), each league
    object carrying `league_id`, `name`, `season`, `status`, `total_rosters`,
    `avatar`, `previous_league_id`. Order is Sleeper's own (roughly most
    recently active first).
    """
    return sleeper_api(f"/user/{user_id}/leagues/{sport}/{season}") or []


def league_chain(league_id) -> dict:
    """Walk previous_league_id -> {season: link}, oldest first.

    Each link has league_id, season, name, last_scored_leg, roster_positions.
    last_scored_leg is the correct week-loop cap (live-safe; unlike state.week
    it does not reset to 0 in the offseason).
    """
    chain: dict = {}
    lid = str(league_id)
    # Sleeper marks "no previous season" two different ways depending on the
    # league: `null` on some, the string "0" on others (seen on a 2024 season
    # whose chain otherwise loaded fine). Both must stop the walk -- otherwise
    # this issues GET /league/0, which 404s and takes the whole season load
    # down with it.
    while lid and lid not in ("None", "none", "0"):
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


def root_league_id(league_id) -> str:
    """The origin (oldest) league_id in this league's season chain -- stable
    forever, since a chain only ever extends FORWARD as new seasons are
    created (the oldest link's own `previous_league_id` is null by
    definition, and Sleeper never rewrites history). This is the folder key
    `season/<league_id>/` bracket configs should use (see playoffs.py's
    `config_paths`), NOT any individual season's own, season-specific id --
    Sleeper gives every season of a league a DIFFERENT league_id, so keying
    by a single season's id would scatter one real league's brackets across
    as many folders as it has seasons.
    """
    chain = league_chain(league_id)
    return next(iter(chain.values()))["league_id"]


def starter_slots(roster_positions) -> dict:
    """Starter-slot counts from roster_positions (drops bench/IR/taxi)."""
    slots: dict = {}
    for p in roster_positions:
        if p in ("BN", "IR", "TAXI"):
            continue
        slots[p] = slots.get(p, 0) + 1
    return slots
