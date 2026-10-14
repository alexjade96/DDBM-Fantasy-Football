"""Alternative Analytics engine and its Testing-tab routes.

Network-free: the player table is a small synthetic frame, and the loaders are
monkeypatched, so nothing reads data/sources/.
"""
import re

import pandas as pd
import pytest
from starlette.requests import Request

from webapp import alt_analytics as aa


def _games() -> pd.DataFrame:
    rows = [
        # season, week, type, opp, site, targets, rec, yds, td
        (2022, 1, "REG", "KC", "Home", 10, 7, 100, 1),
        (2022, 2, "REG", "LV", "Away", 5, 3, 40, 0),
        (2023, 1, "REG", "KC", "Away", 8, 4, 50, 0),
        (2023, 19, "WC", "KC", "Home", 12, 9, 120, 2),
        (2023, 22, "SB", "SF", "Neutral", 6, 5, 70, 0),
    ]
    return pd.DataFrame({
        "player_id": "00-1", "player_display_name": "A B", "position": "WR",
        "team": "DET",
        "season": [r[0] for r in rows], "week": [r[1] for r in rows],
        "game_type": [r[2] for r in rows], "opponent": [r[3] for r in rows],
        "home_away": [r[4] for r in rows], "targets": [r[5] for r in rows],
        "receptions": [r[6] for r in rows], "receiving_yards": [r[7] for r in rows],
        "receiving_tds": [r[8] for r in rows], "passing_yards": 0, "carries": 0,
        "rushing_yards": 0,
    })


def _spec(**kw):
    base = {"measures": ["targets", "receiving_yards"], "agg": "total",
            "filters": {}, "group_by": None}
    base.update(kw)
    return base


def test_career_totals_and_game_count():
    r = aa.run_query(_games(), _spec())
    row = r["rows"][0]
    assert row["games"] == 5 and row["targets"] == 41 and row["receiving_yards"] == 380


def test_filter_by_opponent_and_seasons():
    r = aa.run_query(_games(), _spec(filters={"opponent": "kc", "seasons": [2023, 2022]}))
    assert r["games"] == 3 and r["rows"][0]["receiving_yards"] == 270


def test_filter_by_home_away_and_game_type():
    assert aa.run_query(_games(), _spec(filters={"home_away": "Neutral"}))["games"] == 1
    post = aa.run_query(_games(), _spec(filters={"game_types": ["WC", "SB"]}))
    assert post["games"] == 2 and post["rows"][0]["targets"] == 18


def test_group_by_season_has_a_total_row():
    r = aa.run_query(_games(), _spec(group_by="season"))
    assert [(x["group"], x["games"]) for x in r["rows"]] == [(2022, 2), (2023, 3)]
    assert r["total"]["games"] == 5 and r["total"]["receiving_yards"] == 380


def test_group_by_game_type_is_in_round_order():
    r = aa.run_query(_games(), _spec(group_by="game_type"))
    assert [x["group"] for x in r["rows"]] == ["REG", "WC", "SB"]


def test_per_game_divides_counts_but_not_ratios():
    r = aa.run_query(_games(), _spec(measures=["receiving_yards", "catch_rate"],
                                     agg="per_game"))
    row = r["rows"][0]
    assert row["receiving_yards"] == pytest.approx(76.0)
    assert row["catch_rate"] == pytest.approx(28 / 41 * 100)     # same as in totals
    assert r["columns"][0]["label"].endswith("/g")
    assert not r["columns"][1]["label"].endswith("/g")


def test_ratios_are_sum_over_sum_not_a_mean_of_games():
    r = aa.run_query(_games(), _spec(measures=["yards_per_target"]))
    assert r["rows"][0]["yards_per_target"] == pytest.approx(380 / 41)


def test_ratio_with_a_zero_denominator_is_none():
    r = aa.run_query(_games(), _spec(measures=["yards_per_carry"]))
    assert r["rows"][0]["yards_per_carry"] is None


def test_no_matching_games_gives_no_rows():
    r = aa.run_query(_games(), _spec(filters={"opponent": "ZZZ"}))
    assert r["rows"] == [] and r["games"] == 0 and r["total"] is None


def test_empty_player_frame_is_safe():
    assert aa.run_query(pd.DataFrame(), _spec())["rows"] == []


@pytest.mark.parametrize("bad", [
    _spec(measures=["nope"]), _spec(measures=[]), _spec(agg="median"),
    _spec(group_by="player"), _spec(filters={"home_away": "Moon"}),
    _spec(filters={"game_types": ["XYZ"]}), _spec(filters={"seasons": [2020]}),
])
def test_spec_outside_the_menus_is_rejected(bad):
    with pytest.raises(ValueError):
        aa.run_query(_games(), bad)


def test_available_measures_hide_what_the_player_never_did():
    have = aa.available_measures(_games())
    assert "receiving_yards" in have and "yards_per_target" in have
    assert "passing_yards" not in have and "yards_per_carry" not in have


def test_default_measures_follow_position():
    g = _games()
    assert aa.default_measures("WR", g)[0] == "targets"
    assert "passing_yards" not in aa.default_measures("QB", g)     # none to show


def _rb_games() -> pd.DataFrame:
    g = _games()
    g["position"] = "RB"
    g["carries"] = [12, 15, 9, 20, 18]
    g["rushing_yards"] = [60, 80, 40, 110, 75]
    g["rushing_tds"] = [1, 0, 0, 2, 1]
    g["fantasy_points_ppr"] = [14.0, 9.5, 7.0, 25.0, 12.0]
    g["fantasy_points"] = [10.0, 7.0, 4.0, 19.0, 9.0]
    return g


