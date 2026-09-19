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


def test_playercompare_shell_renders_clear_selection_button():
    """A "Clear selection" button next to Compare selected lets a user
    uncheck every currently-picked row in one click, instead of scrolling
    the leaderboard to find and manually uncheck each one (user request).
    It must start hidden (same as Compare selected -- nothing is checked
    yet on a fresh load), and its click handler must uncheck every box and
    re-sync the counter/button state rather than only hiding itself."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert 'id="playercompare-clear-btn"' in body
    assert "Clear selection" in body
    clear_btn = body[body.index('id="playercompare-clear-btn"') - 60:
                     body.index('id="playercompare-clear-btn"') + 100]
    assert "hidden" in clear_btn
    assert "clearBtn.onclick" in body
    assert "b.checked = false" in body


def test_playercompare_shell_clear_button_gated_on_same_threshold_as_compare():
    """Regression test: Clear selection must appear/disappear at the SAME
    checked-count threshold as Compare selected (n < 2), never a looser one
    (e.g. n < 1) -- an earlier version showed Clear as soon as 1 box was
    checked, which meant it popped in and back out on every single checkbox
    click while exactly 1 box was checked (a visible width "jiggle" in the
    controls row, user-reported). Tying both to the identical condition
    means the row only ever changes shape once, when Compare itself first
    becomes usable."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert "n < 2" in body
    # The clearBtn.hidden assignment must reuse the same `n < 2` condition,
    # not a separate, looser one -- find its own assignment line and check
    # it references `n < 2`, not some other comparison.
    idx = body.index("clearBtn.hidden")
    line = body[idx:body.index(";", idx)]
    assert "n < 2" in line


def test_playercompare_shell_load_button_sits_on_the_left():
    """Regression test: Load must sit with the Position/Season selection
    criteria on the LEFT of the controls row (user request), not pushed to
    the row's right edge the way NFL Stats/ADP's own Load buttons are (both
    plain `.nfl-apply`, right-aligned via that class's own shared
    `margin-left: auto` in style.css). A scoped `.playercompare-load` class
    override keeps every other `.nfl-apply` style but resets just the
    margin, so this tab's Load button doesn't inherit the right-push."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert 'class="nfl-apply playercompare-load"' in body
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index(".nfl-apply.playercompare-load")
    block = css[idx:css.index("}", idx)]
    assert "margin-left: 0" in block


def test_playercompare_shell_compare_and_clear_stay_right_justified():
    """Regression test: Compare selected/Clear selection must stay pushed to
    the controls row's RIGHT edge (user request) even though Load moved to
    the left -- `#playercompare-compare-btn` carries its OWN
    `margin-left: auto`, which pushes it and Clear (sitting right after it
    in source order, with only a small fixed gap) to the right, independent
    of Load's own leftward position."""
    from webapp import app
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index("#playercompare-compare-btn {")
    block = css[idx:css.index("}", idx)]
    assert "margin-left: auto" in block
    # Clear sits flush after Compare with a small FIXED gap, not another
    # auto-margin (which would push it away from Compare instead of beside
    # it, splitting the pair apart at the row's right edge).
    clear_idx = css.index(".playercompare-clear {")
    clear_block = css[clear_idx:css.index("}", clear_idx)]
    assert "margin-left: auto" not in clear_block


def test_playercompare_shell_charts_div_is_not_nested_in_loader_card():
    """Regression test: `#playercompare-charts` must be a SIBLING of the
    controls/leaderboard <section class="card">, not nested inside it -- a
    card nested inside another card still reads as one long panel (the
    outer card's own border/padding wraps both), which defeats "completely
    separate" the user asked for. The loader section must CLOSE before the
    charts div opens."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    section_close = body.index("</section>")
    charts_div = body.index('id="playercompare-charts"')
    assert section_close < charts_div


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
    """No mocked profile data -> player_field_compare fails (network-blocked
    in tests) -> the no-table fallback path (see the two tests below), which
    still renders both the radar and the trend PNGs, just as two stacked
    chart cards instead of the table-embedded layout."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two")
    body = resp.body.decode()
    assert "/chart/player_overlay" in body
    assert "mode=snapshot" in body
    assert "mode=trend" in body


