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

def _fake_percentile_profile(season, pos, player_id, source="sleeper", reload=False,
                             stat_mode="total"):
    if player_id == "missing":
        return None
    if player_id == "boom":
        raise RuntimeError("network access blocked in tests")
    return {"season": season, "position": pos, "player_id": player_id,
            "stat_mode": stat_mode,
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


def test_player_field_compare_passes_stat_mode_through(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    seen = {}

    def _spy(season, pos, player_id, source="sleeper", reload=False, stat_mode="total"):
        seen["stat_mode"] = stat_mode
        return _fake_percentile_profile(season, pos, player_id, source, reload, stat_mode)
    monkeypatch.setattr(nflref_summary, "percentile_profile", _spy)
    out = pc.player_field_compare("2025", "RB", ["1"], stat_mode="per_game")
    assert seen["stat_mode"] == "per_game"
    assert out["1"]["stat_mode"] == "per_game"


def test_player_field_compare_defaults_stat_mode_to_total(monkeypatch):
    import webapp.sources.nflref.summary as nflref_summary
    monkeypatch.setattr(nflref_summary, "percentile_profile", _fake_percentile_profile)
    out = pc.player_field_compare("2025", "RB", ["1"])
    assert out["1"]["stat_mode"] == "total"


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

_FAKE_AXIS_TICKS = [{"percentile": p, "value": float(p * 2)} for p in (20, 40, 60, 80, 100)]


def matplotlib_rgb(color):
    import matplotlib.colors as mcolors
    return mcolors.to_rgb(color)


def _plain_texts(ax):
    """The axes' ordinary texts (spoke names, ring values), without the
    per-spoke colour-coded value annotations."""
    from matplotlib.text import Annotation
    return [t for t in ax.texts if not isinstance(t, Annotation)]


def test_plot_player_overlay_snapshot_spoke_values_are_colour_coded_per_player():
    """Under each spoke name, every player's own value appears in that
    player's colour: `(v1 | v2)`."""
    import matplotlib.pyplot as plt
    from matplotlib.text import Annotation

    from sleepermetrics import plots
    players = {"Alice": _snapshot_profile(70.0), "Bob": _snapshot_profile(40.0)}
    players["Bob"]["columns"][0]["value"] = 150.0
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    pieces = [t for t in ax.texts if isinstance(t, Annotation)]
    assert [t.get_text() for t in pieces] == ["(", "180.0", " | ", "150.0", ")"]
    colors = plots.palette(players.keys())
    # Alice has the higher value, so hers is the filled pill (her colour as the
    # fill, white text); Bob's stays plain text in his own colour.
    assert pieces[1].get_bbox_patch().get_facecolor()[:3] == pytest.approx(
        matplotlib_rgb(colors["Alice"]))
    assert pieces[1].get_color() == "#ffffff"
    assert pieces[3].get_color() == colors["Bob"]
    assert pieces[3].get_bbox_patch() is None
    plt.close(fig)


def _snapshot_profile(pct):
    return {"columns": [
        {"key": "fpts_ppr", "label": "PPR pts", "value": 180.0, "percentile": pct,
         "axis_ticks": _FAKE_AXIS_TICKS},
        {"key": "rush_yd", "label": "Rush yds", "value": 900.0, "percentile": pct,
         "axis_ticks": _FAKE_AXIS_TICKS},
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


def test_plot_player_overlay_snapshot_has_no_legend():
    """The snapshot radar draws no legend at all (2026-09 follow-up, user
    request) -- the caller (webapp/app.py) now names every player directly
    in the chart TITLE ("Christian McCaffrey vs Jonathan Taylor") instead, so
    a reader never needs a color-to-player legend to read the chart. This
    superseded an earlier "legend below, not beside" layout fix -- the
    legend itself is gone now, not just repositioned."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": _snapshot_profile(40.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    assert ax.get_legend() is None
    plt.close(fig)


def test_plot_player_overlay_snapshot_title_colors_each_name_to_match_its_polygon():
    """User-reported: with no legend (see the test above), a reader had no
    way to tell which polygon belonged to which player. The title now
    draws each player's name in THEIR OWN chart color (`_colored_vs_title`)
    instead of one flat color -- verify each drawn name appears as its own
    Text artist on the figure, colored to match `palette()`'s assignment
    for that name, and that a plain " vs " separator (not either player's
    color) sits between them."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": _snapshot_profile(40.0)}
    colors = plots.palette(players.keys())
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot",
                                    title="Alice's RB1 vs Bob's RB1")
    by_text = {t.get_text(): t for t in fig.texts}
    assert by_text["Alice's RB1"].get_color() == colors["Alice's RB1"]
    assert by_text["Bob's RB1"].get_color() == colors["Bob's RB1"]
    assert by_text[" vs "].get_color() == plots.T["ink"]
    plt.close(fig)


def test_plot_player_overlay_snapshot_title_segments_are_centered_as_a_group():
    """Regression test: the colored title segments are drawn as SEPARATE
    Text artists (matplotlib has no single-Text multi-color API) that must
    be repositioned to read as one centered line -- verify the leftmost
    segment's left edge and the rightmost segment's right edge are
    symmetric around the figure's horizontal center (x=0.5 in figure
    fraction), not left-aligned or drifted to one side."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": _snapshot_profile(40.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot",
                                    title="Alice's RB1 vs Bob's RB1")
    title_texts = [t for t in fig.texts if t.get_text() in
                   ("Alice's RB1", "Bob's RB1", " vs ")]
    assert len(title_texts) == 3
    fig.canvas.draw()
    boxes = [t.get_window_extent() for t in title_texts]
    left = min(b.x0 for b in boxes)
    right = max(b.x1 for b in boxes)
    fig_width = fig.get_window_extent().width
    center = (left + right) / 2
    assert abs(center - fig_width / 2) < 1.0  # within a pixel of true center
    plt.close(fig)


def test_plot_player_overlay_snapshot_title_single_player_draws_no_separator():
    """A single player (edge case -- callers normally require 2+, but the
    function itself shouldn't crash) draws just their own colored name,
    no " vs " segment."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot",
                                    title="Alice's RB1")
    texts = [t.get_text() for t in fig.texts]
    assert "Alice's RB1" in texts
    assert " vs " not in texts
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


def test_format_pizza_tick_value_percent_key_renders_as_whole_percent():
    """A genuine 0-1 proportion (snap_share/tgt_share) renders as a rounded
    whole-number percentage on the radar's own ring ticks -- shorter text
    than the leaderboard table's 3-decimal fraction, and the fix for a real,
    user-reported collision between two adjacent share spokes' ring labels
    on a dense chart."""
    from sleepermetrics import plots
    assert plots._format_pizza_tick_value("snap_share", 0.7823) == "78%"
    assert plots._format_pizza_tick_value("tgt_share", 0.340) == "34%"


def test_format_pizza_tick_value_non_percent_key_matches_format_stat_value():
    """Every OTHER key (ratios like wopr/racr/pacr included -- see
    _PERCENT_TICK_KEYS's own docstring for why those stay as a ratio, not a
    percentage) falls through to the exact same formatting
    _format_stat_value already gives the leaderboard table."""
    from sleepermetrics import plots
    for key, value in [("ppg_ppr", 21.345), ("rush_yards", 900.0), ("wopr", 1.482)]:
        assert (plots._format_pizza_tick_value(key, value)
                == plots._format_stat_value(key, value))


def test_format_pizza_tick_value_none_is_en_dash():
    from sleepermetrics import plots
    assert plots._format_pizza_tick_value("snap_share", None) == "–"


def test_radar_axes_pizza_mode_draws_alternating_ring_bands():
    """Alternating concentric ring shading (matches the reference chart's own
    look): with 5 rings, every OTHER band is filled starting at the
    innermost, so 3 of the 5 bands (0-20, 40-60, 80-100) get a fill_between
    collection and the other 2 don't."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plt.figure()
    ax, _ = plots._radar_axes(fig, ["A", "B", "C"], pizza=True)
    assert len(ax.collections) == 3
    plt.close(fig)


def test_radar_axes_non_pizza_mode_draws_no_ring_bands():
    """The season-over-season radar's ORIGINAL (non-pizza) mode is
    unaffected -- no band shading, since pizza=False keeps the old shared
    percentile axis this feature never touched."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plt.figure()
    ax, _ = plots._radar_axes(fig, ["A", "B", "C"], pizza=False)
    assert len(ax.collections) == 0
    plt.close(fig)


def test_plot_player_overlay_snapshot_draws_pizza_ticks_per_spoke():
    """Pizza-chart style (see _draw_pizza_ticks): each spoke prints its OWN
    field-value ticks (from axis_ticks), not a shared percentile scale or a
    per-point "value (percentile)" badge -- the earlier design here, now
    superseded. 5 ticks per spoke x 2 spokes = 10 tick-value text labels
    (spoke-NAME labels, e.g. "PPR pts"/"Rush yds", are also ax.text() calls
    now -- see test_..._spoke_names_rotate_with_their_own_angle -- so this
    counts only the ones matching a real axis_ticks value, not every text
    on the axes)."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    # axis_ticks values are p*2 (see _FAKE_AXIS_TICKS): 40, 80, 120, 160, 200 --
    # fpts_ppr is a _RATE_STAT_KEYS key (one decimal: "40.0"), rush_yd a plain
    # default (bare integer: "40"), so both formats must be matched.
    tick_values = {"40", "80", "120", "160", "200",
                  "40.0", "80.0", "120.0", "160.0", "200.0"}
    tick_texts = [t.get_text() for t in ax.texts if t.get_text() in tick_values]
    assert len(tick_texts) == 10
    plt.close(fig)


def test_plot_player_overlay_snapshot_plots_at_scaled_position_not_percentile():
    """The polygon vertex for a spoke is the column's linear `scaled`
    position (so it lines up with the evenly spaced ring values), falling
    back to `percentile` only for a profile that has no `scaled`."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    prof = {"columns": [
        {"key": "rush_yd", "label": "Rush yds", "value": 9.0, "percentile": 60.0,
         "scaled": 8.0, "axis_ticks": _FAKE_AXIS_TICKS},
        {"key": "other_td", "label": "Other TD", "value": 3.0, "percentile": 55.0,
         "axis_ticks": _FAKE_AXIS_TICKS},   # no `scaled` -> falls back
    ]}
    fig = plots.plot_player_overlay({"Alice": prof}, ["rush_yd", "other_td"],
                                    mode="snapshot")
    ax = fig.axes[0]
    ys = list(ax.lines[0].get_ydata())
    assert ys[:2] == [8.0, 55.0]
    plt.close(fig)


