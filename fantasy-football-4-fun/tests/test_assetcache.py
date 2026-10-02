"""The rendered-asset cache and its silent warm-up (webapp/assetcache.py).

Network-free: the warm-up's fetch is replaced with a fake, and the stores are
plain dicts.  See the module docstring for what each rule is for.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi.responses import HTMLResponse, Response

from webapp import assetcache as ac


def _png(body=b"\x89PNG-data"):
    return Response(body, media_type="image/png",
                    headers={"Cache-Control": "private, max-age=120"})


def test_miss_builds_once_then_hits():
    store, calls = {}, []
    make = lambda: calls.append(1) or _png()
    key = ac.make_key("chart", "standings", "light")
    a = ac.cached_response(store, key, "v1", make)
    b = ac.cached_response(store, key, "v1", make)
    assert len(calls) == 1
    assert a.body == b.body and b.media_type == "image/png"


def test_a_new_data_version_is_a_miss():
    store, calls = {}, []
    make = lambda: calls.append(1) or _png()
    key = ac.make_key("chart", "x")
    ac.cached_response(store, key, "v1", make)
    ac.cached_response(store, key, "v2", make)
    assert len(calls) == 2


def test_responses_carry_a_validator_and_exactly_one_cache_control():
    store = {}
    key = ac.make_key("chart", "x")
    first = ac.cached_response(store, key, "v1", _png)
    again = ac.cached_response(store, key, "v1", _png)
    for r in (first, again):
        assert r.headers["etag"].startswith('"')
        assert r.headers.getlist("cache-control") == [ac.CACHE_CONTROL]
    assert first.headers["etag"] == again.headers["etag"]


def test_matching_if_none_match_answers_304_without_building():
    store, calls = {}, []
    key = ac.make_key("chart", "x")
    etag = ac.etag_for(key, "v1")
    resp = ac.cached_response(store, key, "v1", lambda: calls.append(1) or _png(), inm=etag)
    assert resp.status_code == 304 and not calls and resp.body == b""


def test_a_stale_validator_gets_the_full_response():
    store = {}
    key = ac.make_key("chart", "x")
    stale = ac.etag_for(key, "old-version")
    resp = ac.cached_response(store, key, "v2", _png, inm=stale)
    assert resp.status_code == 200 and resp.body


def test_the_etag_depends_on_the_data_version_and_the_key():
    k1, k2 = ac.make_key("chart", "a"), ac.make_key("chart", "b")
    assert ac.etag_for(k1, "v1") != ac.etag_for(k1, "v2")
    assert ac.etag_for(k1, "v1") != ac.etag_for(k2, "v1")


def test_errors_and_missing_assets_are_not_kept():
    store, calls = {}, []
    key = ac.make_key("chart", "gone")
    make = lambda: calls.append(1) or Response(status_code=404)
    ac.cached_response(store, key, "v1", make)
    ac.cached_response(store, key, "v1", make)
    assert len(calls) == 2 and store == {}


def test_sections_are_cached_without_validators():
    store, calls = {}, []
    make = lambda: calls.append(1) or HTMLResponse("<p>scoreboard</p>")
    key = ac.make_key("part", "overview", "scoreboard")
    a = ac.cached_response(store, key, "v1", make, validate=False)
    b = ac.cached_response(store, key, "v1", make, validate=False)
    assert len(calls) == 1 and b.body == a.body
    assert "etag" not in b.headers


def test_a_ttl_entry_expires_and_is_rebuilt():
    store, calls = {}, []
    make = lambda: calls.append(1) or _png()
    key = ac.make_key("chart", "player")
    ac.cached_response(store, key, None, make, ttl=60)
    assert len(calls) == 1
    store[key]["at"] -= 61                              # age it past the ttl
    ac.cached_response(store, key, None, make, ttl=60)
    assert len(calls) == 2


def test_the_store_lives_on_the_league_entry_so_it_dies_with_it():
    d1, d2 = {"at": 1}, {"at": 2}
    ac.store_for(d1)["k"] = 1
    assert "k" not in ac.store_for(d2)
    assert ac.store_for(d1) is d1["_assets"]
    assert ac.store_for(None) is ac._player_store


# --- finding what to warm -----------------------------------------------------------

def test_extract_urls_finds_charts_and_sections_and_unescapes():
    html = ('<img src="/chart/standings?league=1&amp;season=2026&amp;theme=light">'
            '<div hx-get="/tab/overview/part/config?league=1&amp;season=2026"></div>')
    assert ac.extract_urls(html) == [
        "/chart/standings?league=1&season=2026&theme=light",
        "/tab/overview/part/config?league=1&season=2026"]


def test_extract_urls_skips_live_weeks_and_refreshes_and_repeats():
    html = ('<div hx-get="/tab/overview/part/scoreboard?week=live"></div>'
            '<div hx-get="/tab/overview?refresh=1"></div>'
            '<img src="/chart/a?x=1"><img src="/chart/a?x=1">')
    assert ac.extract_urls(html) == ["/chart/a?x=1"]


# --- the warm-up ---------------------------------------------------------------------

class _Resp:
    def __init__(self, text="", ctype="text/html"):
        self.text, self.headers = text, {"content-type": ctype}


def _site():
    """A fake site: each tab links to one chart and one section; the section links
    to a second chart."""
    def fetch(url):
        fetch.log.append(url)
        if url.startswith("/tab/") and "/part/" not in url:
            name = url.split("/")[2].split("?")[0]
            return _Resp(f'<img src="/chart/{name}?a=1"><div hx-get="/tab/{name}/part/p"></div>')
        if "/part/" in url:
            name = url.split("/")[2]
            return _Resp(f'<img src="/chart/{name}-inner?a=1">')
        return _Resp("", "image/png")
    fetch.log = []
    return fetch


def test_warm_starts_with_the_entry_tab_then_the_others():
    d, fetch = {}, _site()
    n = ac._warm(d, "L", "2026", "roster", "light", ["overview", "roster", "draft"],
                 lambda: d, fetch=fetch)
    panels = [u.split("?")[0] for u in fetch.log if "/part/" not in u and u.startswith("/tab/")]
    assert panels == ["/tab/roster", "/tab/overview", "/tab/draft"]
    assert n == len(fetch.log) == 3 * 4                  # per tab: panel, chart, section, inner chart


def test_warm_follows_a_section_into_its_own_charts():
    d, fetch = {}, _site()
    ac._warm(d, "L", "2026", "overview", "light", ["overview"], lambda: d, fetch=fetch)
    assert any("overview-inner" in u for u in fetch.log)


def test_warm_stops_as_soon_as_the_data_is_replaced():
    d, fetch = {}, _site()
    current = {"d": d}
    inner = fetch
    def swapping(url):
        r = inner(url)
        if len(inner.log) == 2:
            current["d"] = {}                            # league re-assembled
        return r
    n = ac._warm(d, "L", "2026", "overview", "light", ["overview", "draft"],
                 lambda: current["d"], fetch=swapping)
    assert n == 2


def test_warm_waits_while_a_visitor_is_mid_request():
    d, fetch = {}, _site()
    ac.request_started()
    t = threading.Thread(target=ac._warm,
                         args=(d, "L", "2026", "overview", "light", ["overview"], lambda: d),
                         kwargs={"fetch": fetch})
    try:
        t.start()
        time.sleep(0.3)
        assert fetch.log == []                           # held back by the visitor
    finally:
        ac.request_finished()
    t.join(timeout=10)
    assert fetch.log and not t.is_alive()


def test_warm_stops_before_it_could_pass_the_memory_limit(monkeypatch):
    d, fetch = {}, _site()
    monkeypatch.setattr(ac, "memory_limit_bytes", lambda: 1000)
    sizes = iter([100, 600, 600, 900, 900, 995, 995, 995, 995, 995, 995, 995])
    monkeypatch.setattr(ac, "rss_bytes", lambda: next(sizes))
    n = ac._warm(d, "L", "2026", "overview", "light", ["overview", "draft"],
                 lambda: d, fetch=fetch)
    assert 0 < n < 8                                     # started, then declined to go on


def test_warm_is_off_unless_the_server_enabled_it(monkeypatch):
    monkeypatch.setattr(ac, "enabled", False)
    assert ac.warm_async({}, "L", "2026", "overview", "light", ["overview"], lambda: None) is False


def test_warm_runs_once_per_league_entry(monkeypatch):
    monkeypatch.setattr(ac, "enabled", True)
    monkeypatch.delenv("DISABLE_ASSET_WARM", raising=False)
    started = []
    monkeypatch.setattr(ac.threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: started.append(1)})())
    d = {}
    assert ac.warm_async(d, "L", "2026", "overview", "light", ["overview"], lambda: d) is True
    assert ac.warm_async(d, "L", "2026", "overview", "light", ["overview"], lambda: d) is False
    assert ac.warm_async({}, "L", "2026", "overview", "light", ["overview"], lambda: d) is True
    assert len(started) == 2


def test_memory_helpers_degrade_to_none_off_linux(monkeypatch):
    import builtins
    real_open = builtins.open
    def deny(path, *a, **k):
        if str(path).startswith(("/proc", "/sys")):
            raise OSError
        return real_open(path, *a, **k)
    monkeypatch.setattr(builtins, "open", deny)
    assert ac.rss_bytes() is None and ac.memory_limit_bytes() is None


# --- the app wiring -------------------------------------------------------------------

def test_the_chart_route_keeps_its_signature_and_does_not_shadow_sm():
    """Naming a local `sm` inside chart() shadowed the sleepermetrics module for the whole
    function and made every playoff bracket chart raise UnboundLocalError."""
    import inspect
    from webapp import app
    params = inspect.signature(app.chart).parameters
    assert {"name", "league", "season", "theme", "player_ids", "stat_mode"} <= set(params)
    assert "sm" not in app.chart.__wrapped__.__code__.co_varnames
