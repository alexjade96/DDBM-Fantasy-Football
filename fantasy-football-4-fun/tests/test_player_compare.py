"""Network-free tests for webapp.player_compare (league-free real-NFL
position comparison, the landing-page tab's data layer), plus
sleepermetrics.plots.plot_player_overlay (the shared chart this module's
data feeds -- tested here rather than in sleepermetrics' own suite, same
precedent test_player_profile.py already sets for plot_player_radar, since
the chart's only real caller is this webapp module).

`player_field_compare` monkeypatches
`webapp.sources.nflref.summary.percentile_profile` at the module boundary;
`player_trend` monkeypatches `sleepermetrics.nflstats.raw_week` the same
way.
"""
from __future__ import annotations

import pytest

from webapp import player_compare as pc


# --- player_field_compare -------------------------------------------------

def _fake_percentile_profile(season, pos, player_id, source="sleeper", reload=False):
    if player_id == "missing":
        return None
    if player_id == "boom":
        raise RuntimeError("network access blocked in tests")
    return {"season": season, "position": pos, "player_id": player_id,
            "columns": [{"key": "fpts_ppr", "label": "Fantasy Pts", "value": 10.0,
                        "percentile": 90.0}]}


def test_player_field_compare_returns_one_entry_per_id(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)
    out = pc.player_field_compare("2025", "RB", ["1", "2"])
    assert set(out) == {"1", "2"}
    assert out["1"]["player_id"] == "1"


def test_player_field_compare_none_for_missing_player(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)
    out = pc.player_field_compare("2025", "RB", ["missing"])
    assert out == {"missing": None}


def test_player_field_compare_degrades_on_exception(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)
    out = pc.player_field_compare("2025", "RB", ["boom"])
    assert out == {"boom": None}


def test_player_field_compare_empty_ids():
    assert pc.player_field_compare("2025", "RB", []) == {}


def test_player_field_compare_weeks_param_is_accepted_but_noop(monkeypatch):
    """weeks= is a forward-looking seam (see the function's own docstring);
    confirm it's accepted without error even though percentile_profile()
    itself ignores it today."""
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)
    out = pc.player_field_compare("2025", "RB", ["1"], weeks=[15, 16, 17])
    assert out["1"]["player_id"] == "1"


# --- player_trend ----------------------------------------------------

def _fake_raw_week(season, week):
    weekly = {
        1: {"1": {"pts_ppr": 10.0, "rush_yd": 80, "rush_att": 15, "rec": 2},
            "2": {"pts_ppr": 5.0, "rush_yd": 40, "rush_att": 10, "rec": 1}},
        2: {"1": {"pts_ppr": 12.0, "rush_yd": 90, "rush_att": 18, "rec": 3}},
        # week 3: player "1" on a bye (absent entirely); player "2" has no row
        3: {},
    }
    return weekly.get(int(week), {})


def test_player_trend_returns_per_player_week_rows(monkeypatch):
    monkeypatch.setattr(pc.nflstats, "raw_week", _fake_raw_week)
    out = pc.player_trend(["1", "2"], "2025", position="RB", weeks=[1, 2, 3])
    assert [r["week"] for r in out["1"]] == [1, 2]
    assert out["1"][0]["pts_ppr"] == 10.0
    assert out["1"][1]["pts_ppr"] == 12.0
    # player "2" only has a week-1 row -- weeks 2 and 3 are absent, not zero-filled
    assert [r["week"] for r in out["2"]] == [1]


def test_player_trend_uses_position_default_keys(monkeypatch):
    monkeypatch.setattr(pc.nflstats, "raw_week", _fake_raw_week)
    out = pc.player_trend(["1"], "2025", position="RB", weeks=[1])
    row = out["1"][0]
    assert set(row) == {"week", "pts_ppr", "rush_yd", "rush_att", "rec"}


def test_player_trend_explicit_stat_keys_override_default(monkeypatch):
    monkeypatch.setattr(pc.nflstats, "raw_week", _fake_raw_week)
    out = pc.player_trend(["1"], "2025", stat_keys=["pts_ppr"], weeks=[1])
    assert set(out["1"][0]) == {"week", "pts_ppr"}


def test_player_trend_missing_stat_key_omitted_not_none(monkeypatch):
    """A key not present on that player's raw_week line (e.g. a passing key
    requested for a RB) is left out of the row, never included as None."""
    monkeypatch.setattr(pc.nflstats, "raw_week", _fake_raw_week)
    out = pc.player_trend(["1"], "2025", stat_keys=["pts_ppr", "pass_yd"], weeks=[1])
    assert "pass_yd" not in out["1"][0]


def test_player_trend_default_weeks_is_1_to_18(monkeypatch):
    seen_weeks = []

    def _spy(season, week):
        seen_weeks.append(week)
        return {}
    monkeypatch.setattr(pc.nflstats, "raw_week", _spy)
    pc.player_trend(["1"], "2025", position="RB")
    assert seen_weeks == list(range(1, 19))


def test_player_trend_degrades_on_raw_week_exception(monkeypatch):
    def _boom(season, week):
        raise RuntimeError("network access blocked in tests")
    monkeypatch.setattr(pc.nflstats, "raw_week", _boom)
    out = pc.player_trend(["1"], "2025", position="RB", weeks=[1, 2])
    assert out == {"1": []}


def test_player_trend_empty_player_ids():
    assert pc.player_trend([], "2025", position="RB", weeks=[1]) == {}


def test_player_trend_unknown_position_falls_back_to_pts_ppr(monkeypatch):
    monkeypatch.setattr(pc.nflstats, "raw_week", _fake_raw_week)
    out = pc.player_trend(["1"], "2025", position="UNKNOWN", weeks=[1])
    assert set(out["1"][0]) == {"week", "pts_ppr"}


