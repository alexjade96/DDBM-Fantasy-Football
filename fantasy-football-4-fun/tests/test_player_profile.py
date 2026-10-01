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


def test_scope_to_season_filters_by_season_string(monkeypatch):
    """`_scope_to_season` is the general filter that replaced
    `_split_current` (a fixed current/past SPLIT) once the page's
    "follow-up sections" moved to one shared season dropdown re-scoped
    fresh per request (`scope_profile`) -- see that function's own
    docstring for the full history. It returns ONE filtered list for
    whichever season is picked, not a (current, past) tuple; there is no
    "past" concept left, just "whatever season isn't picked simply isn't
    shown this request"."""
    rows = [{"season": "2025", "v": 1}, {"season": 2024, "v": 2},
            {"season": "2025", "v": 3}]
    assert [r["v"] for r in pp._scope_to_season(rows, "2025")] == [1, 3]
    assert [r["v"] for r in pp._scope_to_season(rows, "2024")] == [2]


def test_scope_to_season_compares_int_and_str_seasons_equal(monkeypatch):
    """A row's `season` can be an int (nflverse/pandas) or a str (this
    module's own league-scoped rows) -- both must match a str
    requested season the same way."""
    rows = [{"season": 2025, "v": 1}]
    assert len(pp._scope_to_season(rows, "2025")) == 1


def test_scope_to_season_empty_input():
    assert pp._scope_to_season([], "2025") == []


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
    # A dataset with no matching rows still reports the (empty) shape,
    # `best_effort=True`: the real gsis_id lookup found nothing (the fake
    # loader returns an empty frame for "injuries"), so it falls through to
    # the name+position best-effort match tier -- same lossy join
    # PFR-bridged datasets always use, just engaged one tier later, per
    # `_real_nfl_history`'s own docstring ("A row found this way is marked
    # best_effort too... only engaged when the real id lookup found
    # nothing"). It's marked best_effort because of which PATH it took,
    # not because it found a match through it.
    assert out["injuries"] == {"rows": [], "best_effort": True}


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


# --- _game_log -----------------------------------------------------------
#
# 2026-09 (Phase 4): _game_log switched from calling team_profile's own
# former hand-written merge functions directly to calling the shared
# reconciliation layer's _offense_players_via_shared/
# _defense_players_via_shared adapters instead -- see _game_log's own
# docstring. Verified equivalent (zero numeric mismatches) across ~2,100
# real player-weeks for 33 real active players (QB/WR/TE and 10 real
# defenders) before this switch landed; these tests are the committed
# regression coverage for that switch, not a replacement for that
# real-data sweep. The former functions themselves (_merge_offense_
# players/_merge_defense_players) were DELETED once this migration landed
# and a repo-wide grep confirmed zero remaining callers anywhere.

def _route_weeks_stub(monkeypatch):
    """`_player_route_weeks` imports `webapp.sources.nflref.board` directly
    (not through `_real_nfl_history`'s own mockable seam) -- stub it to
    `([], set())` so these tests don't need a real/fake route dataset."""
    monkeypatch.setattr(pp, "_player_route_weeks", lambda gsis_id, seasons: ([], set()))


def test_game_log_offense_player_uses_shared_reconciliation(monkeypatch):
    """An offensive player's merged row now carries real `_sources`/
    `_agreed` reconciliation metadata (the real, accepted behavior change
    this migration introduces) -- confirms `_game_log` is actually calling
    `team_profile._offense_players_via_shared`, not the old direct
    `_merge_offense_players` call, which never attached this metadata."""
    _route_weeks_stub(monkeypatch)
    monkeypatch.setattr(pp, "_sleeper_player_weeks", lambda *a, **k: [])

    identity = {"player_id": "1", "gsis_id": "00-0000001",
               "player_name": "Test Back", "position": "RB", "team": "SF"}
    real_nfl = {
        "player_stats": {"rows": [
            {"season": "2025", "week": 1, "player_id": "00-0000001",
             "player_display_name": "Test Back", "position": "RB",
             "recent_team": "SF", "attempts": 0, "carries": 12,
             "rushing_yards": 60, "rushing_tds": 1, "targets": 0,
             "receptions": 0, "receiving_yards": 0, "receiving_tds": 0},
        ], "best_effort": False},
        "ngs_rushing": {"rows": [
            {"season": "2025", "week": 1, "player_gsis_id": "00-0000001",
             "player_display_name": "Test Back", "rush_attempts": 12,
             "rush_yards": 60, "rush_touchdowns": 1},
        ], "best_effort": False},
    }

    out = pp._game_log(identity, real_nfl, ["2025"])
    assert len(out) == 1
    row = out[0]["merged_row"]
    rushing = row.get("rushing") or {}
    assert rushing.get("rushing_yards") == 60
    # The real behavior change: reconciliation metadata now present.
    assert rushing.get("rushing_yards_agreed") is True
    assert "player_stats" in (rushing.get("rushing_yards_sources") or {})
    assert "ngs_rushing" in (rushing.get("rushing_yards_sources") or {})


