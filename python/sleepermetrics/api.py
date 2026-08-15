"""Low-level Sleeper API access (mirrors R api.R)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_BASE = "https://api.sleeper.app/v1"
# Undocumented -- a different host and shape from the documented v1 API
# above, reverse-engineered from Sleeper's own draft-lobby client (see
# draft.py's ADP functions for how this is consumed/cached). Kept separate
# from `_BASE`/`sleeper_api` rather than folded in, since it isn't the
# documented API and callers need to treat it as best-effort, not assume it
# behaves (or keeps working) the same way.
_ADP_BASE = "https://api.sleeper.com"
_session: requests.Session | None = None
# Shared by sleeper_api_many() -- a season's worth of per-week matchup/
# transaction calls are independent of each other, so fetching them
# concurrently instead of one at a time is what keeps season assembly from
# blocking a request for tens of seconds. Bounded (not per-call) so nested
# callers (e.g. a per-season batch inside a multi-season chain) can't pile up
# unbounded concurrent connections.
_MAX_WORKERS = 10
_executor: ThreadPoolExecutor | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(
            total=4, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT", "POST"],
        )
        # pool_maxsize matches _MAX_WORKERS so concurrent requests each get a
        # pooled connection instead of contending/discarding past urllib3's
        # default pool size of 10.
        adapter = HTTPAdapter(max_retries=retry, pool_maxsize=_MAX_WORKERS)
        s.mount("https://", adapter)
        _session = s
    return _session


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=_MAX_WORKERS)
    return _executor


def sleeper_api(path: str):
    """GET the public Sleeper v1 API with timeout + retry; return parsed JSON."""
    resp = _get_session().get(f"{_BASE}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()


def sleeper_adp(season) -> list:
    """GET Sleeper's undocumented per-season ADP/projections endpoint --
    the same data its own draft lobby reads from. One row per player, each
    carrying `stats.adp_std`/`adp_half_ppr`/`adp_ppr`/`adp_2qb` (a sentinel
    999.0, not null, means "no real ADP in this format") alongside
    `player.position`/`first_name`/`last_name`. Raises on any HTTP failure --
    same as `sleeper_api` -- so the caller (draft.py) decides how to degrade,
    not this function.
    """
    params = [
        ("season_type", "regular"),
        ("position[]", "QB"), ("position[]", "RB"), ("position[]", "WR"),
        ("position[]", "TE"), ("position[]", "K"), ("position[]", "DEF"),
        ("order_by", "adp_ppr"),
    ]
    resp = _get_session().get(f"{_ADP_BASE}/projections/nfl/{season}",
                              params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def sleeper_api_many(paths: list[str]) -> list:
    """GET several Sleeper API paths concurrently; returns results in the same
    order as `paths` (not completion order), so callers can zip them back
    against whatever the paths were keyed by (e.g. week number) exactly as if
    each had been fetched sequentially. requests.Session is shared safely
    across threads for independent GETs like these -- each request gets its
    own pooled connection from the HTTPAdapter.
    """
    return list(_get_executor().map(sleeper_api, paths))
