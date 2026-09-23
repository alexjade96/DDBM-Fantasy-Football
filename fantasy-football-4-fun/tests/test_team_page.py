"""Network-free tests for the /team/{abbr} route and its lazy-loaded
per-game detail endpoint, /team/{abbr}/game/{week}. Follows the same
direct-call convention test_player_page.py uses for /player/{player_id} --
no ASGI/TestClient layer, a minimal fake Request, and a call straight into
the route function, with webapp.team_profile.team_profile() itself
monkeypatched so these tests exercise only the route + template, not the
aggregator (that's test_team_profile.py's job).
"""
from __future__ import annotations

import pytest

from webapp import app, team_profile as tp


class _Req:
    """Minimal stand-in for starlette's Request -- TemplateResponse only
    needs `.scope` / attribute access."""
    scope = {"type": "http"}
    headers = {}

    def __getattr__(self, _):
        return None


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    tp.clear_profile_cache()
    yield
    tp.clear_profile_cache()


def _game(week, **stats):
    return {"week": week, "game_type": "REG", "away_team": "SF", "away_score": 24,
            "home_team": "DAL", "home_score": 20, "margin": 4, "stats": stats}


_EMPTY_METRIC = {"reconciled": [], "sources": [], "source_groups": []}


@pytest.fixture
def _fake_profile(monkeypatch):
    """Stub webapp.team_profile.team_profile with a two-game schedule --
    week 1 carries real injuries data (so its detail has something to
    render), week 2 carries nothing (the "no advanced stats" empty case)."""
    week1_stats = {
        "passing": _EMPTY_METRIC, "rushing": _EMPTY_METRIC, "receiving": _EMPTY_METRIC,
        "injuries": [{"full_name": "Fred Warner", "team": "SF", "week": 1,
                      "report_primary_injury": "Knee", "report_status": "Questionable"}],
    }
    week2_stats = {"passing": _EMPTY_METRIC, "rushing": _EMPTY_METRIC, "receiving": _EMPTY_METRIC}

    def _fake(abbr, season=None, fresh=False):
        return {
            "identity": {"abbr": abbr, "known": True},
            "current_season": "2025", "seasons_covered": ["2025"],
            "roster": [], "roster_by_position": [],
            "schedule": [_game(1, **week1_stats), _game(2, **week2_stats)],
            "season_history": [], "team_datasets": {}, "team_stats_grouped": {},
        }
    monkeypatch.setattr(tp, "team_profile", _fake)
    monkeypatch.setattr(tp, "is_cached", lambda abbr, season=None: True)
    return _fake


def test_team_page_schedule_rows_are_lazy_not_inline(_fake_profile):
    """The schedule section must show a Loading placeholder + hx-get link
    per game, never the game's own advanced-stat tables inline -- see
    team_profile.html's own comment on why (a real, measured payload cost:
    baking every game's full detail inline ran ~900KB of HTML for one
    team-season)."""
    resp = app.team_page(_Req(), "SF", season="2025")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert body.count("Loading&hellip;") == 2  # one per game
    assert 'hx-get="/team/SF/game/1?season=2025' in body
    assert 'hx-get="/team/SF/game/2?season=2025' in body
    assert 'hx-trigger="toggle once"' in body
    # Nothing from the injuries row leaks into the always-rendered page --
    # it only exists once /team/SF/game/1 is actually fetched.
    assert "Fred Warner" not in body
    assert 'class="stat-cell"' not in body


def test_team_page_loads_htmx_script(_fake_profile):
    """Regression guard for a real bug: the schedule drilldown was wired
    with hx-get/hx-trigger attributes, but team_profile.html never
    included the htmx <script> tag at all (it's a standalone page with no
    dashboard shell -- unlike index.html, which loads htmx for every tab,
    this page had never needed it before the lazy-load schedule rows were
    added). Every hx-* attribute was therefore inert HTML with no JS behind
    it: clicking a row did nothing but the native <details> expand, and the
    "Loading..." placeholder never resolved. This is exactly the kind of
    bug a template-string/route-return-value test CANNOT catch on its own
    (every existing test asserting `hx-get=` is present in the body would
    still pass even with the script tag missing) -- this test exists
    specifically to close that gap. Mirrors player_profile.html's own
    identical include for its one htmx-swapped section."""
    resp = app.team_page(_Req(), "SF", season="2025")
    body = resp.body.decode()
    assert '<script src="/static/htmx-1.9.12.min.js" defer></script>' in body
    # The script tag must appear BEFORE any hx-* attribute is used, i.e.
    # inside <head> -- not an incidental match somewhere else in the page.
    assert body.find("htmx-1.9.12.min.js") < body.find("hx-get=")


def test_team_page_schedule_row_hx_attrs_live_on_details_not_summary(_fake_profile):
    """Regression guard for a real bug: hx-get/hx-trigger="toggle once" were
    originally placed on <summary>, but the native `toggle` DOM event fires
    on the <details> element itself, not <summary> -- so the request never
    fired at all and every row stayed stuck on "Loading..." forever, with
    no client-side error to notice. Every game's drilldown must therefore
    have its hx-* attributes on <details class="dt-row" ...>, targeting its
    own child .dt-detail (`hx-target="find .dt-detail"`), not a sibling
    selector off <summary>."""
    resp = app.team_page(_Req(), "SF", season="2025")
    body = resp.body.decode()
    import re
    rows = re.findall(r'<details class="dt-row"(.*?)>\s*<summary>', body, re.S)
    assert len(rows) == 2  # one per game
    for row_attrs in rows:
        assert "hx-get=" in row_attrs
        assert 'hx-trigger="toggle once"' in row_attrs
        assert 'hx-target="find .dt-detail"' in row_attrs
    # And <summary>'s own OPENING TAG carries none of them -- they must not
    # have been left on both elements either (checking the tag itself, not
    # its content, which legitimately contains other markup).
    summary_tags = re.findall(r"<summary[^>]*>", body)
    assert len(summary_tags) == 2
    for tag in summary_tags:
        assert "hx-get=" not in tag
        assert "hx-trigger=" not in tag


def test_team_game_detail_renders_that_games_stats(_fake_profile):
    """A real hx-get hit returns just that one game's sub-tabbed detail --
    the injuries pill and its row, nothing about week 2 (a different
    game)."""
    resp = app.team_game_detail(_Req(), "SF", 1, season="2025")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "Injuries" in body  # the sub-tab pill label
    assert "Fred Warner" in body
    assert "Knee" in body


def test_team_game_detail_no_data_shows_empty_note(_fake_profile):
    """A game with no advanced stats at all (week 2 in the fixture) shows
    the plain empty note, not a viewswitch with nothing in it."""
    resp = app.team_game_detail(_Req(), "SF", 2, season="2025")
    assert resp.status_code == 200
    body = resp.body.decode()
    assert "No advanced stats found for this game." in body
    assert "dt-stat-mode" not in body


def test_team_game_detail_unknown_week_404s(_fake_profile):
    """A week that isn't in this team's schedule (a stale/tampered URL, not
    a normal click path) 404s rather than silently rendering an empty
    panel."""
    resp = app.team_game_detail(_Req(), "SF", 99, season="2025")
    assert resp.status_code == 404
