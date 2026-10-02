"""Server-side cache of rendered charts and tab sections, plus a silent warm-up.

Why: a chart is redrawn and a section recomputed on EVERY request, and charts
draw one at a time under a lock (matplotlib is not thread-safe), so on a slow
host the overview's four charts arrive about 11 seconds apart.  The only
caching was the browser's two-minute `max-age`.

How it works, with no sizes or timeouts to tune:

* **Scope.**  A rendered asset is stored on the league's cached entry (`d`, the
  dict `league_data()` returns), under `d["_assets"]`.  It therefore lives
  exactly as long as that data does: when the league is re-assembled (the
  15 minute refresh, or `?refresh=1`) the old `d` is replaced and every asset
  built from it goes with it.  League-free assets (player charts) have no `d`;
  they use a small module store with the same TTL the profile cache uses.
* **Validation.**  Responses carry an `ETag` derived from the request key and
  the data version, so a browser revalidates cheaply (a 304, no redraw) instead
  of guessing a `max-age`.
* **Warm-up.**  After someone opens a tab, a daemon thread requests that tab's
  charts and lazy sections (then the other tabs') over loopback, so the cache
  fills while they read.  It is polite: it waits while any real request is in
  flight, stops when the data it is warming has been replaced, and stops before
  the process would pass the container's own memory limit (read from the
  cgroup, using the largest growth it has seen for one asset).
"""
from __future__ import annotations

import contextvars
import hashlib
import os
import re
import threading
import time
from collections import deque
from html import unescape

import requests
from fastapi.responses import Response

from repo_paths import prune_cache

#: The If-None-Match header of the request being handled (set by the app's
#: middleware; sync endpoints run in a copy of the context, so they see it).
if_none_match: contextvars.ContextVar = contextvars.ContextVar("if_none_match", default=None)

#: Revalidate on every use.  The 304 path is cheap, so there is no guessed age.
CACHE_CONTROL = "private, max-age=0, must-revalidate"

_player_store: dict = {}      # league-free assets: key -> entry
_NOT_STORED = ("content-length", "content-type")
_VALIDATOR_HEADERS = ("etag", "cache-control")   # re-derived on every response


# --- what is happening right now ----------------------------------------------

_lock = threading.Lock()
_active = 0
_idle = threading.Event()
_idle.set()


def request_started() -> None:
    global _active
    with _lock:
        _active += 1
        _idle.clear()


def request_finished() -> None:
    global _active
    with _lock:
        _active = max(0, _active - 1)
        if _active == 0:
            _idle.set()


def active_requests() -> int:
    return _active


# --- keys, validators, storage ------------------------------------------------

def make_key(*parts) -> tuple:
    return tuple(parts)


def etag_for(key: tuple, version) -> str:
    return '"' + hashlib.sha1(repr((key, version)).encode()).hexdigest()[:20] + '"'


def store_for(d: dict | None) -> dict:
    """Where assets built from `d` live: on `d` itself, so they die with it."""
    return d.setdefault("_assets", {}) if d is not None else _player_store


def _matches(header: str | None, etag: str) -> bool:
    if not header:
        return False
    return header.strip() == "*" or etag in [p.strip() for p in header.split(",")]


def cacheable(resp) -> bool:
    return isinstance(resp, Response) and resp.status_code == 200


_inflight: dict = {}          # (store id, key) -> Event, for assets being built right now
_inflight_lock = threading.Lock()