def test_plot_player_overlay_snapshot_share_spoke_ticks_render_as_percent():
    """End-to-end: a snap_share/tgt_share spoke's ring ticks render as whole
    percentages ("34%"), not the leaderboard table's 3-decimal fraction
    ("0.340") -- the fix for a real, user-reported collision between two
    adjacent share spokes on a dense chart (shorter text, less to collide
    with a neighbor)."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    ticks = [{"percentile": p, "value": v} for p, v in
             zip((20, 40, 60, 80, 100), (0.05, 0.14, 0.26, 0.34, 0.52))]
    prof = {"columns": [{"key": "tgt_share", "label": "Tgt share", "value": 0.34,
                        "percentile": 80.0, "axis_ticks": ticks}]}
    players = {"Alice's RB1": prof}
    fig = plots.plot_player_overlay(players, ["tgt_share"], mode="snapshot")
    ax = fig.axes[0]
    texts = [t.get_text() for t in ax.texts]
    assert "34%" in texts
    assert "0.340" not in texts
    plt.close(fig)


def test_plot_player_overlay_snapshot_spoke_names_rotate_with_their_own_angle():
    """Spoke-NAME labels (e.g. "Rush yds") are ALSO drawn rotated to their
    own spoke's angle, the same convention/formula as the in-ring value
    ticks -- matplotlib's PolarAxes silently ignores set_rotation() called
    on a REAL theta tick label (confirmed directly: it resets to 0 on every
    draw), so these are drawn as plain ax.text() calls instead, with the
    built-in tick labels hidden. With 4 evenly-spaced spokes, spoke 0 (theta=0,
    "Tgt"-equivalent position) reads horizontal like the reference chart's own
    top spoke, but spoke 1 (theta=90 degrees) must be rotated."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    keys = ["fpts_ppr", "rush_yd", "stat2", "stat3"]
    prof = {"columns": [{"key": k, "label": k, "value": 1.0, "percentile": 70.0,
                        "axis_ticks": _FAKE_AXIS_TICKS} for k in keys]}
    players = {"Alice's RB1": prof}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot")
    ax = fig.axes[0]
    name_texts = {t: t.get_rotation() for t in ax.texts if t.get_text() in keys}
    assert len(name_texts) == 4
    assert set(name_texts.values()) != {0}
    # The real xtick labels are hidden (empty), since they can't be rotated.
    assert all(t.get_text() == "" for t in ax.get_xticklabels())
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_are_not_bold():
    """Ring value labels are normal weight (bold ones crowded each other near
    the hub); only the spoke name stays bold."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    ring_ticks = [t for t in _plain_texts(ax) if t.get_text() != "PPR pts"]
    assert ring_ticks
    assert all(t.get_fontweight() == "normal" for t in ring_ticks)
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_and_spoke_names_are_readably_sized():
    """Ring value ticks (>= 7pt, kept small so inner rings don't collide) and
    spoke-name labels (>= 10pt, bold) -- size-floor regression guard. Spoke
    names are drawn as plain ax.text() (see _radar_axes -- a real theta tick
    label can't be rotated on this projection), so this looks them up by
    matching text content against the stat key/label rather than via
    get_xticklabels(), which is hidden/empty in pizza mode."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    assert all(t.get_fontsize() >= 7 for t in ax.texts)
    spoke_label = next(t for t in ax.texts if t.get_text() == "PPR pts")
    assert spoke_label.get_fontsize() >= 10
    assert spoke_label.get_fontweight() == "bold"
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_rotate_with_their_spoke():
    """Ring value labels are rotated to align with their own spoke's radial
    line (the reference chart's style), not left at the default horizontal
    (rotation=0) regardless of angle. With 4 evenly-spaced spokes, spoke 0
    points straight up (theta=0) and reads horizontal (rotation=0, matching
    the reference chart's own top spoke), but spoke 1 points straight RIGHT
    (theta=90 degrees) and must be rotated -- its numbers read vertically,
    the same way a side spoke's numbers do in the reference image."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    keys = ["fpts_ppr", "rush_yd", "stat2", "stat3"]
    prof = {"columns": [{"key": k, "label": k, "value": 1.0, "percentile": 70.0,
                        "axis_ticks": _FAKE_AXIS_TICKS} for k in keys]}
    players = {"Alice's RB1": prof}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot")
    ax = fig.axes[0]
    rotations = {round(t.get_rotation()) for t in ax.texts}
    assert rotations != {0}
    plt.close(fig)


def test_plot_player_overlay_snapshot_top_spoke_ticks_are_horizontal():
    """Regression test for a real, shipped bug: an earlier rotation formula
    added an unneeded extra 90 degrees (reasoning that spoke 0's OWN
    on-screen position, rotated "up" by set_theta_offset, meant its LABELS
    needed a matching +90 degree rotation too) -- this made every label,
    including the top spoke's, tilt a full quarter-turn off from the
    reference chart's convention (confirmed only by a direct visual
    comparison against the reference image, not by the earlier automated
    checks, which verified non-overlap and right-side-up-ness -- both true
    at the wrong rotation too). The TOP spoke (theta=0) is the reference
    chart's own "already horizontal" case: its ring numbers must render at
    rotation 0, not +/-90."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    assert all(round(t.get_rotation()) % 360 == 0 for t in ax.texts)
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_never_render_upside_down():
    """A tick label's rotation is always normalized into the readable
    right-side-up half (-90 to 90 degrees, mod 360) -- never a raw angle that
    would render the text upside down on the chart's lower half."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    # 8 stat keys -> 8 spokes spanning the full circle, so every quadrant
    # (including the lower half, where an un-normalized rotation would flip
    # the text) is exercised in one render.
    keys = [f"stat{i}" for i in range(8)]
    prof = {"columns": [{"key": k, "label": k, "value": 1.0, "percentile": 70.0,
                        "axis_ticks": _FAKE_AXIS_TICKS} for k in keys]}
    players = {"Alice's RB1": prof}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot")
    ax = fig.axes[0]
    for t in ax.texts:
        norm = t.get_rotation() % 360
        assert norm <= 90 or norm >= 270, f"upside-down rotation: {norm}"
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_va_flips_with_rotation():
    """Regression test for a real, user-reported bug: top-spoke ring numbers
    read fine (clearly outside their own ring), but bottom-spoke ring
    numbers looked wedged BETWEEN rings instead of sitting on their own
    line. Cause: `rotation_mode="anchor"` applies `va` in the text's own
    (rotated, and on the chart's lower half FLIPPED 180 degrees to stay
    right-side-up) local frame, not screen space -- a hardcoded
    `va="bottom"` therefore pushed top-half labels outward (away from
    center, correct) but pushed bottom-half labels inward (toward center,
    wrong) once the same nominal instruction ran through the 180-degree
    flip. Fix: `va` must be "top" for any spoke whose rotation got the
    upside-down correction, "bottom" otherwise, so every label pushes away
    from center in actual screen space. With 8 evenly-spaced spokes, spoke 0
    (theta=0, straight up) gets no flip and must read va="bottom"; spoke 4
    (theta=180 degrees, straight down) gets the flip and must read
    va="top"."""
    import math

    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    keys = [f"stat{i}" for i in range(8)]
    prof = {"columns": [{"key": k, "label": k, "value": 1.0, "percentile": 70.0,
                        "axis_ticks": _FAKE_AXIS_TICKS} for k in keys]}
    players = {"Alice's RB1": prof}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot")
    ax = fig.axes[0]
    # stat0's spoke sits at theta=0 (top, no flip); stat4's sits at
    # theta=pi (bottom, gets the upside-down flip). Ring-tick values are
    # numeric text ("40.0", not "stat0", which is the spoke-NAME label drawn
    # at the same theta but a different radius/style -- exclude it).
    tick_texts = [t for t in _plain_texts(ax) if not t.get_text().startswith("stat")]
    top_texts = [t for t in tick_texts if abs(t.get_position()[0] - 0.0) < 1e-9]
    bottom_texts = [t for t in tick_texts
                    if abs(t.get_position()[0] - math.pi) < 1e-9]
    assert top_texts and bottom_texts
    assert all(t.get_va() == "bottom" for t in top_texts)
    assert all(t.get_va() == "top" for t in bottom_texts)
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_shared_across_players_on_same_spoke():
    """axis_ticks describes the FIELD's distribution, not any one player --
    the same 5 tick labels must appear once per spoke regardless of how many
    players are being compared, not once per player."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0), "Bob's RB1": _snapshot_profile(40.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr", "rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    tick_values = {"40", "80", "120", "160", "200",
                  "40.0", "80.0", "120.0", "160.0", "200.0"}
    tick_texts = [t.get_text() for t in ax.texts if t.get_text() in tick_values]
    assert len(tick_texts) == 10  # still 5 ticks x 2 spokes, not x2 players
    plt.close(fig)


