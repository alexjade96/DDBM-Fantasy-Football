"""Network-free tests for webapp.player_profile -- the single-player
aggregator (player-profile Phase 1). Every external call this module makes
(sleepermetrics.players, nflref.board.load, ffadp.board.combine,
draft/metrics functions, webapp.app.league_data) is monkeypatched at its own
module boundary, matching the convention test_ffadp.py/test_nflref.py use.
"""
from __future__ import annotations

import pandas as pd
import pytest

from webapp import player_profile as pp


@pytest.fixture(autouse=True)
def _clear_profile_cache():
    """player_profile() caches its whole result per (player_id, league_id)
    (see _PROFILE_CACHE) -- without this, a later test reusing the same ids
    (e.g. "5995" + "fake_league") would silently see a prior test's cached,
    differently-mocked result instead of exercising its own mocks."""
    pp.clear_profile_cache()
    yield
    pp.clear_profile_cache()


# --- _norm_name --------------------------------------------------------

def test_norm_name_strips_punctuation_and_suffix():
    assert pp._norm_name("Ja'Marr Chase") == "jamarr chase"
    assert pp._norm_name("Odell Beckham Jr.") == "odell beckham"
    assert pp._norm_name(None) == ""


# --- _recent_seasons -----------------------------------------------------

def test_recent_seasons_uses_nfl_state(monkeypatch):
    # sleepermetrics/__init__.py does `from .league import league`, which
    # rebinds the `league` NAME in the package namespace to that FUNCTION --
    # so `sleepermetrics.league` (attribute access) resolves to the
    # function, not the `league` submodule, even via `import
    # sleepermetrics.league as x`. sys.modules still holds the real module
    # (Python's import machinery keys it there regardless), so pull it from
    # there instead of through attribute access.
    import sys
    league_mod = sys.modules["sleepermetrics.league"]
    monkeypatch.setattr(
        league_mod, "nfl_state", lambda: {"league_season": "2026"})
    assert pp._recent_seasons(3) == ["2026", "2025", "2024"]


def test_recent_seasons_falls_back_on_network_failure(monkeypatch):
    import sys
    league_mod = sys.modules["sleepermetrics.league"]

    def _boom():
        raise RuntimeError("network access blocked in tests")
    monkeypatch.setattr(league_mod, "nfl_state", _boom)
    out = pp._recent_seasons(3)
    assert len(out) == 3
    assert all(isinstance(y, str) for y in out)


# --- _current_season / _split_current ---------------------------------------

def test_current_season_matches_recent_seasons_first_entry(monkeypatch):
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2026", "2025", "2024"])
    assert pp._current_season() == "2026"


def test_split_current_separates_by_season_string(monkeypatch):
    rows = [{"season": "2025", "v": 1}, {"season": 2024, "v": 2},
            {"season": "2025", "v": 3}]
    current, past = pp._split_current(rows, "2025")
    assert [r["v"] for r in current] == [1, 3]
    assert [r["v"] for r in past] == [2]


def test_split_current_compares_int_and_str_seasons_equal(monkeypatch):
    """A row's `season` can be an int (nflverse/pandas) or a str (this
    module's own league-scoped rows) -- both must match a str
    current_season the same way."""
    rows = [{"season": 2025, "v": 1}]
    current, past = pp._split_current(rows, "2025")
    assert len(current) == 1 and not past


def test_split_current_empty_input():
    current, past = pp._split_current([], "2025")
    assert current == [] and past == []


# --- _player_identity ------------------------------------------------------

def _fake_players_df():
    return pd.DataFrame([
        {"player_id": "5995", "player_name": "Justice Hill", "position": "RB",
         "team": "BAL", "gsis_id": " 00-0034975"},  # stray leading space
        {"player_id": "7564", "player_name": "Ja'Marr Chase", "position": "WR",
         "team": "CIN", "gsis_id": None},
    ])


