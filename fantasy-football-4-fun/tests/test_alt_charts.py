"""Network-free tests for the Player Analytics chart prototypes (webapp/alt_charts.py and
GET /testing/altcharts).  The builders are pure, so they are checked on their markup."""
from __future__ import annotations

import re

import pandas as pd
import pytest
from starlette.requests import Request

from webapp import alt_analytics as aa
from webapp import alt_charts as ac


def _req(query: bytes = b""):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                    "query_string": query, "server": ("x", 80), "scheme": "http"})


def test_sparkline_draws_one_line_and_marks_the_last_point():
    svg = ac.sparkline([1, 3, 2, 5])
    assert svg.count("<polyline") == 1 and svg.count("<circle") == 1
    pts = re.search(r'points="([^"]+)"', svg).group(1).split()
    assert len(pts) == 4
    ys = [float(p.split(",")[1]) for p in pts]
    assert ys[3] == min(ys) and ys[0] > ys[1]            # the biggest value is the highest point


def test_sparkline_breaks_at_a_missing_value_and_needs_two_values():
    svg = ac.sparkline([1, 2, None, 4, 5])
    assert svg.count("<polyline") == 2                   # a gap, not a line through nothing
    assert ac.sparkline([3]) == "" and ac.sparkline([None, None]) == "" and ac.sparkline([]) == ""
    assert ac.sparkline([2, 2, 2]).count("<polyline") == 1      # a flat series does not divide by zero


def test_hbars_scale_to_the_largest_and_skip_a_missing_value():
    svg = ac.hbars([("Cover 1", 100.0, "100"), ("Cover 3", 50.0, "50"), ("Cover 6", None, "-")])
    widths = [float(w) for w in re.findall(r'<rect[^>]* width="([\d.]+)"', svg)]
    assert len(widths) == 2 and abs(widths[1] / widths[0] - 0.5) < 0.01
    assert "Cover 6" in svg and ac.hbars([("A", 0, "0")]) == "" and ac.hbars([]) == ""


def test_hbars_escape_the_labels():
    assert "&lt;b&gt;" in ac.hbars([("<b>", 1.0, "1")]) and "<b>" not in ac.hbars([("<b>", 1.0, "1")])


def test_series_chart_bars_start_at_zero_and_a_gap_has_no_bar():
    svg = ac.series_chart(["2020", "2021", "2022"], [4.0, None, 8.0], "bar")
    heights = [float(h) for h in re.findall(r'<rect[^>]* height="([\d.]+)"', svg)]
    assert len(heights) == 2 and abs(heights[0] / heights[1] - 0.5) < 0.01   # honest: 4 is half of 8
    assert "2021" in svg                                  # the label stays, the bar does not


def test_series_chart_line_breaks_at_a_gap_and_rejects_an_unknown_kind():
    svg = ac.series_chart(["a", "b", "c", "d", "e"], [1.0, 2.0, None, 3.0, 4.0], "line")
    assert svg.count("<polyline") == 2 and svg.count("<circle") == 4
    with pytest.raises(ValueError):
        ac.series_chart(["a"], [1.0], "pie")
    assert ac.series_chart(["a", "b"], [None, None], "bar") == ""


def _games():
    return aa.add_derived(pd.DataFrame({
        "player_id": "00-1", "player_display_name": "A B", "position": "WR", "team": "DET",
        "season": [2020, 2020, 2021, 2021, 2022, 2022], "week": [1, 2] * 3,
        "opponent": ["X", "Y", "X", "Z", "Y", "Z"], "home_away": ["Home", "Away"] * 3,
        "game_type": ["REG"] * 6, "carries": [0] * 6, "rushing_yards": [0] * 6,
        "rushing_tds": [0] * 6, "receptions": [2, 3, 5, 6, 8, 9],
        "targets": [4, 5, 8, 9, 12, 13], "receiving_yards": [20, 30, 60, 70, 110, 120],
        "receiving_tds": [0, 0, 1, 0, 1, 1], "receiving_air_yards": [30.0] * 6,
        "fantasy_points_ppr": [4.0, 6.0, 12.0, 13.0, 21.0, 24.0]}))