def test_game_log_defense_player_uses_shared_reconciliation(monkeypatch):
    """A defensive player routes through `_defense_players_via_shared`
    (PFR is defense's only source, so `_agreed` is always True there --
    see that adapter's own docstring) -- confirms the defense branch was
    migrated too, not just the offense one."""
    _route_weeks_stub(monkeypatch)
    monkeypatch.setattr(pp, "_sleeper_player_weeks", lambda *a, **k: [])

    identity = {"player_id": "2", "gsis_id": None,
               "player_name": "Test Backer", "position": "LB", "team": "SF"}
    real_nfl = {
        "pfr_def": {"rows": [
            {"season": "2025", "week": 1, "game_type": "REG", "team": "SF",
             "opponent": "DAL", "pfr_player_name": "Test Backer",
             "pfr_player_id": "TestB00", "def_sacks": 1.0,
             "def_tackles_combined": 9.0, "def_ints": 0.0},
        ], "best_effort": True},
    }

    out = pp._game_log(identity, real_nfl, ["2025"])
    assert len(out) == 1
    row = out[0]["merged_row"]
    defense = row.get("pfr_def") or {}
    assert defense.get("def_sacks") == 1.0
    assert defense.get("def_tackles_combined") == 9.0
    assert defense.get("def_sacks_agreed") is True
    assert defense.get("def_sacks_sources") == {"pfr_def": 1.0}


def test_game_log_offense_reconciled_values_pinned(monkeypatch):
    """Pinned-value regression test for `_offense_players_via_shared`'s
    output on a realistic multi-source offensive week (the shared-layer
    adapter `_game_log` now calls). Originally written as a direct
    equivalence check against the former hand-written
    `_merge_offense_players` (the same comparison the real-data sweep ran
    across ~2,100 real player-weeks before this migration landed); that
    function is now deleted, so the expected values are pinned here
    directly instead of compared live against it."""
    from webapp import team_profile as tp

    role_rows = {
        "player_stats_rushing": [
            {"player_display_name": "Test Back", "season": "2025", "week": 1,
             "team": "SF", "carries": 12, "rushing_yards": 60, "rushing_tds": 1},
        ],
        "ngs_rushing": [
            {"player_display_name": "Test Back", "season": "2025", "week": 1,
             "rush_attempts": 12, "rush_yards": 60, "rush_touchdowns": 1},
        ],
        "snap_counts_offense": [
            {"player": "Test Back", "season": "2025", "week": 1,
             "team": "SF", "position": "RB", "offense_pct": 0.8},
        ],
    }
    roster = [{"player": "Test Back", "position": "RB"}]

    row = tp._offense_players_via_shared(role_rows, roster)["test back"]
    rushing = row["rushing"]
    assert rushing["rushing_yards"] == 60
    assert rushing["carries"] == 12
    assert rushing["rushing_tds"] == 1
    assert rushing["rushing_yards_agreed"] is True
    assert row["position"] == "RB"


