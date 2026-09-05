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
