"""Network-free tests for the unified Testing page (GET /testing,
webapp.app.landing_testing()) -- the single URL both the landing page's nav
(home.html, no league loaded) and the loaded dashboard's tab nav (index.html,
which carries league/season via hx-include) now point at, replacing what
used to be two separate routes/templates (this route rendering
_landing_testing.html for the league-free case, GET /tab/testing rendering
tab_testing.html for the league-scoped case) reachable at genuinely
different URLs for the same "prototypes under review" concept. Unified
2026-09 per user request.

Direct-call convention (no ASGI/TestClient layer), same as
test_season_history.py (whose `_mock_pick` monkeypatches `app.pick` with a
fixture Season rather than touching the network) and
test_playercompare_landing.py.

Every prototype that has lived on this page (a set of Player Comparison
layout demos; a redesigned-landing-page link, "Seasons" menu, and
pill-toggle metric grouping; that trio's replacement, a schedule-drilldown
restyle mockup; and that mockup's own follow-up, a per-source hover flyout)
has since either shipped for real (see test_team_profile.py's
`test_team_profile_reconciled_table_renders_flyout_on_every_cell` for the
flyout's own end-to-end coverage against the real /team/{abbr} page) or
been dropped. tab_testing.html currently shows only the standing "nothing
under review" shell -- these tests cover the route's own dispatch (league-
free vs. league-scoped delegation), not any section's content, since there
is currently no section-specific content to test.
"""
from __future__ import annotations

from webapp import app
from conftest import make_season


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def _mock_pick(monkeypatch, d):
    monkeypatch.setattr(app, "pick", lambda league, season, fresh=False: (
        d, d["seasons"][season if season in d["seasons"] else d["names"][-1]],
        season if season in d["seasons"] else d["names"][-1]))


def _single_season_d():
    s = make_season(season="2025")
    return {"playoffs": {}, "names": ["2025"], "seasons": {"2025": s},
            "resolved_league_id": "123"}


def test_landing_testing_registered_on_home_nav():
    """home.html's Testing nav button must still point at this one URL --
    unchanged by the merge, since home.html never had #league/#season
    fields to hx-include in the first place, so a request from it always
    lands on the league-free branch."""
    from webapp import app as app_mod
    body = (app_mod.BASE / "templates" / "home.html").read_text(encoding="utf-8")
    assert "/testing" in body
    assert ">Testing<" in body


def test_landing_testing_no_league_renders_shell():
    """A bare GET /testing (no league param -- the landing-page path) never
    crashes and shows the standing "nothing under review" shell -- it never
    depended on a league resolving in the first place."""
    resp = app.landing_testing(_Req())
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "<h2>Testing</h2>" in body
    assert "Prototypes under review" in body
    assert "Nothing under review right now" in body


def test_landing_testing_empty_league_string_behaves_like_no_league():
    """The route's own default (`league: str = ""`) must behave exactly
    like the explicit no-arg case above -- an empty string is falsy in the
    route's `if league:` guard, same as None/absent."""
    resp = app.landing_testing(_Req(), league="")
    body = resp.body.decode()
    assert "Nothing under review right now" in body


def test_landing_testing_bad_league_degrades_to_shell(monkeypatch):
    """A league id that fails to resolve (mistyped, private, network gone)
    must degrade to the same league-free render as no league at all --
    never a 500, and never a half-built league-scoped page with missing
    data. Mirrors every other tab's own "couldn't load" degrade contract."""
    monkeypatch.setattr(app, "pick", lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))
    resp = app.landing_testing(_Req(), league="bad-id")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "Nothing under review right now" in body


def test_landing_testing_with_league_delegates_into_tab_testing(monkeypatch):
    """A `league` that resolves must delegate into tab("testing", ...) --
    same pattern load() already uses to delegate into tab("overview", ...,
    boot=1) -- so the league-scoped shell (season picker, live-band) renders
    through the SAME code path GET /tab/testing always has, rather than a
    second, potentially-drifting copy of that logic living in this route."""
    d = _single_season_d()
    _mock_pick(monkeypatch, d)
    resp = app.landing_testing(_Req(), league="123", season="2025")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert "<h2>Testing</h2>" in body
    assert "Nothing under review right now" in body


def test_landing_testing_with_league_carries_pushed_url(monkeypatch):
    """The league-scoped branch delegates through tab()'s own `_pushed()`
    wiring (same as every other tab), which stamps an HX-Push-Url header so
    the browser address bar reflects the loaded league/season -- a concrete
    check that delegation actually ran tab()'s ctx-building, not just that
    the shell renders."""
    d = _single_season_d()
    _mock_pick(monkeypatch, d)
    resp = app.landing_testing(_Req(), league="123", season="2025")
    assert resp.headers.get("HX-Push-Url", "").endswith("tab=testing")


def test_landing_testing_multi_season_league_still_shows_history_interstitial(monkeypatch):
    """tab()'s own multi-season-history redirect (a fresh multi-season
    league load with no season chosen shows a season picker before any
    tab's real content) fires the same way through this delegated path as
    it does for every other tab -- delegation must not special-case Testing
    out of that shared behavior."""
    import dataclasses
    s2024 = dataclasses.replace(make_season(season="2024"), league_id="L2024")
    s2025 = dataclasses.replace(make_season(season="2025"), league_id="L2025")
    d = {"playoffs": {}, "names": ["2024", "2025"],
         "seasons": {"2024": s2024, "2025": s2025},
         "resolved_league_id": "123"}
    _mock_pick(monkeypatch, d)
    resp = app.landing_testing(_Req(), league="123", season=None, boot=1)
    body = resp.body.decode()
    assert "Nothing under review right now" not in body  # history shown instead
    assert "2024" in body and "2025" in body