def test_game_log_offense_and_defense_both_resolve_via_shared_adapters(monkeypatch):
    """Smoke test confirming `_game_log` produces a real merged row for
    both an offensive and a defensive player, via the shared-layer
    adapters (`_offense_players_via_shared`/`_defense_players_via_shared`)
    -- not asserting the old functions are unreachable (they no longer
    exist at all, so there is nothing left to guard against), just that
    both branches of `_game_log`'s `is_defense` dispatch still work."""
    _route_weeks_stub(monkeypatch)
    monkeypatch.setattr(pp, "_sleeper_player_weeks", lambda *a, **k: [])

    offense_identity = {"player_id": "1", "gsis_id": "00-0000001",
                        "player_name": "Test Back", "position": "RB", "team": "SF"}
    offense_real_nfl = {"player_stats": {"rows": [
        {"season": "2025", "week": 1, "player_id": "00-0000001",
         "player_display_name": "Test Back", "position": "RB", "recent_team": "SF",
         "carries": 12, "rushing_yards": 60, "rushing_tds": 1},
    ], "best_effort": False}}
    offense_log = pp._game_log(offense_identity, offense_real_nfl, ["2025"])
    assert offense_log and offense_log[0]["merged_row"]["rushing"]["rushing_yards"] == 60

    defense_identity = {"player_id": "2", "gsis_id": None,
                        "player_name": "Test Backer", "position": "LB", "team": "SF"}
    defense_real_nfl = {"pfr_def": {"rows": [
        {"season": "2025", "week": 1, "pfr_player_name": "Test Backer",
         "def_sacks": 1.0},
    ], "best_effort": True}}
    defense_log = pp._game_log(defense_identity, defense_real_nfl, ["2025"])
    assert defense_log and defense_log[0]["merged_row"]["pfr_def"]["def_sacks"] == 1.0


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
    def _fake(player_id, position, season, stat_mode="total"):
        pts = {"2023": 60.0, "2024": 75.0, "2025": 90.0}[season]
        return {"season": season, "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                             "value": 200.0, "percentile": pts}],
                "n_population": 40}
    monkeypatch.setattr(pp, "_percentile_profile_for", _fake)

    out = pp._all_season_profiles("5995", "RB", ["2025", "2023", "2024"])
    assert sorted(out) == ["2023", "2024", "2025"]
    assert out["2025"]["columns"][0]["percentile"] == 90.0


def test_all_season_profiles_skips_seasons_with_no_data(monkeypatch):
    def _fake(player_id, position, season, stat_mode="total"):
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
    """2026-09: `player_profile()`/`_build_profile` no longer bake ANY
    current/past split into the cached result at all -- `real_nfl`,
    `adp_history`, and the league section's own rows now carry EVERY
    season at once (see `scope_profile`'s own docstring: "the template's
    own per-dataset current_rows/past_rows and *_current/*_past drilldown
    reads are gone along with the drilldowns themselves"). Re-scoping to
    one season is now `scope_profile()`'s own job, called fresh per
    request, not something baked into the cached profile -- this test now
    covers BOTH halves together: `player_profile()` returns the full
    unscoped multi-season rows, and `scope_profile()` on top of it
    correctly filters to just one season's worth."""
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
    # Unscoped: every season's rows present at once, no current/past split.
    assert [r["v"] for r in out["real_nfl"]["player_stats"]["rows"]] == ["new", "old"]
    assert [r["consensus"] for r in out["adp_history"]] == [10, 20]

    scoped = pp.scope_profile(out, "2026")
    assert [r["v"] for r in scoped["real_nfl"]["player_stats"]["rows"]] == ["new"]
    assert [r["consensus"] for r in scoped["adp_history"]] == [10]

    scoped_past = pp.scope_profile(out, "2024")
    assert [r["v"] for r in scoped_past["real_nfl"]["player_stats"]["rows"]] == ["old"]
    assert [r["consensus"] for r in scoped_past["adp_history"]] == [20]
    # draft_board is stubbed identically for every season, so BOTH 2026 and
    # 2024 draft_picks exist in the unscoped `out["league"]` -- confirms
    # league data covers every season too, same as real_nfl/adp_history.
    assert len(out["league"]["draft_picks"]) == 2
    assert {p["season"] for p in out["league"]["draft_picks"]} == {"2026", "2024"}
    # scope_profile()'s own "league_scoped" splits it to one season, same
    # as everything else this function scopes.
    lg_cur = pp.scope_profile(out, "2026")["league_scoped"]
    lg_past = pp.scope_profile(out, "2024")["league_scoped"]
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
    def _fake(player_id, position, season, stat_mode="total"):
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


