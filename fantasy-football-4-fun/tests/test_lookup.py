"""Network-free tests for /lookup: the single auto-detecting search field
that replaced the explicit League/User mode toggle. Sleeper's numeric ids
(league_id, user_id, ...) are drawn from one shared id space, so checking
/league/{q} first (and only /user/{q} on a miss) reliably tells the two
apart without asking the caller to declare which one they typed. Follows the
direct-call convention test_user_leagues.py/test_player_page.py use for
other routes -- no ASGI/TestClient layer, a minimal fake Request and a call
straight into the route function.
"""
from __future__ import annotations

from webapp import app


class _Req:
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


def test_lookup_league_match_in_dashboard_renders_in_place(monkeypatch):
    """nav=0 (the in-dashboard header, shell already loaded): a league match
    renders the Overview in place via the same tab("overview", boot=1) path
    /load always used -- no redirect, since the shell is already there."""
    monkeypatch.setattr(app.sm, "league", lambda lid: {"league_id": lid, "name": "Dank Soupers"})

    calls = []

    def _fake_load(request, league, season, theme):
        calls.append((league, season, theme))
        return app.HTMLResponse("<div>overview</div>")

    monkeypatch.setattr(app, "load", _fake_load)

    resp = app.lookup(_Req(), q="1252770181306929152", nav=0)
    assert calls == [("1252770181306929152", None, "light")]
    assert "HX-Redirect" not in resp.headers


def test_lookup_league_match_from_landing_page_redirects(monkeypatch):
    """nav=1 (the landing page, no dashboard shell loaded yet): a league
    match answers with HX-Redirect so htmx does a full browser navigation to
    /dashboard, instead of swapping a fragment into a page that has no tabs/
    header to show it in."""
    monkeypatch.setattr(app.sm, "league", lambda lid: {"league_id": lid, "name": "Dank Soupers"})

    resp = app.lookup(_Req(), q="1252770181306929152", nav=1)
    assert resp.headers["HX-Redirect"] == "/dashboard?league=1252770181306929152"


def test_lookup_user_match_renders_league_list(monkeypatch):
    """A value that resolves as a user (not a league) renders the same
    "which of this account's leagues?" fragment /user-leagues always has,
    regardless of `nav` -- there is no league to redirect into."""
    def _fail_league(lid):
        return None
    monkeypatch.setattr(app.sm, "league", _fail_league)
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "656711573536088064", "display_name": "LuckyHarm",
        "username": "luckyharm", "avatar": None})

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", lambda paths: [[] for _ in paths])
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    resp = app.lookup(_Req(), q="luckyharm", nav=1)
    assert resp.template.name == "_user_leagues.html"
    assert resp.context["user"]["display_name"] == "LuckyHarm"


def test_lookup_user_match_pushes_bookmarkable_url(monkeypatch):
    """Regression test for a real gap: a user match used to touch the
    address bar at all -- neither this route nor /user-leagues ever set
    HX-Push-Url, so a user's search results could never be reloaded, shared,
    or found again in browser history (unlike a league match, which always
    had a real /dashboard URL). /?user=<handle> (see app.py's home()) is the
    landing page's counterpart, so the fix pushes THAT, regardless of `nav`
    -- the results are identical whichever shell the search was made from."""
    monkeypatch.setattr(app.sm, "league", lambda lid: None)
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "656711573536088064", "display_name": "LuckyHarm",
        "username": "luckyharm", "avatar": None})

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", lambda paths: [[] for _ in paths])
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    resp = app.lookup(_Req(), q="luckyharm", nav=1)
    assert resp.headers["HX-Push-Url"] == "/?user=luckyharm"

    resp2 = app.lookup(_Req(), q="luckyharm", nav=0)
    assert resp2.headers["HX-Push-Url"] == "/?user=luckyharm"


def test_lookup_neither_matches_shows_error(monkeypatch):
    monkeypatch.setattr(app.sm, "league", lambda lid: None)
    monkeypatch.setattr(app.sm, "user", lambda h: None)

    resp = app.lookup(_Req(), q="not-a-real-id")
    assert "error" in resp.context
    assert "not-a-real-id" in resp.context["error"]


def test_lookup_league_check_raising_falls_through_to_user_check(monkeypatch):
    """A 404/network error on the league lookup must not blow up the whole
    request -- it degrades to "not a league" and falls through to the user
    check, same as a clean null response would."""
    def _boom(lid):
        raise RuntimeError("404")
    monkeypatch.setattr(app.sm, "league", _boom)
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "1", "display_name": "Nobody", "username": "nobody", "avatar": None})

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", lambda paths: [[] for _ in paths])
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    resp = app.lookup(_Req(), q="nobody")
    assert resp.template.name == "_user_leagues.html"
    assert resp.context["user"]["display_name"] == "Nobody"


def test_lookup_blank_query_shows_prompt():
    resp = app.lookup(_Req(), q="   ")
    assert "error" in resp.context


def test_lookup_league_short_circuits_before_checking_user(monkeypatch):
    """A league hit must not also spend a call checking /user/{q} -- see the
    route's own docstring on why a collision is not possible on length
    grounds alone."""
    monkeypatch.setattr(app.sm, "league", lambda lid: {"league_id": lid, "name": "X"})

    def _user_should_not_be_called(h):
        raise AssertionError("user() must not be called after a league hit")
    monkeypatch.setattr(app.sm, "user", _user_should_not_be_called)

    resp = app.lookup(_Req(), q="123", nav=1)
    assert resp.headers["HX-Redirect"] == "/dashboard?league=123"


def test_home_with_user_param_prerenders_results(monkeypatch):
    """GET /?user=<handle> (the bookmarkable URL /lookup's user match now
    pushes) must show the SAME results a live search would, rendered
    server-side into #user-results -- not an empty placeholder waiting on a
    client-side fetch that a direct page load/reload would never trigger."""
    monkeypatch.setattr(app.sm, "user", lambda h: {
        "user_id": "656711573536088064", "display_name": "LuckyHarm",
        "username": "luckyharm", "avatar": None})

    import sleepermetrics.api as sm_api
    monkeypatch.setattr(sm_api, "sleeper_api_many", lambda paths: [[] for _ in paths])
    monkeypatch.setattr(app, "_current_nfl_season", lambda: "2026")

    resp = app.home(_Req(), user="luckyharm")
    body = resp.body.decode()
    assert "LuckyHarm" in body
    assert 'id="user-results"' in body


def test_home_without_user_param_renders_empty_placeholder():
    """The normal landing page (no ?user=) must still render the plain
    empty #user-results div -- home() must not blow up or render stray
    content when `user` is blank."""
    resp = app.home(_Req(), user="")
    body = resp.body.decode()
    assert '<div id="user-results"></div>' in body
