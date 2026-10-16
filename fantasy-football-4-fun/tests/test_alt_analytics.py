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
                                  "yards_per_target", "rush_td_rate")
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


def _card(A, card, query: bytes = b""):
    """Call the card route directly with the shared filters in the query string."""
    return A.alt_card(_req(query), player_id="00-1", card=card).body.decode()


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


def test_cards_are_listed_for_the_position_and_the_page_has_no_chips(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    ids = re.findall(r'<section class="card alt-card" data-card="([a-z_]+)"', html)
    assert ids == [c["id"] for c in aa.cards_for("WR")]          # the fixture player is a WR
    assert "coverage" in ids and "routes" in ids
    assert 'data-card="custom"' not in html and 'class="nfl-apply alt-add"' in html   # added, not built in
    assert f'data-eager="{aa.EAGER_CARDS}"' in html
    assert "alt-chip" not in html and "Quick picks" not in html
    assert html.split("<script>")[0].count('class="skeleton alt-skel"') == len(ids)   # each waits for its turn


def test_only_the_run_form_sends_a_request(_routes):
    import re
    html = _builder(_routes, q="ab", player_id="00-1")
    form = re.search(r'<form id="alt-builder-form"[^>]*>', html).group(0)
    assert 'hx-get="/altanalytics/builder"' in form


def test_custom_card_runs_the_spec_and_the_page_disables_unused_measures(_routes):
    html = _card(_routes, "custom",
                 b"measures=receiving_yards&agg=per_game&group_by=season")
    assert "Rec yds /g" in html and 'data-state="ok"' in html
    assert '<th class="n">Pass yds' not in html                  # never a result column
    page = _builder(_routes, q="ab", player_id="00-1", measures=["receiving_yards"])
    # an unused measure stays in the form but is disabled
    box = re.search(r'<input[^>]*value="passing_yards"[^>]*>', page, re.S).group(0)
    assert "disabled" in box


def test_card_route_turns_a_bad_spec_into_a_message(_routes):
    html = _card(_routes, "custom", b"measures=x")
    assert 'data-state="error"' in html and "unknown measure" in html
    assert 'data-state="error"' in _card(_routes, "nope")        # an unknown card too


def test_results_never_render_nan(_routes):
    html = _card(_routes, "custom", b"measures=yards_per_carry&group_by=season")
    assert ">nan<" not in html.lower() and "–" in html


def test_grouped_measures_keep_every_measure_in_one_fixed_order():
    games = pd.DataFrame({"targets": [5, 6], "receptions": [3, 4], "receiving_yards": [40, 60],
                          "carries": [1, 0], "rushing_yards": [3, 0],
                          "fantasy_points_ppr": [9.0, 12.0]})
    order = ["Passing", "Rushing", "Receiving", "Scrimmage", "Kicking", "Fantasy"]
    for pos in ("WR", "RB", "QB", "K", None):          # the order never depends on the player
        assert [g["label"] for g in aa.grouped_measures(games, pos)] == order
    groups = aa.grouped_measures(games, "WR")
    keys = [k for g in groups for k, _, _ in g["items"]]
    assert set(keys) == set(aa.MEASURES)              # nothing hidden
    used = {k: u for g in groups for k, _, u in g["items"]}
    assert used["targets"] and used["rushing_yards"] and not used["passing_yards"]
    flags = {g["label"]: g["used"] for g in groups}    # a group is used when any measure is
    assert flags == {"Passing": False, "Rushing": True, "Receiving": True,
                     "Scrimmage": False, "Kicking": False, "Fantasy": True}
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
    assert "alt-who" in html and "alt-cards" in html             # the dashboard is already open



def test_every_measure_has_a_hover_hint():
    assert set(aa.MEASURE_HINTS) == set(aa.MEASURES)
    assert all(aa.MEASURE_HINTS[k].strip() for k in aa.MEASURES)
    assert "maximum" in aa.MEASURE_HINTS["fg_long"]
    assert {p["id"] for p in aa.PRESETS} == set(aa.PRESET_HINTS)


def test_hints_reach_the_page_for_measures_cards_and_controls(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    assert f'title="{aa.MEASURE_HINTS["targets"]}"' in html
    unused = re.search(r'<label class="adp-check alt-unused"\s+title="([^"]*)"', html).group(1)
    assert unused.endswith("No production for this player.")     # definition first, then the note
    cards = re.findall(r'<section class="card alt-card" data-card="[a-z_]+" data-state="idle" title="([^"]*)"', html)
    assert len(cards) == len(aa.cards_for("WR")) and all(cards)
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
    assert aa.PLAIN_KEYS == {"m_passing", "m_rushing", "m_receiving", "m_scrimmage",
                             "m_kicking", "m_fantasy", "agg", "group_by"}


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


def test_card_route_runs_with_the_extra_filters(monkeypatch, _routes):
    monkeypatch.setattr(aa, "load_player", lambda pid: _ctx_games())
    html = _card(_routes, "custom", b"measures=targets&coach=Reid&result=W&week_from=2")
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
    assert "alt-chip" not in html                   # no Quick picks: the cards replace them
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


def test_section_headers_carry_live_counts(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert 'data-count="filters"' in html
    for g in ("m_passing", "m_rushing", "m_receiving", "m_kicking", "m_fantasy"):
        assert f'data-count="{g}"' in html                  # one count per stat group
    assert "<h4>Measures" not in html                        # no Measures wrapper header


def test_two_pickers_each_count_their_own_ticked_boxes(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert "<h4>Layout" not in html and "<h4>Filters " in html
    shown = aa.default_shown("WR")
    stat_keys = [k for g, items in aa.PICKER_MENU if g in ("Stats", "Results") for k, _ in items]
    n_stats = sum(k in shown for k in stat_keys)
    n_filters = len(shown) - n_stats
    assert f'data-count="picked-stats">{n_stats}</span>' in html
    assert f'data-count="picked-filters">{n_filters}</span>' in html
    assert html.count('class="alt-fpick"') == 2          # Choose filters and Choose stats
    assert "alt-badge" not in html


def test_player_title_and_sections_order(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    order = [html.index(x) for x in ('class="alt-search"', 'class="alt-who"',
                                     "<h4>Filters ", "<h4>Add a card",
                                     "<h4>Receiving", "<h4>Show", 'id="alt-cards"')]
    assert order == sorted(order)                        # search, player, filters, the card builder, then the cards
    assert 'alt-who-name">A B</span>' in html and "WR &middot; DET" in html
    assert 'name="fshow" value="m_receiving"' in html and "<h5>Stats</h5>" in html
    assert "<h5>Measures</h5>" not in html


# -- play-level queries (pass_plays) ---------------------------------------------

def _plays(rows, **const) -> pd.DataFrame:
    """rows: (season, week, attempt, complete, yards, td, man_zone, box)."""
    df = pd.DataFrame(rows, columns=["season", "week", "attempt", "complete", "yards",
                                     "td", "man_zone", "box"])
    df["play_id"] = range(1, len(df) + 1)
    df["interception"] = 0
    df["air_yards"] = df["yards"].astype(float)
    df["sack"] = 0
    df["coverage"] = None
    df["rushers"] = 4.0
    df["pressure"] = 0.0
    df["ttt"] = 2.5
    df["formation"] = "SHOTGUN"
    df["route"] = "GO"
    df["receiver_id"] = "00-1"
    df["passer_id"] = None
    for k, v in const.items():
        df[k] = v
    return df


_MAN, _ZONE = "MAN_COVERAGE", "ZONE_COVERAGE"


def _wr_plays() -> pd.DataFrame:
    return _plays([
        (2022, 1, 1, 1, 10, 0, _MAN, 6.0), (2022, 1, 1, 0, 0, 0, _MAN, 7.0),
        (2022, 1, 1, 1, 20, 1, _ZONE, 6.0), (2022, 2, 1, 1, 5, 0, _ZONE, 8.0),
        (2023, 1, 1, 1, 30, 1, _MAN, 7.0), (2023, 1, 1, 1, 7, 0, None, 7.0),
        (2023, 22, 1, 0, 0, 0, _MAN, 6.0),
    ])                                    # 2023 week 19: a game with no play at all


@pytest.fixture
def _playdata(monkeypatch):
    plays = _wr_plays()
    monkeypatch.setattr(aa, "load_plays", lambda pid, passer: plays)
    monkeypatch.setattr(aa, "_play_coverage",
                        {2022: {"man_zone": .9, "box": 1.0, "coverage": .9, "rushers": 1.0,
                                "pressure": 1.0, "ttt": 1.0, "formation": 1.0, "route": .9},
                         2023: {"man_zone": .99, "box": 1.0, "coverage": .99, "rushers": 1.0,
                                "pressure": 1.0, "ttt": 1.0, "formation": 1.0, "route": .9}})
    return plays


def _pq(**kw):
    base = {"measures": ["targets", "receptions", "receiving_yards", "receiving_tds"],
            "agg": "total", "filters": {}, "group_by": None}
    base.update(kw)
    return base


def test_uses_plays_only_for_a_play_filter_or_play_group():
    assert not aa.uses_plays(aa._clean(_pq()))
    assert aa.uses_plays(aa._clean(_pq(filters={"man_zone": "Man"})))
    assert aa.uses_plays(aa._clean(_pq(group_by="coverage")))
    assert not aa.uses_plays(aa._clean(_pq(group_by="season", filters={"opponent": "KC"})))


def test_man_filter_sums_the_players_targets_in_man_coverage(_playdata):
    r = aa.run_query(_games(), _pq(filters={"man_zone": "Man"}))
    row = r["rows"][0]
    assert row["targets"] == 4 and row["receptions"] == 2
    assert row["receiving_yards"] == 40 and row["receiving_tds"] == 1
    assert row["games"] == 5 and r["games"] == 5          # every game in a usable season
    assert r["play_seasons"] == "2022 to 2023"


def test_per_game_divides_by_games_played_including_a_game_with_no_play(_playdata):
    r = aa.run_query(_games(), _pq(agg="per_game", filters={"man_zone": "Man"}))
    assert r["rows"][0]["targets"] == pytest.approx(4 / 5)    # 5 games, one had no man play


def test_play_group_splits_plays_and_leaves_a_blank_scheme_out(_playdata):
    r = aa.run_query(_games(), _pq(group_by="man_zone"))
    by = {x["group"]: x for x in r["rows"]}
    assert set(by) == {"Man", "Zone"}
    assert (by["Man"]["targets"], by["Man"]["games"]) == (4, 3)
    assert (by["Zone"]["targets"], by["Zone"]["games"], by["Zone"]["receiving_yards"]) == (2, 2, 25)
    # the play with no coverage recorded (7 yards) is in no group and not in the total
    assert r["total"]["targets"] == 6 and r["total"]["receiving_yards"] == 65
    assert r["total"]["games"] == 4 == r["games"]


def test_group_per_game_counts_only_games_with_such_a_play(_playdata):
    r = aa.run_query(_games(), _pq(agg="per_game", group_by="man_zone"))
    man = {x["group"]: x for x in r["rows"]}["Man"]
    assert man["targets"] == pytest.approx(4 / 3)


def test_game_filters_and_play_filters_combine(_playdata):
    r = aa.run_query(_games(), _pq(filters={"man_zone": "Man", "opponent": "KC"}))
    # KC games: 2022 wk1 (2 man targets), 2023 wk1 (1), 2023 wk19 (none)
    assert r["rows"][0]["targets"] == 3 and r["games"] == 3


def test_game_group_with_a_play_filter_keeps_zero_games(_playdata):
    r = aa.run_query(_games(), _pq(group_by="game_type", filters={"man_zone": "Man"}))
    by = {x["group"]: x for x in r["rows"]}
    assert by["WC"]["targets"] == 0 and by["WC"]["games"] == 1      # a real zero, not a dash
    assert by["SB"]["targets"] == 1 and by["REG"]["targets"] == 3
    assert r["total"]["targets"] == 4


def test_a_measure_a_play_query_cannot_answer_is_a_dash(_playdata):
    r = aa.run_query(_games(), _pq(measures=["targets", "rushing_yards", "fantasy_points_ppr"],
                                   filters={"man_zone": "Zone"}))
    row = r["rows"][0]
    assert row["targets"] == 2 and row["rushing_yards"] is None
    assert row["fantasy_points_ppr"] is None
    assert aa.table_view(r)["rows"][0]["cells"][1] == "–"


def test_ratios_use_the_plays_sums(_playdata):
    r = aa.run_query(_games(), _pq(measures=["catch_rate", "yards_per_target", "yards_per_reception"],
                                   filters={"man_zone": "Man"}))
    row = r["rows"][0]
    assert row["catch_rate"] == pytest.approx(50.0)           # 2 of 4
    assert row["yards_per_target"] == pytest.approx(10.0)     # 40 / 4
    assert row["yards_per_reception"] == pytest.approx(20.0)  # 40 / 2


def test_a_season_without_the_needed_column_is_left_out(monkeypatch, _playdata):
    monkeypatch.setattr(aa, "_play_coverage",
                        {2022: {"man_zone": 0.0, "box": 1.0}, 2023: {"man_zone": .99, "box": 1.0}})
    r = aa.run_query(_games(), _pq(filters={"man_zone": "Man"}))
    assert r["games"] == 3 and r["play_seasons"] == "2023"     # 2022 had no coverage data
    assert r["rows"][0]["targets"] == 2
    # a filter on a column both seasons have keeps both
    assert aa.run_query(_games(), _pq(filters={"box": "7"}))["games"] == 5


def test_no_season_with_data_gives_no_rows(monkeypatch, _playdata):
    monkeypatch.setattr(aa, "_play_coverage", {2022: {"man_zone": 0.0}, 2023: {"man_zone": 0.0}})
    r = aa.run_query(_games(), _pq(filters={"man_zone": "Man"}))
    assert r["rows"] == [] and r["games"] == 0


def _labels(series):
    return [None if pd.isna(x) else x for x in series]


def test_box_rusher_pressure_and_time_to_throw_bands():
    p = pd.DataFrame({"box": [5.0, 6.0, 7.0, 8.0, 11.0, None],
                      "rushers": [3.0, 4.0, 5.0, 6.0, 4.0, None],
                      "pressure": [1.0, 0.0, None, 1.0, 0.0, 1.0],
                      "ttt": [1.0, 2.4, 2.5, 3.49, 3.5, None]})
    assert _labels(aa._play_values(p, "box")) == ["6 or fewer", "6 or fewer", "7", "8 or more",
                                                  "8 or more", None]
    assert _labels(aa._play_values(p, "rushers")) == ["3 or fewer", "4", "5 or more (blitz)",
                                                      "5 or more (blitz)", "4", None]
    assert _labels(aa._play_values(p, "pressure")) == ["Yes", "No", None, "Yes", "No", "Yes"]
    assert _labels(aa._play_values(p, "ttt")) == ["Under 2.5 s", "Under 2.5 s", "2.5 to 3.5 s",
                                                  "2.5 to 3.5 s", "3.5 s or more", None]


def test_coverage_route_and_formation_menus_use_the_stored_values(_playdata):
    p = _playdata.copy()
    p["coverage"] = ["COVER_3", "COVER_1", "COVER_3", "2_MAN", None, "COVER_3", "COVER_0"]
    p["route"] = ["GO", "SLANT", "GO", "SCREEN", None, "HITCH/CURL", "GO"]
    assert aa._play_values(p, "coverage").tolist()[:4] == ["Cover 3", "Cover 1", "Cover 3", "2-man"]
    assert _labels(aa._play_values(p, "route"))[3:6] == ["Screen", None, "Hitch/curl"]
    assert aa._play_values(p, "formation").iloc[0] == "Shotgun"


def test_bad_play_filter_values_are_refused():
    for f in ({"man_zone": "Blitz"}, {"coverage": "Cover 5"}, {"pressure": "Maybe"},
              {"box": "9"}, {"route": "Fly"}):
        with pytest.raises(ValueError):
            aa._clean(_pq(filters=f))
    with pytest.raises(ValueError):
        aa._clean(_pq(group_by="not_a_group"))


def test_a_quarterback_is_read_as_a_passer_and_a_sack_is_not_an_attempt(monkeypatch):
    g = _games()
    g["position"] = "QB"
    p = _plays([(2022, 1, 1, 1, 12, 1, _MAN, 6.0), (2022, 1, 1, 0, 0, 0, _MAN, 6.0),
                (2022, 1, 0, 0, -7, 0, _MAN, 6.0), (2023, 1, 1, 1, 8, 0, _ZONE, 6.0)],
               passer_id="00-1", receiver_id=None)
    p.loc[2, "sack"] = 1
    p.loc[1, "interception"] = 1
    monkeypatch.setattr(aa, "load_plays", lambda pid, passer: p if passer else pd.DataFrame())
    monkeypatch.setattr(aa, "_play_coverage", {2022: {"man_zone": 1.0}, 2023: {"man_zone": 1.0}})
    r = aa.run_query(g, {"measures": ["attempts", "completions", "passing_yards", "passing_tds",
                                      "interceptions", "completion_rate", "targets"],
                         "agg": "total", "group_by": None, "filters": {"man_zone": "Man"}})
    row = r["rows"][0]
    assert row["attempts"] == 2 and row["completions"] == 1      # the sack is not an attempt
    assert row["passing_yards"] == 12 and row["passing_tds"] == 1 and row["interceptions"] == 1
    assert row["completion_rate"] == pytest.approx(50.0)
    assert row["targets"] is None                                # receiver measure: a dash


def test_air_yards_not_recorded_is_a_dash_not_zero(monkeypatch, _playdata):
    p = _wr_plays()
    p["air_yards"] = float("nan")
    monkeypatch.setattr(aa, "load_plays", lambda pid, passer: p)
    r = aa.run_query(_games(), _pq(measures=["receiving_air_yards", "targets"],
                                   filters={"man_zone": "Man"}))
    assert r["rows"][0]["receiving_air_yards"] is None and r["rows"][0]["targets"] == 4


def test_play_measures_are_a_subset_of_the_known_measures_and_pick_a_role():
    assert aa.PLAY_MEASURES <= set(aa.MEASURES)
    assert aa._PASSER_MEASURES <= aa.PLAY_MEASURES
    assert "rushing_yards" not in aa.PLAY_MEASURES and "fg_made" not in aa.PLAY_MEASURES


def test_play_filters_are_in_the_picker_and_default_off():
    keys = dict(aa.PICKER_MENU)["Play"]
    assert [k for k, _ in keys] == ["man_zone", "coverage", "box", "rushers", "pressure",
                                    "ttt", "route", "formation"]
    assert set(aa.PLAY_KEYS) <= set(aa.PICKER_KEYS) and set(aa.PLAY_KEYS) <= set(aa.EXTRA_KEYS)
    for pos in ("QB", "RB", "WR", "TE", "K", None):
        assert not (set(aa.PLAY_KEYS) & set(aa.default_shown(pos)))


def test_play_presets_only_pick_measures_a_play_query_can_answer():
    for pid, group in (("man_zone", "man_zone"), ("pressure", "pressure")):
        for pos in ("QB", "WR", "RB", "TE"):
            g = _games()
            fill = aa.preset_fill(pid, g, pos)
            assert fill["group_by"] == group
            assert fill["measures"] and set(fill["measures"]) <= aa.PLAY_MEASURES


def test_play_filters_are_read_from_the_query_and_run_in_the_card_route(_routes, monkeypatch, _playdata):
    html = _builder(_routes, q="solo", player_id="00-1", measures=["targets"],
                    _query=b"man_zone=Man&fshow_set=1&fshow=m_receiving")
    assert not _field_hidden(html, "man_zone")                    # a set filter is always shown
    assert _field_hidden(html, "coverage") and _field_hidden(html, "route")
    assert 'data-count="filters">1 in use' in html
    card = _card(_routes, "custom", b"measures=targets&man_zone=Man")
    assert re.search(r"<td[^>]*>\s*4\s*</td>", card)             # 4 targets in man coverage
    assert "Pass-play data used: 2022 to 2023" in card            # which seasons answered


def test_builder_page_has_a_play_band_and_dims_game_only_measures(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert 'data-blk="sub-play"' in html and "<h5 class=\"alt-subhead\">Play</h5>" in html
    assert '<optgroup label="Pass plays">' in html
    assert "alt-gameonly" in html and "aa.PLAY_KEYS" not in html
    assert '"man_zone", "coverage"' in html                        # the script knows the play keys


# -- cards -----------------------------------------------------------------------

def test_cards_follow_the_position():
    ids = lambda pos: [c["id"] for c in aa.cards_for(pos)]      # noqa: E731
    base = ["workload", "production", "efficiency", "home_away", "by_opponent"]
    assert ids("WR") == ids("RB") == ids("TE") == base + ["coverage", "routes"]
    assert ids("QB") == base + ["coverage"]                      # a route is the receiver's
    assert ids("K") == base and ids(None) == base               # no pass plays to split
    assert aa.CARD_ORDER == [c["id"] for c in aa.cards_for("WR")]
    assert 1 <= aa.EAGER_CARDS < len(aa.CARD_ORDER)


def test_card_spec_uses_the_cards_layout_and_the_shared_filters():
    g = _games()
    f = {"opponent": "KC", "home_away": "Home"}
    spec = aa.card_spec("workload", g, "WR", f)
    assert (spec["agg"], spec["group_by"], spec["filters"]) == ("per_game", "season", f)
    assert spec["measures"] == aa._family_measures(["volume"], g, "WR")
    assert aa.card_spec("home_away", g, "WR", {})["group_by"] == "home_away"
    with pytest.raises(ValueError):
        aa.card_spec("nope", g, "WR", {})


def test_pass_play_cards_only_ask_for_measures_a_play_query_can_answer():
    for pos in ("QB", "WR", "RB", "TE"):
        for card in ("coverage", "routes"):
            if card == "routes" and pos == "QB":
                continue
            spec = aa.card_spec(card, _games(), pos, {})
            assert spec["measures"] and set(spec["measures"]) <= aa.PLAY_MEASURES
            assert aa._clean(spec)["group_by"] == spec["group_by"]  # a valid spec


def test_every_non_play_card_runs_for_every_position():
    for pos, g in (("WR", _games()), ("RB", _rb_games()), ("K", _kicker_games())):
        for c in aa.cards_for(pos):
            if c["id"] in ("coverage", "routes"):
                continue                                          # needs the pass-play table
            r = aa.run_card(g, pos, c["id"], {})
            assert r["columns"] and "rows" in r


def test_has_data_is_false_for_no_rows_or_only_unrecorded_values():
    cols = [{"key": "targets", "label": "Targets"}]
    assert not aa.has_data({"columns": cols, "rows": []})
    assert not aa.has_data({"columns": cols, "rows": [{"targets": None, "games": 2}]})
    assert aa.has_data({"columns": cols, "rows": [{"targets": 0.0, "games": 2}]})   # zero is data


def test_card_route_returns_a_card_body_and_matches_the_engine(_routes):
    g = _games()
    html = _card(_routes, "workload")
    assert 'data-state="ok"' in html and "<table>" in html
    want = aa.table_view(aa.run_card(g, "WR", "workload", {}))
    for col in want["columns"]:
        assert f'<th class="n">{col}</th>' in html
    for row in want["rows"]:
        assert f"<td>{row['label']}</td>" in html


def test_card_route_applies_the_shared_filters(_routes):
    all_games = _card(_routes, "workload")
    html = _card(_routes, "workload", b"season_from=2023&season_to=2023")
    assert "<td>2022</td>" in all_games and "<td>2022</td>" not in html
    assert "<td>2023</td>" in html


def test_a_card_with_nothing_to_show_says_empty_so_the_page_can_hide_it(_routes):
    html = _card(_routes, "workload", b"opponent=ZZZ")            # no such opponent
    assert 'data-state="empty"' in html and "<table>" not in html


def test_card_route_with_an_unknown_player_is_an_error(_routes):
    html = _routes.alt_card(_req(), player_id="nobody", card="workload").body.decode()
    assert 'data-state="error"' in html and "Unknown player" in html


def test_page_queue_loads_the_first_few_together_then_the_rest_one_at_a_time(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    assert "Promise.all(std.slice(0, n).map(load))" in html       # the first few at once
    assert "std.slice(n).concat(added).reduce" in html           # then a chain, one by one, added cards last
    assert "IntersectionObserver" not in html                    # not tied to scrolling
    assert "window.altQueue.stop = true" in html                 # Run / a new player stops the old queue
    assert "st === 'empty'" in html                              # an empty card is hidden


# -- derived columns and rates --------------------------------------------------------

def _derive_frame():
    return pd.DataFrame({
        "season": [2022, 2022, 2023], "week": [1, 2, 1], "opponent": ["X", "Y", "X"],
        "home_away": ["Home", "Away", "Home"], "game_type": ["REG"] * 3,
        "carries": [10, 0, 5], "rushing_yards": [50, 0, 30], "rushing_tds": [1, 0, 0],
        "targets": [5, 8, float("nan")], "receptions": [3, 6, 4],
        "receiving_yards": [40, 80, 20], "receiving_tds": [0, 1, 0],
        "receiving_air_yards": [30.0, 60.0, float("nan")],
        "passing_yards": [0, 0, 0], "fg_made": [0, 0, 0], "pat_made": [0, 0, 0],
        "fantasy_points_ppr": [12.0, 20.0, 8.0]})


def test_add_derived_builds_touches_scrimmage_and_kick_points():
    g = aa.add_derived(_derive_frame())
    assert g["touches"].tolist() == [13, 6, 9]
    assert g["scrimmage_yards"].tolist() == [90, 80, 50]
    assert g["scrimmage_tds"].tolist() == [1, 1, 0]
    k = aa.add_derived(_kicker_games())
    assert k["kick_points"].tolist() == [8, 7, 12]                  # 3 per FG, 1 per PAT


def test_add_derived_is_missing_only_when_every_part_is_missing():
    df = pd.DataFrame({"carries": [float("nan"), 2.0], "receptions": [float("nan"), float("nan")]})
    t = aa.add_derived(df)["touches"]
    assert pd.isna(t.iloc[0]) and t.iloc[1] == 2.0
    assert aa.add_derived(pd.DataFrame()).empty
    assert "touches" not in aa.add_derived(pd.DataFrame({"x": [1]})).columns   # no parts, no column


def test_new_rates_are_sum_over_sum_and_skip_unrecorded_parts():
    g = aa.add_derived(_derive_frame())
    r = aa.run_query(g, {"measures": ["adot", "yards_per_air_yard", "rec_td_rate",
                                      "rush_td_rate", "yards_per_touch", "ppr_per_touch"]})
    row = r["rows"][0]
    assert abs(row["adot"] - 90 / 13) < 1e-9                  # 2023 has no air yards or targets
    assert abs(row["yards_per_air_yard"] - 120 / 90) < 1e-9
    assert abs(row["rec_td_rate"] - 1 / 13 * 100) < 1e-9      # a percent
    assert abs(row["rush_td_rate"] - 1 / 15 * 100) < 1e-9
    assert abs(row["yards_per_touch"] - 220 / 28) < 1e-9
    assert abs(row["ppr_per_touch"] - 40 / 28) < 1e-9
    assert aa.format_value("rec_td_rate", row["rec_td_rate"]).endswith("%")


def test_every_new_measure_is_listed_in_a_group_with_a_hint():
    new = {"touches", "scrimmage_yards", "scrimmage_tds", "kick_points", "yards_per_completion",
           "pass_td_rate", "int_rate", "rush_td_rate", "rec_td_rate", "adot",
           "yards_per_air_yard", "yards_per_touch", "ppr_per_touch"}
    listed = {k for _, keys in aa.MEASURE_GROUPS for k in keys}
    assert new <= listed and new <= set(aa.MEASURES) and new <= set(aa.MEASURE_HINTS)
    assert listed == set(aa.MEASURES)                          # nothing unlisted, nothing extra


def test_new_rates_appear_in_the_efficiency_card_by_position():
    g = aa.add_derived(_derive_frame())
    wr = aa.card_spec("efficiency", g, "WR", {})["measures"]
    assert {"adot", "yards_per_air_yard", "rec_td_rate"} <= set(wr)
    rb = aa.card_spec("efficiency", g, "RB", {})["measures"]
    assert "yards_per_touch" in rb and "rush_td_rate" in rb
    assert "scrimmage_yards" in aa.card_spec("production", g, "RB", {})["measures"]


# -- indicators ------------------------------------------------------------------------

def _res(rows, group="season", agg="per_game", keys=("targets",)):
    return {"columns": [{"key": k, "label": aa.MEASURES[k]} for k in keys],
            "rows": [{"group": gv, "games": 16, **vals} for gv, vals in rows],
            "total": None, "games": 16 * len(rows),
            "spec": {"group_by": group, "agg": agg, "measures": list(keys), "filters": {}}}


def test_heat_runs_from_the_players_worst_row_to_best_and_marks_the_extremes():
    marks, _ = aa.indicators(_res([(2020, {"targets": 4.0}), (2021, {"targets": 6.0}),
                                   (2022, {"targets": 8.0})]))
    h = [m[0]["h"] for m in marks]
    assert h == [0, aa._HEAT_MAX // 2, aa._HEAT_MAX]
    assert [m[0].get("mark") for m in marks] == ["worst", None, "best"]


def test_lower_is_better_stats_flip_heat_marks_and_arrow_tone():
    res = _res([(2020, {"interceptions": 10.0}), (2021, {"interceptions": 4.0}),
                (2022, {"interceptions": 6.0})], keys=("interceptions",))
    marks, _ = aa.indicators(res)
    assert marks[1][0]["mark"] == "best" and marks[0][0]["mark"] == "worst"
    assert marks[1][0]["trend"]["arrow"] == "\u25bc" and marks[1][0]["trend"]["tone"] == "good"
    assert marks[2][0]["trend"]["arrow"] == "\u25b2" and marks[2][0]["trend"]["tone"] == "bad"


def test_trend_arrows_need_a_real_change_and_only_on_rates_or_per_game_by_season():
    rows = [(2020, {"targets": 10.0}), (2021, {"targets": 10.2}), (2022, {"targets": 12.0})]
    marks, _ = aa.indicators(_res(rows))
    assert "trend" not in marks[0][0] and "trend" not in marks[1][0]        # +2% is noise
    t = marks[2][0]["trend"]
    assert t["arrow"] == "\u25b2" and t["tone"] == "good" and "+18%" in t["title"] and "2021" in t["title"]
    assert not any("trend" in m[0] for m in aa.indicators(_res(rows, agg="total"))[0])   # totals depend on games
    assert not any("trend" in m[0] for m in aa.indicators(_res(rows, group="opponent"))[0])


def test_count_columns_by_a_non_season_group_get_share_bars_not_heat():
    marks, _ = aa.indicators(_res([("A", {"targets": 50.0}), ("B", {"targets": 30.0}),
                                   ("C", {"targets": 20.0})], group="opponent", agg="total"))
    assert [m[0]["bar"] for m in marks] == [100, 60, 40]          # against the longest row
    assert [m[0]["share"] for m in marks] == [50, 30, 20]         # percent of the total
    assert all("h" not in m[0] for m in marks)
    rate = _res([("A", {"catch_rate": 70.0}), ("B", {"catch_rate": 60.0}), ("C", {"catch_rate": 50.0})],
                group="opponent", agg="total", keys=("catch_rate",))
    assert all("bar" not in m[0] and "h" in m[0] for m in aa.indicators(rate)[0])   # a rate has no share


def test_no_indicators_for_too_few_rows_or_no_spread_or_unrecorded_values():
    assert aa.indicators(_res([(2020, {"targets": 4.0}), (2021, {"targets": 9.0})]))[0] == [[{}], [{}]]
    flat = [(2020, {"targets": 5.0}), (2021, {"targets": 5.0}), (2022, {"targets": 5.0})]
    assert aa.indicators(_res(flat))[0] == [[{}], [{}], [{}]]
    gap = _res([(2020, {"targets": 4.0}), (2021, {"targets": None}), (2022, {"targets": 8.0}),
                (2023, {"targets": 6.0})])
    marks, _ = aa.indicators(gap)
    assert marks[1][0] == {} and marks[0][0]["mark"] == "worst"        # a dash is never a low
    assert aa.indicators(_res([(2020, {"targets": 4.0}), (2021, {"targets": None}),
                               (2022, {"targets": 8.0})]))[0] == [[{}], [{}], [{}]]   # only two values


def test_header_chips_name_the_best_season_and_the_latest_change():
    _, chips = aa.indicators(_res([(2020, {"targets": 8.0}), (2021, {"targets": 6.0}),
                                   (2022, {"targets": 9.0})]))
    assert [c["text"] for c in chips] == ["Best: 2022", "\u25b2 50%"]
    assert chips[1]["tone"] == "good" and "2022 vs 2021" in chips[1]["title"]
    assert aa.indicators(_res([("A", {"targets": 1.0}), ("B", {"targets": 2.0}),
                               ("C", {"targets": 3.0})], group="opponent"))[1] == []


def test_table_view_carries_marks_and_chips_and_keeps_cells_as_strings():
    tv = aa.table_view(_res([(2020, {"targets": 4.0}), (2021, {"targets": 6.0}),
                             (2022, {"targets": 8.0})]))
    assert tv["rows"][0]["cells"] == ["4"] or isinstance(tv["rows"][0]["cells"][0], str)
    assert len(tv["rows"][2]["marks"]) == 1 and tv["rows"][2]["marks"][0]["mark"] == "best"
    assert tv["chips"][0]["text"] == "Best: 2022"
    assert tv["total"] is None


def test_card_template_renders_tints_marks_arrows_bars_and_chips(_routes, monkeypatch):
    g = aa.add_derived(pd.DataFrame({
        "player_id": "00-1", "player_display_name": "A B", "position": "WR", "team": "DET",
        "season": [2020, 2020, 2021, 2021, 2022, 2022], "week": [1, 2] * 3,
        "opponent": ["X", "Y", "X", "Z", "Y", "Z"], "home_away": ["Home", "Away"] * 3,
        "game_type": ["REG"] * 6, "carries": [0] * 6, "rushing_yards": [0] * 6,
        "rushing_tds": [0] * 6, "receptions": [2, 3, 5, 6, 8, 9],
        "targets": [4, 5, 8, 9, 12, 13], "receiving_yards": [20, 30, 60, 70, 110, 120],
        "receiving_tds": [0, 0, 1, 0, 1, 1], "receiving_air_yards": [30.0] * 6,
        "fantasy_points_ppr": [4.0, 6.0, 12.0, 13.0, 21.0, 24.0]}))
    monkeypatch.setattr(aa, "load_player", lambda pid: g)
    html = _card(_routes, "workload")
    assert 'class="n alt-heat alt-worst"' in html and 'class="n alt-heat alt-best"' in html
    assert re.search(r'style="--h: 0%"', html) and f'style="--h: {aa._HEAT_MAX}%"' in html
    assert "alt-trend alt-trend-good" in html and "vs 2021" in html     # an arrow with its title
    assert 'class="alt-chipnote alt-chipnote-plain" title="Targets /g: ' in html and ">Best: 2022<" in html
    by = _card(_routes, "by_opponent")
    assert 'class="n alt-share"' in by and "% of the total" in by and "--w: 100%" in by and "alt-heat" not in by


def test_cards_are_their_own_sections_outside_the_search_and_filter_card(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    panel = html.index('<section class="card alt-panel">')
    panel_end = html.index("</section>", panel)                 # the search and filter card
    form_end = html.index("</form>", html.index('<form id="alt-builder-form"'))
    grid = html.index('id="alt-cards"')
    assert form_end < panel_end < grid                           # the form closes before the cards
    assert panel < html.index("<h4>Add a card") < form_end       # the builder is in the top card
    ids = re.findall(r'<section class="card alt-card" data-card="([a-z_]+)"', html)
    assert ids == [c["id"] for c in aa.cards_for("WR")]          # one real card section each
    assert html.count('<section class="card alt-card') == len(ids)
    assert html.rstrip().endswith("</div>") and 'id="alt-builder" class="alt-root"' in html


def test_the_card_builder_controls_are_inside_the_form_and_added_cards_are_tied_to_it(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    form = html[html.index('<form id="alt-builder-form"'):html.index("</form>", html.index('<form id="alt-builder-form"'))]
    for name in ("measures", "agg", "group_by"):
        assert f'name="{name}"' in form, name                    # no form= trick needed any more
    assert 'form="alt-builder-form"' not in form
    assert "keep.setAttribute('form', 'alt-builder-form')" in html   # an added card's hidden spec
    assert "root.addEventListener(ev" in html




# -- cards the user adds -----------------------------------------------------------------

def test_custom_title_names_the_first_stats_and_how_they_are_shown():
    t = aa.custom_title({"measures": ["targets", "receiving_yards"], "agg": "per_game",
                         "group_by": "season"})
    assert t == "Targets, Rec yds \u00b7 per game, by season"
    many = aa.custom_title({"measures": ["targets", "receptions", "receiving_yards", "catch_rate"],
                            "agg": "total", "group_by": None})
    assert many == "Targets, Rec, Rec yds +1 \u00b7 total, career"
    assert aa.custom_title({"measures": ["attempts"], "agg": "total", "group_by": "man_zone"}).endswith("by man or zone")


def test_parse_custom_cards_keeps_valid_unique_specs_and_drops_the_rest():
    import json
    good = json.dumps({"measures": ["targets"], "agg": "per_game", "group_by": "season"})
    raw = [good, good, "not json", json.dumps({"measures": ["nope"]}), json.dumps({"measures": []}),
           json.dumps({"measures": ["targets"], "agg": "weekly"}),
           json.dumps({"measures": ["receptions"], "group_by": "opponent"})]
    cards = aa.parse_custom_cards(raw)
    assert [c["spec"]["measures"] for c in cards] == [["targets"], ["receptions"]]
    assert cards[0]["spec"] == {"measures": ["targets"], "agg": "per_game", "group_by": "season"}
    assert cards[1]["spec"]["agg"] == "total"                    # the default
    assert cards[0]["title"] == aa.custom_title(cards[0]["spec"])
    assert aa.parse_custom_cards([]) == [] and aa.parse_custom_cards(None) == []


def test_parse_custom_cards_stops_at_the_limit():
    import json
    raw = [json.dumps({"measures": ["targets"], "agg": "total", "group_by": g})
           for g in ("season", "opponent", "home_away", "game_type", "week", "man_zone", "coverage", "route")]
    assert len(aa.parse_custom_cards(raw)) == aa.MAX_CUSTOM_CARDS


def test_builder_renders_the_cards_carried_in_the_query_after_default_ones(_routes):
    import json
    from urllib.parse import quote
    spec = {"measures": ["targets", "receiving_yards"], "agg": "per_game", "group_by": "season"}
    q = ("xcard=" + quote(json.dumps(spec)) + "&xcard=" + quote("garbage")).encode()
    html = _builder(_routes, q="ab", player_id="00-1", _query=q)
    cards = re.findall(r'<section class="card alt-card alt-xcard"[^>]*>', html)
    assert len(cards) == 1 and 'data-card="custom"' in cards[0]      # the invalid one is dropped
    assert json.loads(re.search(r"data-spec='([^']*)'", cards[0]).group(1)) == spec
    assert "Targets, Rec yds \u00b7 per game, by season" in html
    assert html.index('data-card="workload"') < html.index("alt-xcard")  # after the default cards
    hidden = re.search(r'<input type="hidden" form="alt-builder-form" name="xcard" value=\'([^\']*)\'>', html)
    assert hidden and json.loads(hidden.group(1)) == spec           # so Run sends it again
    assert 'data-count="cards">1 added' in html
    none = _builder(_routes, q="ab", player_id="00-1")
    assert "alt-xcard" not in none.split("<script>")[0] and 'data-count="cards" hidden' in none


def test_card_route_names_a_custom_card_for_the_page(_routes):
    html = _card(_routes, "custom", b"measures=targets&measures=receiving_yards&agg=per_game&group_by=season")
    assert 'data-title="Targets, Rec yds \u00b7 per game, by season"' in html
    assert 'data-state="ok"' in html and "Targets /g" in html


def test_page_script_adds_removes_and_caps_cards(_routes):
    html = _builder(_routes, q="ab", player_id="00-1")
    assert f"var MAXC = {aa.MAX_CUSTOM_CARDS};" in html
    assert "Tick at least one stat." in html and "alt-xremove" in html
    assert "function enqueue(el)" in html                         # an added card joins the loading line
    assert "OWN[k]" in html                                       # the builder's stats never leak into a default card
    assert "xcard: 1" in html                                     # nor the carried specs into a card request


def test_card_tables_have_column_dividers():
    from webapp import app as A
    css = (A.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert "#alt-builder .alt-card-table th + th, #alt-builder .alt-card-table td + td" in css
    assert "border-left: 1px solid var(--line)" in css.split("#alt-builder .alt-card-table th + th")[1][:120]


# -- builder restyle: two pickers, applied chips, pills, segmented control -------------

def test_each_picker_is_searchable_and_has_all_and_none_per_group(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    pickers = re.findall(r'<details class="alt-fpick" data-pk="([\w-]+)">', html)
    assert pickers == ["picked-filters", "picked-stats"]
    assert html.count('class="alt-fsearch"') == 2
    groups = [g for g, _ in aa.PICKER_MENU]
    assert html.count('data-bulk="all"') == html.count('data-bulk="none"') == len(groups)
    # the filters picker holds the filter groups only, the stats picker the Stats and Results groups
    filters_menu = html[html.index('data-pk="picked-filters"'):html.index('data-pk="picked-stats"')]
    assert "<h5>Game</h5>" in filters_menu and "<h5>Stats</h5>" not in filters_menu
    stats_menu = html[html.index('data-pk="picked-stats"'):]
    assert "<h5>Stats</h5>" in stats_menu and "<h5>Results</h5>" in stats_menu and "<h5>Game</h5>" not in stats_menu


def test_every_picker_box_still_posts_as_fshow_with_one_sentinel(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert html.count('name="fshow_set"') == 1
    assert len(re.findall(r'name="fshow" value="', html)) == len(aa.PICKER_KEYS)


def test_each_picker_sits_in_its_own_section_header_so_it_never_hides_with_its_body(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    head = re.search(r'<div class="alt-bhead">\s*<h4>Filters .*?</details>', html, re.S).group(0)
    assert 'data-pk="picked-filters"' in head
    add = re.search(r'<div class="alt-bhead">\s*<h4>Add a card .*?</details>', html, re.S).group(0)
    assert 'data-pk="picked-stats"' in add
    # the bodies are what hides when nothing is chosen, not the sections that hold the pickers
    assert 'data-blk="filters-body"' in html and 'data-blk="build-body"' in html
    assert 'class="alt-block alt-filters" data-blk' not in html and 'class="alt-block alt-addcard" data-blk' not in html


def test_applied_filters_get_a_chip_row_beside_run(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    row = re.search(r'<div class="alt-actions">.*?</div>\s*</div>', html, re.S).group(0)
    assert 'class="alt-applied"' in row and 'class="alt-clear"' in row and 'class="nfl-apply alt-run"' in row
    assert row.index("alt-applied") < row.index("alt-clear") < row.index("alt-run")
    for fn in ("function renderApplied()", "function valueText(el)", "alt-achip-x"):
        assert fn in html


def test_stats_and_game_types_are_pills_and_total_per_game_is_segmented(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    assert 'class="alt-mboxes alt-pills"' in html and 'class="alt-types alt-pills"' in html
    assert 'class="alt-seg"' in html
    assert html.count('type="radio" name="agg"') == len(aa.AGGS)
    assert re.search(r'<input type="radio" name="agg" value="total" checked>', html)   # the default stays Total
    assert '<select name="agg"' not in html
    from webapp import app as A
    css = (A.BASE / "static" / "style.css").read_text(encoding="utf-8")
    assert ".alt-pills .adp-check input:checked + span" in css and ".alt-seg input:checked + span" in css


def test_picker_script_closes_others_searches_and_bulk_ticks(_routes):
    html = _builder(_routes, q="solo", player_id="00-1")
    for marker in ("function closePickers(except)", "'toggle'", "'Escape'", "closest(\"[data-bulk]\")",
                   "dispatchEvent(new Event('change'"):
        assert marker in html
    assert "[data-pk=\"picked-stats\"] input[name=fshow][value^=\"m_\"]:checked" in html   # the note follows the stat groups only
    assert "'input[type=radio]'" in html                          # unticking Show resets the segmented control


def test_no_filters_chosen_note_shows_only_when_no_filter_is_ticked(_routes):
    shown = _builder(_routes, q="solo", player_id="00-1")
    assert re.search(r'<p class="alt-fempty" hidden>', shown)
    none = _builder(_routes, q="solo", player_id="00-1", _query=b"fshow_set=1&fshow=m_receiving")
    assert re.search(r'<p class="alt-fempty">No filters chosen: every game counts\.</p>', none)


def test_nothing_chosen_stats_note_is_hidden_when_a_stat_group_is_shown(_routes):
    # (the server forces a group on whenever measures are selected, so the empty state is
    # reached in the browser by unticking, and is covered by the Chromium check)
    html = _builder(_routes, q="solo", player_id="00-1", _query=b"fshow_set=1&fshow=m_receiving")
    assert re.search(r'<p class="alt-fnone" hidden>', html)