# --- plots.plot_player_overlay ----------------------------------------

def _snapshot_profile(pct):
    return {"columns": [
        {"key": "fpts_ppr", "label": "PPR pts", "value": 180.0, "percentile": pct},
        {"key": "rush_yd", "label": "Rush yds", "value": 900.0, "percentile": pct},
    ]}


def test_plot_player_overlay_snapshot_draws_one_polygon_per_player():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": _snapshot_profile(40.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot")
    assert fig is not None
    ax = fig.axes[0]
    assert len(ax.lines) == 2
    plt.close(fig)


def test_plot_player_overlay_snapshot_defaults_stat_keys_from_first_profile():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, [], mode="snapshot")
    assert fig is not None
    plt.close(fig)


def test_plot_player_overlay_snapshot_skips_none_profiles():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": None}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    assert len(ax.lines) == 1
    plt.close(fig)


def test_plot_player_overlay_snapshot_degrades_on_no_players():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({}, ["fpts_ppr"], mode="snapshot")
    assert fig is not None
    plt.close(fig)


def test_plot_player_overlay_snapshot_degrades_when_all_profiles_none():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({"Alice's RB1": None}, ["fpts_ppr"], mode="snapshot")
    assert fig is not None
    plt.close(fig)


# --- radar value labels (stat value + percentile per spoke) ---------------

def test_format_stat_value_share_key_three_decimals():
    from sleepermetrics import plots
    assert plots._format_stat_value("snap_share", 0.7823) == "0.782"


def test_format_stat_value_rate_key_one_decimal():
    from sleepermetrics import plots
    assert plots._format_stat_value("ppg_ppr", 21.345) == "21.3"


def test_format_stat_value_default_key_integer():
    from sleepermetrics import plots
    assert plots._format_stat_value("rush_yards", 900.0) == "900"


def test_format_stat_value_none_is_en_dash():
    from sleepermetrics import plots
    assert plots._format_stat_value("rush_yards", None) == "–"


def test_format_stat_value_non_numeric_is_en_dash():
    from sleepermetrics import plots
    assert plots._format_stat_value("rush_yards", "n/a") == "–"


def test_plot_player_overlay_snapshot_draws_value_and_percentile_text():
    """Regression test for the feature: every spoke's label shows the raw
    stat value AND the percentile, e.g. "900 (70)", not just the bare
    percentile the earlier version of this chart plotted. fpts_ppr is a
    _RATE_STAT_KEYS key (one decimal, matching the leaderboard table's own
    convention), rush_yd is a plain default (integer)."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    texts = [t.get_text() for t in ax.texts]
    assert "180.0 (70)" in texts
    assert "900 (70)" in texts
    plt.close(fig)


def test_plot_player_overlay_snapshot_labels_dodge_own_spoke_tick_text():
    """Regression test for a real, shipped bug: a spoke pointing straight at
    its own tick label (e.g. the top spoke, 12 o'clock) put the value label
    on the SAME angular ray as that tick text -- no radial push distance
    could ever clear it (verified with an isolated single-spoke render
    before the fix). The fix adds a small angular nudge as a fallback; this
    asserts the label's rendered bbox no longer overlaps the tick label's
    for a single top-pointing spoke, the exact case that was broken."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Jahmyr Gibbs": {"columns": [{"key": "rush_td", "label": "Rush TD",
                                      "value": 16.0, "percentile": 97.0}]},
        "Derrick Henry": {"columns": [{"key": "rush_td", "label": "Rush TD",
                                       "value": 3.0, "percentile": 100.0}]},
    }
    fig = plots.plot_player_overlay(players, ["rush_td"], mode="snapshot")
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ax = fig.axes[0]
    tick_bb = ax.get_xticklabels()[0].get_window_extent(rend)
    label_bbs = [t.get_window_extent(rend) for t in ax.texts]
    assert not any(bb.overlaps(tick_bb) for bb in label_bbs)
    plt.close(fig)


def test_plot_player_overlay_snapshot_skips_labels_for_missing_column():
    """A player with no row for a given stat key (a position-specific stat
    the other player's profile doesn't carry) draws no label for that
    spoke rather than a stray "None"/zero label."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": {"columns": [{"key": "rush_yd", "label": "Rush yds",
                                     "value": 900.0, "percentile": 70.0}]},
        "Bob's RB1": {"columns": []},
    }
    fig = plots.plot_player_overlay(players, ["rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    texts = [t.get_text() for t in ax.texts]
    assert texts == ["900 (70)"]
    plt.close(fig)


def test_plot_player_overlay_trend_draws_one_line_per_player():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 15.0}],
        "Bob's RB1": [{"week": 1, "pts_ppr": 8.0}],
    }
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend")
    ax = fig.axes[0]
    assert len(ax.lines) == 2
    plt.close(fig)


def test_plot_player_overlay_trend_skips_players_with_no_rows_for_stat():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": [{"week": 1, "pts_ppr": 10.0}],
        "Bob's RB1": [{"week": 1, "rush_yd": 40}],  # no pts_ppr key at all
    }
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend")
    ax = fig.axes[0]
    assert len(ax.lines) == 1
    plt.close(fig)


def test_plot_player_overlay_trend_degrades_on_no_stat_keys():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({"Alice's RB1": []}, [], mode="trend")
    assert fig is not None
    plt.close(fig)


def test_plot_player_overlay_trend_degrades_when_no_player_has_the_stat():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": [{"week": 1, "rush_yd": 40}]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend")
    assert fig is not None
    plt.close(fig)


def test_plot_player_overlay_unrecognized_mode_degrades():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({"Alice's RB1": _snapshot_profile(70.0)},
                                      ["fpts_ppr"], mode="bogus")
    assert fig is not None
    plt.close(fig)
