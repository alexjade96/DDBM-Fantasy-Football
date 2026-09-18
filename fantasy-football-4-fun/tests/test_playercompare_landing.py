"""Network-free tests for the Player Comparison landing tab (league-free,
lives on the landing page alongside ADP Comparison / NFL Stats -- see
webapp/player_compare.py's module docstring for the scope decision).
Direct-call convention (no ASGI/TestClient layer), same as test_nflref.py's
own /nflstats route tests. `playercompare_data`'s route imports `nflref`
LOCALLY (`from webapp.sources import nflref`, not a module-level import in
app.py -- there is no `app.nflref` attribute to patch), so the leaderboard
call is stubbed at its real source instead:
`sleepermetrics.nflstats.player_leaderboard`/
`webapp.sources.nflref.summary.leaderboard_columns`, the same functions
`nflref.summary.player_leaderboard(source="sleeper")` delegates through.
"""
from __future__ import annotations

import pandas as pd
import pytest


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def test_playercompare_registered_on_home_nav():
    from webapp import app
    body = (app.BASE / "templates" / "home.html").read_text(encoding="utf-8")
    assert "/playercompare" in body
    assert "Player Comparison" in body


def test_playercompare_shell_renders_controls():
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "Player Comparison" in body
    assert 'value="RB" selected' in body


def test_playercompare_shell_wires_chart_fade_in():
    """Regression test for a real, shipped bug: .card.chart img starts at
    opacity:0 (style.css) and is only flipped to opacity:1 via the
    'loaded' class, normally added by the dashboard shell's (index.html)
    prepCharts() on the image's load event. This landing-page tab is a
    standalone page (no dashboard shell) that renders .card.chart images
    for the first time on this tab family (ADP Comparison / NFL Stats never
    render chart PNGs) -- without its own copy of that fade-in logic, the
    comparison charts loaded real PNG data (confirmed via direct fetch, and
    img.complete/naturalWidth both reporting success) but stayed invisible
    forever, since nothing ever added the 'loaded' class. Caught only by
    driving a real browser through the full click flow, not by inspecting
    rendered HTML alone -- assert the fix's own JS is present here so a
    future edit to this template can't silently drop it again."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert "fadeInCharts" in body
    assert "classList.add('loaded')" in body
    assert "e.target === charts" in body


def test_playercompare_params_defaults_and_validates():
    from webapp import app
    pos, sea = app._playercompare_params("BOGUS", "1999")
    assert pos == "RB"
    assert int(sea) >= 2016


def test_playercompare_params_accepts_valid_values():
    from webapp import app
    pos, sea = app._playercompare_params("WR", "2024")
    assert (pos, sea) == ("WR", "2024")


def test_playercompare_data_degrades_on_no_data(monkeypatch):
    from sleepermetrics import nflstats
    from webapp import app
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: pd.DataFrame())
    resp = app.playercompare_data(_Req(), position="RB", season="2024")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "No RB data available" in body


def test_playercompare_data_renders_checkbox_rows(monkeypatch):
    from sleepermetrics import nflstats
    from webapp import app
    from webapp.sources.nflref import summary as nflref_summary

    lb = pd.DataFrame([
        {"rank": 1, "player_id": "1", "gsis_id": None, "player": "Test RB",
         "position": "RB", "team": "SF", "games": 10, "rush_yards": 900,
         "fpts_ppr": 180.0},
    ])
    monkeypatch.setattr(nflstats, "player_leaderboard", lambda *a, **k: lb)
    monkeypatch.setattr(nflref_summary, "leaderboard_columns",
                        lambda pos, src: [("rush_yards", "Rush yds"), ("fpts_ppr", "PPR pts")])
    resp = app.playercompare_data(_Req(), position="RB", season="2024")
    body = resp.body.decode()
    assert "Test RB" in body
    assert 'data-playercompare-pick' in body
    assert 'value="1"' in body


def test_playercompare_data_degrades_on_exception(monkeypatch):
    from sleepermetrics import nflstats
    from webapp import app

    def _boom(*a, **k):
        raise RuntimeError("network access blocked in tests")
    monkeypatch.setattr(nflstats, "player_leaderboard", _boom)
    resp = app.playercompare_data(_Req(), position="RB", season="2024")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "No RB data available" in body


def test_playercompare_chart_section_below_two_players_shows_hint():
    from webapp import app
    resp = app.playercompare_chart_section(_Req(), position="RB", season="2024",
                                           player_ids="1", player_labels="Test RB")
    body = resp.body.decode()
    assert "Check at least 2 players" in body


def test_playercompare_chart_section_renders_both_chart_images():
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two")
    body = resp.body.decode()
    assert "/chart/player_overlay" in body
    assert "mode=snapshot" in body
    assert "mode=trend" in body


def test_chart_player_overlay_is_league_free_no_pick_needed(monkeypatch):
    """The player_overlay branch must dispatch BEFORE pick() -- calling it
    with no real league must not hit the network-dependent pick() path at
    all (mirrors the existing PLAYER_CHARTS/player_radar precedent)."""
    from webapp import app, player_compare as pc

    def _boom_pick(*a, **k):
        raise AssertionError("pick() should not be called for player_overlay")
    monkeypatch.setattr(app, "pick", _boom_pick)
    monkeypatch.setattr(pc, "player_field_compare", lambda season, pos, ids: {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 100.0, "percentile": 70.0}]}})
    resp = app.chart("player_overlay", position="RB", season="2024",
                     mode="snapshot", player_ids="1", player_labels="Test RB")
    assert resp.status_code == 200
    assert resp.media_type == "image/png"


def test_chart_player_overlay_trend_is_league_free(monkeypatch):
    from webapp import app, player_compare as pc

    def _boom_pick(*a, **k):
        raise AssertionError("pick() should not be called for player_overlay")
    monkeypatch.setattr(app, "pick", _boom_pick)
    monkeypatch.setattr(pc, "player_trend", lambda ids, season, position=None: {
        "1": [{"week": 1, "pts_ppr": 10.0}]})
    resp = app.chart("player_overlay", position="RB", season="2024",
                     mode="trend", player_ids="1", player_labels="Test RB")
    assert resp.status_code == 200
    assert resp.media_type == "image/png"


def test_chart_player_overlay_no_ids_degrades_without_pick(monkeypatch):
    from webapp import app

    def _boom_pick(*a, **k):
        raise AssertionError("pick() should not be called for player_overlay")
    monkeypatch.setattr(app, "pick", _boom_pick)
    resp = app.chart("player_overlay", position="RB")
    assert resp.status_code == 200
    assert resp.media_type == "image/png"
