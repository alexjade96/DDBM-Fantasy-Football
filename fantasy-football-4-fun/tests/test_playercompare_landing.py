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
    """A "Reset" button (id/class playercompare-clear -- internal name
    unchanged, only the visible label is "Reset") lets a user uncheck every
    currently-picked row in one click, instead of scrolling the leaderboard
    to find and manually uncheck each one (user request). It must be
    VISIBLE (never `hidden`) as soon as the board loads, same as Compare --
    both render immediately, just non-clickable (`disabled`) until 2+ rows
    are checked (user request). Its click handler must uncheck every box
    and re-sync the counter/button state."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert 'id="playercompare-clear-btn"' in body
    assert "Reset" in body
    clear_btn = body[body.index('id="playercompare-clear-btn"') - 60:
                     body.index('id="playercompare-clear-btn"') + 100]
    assert "hidden" not in clear_btn
    assert "disabled" in clear_btn
    assert "clearBtn.onclick" in body
    assert "b.checked = false" in body


def test_playercompare_shell_clear_button_gated_on_same_threshold_as_compare():
    """Regression test: Reset must become clickable at the SAME
    checked-count threshold as Compare (n >= 2), never a looser one -- user
    asked explicitly that neither button work without the other. Both
    buttons render immediately on board load (never `hidden` -- an earlier
    version hid them until 2+ checked, popping them into the layout late;
    a later version hid Compare only when the board was completely empty
    while Reset stayed hidden until 2+ checked, so the two disagreed on
    when to even appear); now both are always visible and only their
    `disabled` state -- driven by the SAME `usable` variable -- changes."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert "var usable = n >= 2;" in body
    idx = body.index("btn.disabled")
    line = body[idx:body.index(";", idx)]
    assert "!usable" in line
    idx = body.index("clearBtn.disabled")
    line = body[idx:body.index(";", idx)]
    assert "!usable" in line


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
    """Regression test: Reset/Compare must stay pushed to the controls row's
    RIGHT edge (user request) even though Load moved to the left. Promoted
    from the Testing tab's "grouped controls" demo (prototype #3): the
    controls now read as two GROUPS (filters, actions) separated by a
    divider, and `.playercompare-group-actions` (not an individual button's
    own margin) carries the `margin-left: auto` that pushes the whole
    Reset+Compare group to the right edge."""
    from webapp import app
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index(".playercompare-group-actions {")
    block = css[idx:css.index("}", idx)]
    assert "margin-left: auto" in block
    body = app.playercompare(_Req()).body.decode()
    assert 'class="playercompare-group playercompare-group-actions"' in body
    # Reset/Compare must both be INSIDE that actions group in the markup.
    grp_idx = body.index('class="playercompare-group playercompare-group-actions"')
    grp_end = body.index('</div>', grp_idx)
    grp_block = body[grp_idx:grp_end]
    assert 'id="playercompare-clear-btn"' in grp_block
    assert 'id="playercompare-compare-btn"' in grp_block


def test_playercompare_shell_controls_are_grouped_with_a_divider():
    """Regression test: filters (Position/Season/Load) and actions
    (Reset/Compare) sit in separate `.playercompare-group` sub-rows with a
    `.playercompare-group-divider` between them, promoted from the Testing
    tab's "grouped controls" demo, prototype #3 (user request)."""
    from webapp import app
    body = app.playercompare(_Req()).body.decode()
    assert 'class="playercompare-group playercompare-group-filters"' in body
    assert 'class="playercompare-group-divider"' in body
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".playercompare-group-divider {" in css


def test_playercompare_shell_clear_precedes_compare_in_source_order():
    """Regression test: Reset must appear BEFORE Compare
    in the rendered markup, so it sits to Compare's LEFT (user request)."""
    from webapp import app
    resp = app.playercompare(_Req())
    body = resp.body.decode()
    assert body.index('id="playercompare-clear-btn"') < \
        body.index('id="playercompare-compare-btn"')