def test_plot_player_radar_title_and_subtitle_follow_the_selected_season():
    """Title is "Player (POS) (season)" and the subtitle states the data
    limits ("Comparison against N Active POSs") for the FOCUSED season: both
    N and the year change with the selection, and it stays one short line."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    p24, p25 = _profile("2024", 40.0), _profile("2025", 72.0)
    p24["n_population"], p25["n_population"] = 88, 92
    for focus, n in (("2024", 88), ("2025", 92)):
        fig = plots.plot_player_radar({"2024": p24, "2025": p25}, focus, "Justice Hill")
        pos = p25["position"]
        assert fig._suptitle.get_text() == f"Justice Hill ({pos}) ({focus})"
        subs = [t for t in fig.texts if t.get_text().startswith("Comparison against")]
        assert len(subs) == 1
        assert subs[0].get_text() == f"Comparison against {n} Active {pos}s"
        plt.close(fig)


def test_plot_player_radar_spoke_labels_carry_the_focused_seasons_value():
    """Each spoke name has the focused season's own value on a second line
    ("Rush yds" over "(900)"), and it follows the selection."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    p24, p25 = _profile("2024", 40.0), _profile("2025", 72.0)
    for c in p24["columns"]:
        c["value"] = 111.0
    for c in p25["columns"]:
        c["value"] = 222.0
    for focus, prof in (("2024", p24), ("2025", p25)):
        fig = plots.plot_player_radar({"2024": p24, "2025": p25}, focus, "Justice Hill")
        ax = fig.axes[0]
        texts = {t.get_text() for t in ax.texts if "\n(" in t.get_text()}
        # value formatting follows the ring labels (rate stats keep decimals,
        # share stats print as a percent), so build the expectation the same way
        want = {c["label"] + "\n(" + plots._format_pizza_tick_value(c["key"], c["value"]) + ")"
                for c in prof["columns"]}
        assert texts == want, (texts, want)
        plt.close(fig)


def _scaled_profile(season, value, lo, hi, higher=True, pct=50.0):
    """One-column profile carrying the fields percentile_profile now adds."""
    return {"season": season, "position": "QB", "player_id": "1", "n_population": 70,
            "columns": [{"key": "pass_yards", "label": "Pass yds", "value": value,
                         "percentile": pct, "bounds": [lo, hi],
                         "higher_is_better": higher, "scaled": 50.0,
                         "axis_ticks": []}]}


def test_radar_scales_widen_to_fit_the_players_other_seasons():
    """The focused season's field gives the bounds; another season of the
    SAME player outside that range widens them. Nothing else about the
    profiles changes (percentile/rank stay per-season)."""
    from sleepermetrics import plots
    focus = _scaled_profile("2026", 533.0, 0.0, 844.0, pct=90.0)
    other = _scaled_profile("2025", 4564.0, 0.0, 4707.0, pct=98.9)
    scales = plots._radar_scales({"2025": other, "2026": focus}, focus, ["pass_yards"])
    assert scales["pass_yards"]["hi"] == 4564.0       # widened by the 2025 value
    assert scales["pass_yards"]["lo"] == 0.0
    # percentile data is untouched
    assert focus["columns"][0]["percentile"] == 90.0 and other["columns"][0]["percentile"] == 98.9


def test_radar_scales_not_widened_when_other_seasons_are_inside_the_range():
    from sleepermetrics import plots
    focus = _scaled_profile("2026", 533.0, 0.0, 844.0)
    other = _scaled_profile("2025", 400.0, 0.0, 700.0)
    s = plots._radar_scales({"2025": other, "2026": focus}, focus, ["pass_yards"])["pass_yards"]
    assert (s["lo"], s["hi"]) == (0.0, 844.0)


def test_radar_scales_lower_is_better_keeps_best_at_the_rim():
    from sleepermetrics import plots
    scale = {"lo": 280.0, "hi": 450.0, "higher": False}
    assert plots._scale_position(scale, 280.0) == 100.0
    assert plots._scale_position(scale, 450.0) == 0.0
    ticks = [t["value"] for t in plots._scale_ticks(scale)]
    assert ticks == sorted(ticks, reverse=True) and ticks[-1] == 280.0


