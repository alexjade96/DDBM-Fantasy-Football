"""League metadata and the multi-season chain (mirrors R league.R)."""
from __future__ import annotations

import time

from .api import sleeper_api, sleeper_api_many


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


# current_season_league_id() results, keyed f"{league_id}:{season}". A new
# season's league_id appears once a year, so a long TTL is fine; a stale
# entry only means the selector caps one season early until it expires or a
# ?refresh=1 clears it (webapp side).
_forward_cache: dict = {}
_FORWARD_TTL = 6 * 3600


def clear_forward_cache() -> None:
    """Drop the current_season_league_id() memo (webapp refresh path)."""
    _forward_cache.clear()


def current_season_league_id(league_id, nfl_season: str | None = None) -> str:
    """This league's most recent season's league_id, resolved FORWARD.

    Sleeper only ever links `previous_league_id` (newer -> older), so a pasted
    2024-season id cannot see the same league's live 2025/2026 season (each
    season gets its own id). This reconstructs the forward link: take the
    pasted league's members, ask Sleeper which leagues each is in for
    `nfl_season` (default: `/state/nfl`'s current season), and keep the one
    whose own backward chain shares this league's chain ROOT -- the origin id,
    which is stable for the life of the league and unique per real league, so
    a root match means "the same league, a later season".

    Returns `league_id` UNCHANGED when it is already the newest season, when
    no member's current-season leagues share the chain root, or when any
    Sleeper call fails. Never raises. Memoised for `_FORWARD_TTL`.
    """
    lid = str(league_id)
    try:
        season = str(nfl_season) if nfl_season else str(
            (nfl_state() or {}).get("league_season")
            or (nfl_state() or {}).get("season") or "")
    except Exception:
        return lid
    if not season:
        return lid

    ck = f"{lid}:{season}"
    hit = _forward_cache.get(ck)
    if hit and time.time() - hit["at"] < _FORWARD_TTL:
        return hit["id"]

    def _remember(resolved: str) -> str:
        _forward_cache[ck] = {"id": resolved, "at": time.time()}
        return resolved

    try:
        chain = league_chain(lid)
        if season in chain:
            return _remember(lid)                       # already the current season
        root = next(iter(chain.values()))["league_id"]
    except Exception:
        return lid

    try:
        rosters = sleeper_api(f"/league/{lid}/rosters") or []
    except Exception:
        return lid
    uids = sorted({r.get("owner_id") for r in rosters if r.get("owner_id")})
    if not uids:
        return _remember(lid)

    try:
        member_leagues = sleeper_api_many(
            [f"/user/{u}/leagues/nfl/{season}" for u in uids])
    except Exception:
        return lid

    # Candidate current-season league ids the members are in, deduped, the
    # pasted id itself dropped. "in_season"/"drafting" first so the live one
    # is checked before any dormant same-name league.
    seen, ordered = set(), []
    for res in member_leagues:
        for lg in (res or []):
            cid = lg.get("league_id")
            if not cid or cid == lid or cid in seen:
                continue
            seen.add(cid)
            live = (lg.get("status") or "") in ("in_season", "drafting", "pre_draft")
            ordered.append((0 if live else 1, cid))
    ordered.sort(key=lambda t: t[0])

    for _, cid in ordered:
        try:
            if next(iter(league_chain(cid).values()))["league_id"] == root:
                return _remember(cid)
        except Exception:
            continue
    return _remember(lid)


def starter_slots(roster_positions) -> dict:
    """Starter-slot counts from roster_positions (drops bench/IR/taxi)."""
    slots: dict = {}
    for p in roster_positions:
        if p in ("BN", "IR", "TAXI"):
            continue
        slots[p] = slots.get(p, 0) + 1
    return slots
