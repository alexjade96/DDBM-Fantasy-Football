"""Live smoke tests against a deployed copy of the site (for example Render).

These hit a real server over the network, so they are OPT-IN and live outside
`tests/` (the network-free suite that `verify.py` runs).  Nothing here runs
unless a site URL is given:

    pytest tests_live --site-url https://ddbm-fantasy-football.onrender.com
    SITE_URL=https://example.onrender.com pytest tests_live

A free Render instance sleeps when idle and takes a while to wake, and it
answers 502/503 while a deploy swaps instances.  `fetch` therefore retries
those, and every limit below is an environment variable rather than a baked-in
number:

    SITE_TIMEOUT   seconds to wait for one response   (default 300)
    SITE_RETRIES   extra attempts on 502/503/timeout   (default 3)
    SITE_SKIP_SLOW set to 1 to skip the season report

The tests assert status codes and page content, never speed.  A request that
kills the process shows up as a failure here (a 502 that survives the retries,
or a /health that stops answering), which is the signal that matters on a
512MB instance.
"""
from __future__ import annotations

import os
import time

import pytest
import requests


def pytest_addoption(parser):
    parser.addoption("--site-url", action="store", default=None,
                     help="Base URL of the deployed site to test.")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Site:
    """A thin client: base URL, retry on the failures a sleeping or redeploying
    host produces, and a record of every response for diagnostics."""

    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.timeout = _env_int("SITE_TIMEOUT", 300)
        self.retries = _env_int("SITE_RETRIES", 3)
        self.session = requests.Session()

    def fetch(self, path: str, **kw) -> requests.Response:
        url = path if path.startswith("http") else f"{self.base}{path}"
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, **kw)
            except requests.RequestException as exc:      # timeout, reset
                last = exc
            else:
                if resp.status_code not in (502, 503):
                    return resp
                last = RuntimeError(f"{resp.status_code} from {url}")
            if attempt < self.retries:
                time.sleep(2 ** attempt)                  # 1s, 2s, 4s ...
        raise AssertionError(f"{url} never answered cleanly: {last}")

    def healthy(self) -> bool:
        try:
            return self.session.get(f"{self.base}/health",
                                    timeout=self.timeout).status_code == 200
        except requests.RequestException:
            return False


@pytest.fixture(scope="session")
def site(request) -> Site:
    base = request.config.getoption("--site-url") or os.environ.get("SITE_URL")
    if not base:
        pytest.skip("live site tests are opt-in: pass --site-url or set SITE_URL")
    s = Site(base)
    # Wake a sleeping instance once, up front, so the first real test is not
    # the one that pays for it.
    assert s.fetch("/health").status_code == 200, "site did not wake"
    return s