def test_playercompare_chart_section_both_charts_default_to_per_game():
    """Both the radar and the trend line open on "Per game" by default (user
    request) -- the radar's own initial <img> src and its "Per game" pill
    must both start selected, not "Total"."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two")
    body = resp.body.decode()
    assert "mode=snapshot&stat_mode=per_game" in body
    assert "mode=trend&stat_mode=per_game" in body
    # The one shared rail's "Per game" pill starts .on, "Total" does not.
    rail = body.split('data-stat-mode-rail="both"')[1].split("</nav>")[0]
    assert 'class="year on" data-stat-mode="per_game"' in rail
    assert 'class="year" data-stat-mode="total"' in rail


def test_playercompare_chart_section_results_are_their_own_card():
    """The comparison output lives in its OWN <section class="card">,
    separate from the leaderboard/controls card in _playercompare_compare.html
    (that card is not part of this fragment at all -- this fragment starts
    fresh with its own section)."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two")
    body = resp.body.decode()
    assert body.strip().startswith('<section class="card">')


def test_playercompare_chart_section_no_table_falls_back_to_stacked_cards():
    """Without a 2-player metric table (3+ players, or a profile that never
    resolved), the radar and trend charts fall back to their own stacked
    .card.chart figures -- no `.grid two` side-by-side layout anymore (that
    was an earlier session's layout; the table now replaces it for the
    2-player case), and no `wide` class forcing either into its own row.
    Also no `.compare-header-row` (the portrait+radar strip only exists
    alongside the table)."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2,3", player_labels="A,B,C")
    body = resp.body.decode()
    assert 'class="compare-table"' not in body
    assert "compare-header-row" not in body
    assert 'class="grid two"' not in body
    assert "card chart wide" not in body
    assert body.count("card chart") == 2


def test_playercompare_chart_section_one_shared_rail_drives_both_charts():
    """Only ONE .rail exists (data-stat-mode-rail="both"), not two separate
    per-chart rails -- and its JS updates every img[data-chart], not just one
    keyed chart, so a single click moves both charts together."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two")
    body = resp.body.decode()
    assert body.count('<nav class="rail"') == 1
    assert 'data-stat-mode-rail="both"' in body
    assert "imgs.forEach" in body


def test_playercompare_chart_section_two_players_renders_metric_table(monkeypatch):
    """The 3-column comparison table only builds for exactly 2 players, keyed
    off the same player_field_compare() profiles the radar chart itself
    reads -- so the table's numbers always agree with what the radar plots."""
    from webapp import app, player_compare as pc

    profiles = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
            {"key": "rush_yd", "label": "Rush yds", "value": 90.0, "percentile": 55.0},
        ]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
            {"key": "rush_yd", "label": "Rush yds", "value": 110.0, "percentile": 70.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    assert "compare-table" in body
    assert "Player A" in body and "Player B" in body
    assert "PPR pts" in body and "Rush yds" in body
    assert "22" in body and "18" in body
    assert "80.0%" in body and "60.0%" in body


def test_playercompare_chart_section_metric_table_shows_headshots(monkeypatch):
    """The header row carries each player's Sleeper headshot, linked to their
    profile page -- `pid_a`/`pid_b` are the real Sleeper player_ids already
    in `player_ids` (this whole tab forces source="sleeper"), not a
    separately resolved id."""
    from webapp import app, player_compare as pc

    profiles = {
        "4046": {"player_id": "4046", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
        ]},
        "4239": {"player_id": "4239", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="4046,4239", player_labels="Player A,Player B")
    body = resp.body.decode()
    assert body.count("pface") == 2
    assert "https://sleepercdn.com/content/nfl/players/4046.jpg" in body
    assert "https://sleepercdn.com/content/nfl/players/4239.jpg" in body
    assert '/player/4046' in body
    assert '/player/4239' in body


def test_playercompare_chart_section_metric_table_tints_the_better_side(monkeypatch):
    """Whichever side has the higher percentile at a stat gets the green
    dv-pos tint, the other gets red dv-neg -- comparing PERCENTILE, not raw
    value, since a lower-is-better stat (e.g. points allowed) already has
    that direction baked into its percentile."""
    from webapp import app, player_compare as pc

    profiles = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
        ]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    row = body.split('id="compare-table-body"')[1].split("</tbody>")[0]
    cells = row.split("<td")
    assert "dv-pos" in cells[1]
    assert "dv-neg" in cells[3]