def test_prototypes_use_the_cards_data(monkeypatch):
    g = _games()
    p = ac.prototypes(g, "WR")
    seasons = aa.run_card(g, "WR", "workload", {})
    assert [c["label"] for c in p["spark"]["columns"]] == [c["label"] for c in seasons["columns"]]
    assert all(c["spark"].startswith("<svg") for c in p["spark"]["columns"])
    assert len(p["spark"]["view"]["rows"]) == 3
    assert p["series"]["bar"].count("<rect") == 3 and p["series"]["line"].count("<circle") == 3
    assert p["share"] is None                                  # no pass-play table in the fixture


def test_prototypes_degrade_to_none_without_data_or_seasons():
    assert ac.prototypes(pd.DataFrame(), "WR") == {"spark": None, "share": None, "series": None}
    assert ac.prototypes(None, "WR")["series"] is None
    one = _games().iloc[:2].copy()                             # a single season: no trend to draw
    assert ac.prototypes(one, "WR")["spark"] is None


@pytest.fixture
def _routes(monkeypatch):
    from webapp import app as A
    g = _games()
    hit = {"player_id": "00-1", "name": "A B", "position": "WR", "team": "DET",
           "first_season": 2020, "last_season": 2022, "games": 6}
    monkeypatch.setattr(aa, "search_players", lambda q, limit=12: [hit] if q == "ab" else [])
    monkeypatch.setattr(aa, "load_player", lambda pid: g if pid == "00-1" else pd.DataFrame())
    return A


def test_testing_route_renders_the_three_prototypes(_routes):
    html = _routes.testing_altcharts(_req(), q="ab").body.decode()
    assert "A B" in html and "1. Sparkline under each column" in html
    assert 'class="alt-spark"' in html and "3. Targets /g by season" in html
    assert 'data-pane="bar"' in html and 'data-pane="line"' in html
    assert ">nan<" not in html.lower()


def test_testing_route_handles_no_match_and_an_empty_query(_routes):
    assert 'No player matches "zzz"' in _routes.testing_altcharts(_req(), q="zzz").body.decode()
    assert "alt-proto-grid" not in _routes.testing_altcharts(_req(), q="").body.decode()


def test_testing_tab_has_the_prototype_form():
    from webapp import app as A
    html = (A.BASE / "templates" / "tab_testing.html").read_text(encoding="utf-8")
    assert 'hx-get="/testing/altcharts"' in html and 'id="alt-proto-out"' in html


# -- the Chart view of a card ----------------------------------------------------------------

def _result(rows, group="season", agg="per_game", keys=("targets", "catch_rate")):
    return {"columns": [{"key": k, "label": aa.MEASURES[k]} for k in keys],
            "rows": [{"group": g, "games": 16, **v} for g, v in rows], "total": None,
            "games": 16 * len(rows),
            "spec": {"group_by": group, "agg": agg, "measures": list(keys), "filters": {}}}


def test_a_line_fits_its_own_range_but_bars_start_at_zero():
    line = ac.series_chart(["a", "b", "c"], [5.0, 7.0, 10.0], "line")
    ticks = [float(t) for t in re.findall(r'text-anchor="end"[^>]*>([\d.]+)<', line)]
    assert min(ticks) > 0 and max(ticks) > 10                       # fitted, not from zero
    bar = ac.series_chart(["a", "b", "c"], [5.0, 7.0, 10.0], "bar")
    bticks = [float(t) for t in re.findall(r'text-anchor="end"[^>]*>([\d.]+)<', bar)]
    assert min(bticks) == 0.0                                       # a bar axis includes zero
    zero = ac.series_chart(["a", "b"], [5.0, 7.0], "line", fit=False)
    assert min(float(t) for t in re.findall(r'text-anchor="end"[^>]*>([\d.]+)<', zero)) == 0.0


