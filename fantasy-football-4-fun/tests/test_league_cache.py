"""League cache behaviour in webapp/app.py and sleepermetrics.season.seasons().

Network-free: the chain, the season assembly and the league id resolution are
replaced with stubs.  Covers: finished seasons are reused on a refresh, the
rendered-asset store survives a refresh when nothing can have changed, the
Render-only league cap, and that the player charts build their data before
taking the render lock.
"""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

import sleepermetrics as sm
import sys

import sleepermetrics.season  # noqa: F401
from webapp import app as app_mod
from webapp import assetcache

season_mod = sys.modules["sleepermetrics.season"]   # the package re-exports a function named season


def _link(lid, status):
    return {"league_id": lid, "status": status}


def _season(lid, status):
    return SimpleNamespace(league_id=lid, status=status, season=lid, name="L",
                           standings=None)


@pytest.fixture
def chain(monkeypatch):
    """Two finished seasons and one in progress; counts assemble_season calls."""
    links = {"2024": _link("a", "complete"), "2025": _link("b", "complete"),
             "2026": _link("c", "in_season")}
    calls = []
    monkeypatch.setattr(season_mod, "league_chain", lambda lid: links)
    monkeypatch.setattr(season_mod, "assemble_season",
                        lambda link: calls.append(link["league_id"]) or
                        _season(link["league_id"], link["status"]))
    return links, calls


def test_seasons_without_reuse_fetches_everything(chain):
    _, calls = chain
    season_mod.seasons("x")
    assert calls == ["a", "b", "c"]


def test_seasons_reuses_finished_seasons_only(chain):
    _, calls = chain
    first = season_mod.seasons("x")
    calls.clear()
    second = season_mod.seasons("x", reuse=first)
    assert calls == ["c"]                       # only the one in progress
    assert second["2024"] is first["2024"] and second["2025"] is first["2025"]
    assert second["2026"] is not first["2026"]


def test_a_season_that_just_finished_is_refetched(chain):
    links, calls = chain
    first = season_mod.seasons("x")             # 2026 was in progress
    links["2026"] = _link("c", "complete")
    calls.clear()
    season_mod.seasons("x", reuse=first)
    assert calls == ["c"]                       # old copy said in progress


def test_a_different_league_id_is_not_reused(chain):
    links, calls = chain
    first = season_mod.seasons("x")
    links["2024"] = _link("other", "complete")
    calls.clear()
    season_mod.seasons("x", reuse=first)
    assert "other" in calls


# --- _assemble_league --------------------------------------------------------

@pytest.fixture
def assemble(monkeypatch):
    """_assemble_league with the network pieces stubbed; returns a runner."""
    app_mod._cache.clear()
    state = {"seasons": {}}

    monkeypatch.setattr(sm, "current_season_league_id", lambda lid: str(lid))
    monkeypatch.setattr(sm, "seasons", lambda lid, reuse=None, **kw: state["seasons"])
    monkeypatch.setattr(sm, "apply_playoffs", lambda s, *_a, **_k: s)
    monkeypatch.setattr(sm, "load_playoffs", lambda *a, **k: {})
    monkeypatch.setattr(sm, "sleeper_bracket", lambda *a, **k: {})
    yield state
    app_mod._cache.clear()


def test_refresh_keeps_assets_when_every_season_is_finished(assemble):
    done = {"2024": _season("a", "complete"), "2025": _season("b", "complete")}
    assemble["seasons"] = done
    first = app_mod._assemble_league("L1")
    assetcache.store_for(first)[("chart", "x")] = {"body": b"png"}
    first["_warming"] = {("2025", "light")}
    ver = first.get("ver", first["at"])

    second = app_mod._assemble_league("L1")
    assert second is not first
    assert second["_assets"] is first["_assets"]
    assert second["_warming"] == {("2025", "light")}
    assert second.get("ver", second["at"]) == ver
    assert second["at"] >= first["at"]          # the entry's age restarts


def test_refresh_drops_assets_while_a_season_is_in_progress(assemble):
    assemble["seasons"] = {"2025": _season("b", "complete"),
                           "2026": _season("c", "in_season")}
    first = app_mod._assemble_league("L1")
    assetcache.store_for(first)[("chart", "x")] = {"body": b"png"}
    # What sm.seasons(reuse=...) would return: the finished season reused, the
    # live one rebuilt.
    assemble["seasons"] = {"2025": first["seasons"]["2025"],
                           "2026": _season("c", "in_season")}
    second = app_mod._assemble_league("L1")
    assert "_assets" not in second              # data may have changed