def test_plot_player_overlay_snapshot_no_ticks_for_spoke_missing_axis_ticks():
    """A profile column with no axis_ticks (e.g. an older/stubbed profile)
    draws no ring labels for that spoke rather than raising -- the spoke's
    own NAME label ("Rush yds") still renders regardless, since that comes
    from the caller's stat_keys/labels, not from axis_ticks."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": {"columns": [{"key": "rush_yd", "label": "Rush yds",
                                     "value": 900.0, "percentile": 70.0}]},
        "Bob's RB1": {"columns": []},
    }
    fig = plots.plot_player_overlay(players, ["rush_yd"], mode="snapshot")
    ax = fig.axes[0]
    assert [t.get_text() for t in _plain_texts(ax)] == ["Rush yds"]
    plt.close(fig)


def _series_of(ax, name):
    """A running-total line's plotted points for one player (the points are one
    scatter per player, labelled with the name; the segments between them are
    separate lines so a no-game stretch can be dotted)."""
    cs = [c for c in ax.collections if c.get_label() == name]
    return [float(y) for _x, y in cs[0].get_offsets()] if cs else []


def test_plot_player_overlay_trend_draws_one_line_per_player():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 15.0}],
        "Bob's RB1": [{"week": 1, "pts_ppr": 8.0}],
    }
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend")
    ax = fig.axes[0]
    assert sorted(c.get_label() for c in ax.collections if c.get_label() in players) == sorted(players)
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
    assert [c.get_label() for c in ax.collections if c.get_label() in players] == ["Alice's RB1"]
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


def test_plot_player_overlay_trend_per_game_plots_weekly_values():
    """stat_mode="per_game" (the default trend view) plots each week's own
    value unmodified -- the pre-existing behavior, now reachable by name."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 15.0}]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="per_game")
    ax = fig.axes[0]
    ys = list(ax.lines[0].get_ydata())
    assert ys == pytest.approx([10.0, 15.0])
    plt.close(fig)


