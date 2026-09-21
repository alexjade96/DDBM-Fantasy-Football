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


def test_plot_player_overlay_snapshot_ticks_are_bold():
    """Ring value labels are bold (matching the reference chart's own bold
    ring numbers), not the default/normal font weight."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    assert all(t.get_fontweight() == "bold" for t in ax.texts)
    plt.close(fig)


def test_plot_player_overlay_snapshot_ticks_and_spoke_names_are_readably_sized():
    """Ring value ticks (>= 8pt) and spoke-name labels (>= 10pt, bold) are
    both sized up from an earlier, harder-to-read pass (6.5pt/9pt normal
    weight) -- regression guard for the user-requested size increase. Spoke
    names are drawn as plain ax.text() (see _radar_axes -- a real theta tick
    label can't be rotated on this projection), so this looks them up by
    matching text content against the stat key/label rather than via
    get_xticklabels(), which is hidden/empty in pizza mode."""
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    players = {"Alice's RB1": _snapshot_profile(70.0)}
    fig = plots.plot_player_overlay(players, ["fpts_ppr"], mode="snapshot")
    ax = fig.axes[0]
    assert all(t.get_fontsize() >= 8 for t in ax.texts)
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
    tick_texts = [t for t in ax.texts if not t.get_text().startswith("stat")]
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
    assert [t.get_text() for t in ax.texts] == ["Rush yds"]
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
    ys = list(ax.lines[0].get_ydata())
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
    by_label = {line.get_label(): list(line.get_ydata()) for line in ax.lines}
    assert by_label["Alice's RB1"] == pytest.approx([10.0, 20.0])
    assert by_label["Bob's RB1"] == pytest.approx([3.0, 6.0])
    plt.close(fig)


def test_plot_player_overlay_unrecognized_mode_degrades():
    import matplotlib.pyplot as plt

    from sleepermetrics import plots
    fig = plots.plot_player_overlay({"Alice's RB1": _snapshot_profile(70.0)},
                                      ["fpts_ppr"], mode="bogus")
    assert fig is not None
    plt.close(fig)