def test_preset_fill_uses_the_builders_own_field_names():
    fill = aa.preset_fill("production", _games(), "WR")
    assert set(fill) == {"measures", "agg", "group_by", "opponent", "season_from",
                         "season_to", "home_away", "game_types", "shown"}


def test_presets_change_the_measure_checkboxes_not_just_the_grouping():
    g = _rb_games()
    sets = {p["id"]: tuple(aa.preset_fill(p["id"], g, "RB")["measures"]) for p in aa.PRESETS}
    assert sets["workload"] == ("carries", "targets", "receptions")
    assert sets["efficiency"] == ("yards_per_carry", "yards_per_reception", "catch_rate",
                                  "yards_per_target")
    assert sets["fantasy"] == ("fantasy_points_ppr", "fantasy_points")
    assert sets["production"] == ("rushing_yards", "receiving_yards", "rushing_tds",
                                  "receiving_tds")
    assert sets["playoffs"][-1] == "fantasy_points_ppr"       # PPR only, not standard
    assert len({v for v in sets.values()}) >= 6              # not eight copies of one list


def test_presets_change_show_and_the_grouping():
    g = _rb_games()
    fill = {p["id"]: aa.preset_fill(p["id"], g, "RB") for p in aa.PRESETS}
    assert fill["workload"]["agg"] == "per_game" and fill["production"]["agg"] == "total"
    assert fill["home_away"]["group_by"] == "home_away"
    assert fill["by_opponent"]["group_by"] == "opponent"
    assert fill["playoffs"]["group_by"] == "game_type"


def test_playoff_preset_ticks_the_playoff_game_types_only():
    assert aa.preset_fill("playoffs", _rb_games(), "RB")["game_types"] == ["WC", "DIV", "CON", "SB"]
    assert aa.preset_fill("workload", _rb_games(), "RB")["game_types"] == []


def test_recent_form_covers_the_last_three_seasons_and_never_before_the_first():
    short = _rb_games()                                    # 2022 to 2023 only
    assert aa.preset_fill("recent", short, "RB")["season_from"] == "2022"
    long = pd.concat([short.assign(season=2018), short], ignore_index=True)   # 2018 to 2023
    assert aa.preset_fill("recent", long, "RB")["season_from"] == "2021"      # 2023 - 2
    assert aa.preset_fill("workload", long, "RB")["season_from"] == ""


def test_measure_choices_follow_position_and_what_the_player_has():
    wr = aa.preset_fill("workload", _games(), "WR")["measures"]
    assert wr == ["targets", "receptions"]            # carries: the WR has none
    te = aa.preset_fill("production", _games(), "TE")["measures"]
    assert "rushing_yards" not in te and "receiving_yards" in te
    qb = aa.preset_fill("efficiency", _games(), "QB")["measures"]
    assert qb == aa.default_measures("QB", _games())  # nothing in the family: falls back


def test_every_preset_leaves_the_opponent_site_and_end_season_at_any():
    for p in aa.PRESETS:
        fill = aa.preset_fill(p["id"], _rb_games(), "RB")
        assert fill["opponent"] == "" and fill["home_away"] == "" and fill["season_to"] == ""


def test_preset_fill_is_a_valid_spec_for_every_preset_and_position():
    """Whatever a chip fills, running the form must not be rejected."""
    for pos, g in (("RB", _rb_games()), ("WR", _games()), ("TE", _games()), ("QB", _games())):
        for p in aa.PRESETS:
            f = aa.preset_fill(p["id"], g, pos)
            spec = {"measures": f["measures"], "agg": f["agg"],
                    "group_by": f["group_by"] or None,
                    "filters": {"game_types": f["game_types"] or None,
                                "seasons": [int(f["season_from"]), 2030] if f["season_from"] else None}}
            assert aa.run_query(g, spec)["spec"]["measures"]


def test_unknown_preset_is_rejected():
    with pytest.raises(ValueError):
        aa.preset_fill("nope", _games(), "WR")


def test_preset_chips_cover_every_preset():
    chips = aa.preset_chips(_games(), "WR")
    assert [c["id"] for c in chips] == [p["id"] for p in aa.PRESETS]
    assert all(c["label"] and c["fill"]["measures"] for c in chips)


def test_format_value():
    assert aa.format_value("targets", 1663.0) == "1,663"
    assert aa.format_value("receiving_yards", 76.5) == "76.5"
    assert aa.format_value("catch_rate", 72.34) == "72.3%"
    assert aa.format_value("yards_per_target", 8.8457) == "8.85"
    assert aa.format_value("targets", None) == "–"
    assert aa.format_value("targets", float("nan")) == "–"


def test_table_view_labels_and_total():
    r = aa.run_query(_games(), _spec(group_by="game_type"))
    v = aa.table_view(r)
    assert v["group_label"] == "Game type"
    assert [x["label"] for x in v["rows"]] == ["Regular season", "Wild card", "Super Bowl"]
    assert v["total"]["cells"][0] == "41"
    assert aa.table_view(aa.run_query(_games(), _spec()))["rows"][0]["label"] == "Career"


def test_coverage_reports_the_partial_latest_season():
    cov = aa.coverage(_games())
    assert (cov["first_season"], cov["last_season"], cov["last_week"]) == (2022, 2023, 22)


# -- player search and loading ---------------------------------------------------