def test_plot_player_overlay_trend_total_plots_cumulative_sum():
    """stat_mode="total" draws the running season total through each week,
    not that week's own value -- the toggle's other half."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 15.0},
                               {"week": 3, "pts_ppr": 5.0}]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="total")
    ax = fig.axes[0]
    ys = _series_of(ax, "Alice's RB1")
    assert ys == pytest.approx([10.0, 25.0, 30.0])
    plt.close(fig)


def test_plot_player_overlay_trend_cumulative_is_per_player_independent():
    """Each player's running total is its own -- one player's cumulative sum
    must not leak into another's line."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {
        "Alice's RB1": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 10.0}],
        "Bob's RB1": [{"week": 1, "pts_ppr": 3.0}, {"week": 2, "pts_ppr": 3.0}],
    }
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="total")
    ax = fig.axes[0]
    assert _series_of(ax, "Alice's RB1") == pytest.approx([10.0, 20.0])
    assert _series_of(ax, "Bob's RB1") == pytest.approx([3.0, 6.0])
    plt.close(fig)


def test_plot_player_overlay_unrecognized_mode_degrades():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({"Alice's RB1": _snapshot_profile(70.0)},
                                      ["fpts_ppr"], mode="bogus")
    assert fig is not None
    plt.close(fig)


# --- radar: leader highlight and grouped spokes ----------------------------