def test_plot_player_radar_ghost_season_is_plotted_by_value_on_the_shared_scale():
    """A 4,564-yard ghost season must sit on the rings printed for the
    FOCUS season's (widened) scale -- at the rim -- not at its own season's
    97% position, and the outer ring label must read the widened maximum."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    focus = _scaled_profile("2026", 533.0, 0.0, 844.0, pct=90.0)
    ghost = _scaled_profile("2025", 4564.0, 0.0, 4707.0, pct=98.9)
    ghost["columns"][0]["scaled"] = 97.0
    fig = plots.plot_player_radar({"2025": ghost, "2026": focus}, "2026", "Jared Goff")
    ax = fig.axes[0]
    by_label = {l.get_label(): l for l in ax.lines if l.get_label() in ("2025", "2026")}
    assert by_label["2025"].get_ydata()[0] == pytest.approx(100.0)       # at the rim
    assert by_label["2026"].get_ydata()[0] == pytest.approx(533.0 / 4564.0 * 100)
    ring_texts = {t.get_text() for t in ax.texts}
    assert "4564" in ring_texts          # outer ring = widened max, not 844
    assert "844" not in ring_texts
    plt.close(fig)


def test_with_per_game_attaches_per_game_value_and_keeps_total_percentile():
    """The table keeps season totals (value, percentile, rank) and gains a
    per-game value from the per-game profile; share/rate stats get None."""
    total = {"season": "2026", "columns": [
        {"key": "pass_yards", "label": "Pass yds", "value": 533.0, "percentile": 90.0, "rank": 8},
        {"key": "snap_share", "label": "Snap share", "value": 1.0, "percentile": 85.0, "rank": 1}]}
    per_game = {"season": "2026", "columns": [
        {"key": "pass_yards", "label": "Pass yds", "value": 266.5, "percentile": 70.0},
        {"key": "snap_share", "label": "Snap share", "value": 1.0, "percentile": 85.0}]}
    out = pp._with_per_game(total, per_game)
    cols = {c["key"]: c for c in out["columns"]}
    assert cols["pass_yards"]["per_game"] == 266.5
    assert cols["pass_yards"]["value"] == 533.0 and cols["pass_yards"]["percentile"] == 90.0
    assert cols["snap_share"]["per_game"] is None          # already a rate
    assert total["columns"][0].get("per_game") is None     # input not mutated


def test_with_per_game_degrades_without_a_per_game_profile():
    total = {"season": "2026", "columns": [
        {"key": "pass_yards", "label": "Pass yds", "value": 533.0, "percentile": 90.0}]}
    assert pp._with_per_game(total, None)["columns"][0]["per_game"] is None
    assert pp._with_per_game(None, {"columns": []}) is None


def test_player_profile_builds_total_and_per_game_season_profiles(monkeypatch):
    monkeypatch.setattr(pp, "sleeper_players", _fake_players_df)
    monkeypatch.setattr(pp, "_real_nfl_history", lambda *a, **k: {})
    monkeypatch.setattr(pp, "_adp_history", lambda *a, **k: [])
    monkeypatch.setattr(pp, "_recent_seasons", lambda n=5: ["2025"])
    modes = []

    def _fake(player_id, position, season, stat_mode="total"):
        modes.append(stat_mode)
        return {"season": season, "position": position, "player_id": player_id,
                "n_population": 30, "stat_mode": stat_mode,
                "columns": [{"key": "fpts_ppr", "label": "PPR pts",
                             "value": 10.0 if stat_mode == "per_game" else 180.0,
                             "percentile": 72.0}]}
    monkeypatch.setattr(pp, "_percentile_profile_for", _fake)
    out = pp.player_profile("5995")
    assert sorted(set(modes)) == ["per_game", "total"]
    assert out["season_profiles"]["2025"]["stat_mode"] == "total"
    assert out["season_profiles_per_game"]["2025"]["stat_mode"] == "per_game"


def test_plot_player_radar_per_game_marks_subtitle_and_uses_decimals():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    prof = _scaled_profile("2026", 266.5, 0.0, 422.0)
    fig = plots.plot_player_radar({"2026": prof}, "2026", "Jared Goff", per_game=True)
    subs = [t.get_text() for t in fig.texts if t.get_text().startswith(("Comparison against", "Per game comparison"))]
    assert subs == ["Per game comparison against 70 Active QBs"]
    labels = [t.get_text() for t in fig.axes[0].texts if "\n(" in t.get_text()]
    assert labels == ["Pass yds\n(266.5)"]
    plt.close(fig)
    fig = plots.plot_player_radar({"2026": prof}, "2026", "Jared Goff")
    assert not [t for t in fig.texts if "(per game)" in t.get_text()]
    plt.close(fig)


def test_plot_player_radar_defaults_focus_to_most_recent_when_unresolved():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    profiles = {"2023": _profile("2023", 40.0), "2025": _profile("2025", 72.0)}
    fig = plots.plot_player_radar(profiles, "2099", "Justice Hill")
    assert fig._suptitle.get_text().endswith("(2025)")
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


def test_format_pizza_tick_value_per_game_is_short_and_keeps_decimals():
    from sleepermetrics import plots
    f = plots._format_pizza_tick_value
    assert f("pass_yards", 266.5, True) == "266.5"
    assert f("pass_yards", 26.0, True) == "26"          # trailing zero dropped
    assert f("rush_td", 0.4, True) == "0.4"
    assert f("rush_td", 0.0, True) == "0"
    assert f("rush_td", 0.125, True) == "0.12" or f("rush_td", 0.125, True) == "0.13"
    assert f("snap_share", 0.78, True) == "78%"          # shares stay percents
    assert f("pass_yards", 533.0, False) == "533"        # totals unchanged