def test_x_labels_are_thinned_so_they_do_not_overlap():
    labels = [str(y) for y in range(2000, 2026)]
    svg = ac.series_chart(labels, list(range(26)), "bar", width=280, height=150)
    shown = re.findall(r'text-anchor="middle"[^>]*>(\d{4})<', svg)
    assert 0 < len(shown) < 14 and shown[0] == "2000"             # first kept, others skipped
    few = ac.series_chart(["2020", "2021", "2022"], [1, 2, 3], "bar", width=280, height=150)
    assert len(re.findall(r'text-anchor="middle"', few)) == 3       # nothing dropped when there is room


def test_season_card_is_one_chart_with_a_line_per_stat():
    rows = [(2020, {"targets": 8.0, "catch_rate": 70.0}), (2021, {"targets": 9.0, "catch_rate": 68.0}),
            (2022, {"targets": 7.5, "catch_rate": None})]
    ch = ac.card_charts(_result(rows))
    assert ch["kind"] == "series" and ch["svg"].count("<svg") == 1            # one chart, not one per stat
    assert [l["label"] for l in ch["legend"]] == ["Targets", "Catch %"]
    assert ch["svg"].count('class="alt-s"') == 2 and ch["svg"].count("<polyline") == 2
    assert ch["svg"].count("<circle") == 5                                    # the gap draws no point
    assert [l["color"] for l in ch["legend"]] == ac.PALETTE[:2]





def test_card_charts_are_none_without_two_rows_or_two_recorded_values():
    assert ac.card_charts(_result([(2020, {"targets": 8.0})])) is None
    assert ac.card_charts(_result([(2020, {"targets": 8.0}), (2021, {"targets": None})],
                                  keys=("targets",))) is None
    assert ac.card_charts(_result([("A", {"targets": 0.0}), ("B", {"targets": 0.0})],
                                  group="opponent", agg="total", keys=("targets",))) is None


def test_missing_values_are_gaps_in_the_card_charts():
    rows = [("A", {"targets": 5.0}), ("B", {"targets": None}), ("C", {"targets": 3.0})]
    ch = ac.card_charts(_result(rows, group="opponent", agg="total", keys=("targets",)))
    assert ch["svg"].count('<rect class="bar"') == 2                 # no zero bar for B
    assert "B" in ch["svg"]                                           # the row label stays


def test_card_body_has_a_table_chart_toggle_and_both_views(_routes):
    html = _routes.alt_card(_req(), player_id="00-1", card="workload").body.decode()
    assert 'class="alt-views"' in html and 'data-view="table"' in html and 'data-view="chart"' in html
    assert re.search(r'<div class="alt-view-pane alt-chart-pane" data-view="chart" hidden>', html)
    assert html.index('class="alt-view-pane" data-view="table"') < html.index("alt-chart-pane")
    assert html.count('class="alt-multi"') == 1 and 'class="alt-leg"' in html   # one chart and a legend
    assert 'class="alt-mini"' not in html and "alt-chart-stat" not in html     # no chart per stat, no picker
    assert "percent of its own average" in html or "own average" in html or "All stats share one axis" in html
    opp = _routes.alt_card(_req(), player_id="00-1", card="by_opponent").body.decode()
    assert "alt-gbars" in opp and ("percent of its own average" in opp or "All stats share one axis" in opp)
    assert 'class="alt-aggs"' in opp and 'data-agg="total"' in opp and 'data-agg="per_game"' in opp


def test_a_card_with_one_row_has_no_toggle(_routes):
    html = _routes.alt_card(_req(b"measures=targets"), player_id="00-1", card="custom").body.decode()
    assert 'data-state="ok"' in html and "alt-views" not in html and "alt-chart-pane" not in html