def _prof(**values):
    return {"columns": [{"key": k, "label": k, "value": v, "percentile": 50.0,
                         "higher_is_better": k not in ("pts_allow", "yds_allow"),
                         "axis_ticks": _FAKE_AXIS_TICKS} for k, v in values.items()]}


def test_spoke_leaders_best_ties_and_direction():
    from sleepermetrics import plots
    players = {"A": _prof(carries=10.0, pts_allow=20.0), "B": _prof(carries=14.0, pts_allow=24.0),
               "C": _prof(carries=14.0, pts_allow=24.0)}
    assert plots._spoke_leaders(players, "carries") == {"B", "C"}      # a tie leads together
    assert plots._spoke_leaders(players, "pts_allow") == {"A"}         # lower is better


def test_spoke_leaders_nobody_leads_with_one_value_or_all_equal():
    from sleepermetrics import plots
    assert plots._spoke_leaders({"A": _prof(carries=10.0)}, "carries") == set()
    assert plots._spoke_leaders({"A": _prof(carries=10.0), "B": _prof(carries=10.0)}, "carries") == set()
    assert plots._spoke_leaders({"A": _prof(carries=10.0), "B": None}, "carries") == set()


def test_grouped_spoke_order_keeps_related_stats_adjacent():
    from sleepermetrics import plots
    jumbled = ["pts_allow", "sacks", "ints", "safeties", "qb_hits", "forced_fumbles", "tackles"]
    out = plots._grouped_spoke_order(jumbled)
    assert out == ["sacks", "qb_hits", "tackles", "ints", "forced_fumbles", "pts_allow", "safeties"]
    # an offensive list already in group order is left exactly as it was
    off = ["targets", "receptions", "rec_yards", "carries", "rush_yards", "snap_share"]
    assert plots._grouped_spoke_order(off) == off
    # a stat in no group goes last, in its original relative position
    assert plots._grouped_spoke_order(["mystery", "carries", "other"]) == ["carries", "mystery", "other"]


def test_spoke_group_runs():
    from sleepermetrics import plots
    keys = ["targets", "receptions", "carries", "snap_share", "mystery"]
    assert plots._spoke_group_runs(keys) == [("Receiving", 0, 1), ("Rushing", 2, 2), ("Usage", 3, 3)]


def test_snapshot_radar_orders_spokes_by_group_and_draws_separators():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"A": _prof(snap_share=0.7, carries=12.0, targets=5.0),
               "B": _prof(snap_share=0.6, carries=9.0, targets=6.0)}
    fig = plots.plot_player_overlay(players, ["snap_share", "carries", "targets"], mode="snapshot")
    ax = fig.axes[0]
    spoke_names = {"targets", "carries", "snap_share"}      # the fake profile labels each spoke by its key
    names = [t.get_text() for t in _plain_texts(ax) if t.get_text() in spoke_names]
    assert names == ["targets", "carries", "snap_share"]    # Receiving, Rushing, Usage
    assert len(ax.lines) == 2 + 3                            # two players + three group boundaries
    plt.close(fig)


def test_snapshot_radar_single_group_has_no_separators():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"A": _prof(carries=12.0, rush_yards=50.0), "B": _prof(carries=9.0, rush_yards=70.0)}
    fig = plots.plot_player_overlay(players, ["carries", "rush_yards"], mode="snapshot")
    assert len(fig.axes[0].lines) == 2
    plt.close(fig)


# --- trend chart: readable axes, gaps, direct labels ------------------------

def test_trend_axis_label_title_and_integer_week_ticks():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice": [{"week": w, "pts_ppr": 10.0 + w} for w in (1, 2, 3, 4)]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", title="RB 2025",
                                    stat_mode="per_game")
    ax = fig.axes[0]
    assert ax.get_ylabel() == "PPR points"
    title_texts = [t.get_text() for t in fig.texts] + [ax.get_title(loc="left"), ax.get_title()]
    assert any("RB 2025: PPR points" in s for s in title_texts)
    ticks = [t for t in ax.get_xticks() if 1 <= t <= 4]
    assert ticks == [1, 2, 3, 4]
    plt.close(fig)


def test_trend_per_game_line_breaks_at_a_missed_week_but_cumulative_does_not():
    import math

    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    rows = [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 12.0}, {"week": 5, "pts_ppr": 9.0}]
    fig = plots.plot_player_overlay({"Alice": rows}, ["pts_ppr"], mode="trend", stat_mode="per_game")
    ys = list(fig.axes[0].lines[0].get_ydata())
    assert len(ys) == 4 and math.isnan(ys[2])                 # gap before week 5
    plt.close(fig)
    fig = plots.plot_player_overlay({"Alice": rows}, ["pts_ppr"], mode="trend", stat_mode="total")
    ys = _series_of(fig.axes[0], "Alice")
    assert ys == pytest.approx([10.0, 22.0, 31.0])            # a running total has no gaps
    plt.close(fig)


def test_trend_has_direct_labels_instead_of_a_legend():
    import matplotlib.pyplot as plt
    from matplotlib.text import Annotation

    from sleepermetrics import plots
    players = {"Alice": [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 20.0}],
               "Bob": [{"week": 1, "pts_ppr": 11.0}, {"week": 2, "pts_ppr": 12.0}]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="per_game")
    ax = fig.axes[0]
    assert ax.get_legend() is None
    # End labels have a connector line; the best/worst week labels do not.
    labels = sorted(t.get_text() for t in ax.texts
                    if isinstance(t, Annotation) and t.arrow_patch is not None)
    assert labels == ["Alice  (avg 15.0)", "Bob  (avg 11.5)"]
    plt.close(fig)
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="total")
    labels = sorted(t.get_text() for t in fig.axes[0].texts if isinstance(t, Annotation))
    assert labels == ["Alice  (30)", "Bob  (23)"]          # whole-number totals print as integers
    plt.close(fig)


