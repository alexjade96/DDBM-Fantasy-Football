"""Measures the outbound HTTP calls a piece of code makes.

Why: several functions pull data ad hoc instead of filtering data already
stored (see docs/data-loading-refactor-plan.md).  To judge a refactor step
you need numbers: how many calls, how many bytes, how long, and how often
the same URL was fetched twice.

Use:

    from webapp import loadmeter
    with loadmeter.session("cold player profile") as m:
        player_profile.player_profile("4034")
    print(m.report())

Off unless a session is open: nothing is patched at import time, and the
patch is removed when the last session closes.  It hooks
`requests.Session.send`, the one place every HTTP call in this codebase
passes through (the Sleeper session, nflverse downloads and each ADP
provider), so no loader needs editing.

What is recorded, per call: time, method, host, path, status, bytes, seconds
and the nearest calling function in this repo.  Never recorded: the query
string, headers, cookies or the body.  Query strings are dropped because
some endpoints could carry keys there.

What is recorded about WHERE a call went (an allow list, so it fails closed):

* `api.sleeper.app` calls are recorded only as a fixed template from
  `_SLEEPER_TEMPLATES` (`/v1/league/{league}/matchups/{week}`); the league,
  user and draft ids in the real path are never copied.  A Sleeper path that
  matches no template is recorded as `(unrecognised)`.
* A host in `_PUBLIC_HOSTS` (nflverse, ESPN, Yahoo, CBS, FFC, RotoWire, Sleeper's
  ADP and player images) records its path as is, but only when it matches that
  host's pattern; these URLs name public NFL data only.
* Any other host records the host alone.
* No call keeps its real path.  Repeats are counted from a one-way
  fingerprint, so a report, the recent ring and a saved file cannot carry a
  league or user id.  Adding a Sleeper endpoint means adding a template.

Two ways to collect:

* `session(label)`: records every call from every thread while it is open.
  For scripts and tests.
* `request(label)`: records only the calls caused by ONE request, through a
  context variable that is copied into `ThreadPoolExecutor` workers (so
  `sleeper_api_many` is attributed correctly).  Calls with no request context
  (the refresher, the cache warm-up's own threads) are counted separately as
  background.  `webapp.app` wraps each real request in this when `enabled()`;
  finished requests are kept in a bounded ring (`recent()`), served locally at
  `/loadmeter`, and summarised in `X-Load-*` response headers.

`enabled()` is True for local development and False on Render (nothing to
read the data with there, and no wish to expose it); `LOADMETER=1` or `0`
overrides either way.

Limits: only NETWORK calls are counted.  A hit on a memory or disk cache
makes no request, so it does not show up here (that is the point: a warm
path should show zero calls).  A redirect chain counts as one call (the original URL, the final size, the
total time).  A call made on a worker thread (for example
`sleeper_api_many`) is attributed to the API helper, not to the code that
asked for it.  Bytes for a streamed response come from Content-Length when
the server sent one, else 0.
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import re
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import requests

_LOCK = threading.Lock()
_OPEN: list["Meter"] = []
_ORIGINAL_SEND = None
_ORIGINAL_SUBMIT = None
_PERMANENT = False          # set by ensure_installed(); sessions never undo it
_DEPTH = threading.local()
_CTX: contextvars.ContextVar = contextvars.ContextVar("loadmeter_request", default=None)

RECENT_MAX = 200
_RECENT: deque = deque(maxlen=RECENT_MAX)     # summaries of finished requests
_BACKGROUND = {"calls": 0, "bytes": 0}        # calls made outside any request

# Frames from these modules are plumbing, not the code that wanted the data.
_SKIP_PARTS = ("/site-packages/", "/requests/", "/urllib3/", "/concurrent/",
               "/threading.py")
_SELF = Path(__file__).resolve().as_posix()
_REPO = Path(__file__).resolve().parents[2]


# -- what a call may be reported as ---------------------------------------

_SLEEPER_TEMPLATES = [
    (re.compile(r"/v1/league/[0-9]+"), "/v1/league/{league}"),
    (re.compile(r"/v1/league/[0-9]+/rosters"), "/v1/league/{league}/rosters"),
    (re.compile(r"/v1/league/[0-9]+/users"), "/v1/league/{league}/users"),
    (re.compile(r"/v1/league/[0-9]+/winners_bracket"), "/v1/league/{league}/winners_bracket"),
    (re.compile(r"/v1/league/[0-9]+/losers_bracket"), "/v1/league/{league}/losers_bracket"),
    (re.compile(r"/v1/league/[0-9]+/drafts"), "/v1/league/{league}/drafts"),
    (re.compile(r"/v1/league/[0-9]+/matchups/[0-9]+"), "/v1/league/{league}/matchups/{week}"),
    (re.compile(r"/v1/league/[0-9]+/transactions/[0-9]+"), "/v1/league/{league}/transactions/{week}"),
    (re.compile(r"/v1/draft/[0-9]+/picks"), "/v1/draft/{draft}/picks"),
    (re.compile(r"/v1/user/[^/]+"), "/v1/user/{user}"),
    (re.compile(r"/v1/user/[^/]+/leagues/[a-z]+/[0-9]{4}"), "/v1/user/{user}/leagues/{sport}/{season}"),
    (re.compile(r"/v1/state/nfl"), "/v1/state/nfl"),
    (re.compile(r"/v1/players/nfl"), "/v1/players/nfl"),
    (re.compile(r"/v1/stats/nfl/regular/[0-9]{4}/[0-9]+"), "/v1/stats/nfl/regular/{season}/{week}"),
]

# host -> pattern of the paths that may be shown as is (public NFL data only).
# None means "any path is fine to show as a fixed label" (see _OPAQUE_HOSTS).
_PUBLIC_HOSTS = {
    "api.sleeper.com": re.compile(r"/projections/nfl/[0-9]{4}"),
    "github.com": re.compile(r"/nflverse/nflverse-data/releases/download/[\w.\-]+/[\w.\-]+"),
    "sleepercdn.com": re.compile(r"/(content/nfl/players/[\w]+\.jpg|images/team_logos/nfl/[\w]+\.png)"),
    "fantasyfootballcalculator.com": re.compile(r"/api/v1/adp/[\w\-]+"),
    "lm-api-reads.fantasy.espn.com": re.compile(r"/apis/v3/games/ffl/seasons/[0-9]{4}/players"),
    "pub-api-ro.fantasysports.yahoo.com": re.compile(r"/fantasy/v2/(game/[0-9]+/players.*|games.*)"),
    "www.cbssports.com": re.compile(r"/fantasy/football/draft/averages/?"),
    "www.rotowire.com": re.compile(r"/football/tables/adp\.php"),
}
# Hosts whose paths are opaque ids; reported as one fixed label.
_OPAQUE_HOSTS = {"release-assets.githubusercontent.com": "(nflverse release asset)"}


def classify(host: str, path: str) -> str:
    """The only description of a call's destination that is ever kept.

    Allow list: a Sleeper path is shown as the template it matches; a path on a
    public NFL-data host is shown as is when it fits that host's pattern;
    anything else is a fixed placeholder.  The input is never echoed unless it
    matched one of the patterns above."""
    host = (host or "").lower()
    if host == "api.sleeper.app":
        for rx, label in _SLEEPER_TEMPLATES:
            if rx.fullmatch(path or ""):
                return label
        return "(unrecognised)"
    if host in _OPAQUE_HOSTS:
        return _OPAQUE_HOSTS[host]
    rx = _PUBLIC_HOSTS.get(host)
    if rx is not None:
        return path if rx.fullmatch(path or "") else "(unrecognised)"
    return "(host not listed)"


def _fingerprint(method: str, host: str, path: str) -> str:
    """One-way tag used only to count repeated URLs."""
    return hashlib.sha1(f"{method} {host}{path}".encode()).hexdigest()[:12]


@dataclass
class Call:
    at: float
    method: str
    host: str
    endpoint: str          # a template or public path from classify(), never the real path
    fingerprint: str       # one-way hash of the real URL, for counting repeats only
    status: int | None
    nbytes: int
    seconds: float
    caller: str


@dataclass
class Meter:
    label: str = ""
    calls: list[Call] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    elapsed: float = 0.0

    # -- summaries -------------------------------------------------------
    def total_bytes(self) -> int:
        return sum(c.nbytes for c in self.calls)

    def total_seconds(self) -> float:
        return sum(c.seconds for c in self.calls)

    def repeats(self) -> int:
        """Calls beyond the first for a URL already fetched in this session."""
        urls = [c.fingerprint for c in self.calls]
        return len(urls) - len(set(urls))

    def by_endpoint(self) -> list[dict]:
        """One row per (caller, host, path-shape): count, bytes, seconds."""
        rows: dict[tuple, dict] = {}
        for c in self.calls:
            key = (c.caller, c.host, c.endpoint)
            r = rows.setdefault(key, {"caller": c.caller, "host": c.host,
                                      "endpoint": c.endpoint, "calls": 0,
                                      "bytes": 0, "seconds": 0.0})
            r["calls"] += 1
            r["bytes"] += c.nbytes
            r["seconds"] += c.seconds
        out = list(rows.values())
        out.sort(key=lambda r: (-r["bytes"], -r["calls"]))
        return out

    def by_host(self) -> list[dict]:
        rows: dict[str, dict] = {}
        for c in self.calls:
            r = rows.setdefault(c.host, {"host": c.host, "calls": 0,
                                         "bytes": 0, "seconds": 0.0})
            r["calls"] += 1
            r["bytes"] += c.nbytes
            r["seconds"] += c.seconds
        return sorted(rows.values(), key=lambda r: -r["bytes"])

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "elapsed_seconds": round(self.elapsed, 3),
            "calls": len(self.calls),
            "repeats": self.repeats(),
            "bytes": self.total_bytes(),
            "network_seconds": round(self.total_seconds(), 3),
            "by_host": self.by_host(),
            "by_endpoint": self.by_endpoint(),
        }

    def summary(self, top: int = 5) -> dict:
        """Compact form for the recent-requests ring."""
        return {
            "label": self.label,
            "started": round(self.started, 3),
            "elapsed_seconds": round(self.elapsed, 3),
            "calls": len(self.calls),
            "repeats": self.repeats(),
            "bytes": self.total_bytes(),
            "network_seconds": round(self.total_seconds(), 3),
            "top": [{k: r[k] for k in ("calls", "bytes", "host", "endpoint", "caller")}
                    for r in self.by_endpoint()[:top]],
        }

    def report(self, top: int = 15) -> str:
        mb = self.total_bytes() / 1e6
        lines = [
            f"{self.label or 'session'}: {len(self.calls)} calls, "
            f"{mb:.2f} MB, {self.total_seconds():.1f}s on the network "
            f"({self.elapsed:.1f}s elapsed), {self.repeats()} repeated URLs",
        ]
        for h in self.by_host():
            lines.append(f"  host {h['host']}: {h['calls']} calls, "
                         f"{h['bytes'] / 1e6:.2f} MB, {h['seconds']:.1f}s")
        if self.calls:
            lines.append("  heaviest endpoints:")
        for r in self.by_endpoint()[:top]:
            lines.append(f"    {r['calls']:>3}x {r['bytes'] / 1e6:>7.2f} MB "
                         f"{r['seconds']:>6.1f}s  {r['host']}{r['endpoint']}  "
                         f"<- {r['caller']}")
        return "\n".join(lines)


def _caller() -> str:
    """The nearest frame that belongs to this repo and is not plumbing."""
    f = sys._getframe(2)
    first_repo = None
    while f is not None:
        fn = f.f_code.co_filename.replace("\\", "/")
        if Path(fn).resolve().as_posix() != _SELF                 and not any(p in fn for p in _SKIP_PARTS):
            try:
                rel = Path(fn).resolve().relative_to(_REPO).as_posix()
            except ValueError:
                rel = None
            if rel:
                label = f"{rel}:{f.f_code.co_name}"
                # The API helpers are the last stop; prefer the code above
                # them when there is any.
                if rel.endswith("/api.py"):
                    first_repo = first_repo or label
                else:
                    return label
        f = f.f_back
    return first_repo or "unknown"


def _record(method: str, url: str, status, nbytes: int, secs: float) -> None:
    parts = urlsplit(url)
    host = parts.hostname or ""
    call = Call(time.time(), method, host, classify(host, parts.path),
                _fingerprint(method, host, parts.path),
                status, nbytes, secs, _caller())
    req = _CTX.get()
    with _LOCK:
        targets = list(_OPEN)
        if req is not None and req not in targets:
            targets.append(req)
        if not targets:
            _BACKGROUND["calls"] += 1
            _BACKGROUND["bytes"] += nbytes
        for m in targets:
            m.calls.append(call)


def _size(resp) -> int:
    try:
        if not getattr(resp, "_content_consumed", False) and \
                getattr(resp, "_content", False) is False:
            return int(resp.headers.get("Content-Length") or 0)
        return len(resp.content)
    except Exception:
        return 0


def _install() -> None:
    global _ORIGINAL_SEND, _ORIGINAL_SUBMIT
    if _ORIGINAL_SEND is not None:
        return
    _ORIGINAL_SEND = requests.Session.send
    _ORIGINAL_SUBMIT = ThreadPoolExecutor.submit

    def submit(self, fn, /, *a, **k):
        # Carry the request context into the worker so its calls are
        # attributed to the request that asked (only when there is one).
        if _CTX.get() is not None:
            ctx = contextvars.copy_context()
            return _ORIGINAL_SUBMIT(self, ctx.run, fn, *a, **k)
        return _ORIGINAL_SUBMIT(self, fn, *a, **k)

    ThreadPoolExecutor.submit = submit

    def send(self, request, **kwargs):
        # A redirect is followed by `send` calling itself once per hop.  Count
        # the whole chain as ONE logical call (final size, total time), or a
        # 20 MB download behind a redirect would be reported twice.
        if getattr(_DEPTH, "n", 0) > 0:
            return _ORIGINAL_SEND(self, request, **kwargs)
        _DEPTH.n = 1
        t0 = time.perf_counter()
        status, nbytes = None, 0
        try:
            resp = _ORIGINAL_SEND(self, request, **kwargs)
            status, nbytes = resp.status_code, _size(resp)
            return resp
        finally:
            _DEPTH.n = 0
            _record(request.method, request.url, status, nbytes,
                    time.perf_counter() - t0)

    requests.Session.send = send


def _uninstall() -> None:
    global _ORIGINAL_SEND, _ORIGINAL_SUBMIT
    if _PERMANENT:
        return
    if _ORIGINAL_SEND is not None:
        requests.Session.send = _ORIGINAL_SEND
        _ORIGINAL_SEND = None
    if _ORIGINAL_SUBMIT is not None:
        ThreadPoolExecutor.submit = _ORIGINAL_SUBMIT
        _ORIGINAL_SUBMIT = None


def active() -> bool:
    return bool(_OPEN)


@contextmanager
def session(label: str = ""):
    """Collect every HTTP call made (on any thread) while the block runs."""
    m = Meter(label=label)
    with _LOCK:
        _OPEN.append(m)
        _install()
    t0 = time.perf_counter()
    try:
        yield m
    finally:
        m.elapsed = time.perf_counter() - t0
        with _LOCK:
            _OPEN.remove(m)
            if not _OPEN:
                _uninstall()


# -- live, per-request measurement ----------------------------------------

def enabled() -> bool:
    """On for local development, off on Render.  `LOADMETER=1` / `0` wins."""
    flag = os.environ.get("LOADMETER", "").strip().lower()
    if flag in ("1", "true", "yes", "on"):
        return True
    if flag in ("0", "false", "no", "off"):
        return False
    from repo_paths import on_render
    return not on_render()


def ensure_installed() -> None:
    """Install the hooks for the life of the process (idempotent).  Called by
    the app on the first request, never at import, so importing the app in a
    test does not patch `requests`."""
    global _PERMANENT
    with _LOCK:
        _PERMANENT = True
        _install()


@contextmanager
def request(label: str = ""):
    """Attribute every call caused by this request (and its worker threads)
    to one meter, and keep a summary of it in the recent ring."""
    m = Meter(label=label)
    token = _CTX.set(m)
    t0 = time.perf_counter()
    try:
        yield m
    finally:
        m.elapsed = time.perf_counter() - t0
        _CTX.reset(token)
        _RECENT.append(m.summary())


def recent(limit: int | None = None) -> dict:
    """Newest first, plus the background (no-request) totals."""
    items = list(_RECENT)[::-1]
    if limit:
        items = items[:limit]
    with _LOCK:
        bg = dict(_BACKGROUND)
    return {"requests": items, "background": bg, "kept": len(_RECENT),
            "capacity": RECENT_MAX}


def clear_recent() -> None:
    _RECENT.clear()
    with _LOCK:
        _BACKGROUND.update(calls=0, bytes=0)