def test_playercompare_chart_section_header_row_is_outside_the_table(monkeypatch):
    """Regression test for a real, shipped bug: the portrait+radar header
    used to live INSIDE the comparison table's own <thead> as a <th> with
    `display: flex` -- flex on a table cell pulls it OUT of the table's
    column-sizing algorithm entirely (a flex container sizes to its own
    content, ignoring `table-layout: fixed`'s computed column width), which
    rendered the header ~3x narrower than the body cells in the same column,
    with the portraits both squeezed AND not aligned to their column.

    The fix moves the whole header (portrait | radar | portrait) OUT of the
    table into its own `.compare-header-row` flex strip ABOVE it -- this also
    doubles as the visibility improvement the user asked for separately
    (bigger portraits/radar with no table-column constraint at all). The
    table itself now has NO <thead>: `.compare-table` should contain no
    `<th>` at all, and `.compare-header-row` must appear BEFORE it in the
    document."""
    from webapp import app, player_compare as pc

    profiles = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
        ]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    assert "<thead>" not in body
    assert "<th" not in body
    header_idx = body.index("compare-header-row")
    table_idx = body.index('class="compare-table"')
    assert header_idx < table_idx
    # Portrait+name sides flank the radar in the header row.
    assert body.count("compare-header-side") == 2
    a_idx = body.index("compare-header-side")
    radar_idx = body.index("compare-header-radar")
    b_idx = body.rindex("compare-header-side")
    assert a_idx < radar_idx < b_idx
    assert "mode=snapshot" in body
    assert ">Metric<" not in body


def test_playercompare_chart_section_header_row_portraits_are_enlarged():
    """The comparison view's whole point (per user request) is a more
    visible portrait/radar row -- guard the actual enlarged .pface override
    exists, is MEANINGFULLY bigger than the shared base size (not pinned to
    one exact px value, which would make this test fragile against future
    size tweaks), and is scoped to this row, not a change to the shared
    .pface base rule used everywhere else in the app."""
    import re
    from webapp import app
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index(".compare-header-side .pface {")
    block = css[idx:css.index("}", idx)]
    override_px = int(re.search(r"width:\s*(\d+)px", block).group(1))
    # The shared BARE base rule (used elsewhere, e.g. dense inline tables)
    # must stay untouched -- search line-anchored (`\n.pface {`) so this
    # doesn't match a scoped override like `.nfl-cmp .pface { width: 16px;
    # ... }` earlier in the file.
    base_idx = css.index("\n.pface {") + 1
    base_block = css[base_idx:css.index("}", base_idx)]
    base_px = int(re.search(r"width:\s*(\d+)px", base_block).group(1))
    assert base_px == 22
    assert override_px >= base_px * 2


def test_playercompare_chart_section_trend_chart_sits_below_table(monkeypatch):
    """The trend line renders AFTER (below) the comparison table, not beside
    it -- the table is the primary/centerpiece view now."""
    from webapp import app, player_compare as pc

    profiles = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
        ]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    table_idx = body.index("compare-table")
    trend_idx = body.index('data-chart="trend"')
    assert table_idx < trend_idx