def test_player_identity_strips_padded_gsis_id(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("5995")
    assert ident["player_name"] == "Justice Hill"
    assert ident["gsis_id"] == "00-0034975"  # stray space stripped


def test_player_identity_handles_missing_gsis(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("7564")
    assert ident["gsis_id"] is None


def test_player_identity_unknown_player_id(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    ident = pp._player_identity("999999")
    assert ident["player_id"] == "999999"
    assert ident["player_name"] is None


# --- _real_nfl_history -----------------------------------------------------

def test_real_nfl_history_matches_gsis_and_name_fallback(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "player_stats":
            return pd.DataFrame([
                {"player_id": "00-0034975", "player_display_name": "Justice Hill",
                 "position": "RB", "season": season},
                {"player_id": "00-0000000", "player_display_name": "Someone Else",
                 "position": "RB", "season": season},
            ])
        if dataset == "pfr_rush":
            return pd.DataFrame([
                {"pfr_player_id": "HillJu00", "pfr_player_name": "Justice Hill",
                 "position": "RB", "season": season},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = pp._real_nfl_history("00-0034975", "Justice Hill", "RB", ["2025"])
    assert len(out["player_stats"]["rows"]) == 1
    assert out["player_stats"]["best_effort"] is False
    assert len(out["pfr_rush"]["rows"]) == 1
    assert out["pfr_rush"]["best_effort"] is True
    # a dataset with no matching rows still reports the (empty) shape
    assert out["injuries"] == {"rows": [], "best_effort": False}


def test_real_nfl_history_no_gsis_id_still_tries_name_fallback(monkeypatch):
    def _fake_load(dataset, season):
        if dataset == "snap_counts":
            return pd.DataFrame([
                {"pfr_player_id": "X", "player": "Nobody Special",
                 "position": "RB", "season": season},
            ])
        return pd.DataFrame()

    import webapp.sources.nflref.board as nflref_board
    monkeypatch.setattr(nflref_board, "load", _fake_load)

    out = pp._real_nfl_history(None, "Nobody Special", "RB", ["2025"])
    # gsis-bridged datasets get nothing without a gsis_id
    assert out["player_stats"]["rows"] == []
    # name-fallback datasets still work without one
    assert len(out["snap_counts"]["rows"]) == 1


def test_real_nfl_history_degrades_on_nflref_import_failure(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def _boom(name, *a, **k):
        if "nflref" in name:
            raise ImportError("simulated")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _boom)
    assert pp._real_nfl_history("00-0034975", "X", "RB", ["2025"]) == {}


# --- _adp_history ------------------------------------------------------

def test_adp_history_filters_to_one_player(monkeypatch):
    def _fake_combine(season, scoring="ppr", **kw):
        return {"rows": [
            {"sleeper_id": "5995", "player": "Justice Hill", "consensus": 40.0},
            {"sleeper_id": "7564", "player": "Ja'Marr Chase", "consensus": 1.0},
        ]}

    import webapp.sources.ffadp.board as ffadp_board
    monkeypatch.setattr(ffadp_board, "combine", _fake_combine)

    out = pp._adp_history("5995", ["2025", "2024"])
    assert len(out) == 2
    assert all(r["sleeper_id"] == "5995" for r in out)
    assert out[0]["season"] == "2025"


def test_adp_history_skips_seasons_with_no_match(monkeypatch):
    def _fake_combine(season, scoring="ppr", **kw):
        return {"rows": [{"sleeper_id": "7564", "player": "Someone Else"}]}

    import webapp.sources.ffadp.board as ffadp_board
    monkeypatch.setattr(ffadp_board, "combine", _fake_combine)

    assert pp._adp_history("5995", ["2025"]) == []


# --- _percentile_profile_for / _all_season_profiles -------------------------

def test_percentile_profile_for_delegates_to_nflref(monkeypatch):
    calls = []

    def _fake_percentile_profile(season, pos, player_id, source="sleeper"):
        calls.append((season, pos, player_id, source))
        return {"season": season, "position": pos, "player_id": player_id,
                "n_population": 40, "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                                                  "value": 200.0, "percentile": 90.0}]}

    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)

    out = pp._percentile_profile_for("5995", "RB", "2025")
    assert out["n_population"] == 40
    assert calls == [("2025", "RB", "5995", "sleeper")]


def test_percentile_profile_for_returns_none_with_no_position():
    assert pp._percentile_profile_for("5995", None, "2025") is None


def test_percentile_profile_for_degrades_on_error(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary

    def _boom(*a, **k):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr(nflref_summary, "percentile_profile", _boom)
    assert pp._percentile_profile_for("5995", "RB", "2025") is None


def test_all_season_profiles_keys_by_season(monkeypatch):
    def _fake(player_id, position, season):
        pts = {"2023": 60.0, "2024": 75.0, "2025": 90.0}[season]
        return {"season": season, "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                             "value": 200.0, "percentile": pts}],
                "n_population": 40}
    monkeypatch.setattr(pp, "_percentile_profile_for", _fake)

    out = pp._all_season_profiles("5995", "RB", ["2025", "2023", "2024"])
    assert sorted(out) == ["2023", "2024", "2025"]
    assert out["2025"]["columns"][0]["percentile"] == 90.0


def test_all_season_profiles_skips_seasons_with_no_data(monkeypatch):
    def _fake(player_id, position, season):
        return None if season == "2023" else {
            "season": season,
            "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                        "value": 100.0, "percentile": 50.0}],
            "n_population": 40}
    monkeypatch.setattr(pp, "_percentile_profile_for", _fake)

    out = pp._all_season_profiles("5995", "RB", ["2023", "2024"])
    assert list(out) == ["2024"]


# --- _league_history / player_profile (end to end, all sources stubbed) ----

def test_league_history_degrades_when_no_league_data(monkeypatch):
    out = pp._league_history("5995", {})
    assert out == {
        "draft_picks": [], "honors": [], "trade_stints": [],
        "waiver_rows": [], "roster_splits": {},
    }


def test_player_profile_without_league_id_has_no_league_section(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2025"])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})

    out = pp.player_profile("5995")
    assert out["identity"]["player_name"] == "Justice Hill"
    assert out["league"] is None


def test_player_profile_with_league_id_builds_league_section(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})

    fake_season = object()  # never inspected directly -- draft/metrics are stubbed
    monkeypatch.setattr(
        "webapp.app.league_data",
        lambda league_id: {"seasons": {"2025": fake_season}})
    monkeypatch.setattr(
        "sleepermetrics.draft.draft_board",
        lambda s: pd.DataFrame([{"player_id": "5995", "round": 4,
                                  "pick_in_round": 2, "user_name": "rezzu"}]))
    monkeypatch.setattr(
        "sleepermetrics.metrics.player_honors",
        lambda s: [{"player_id": "5995", "managers": {"rezzu"}}])
    monkeypatch.setattr(
        "sleepermetrics.metrics.trade_player_rates", lambda s: [])
    monkeypatch.setattr(
        "sleepermetrics.metrics.waiver_ledger",
        lambda s, top_n=None: pd.DataFrame(
            [{"player_id": "5995", "user_name": "rezzu", "points": 24.1}]))
    monkeypatch.setattr(
        "sleepermetrics.draft._player_team_splits",
        lambda s, ids: {"5995": [{"user_name": "rezzu", "points": 24.1}]})

    out = pp.player_profile("5995", league_id="fake_league")
    lg = out["league"]
    assert len(lg["draft_picks"]) == 1 and lg["draft_picks"][0]["season"] == "2025"
    assert len(lg["honors"]) == 1 and lg["honors"][0]["managers"] == ["rezzu"]
    assert len(lg["waiver_rows"]) == 1
    assert lg["roster_splits"] == {"2025": [{"user_name": "rezzu", "points": 24.1}]}
    # league seasons should widen seasons_covered even past the default window
    assert "2025" in out["seasons_covered"]


def test_player_profile_splits_current_vs_past_seasons(monkeypatch):
    """_build_profile's current/past split (league_current/league_past,
    adp_current/adp_past, and real_nfl[ds]'s current_rows/past_rows) --
    the shape player_profile.html reads to show this season directly and
    push everything else behind a drilldown."""
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2026", "2025", "2024"])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    monkeypatch.setattr(
        pp, "_real_nfl_history",
        lambda *a, **k: {"player_stats": {
            "rows": [{"season": "2026", "v": "new"}, {"season": "2024", "v": "old"}],
            "best_effort": False}})
    monkeypatch.setattr(
        pp, "_adp_history",
        lambda *a, **k: [{"season": "2026", "consensus": 10},
                         {"season": "2024", "consensus": 20}])

    fake_season = object()
    monkeypatch.setattr(
        "webapp.app.league_data",
        lambda league_id: {"seasons": {"2026": fake_season, "2024": fake_season}})
    monkeypatch.setattr(
        "sleepermetrics.draft.draft_board",
        lambda s: pd.DataFrame([{"player_id": "5995", "round": 4,
                                  "pick_in_round": 2, "user_name": "rezzu"}]))
    monkeypatch.setattr("sleepermetrics.metrics.player_honors", lambda s: [])
    monkeypatch.setattr("sleepermetrics.metrics.trade_player_rates", lambda s: [])
    monkeypatch.setattr(
        "sleepermetrics.metrics.waiver_ledger",
        lambda s, top_n=None: pd.DataFrame(columns=["player_id"]))
    monkeypatch.setattr(
        "sleepermetrics.draft._player_team_splits",
        lambda s, ids: {"5995": [{"user_name": "rezzu", "points": 24.1}]}
                       if s is fake_season else {})

    out = pp.player_profile("5995", league_id="fake_league")

    assert out["current_season"] == "2026"
    assert [r["v"] for r in out["real_nfl"]["player_stats"]["current_rows"]] == ["new"]
    assert [r["v"] for r in out["real_nfl"]["player_stats"]["past_rows"]] == ["old"]
    assert [r["consensus"] for r in out["adp_current"]] == [10]
    assert [r["consensus"] for r in out["adp_past"]] == [20]
    # draft_board is stubbed identically for every season, so BOTH 2026 and
    # 2024 draft_picks exist -- confirms the split, not just presence.
    lg_cur = out["league_current"]
    lg_past = out["league_past"]
    assert len(lg_cur["draft_picks"]) == 1 and lg_cur["draft_picks"][0]["season"] == "2026"
    assert len(lg_past["draft_picks"]) == 1 and lg_past["draft_picks"][0]["season"] == "2024"


def test_player_profile_league_section_degrades_on_league_data_failure(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})

    def _boom(league_id):
        raise RuntimeError("simulated failure")
    monkeypatch.setattr("webapp.app.league_data", _boom)

    out = pp.player_profile("5995", league_id="fake_league")
    # a failed league_data() call should not crash the whole profile --
    # league section comes back as the all-empty shape, not None, since
    # league_id WAS given (None means "no league_id passed" specifically)
    assert out["league"] == {
        "draft_picks": [], "honors": [], "trade_stints": [],
        "waiver_rows": [], "roster_splits": {},
    }


# --- caching ---------------------------------------------------------------

def test_player_profile_caches_repeat_calls(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    calls = []

    def _tracked_real_nfl(*a, **k):
        calls.append(1)
        return {}
    monkeypatch.setattr(pp, "_real_nfl_history", _tracked_real_nfl)

    first = pp.player_profile("5995")
    second = pp.player_profile("5995")
    assert len(calls) == 1  # the second call hit the cache, never rebuilt
    assert first is second  # same cached dict object, not just equal


def test_player_profile_fresh_bypasses_cache(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    calls = []

    def _tracked_real_nfl(*a, **k):
        calls.append(1)
        return {}
    monkeypatch.setattr(pp, "_real_nfl_history", _tracked_real_nfl)

    pp.player_profile("5995")
    pp.player_profile("5995", fresh=True)
    assert len(calls) == 2  # fresh=True forced a rebuild


def test_player_profile_cache_keys_by_league_id_too(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    monkeypatch.setattr(
        "webapp.app.league_data", lambda league_id: {"seasons": {}})

    no_league = pp.player_profile("5995")
    with_league = pp.player_profile("5995", league_id="fake_league")
    assert no_league["league"] is None
    assert with_league["league"] is not None  # distinct cache entries


def test_player_profile_cache_expires_after_ttl(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    calls = []

    def _tracked_real_nfl(*a, **k):
        calls.append(1)
        return {}
    monkeypatch.setattr(pp, "_real_nfl_history", _tracked_real_nfl)

    pp.player_profile("5995")
    # simulate the cache entry having aged past the TTL
    key = ("5995", None)
    pp._PROFILE_CACHE[key]["at"] -= pp._PROFILE_TTL + 1
    pp.player_profile("5995")
    assert len(calls) == 2  # expired entry triggered a rebuild


def test_is_cached_false_before_any_call(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    assert pp.is_cached("5995") is False
    assert pp.is_cached("5995", league_id="123") is False


def test_is_cached_true_after_a_real_call(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_percentile_profile_for", lambda *a, **k: None)
    monkeypatch.setattr(pp, "_all_season_profiles", lambda *a, **k: {})
    pp.player_profile("5995")
    assert pp.is_cached("5995") is True
    # a different league_id key must not be reported cached just because
    # the no-league entry is
    assert pp.is_cached("5995", league_id="123") is False


def test_is_cached_false_after_ttl_expiry():
    pp._PROFILE_CACHE[("5995", None)] = {"data": {}, "at": 0}  # ancient
    assert pp.is_cached("5995") is False


# --- percentile_profile / season_profiles wired into player_profile() -----

def test_player_profile_picks_most_recent_season_with_data(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2026", "2025", "2024"])

    # 2026 has no data yet (offseason); 2025 does -- the focus season should
    # land on 2025, the most recent with real data, not 2026.
    def _fake(player_id, position, season):
        return None if season == "2026" else {
            "season": season, "position": position, "player_id": player_id,
            "n_population": 30,
            "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                        "value": 180.0, "percentile": 72.0}]}
    monkeypatch.setattr(pp, "_percentile_profile_for", _fake)

    out = pp.player_profile("5995")
    assert out["focus_season"] == "2025"
    assert out["percentile_profile"]["season"] == "2025"
    assert out["percentile_profile"]["columns"][0]["percentile"] == 72.0


def test_player_profile_includes_season_profiles(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(
        pp, "_all_season_profiles",
        lambda *a, **k: {"2024": {"season": "2024", "columns": [], "n_population": 30},
                         "2025": {"season": "2025", "columns": [], "n_population": 30}})

    out = pp.player_profile("5995")
    assert len(out["season_profiles"]) == 2
    assert out["available_seasons"] == ["2025", "2024"]
    assert out["focus_season"] == "2025"


# --- plots.plot_player_radar (season-overlay radar) -------------------------

def _profile(season, pct):
    return {"season": season, "position": "RB", "player_id": "5995",
           "n_population": 40,
           "columns": [{"key": "fpts_ppr", "label": "PPR pts", "value": 180.0, "percentile": pct},
                       {"key": "snap_share", "label": "Snap share", "value": 0.8, "percentile": pct},
                       {"key": "rz_touches", "label": "RZ touch", "value": 12.0, "percentile": pct}]}


def test_plot_player_radar_draws_a_single_season_figure():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_radar({"2025": _profile("2025", 72.0)}, "2025", "Justice Hill")
    assert fig is not None
    plt.close(fig)


def test_plot_player_radar_overlays_multiple_seasons_with_focus():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    profiles = {"2023": _profile("2023", 40.0), "2024": _profile("2024", 55.0),
               "2025": _profile("2025", 72.0)}
    fig = plots.plot_player_radar(profiles, "2024", "Justice Hill")
    assert fig is not None
    # Focus season's own line plus the two ghosted seasons.
    ax = fig.axes[0]
    assert len(ax.lines) == 3
    plt.close(fig)


def test_plot_player_radar_multi_season_legend_sits_below_not_beside():
    """Same layout fix as plot_player_overlay's own legend: centered BELOW
    the radar, not off to the side pushing the polar axes off-center."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    profiles = {"2023": _profile("2023", 40.0), "2024": _profile("2024", 55.0),
               "2025": _profile("2025", 72.0)}
    fig = plots.plot_player_radar(profiles, "2024", "Justice Hill")
    ax = fig.axes[0]
    legend = ax.get_legend()
    assert legend is not None
    bbox = legend.get_bbox_to_anchor()._bbox
    assert bbox.y0 < 0
    plt.close(fig)


def test_plot_player_radar_long_subtitle_does_not_overflow_the_figure():
    """A long subtitle (this function's own, always-present "Each spoke:
    real stat value..." sentence) must wrap rather than run off a 7in-wide
    centered figure -- a real, shipped regression once the title/subtitle
    moved from left-aligned to centered (an unwrapped long line ran off the
    right edge entirely). Asserts the rendered subtitle text actually
    contains a newline (i.e. textwrap did wrap it, not a no-op)."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_radar({"2025": _profile("2025", 72.0)}, "2025", "Justice Hill")
    subtitle_texts = [t for t in fig.texts if "Each spoke" in t.get_text()]
    assert len(subtitle_texts) == 1
    assert "\n" in subtitle_texts[0].get_text()
    plt.close(fig)


def test_plot_player_radar_defaults_focus_to_most_recent_when_unresolved():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    profiles = {"2023": _profile("2023", 40.0), "2025": _profile("2025", 72.0)}
    fig = plots.plot_player_radar(profiles, "2099", "Justice Hill")
    assert fig._suptitle.get_text().startswith("Justice Hill · 2025")
    plt.close(fig)


def test_plot_player_radar_degrades_on_no_data():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_radar(None, None, "Nobody")
    assert fig is not None
    plt.close(fig)
    fig2 = plots.plot_player_radar({"2025": {"columns": []}}, "2025", "Nobody")
    assert fig2 is not None
    plt.close(fig2)