def test_trend_direct_labels_do_not_overlap_when_lines_end_together():
    import matplotlib.pyplot as plt
    from matplotlib.text import Annotation

    from sleepermetrics import plots
    players = {n: [{"week": 1, "pts_ppr": 10.0}, {"week": 2, "pts_ppr": 10.0 + i * 0.01}]
               for i, n in enumerate(["A", "B", "C"])}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="per_game")
    ax = fig.axes[0]
    ys = sorted(t.xyann[1] for t in ax.texts
                if isinstance(t, Annotation) and t.arrow_patch is not None)
    lo, hi = ax.get_ylim()
    assert all(b - a >= 0.05 * (hi - lo) for a, b in zip(ys, ys[1:]))      # nudged apart
    plt.close(fig)


# --- radar: spoke groups lead with what matters for the position ------------

_OFFENCE_KEYS = ["pass_att", "pass_yards", "targets", "receptions", "carries", "rush_yards",
                 "snap_share"]


def test_spoke_group_order_leads_with_the_positions_main_group():
    from sleepermetrics import plots
    first = lambda pos, keys=_OFFENCE_KEYS: plots._spoke_group_runs(
        plots._grouped_spoke_order(keys, pos))[0][0]
    assert first("QB") == "Passing"
    assert first("RB") == "Rushing"
    assert first("WR") == "Receiving"
    assert first("TE") == "Receiving"
    assert first("rb") == "Rushing"                       # case-insensitive
    assert first("DEF", ["sacks", "ints", "pts_allow", "safeties"]) == "Allowed"


def test_spoke_group_order_full_sequence_per_position():
    from sleepermetrics import plots
    groups = lambda pos, keys: [g for g, _a, _b in plots._spoke_group_runs(
        plots._grouped_spoke_order(keys, pos))]
    keys = ["targets", "carries", "snap_share", "pass_yards"]
    # groups a position does not list follow the listed ones
    assert groups("QB", keys) == ["Passing", "Rushing", "Usage", "Receiving"]
    assert groups("RB", keys) == ["Rushing", "Receiving", "Usage", "Passing"]
    assert groups("WR", keys) == ["Receiving", "Rushing", "Usage", "Passing"]


def test_spoke_group_order_unknown_position_uses_the_default_order():
    from sleepermetrics import plots
    keys = ["carries", "targets", "snap_share"]
    default = plots._grouped_spoke_order(keys)
    assert default == ["targets", "carries", "snap_share"]
    assert plots._grouped_spoke_order(keys, None) == default
    assert plots._grouped_spoke_order(keys, "K") == default


def test_spoke_group_order_keeps_stats_inside_a_group_in_order():
    from sleepermetrics import plots
    out = plots._grouped_spoke_order(["rec_td", "carries", "receptions", "rush_td", "targets",
                                      "rush_yards", "rec_yards"], "RB")
    assert out == ["carries", "rush_yards", "rush_td", "targets", "receptions", "rec_yards", "rec_td"]


def test_snapshot_radar_starts_with_the_positions_main_group():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"A": _prof(targets=5.0, carries=12.0, snap_share=0.7),
               "B": _prof(targets=6.0, carries=9.0, snap_share=0.6)}
    spokes = {"targets", "carries", "snap_share"}
    for pos, expected in (("RB", ["carries", "targets", "snap_share"]),
                          ("WR", ["targets", "carries", "snap_share"])):
        fig = plots.plot_player_overlay(players, ["snap_share", "carries", "targets"],
                                        mode="snapshot", position=pos)
        names = [t.get_text() for t in _plain_texts(fig.axes[0]) if t.get_text() in spokes]
        assert names == expected
        plt.close(fig)


def test_spoke_leaders_fewer_interceptions_leads_even_though_data_says_higher_is_better():
    from sleepermetrics import plots
    players = {"A": _prof(pass_int=0.4), "B": _prof(pass_int=0.9)}
    assert players["A"]["columns"][0]["higher_is_better"] is True        # the data's quirk
    assert plots._spoke_leaders(players, "pass_int") == {"A"}


# --- trend metric selector: table metric -> weekly key, zero fill ------------

def test_trend_raw_key_maps_table_metrics_to_weekly_keys():
    assert pc.trend_raw_key("rush_yards", "RB") == "rush_yd"
    assert pc.trend_raw_key("carries", "RB") == "rush_att"
    assert pc.trend_raw_key("targets", "WR") == "rec_tgt"
    assert pc.trend_raw_key("pass_yards", "QB") == "pass_yd"
    assert pc.trend_raw_key("sacks", "DEF") == "sack"
    assert pc.trend_raw_key("pts_allow", "def") == "pts_allow"        # case-insensitive


def test_trend_raw_key_has_none_for_rates_unknowns_and_fantasy_points():
    for key in ("snap_share", "tgt_share", "rz_touches", "adot", "fpts_ppr", "ppg_ppr",
                "games", "bogus", "", None):
        assert pc.trend_raw_key(key, "RB") is None, key
    assert pc.trend_raw_key("sacks", "RB") is None                    # a DEF stat on an offence request


def test_trend_raw_key_every_offence_and_defence_choice_is_a_real_weekly_key():
    from sleepermetrics import nflstats
    for pos, real in (("RB", nflstats._USAGE_KEYS), ("QB", nflstats._USAGE_KEYS),
                      ("DEF", nflstats._DEF_USAGE_KEYS)):
        for key, _label in pc.trend_choices(pos):
            assert pc.trend_raw_key(key, pos) in real, (pos, key)


def test_trend_choices_per_position():
    rb = [k for k, _ in pc.trend_choices("RB")]
    assert "rush_yards" in rb and "targets" in rb
    assert not {"snap_share", "tgt_share", "adot", "fpts_ppr", "games"} & set(rb)
    assert "pass_yards" in [k for k, _ in pc.trend_choices("QB")]
    assert "sacks" in [k for k, _ in pc.trend_choices("DEF")]