def test_page_script_switches_views_in_the_browser_and_remembers_them(_routes):
    page = _routes.alt_builder(_req(), q="ab", player_id="00-1", run=0, measures=[], agg="total",
                               group_by="", opponent="", season_from="", season_to="",
                               home_away="", game_types=[]).body.decode()
    assert "function showView(el, view)" in page and "window.altViews" in page
    assert "applyView(el);" in page                                  # re-applied when a card loads
    assert "closest('.alt-leg')" in page and "toggle('alt-off', off)" in page   # the legend switches a stat
    assert "alt-chart-stat" not in page
    assert "function emphasise(e, on)" in page and "'alt-dim'" in page   # hover follows one stat
    from webapp import app as A
    assert "g.alt-s.alt-dim { opacity" in (A.BASE / "static" / "style.css").read_text(encoding="utf-8")


def test_long_category_labels_fit_and_the_chart_pane_is_not_clipped():
    svg = ac.hbars([("Shallow cross/drag", 35.0, "35"), ("Swing", 3.0, "3")])
    x = float(re.search(r'<text x="([\d.]+)" y="[\d.]+" text-anchor="end"', svg).group(1))
    assert x >= 120                                           # room for ~18 characters at 12px
    from webapp import app as A
    css = (A.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".alt-chart-pane {" not in css                     # a clipped pane hid the last row of small charts


# -- the integrated charts -----------------------------------------------------------------------

def _stat(key, label, vals):
    from webapp import alt_analytics as aa
    return {"key": key, "label": label, "values": vals, "fmt": lambda v, k=key: aa.format_value(k, v)}


def test_stats_of_similar_size_share_one_axis_in_their_own_units():
    ch = ac.multi_line(["2020", "2021", "2022"],
                       [_stat("targets", "Targets /g", [8.0, 9.0, 10.0]),
                        _stat("receptions", "Rec /g", [5.0, 6.0, 7.0])])
    assert ch["mode"] == "shared"
    ticks = re.findall(r'text-anchor="end"[^>]*>([^<]+)<', ch["svg"])
    assert "low" not in ticks and "high" not in ticks               # real numbers on the axis
    ys = {k: [float(y) for y in re.findall(r'<circle cx="[\d.]+" cy="([\d.]+)"', g)]
          for k, g in zip("ab", re.findall(r'<g class="alt-s".*?</g>', ch["svg"]))}
    assert ys["a"][0] < ys["b"][0]                                   # 8 sits above 5 on the same axis





def test_multi_line_leaves_out_a_stat_with_one_value_and_needs_two_points():
    ch = ac.multi_line(["a", "b", "c"], [_stat("targets", "Targets", [1.0, 2.0, 3.0]),
                                         _stat("receptions", "Rec", [None, None, 4.0])])
    assert [l["label"] for l in ch["legend"]] == ["Targets"]
    assert ac.multi_line(["a"], [_stat("targets", "Targets", [1.0])]) is None
    assert ac.multi_line(["a", "b"], [_stat("targets", "Targets", [None, None])]) is None


def test_multi_line_tooltips_carry_the_real_value_and_a_gap_breaks_the_line():
    ch = ac.multi_line(["2020", "2021", "2022", "2023", "2024"],
                       [_stat("targets", "Targets", [8.0, 9.0, None, 7.0, 6.0])])
    assert "2021: Targets 9" in ch["svg"] and ch["svg"].count("<polyline") == 2





def test_grouped_bars_are_none_without_a_positive_value():
    assert ac.multi_bars(["A", "B"], [_stat("targets", "Targets", [0.0, None])]) is None
    assert ac.multi_bars([], [_stat("targets", "Targets", [])]) is None


def test_compact_axis_numbers():
    assert [ac._compact(v) for v in (0, 7.5, 10, 999, 1000, 1250, 1776, 12000)] == \
        ["0", "7.5", "10", "999", "1k", "1.2k", "1.8k", "12k"]


# -- round ticks, value labels, shared bar axis -----------------------------------------------

def test_nice_ticks_are_round_and_cover_the_range():
    assert ac._nice_ticks(0, 97) == [0, 25, 50, 75, 100]
    assert ac._nice_ticks(3.4, 10.2)[0] <= 3.4 and ac._nice_ticks(3.4, 10.2)[-1] >= 10.2
    assert ac._nice_ticks(0, 1.0) == [0, 0.25, 0.5, 0.75, 1.0]
    assert ac._tick_decimals([0, 0.25, 0.5]) == 2 and ac._tick_decimals([0, 5, 10]) == 0


def test_shared_axis_lines_have_round_ticks_and_end_values():
    ch = ac.multi_line(["2020", "2021", "2022"], [_stat("targets", "Targets /g", [8.3, 9.1, 10.2]),
                                                  _stat("receptions", "Rec /g", [5.0, 6.0, 7.4])],
                       x_title="Season")
    ticks = [float(t.replace(",", "")) for t in re.findall(r'text-anchor="end"[^>]*>([\d.,]+)<', ch["svg"])]
    assert len(ticks) >= 4 and all(abs(t * 2 - round(t * 2)) < 1e-6 for t in ticks)   # steps of 0.5 or more
    assert "Season" in ch["svg"]
    assert "10.2" in ch["svg"] and "7.4" in ch["svg"]                                   # last values written out


def test_a_lone_line_labels_every_point():
    ch = ac.multi_line(["a", "b", "c"], [_stat("targets", "Targets", [4.0, 6.0, 5.0])])
    assert len(re.findall(r'text-anchor="middle"[^>]*fill="#[0-9a-f]+">', ch["svg"])) == 2   # the last is the end label


def test_end_labels_never_sit_closer_than_the_gap():
    ys = ac._spread_labels([(100.0, 0), (101.0, 1), (102.0, 2)], 0, 300)
    vals = sorted(ys.values())
    assert all(b - a >= 12.5 - 1e-9 for a, b in zip(vals, vals[1:]))


def test_bars_of_similar_stats_share_an_axis_and_every_bar_has_its_value():
    ch = ac.multi_bars(["Short", "A very long opponent name here"],
                       [_stat("targets", "Targets", [10.0, 5.0]), _stat("receptions", "Rec", [8.0, 4.0])],
                       x_title="Opponent", games=[3, 2])
    assert ch["mode"] == "shared" and 'class="trk"' not in ch["svg"]
    w = [float(x) for x in re.findall(r'<rect class="bar"[^>]* width="([\d.]+)"', ch["svg"])]
    assert abs(w[0] / w[2] - 10 / 8) < 0.01                                             # one scale for both stats
    assert "Opponent" in ch["svg"] and "(2 games)" in ch["svg"]
    assert "A very long opponent name here" in ch["svg"] and "…" in ch["svg"]            # shortened, full in tooltip
    assert ch["svg"].count('font-size="11" fill="currentColor"') + ch["svg"].count('font-size="10" fill="currentColor"') >= 4
    assert 'class="band"' in ch["svg"]




# -- index lines, bar axes, one stat at a time ---------------------------------------------------

def test_stats_of_different_size_are_drawn_as_percent_of_their_own_average():
    ch = ac.multi_line(["2020", "2021", "2022"],
                       [_stat("receiving_yards", "Rec yds", [900.0, 1100.0, 1300.0]),
                        _stat("receiving_tds", "Rec TD", [3.0, 9.0, 6.0])], x_title="Season")
    assert ch["mode"] == "index"
    assert not {">low<", ">mid<", ">high<"} & set(re.findall(r">[a-z]+<", ch["svg"]))
    ticks = re.findall(r'text-anchor="end"[^>]*>([\d,.]+%)<', ch["svg"])
    assert len(ticks) >= 4 and "100%" in ticks                       # real percent ticks, 100 is the average
    assert "% of own average" in ch["svg"] and "stroke-dasharray" in ch["svg"]
    assert [l["note"] for l in ch["legend"]] == ["900 to 1,300", "3 to 9"]   # the real range stays in the legend
    assert "1,300" in ch["svg"] and "(" in ch["svg"] and "% of his average" in ch["svg"]  # real value and index in tips


def test_a_stat_whose_average_is_not_positive_is_left_out_of_an_index_chart():
    ch = ac.multi_line(["a", "b", "c"], [_stat("receiving_yards", "Rec yds", [900.0, 1100.0, 1300.0]),
                                         _stat("net", "Net", [-5.0, 1.0, -2.0])])
    assert ch is not None and [l["label"] for l in ch["legend"]] == ["Rec yds"]


def test_stats_of_similar_size_are_one_bar_chart_on_a_shared_axis():
    rows = [(f"T{i}", {"targets": float(10 + i), "receptions": float(6 + i)}) for i in range(5)]
    ch = ac.card_charts(_result(rows, group="opponent", agg="total", keys=("targets", "receptions")))
    assert ch["kind"] == "bars" and ch["mode"] == "shared" and "alt-yl" not in ch["svg"]
    assert ch["svg"].count('class="alt-s"') == 2 and "Targets / Rec" in ch["svg"]


def test_every_stat_is_drawn_together_even_when_the_sizes_differ_and_rows_are_many():
    rows = [(f"T{i:02d}", {"targets": i / 2, "catch_rate": 50.0 + (i * 7) % 23}) for i in range(1, 31)]
    ch = ac.card_charts(_result(rows, group="opponent", agg="total"))
    assert ch["mode"] == "index" and ch["shown"] == ch["of"] == 30 and "panes" not in ch
    assert ch["svg"].count('class="alt-s"') == 2 and len(ch["legend"]) == 2     # both stats, one chart
    labels = re.findall(r'text-anchor="end"[^>]*><title>(T\d+)', ch["svg"])
    assert len(labels) == 30 and labels[0] == "T30"                              # every opponent, ranked by the first stat
    assert ch["svg"].count('class="bar"') == 60                                  # a bar per stat in every row
    assert "stroke-dasharray" in ch["svg"] and "% of each stat" in ch["svg"]    # the average line and a neutral axis


def test_an_index_chart_swaps_the_axis_to_each_stats_own_units():
    ch = ac.multi_bars(["A", "B", "C"], [_stat("receiving_yards", "Rec yds", [1000.0, 500.0, 250.0]),
                                         _stat("receiving_tds", "Rec TD", [4.0, 2.0, 1.0])])
    assert ch["mode"] == "index"
    sets = re.findall(r'<g class="alt-yl[^"]*"[^>]*>.*?</g>', ch["svg"])
    assert len(sets) == 3                                                         # the neutral set, then one per stat
    assert "alt-yl-def" in sets[0] and "%" in sets[0] and 'data-ys="0"' in sets[1] and 'data-ys="1"' in sets[2]
    assert "Rec yds" in sets[1] and "Rec TD" in sets[2]                           # each set is titled by its stat
    assert "%" not in re.sub(r"<title>.*?</title>", "", sets[1])                  # real units, not percents
    first = [t for t in re.findall(r">([\d,.]+)<", sets[1])]
    second = [t for t in re.findall(r">([\d,.]+)<", sets[2])]
    assert first != second and len(first) == len(second) >= 4                    # the same ticks, written per stat


def test_a_line_chart_axis_starts_neutral_and_carries_each_stats_units():
    ch = ac.multi_line(["2020", "2021", "2022"],
                       [_stat("receiving_yards", "Rec yds", [900.0, 1100.0, 1300.0]),
                        _stat("receiving_tds", "Rec TD", [3.0, 9.0, 6.0])])
    sets = re.findall(r'<g class="alt-yl[^"]*"[^>]*>.*?</g>', ch["svg"])
    assert len(sets) == 3 and "alt-yl-def" in sets[0] and 'data-ys="1"' in sets[2]
    assert "% of own average" in sets[0] and "Rec TD" in sets[2]
    shared = ac.multi_line(["a", "b"], [_stat("targets", "Targets", [8.0, 9.0]), _stat("receptions", "Rec", [5.0, 6.0])])
    assert "alt-yl" not in shared["svg"]                                          # a shared axis already is real units


def test_page_script_puts_the_hovered_stats_units_on_the_axis(_routes):
    page = _routes.alt_builder(_req(), q="ab", player_id="00-1", run=0, measures=[], agg="total",
                               group_by="", opponent="", season_from="", season_to="",
                               home_away="", game_types=[]).body.decode()
    assert "g.alt-yl[data-ys=" in page and "'alt-show'" in page and "'alt-hide'" in page
    assert "closest('g.alt-s')" in page                                           # hovering the line or bars works too
    assert "data-pick" not in page and "alt-one" not in page                      # no one-stat-at-a-time chart
    from webapp import app as A
    assert "g.alt-yl.alt-show" in (A.BASE / "static" / "style.css").read_text(encoding="utf-8")


def test_rows_beyond_the_cap_are_not_drawn_and_the_card_says_how_many():
    rows = [(f"T{i:02d}", {"targets": float(i)}) for i in range(1, 51)]
    ch = ac.card_charts(_result(rows, group="opponent", agg="total", keys=("targets",)))
    assert ch["shown"] == ac.MAX_BAR_ROWS == 40 and ch["of"] == 50


def test_bars_have_a_bottom_axis_with_round_ticks_and_a_title():
    ch = ac.multi_bars(["A", "B"], [_stat("receiving_yards", "Rec yds", [1000.0, 480.0])], x_title="Opponent",
                       games=[12, 3])
    svg = ch["svg"]
    ticks = [float(t.replace(",", "")) for t in re.findall(r'text-anchor="middle"[^>]*>([\d,.]+)<', svg)]
    assert ticks[0] == 0 and ticks == sorted(ticks) and ticks[-1] >= 1000
    assert "Rec yds" in svg and "Opponent" in svg                      # axis title and the grouping name
    assert "12 g" in svg and "(3 games)" in svg                        # the game count on the row


def test_one_axis_means_bar_length_follows_the_value_across_stats():
    ch = ac.multi_bars(["A", "B"], [_stat("receiving_yards", "Rec yds", [1000.0, 500.0]),
                                    _stat("receiving_tds", "Rec TD", [800.0, 400.0])])
    groups = re.findall(r'<g class="alt-s".*?</g>', ch["svg"])
    w = [[float(x) for x in re.findall(r'<rect class="bar"[^>]* width="([\d.]+)"', g)] for g in groups]
    assert abs(w[0][0] / w[1][0] - 1000 / 800) < 0.01 and abs(w[0][1] / w[0][0] - 0.5) < 0.01
    assert [l["note"] for l in ch["legend"]] == ["largest 1,000", "largest 800"]


def test_a_chart_scrolls_in_the_same_box_as_its_table(_routes):
    html = _routes.alt_card(_req(), player_id="00-1", card="workload").body.decode()
    assert re.search(r'<div class="alt-chart-scroll"><svg class="alt-multi"', html)    # the legend stays outside it
    assert html.index('class="alt-legend"') < html.index('class="alt-chart-scroll"')
    from webapp import app as A
    css = (A.BASE / "static" / "style.css").read_text(encoding="utf-8")
    table = re.search(r"\.alt-card-table \{ max-height: (\d+)px; overflow: auto;", css).group(1)
    chart = re.search(r"\.alt-chart-scroll \{ max-height: (\d+)px; overflow: auto;", css).group(1)
    assert table == chart                                                              # one height for both views