def test_playercompare_shell_row_highlight_wired_in_sync():
    """Promoted from the Testing tab's "row highlight on check" demo
    (prototype #2, user request): a checked leaderboard row gets a tinted
    background. Must be driven from sync() itself (not just the checkbox's
    own `change` listener), since Reset sets `checked = false` directly
    without dispatching a `change` event -- if the highlight toggle only
    lived in the `change` handler, Reset would leave stale highlights on
    every row it cleared."""
    from webapp import app
    body = app.playercompare(_Req()).body.decode()
    assert "playercompare-row-picked" in body
    sync_idx = body.index("var sync = function ()")
    sync_end = body.index("};", sync_idx)
    sync_block = body[sync_idx:sync_end]
    assert "playercompare-row-picked" in sync_block
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert "#playercompare-board tr.playercompare-row-picked" in css


def test_playercompare_shell_chip_strip_wired_in_sync():
    """Promoted from the Testing tab's "chip strip" demo (prototype #1,
    user request): a small pill per checked leaderboard row renders below
    the board, with an x to uncheck. Must be driven from sync() itself
    (same reasoning as the row-highlight promotion), so Reset's direct
    `checked = false` (no `change` event) still clears the strip. The
    strip sits BELOW the board, not tied to Reset/Compare's own position
    in the controls row (the "agnostic to the table" placement the demo
    settled on)."""
    from webapp import app
    body = app.playercompare(_Req()).body.decode()
    assert 'id="playercompare-chip-strip"' in body
    strip_marker = body.index('id="playercompare-chip-strip"')
    assert "hidden" in body[strip_marker - 10:strip_marker + 40]
    sync_idx = body.index("var sync = function ()")
    sync_end = body.index("};", sync_idx)
    sync_block = body[sync_idx:sync_end]
    assert "chipStrip" in sync_block
    assert "playercompare-chip" in sync_block
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".playercompare-chips {" in css
    assert ".playercompare-chip {" in css
    assert ".playercompare-chip-x {" in css


def test_playercompare_shell_chip_strip_sits_below_the_board():
    """Regression test: the chip strip must appear AFTER `#playercompare-
    board` in source order (below it), not interleaved with or above the
    controls row -- Reset/Compare stay in the fixed controls row regardless
    of the chip strip's own presence."""
    from webapp import app
    body = app.playercompare(_Req()).body.decode()
    board_idx = body.index('id="playercompare-board"')
    strip_idx = body.index('id="playercompare-chip-strip"')
    assert board_idx < strip_idx


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


def _profiles(*specs):
    """{"1": profile, ...} from (pid, [(key, label, value, pct), ...]) specs."""
    return {pid: {"player_id": pid, "columns": [
        {"key": k, "label": l, "value": v, "percentile": pc} for k, l, v, pc in cols]}
        for pid, cols in specs}


def _patch_profiles(monkeypatch, profiles):
    from webapp import player_compare as pc
    monkeypatch.setattr(pc, "player_field_compare", lambda season, pos, ids, **k: profiles)


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


def test_playercompare_chart_section_no_profiles_shows_charts_without_matrix():
    """When no profile resolved (network blocked in tests) there is no matrix,
    but the radar still renders in its centered slot and the trend chart is the
    only `.card.chart`; no side-by-side grid, no `wide` card."""
    from webapp import app
    resp = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2,3", player_labels="A,B,C")
    body = resp.body.decode()
    assert 'class="compare-table"' not in body
    assert body.count('class="compare-header-radar"') == 1
    assert "compare-header-row" not in body
    assert 'class="grid two"' not in body
    assert "card chart wide" not in body
    assert body.count("card chart") == 1


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