def test_trend_labels_exist_for_every_chartable_weekly_key():
    from sleepermetrics import plots
    for pos in ("RB", "QB", "DEF"):
        for key, _label in pc.trend_choices(pos):
            raw = pc.trend_raw_key(key, pos)
            assert raw in plots._TREND_LABELS, raw


def test_player_trend_zero_fill_makes_a_played_week_zero_not_a_gap(monkeypatch):
    """Sleeper omits a stat that is zero, so a played week lacking the key is a
    real 0; a week with no line at all stays absent."""
    def _raw(season, week):
        return {1: {"1": {"rush_td": 1.0, "pts_ppr": 12.0}},
                2: {"1": {"pts_ppr": 8.0}},                      # played, no rush TD
                3: {}}.get(int(week), {})
    monkeypatch.setattr(pc.nflstats, "raw_week", _raw)
    plain = pc.player_trend(["1"], "2025", stat_keys=["rush_td"], weeks=[1, 2, 3])["1"]
    assert plain == [{"week": 1, "rush_td": 1.0}, {"week": 2}]       # the default: key left out
    filled = pc.player_trend(["1"], "2025", stat_keys=["rush_td"], weeks=[1, 2, 3],
                             zero_fill=True)["1"]
    assert filled == [{"week": 1, "rush_td": 1.0}, {"week": 2, "rush_td": 0.0}]


def test_per_game_trend_marks_best_and_worst_week_and_rolling_average():
    from matplotlib.text import Annotation

    from sleepermetrics import plots
    players = {"Alice": [{"week": w, "pts_ppr": v} for w, v in
                         ((1, 10.0), (2, 30.0), (3, 20.0), (4, 5.0))]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="per_game")
    ax = fig.axes[0]
    notes = [t.get_text() for t in ax.texts
             if isinstance(t, Annotation) and t.arrow_patch is None]
    assert "best 30.0 (wk 2)" in notes and "worst 5.0 (wk 4)" in notes
    # bold rolling line: third point is the mean of the first three games
    rolling = [ln for ln in ax.get_lines() if ln.get_linewidth() > 2.5][0]
    assert list(rolling.get_ydata())[2] == 20.0
    # no week-0 tick from the full-width band lines
    assert 0 not in [int(t) for t in ax.get_xticks()]
    # cumulative mode keeps the plain lines (no best/worst marks)
    fig2 = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="total")
    assert not [t for t in fig2.axes[0].texts if isinstance(t, Annotation) and t.arrow_patch is None]


def test_radar_value_line_sits_on_the_inner_side_on_every_spoke():
    """The name is at the same distance from the centre on every spoke and its
    value line is always closer to the radar than the name: the bottom and left
    labels are flipped to read upright, and the same offset used to put their
    value line OUTSIDE the name, so the label block sat farther out there."""
    import math

    from matplotlib.text import Annotation

    from sleepermetrics import plots
    keys = ["targets", "receptions", "rec_yards", "rec_td", "carries", "rush_yards",
            "rush_td", "snap_share"]
    players = {"A": _prof(**{k: 10.0 + i for i, k in enumerate(keys)}),
               "B": _prof(**{k: 12.0 + i for i, k in enumerate(keys)})}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot", position="WR",
                                    stat_mode="per_game")
    fig.canvas.draw()
    ax = fig.axes[0]
    rend = fig.canvas.get_renderer()
    cx, cy = ax.transData.transform((0, 0))
    ordered = plots._grouped_spoke_order(keys, "WR")
    n = len(ordered)
    name_d, value_d = [], []
    for i, key in enumerate(ordered):
        ang = i / n * 2 * math.pi
        sx, sy = math.sin(ang), math.cos(ang)
        radial = lambda t: (lambda b: (((b.x0 + b.x1) / 2 - cx) * sx + ((b.y0 + b.y1) / 2 - cy) * sy))(
            t.get_window_extent(rend))
        name = [t for t in ax.texts if not isinstance(t, Annotation) and t.get_text() == key][0]
        pieces = [t for t in ax.texts if isinstance(t, Annotation) and abs(t.xy[0] - ang) < 1e-9]
        name_d.append(radial(name))
        value_d.append(sum(radial(t) for t in pieces) / len(pieces))
    assert all(v < nm for v, nm in zip(value_d, name_d))
    assert max(name_d) - min(name_d) < 2          # the name is equally far out everywhere
    assert max(value_d) - min(value_d) < 2        # and so is the value line



# --- running-total trend chart: dotted no-game gaps and the season projection -----

def _total_fig(players, keys=("pts_ppr",), remaining=None):
    from sleepermetrics import plots
    fig = plots.plot_player_overlay(players, list(keys), mode="trend", stat_mode="total",
                                    title="RB 2026", remaining=remaining)
    fig.canvas.draw()
    return fig


def _end_label_texts(fig):
    from matplotlib.text import Annotation
    return [t for t in fig.axes[0].texts if isinstance(t, Annotation) and t.arrow_patch is not None]


def test_total_chart_dots_a_week_with_no_game_and_solid_between_games():
    players = {"A": [{"week": w, "pts_ppr": 10.0} for w in (1, 2, 4, 5)]}      # no game in week 3
    fig = _total_fig(players)
    gids = [ln.get_gid() for ln in fig.axes[0].get_lines()]
    assert gids.count("no-game") == 1                # the one segment across the gap (2 -> 4)
    assert len(gids) == 3                            # 1-2, 2-4 (dotted), 4-5
    assert not [t for t in _end_label_texts(fig) if "on pace" in t.get_text()]


