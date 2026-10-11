"""webapp/loadmeter.py: counts outbound HTTP calls inside a session.

Network-free: the HTTP transport is replaced, so no socket is opened.  The
meter hooks Session.send, which still runs for real.
"""
from __future__ import annotations

import threading

import pytest
import requests

from webapp import loadmeter


@pytest.fixture(autouse=True)
def base(monkeypatch):
    """Replace the transport so no socket is ever opened (the suite blocks
    them).  Session.send still runs for real, which is what the meter hooks."""
    def fake_send(self, request, **kwargs):
        if request.url.endswith("/redir"):
            resp = requests.Response()
            resp.status_code = 302
            resp._content = b""
            resp.headers["Location"] = "http://cdn.example.test/file"
            resp.url = request.url
            resp.request = request
            return resp
        if "unreachable" in request.url:
            raise requests.exceptions.ConnectionError("down")
        resp = requests.Response()
        resp.status_code = 200
        resp._content = b"x" * 1000
        resp.url = request.url
        resp.request = request
        return resp
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", fake_send)
    return "http://fantasyfootballcalculator.com/api/v1/adp"


def _fetch_a(url):
    return requests.get(url)


def test_counts_calls_and_bytes(base):
    with loadmeter.session("t") as m:
        _fetch_a(base + "/a")
        _fetch_a(base + "/b")
    assert len(m.calls) == 2
    assert m.total_bytes() == 2000
    assert m.repeats() == 0
    assert all(c.status == 200 for c in m.calls)


def test_repeated_url_is_counted_as_a_repeat(base):
    with loadmeter.session() as m:
        for _ in range(3):
            _fetch_a(base + "/same")
    assert len(m.calls) == 3 and m.repeats() == 2
    rows = m.by_endpoint()
    assert len(rows) == 1 and rows[0]["calls"] == 3 and rows[0]["bytes"] == 3000


def test_query_string_is_never_recorded(base):
    with loadmeter.session() as m:
        requests.get(base + "/p", params={"key": "SECRET123"})
    dumped = repr(m.to_dict()) + m.report() + repr(m.calls)
    assert "SECRET123" not in dumped and "key=" not in dumped
    assert m.calls[0].endpoint == "/api/v1/adp/p"


def test_nothing_recorded_or_patched_outside_a_session(base):
    original = requests.Session.send
    with loadmeter.session():
        assert requests.Session.send is not original
    assert requests.Session.send is original
    assert not loadmeter.active()
    requests.get(base + "/after")      # must not raise or record anywhere


def test_nested_sessions_each_see_the_calls(base):
    with loadmeter.session("outer") as outer:
        _fetch_a(base + "/1")
        with loadmeter.session("inner") as inner:
            _fetch_a(base + "/2")
        _fetch_a(base + "/3")
    assert len(outer.calls) == 3 and len(inner.calls) == 1
    assert requests.Session.send.__module__ != "webapp.loadmeter"


def test_calls_from_worker_threads_are_counted(base):
    with loadmeter.session() as m:
        ts = [threading.Thread(target=_fetch_a, args=(base + f"/t{i}",))
              for i in range(4)]
        [t.start() for t in ts]
        [t.join() for t in ts]
    assert len(m.calls) == 4


def test_caller_is_the_nearest_repo_function(base):
    with loadmeter.session() as m:
        _fetch_a(base + "/who")
    assert m.calls[0].caller.endswith("tests/test_loadmeter.py:_fetch_a")


def test_failed_request_is_still_recorded_and_the_patch_removed():
    original = requests.Session.send
    with loadmeter.session() as m:
        with pytest.raises(requests.exceptions.RequestException):
            requests.get("http://unreachable.example.test/", timeout=2)
    assert len(m.calls) == 1 and m.calls[0].status is None
    assert requests.Session.send is original


def test_report_is_readable_when_empty_and_when_full(base):
    with loadmeter.session("empty") as e:
        pass
    assert "0 calls" in e.report()
    with loadmeter.session("full") as f:
        _fetch_a(base + "/z")
    out = f.report()
    assert "1 calls" in out and "/z" in out and "fantasyfootballcalculator.com" in out


def test_redirect_chain_counts_as_one_call_with_the_final_size(base):
    with loadmeter.session() as m:
        r = requests.get(base + "/redir")
    assert r.status_code == 200 and len(r.history) == 1
    assert len(m.calls) == 1
    assert m.calls[0].endpoint.endswith("/redir") and m.calls[0].nbytes == 1000
    assert m.total_bytes() == 1000 and m.repeats() == 0