def test_playercompare_chart_section_script_does_not_use_current_script():
    """Regression test for a real, shipped bug caught only by a live browser
    check (not by any earlier automated test): `document.currentScript` is
    NOT reliably set when a <script> tag is re-executed via htmx's
    allowScriptTags mechanism (how this whole script runs at all, since it
    arrives via an innerHTML swap rather than the initial page parse) -- it
    was `null` on every real load, so `document.currentScript.closest(...)`
    threw `Cannot read properties of null` immediately, silently breaking
    the ENTIRE toggle handler (both the chart-image rewrite AND the new
    table-refresh fetch) with no visible error to a user just looking at the
    page. Confirmed via Playwright's console/pageerror listeners against a
    real server, not assumed from reading the code. The fix scopes off the
    stable `#playercompare-charts` id instead."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="A,B")
    body = resp.body.decode()
    # Explanatory comments are allowed to MENTION document.currentScript
    # (see this very docstring) -- what must never come back is the actual
    # broken usage pattern, `.closest(` called directly on it.
    assert "document.currentScript.closest(" not in body
    assert "getElementById('playercompare-charts')" in body


def test_playercompare_chart_section_toggle_refreshes_table_via_htmx(monkeypatch):
    """Regression test for a real, user-reported bug: clicking the Total/Per
    game toggle used to only rewrite the chart <img> src's `stat_mode` query
    param -- the table's values/percentiles are server-rendered, so they
    silently never changed on toggle. The fix wires the same click handler
    to also htmx-fetch `/playercompare/table?...&stat_mode=<mode>` and swap
    it into `#compare-table-body`. Guard the wiring is actually present:
    the table body has the right id, and the click handler references both
    the table URL and htmx.ajax targeting that id."""
    from webapp import app, player_compare as pc

    profiles = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0},
        ]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0},
        ]},
    }
    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: profiles)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    assert 'id="compare-table-body"' in body
    assert "/playercompare/table?" in body
    assert "htmx.ajax" in body
    assert "target: tableBody" in body
    assert "stat_mode=' + mode" in body


def test_playercompare_table_route_reflects_stat_mode(monkeypatch):
    """The new /playercompare/table route (the toggle's own refresh target)
    actually passes stat_mode through to player_field_compare, so a
    Total-mode fetch reads different values than a Per-game one."""
    from webapp import app, player_compare as pc

    seen_modes = []

    def _fake(season, pos, ids, **k):
        seen_modes.append(k.get("stat_mode"))
        return {
            "1": {"player_id": "1", "columns": [
                {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0}]},
            "2": {"player_id": "2", "columns": [
                {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0}]},
        }
    monkeypatch.setattr(pc, "player_field_compare", _fake)
    resp = app.playercompare_table(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B", stat_mode="total")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert seen_modes == ["total"]
    assert "22.5" in body and "18.0" in body
    assert "PPR pts" in body


def test_playercompare_table_route_has_no_table_wrapper_or_header():
    """The /playercompare/table route returns ONLY <tr> rows -- no <table>,
    no <thead>, no header/portrait markup -- since it's swapped into an
    EXISTING <tbody> in place, and the header row lives outside the table
    entirely now (see the header-row-is-outside-the-table test above)."""
    from webapp import app, player_compare as pc

    monkeypatch_targets = {
        "1": {"player_id": "1", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 22.5, "percentile": 80.0}]},
        "2": {"player_id": "2", "columns": [
            {"key": "fpts_ppr", "label": "PPR pts", "value": 18.0, "percentile": 60.0}]},
    }
    import unittest.mock
    with unittest.mock.patch.object(pc, "player_field_compare",
                                    lambda season, pos, ids, **k: monkeypatch_targets):
        resp = app.playercompare_table(
            _Req(), position="RB", season="2024",
            player_ids="1,2", player_labels="Player A,Player B", stat_mode="per_game")
    body = resp.body.decode()
    assert "<table" not in body
    assert "<thead" not in body
    assert "compare-header" not in body
    assert "<tr>" in body


def test_playercompare_table_route_invalid_stat_mode_falls_back_to_per_game():
    from webapp import app
    resp = app.playercompare_table(
        _Req(), position="RB", season="2024",
        player_ids="", player_labels="", stat_mode="bogus")
    assert resp.status_code == 200


def test_playercompare_chart_section_three_players_skips_metric_table(monkeypatch):
    from webapp import app, player_compare as pc

    def _boom(*a, **k):
        raise AssertionError("player_field_compare should not be called for 3+ players")
    monkeypatch.setattr(pc, "player_field_compare", _boom)
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2,3", player_labels="A,B,C")
    body = resp.body.decode()
    assert 'class="compare-table"' not in body


def test_playercompare_chart_section_metric_table_degrades_on_missing_profile(monkeypatch):
    """A player with no leaderboard row (percentile_profile returns None)
    must not crash the fragment -- the table is simply omitted."""
    from webapp import app, player_compare as pc

    monkeypatch.setattr(pc, "player_field_compare",
                        lambda season, pos, ids, **k: {"1": None, "2": None})
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B")
    body = resp.body.decode()
    assert resp.status_code == 200
    assert 'class="compare-table"' not in body


def test_chart_player_overlay_snapshot_title_names_the_players(monkeypatch):
    """The radar chart has no legend (see plots.py's own snapshot branch) --
    the title must name every selected player directly ("A vs B") instead,
    built from `player_labels`, so a reader never needs a legend lookup."""
    from sleepermetrics import plots
    from webapp import app, player_compare as pc

    captured = {}

    def _spy(players, stat_keys, **kw):
        captured.update(kw)
        return plots._no_data("stub")
    monkeypatch.setattr(plots, "plot_player_overlay", _spy)
    monkeypatch.setattr(pc, "player_field_compare", lambda season, pos, ids, **k: {
        "1": {"player_id": "1", "columns": []}, "2": {"player_id": "2", "columns": []}})
    app.chart("player_overlay", position="RB", season="2024", mode="snapshot",
             player_ids="1,2", player_labels="Christian McCaffrey,Jonathan Taylor")
    assert captured.get("title") == "Christian McCaffrey vs Jonathan Taylor"


def test_chart_player_overlay_is_league_free_no_pick_needed(monkeypatch):
    """The player_overlay branch must dispatch BEFORE pick() -- calling it
    with no real league must not hit the network-dependent pick() path at
    all (mirrors the existing PLAYER_CHARTS/player_radar precedent)."""
    from webapp import app, player_compare as pc

    def _boom_pick(*a, **k):
        raise AssertionError("pick() should not be called for player_overlay")
    monkeypatch.setattr(app, "pick", _boom_pick)
    monkeypatch.setattr(pc, "player_field_compare", lambda season, pos, ids, **k: {
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