def test_total_chart_projects_to_the_end_of_the_schedule_at_the_current_rate():
    players = {"A": [{"week": w, "rec_yards": 25.0} for w in (1, 2, 3, 4)]}
    fig = _total_fig(players, ("rec_yards",), {"A": {"games": 13, "end_week": 18}})
    labels = [t.get_text() for t in _end_label_texts(fig)]
    assert labels == ["A\n100, on pace for 425"]          # 100 over 4 games = 25 a game, plus 13 more
    dashed = [ln for ln in fig.axes[0].get_lines() if ln.get_gid() == "projection"]
    assert len(dashed) == 1 and list(dashed[0].get_xdata()) == [4, 18]


def test_total_chart_has_no_projection_when_nothing_is_left_or_the_total_is_zero():
    players = {"Done": [{"week": w, "pts_ppr": 5.0} for w in (1, 2, 3)],
               "Zero": [{"week": w, "pts_ppr": 0.0} for w in (1, 2, 3)],
               "Unknown": [{"week": w, "pts_ppr": 5.0} for w in (1, 2, 3)]}
    fig = _total_fig(players, remaining={"Done": {"games": 0, "end_week": 18},
                                         "Zero": {"games": 10, "end_week": 18}})
    assert not [t for t in _end_label_texts(fig) if "on pace" in t.get_text()]
    assert not [ln for ln in fig.axes[0].get_lines() if ln.get_gid() == "projection"]


def test_total_chart_shows_counting_stats_as_integers_and_points_with_a_decimal():
    count = _total_fig({"A": [{"week": w, "rush_td": 1.0} for w in (1, 2)]}, ("rush_td",),
                       {"A": {"games": 15, "end_week": 18}})
    assert [t.get_text() for t in _end_label_texts(count)] == ["A\n2, on pace for 17"]
    pts = _total_fig({"A": [{"week": 1, "pts_ppr": 10.5}, {"week": 2, "pts_ppr": 11.0}]},
                     remaining={"A": {"games": 15, "end_week": 18}})
    assert "21.5, on pace for" in _end_label_texts(pts)[0].get_text()


def test_per_game_chart_ignores_remaining_games():
    from sleepermetrics import plots
    players = {"A": [{"week": w, "pts_ppr": 10.0 + w} for w in (1, 2, 3)]}
    fig = plots.plot_player_overlay(players, ["pts_ppr"], mode="trend", stat_mode="per_game",
                                    remaining={"A": {"games": 10, "end_week": 18}})
    assert not [t for t in _end_label_texts(fig) if "on pace" in t.get_text()]


def test_total_chart_fits_its_labels_for_every_stat_at_every_position():
    """The sweep as a regression test: every stat the trend chart can show for
    every position, three players with long names and totals that are tied or
    zero for some of them.  No label may run off the figure or sit on another."""
    import matplotlib.pyplot as plt
    from matplotlib.text import Text

    from webapp import player_compare as pc
    names = ["Amon-Ra St. Brown", "Jaxon Smith-Njigba", "Christian McCaffrey"]
    checked = 0
    for pos in ("QB", "RB", "WR", "TE", "DEF", "K"):
        for key, _label in pc.trend_choices(pos):
            raw = pc.trend_raw_key(key, pos)
            if not raw:
                continue
            players = {names[0]: [{"week": w, raw: 4.0} for w in (1, 2, 3, 4)],
                       names[1]: [{"week": w, raw: 4.0} for w in (1, 2, 3, 4)],     # tied with the first
                       names[2]: [{"week": w, raw: 0.0} for w in (1, 2, 3, 4)]}     # zero throughout
            left = {n: {"games": 13, "end_week": 18} for n in names}
            fig = _total_fig(players, (raw,), left)
            rend = fig.canvas.get_renderer()
            boxes = sorted((Text.get_window_extent(t, rend) for t in _end_label_texts(fig)),
                           key=lambda b: b.y0)
            assert len(boxes) == 3, (pos, key)
            assert all(b.x1 <= fig.bbox.width for b in boxes), (pos, key, "label past the figure")
            assert all(b2.y0 >= b1.y1 - 1 for b1, b2 in zip(boxes, boxes[1:])), (pos, key, "labels overlap")
            plt.close(fig)
            checked += 1
    assert checked >= 30                                  # the sweep really covered the categories



def test_trend_chart_is_drawn_at_the_shape_the_page_gives_it():
    """The Compare page puts the trend chart beside the square radar in a column
    1.3 times as wide, so the image is drawn 1.3 wide to 1 tall (9.1 x 7.0) and
    the two end up the same height."""
    players = {"A": [{"week": w, "pts_ppr": 10.0} for w in (1, 2, 3)]}
    fig = _total_fig(players)
    w, h = fig.get_size_inches()
    assert round(w / h, 2) == 1.3


def test_radar_sits_close_under_its_title_block():
    """No dead band between the subtitle and the top-most spoke label: the plot
    is moved up until that gap is a few pixels."""
    from matplotlib.text import Text

    from sleepermetrics import plots
    keys = ["targets", "receptions", "rec_yards", "rec_td", "carries", "rush_yards",
            "rush_td", "snap_share"]
    players = {"A": _prof(**{k: 10.0 + i for i, k in enumerate(keys)}),
               "B": _prof(**{k: 12.0 + i for i, k in enumerate(keys)})}
    fig = plots.plot_player_overlay(players, keys, mode="snapshot", position="WR",
                                    stat_mode="per_game")
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    ax = fig.axes[0]
    sub = [t for t in fig.texts if t.get_text().startswith("Filled value")][0]
    label_top = max(Text.get_window_extent(t, rend).y1 for t in ax.texts)
    gap = Text.get_window_extent(sub, rend).y0 - label_top
    assert 0 <= gap <= 12, gap                 # was about 45px before the plot was moved up
