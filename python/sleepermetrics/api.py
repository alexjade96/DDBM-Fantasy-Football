"""Low-level Sleeper API access (mirrors R api.R)."""
from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_BASE = "https://api.sleeper.app/v1"
_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(
            total=4, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT", "POST"],
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


def sleeper_api(path: str):
    """GET the public Sleeper v1 API with timeout + retry; return parsed JSON."""
    resp = _get_session().get(f"{_BASE}{path}", timeout=30)
    resp.raise_for_status()
    return resp.json()