# --- live per-request measurement ------------------------------------------

@pytest.fixture
def live(monkeypatch):
    """ensure_installed() is permanent by design; undo it after each test."""
    loadmeter.clear_recent()
    yield loadmeter
    loadmeter._PERMANENT = False
    loadmeter._uninstall()
    loadmeter.clear_recent()


def test_enabled_defaults_local_on_render_off_and_env_overrides(monkeypatch):
    monkeypatch.delenv("LOADMETER", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    assert loadmeter.enabled() is True
    monkeypatch.setenv("RENDER", "true")
    assert loadmeter.enabled() is False
    monkeypatch.setenv("LOADMETER", "1")
    assert loadmeter.enabled() is True
    monkeypatch.setenv("RENDER", "")
    monkeypatch.setenv("LOADMETER", "0")
    assert loadmeter.enabled() is False


def test_request_counts_only_its_own_calls(base, live):
    live.ensure_installed()
    with live.request("GET /a") as a:
        _fetch_a(base + "/one")
    with live.request("GET /b") as b:
        _fetch_a(base + "/two")
        _fetch_a(base + "/three")
    assert len(a.calls) == 1 and len(b.calls) == 2
    recent = live.recent()
    assert [r["label"] for r in recent["requests"]] == ["GET /b", "GET /a"]
    assert recent["requests"][0]["calls"] == 2 and recent["requests"][0]["bytes"] == 2000


def test_pool_workers_are_attributed_to_the_request(base, live):
    from concurrent.futures import ThreadPoolExecutor
    live.ensure_installed()
    with ThreadPoolExecutor(3) as ex, live.request("GET /fan") as m:
        list(ex.map(lambda i: _fetch_a(base + f"/w{i}"), range(5)))
    assert len(m.calls) == 5


def test_calls_outside_any_request_are_background(base, live):
    live.ensure_installed()
    t = threading.Thread(target=_fetch_a, args=(base + "/bg",))
    t.start(); t.join()
    with live.request("GET /x") as m:
        pass
    assert len(m.calls) == 0
    assert live.recent()["background"]["calls"] == 1


def test_two_overlapping_requests_do_not_mix(base, live):
    live.ensure_installed()
    out = {}
    gate = threading.Barrier(2)

    def visitor(name, n):
        with live.request(name) as m:
            gate.wait()
            for i in range(n):
                _fetch_a(base + f"/{name}x{i}")
        out[name] = m

    ts = [threading.Thread(target=visitor, args=("u1", 2)),
          threading.Thread(target=visitor, args=("u2", 5))]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(out["u1"].calls) == 2 and len(out["u2"].calls) == 5
    assert all(c.endpoint.endswith("/u1x" + c.endpoint[-1]) for c in out["u1"].calls)


def test_ring_is_bounded(base, live, monkeypatch):
    from collections import deque
    monkeypatch.setattr(loadmeter, "_RECENT", deque(maxlen=3))
    for i in range(7):
        with live.request(f"r{i}"):
            pass
    assert [r["label"] for r in live.recent()["requests"]] == ["r6", "r5", "r4"]


def test_app_endpoint_is_local_only_and_off_when_disabled(monkeypatch):
    from types import SimpleNamespace
    from webapp import app as appmod
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("LOADMETER", raising=False)
    local = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    remote = SimpleNamespace(client=SimpleNamespace(host="203.0.113.9"))
    assert appmod.loadmeter_view(local).status_code == 200
    assert appmod.loadmeter_view(remote).status_code == 404
    monkeypatch.setenv("RENDER", "true")
    assert appmod.loadmeter_view(local).status_code == 404
    monkeypatch.setenv("RENDER", "")
    monkeypatch.setenv("LOADMETER", "1")
    assert appmod.loadmeter_view(local, format="text").status_code == 200


# --- what a call may be reported as (allow list) ---------------------------

LEAGUE = "1252770181306929152"
USER = "alexjade96"


@pytest.mark.parametrize("host,path,expected", [
    ("api.sleeper.app", f"/v1/league/{LEAGUE}", "/v1/league/{league}"),
    ("api.sleeper.app", f"/v1/league/{LEAGUE}/matchups/5", "/v1/league/{league}/matchups/{week}"),
    ("api.sleeper.app", f"/v1/league/{LEAGUE}/transactions/12", "/v1/league/{league}/transactions/{week}"),
    ("api.sleeper.app", f"/v1/league/{LEAGUE}/rosters", "/v1/league/{league}/rosters"),
    ("api.sleeper.app", f"/v1/user/{USER}", "/v1/user/{user}"),
    ("api.sleeper.app", f"/v1/user/{LEAGUE}/leagues/nfl/2024", "/v1/user/{user}/leagues/{sport}/{season}"),
    ("api.sleeper.app", "/v1/stats/nfl/regular/2024/3", "/v1/stats/nfl/regular/{season}/{week}"),
    ("api.sleeper.app", "/v1/state/nfl", "/v1/state/nfl"),
    # a Sleeper path nobody listed is never echoed
    ("api.sleeper.app", f"/v1/league/{LEAGUE}/something_new", "(unrecognised)"),
    ("api.sleeper.app", f"/v1/user/{USER}/extra/{LEAGUE}", "(unrecognised)"),
    # public hosts: shown as is when they fit, else not
    ("github.com", "/nflverse/nflverse-data/releases/download/pbp/play_by_play_2024.parquet",
     "/nflverse/nflverse-data/releases/download/pbp/play_by_play_2024.parquet"),
    ("github.com", f"/someone/private-{LEAGUE}", "(unrecognised)"),
    ("release-assets.githubusercontent.com", "/github-production-release-asset/452908115/x",
     "(nflverse release asset)"),
    ("sleepercdn.com", "/content/nfl/players/4034.jpg", "/content/nfl/players/4034.jpg"),
    ("sleepercdn.com", f"/avatars/{LEAGUE}", "(unrecognised)"),      # user avatars are private
    # any other host: nothing about the path survives
    ("evil.example", f"/league/{LEAGUE}", "(host not listed)"),
])
def test_classify_is_an_allow_list(host, path, expected):
    assert loadmeter.classify(host, path) == expected


def test_no_league_or_user_id_reaches_any_output(base, live):
    live.ensure_installed()
    urls = [f"https://api.sleeper.app/v1/league/{LEAGUE}/matchups/5",
            f"https://api.sleeper.app/v1/user/{USER}",
            f"https://api.sleeper.app/v1/league/{LEAGUE}/not_listed",
            f"https://sleepercdn.com/avatars/{LEAGUE}",
            f"https://other.example/{LEAGUE}?token={USER}"]
    with live.request("GET /page") as m:
        for u in urls:
            requests.get(u)
    with loadmeter.session("s") as s:
        for u in urls:
            requests.get(u)
    blob = " ".join([repr(m.calls), repr(m.to_dict()), repr(m.summary()), m.report(),
                     repr(s.calls), s.report(), repr(live.recent())])
    assert LEAGUE not in blob and USER not in blob and "token" not in blob
    import re
    assert not re.search(r"(?<![0-9.])[0-9]{15,}", blob)       # second net: no long id (not digits inside a float)


def test_repeats_still_counted_without_keeping_the_real_path(base):
    u = f"https://api.sleeper.app/v1/league/{LEAGUE}/matchups/5"
    with loadmeter.session() as m:
        requests.get(u); requests.get(u)
        requests.get(f"https://api.sleeper.app/v1/league/{LEAGUE}/matchups/6")
    assert len(m.calls) == 3 and m.repeats() == 1
    assert all(LEAGUE not in repr(c) for c in m.calls)


def test_every_sleeper_path_the_code_uses_has_a_template():
    """Fails when someone adds a Sleeper endpoint without a template; the
    report would otherwise call it (unrecognised)."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    lit = re.compile(r'f?"(/(?:league|user|draft|stats|state|players)[^"\s]*)"')
    seen = set()
    for py in list((root / "sleepermetrics").rglob("*.py")) + list((root / "webapp").rglob("*.py")):
        if "venv" in py.parts:
            continue
        text = py.read_text(encoding="utf-8")
        for m in lit.finditer(text):
            near = text[max(0, m.start() - 160):m.start()]
            if "sleeper_api" not in near and "paths" not in near:
                continue                      # a web route or other string, not a Sleeper call
            def sub(x):
                inner = x.group(1)
                if "sport" in inner:
                    return "nfl"
                if "season" in inner or inner in ("y", "year"):
                    return "2024"
                return "1"
            path = "/v1" + re.sub(r"\{([^}]*)\}", sub, m.group(1))
            if loadmeter.classify("api.sleeper.app", path) == "(unrecognised)":
                seen.add(m.group(1))
    assert not seen, f"Sleeper paths with no template in loadmeter._SLEEPER_TEMPLATES: {sorted(seen)}"