@pytest.fixture
def _fake_table(monkeypatch):
    aa.clear_cache()
    frames = {
        "2022": pd.DataFrame({
            "player_id": ["00-1", "00-2"], "player_display_name": ["Justin Jefferson", "Van Jefferson"],
            "position": ["WR", "WR"], "team": ["MIN", "LA"], "season": [2022, 2022],
            "week": [1, 1], "targets": [9, 3]}),
        "2023": pd.DataFrame({
            "player_id": ["00-1"], "player_display_name": ["Justin Jefferson"],
            "position": ["WR"], "team": ["MIN"], "season": [2023], "week": [1], "targets": [8]}),
    }
    monkeypatch.setattr(aa, "seasons_available", lambda: [2022, 2023])
    monkeypatch.setattr(aa.nflref, "load", lambda name, season, **k: frames[season].copy())
    yield
    aa.clear_cache()


def test_search_finds_every_word_and_ranks_by_recency(_fake_table):
    hits = aa.search_players("jefferson")
    assert [h["name"] for h in hits] == ["Justin Jefferson", "Van Jefferson"]
    assert hits[0]["games"] == 2 and hits[0]["last_season"] == 2023
    assert [h["name"] for h in aa.search_players("justin jeff")] == ["Justin Jefferson"]


def test_search_needs_two_characters_and_handles_no_match(_fake_table):
    assert aa.search_players("j") == [] and aa.search_players("") == []
    assert aa.search_players("zzzz") == []


def test_load_player_returns_all_seasons_in_order(_fake_table):
    g = aa.load_player("00-1")
    assert g["season"].tolist() == [2022, 2023]
    assert aa.load_player("nobody").empty


# -- routes ----------------------------------------------------------------------

def _req(query: bytes = b""):
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                    "query_string": query, "server": ("x", 80), "scheme": "http"})


@pytest.fixture
def _routes(monkeypatch):
    from webapp import app as A
    g = _games()
    one = {"player_id": "00-1", "name": "A B", "position": "WR", "team": "DET",
           "first_season": 2022, "last_season": 2023, "games": 5}
    two = {"player_id": "00-2", "name": "A Bee", "position": "RB", "team": "KC",
           "first_season": 2020, "last_season": 2020, "games": 3}

    def search(q, limit=12):                 # "solo" has one match, other "a" names two
        return [one] if q == "solo" else ([one, two] if "a" in q else [])
    monkeypatch.setattr(aa, "search_players", search)
    monkeypatch.setattr(aa, "load_player", lambda pid: g if pid == "00-1" else pd.DataFrame())
    return A


def _builder(A, **kw):
    """Call the route function directly, giving the list arguments real values
    (FastAPI's Query defaults only resolve through the framework)."""
    args = {"q": "", "player_id": "", "run": 0, "measures": [], "agg": "total",
            "group_by": "", "opponent": "", "season_from": "", "season_to": "",
            "home_away": "", "game_types": []}
    query = kw.pop("_query", b"")
    args.update(kw)
    return A.alt_builder(_req(query), **args).body.decode()


def test_builder_route_search_lists_matches_and_loads_no_chips(_routes):
    html = _builder(_routes, q="ab")
    assert "A B" in html and "hx-vals" in html and "alt-chip" not in html


def test_chosen_player_shows_full_name_and_position_under_the_search_box(_routes):
    import re
    html = _builder(_routes, q="ab", player_id="00-1")
    assert re.search(r'<div class="alt-who"[^>]*>\s*<span class="alt-who-name">A B</span>\s*<span class="alt-who-meta">WR &middot; DET</span>', html)
    assert 'name="q" value="A B"' in html            # the box shows the full name, not the query


def test_search_box_keeps_the_typed_query_until_a_player_is_chosen(_routes):
    html = _builder(_routes, q="ab")
    assert 'name="q" value="ab"' in html and "alt-player" not in html


def test_unknown_player_shows_no_match_message(_routes):
    html = _builder(_routes, q="zzz", player_id="nobody")
    assert "No player matches" in html


def test_chips_carry_their_fill_and_send_no_request(_routes):
    import json, re
    html = _builder(_routes, q="ab", player_id="00-1")
    chips = re.findall(r"<button([^>]*class=\"alt-chip\"[^>]*)>", html)
    assert len(chips) == len(aa.PRESETS)
    for attrs in chips:
        assert "hx-" not in attrs and 'type="button"' in attrs   # filling is client-side only
    fills = [json.loads(re.search(r"data-fill='([^']*)'", a).group(1)) for a in chips]
    play = fills[[p["id"] for p in aa.PRESETS].index("playoffs")]
    assert play["group_by"] == "game_type" and play["game_types"] == ["WC", "DIV", "CON", "SB"]


def test_only_the_run_form_sends_a_request(_routes):
    import re
    html = _builder(_routes, q="ab", player_id="00-1")
    form = re.search(r'<form id="alt-builder-form"[^>]*>', html).group(0)
    assert 'hx-get="/altanalytics/builder"' in form


def test_builder_route_runs_the_spec_and_disables_unused_measures(_routes):
    html = _routes.alt_builder(_req(), q="ab", player_id="00-1", run=1,
                               measures=["receiving_yards"], agg="per_game",
                               group_by="season", opponent="", season_from="",
                               season_to="", home_away="", game_types=[]).body.decode()
    assert "Rec yds /g" in html
    # an unused measure stays in the form but is disabled, and is never a result column
    box = re.search(r'<input[^>]*value="passing_yards"[^>]*>', html, re.S).group(0)
    assert "disabled" in box
    assert '<th class="n">Pass yds' not in html


def test_builder_route_turns_a_bad_spec_into_a_message(_routes):
    html = _routes.alt_builder(_req(), q="ab", player_id="00-1", run=1,
                               measures=["x"], agg="total", group_by="", opponent="",
                               season_from="", season_to="", home_away="",
                               game_types=[]).body.decode()
    assert "unknown measure" in html