def test_matrix_marks_the_best_value_and_tints_by_percentile(monkeypatch):
    """The higher percentile in a row is the lead (filled pill) and leans green,
    the lowest leans red, comparing PERCENTILE not raw value, since a
    lower-is-better stat already has its direction baked in."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("fpts_ppr", "PPR pts", 22.5, 80.0)]),
        ("2", [("fpts_ppr", "PPR pts", 18.0, 30.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B").body.decode()
    row = body.split('id="compare-table-body"')[1].split("</tbody>")[0]
    cells = row.split("<td")[1:]
    assert "compare-lead" in cells[0] and "compare-lead" not in cells[1]
    assert "heat-pos" in cells[0] and "heat-neg" in cells[1]


def test_matrix_header_carries_the_portraits_and_the_radar_sits_above(monkeypatch):
    """Portraits and names are the matrix's own column headers (one <th> per
    player, pinned on top), and the radar is centered ABOVE the table, not
    flanked by portraits (the old 2-player header row is gone)."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("fpts_ppr", "PPR pts", 22.5, 80.0)]),
        ("2", [("fpts_ppr", "PPR pts", 18.0, 60.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Player A,Player B").body.decode()
    head = body.split("<thead>")[1].split("</thead>")[0]
    assert head.count('class="compare-player"') == 2
    assert "pface" in head and "Player A" in head and "Player B" in head
    assert "compare-header-row" not in body and "compare-header-side" not in body
    assert body.index('class="compare-header-radar"') < body.index('class="compare-table"')
    assert "mode=snapshot" in body


def test_matrix_portraits_are_enlarged_and_scoped():
    """Header portraits are meaningfully bigger than the shared inline .pface
    (22px) and the override is scoped to the matrix, not the shared rule."""
    import re
    from webapp import app
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    idx = css.index(".compare-table .compare-player .pface {")
    block = css[idx:css.index("}", idx)]
    assert int(re.search(r"width:\s*(\d+)px", block).group(1)) >= 44
    base_idx = css.index("\n.pface {") + 1
    base_block = css[base_idx:css.index("}", base_idx)]
    assert int(re.search(r"width:\s*(\d+)px", base_block).group(1)) == 22


def test_matrix_css_scrolls_and_pins_header_and_stat_column():
    """A wide comparison scrolls sideways inside its own box with the stat
    names pinned; sticky cells need an opaque background and
    `border-collapse: separate` (collapsed borders do not travel with them)."""
    from webapp import app
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    box = css[css.index(".compare-matrix-scroll {"):]
    box = box[:box.index("}")]
    assert "overflow-x: auto" in box          # sideways scroll
    assert "max-height" not in box            # every row shows: no vertical scroll
    table = css[css.index(".compare-table {"):]
    table = table[:table.index("}")]
    assert "border-collapse: separate" in table and "min-width" in table
    head = css[css.index(".compare-table thead th {"):]
    assert "position: sticky" in head[:head.index("}")]
    metric = css[css.index(".compare-table th.compare-metric {"):]
    metric = metric[:metric.index("}")]
    assert "position: sticky" in metric and "left: 0" in metric and "background-color" in metric
    sel = css[css.index(".compare-table tr.compare-selected td"):]
    assert "background-image" in sel[:sel.index("}")]


def test_matrix_is_kept_out_of_the_shared_table_sorter(monkeypatch):
    """table-sort.js binds every `#panel table` that is not inside `.nosort`;
    the matrix header cells are players, not sortable columns."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("fpts_ppr", "PPR pts", 22.5, 80.0)]),
        ("2", [("fpts_ppr", "PPR pts", 18.0, 60.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="A,B").body.decode()
    wrapper = body[:body.index('class="compare-table"')]
    assert "compare-matrix-scroll nosort" in wrapper


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


def test_three_players_get_a_matrix_with_three_columns(monkeypatch):
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rush_yards", "Rush yds", 90.0, 55.0)]),
        ("2", [("rush_yards", "Rush yds", 110.0, 70.0)]),
        ("3", [("rush_yards", "Rush yds", 70.0, 40.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2,3", player_labels="A,B,C").body.decode()
    head = body.split("<thead>")[1].split("</thead>")[0]
    assert head.count('class="compare-player"') == 3
    assert "--n: 3" in body
    row = body.split('id="compare-table-body"')[1].split("</tbody>")[0]
    assert row.count("<td") == 3
    assert row.count("compare-lead") == 1             # only the 70th percentile leads
    assert row.split("<td")[2].count("compare-lead") == 1


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


# -- loading indicators ---------------------------------------------------------

def test_home_has_the_progress_bar_every_request_uses():
    """The landing page needs #bar plus hx-indicator on the body: the only CSS
    tied to a request in flight is `#bar.htmx-request`, so without them every
    tab switch / Load / Compare / Search ran with nothing visible."""
    from webapp import app
    body = app.home(_Req(), user="").body.decode()
    assert '<body hx-indicator="#bar">' in body
    assert '<div id="bar"></div>' in body
    assert 'id="load-status"' in body


def test_home_elapsed_pill_waits_before_showing_and_self_heals():
    from webapp import app
    body = (app.BASE / "templates" / "home.html").read_text(encoding="utf-8")
    assert "SHOW_AFTER_MS" in body            # a fast swap must not flash it
    assert "htmx-request" in body             # self-heal keys off the real request class
    assert "a[download]" in body              # file downloads get a notice too


def test_playercompare_toggle_shows_skeleton_and_dims_the_table():
    """Flipping Total / Per game re-renders the PNGs and the table, so both
    show a loading state until the new content lands."""
    from webapp import app
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2024",
        player_ids="1,2", player_labels="Test RB,Test RB Two").body.decode()
    assert "classList.add('skeleton')" in body
    assert "tableBody.style.opacity" in body


# -- trend metric selector: click a table row to chart that stat ----------------

def _two_profiles(monkeypatch):
    from webapp import player_compare as pc
    cols = lambda a, b, c: [
        {"key": "rush_yards", "label": "Rush yds", "value": a, "percentile": 55.0},
        {"key": "snap_share", "label": "Snap share", "value": b, "percentile": 70.0},
        {"key": "fpts_ppr", "label": "PPR pts", "value": c, "percentile": 80.0}]
    monkeypatch.setattr(pc, "player_field_compare", lambda season, pos, ids, **k: {
        "1": {"player_id": "1", "columns": cols(90.0, 0.7, 22.0)},
        "2": {"player_id": "2", "columns": cols(110.0, 0.6, 18.0)}})


def test_metric_table_rows_with_a_weekly_series_are_clickable(monkeypatch):
    from webapp import app
    _two_profiles(monkeypatch)
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="Player A,Player B").body.decode()
    assert 'data-trend-stat="rush_yards"' in body
    assert 'class="compare-clickable"' in body
    # a rate (snap share) and fantasy points have no weekly series: plain rows
    assert 'data-trend-stat="snap_share"' not in body
    assert 'data-trend-stat="fpts_ppr"' not in body
    assert "Click a stat to chart it week by week" in body
    assert 'id="trend-stat-select"' not in body            # the dropdown is only for 3+ players


def test_metric_table_refresh_route_keeps_rows_clickable(monkeypatch):
    from webapp import app
    _two_profiles(monkeypatch)
    body = app.playercompare_table(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="A,B", stat_mode="total").body.decode()
    assert 'data-trend-stat="rush_yards"' in body


def test_three_players_have_clickable_rows_not_a_dropdown(monkeypatch):
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rush_yards", "Rush yds", 90.0, 55.0)]),
        ("2", [("rush_yards", "Rush yds", 110.0, 70.0)]),
        ("3", [("rush_yards", "Rush yds", 70.0, 40.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2,3",
        player_labels="A,B,C").body.decode()
    assert 'data-trend-stat="rush_yards"' in body
    assert 'id="trend-stat-select"' not in body


def test_matrix_ties_and_missing_values(monkeypatch):
    """All-equal rows lead nobody; tied best values all lead; a player with no
    value for a stat gets a dash cell and the row still renders."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rush_yards", "Rush yds", 90.0, 60.0), ("snap_share", "Snap share", 0.5, 50.0),
               ("rush_td", "Rush TD", 2.0, 70.0)]),
        ("2", [("rush_yards", "Rush yds", 91.0, 60.0), ("snap_share", "Snap share", 0.6, 80.0)]),
        ("3", [("rush_yards", "Rush yds", 70.0, 60.0), ("snap_share", "Snap share", 0.6, 80.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2,3",
        player_labels="A,B,C").body.decode()
    rows = body.split('id="compare-table-body"')[1].split("</tbody>")[0].split("</tr>")
    by_label = {r.split('class="compare-metric">')[1].split("<")[0]: r
                for r in rows if "compare-metric" in r}
    assert "compare-lead" not in by_label["Rush yds"]            # all equal percentile
    assert by_label["Snap share"].count("compare-lead") == 2     # tied best
    assert "compare-missing" in by_label["Rush TD"]
    assert by_label["Rush TD"].count("compare-lead") == 0        # one value only


def test_matrix_rows_follow_the_radars_grouped_order(monkeypatch):
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("snap_share", "Snap share", 0.5, 50.0), ("receptions", "Rec", 3.0, 60.0),
               ("rush_yards", "Rush yds", 90.0, 55.0)]),
        ("2", [("snap_share", "Snap share", 0.6, 80.0), ("receptions", "Rec", 4.0, 70.0),
               ("rush_yards", "Rush yds", 80.0, 45.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="A,B").body.decode()
    labels = [x.split("<")[0] for x in body.split('class="compare-metric">')[1:]]
    assert labels == ["Rush yds", "Rec", "Snap share"]     # RB: rushing, receiving, usage


def test_selected_row_is_marked_and_survives_the_table_refresh(monkeypatch):
    """The script marks the clicked row `compare-selected`, clears it on a
    second click, and re-applies the mark after a Total/Per game swap."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rush_yards", "Rush yds", 90.0, 55.0)]),
        ("2", [("rush_yards", "Rush yds", 110.0, 70.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="A,B").body.decode()
    assert "compare-selected" in body
    assert "setTrendStat(s === trendStat ? '' : s)" in body
    assert "tableBody.style.opacity = ''; markTrend();" in body


def test_charts_script_binds_the_row_click_to_the_fragment_not_the_persistent_root():
    """#playercompare-charts persists across Compare clicks, so a listener bound
    there would be added again each time and a row would toggle twice."""
    from webapp import app
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2,3",
        player_labels="A,B,C").body.decode()
    assert "root.querySelector('section.card')" in body
    assert "card.addEventListener('click'" in body
    assert "root.addEventListener('click'" not in body


def test_chart_trend_stat_requests_that_weekly_key_zero_filled(monkeypatch):
    from webapp import app, player_compare as pc
    seen = {}

    def _trend(ids, season, position=None, stat_keys=None, weeks=None, zero_fill=False):
        seen.update(stat_keys=stat_keys, zero_fill=zero_fill)
        return {"1": [{"week": 1, "rush_yd": 80.0}, {"week": 2, "rush_yd": 0.0}]}
    monkeypatch.setattr(pc, "player_trend", _trend)
    resp = app.chart("player_overlay", position="RB", season="2025", mode="trend",
                     player_ids="1", player_labels="Test RB", trend_stat="rush_yards")
    assert resp.status_code == 200 and resp.media_type == "image/png"
    assert seen == {"stat_keys": ["rush_yd"], "zero_fill": True}


@pytest.mark.parametrize("bad", [None, "", "bogus", "snap_share", "fpts_ppr"])
def test_chart_unknown_or_unchartable_trend_stat_falls_back_to_ppr_points(monkeypatch, bad):
    from webapp import app, player_compare as pc
    seen = {}

    def _trend(ids, season, position=None, stat_keys=None, weeks=None, zero_fill=False):
        seen.update(stat_keys=stat_keys, zero_fill=zero_fill)
        return {"1": [{"week": 1, "pts_ppr": 10.0}]}
    monkeypatch.setattr(pc, "player_trend", _trend)
    resp = app.chart("player_overlay", position="RB", season="2025", mode="trend",
                     player_ids="1", player_labels="Test RB", trend_stat=bad)
    assert resp.status_code == 200
    assert seen == {"stat_keys": None, "zero_fill": False}      # the default key set, no zero fill



def _cells_of(body, label):
    rows = body.split('id="compare-table-body"')[1].split("</tbody>")[0].split("</tr>")
    row = [r for r in rows if f'class="compare-metric">{label}<' in r][0]
    return row.split("<td")[1:]


def test_matrix_tint_is_relative_to_the_players_in_the_row(monkeypatch):
    """Best leans green, worst leans red, a middle player is neutral-ish (the
    smallest tint), and the strength follows how far apart the players are:
    close values give a faint tint, wide gaps a strong one.  All-equal rows
    and single-value rows get no tint at all."""
    import re
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rush_yards", "Rush yds", 90.0, 99.0), ("rush_td", "Rush TD", 1.0, 97.0),
               ("carries", "Car", 10.0, 60.0), ("targets", "Tgt", 5.0, 50.0)]),
        ("2", [("rush_yards", "Rush yds", 70.0, 60.0), ("rush_td", "Rush TD", 1.0, 96.0),
               ("carries", "Car", 10.0, 60.0)]),
        ("3", [("rush_yards", "Rush yds", 50.0, 20.0), ("rush_td", "Rush TD", 0.0, 95.0),
               ("carries", "Car", 10.0, 60.0)])))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2,3",
        player_labels="A,B,C").body.decode()
    amt = lambda cell: int(re.search(r"--h: (\d+)%", cell).group(1))
    wide = _cells_of(body, "Rush yds")
    assert "heat-pos" in wide[0] and "heat-neg" in wide[2]
    assert amt(wide[1]) <= 2 and amt(wide[0]) >= 20 and amt(wide[2]) >= 20   # middle ~neutral
    close = _cells_of(body, "Rush TD")                                        # 95 to 97
    assert amt(close[0]) < amt(wide[0]) / 2                                   # faint when close
    equal = _cells_of(body, "Car")
    assert all("heat-" not in c and amt(c) == 0 for c in equal)
    single = _cells_of(body, "Tgt")
    assert "heat-" not in single[0]


def test_matrix_per_game_values_show_decimals_but_totals_and_shares_do_not(monkeypatch):
    """Per game, rec TD is 0.12 and 0.25 a game, not "0" and "0" (the whole-
    number format made rows of identical zeros carry different tints).  Totals
    stay whole numbers and share stats keep their 3-decimal form."""
    from webapp import app
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rec_td", "Rec TD", 0.12, 84.8), ("yds", "Yds", 36.24, 90.0),
               ("snap_share", "Snap share", 0.83, 98.0)]),
        ("2", [("rec_td", "Rec TD", 0.25, 94.6), ("yds", "Yds", 30.5, 80.0),
               ("snap_share", "Snap share", 0.78, 96.0)])))
    per_game = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="A,B").body.decode()
    rec = _cells_of(per_game, "Rec TD")
    assert ">0.12<" in rec[0] and ">0.25<" in rec[1]
    assert ">36.2<" in "".join(_cells_of(per_game, "Yds")) and ">30.5<" in "".join(_cells_of(per_game, "Yds"))
    assert ">0.830<" in _cells_of(per_game, "Snap share")[0]
    _patch_profiles(monkeypatch, _profiles(
        ("1", [("rec_td", "Rec TD", 7.0, 100.0)]), ("2", [("rec_td", "Rec TD", 4.0, 95.9)])))
    total = app.playercompare_table(
        _Req(), position="RB", season="2025", player_ids="1,2",
        player_labels="A,B", stat_mode="total").body.decode()
    assert ">7<" in total and ">4<" in total and "7.0" not in total


# -- the player cap (a trial value; one constant) ----------------------------------

def test_split_picks_trims_to_the_cap():
    from webapp import app
    cap = app._PLAYERCOMPARE_MAX
    ids = ",".join(str(i) for i in range(cap + 3))
    labels = ",".join(f"P{i}" for i in range(cap + 3))
    got_ids, got_labels = app._split_picks(ids, labels)
    assert len(got_ids) == cap and len(got_labels) == cap
    assert got_ids == [str(i) for i in range(cap)]
    assert app._split_picks("", "") == ([], [])


def test_compare_request_over_the_cap_renders_only_the_cap(monkeypatch):
    """A hand-edited URL with more ids than the cap still gets the cap's worth
    of matrix columns, and the charts' urls carry only those ids."""
    from webapp import app
    cap = app._PLAYERCOMPARE_MAX
    ids = [str(i) for i in range(1, cap + 3)]
    _patch_profiles(monkeypatch, _profiles(
        *[(i, [("rush_yards", "Rush yds", 50.0 + int(i), 40.0 + int(i))]) for i in ids]))
    body = app.playercompare_chart_section(
        _Req(), position="RB", season="2025", player_ids=",".join(ids),
        player_labels=",".join(f"P{i}" for i in ids)).body.decode()
    head = body.split("<thead>")[1].split("</thead>")[0]
    assert head.count('class="compare-player"') == cap
    assert f"P{cap + 1}" not in body
    refreshed = app.playercompare_table(
        _Req(), position="RB", season="2025", player_ids=",".join(ids),
        player_labels=",".join(f"P{i}" for i in ids), stat_mode="total").body.decode()
    assert refreshed.split("</tr>")[0].count("<td") == cap


def test_page_locks_unticked_boxes_at_the_cap():
    """The shell reads the cap from the server (one number), disables the
    unticked boxes at the cap and shows a note; a ticked box is never locked."""
    from webapp import app
    body = app.playercompare(_Req()).body.decode()
    assert f'data-max="{app._PLAYERCOMPARE_MAX}"' in body
    assert 'id="playercompare-cap-note"' in body
    assert "b.disabled = atCap && !b.checked" in body
    css = (app.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".playercompare-row-locked" in css
