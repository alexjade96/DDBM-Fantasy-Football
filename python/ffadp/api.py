"""Thin HTTP wrappers for the non-Sleeper ADP sources.

One place for the outbound calls so a test can monkeypatch a single function
and the network stays out of the suite. Sleeper's own ADP endpoint is wrapped
in sleepermetrics.api and reused from there.
"""
from __future__ import annotations

import json

import requests

_UA = "sleepermetrics-ffadp/1.0 (+https://github.com/alexjade96/DDBM-Fantasy-Football)"

# ESPN's read replica. The public "players" list view carries
# ownership.averageDraftPosition platform-wide -- no league id, no cookies.
# Confirmed working for seasons 2004..present.
_ESPN_BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"


def espn_players(season) -> list:
    """Raw ESPN kona_player_info list for a season (one big JSON array).

    The response is large (~20 MB: ~2,900 players with full stat blocks) and
    ESPN ignores an x-fantasy-filter `limit`, so callers MUST trim + snapshot
    the result rather than hold it. Raises on any non-2xx / non-JSON so the
    provider can fall back to its on-disk snapshot.
    """
    url = f"{_ESPN_BASE}/seasons/{season}/players?scoringPeriodId=0&view=kona_player_info"
    # A minimal filter -- ESPN wants the header present even though it ignores
    # `limit` on this view.
    hdrs = {
        "User-Agent": _UA,
        "x-fantasy-filter": json.dumps({"players": {"limit": 5000, "offset": 0}}),
    }
    resp = requests.get(url, headers=hdrs, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("unexpected ESPN players payload")
    return data


# --- Fantasy Football Calculator ------------------------------------------
# Public REST API, free for commercial use with attribution, updated daily.
# https://fantasyfootballcalculator.com/api/v1/adp/<format>?teams=12&year=Y
# Rows carry a real name/position/team, so no cross-id map is needed.
_FFC_BASE = "https://fantasyfootballcalculator.com/api/v1/adp"
# board scoring key -> FFC's own format slug.
FFC_FORMAT = {"std": "standard", "half_ppr": "half-ppr",
              "ppr": "ppr", "2qb": "2qb"}


def ffc_adp(season, fmt: str = "ppr", teams: int = 12) -> list[dict]:
    """FFC's ADP `players` list for a season + scoring format.

    `fmt` is a board scoring key ("std"/"half_ppr"/"ppr"/"2qb"); it is mapped
    to FFC's slug here. Raises on a non-2xx / non-Success payload so the
    provider falls back to its snapshot.
    """
    slug = FFC_FORMAT.get(fmt, "ppr")
    url = f"{_FFC_BASE}/{slug}"
    resp = requests.get(url, params={"teams": teams, "year": int(season)},
                        headers={"User-Agent": _UA}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, dict) or data.get("status") != "Success":
        raise ValueError(f"FFC returned {data.get('status')!r} for {season}/{slug}")
    return data.get("players") or []


# --- Yahoo (public read-only mirror) ------------------------------------
# pub-api-ro.fantasysports.yahoo.com serves the same Fantasy API as the
# OAuth host but WITHOUT auth for read-only, non-league resources -- the
# platform-wide `players;out=draft_analysis` collection is one of them. No
# cookies, no key, no UA required (one is sent anyway). It carries
# `preseason_average_pick` (the pre-draft consensus, stable for a past
# season) alongside the live `average_pick`, keyed by Yahoo player id.
_YAHOO_BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
# NFL "game key" per season (Yahoo's own id for that year's game). Resolved
# from /games;game_codes=nfl;seasons=... -- hard-coded through 2026, with a
# live lookup fallback for later years. (Keys exist back to 2018, but Yahoo
# only exposes a usable preseason_average_pick from 2022 on -- see
# ffadp.yahoo.EARLIEST.)
_YAHOO_GAME_KEY = {
    2022: "414", 2023: "423", 2024: "449", 2025: "461", 2026: "470",
}


def _yahoo_game_key(season) -> str:
    """Yahoo's NFL game key for a season. Hard-coded map first; a live
    /games lookup for a year past the map; "nfl" (the current-year alias)
    as the last resort."""
    yr = int(season)
    if yr in _YAHOO_GAME_KEY:
        return _YAHOO_GAME_KEY[yr]
    try:
        url = f"{_YAHOO_BASE}/games;game_codes=nfl;seasons={yr}?format=json_f"
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
        resp.raise_for_status()
        for g in resp.json()["fantasy_content"]["games"]:
            gg = g.get("game") or {}
            if str(gg.get("season")) == str(yr) and gg.get("game_key"):
                return str(gg["game_key"])
    except Exception:
        pass
    return "nfl"


def yahoo_adp(season, scoring: str = "ppr", page: int = 100) -> list[dict]:
    """Yahoo draft-analysis rows for a season (flattened `player` dicts).

    Pages the platform-wide players collection (sort=AR = by average draft
    result) until a short page or a page with no usable pick. `scoring` is
    accepted for signature parity but Yahoo publishes one ADP. Raises on a
    non-2xx / non-JSON payload so the provider falls back to its snapshot.
    """
    key = _yahoo_game_key(season)
    out: list[dict] = []
    start = 0
    while True:
        url = (f"{_YAHOO_BASE}/game/{key}/players;position=ALL;sort=AR;"
               f"start={start};count={page};out=draft_analysis?format=json_f")
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        players = (data.get("fantasy_content", {}).get("game", {})
                   .get("players") or [])
        if not isinstance(players, list) or not players:
            break
        rows = [p.get("player") or {} for p in players]
        out.extend(rows)
        # Stop once the preseason pick values run into the "undrafted" tail.
        def _pick(r):
            try:
                return float((r.get("draft_analysis") or {})
                             .get("preseason_average_pick"))
            except (TypeError, ValueError):
                return None
        if len(players) < page or not any(
                (v := _pick(r)) is not None and v < 999 for r in rows[-10:]):
            break
        start += len(players)
        if start >= 600:            # hard cap; a full board is ~250 rows
            break
    return out


# --- CBS Sports draft averages ----------------------------------------------
# The public draft-averages page is server-rendered HTML (a "TableBase"
# table), no auth, no league id. One current-season ADP list -- CBS ignores
# every scoring / season query param, so there is no format split and no
# history. The value is a real averaged draft position (e.g. "1.12").
_CBS_URL = "https://www.cbssports.com/fantasy/football/draft/averages/"


def cbs_adp() -> str:
    """The raw CBS draft-averages HTML for the current season. Raises on a
    non-2xx so the provider falls back to its snapshot."""
    resp = requests.get(_CBS_URL, headers={"User-Agent": _UA}, timeout=30)
    resp.raise_for_status()
    return resp.text


def rotowire_adp(scoring: str = "PPR") -> list[dict]:
    """RotoWire's ADP comparison table for the CURRENT season (one JSON list).

    `scoring` is RotoWire's own slug -- "PPR" or "Standard"; anything else
    falls back to "PPR". Each row carries several sites' ADP in its own
    column plus RotoWire's `average` consensus, keyed by first/last name +
    team + pos. There is no year parameter -- the endpoint always returns
    the live draft-season table. Raises on a non-2xx / non-list payload so a
    provider can fall back to its snapshot.
    """
    slug = "Standard" if str(scoring).lower() in ("standard", "std") else "PPR"
    url = "https://www.rotowire.com/football/tables/adp.php"
    resp = requests.get(url, params={"pos": "ALL", "scoring": slug},
                        headers={"User-Agent": _UA}, timeout=45)
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("unexpected RotoWire adp payload")
    return data