def test_results_never_render_nan(_routes):
    html = _routes.alt_builder(_req(), q="ab", player_id="00-1", run=1,
                               measures=["yards_per_carry"], agg="total", group_by="season",
                               opponent="", season_from="", season_to="", home_away="",
                               game_types=[]).body.decode()
    assert ">nan<" not in html.lower() and "–" in html


def test_grouped_measures_keep_every_measure_in_one_fixed_order():
    games = pd.DataFrame({"targets": [5, 6], "receptions": [3, 4], "receiving_yards": [40, 60],
                          "carries": [1, 0], "rushing_yards": [3, 0],
                          "fantasy_points_ppr": [9.0, 12.0]})
    order = ["Passing", "Rushing", "Receiving", "Kicking", "Fantasy"]
    for pos in ("WR", "RB", "QB", "K", None):          # the order never depends on the player
        assert [g["label"] for g in aa.grouped_measures(games, pos)] == order
    groups = aa.grouped_measures(games, "WR")
    keys = [k for g in groups for k, _, _ in g["items"]]
    assert set(keys) == set(aa.MEASURES)              # nothing hidden
    used = {k: u for g in groups for k, _, u in g["items"]}
    assert used["targets"] and used["rushing_yards"] and not used["passing_yards"]
    flags = {g["label"]: g["used"] for g in groups}    # a group is used when any measure is
    assert flags == {"Passing": False, "Rushing": True, "Receiving": True,
                     "Kicking": False, "Fantasy": True}
    empty = aa.grouped_measures(games.iloc[0:0], "WR")
    assert not any(g["used"] for g in empty)


def test_measure_groups_list_counts_then_rates_then_the_maximum():
    kick = dict(aa.MEASURE_GROUPS)["Kicking"]
    assert kick.index("fg_made") < kick.index("fg_pct") < kick.index("fg_long")
    assert kick.index("pat_missed") < kick.index("pat_pct")
    rec = dict(aa.MEASURE_GROUPS)["Receiving"]
    assert rec.index("receiving_air_yards") < rec.index("yards_per_target")


def _kicker_games():
    return pd.DataFrame({
        "season": [2024, 2024, 2025], "week": [1, 2, 1],
        "fg_att": [3, 2, 4], "fg_made": [2, 2, 3], "fg_long": [48, 52, 44],
        "pat_att": [2, 1, 3], "pat_made": [2, 1, 3],
        "fg_made_50_59": [0, 1, 0], "fg_missed": [1, 0, 1], "pat_missed": [0, 0, 0],
        "targets": [None, None, None], "opponent": ["X", "Y", "X"],
        "home_away": ["Home", "Away", "Home"], "game_type": ["REG"] * 3})


def test_kicker_measures_and_longest_field_goal():
    g = _kicker_games()
    have = aa.available_measures(g)
    assert {"fg_made", "fg_pct", "fg_long", "pat_pct", "fg_made_50_59"} <= set(have)
    assert "targets" not in have and "passing_yards" not in have
    r = aa.run_query(g, {"measures": ["fg_made", "fg_pct", "fg_long"], "agg": "total"})
    t = r["rows"][0]
    assert t["fg_made"] == 7 and t["fg_long"] == 52               # a maximum, not a sum
    assert abs(t["fg_pct"] - 7 / 9 * 100) < 1e-6
    assert aa.default_measures("K", g)[:2] == ["fg_made", "fg_att"]
    assert [x["label"] for x in aa.grouped_measures(g, "K") if x["used"]] == ["Kicking"]


def test_unrecorded_values_are_left_out_not_read_as_zero():
    g = pd.DataFrame({"season": [2006, 2010], "week": [1, 1],
                      "targets": [float("nan"), 10.0], "receptions": [5, 6],
                      "receiving_yards": [50, 70]})
    r = aa.run_query(g, {"measures": ["targets", "catch_rate"], "agg": "per_game",
                         "group_by": "season"})
    by = {row["group"]: row for row in r["rows"]}
    assert by[2006]["targets"] is None and by[2006]["catch_rate"] is None
    assert by[2010]["targets"] == 10.0
    career = aa.run_query(g, {"measures": ["targets", "catch_rate"], "agg": "per_game"})
    c = career["rows"][0]
    assert c["targets"] == 10.0                    # divided by the games that recorded it
    assert abs(c["catch_rate"] - 60.0) < 1e-6      # 6 of 10, not 11 of 10


def test_player_analytics_tab_renders_the_empty_builder(_routes):
    body = _routes.altanalytics(_req()).body.decode()
    assert 'id="alt-builder"' in body and 'name="q"' in body
    assert 'hx-get="/altanalytics/builder"' in body
    assert "alt-chip" not in body and "alt-group" not in body   # nothing until a search


def test_landing_nav_has_the_player_analytics_tab():
    from webapp import app as A
    home = (A.BASE / "templates" / "home.html").read_text(encoding="utf-8")
    assert 'hx-get="/altanalytics">Player Analytics<' in home
    assert home.index("Player Analytics") < home.index(">Testing<")


def test_search_results_are_rows_with_position_team_seasons_and_games(_routes):
    html = _builder(_routes, q="ab")
    assert 'class="alt-matches"' in html
    assert html.count('class="alt-match"') == 2                  # one row per match
    row = re.search(r'<button[^>]*class="alt-match"[^>]*>(.*?)</button>', html, re.S).group(1)
    for text in ("A B", "WR", "DET", "2022 to 2023", ">5<"):
        assert text in row
    assert "2020 to 2020" not in html and "<span>2020</span>" in html   # a single season reads as one year
    assert "2 matches" in html