def cached_response(store: dict, key: tuple, version, make, *, ttl: float | None = None,
                    inm: str | None = None, validate: bool = True,
                    _coalesce: bool = True) -> Response:
    """Serve `key` from `store`, or build it with `make()` and keep it.

    `version` ties an entry to the data it was built from (a changed version is
    a miss).  `ttl` bounds an entry that has no data version of its own (the
    league-free store).  With `validate`, a matching `If-None-Match` answers 304
    without touching the store at all, which is what makes a revisit free.

    Concurrent requests for the same missing asset share ONE build: the first
    renders it, the others wait and then take the stored result.  Without that a
    visitor and the warm-up asking for the same chart at the same moment would
    each draw it, doubling the work on a host where a chart takes seconds.
    The `X-Cache` header says which path answered: hit, miss, shared or 304.
    """
    entry = store.get(key)
    if entry is not None:
        stale = (entry["ver"] != version) if ttl is None else (time.time() - entry["at"] >= ttl)
        if stale:
            entry = None
    ver = version if ttl is None else (entry["at"] if entry else None)
    if validate and ver is not None:
        etag = etag_for(key, ver)
        if _matches(inm, etag):
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL,
                                                      "X-Cache": "304"})
    if entry is not None:
        headers = dict(entry["headers"])
        headers["X-Cache"] = "hit"
        if validate:
            headers.update({"ETag": etag_for(key, ver), "Cache-Control": CACHE_CONTROL})
        return Response(entry["body"], media_type=entry["media_type"], headers=headers)

    token = (id(store), key)
    mine = True
    if _coalesce:
        with _inflight_lock:
            event = _inflight.get(token)
            mine = event is None
            if mine:
                _inflight[token] = event = threading.Event()
        if not mine:
            event.wait()                    # someone else is drawing it; take their result
            resp = cached_response(store, key, version, make, ttl=ttl, inm=inm,
                                   validate=validate, _coalesce=False)
            if resp.headers.get("x-cache") == "hit":
                resp.headers["X-Cache"] = "shared"
            return resp

    try:
        resp = make()
        if cacheable(resp):
            now = time.time()
            drop = _NOT_STORED + (_VALIDATOR_HEADERS if validate else ())
            keep = {k: v for k, v in resp.headers.items() if k.lower() not in drop}
            store[key] = {"body": resp.body, "media_type": resp.media_type, "headers": keep,
                          "ver": version, "at": now}
            if ttl is not None:
                prune_cache(store, ttl)
                ver = now
            if validate and ver is not None:
                resp.headers["ETag"] = etag_for(key, ver)
                resp.headers["Cache-Control"] = CACHE_CONTROL
        resp.headers["X-Cache"] = "miss"
        return resp
    finally:
        if _coalesce:
            with _inflight_lock:
                _inflight.pop(token, None)
            event.set()


# --- warm-up --------------------------------------------------------------------

enabled = False       # turned on by the app's lifespan, so direct handler calls
                      # (tests, scripts) never start loopback requests


_CHART_SRC = re.compile(r'src="(/chart/[^"]+)"')
_PART_GET = re.compile(r'hx-get="(/tab/[^"]*/part/[^"]+)"')


def extract_urls(html: str) -> list[str]:
    """The chart images and lazy sections a rendered tab asks for next.  Live
    weeks and refreshes are skipped: they are never cached."""
    out, seen = [], set()
    for rx in (_CHART_SRC, _PART_GET):
        for raw in rx.findall(html):
            u = unescape(raw)
            if "week=live" in u or "refresh=1" in u or u in seen:
                continue
            seen.add(u)
            out.append(u)
    return out


def rss_bytes() -> int | None:
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return None


def memory_limit_bytes() -> int | None:
    """The container's own memory cap (cgroup v2, then v1); None when unlimited
    or not on Linux."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw = open(path, encoding="ascii").read().strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 50:      # v1 reports a huge number for "no limit"
            return int(raw)
    return None


class _Stop(Exception):
    pass


def warm_async(d: dict, league: str, season: str, first_tab: str, theme: str,
               tabs: list[str], current_d) -> bool:
    """Start the warm-up for this data once.  `current_d()` returns the league's
    live cache entry, so the worker can tell when `d` has been replaced.  The
    marker lives on `d`, so a refreshed league is warmed again on its next visit."""
    if not enabled or os.environ.get("DISABLE_ASSET_WARM") == "1":
        return False
    with _lock:
        if d.get("_warming"):
            return False
        d["_warming"] = True
    threading.Thread(target=_warm, name=f"warm-assets-{league}-{season}", daemon=True,
                     args=(d, league, season, first_tab, theme, tabs, current_d)).start()
    return True


def _warm(d, league, season, first_tab, theme, tabs, current_d, fetch=None) -> int:
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"
    worst = 0                       # largest growth in resident memory for one asset
    done = 0

    def default_fetch(url):
        return requests.get(base + url, headers={"X-Warm": "1"}, timeout=None)
    do_fetch = fetch or default_fetch

    def get(url):
        nonlocal worst, done
        _idle.wait()                                   # never compete with a visitor
        if current_d() is not d:                       # the data was replaced
            raise _Stop
        before, limit = rss_bytes(), memory_limit_bytes()
        if before is not None and limit is not None and before + worst >= limit:
            raise _Stop                                # the next one might not fit
        resp = do_fetch(url)
        after = rss_bytes()
        if before is not None and after is not None:
            worst = max(worst, after - before)
        done += 1
        return resp

    order = [first_tab] + [t for t in tabs if t != first_tab]
    seen: set[str] = set()
    try:
        for t in order:
            panel = get(f"/tab/{t}?league={league}&season={season}&theme={theme}")
            queue = deque(extract_urls(panel.text))
            while queue:
                u = queue.popleft()
                if u in seen:
                    continue
                seen.add(u)
                resp = get(u)
                if "text/html" in resp.headers.get("content-type", ""):
                    queue.extend(x for x in extract_urls(resp.text) if x not in seen)
    except _Stop:
        pass
    except Exception:
        pass                                           # best effort, never loud
    return done
