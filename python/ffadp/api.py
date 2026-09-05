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


# --- MyFantasyLeague ------------------------------------------------------
# Public developer API, no auth for season-wide reports. The ADP report keys
# players by MFL id only, so mfl_players() supplies the id -> name/pos/team map.
_MFL_BASE = "https://api.myfantasyleague.com"


def mfl_adp(season, is_ppr: int = 1, fcount: int = 12) -> list[dict]:
    """MFL's aggregate ADP rows for a season (list of {id, rank, averagePick,
    minPick, maxPick, draftsSelectedIn, draftSelPct}). Raises on a bad payload.

    The PPR / league-size filters only bite from ~2019 on; for older seasons
    MFL returns 0 drafts for a filtered request, so this falls back to the
    unfiltered (format-agnostic) aggregate rather than coming back empty.
    """
    url = f"{_MFL_BASE}/{int(season)}/export"

    def _pull(params):
        resp = requests.get(url, params=params,
                            headers={"User-Agent": _UA}, timeout=30)
        resp.raise_for_status()
        return (resp.json() or {}).get("adp") or {}

    adp = _pull({"TYPE": "adp", "PERIOD": "DRAFT", "FCOUNT": fcount,
                 "IS_PPR": is_ppr, "IS_KEEPER": "N", "IS_MOCK": 0, "JSON": 1})
    rows = adp.get("player")
    if not rows:
        adp = _pull({"TYPE": "adp", "JSON": 1})
        rows = adp.get("player")
    if not isinstance(rows, list):
        raise ValueError(f"unexpected MFL adp payload for {season}")
    return rows


def mfl_players(season) -> dict[str, dict]:
    """MFL id -> {name, position, team} for a season. Names come back
    "Last, First"; kept verbatim here and flipped by the provider."""
    url = f"{_MFL_BASE}/{int(season)}/export"
    resp = requests.get(url, params={"TYPE": "players", "JSON": 1},
                        headers={"User-Agent": _UA}, timeout=45)
    resp.raise_for_status()
    pl = ((resp.json() or {}).get("players") or {}).get("player") or []
    out: dict[str, dict] = {}
    for p in pl:
        pid = str(p.get("id") or "")
        if pid:
            out[pid] = {"name": p.get("name") or "", "position": p.get("position"),
                        "team": p.get("team")}
    return out