def test_a_search_with_one_match_goes_straight_to_the_player(_routes):
    html = _builder(_routes, q="solo")
    assert 'class="alt-matches"' not in html
    assert "alt-who" in html and "alt-chip" in html              # the builder is already open



def test_every_measure_has_a_hover_hint():
    assert set(aa.MEASURE_HINTS) == set(aa.MEASURES)
    assert all(aa.MEASURE_HINTS[k].strip() for k in aa.MEASURES)
    assert "maximum" in aa.MEASURE_HINTS["fg_long"]
    assert {p["id"] for p in aa.PRESETS} == set(aa.PRESET_HINTS)


def test_hints_reach_the_page_for_measures_chips_and_controls(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    assert f'title="{aa.MEASURE_HINTS["targets"]}"' in html
    unused = re.search(r'<label class="adp-check alt-unused"\s+title="([^"]*)"', html).group(1)
    assert unused.endswith("No production for this player.")     # definition first, then the note
    chips = re.findall(r'class="alt-chip" title="([^"]*)"', html)
    assert len(chips) == len(aa.PRESETS) and all(chips)
    for key in ("agg", "group_by", "opponent", "home_away", "season_from", "season_to", "game_types"):
        assert f'title="{aa.CONTROL_HINTS[key]}"' in html


# -- search paging and sorting --------------------------------------------------

def _roster(n=30):
    """n players with varied positions, teams, seasons and games, and some ties."""
    pos = ["WR", "QB", "K", "RB", "TE", "FB", "P"]
    return [{"player_id": f"00-{i:02d}", "name": f"Smith {chr(65 + i % 26)}{i}",
             "position": pos[i % len(pos)], "team": ["DET", "KC", "BAL"][i % 3],
             "first_season": 2010 + i % 5, "last_season": 2015 + i % 7,
             "games": 10 + (i % 4) * 20} for i in range(n)]


@pytest.fixture
def _many(monkeypatch):
    rows = _roster()
    monkeypatch.setattr(aa, "search_players", lambda q, limit=None: list(rows))
    return rows


def test_search_page_cuts_pages_without_dropping_anyone(_many):
    seen = []
    first = aa.search_page("smith")
    assert first["total"] == 30 and first["pages"] == 3 and first["page"] == 1
    assert (first["first"], first["last"]) == (1, 12)
    for n in (1, 2, 3):
        pg = aa.search_page("smith", page=n)
        seen += [r["player_id"] for r in pg["rows"]]
    assert sorted(seen) == sorted(r["player_id"] for r in _many)     # everyone, once
    last = aa.search_page("smith", page=3)
    assert (last["first"], last["last"]) == (25, 30) and len(last["rows"]) == 6
    assert aa.search_page("smith", page=99)["page"] == 3             # out of range clamps
    assert aa.search_page("smith", page=0)["page"] == 1


def test_search_page_defaults_to_most_recent_season_then_games_then_name(_many):
    pg = aa.search_page("smith")
    assert (pg["sort"], pg["direction"]) == ("seasons", "desc")
    keys = [(r["last_season"], r["first_season"]) for r in pg["rows"]]
    assert keys == sorted(keys, reverse=True)
    junk = aa.search_page("smith", sort="nonsense", direction="sideways")
    assert (junk["sort"], junk["direction"]) == ("seasons", "desc")


def test_search_sort_covers_the_whole_set_before_paging(_many):
    ordered = []
    for n in (1, 2, 3):
        ordered += aa.search_page("smith", sort="games", direction="desc", page=n)["rows"]
    games = [r["games"] for r in ordered]
    assert games == sorted(games, reverse=True)                      # page 2 continues page 1


def test_search_sort_ties_never_move(_many):
    a = aa.search_page("smith", sort="team", direction="asc", page=1)["rows"]
    b = aa.search_page("smith", sort="team", direction="asc", page=1)["rows"]
    assert [r["player_id"] for r in a] == [r["player_id"] for r in b]
    same_team = [r for r in a if r["team"] == a[0]["team"]]
    keys = [(-r["games"], r["name"].casefold()) for r in same_team]
    assert keys == sorted(keys)                                      # games desc, then name A to Z
    desc = aa.search_page("smith", sort="name", direction="desc")["rows"]
    assert [r["name"].casefold() for r in desc] == sorted([r["name"].casefold() for r in desc],
                                                          reverse=True)


def test_search_position_sort_follows_fantasy_order_not_the_alphabet(_many):
    order = []
    for n in (1, 2, 3):
        order += [r["position"] for r in aa.search_page("smith", sort="position",
                                                         direction="asc", page=n)["rows"]]
    firsts = list(dict.fromkeys(order))
    assert firsts == ["QB", "RB", "FB", "WR", "TE", "K", "P"]


def test_each_column_starts_in_its_natural_direction(_many):
    assert aa.search_page("smith", sort="name")["direction"] == "asc"
    assert aa.search_page("smith", sort="games")["direction"] == "desc"
    assert aa.search_page("smith", sort="seasons")["direction"] == "desc"


def test_results_page_has_sort_headers_and_a_pager(_routes, _many):
    html = _builder(_routes, q="smith")
    heads = re.findall(r'class="alt-sort( on)?"', html)
    assert len(heads) == 5 and heads.count(" on") == 1               # one active column
    assert "&#9660;" in html                                         # default: seasons, descending
    assert "30 matches" in html and "1 to 12" in html
    nav = re.search(r'<nav class="alt-pager".*?</nav>', html, re.S).group(0)
    assert "Prev" in nav and "Next" in nav and 'aria-current="page"' in nav
    assert re.search(r'<button[^>]*disabled[^>]*>\s*Prev', nav, re.S)   # no page before 1
    assert '"page": 2' in nav.replace("&#34;", '"')


def test_clicking_the_active_sort_header_flips_its_direction(_routes, _many):
    html = _builder(_routes, q="smith", sort="games", direction="desc")
    head = re.search(r'<button[^>]*class="alt-sort on"[^>]*>', html).group(0)
    assert "asc" in head.replace("&#34;", '"') and "Sort by games, lowest first" in head
    other = re.search(r'<button[^>]*class="alt-sort"[^>]*title="Sort by player[^"]*"', html)
    assert other and "asc" in other.group(0).replace("&#34;", '"')


def test_page_two_continues_the_order_and_keeps_the_sort(_routes, _many):
    html = _builder(_routes, q="smith", sort="games", direction="desc", page=2)
    assert "13 to 24" in html
    nav = re.search(r'<nav class="alt-pager".*?</nav>', html, re.S).group(0)
    assert 'aria-current="page"' in nav
    assert "games" in nav.replace("&#34;", '"') and "desc" in nav.replace("&#34;", '"')


def test_a_single_page_has_no_pager(_routes):
    html = _builder(_routes, q="ab")
    assert "alt-pager" not in html and "2 matches" in html and " to " not in re.search(
        r'<p class="alt-count">(.*?)</p>', html).group(1)


# -- quick picks, reset and narrowed filters -----------------------------------

def test_reset_chip_carries_the_players_defaults_and_a_hint(_routes):
    import json
    html = _builder(_routes, q="ab", player_id="00-1")
    assert "Quick picks" in html
    tag = re.search(r'<button[^>]*class="alt-chip alt-reset"[^>]*>', html).group(0)
    from markupsafe import escape
    assert str(escape(aa.CONTROL_HINTS["reset"])) in tag     # the template escapes the apostrophe
    fill = json.loads(re.search(r"data-fill='([^']*)'", tag).group(1).replace("&#34;", '"'))
    assert fill["measures"] == aa.default_measures("WR", _games())
    assert (fill["agg"], fill["group_by"], fill["opponent"], fill["home_away"]) == ("total", "", "", "")
    assert fill["game_types"] == [] and fill["season_from"] == "" and fill["season_to"] == ""


def test_reset_fill_matches_the_form_it_resets(_routes):
    g = _games()
    f = aa.reset_fill(g, "WR")
    assert set(f) == set(aa.preset_fill("workload", g, "WR"))          # same shape as a chip


def test_filter_flag_and_clear_button_are_wired(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    btn = re.search(r'<button[^>]*class="alt-clear"[^>]*>', html).group(0)
    assert "hidden" in btn and aa.CONTROL_HINTS["clear_filters"] in btn   # hidden until a filter is set
    assert "alt-narrow" in html and "function flag" in html               # the script that marks them


# -- game-context filters --------------------------------------------------

def _ctx_games() -> pd.DataFrame:
    g = _games()
    g["coach"] = ["Reid", "Reid", "Reid", "Reid", "Shanahan"]
    g["opp_coach"] = ["Payton", "Smith", "Payton", "Payton", "Kubiak"]
    g["qb_id"] = ["q1", "q1", "q2", "q2", "q2"]
    g["qb"] = ["Qa", "Qa", "Qb", "Qb", "Qb"]
    g["opp_qb_id"] = ["z1"] * 5
    g["opp_qb"] = ["Zed"] * 5
    g["referee"] = ["R1", "R2", "R1", "R1", None]
    g["result"] = ["W", "L", "W", "W", "L"]
    g["spread"] = [-3.0, 2.0, -1.0, 0.0, 4.0]
    g["roof"] = ["outdoors", "dome", "outdoors", "closed", "open"]
    g["surface"] = ["Grass", "Turf", "Grass", None, "Turf"]
    g["weekday"] = ["Sunday"] * 4 + ["Sunday"]
    g["temp"] = [30.0, float("nan"), 55.0, float("nan"), 80.0]
    g["wind"] = [4.0, float("nan"), 12.0, float("nan"), 20.0]
    g["rest"] = [7, 6, 10, 14, 7]
    g["div_game"] = [1, 0, 0, 0, 0]
    g["overtime"] = [0.0, 0.0, 1.0, 0.0, 0.0]
    return g


def _n(filters):
    return aa.run_query(_ctx_games(), _spec(filters=filters))["games"]


def test_name_and_menu_filters_match_exactly():
    assert _n({"coach": "Reid"}) == 4 and _n({"opp_coach": "Payton"}) == 3
    assert _n({"qb_id": "q2"}) == 3 and _n({"referee": "R1"}) == 3
    assert _n({"result": "W"}) == 3 and _n({"team": "det"}) == 5
    assert _n({"roof": "dome"}) == 1 and _n({"surface": "Turf"}) == 2


def test_blank_values_never_match_a_band_or_category():
    # temp is blank for 2 games, surface for 1: they count in no band or bucket
    assert sum(_n({"temp": b}) for b in aa.EXTRA_BANDS["temp"][2]) == 3
    assert _n({"surface": "Grass"}) + _n({"surface": "Turf"}) == 4


def test_bands_roles_weeks_and_yes_no():
    assert _n({"temp": "Under 40"}) == 1 and _n({"temp": "Over 70"}) == 1
    assert _n({"wind": "10 to 15"}) == 1
    assert _n({"rest": "Short (6 days or fewer)"}) == 1
    assert _n({"rest": "Normal (7 to 9)"}) == 2 and _n({"rest": "Long (10 or more)"}) == 2
    assert _n({"role": "Favorite"}) == 2 and _n({"role": "Underdog"}) == 2   # spread 0 is neither
    assert _n({"weeks": [4, 1]}) == 3 and _n({"weeks": [19, 22]}) == 2
    assert _n({"div_game": "Yes"}) == 1 and _n({"div_game": "No"}) == 4
    assert _n({"overtime": "Yes"}) == 1


def test_filters_combine_and_splits_add_up():
    assert _n({"coach": "Reid", "home_away": "Home"}) == 2
    assert _n({"result": "W"}) + _n({"result": "L"}) == _n({})


def test_extra_filters_reject_values_outside_the_menus():
    for bad in ({"result": "X"}, {"roof": "tent"}, {"temp": "hot"}, {"role": "Lock"},
                {"div_game": "Maybe"}, {"weeks": [1]}):
        with pytest.raises(ValueError):
            aa.run_query(_ctx_games(), _spec(filters=bad))


def test_an_old_frame_without_the_new_columns_matches_nothing_for_them():
    assert aa.run_query(_games(), _spec(filters={"coach": "Reid"}))["games"] == 0
    assert aa.run_query(_games(), _spec())["games"] == 5


def test_context_options_list_only_names_in_the_games():
    o = aa.context_options(_ctx_games())
    assert o["coach"] == ["Reid", "Shanahan"] and o["referee"] == ["R1", "R2"]
    assert o["qb_id"] == [{"value": "q1", "label": "Qa"}, {"value": "q2", "label": "Qb"}]
    assert aa.context_options(pd.DataFrame())["coach"] == []






# -- the filter picker: which filter fields are on screen -----------------------------

def _badge(html: str):
    """(hidden, text) of the Filters header's "n in use" count."""
    m = re.search(r'<span class="alt-hcount" data-count="filters"([^>]*)>(\d+) in use</span>', html)
    assert m
    return ("hidden" in m.group(1), m.group(2))


def test_shown_fields_defaults_then_follows_the_form():
    assert aa.shown_fields([], False, set()) == aa.DEFAULT_SHOWN
    # the form had the picker: the ticked boxes win, in menu order
    assert aa.shown_fields(["coach", "opponent"], True, set()) == ["opponent", "coach"]
    # everything unticked is a real choice, not a reason to fall back to defaults
    assert aa.shown_fields([], True, set()) == []
    # a filter with a value is always shown, ticked or not
    assert aa.shown_fields([], True, {"temp"}) == ["temp"]
    # unknown names are dropped
    assert aa.shown_fields(["bogus", "roof"], True, set()) == ["roof"]


def test_every_menu_filter_is_unique_and_has_a_field():
    keys = aa.PICKER_KEYS
    assert len(keys) == len(set(keys))
    # each menu key is a filter the engine cleans, a measure group or a Show control
    engine = {"opponent", "home_away", "seasons", "game_types", *aa.EXTRA_KEYS}
    assert set(keys) - aa.PLAIN_KEYS == engine
    assert aa.PLAIN_KEYS == {"m_passing", "m_rushing", "m_receiving", "m_kicking",
                             "m_fantasy", "agg", "group_by"}


def _field_hidden(html: str, key: str) -> bool:
    m = re.search(r'<div class="[^"]*alt-(?:field|mgroup)[^"]*" data-f="%s"([^>]*)>' % key, html)
    assert m, key
    return "hidden" in m.group(1)


def test_builder_route_shows_only_the_default_filters_at_first(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    shown = [k for k in aa.PICKER_KEYS if not _field_hidden(html, k)]
    assert shown == aa.default_shown("WR")          # the fixture player is a WR
    assert "m_receiving" in shown and "m_passing" not in shown and "qb_id" in shown
    assert 'name="fshow" value="opponent"' in html and "checked" in html
    assert _badge(html)[0] is True and _badge(html)[1] == "0"


def test_builder_route_shows_the_ticked_filters_and_keeps_them_after_a_run(monkeypatch, _routes):
    monkeypatch.setattr(aa, "load_player", lambda pid: _ctx_games())
    html = _builder(_routes, q="solo", player_id="00-1", run=1, measures=["targets"],
                    _query=b"fshow_set=1&fshow=coach&fshow=temp&coach=Reid&result=W&week_from=2")
    shown = [k for k in aa.PICKER_KEYS if not _field_hidden(html, k)]
    # coach and temp were ticked; result and weeks have values so they show too, and
    # the Receiving group stays because a receiving measure is ticked
    assert shown == ["m_receiving", "weeks", "result", "coach", "temp"]
    assert _badge(html) == (False, "3")                      # coach, result, weeks have values
    assert '<option value="Reid" selected>' in html
    assert '<option value="W" selected>' in html


def test_builder_route_with_every_filter_unticked_shows_none(monkeypatch, _routes):
    monkeypatch.setattr(aa, "load_player", lambda pid: _ctx_games())
    html = _builder(_routes, q="solo", player_id="00-1", _query=b"fshow_set=1")
    filters = [k for k in aa.PICKER_KEYS if k not in aa.PLAIN_KEYS]
    assert all(_field_hidden(html, k) for k in filters)
    assert _field_hidden(html, "agg") and _field_hidden(html, "group_by")


def test_builder_route_runs_with_the_extra_filters(monkeypatch, _routes):
    monkeypatch.setattr(aa, "load_player", lambda pid: _ctx_games())
    html = _builder(_routes, q="solo", player_id="00-1", run=1, measures=["targets"],
                    _query=b"coach=Reid&result=W&week_from=2")
    # Reid wins from week 2 on: 2023 week 1 is out, the WC game (12) is in
    assert re.search(r"<td[^>]*>\s*1\s*</td>", html)          # one game matches
    assert re.search(r"<td[^>]*>\s*12\s*</td>", html)         # its 12 targets


def test_a_non_default_show_choice_stays_on_screen_even_if_unticked(monkeypatch, _routes):
    monkeypatch.setattr(aa, "load_player", lambda pid: _ctx_games())
    html = _builder(_routes, q="solo", player_id="00-1", agg="per_game", group_by="season",
                    measures=["targets"], _query=b"fshow_set=1")
    assert not _field_hidden(html, "agg") and not _field_hidden(html, "group_by")
    assert not _field_hidden(html, "m_receiving")
    assert _field_hidden(html, "m_passing") and _field_hidden(html, "m_kicking")


def test_measure_groups_and_show_controls_are_in_the_picker_but_presets_are_not(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    for key in ("m_passing", "m_rushing", "m_receiving", "m_kicking", "m_fantasy",
                "agg", "group_by"):
        assert f'name="fshow" value="{key}"' in html
    assert "alt-chip" in html                       # the Quick picks are still a separate row
    assert 'name="fshow" value="workload"' not in html


def test_default_shown_follows_the_position():
    qb, rb, wr, k = (aa.default_shown(p) for p in ("QB", "RB", "WR", "K"))
    assert {"m_passing", "m_rushing"} <= set(qb) and "m_receiving" not in qb
    assert {"m_rushing", "m_receiving"} <= set(rb) and "m_passing" not in rb
    assert "m_receiving" in wr and "m_kicking" not in wr
    assert "m_kicking" in k and not ({"m_passing", "m_rushing", "m_receiving"} & set(k))
    assert {"roof", "surface", "temp", "wind"} <= set(k)
    for shown in (qb, rb, wr, k):
        assert set(aa._COMMON_FILTERS) <= set(shown) and {"agg", "group_by"} <= set(shown)
        assert shown == [x for x in aa.PICKER_KEYS if x in shown]       # picker order
    # an unknown position gets every measure group and no position extras
    assert aa.default_shown("DEF") == aa.DEFAULT_SHOWN
    assert aa.default_shown(None) == aa.DEFAULT_SHOWN


def test_every_position_default_is_a_real_picker_key():
    for pos in list(aa._DEFAULT_MEASURES) + ["DEF", None]:
        assert set(aa.default_shown(pos)) <= set(aa.PICKER_KEYS)
    for pos, extra in aa._POSITION_FILTERS.items():
        assert pos in aa._DEFAULT_MEASURES and set(extra) <= set(aa.PICKER_KEYS)


def test_shown_fields_uses_the_given_default_until_the_form_has_the_picker():
    assert aa.shown_fields([], False, set(), ["roof"]) == ["roof"]
    assert aa.shown_fields(["wind"], True, set(), ["roof"]) == ["wind"]
    assert aa.shown_fields([], False, {"temp"}, ["roof"]) == ["roof", "temp"]


def test_reset_fill_carries_the_position_defaults(_routes):
    g = _games()
    fill = aa.reset_fill(g, "WR")
    assert fill["shown"] == aa.default_shown("WR")
    html = _builder(_routes, q="solo", player_id="00-1")
    assert '"shown"' in html                        # the Reset chip's data-fill has it


def test_preset_shown_ticks_what_it_uses_and_nothing_else():
    g = _games()
    s = aa.preset_fill("workload", g, "WR")["shown"]
    assert s == ["m_receiving", "agg", "group_by"]                   # no filters at all
    po = aa.preset_fill("playoffs", g, "WR")
    assert "game_types" in po["shown"] and "opponent" not in po["shown"]
    assert "seasons" in aa.preset_fill("recent", g, "WR")["shown"]
    # groups follow the measures the preset picked, in picker order
    qb = aa.shown_for_fill({"measures": ["passing_yards", "rushing_yards"]})
    assert qb == ["m_passing", "m_rushing", "agg", "group_by"]
    both = aa.shown_for_fill({"measures": ["targets"], "opponent": "KC", "home_away": "Home",
                              "season_from": "2020", "game_types": ["SB"]})
    assert both == ["m_receiving", "agg", "group_by", "opponent", "home_away", "seasons", "game_types"]


def test_every_chip_carries_a_shown_list_of_real_picker_keys(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    import json
    from markupsafe import escape
    fills = re.findall(r"data-fill='([^']*)'", html)
    assert len(fills) == len(aa.PRESETS) + 1                         # every preset and Reset
    for raw in fills:
        d = json.loads(raw.replace("&#34;", '"'))
        assert d["shown"] and set(d["shown"]) <= set(aa.PICKER_KEYS)


def test_section_headers_carry_live_counts(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert 'data-count="filters"' in html
    for g in ("m_passing", "m_rushing", "m_receiving", "m_kicking", "m_fantasy"):
        assert f'data-count="{g}"' in html                  # one count per stat group
    assert "<h4>Measures" not in html                        # no Measures wrapper header


def test_filter_section_replaces_layout_and_counts_the_ticked_boxes(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert "<h4>Layout" not in html and "<h4>Filter " in html
    n = len(aa.default_shown("WR"))
    assert f'data-count="picked">{n} selected</span>' in html
    assert "alt-badge" not in html                       # the button no longer carries a count


def test_player_title_and_sections_order(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    order = [html.index(x) for x in ('class="alt-search"', 'class="alt-who"',
                                     "<h4>Filter ", "<h4>Quick picks", "<h4>Receiving",
                                     "<h4>Show", "<h4>Filters ")]
    assert order == sorted(order)                        # search, player, Filter, Quick picks, stats...
    assert 'alt-who-name">A B</span>' in html and "WR &middot; DET" in html
    assert 'name="fshow" value="m_receiving"' in html and "<h5>Stats</h5>" in html
    assert "<h5>Measures</h5>" not in html