# --- league cap --------------------------------------------------------------

def _put(key, used, resolved=None):
    d = {"at": 0.0, "used": used, "resolved_league_id": resolved or key}
    app_mod._cache[key] = d
    if resolved and resolved != key:
        app_mod._cache[resolved] = d
    return d


def test_cap_is_inactive_off_render(monkeypatch):
    monkeypatch.delenv("RENDER", raising=False)
    app_mod._cache.clear()
    for i in range(6):
        _put(f"L{i}", i)
    app_mod._evict_leagues(limit=2)
    assert len(app_mod._cache) == 6
    app_mod._cache.clear()


def test_cap_evicts_least_recently_used_on_render(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app_mod._cache.clear()
    for i in range(5):
        _put(f"L{i}", float(i))
    app_mod._evict_leagues(limit=3)
    assert sorted(app_mod._cache) == ["L2", "L3", "L4"]
    app_mod._cache.clear()


def test_cap_treats_two_ids_for_one_league_as_one(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app_mod._cache.clear()
    _put("old", 1.0, resolved="new")            # one league, two keys
    _put("L1", 2.0)
    _put("L2", 3.0)
    app_mod._evict_leagues(limit=2)
    assert sorted(app_mod._cache) == ["L1", "L2"]   # both keys of the oldest went
    app_mod._cache.clear()


def test_cap_never_evicts_the_default_league(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    app_mod._cache.clear()
    _put(app_mod.DEFAULT_LEAGUE, 0.0)           # the least recently used
    for i in range(4):
        _put(f"L{i}", float(i + 1))
    app_mod._evict_leagues(limit=3)
    assert app_mod.DEFAULT_LEAGUE in app_mod._cache
    assert len({id(d) for d in app_mod._cache.values()}) == 3
    app_mod._cache.clear()


# --- the render lock ---------------------------------------------------------

def test_player_radar_builds_its_data_before_taking_the_render_lock(monkeypatch):
    from webapp import player_profile as pp

    seen = {}

    def fake_profile(player_id, league_id=None):
        seen["locked_during_build"] = app_mod._render_lock.locked()
        return {"identity": {"player_name": "P"}, "season_profiles": {},
                "season_profiles_per_game": {}, "focus_season": "2025"}

    monkeypatch.setattr(pp, "player_profile", fake_profile)
    monkeypatch.setattr(app_mod.plots, "plot_player_radar", lambda *a, **k: object())
    monkeypatch.setattr(app_mod, "png", lambda fig: app_mod.Response(b"x", media_type="image/png"))
    app_mod.chart.__wrapped__("player_radar", league="", player_id="123")
    assert seen["locked_during_build"] is False


def test_player_comparison_builds_its_data_before_taking_the_render_lock(monkeypatch):
    from webapp import player_compare as pc

    seen = []
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda *a, **k: seen.append(app_mod._render_lock.locked()) or {})
    monkeypatch.setattr(pc, "player_trend",
                        lambda *a, **k: seen.append(app_mod._render_lock.locked()) or {})
    monkeypatch.setattr(app_mod.plots, "plot_player_overlay", lambda *a, **k: object())
    monkeypatch.setattr(app_mod, "png", lambda fig: app_mod.Response(b"x", media_type="image/png"))
    for mode in ("snapshot", "trend"):
        app_mod.chart.__wrapped__("player_overlay", player_ids="1,2", player_labels="A,B",
                                  position="RB", season="2025", mode=mode)
    assert seen == [False, False]


def test_another_chart_is_not_held_behind_a_slow_player_build(monkeypatch):
    """While a player build is running, the render lock is free for others."""
    from webapp import player_profile as pp

    started, release = threading.Event(), threading.Event()

    def slow_profile(player_id, league_id=None):
        started.set()
        release.wait(5)
        return {"identity": {}, "season_profiles": {}, "season_profiles_per_game": {}}

    monkeypatch.setattr(pp, "player_profile", slow_profile)
    monkeypatch.setattr(app_mod.plots, "plot_player_radar", lambda *a, **k: object())
    monkeypatch.setattr(app_mod, "png", lambda fig: app_mod.Response(b"x", media_type="image/png"))
    t = threading.Thread(target=lambda: app_mod.chart.__wrapped__(
        "player_radar", league="", player_id="1"))
    t.start()
    assert started.wait(5)
    got = app_mod._render_lock.acquire(timeout=1)       # another chart's draw
    if got:
        app_mod._render_lock.release()
    release.set()
    t.join(5)
    assert got
