"""Live smoke tests: is the deployed site up, and do its heavy pages survive?

See conftest.py for how to run them.  Each test names the failure it guards
against.  Pages that build a lot in memory (player profile, team profile, ADP
board, season report) are followed by a /health check, because the failure
this suite exists to catch is the instance running out of memory and
restarting: the heavy request itself may even succeed while the NEXT one fails.
"""
from __future__ import annotations

import os
import re

import pytest

# A QB with a stable, well-known Sleeper id, and a team with a full history.
PLAYER = ("4984", "Josh Allen")
OTHER_PLAYER = ("8183", "Brock Purdy")
TEAM = ("BUF", "2025")
SEASON = "2025"


def _alive(site):
    assert site.healthy(), "/health stopped answering: the instance probably restarted"


# --- the basics -------------------------------------------------------------

def test_health(site):
    r = site.fetch("/health")
    assert r.status_code == 200


def test_landing_page(site):
    r = site.fetch("/")
    assert r.status_code == 200
    assert "Fantasy Football 4 Fun" in r.text


@pytest.mark.parametrize("path", [
    "/static/style.css", "/static/htmx-1.9.12.min.js", "/static/table-sort.js"])
def test_static_assets(site, path):
    assert site.fetch(path).status_code == 200


# --- player profile (the page that ran out of memory) -------------------------

def test_player_loader_page(site):
    """A cold profile answers instantly with a loader that redirects to render=1."""
    r = site.fetch(f"/player/{PLAYER[0]}?season=2026")
    assert r.status_code == 200
    assert "render=1" in r.text or PLAYER[1] in r.text


def test_player_profile_renders(site):
    r = site.fetch(f"/player/{PLAYER[0]}?render=1&season=2026")
    assert r.status_code == 200
    assert PLAYER[1] in r.text
    assert ">nan<" not in r.text
    # A None league leaked into chart urls as the text "None" and made the radar
    # build a second profile under a different cache key.
    assert "league=None" not in r.text
    _alive(site)


def test_player_radar_chart(site):
    page = site.fetch(f"/player/{PLAYER[0]}?render=1&season=2026").text
    m = re.search(r'src="(/chart/player_radar[^"]+)"', page)
    assert m, "profile page has no radar chart"
    r = site.fetch(m.group(1).replace("&amp;", "&"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    _alive(site)


def test_player_season_fragment(site):
    site.fetch(f"/player/{PLAYER[0]}?render=1&season=2026")
    r = site.fetch(f"/player/{PLAYER[0]}/season?theme=light&season_scope={SEASON}")
    assert r.status_code == 200
    assert ">nan<" not in r.text


def test_second_player_after_first(site):
    """Two different cold profiles in a row: memory must not accumulate to a kill."""
    r = site.fetch(f"/player/{OTHER_PLAYER[0]}?render=1&season=2026")
    assert r.status_code == 200
    assert OTHER_PLAYER[1] in r.text
    _alive(site)


# --- team profile -------------------------------------------------------------

def test_team_profile_renders(site):
    r = site.fetch(f"/team/{TEAM[0]}?render=1&season={TEAM[1]}")
    assert r.status_code == 200
    assert ">nan<" not in r.text
    _alive(site)


# --- NFL stats tab ------------------------------------------------------------

@pytest.mark.parametrize("query", [
    "view=leaderboard&season=2025&pos=QB&source=sleeper",
    "view=leaderboard&season=2024&pos=QB&source=nflverse",
    "view=compare&season=2024&pos=QB",
])
def test_nflstats_views(site, query):
    r = site.fetch(f"/nflstats/data?{query}")
    assert r.status_code == 200
    assert ">nan<" not in r.text


# --- ADP comparison (large response) -------------------------------------------

@pytest.mark.parametrize("season", ["2025", "2018"])
def test_adp_board(site, season):
    r = site.fetch(f"/adp/data?season={season}&scoring=ppr&pos=ALL")
    assert r.status_code == 200
    assert "<table" in r.text
    _alive(site)


# --- player comparison ----------------------------------------------------------

def test_playercompare_leaderboard(site):
    r = site.fetch("/playercompare/data?position=RB&season=2025")
    assert r.status_code == 200
    assert "checkbox" in r.text


def test_playercompare_chart(site):
    q = (f"position=QB&season=2025&mode=snapshot&stat_mode=per_game"
         f"&player_ids={PLAYER[0]}%2C{OTHER_PLAYER[0]}"
         f"&player_labels={PLAYER[1].replace(' ', '%20')}%2C{OTHER_PLAYER[1].replace(' ', '%20')}")
    r = site.fetch(f"/chart/player_overlay?{q}")
    assert r.status_code == 200
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


# --- league dashboard -------------------------------------------------------------

def test_dashboard_overview(site):
    r = site.fetch("/tab/overview?boot=1")
    assert r.status_code == 200


@pytest.mark.skipif(os.environ.get("SITE_SKIP_SLOW") == "1",
                    reason="SITE_SKIP_SLOW=1")
def test_season_report(site):
    """The biggest single response (about 20 charts baked into one file)."""
    r = site.fetch("/report?render=1")
    assert r.status_code == 200
    assert "<html" in r.text.lower()
    _alive(site)


# --- last: after everything above, the instance must still be the same healthy one

def test_still_healthy_after_everything(site):
    _alive(site)
