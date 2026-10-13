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
                         "season_to", "home_away", "game_types"}


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

def _req():
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [],
                    "query_string": b"", "server": ("x", 80), "scheme": "http"})


@pytest.fixture
def _routes(monkeypatch):
    from webapp import app as A
    g = _games()
    monkeypatch.setattr(aa, "search_players", lambda q, limit=12: (
        [{"player_id": "00-1", "name": "A B", "position": "WR", "team": "DET",
          "first_season": 2022, "last_season": 2023, "games": 5}] if "a" in q else []))
    monkeypatch.setattr(aa, "load_player", lambda pid: g if pid == "00-1" else pd.DataFrame())
    return A


def _builder(A, **kw):
    """Call the route function directly, giving the list arguments real values
    (FastAPI's Query defaults only resolve through the framework)."""
    args = {"q": "", "player_id": "", "run": 0, "measures": [], "agg": "total",
            "group_by": "", "opponent": "", "season_from": "", "season_to": "",
            "home_away": "", "game_types": []}
    args.update(kw)
    return A.alt_builder(_req(), **args).body.decode()


def test_builder_route_search_lists_matches_and_loads_no_chips(_routes):
    html = _builder(_routes, q="ab")
    assert "A B" in html and "hx-vals" in html and "alt-chip" not in html


def test_chosen_player_shows_full_name_and_position_under_the_search_box(_routes):
    import re
    html = _builder(_routes, q="ab", player_id="00-1")
    assert re.search(r'<p class="alt-player"[^>]*><strong>A B</strong>\s*&middot; WR &middot; DET', html)
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
    assert 'hx-get="/testing/alt/builder"' in form


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


def test_grouped_measures_keep_every_measure_and_flag_unused():
    games = pd.DataFrame({"targets": [5, 6], "receptions": [3, 4], "receiving_yards": [40, 60],
                          "carries": [1, 0], "rushing_yards": [3, 0],
                          "fantasy_points_ppr": [9.0, 12.0]})
    groups = aa.grouped_measures(games, "WR")
    assert [g["label"] for g in groups] == ["Receiving", "Passing", "Rushing", "Kicking", "Fantasy"]
    keys = [k for g in groups for k, _, _ in g["items"]]
    assert set(keys) == set(aa.MEASURES)              # nothing hidden
    used = {k: u for g in groups for k, _, u in g["items"]}
    assert used["targets"] and used["rushing_yards"] and not used["passing_yards"]
    assert aa.grouped_measures(games, "RB")[0]["label"] == "Rushing"
    assert not any(u for g in aa.grouped_measures(games.iloc[0:0], "WR") for *_, u in g["items"])


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
    assert aa.grouped_measures(g, "K")[0]["label"] == "Kicking"


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
