"""Charts (matplotlib; mirrors R plots.R theme, palette + flair)."""
from __future__ import annotations

import re
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import headshots, metrics  # noqa: E402
from .season import Season  # noqa: E402


def _identity_rows(ax, labels, images, zoom=0.30, gap_pt=13, ys=None):
    """Icon-then-name axis: every row reads [icon] name  |  bar.

    The names stay real tick labels (so nothing has to re-implement them) but are
    left-aligned into a column, and each row's circular token is hung just to
    their left. Finding where that column starts needs the *rendered* label
    width, so this draws once and measures rather than guessing from character
    counts.

    `ys` overrides the default one-row-per-integer placement (`range(len(labels))`)
    -- needed by any chart that spaces rows non-uniformly (e.g. a gap between
    grouped rows); it must already match whatever y-coordinates the caller drew
    its marks at, since this function doesn't touch the data series.

    Best-effort: a row with no image keeps its plain name, and if nothing loaded
    at all the axis is left exactly as it was.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.transforms import blended_transform_factory
    if not any(im is not None for im in images):
        return
    fig = ax.figure
    ys = list(ys) if ys is not None else list(range(len(labels)))
    ax.set_yticks(ys)
    ax.set_yticklabels(labels)
    for t in ax.get_yticklabels():
        t.set_ha("left")
    fig.canvas.draw()                       # realise the text extents
    maxw_px = max(t.get_window_extent().width for t in ax.get_yticklabels())
    pad = maxw_px * 72.0 / fig.dpi + gap_pt   # px -> pt: where the name column starts
    ax.tick_params(axis="y", pad=pad)
    tr = blended_transform_factory(ax.transAxes, ax.transData)  # x=axes, y=data
    for y, img in zip(ys, images):
        if img is None:
            continue
        # 7.4pt clear of the name column -- matches the R side's 2.6mm.
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (0, y), xycoords=tr,
                            xybox=(-(pad + 7.4), 0), boxcoords="offset points",
                            frameon=False, box_alignment=(1.0, 0.5),
                            pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)


def _portraits(ax, labels, ids, positions, zoom=0.30, ys=None):
    """Icon-then-name axis for a player chart (token = the player's headshot)."""
    _identity_rows(ax, list(labels),
                   [headshots.load(pid, pos, size=72) for pid, pos in zip(ids, positions)],
                   zoom=zoom, ys=ys)

# Validated against the project's categorical color checker (adjacent-pair CVD
# deltaE >= 8, chroma floor, light+dark contrast) -- the old tab10 set failed
# all three (QB-red/RB-green sat right on the deutan confusion line; DEF-brown
# read as flat gray). Order matters: it's the ADJACENT pairing that was
# checked, so keep QB/RB/WR/TE/K/DEF in this order wherever it's consumed.
POS_COLORS = {"QB": "#2a78d6", "RB": "#eb6834", "WR": "#1baf7a",
              "TE": "#eda100", "K": "#e87ba4", "DEF": "#008300"}
MEDAL = ["#f1c40f", "#c8cdd0", "#cd7f32"]  # gold, silver, bronze

# --- theme ----------------------------------------------------------------
# The *structural* chart colours (surface, text, grid, spines, marker edges,
# neutral fills) as switchable tokens, so a dark-mode viewer gets dark charts
# instead of white rectangles punched into a dark page. Semantic hues (position
# colours, medals, luck green/red) read on either ground and stay fixed.
#
# Tokens mirror the web app's CSS variables (style.css) so the charts sit on the
# same surface as the page around them. `set_chart_theme` also pushes the
# implicit colours (legend text, un-themed labels) through matplotlib rcParams,
# so nothing is left defaulting to black-on-dark.
_THEMES = {
    "light": {"bg": "#ffffff", "ink": "#262626", "ink2": "#333333",
              "muted": "#666666", "faint": "#999999", "tick": "#4d4d4d",
              "grid": "#ececec", "spine": "#cccccc", "rule": "#b8b8b8",
              "edge": "#ffffff", "neutral": "#c3c9d0"},
    "dark":  {"bg": "#1a201d", "ink": "#e6ebe8", "ink2": "#d3dad6",
              "muted": "#9aa5a0", "faint": "#7c867f", "tick": "#9aa5a0",
              "grid": "#2b332f", "spine": "#3a443f", "rule": "#4a544f",
              "edge": "#1a201d", "neutral": "#3f4a45"},
}
T = dict(_THEMES["light"])


def set_chart_theme(name: str) -> None:
    """Select the light/dark structural palette for subsequent renders.

    Reassigns the module-level `T` (read by every plot fn) and syncs the
    implicit matplotlib colours via rcParams. Renders are serialised by a lock
    on the caller's side, so the two never cross for concurrent requests.
    """
    global T
    T = dict(_THEMES.get(name, _THEMES["light"]))
    matplotlib.rcParams.update({
        "text.color": T["ink"], "axes.labelcolor": T["muted"],
        "xtick.color": T["tick"], "ytick.color": T["tick"],
        "axes.edgecolor": T["spine"],
        "figure.facecolor": T["bg"], "axes.facecolor": T["bg"],
        "savefig.facecolor": T["bg"], "legend.labelcolor": T["ink2"],
    })


def _avatar_map(s) -> dict:
    """{user_name: avatar url} from the season's accounts frame (best-effort).

    Prefers the account picture (as the Managers panel does), then a custom team
    picture. pandas NaN is truthy, so guard it explicitly or a missing avatar
    would resolve to the float nan.
    """
    import pandas as pd
    a = getattr(s, "accounts", None)
    if a is None or a.empty:
        return {}
    out = {}
    for _, r in a.iterrows():
        url = (r["avatar_url"] if pd.notna(r.get("avatar_url"))
               else r["team_avatar_url"] if pd.notna(r.get("team_avatar_url"))
               else None)
        out[r["user_name"]] = url
    return out


def _row_avatars(ax, names, s, zoom=0.30):
    """Icon-then-name axis for a team chart (token = the manager's avatar)."""
    urls = _avatar_map(s)
    names = list(names)
    _identity_rows(ax, names, [headshots.avatar_image(urls.get(n)) for n in names],
                   zoom=zoom)


def _point_avatars(ax, xs, ys, names, s, zoom=0.5):
    """Draw each manager's avatar as the marker at their (x, y) point.

    Overlays the existing scatter dots, so a manager with no avatar still shows
    their coloured dot underneath. Returns the list of drawn AnnotationBbox
    artists (empty if none), so a caller doing its own label placement can
    pass them to `_place_labels(avoid=...)` -- the avatar's real rendered size
    is much bigger than the underlying data point, and the collision solver
    only dodges the point itself unless told about the image too. Falsy when
    empty, so `if not _point_avatars(...)` callers are unaffected.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    urls = _avatar_map(s)
    drawn = []
    for x, y, n in zip(xs, ys, names):
        img = headshots.avatar_image(urls.get(n))
        if img is None:
            continue
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (x, y), frameon=False,
                            pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)
        drawn.append(ab)
    return drawn


# A stable colour per manager. Was matplotlib's 'Paired' colormap, which
# failed the project's categorical checker outright: 6 of 12 swatches fell
# outside the lightness band (several near-white, e.g. the pale yellow --
# 1.0-1.6:1 contrast against a white chart surface, effectively invisible
# until you read the label beside it) and 2 fell below the chroma floor
# (read as flat gray). This ordered list passes chroma/CVD/contrast on both
# the light and dark chart surfaces (only the aesthetic "ideal dark-mode
# lightness band" check misses, which the fixed cross-theme architecture
# can't fully satisfy without threading `T` through every categorical use --
# not a legibility problem, since contrast still clears 3:1 throughout).
# Beyond 10 names (career-spanning charts can exceed one season's roster) it
# cycles rather than blending into worse colours the way `Paired` did past 12
# -- repeats are an inherent limit of a finite categorical set, not a
# regression, and every chart that uses this also carries avatars/direct
# labels as the real identity channel (the required mitigation for a
# categorical set this wide, which can't pass strict all-pairs CVD
# separation by hue alone).
_MANAGER_HUES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4",
                  "#008300", "#7b5ce0", "#e34948", "#0f9999", "#b5651d"]


def palette(names) -> dict:
    """A stable colour per manager, assigned in sorted-name order."""
    names = sorted(set(names))
    return {n: _MANAGER_HUES[i % len(_MANAGER_HUES)] for i, n in enumerate(names)}


def _finish(fig, ax, title, subtitle=None, xlabel=None, ylabel=None, caption=None,
            grid_axis="x"):
    # A long subtitle (e.g. plot_efficiency's 3-clause one) runs off the right
    # edge of the figure at its natural width -- ax.text has no width limit of
    # its own, and matplotlib's `wrap=True` wraps to the FIGURE width, not the
    # axes' width, so it never fires while the text still starts near x=0.
    # Wrapping explicitly at a fixed character width (measured against this
    # file's usual figsize=(9,6)/9.5pt font) keeps it inside the canvas; the
    # title's own `pad` grows with the wrapped line count so a 2-line subtitle
    # doesn't climb into the title above it (that direction only, since the
    # subtitle is anchored at the axes top and grows upward from there).
    wrapped_subtitle = None
    n_lines = 1
    if subtitle:
        wrapped_subtitle = textwrap.fill(subtitle, width=95, break_long_words=False)
        n_lines = wrapped_subtitle.count("\n") + 1
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold",
                 color=T["ink"], pad=24 + max(0, n_lines - 1) * 13)
    if wrapped_subtitle:
        # A subtitle positioned as an AXES-FRACTION y (e.g. 1.015) scales with the
        # axes' own height in points, while the title's `pad` is a fixed point
        # value -- so the two drift relative to each other per chart, and for a
        # tall axes the subtitle can climb high enough to run into the title
        # (measured: as little as ~0.5px of clearance, sometimes negative).
        # offset_copy anchors it at the axes top and nudges it up by a FIXED
        # point amount instead, so the gap to the title is the same on every
        # chart regardless of axes height.
        from matplotlib.transforms import offset_copy
        trans = offset_copy(ax.transAxes, fig=fig, x=0, y=5, units="points")
        ax.text(0, 1.0, wrapped_subtitle, transform=trans, fontsize=9.5,
                color=T["muted"], va="bottom")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, color=T["muted"])
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, color=T["muted"])
    if caption:
        fig.text(0.99, 0.01, caption, ha="right", fontsize=7, color=T["faint"])
    ax.grid(axis=grid_axis, color=T["grid"], linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors=T["tick"], labelsize=9.5)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(T["spine"])
    fig.tight_layout()
    return fig



# Candidate label placements, tried in order: above, below, either side, then
# the diagonals, then further out. First one that hits nothing wins.
_LABEL_SPOTS = [
    (0, 16, "center", "bottom"), (0, -18, "center", "top"),
    (42, 0, "left", "center"), (-42, 0, "right", "center"),
    (34, 13, "left", "bottom"), (-34, 13, "right", "bottom"),
    (34, -15, "left", "top"), (-34, -15, "right", "top"),
    (0, 30, "center", "bottom"), (0, -32, "center", "top"),
]


def _place_labels(fig, ax, xs, ys, texts, fontsize=8.4, color=None, avoid=()):
    """Annotate scattered points without letting the labels collide.

    A fixed offset works until two teams land in the same corner, and then one
    label prints straight through another. This tries each candidate offset and
    keeps the first whose rendered box clears every label already placed AND
    every marker -- measured from the real text extents, not guessed from string
    length, because the two differ enough to matter at these sizes.

    MUST be called after `_finish`, which runs tight_layout: that resizes the
    axes, so any geometry solved before it is stale by the time it is drawn.
    """
    fig.canvas.draw()
    rend = fig.canvas.get_renderer()
    pix = ax.transData.transform(list(zip(xs, ys)))
    fig_bounds = fig.bbox
    # Seed with any fixed artists that must also be dodged (zone captions etc.),
    # otherwise the solver treats their space as free.
    boxes: list = [a.get_window_extent(rend) for a in avoid]

    def clashes(bb):
        # A point at the edge of the data range (e.g. the rightmost x) can have
        # every candidate spot clear of every OTHER label/marker yet still spill
        # off the canvas itself -- nothing else is out there to collide with, so
        # this must be checked separately from the pairwise clash test below.
        if bb.x0 < fig_bounds.x0 or bb.x1 > fig_bounds.x1 or \
                bb.y0 < fig_bounds.y0 or bb.y1 > fig_bounds.y1:
            return True
        if any(bb.overlaps(o) for o in boxes):
            return True
        return any(bb.x0 - 5 <= px <= bb.x1 + 5 and bb.y0 - 5 <= py <= bb.y1 + 5
                   for px, py in pix)

    # Densest area first: points with the most neighbours are hardest to place,
    # so give them the pick of the spots before the isolated ones take them.
    order = sorted(range(len(xs)), key=lambda i: -sum(
        1 for j in range(len(xs))
        if j != i and abs(pix[j][0] - pix[i][0]) < 90 and abs(pix[j][1] - pix[i][1]) < 55))
    for i in order:
        best = None
        on_canvas_fallback = None      # clashes another label, but not the edge
        for dx, dy, ha, va in _LABEL_SPOTS:
            ann = ax.annotate(texts[i], (xs[i], ys[i]), textcoords="offset points",
                              xytext=(dx, dy), ha=ha, va=va, fontsize=fontsize,
                              color=color or T["ink"], zorder=5,
                              bbox=dict(facecolor=T["bg"], edgecolor="none",
                                        alpha=.75, pad=1.4))
            bb = ann.get_window_extent(rend)
            if not clashes(bb):
                best = (ann, bb)
                break
            off_canvas = bb.x0 < fig_bounds.x0 or bb.x1 > fig_bounds.x1 or \
                bb.y0 < fig_bounds.y0 or bb.y1 > fig_bounds.y1
            if on_canvas_fallback is None and not off_canvas:
                on_canvas_fallback = (ann, bb)
                continue
            ann.remove()
        # Every spot clashes with something -- prefer a spot that only overlaps
        # another label (still readable, just crowded) over the (0, 16) default,
        # which can itself run off the figure edge for an extreme point.
        if best is None and on_canvas_fallback is not None:
            best = on_canvas_fallback
        elif best is None:
            ann = ax.annotate(texts[i], (xs[i], ys[i]), textcoords="offset points",
                              xytext=(0, 16), ha="center", va="bottom",
                              fontsize=fontsize, color=color or T["ink"], zorder=5,
                              bbox=dict(facecolor=T["bg"], edgecolor="none",
                                        alpha=.75, pad=1.4))
            best = (ann, ann.get_window_extent(rend))
        elif on_canvas_fallback is not None and on_canvas_fallback[0] is not best[0]:
            on_canvas_fallback[0].remove()
        boxes.append(best[1])

def _cap(s: Season) -> str:
    return f"Data: Sleeper API  ·  {s.name} {s.season}"


def _medals(ax, d, rank_col, x0):
    """Podium discs (gold/silver/bronze) with rank number for top-3 rows."""
    for i, (_, r) in enumerate(d.iterrows()):
        rk = int(r[rank_col])
        if rk <= 3:
            ax.scatter([x0], [i], s=200, c=MEDAL[rk - 1], edgecolors=T["edge"],
                       linewidths=1.2, zorder=5)
            # Stays dark on both themes: the disc under it is always bright.
            ax.text(x0, i, str(rk), ha="center", va="center", fontsize=8,
                    fontweight="bold", color="#2b2b2b", zorder=6)


def save(fig, path: str) -> str:
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor=T["bg"])
    plt.close(fig)
    return path


def plot_standings(s: Season):
    d = s.standings.sort_values("final_position", ascending=False).reset_index(drop=True)
    # A pre-season / unstarted season has a standings frame with no rows, or
    # rows whose points are all NaN/0 -- `xmax` is then NaN and set_xlim below
    # raises "Axis limits cannot be NaN or Inf". Same guard the other frame-
    # derived charts already carry (plot_efficiency, plot_flex_usage, ...).
    if d.empty or not (d["points"].fillna(0) > 0).any():
        return _no_data(f"No standings for {s.season} yet.")
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(d)), d["points"], color=[pal[n] for n in d["user_name"]],
            height=0.72, zorder=2)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    xmax = d["points"].max()
    for i, (_, r) in enumerate(d.iterrows()):
        star = "  ★" if r["champion"] else ""
        ax.text(r["points"] + xmax * 0.01, i, f"{r['wins']}-{r['losses']}{star}",
                va="center", fontsize=9, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.16)
    return _finish(fig, ax, f"{s.season} Standings",
                   "Bars = total points, in standing order  ·  ★ champion",
                   "Season Points", caption=_cap(s))


def plot_luck(s: Season):
    d = metrics.luck(s).sort_values("luck").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    y = range(len(d))
    colors = ["#2ca02c" if v > 0 else "#d62728" for v in d["luck"]]
    for yi, (_, r) in enumerate(d.iterrows()):
        ax.plot([r["exp_w"], r["wins"]], [yi, yi], color=colors[yi], lw=2.5, alpha=0.5, zorder=1)
    ax.scatter(d["exp_w"], y, color="#a6a6a6", s=65, zorder=2, label="expected (all-play)")
    ax.scatter(d["wins"], y, color=colors, s=95, zorder=3, label="actual")
    for yi, (_, r) in enumerate(d.iterrows()):
        off, ha = (0.15, "left") if r["luck"] > 0 else (-0.15, "right")
        ax.text(r["wins"] + off, yi, f"{r['luck']:+.1f}", va="center", ha=ha,
                fontsize=8, fontweight="bold", color=colors[yi])
    ax.set_yticks(list(y))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    return _finish(fig, ax, "Luck: Actual vs All-Play Expected Wins",
                   "Grey dot = expected wins vs the whole league each week; coloured = actual",
                   "Wins", caption=_cap(s))


def plot_efficiency(s: Season):
    """Cleveland dot plot, not a zero-based bar: a season's efficiency spread
    is usually a tight band (80-90%), so a 0-100 bar buries the real spread
    in a few pixels of length difference -- the same fix already applied to
    the weekly `plot_mgr_efficiency_trend`, ported here for the season view.

    Each season-average dot also gets a faint whisker spanning that manager's
    worst-to-best WEEK -- the average alone can't tell a metronomic 85% every
    week apart from a lurching 60-100%, and those are different stories (same
    "average vs volatility" idea `plot_boom_bust` already applies elsewhere on
    this tab, here applied to efficiency specifically). The axis is honestly
    zoomed to the combined range (averages AND weekly extremes), not just the
    averages, so a whisker is never clipped by an axis sized only for dots.

    The whisker's own two ENDPOINTS now carry small marker caps (2026-08,
    replacing the earlier "-X pts benched" text label) -- a faint bar alone
    tells you a range exists but not exactly where its two ends land without
    hovering/guessing off the axis; a light "|" cap at each end pins the
    actual best/worst week value precisely, the same way a box plot's
    whisker caps do. The bench-points text is dropped entirely rather than
    moved -- it was answering a different question (a season TOTAL cost,
    not a per-week extreme) that the endpoint markers don't replace, and
    keeping both crowded the row; `bench` is still on `d` for any caller
    that wants it, just no longer printed on this chart.

    Each of the three marks now carries its OWN label planted next to IT
    (2026-08, replacing one combined "88.5% (76-97%)" string anchored past
    the whisker's right edge) -- the average % sits beside the average dot,
    the low % beside the low cap, the high % beside the high cap, so a
    reader finds a number by looking at the mark, not by matching a
    parenthetical back to whichever end of the bar it must belong to. The
    low/high labels are vertically offset (low label below its row's
    center line, high label above) since the two caps can sit close
    together -- or even overlap -- for a metronomically consistent manager,
    and same-height labels at nearly the same x would otherwise collide;
    the average label stays vertically centered on its dot, matching the
    convention every other row-label in this chart family already uses.
    Omitted when a manager has no weekly range (a single scored week, or
    missing lineup data), leaving just the centered season-average % label
    as before.
    """
    d = metrics.efficiency(s).sort_values("eff").reset_index(drop=True)
    if d.empty or not d["eff"].notna().any():
        # A just-started season has actual == optimal == 0 for every team, so
        # `eff` is all-NaN -- there is nothing to plot and the axis math below
        # would be NaN.
        return _no_data(f"No lineup data for {s.season} yet.")
    lu = getattr(s, "lineup", None)
    weekly_range = {}
    if lu is not None and {"user_name", "actual", "optimal"}.issubset(
            getattr(lu, "columns", [])):
        wk = lu.copy()
        wk["eff"] = (wk["actual"] / wk["optimal"].clip(lower=1e-9) * 100).clip(upper=100)
        rng = wk.groupby("user_name")["eff"].agg(["min", "max"])
        weekly_range = {n: (float(r["min"]), float(r["max"])) for n, r in rng.iterrows()}
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = matplotlib.colormaps["Greens"]
    lo, hi = float(d["eff"].min()), float(d["eff"].max())
    all_vals = [lo, hi] + [v for rng in weekly_range.values() for v in rng]
    span_lo, span_hi = min(all_vals), max(all_vals)
    norm = mcolors.Normalize(vmin=lo - (hi - lo) * 0.3, vmax=hi + (hi - lo) * 0.1)
    for i, (_, r) in enumerate(d.iterrows()):
        rng = weekly_range.get(r["user_name"])
        if rng and rng[1] > rng[0]:
            ax.plot(rng, [i, i], color=T["neutral"], lw=4, alpha=0.5, zorder=2,
                    solid_capstyle="round")
            # Endpoint caps: a low-key "|" marker pinning the worst/best
            # WEEK exactly, distinct from the season-average dot (below) --
            # smaller and unfilled so they read as a range boundary, not a
            # second data series competing with the average.
            ax.scatter(rng, [i, i], s=55, marker="|", linewidths=1.6,
                       color=T["muted"], zorder=2.5)
    ax.scatter(d["eff"], range(len(d)), s=130, c=[cmap(norm(v)) for v in d["eff"]],
               zorder=3, edgecolors=T["edge"], linewidths=1)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    off = (span_hi - span_lo) * 0.015
    for i, (_, r) in enumerate(d.iterrows()):
        rng = weekly_range.get(r["user_name"])
        has_range = bool(rng and rng[1] > rng[0])
        # Average label: centered on its own row, offset ABOVE the whisker
        # when a range exists (so it never sits on the semi-transparent
        # whisker line passing directly through the row's own y), plain
        # centered when there's no range to avoid.
        ax.text(r["eff"], i + (0.26 if has_range else 0),
                f"{r['eff']:.1f}%", ha="center",
                va="bottom" if has_range else "center",
                fontsize=8, fontweight="bold", color=T["ink2"])
        if has_range:
            # Low/high labels sit INLINE with the whisker (same y as the
            # row, va="center") just outside their own cap -- low label to
            # the LEFT of the low cap, high label to the RIGHT of the high
            # cap (2026-08, replacing a below-the-row placement that pushed
            # the bottom row's labels down far enough to collide with the
            # x-axis itself). Horizontal, not vertical, is the only
            # direction guaranteed clear here: the whisker line the labels
            # sit beside already reserves that row's own y for every
            # manager, top to bottom, so placing labels off to the sides
            # keeps every row's labels inside its own lane regardless of
            # position in the chart.
            ax.text(rng[0] - off, i, f"{rng[0]:.0f}%", ha="right",
                    va="center", fontsize=7.5, color=T["muted"])
            ax.text(rng[1] + off, i, f"{rng[1]:.0f}%", ha="left",
                    va="center", fontsize=7.5, color=T["muted"])
    pad = max((span_hi - span_lo) * 0.15, 1.5)
    ax.set_xlim(span_lo - pad, span_hi + pad)
    return _finish(fig, ax, "Lineup Efficiency",
                   "Darker = better  ·  faint bar spans each manager's worst-to-best week",
                   "Efficiency %", caption=_cap(s))


def plot_pf_pa(s: Season):
    d = metrics.points_for_against(s)
    pal = palette(d["user_name"])
    mx, my = d["points"].median(), d["pa"].median()
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.axvline(mx, ls="--", color=T["rule"], zorder=1)
    ax.axhline(my, ls="--", color=T["rule"], zorder=1)
    sizes = 40 + (d["wins"] - d["wins"].min()) / max(d["wins"].max() - d["wins"].min(), 1) * 220
    ax.scatter(d["points"], d["pa"], s=sizes, c=[pal[n] for n in d["user_name"]],
               alpha=0.9, zorder=3, edgecolors=T["edge"], linewidths=1)
    avatars = _point_avatars(ax, d["points"], d["pa"], d["user_name"], s, zoom=0.44)
    xr = ax.get_xlim(); yr = ax.get_ylim()
    corners = [
        ax.text(xx, yy, lab, ha=ha, va=va, fontsize=9, style="italic", color="#bfbfbf")
        for (xx, yy, ha, va, lab) in [
            (xr[1], yr[0], "right", "bottom", "Dominant"),
            (xr[0], yr[1], "left", "top", "Snakebit"),
            (xr[1], yr[1], "right", "top", "Shootouts"),
            (xr[0], yr[0], "left", "bottom", "Low-event")]]
    fig = _finish(fig, ax, "Points For vs Points Against",
                   "Lower-right beats up the league; upper-left gets snakebit  ·  size = wins",
                   "Points For", "Points Against", caption=_cap(s), grid_axis="both")
    # After _finish (tight_layout has settled the axes) so the collision solver
    # works with final geometry, and avoiding the avatar images themselves --
    # same pattern as plot_boom_bust, needed here for the same reason (avatars
    # cluster tightly enough that a fixed offset prints labels through them).
    _place_labels(fig, ax, list(d["points"]), list(d["pa"]),
                  [f"{r.user_name} ({r.wins}W)" for r in d.itertuples(index=False)],
                  avoid=(*avatars, *corners))
    return fig


def plot_allplay(s: Season):
    """All-play standings (mirrors R sl_plot_allplay)."""
    d = metrics.allplay(s).sort_values("allplay_pct").reset_index(drop=True)
    fill = {"helped": "#2ca02c", "hurt": "#d62728", "even": T["neutral"]}
    fig, ax = plt.subplots(figsize=(9.5, 6))
    colors = [T["neutral"] if v == 0 else ("#2ca02c" if v > 0 else "#d62728")
              for v in d["rank_delta"]]
    ax.barh(range(len(d)), d["allplay_pct"], color=colors, height=0.72, zorder=2)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    for i, (_, r) in enumerate(d.iterrows()):
        gap = "even" if r["rank_delta"] == 0 else f"{r['rank_delta']:+d}"
        ax.text(r["allplay_pct"] + 0.01, i,
                f"{r['allplay_pct'] * 100:.0f}%  ·  finished {int(r['final_position'])} ({gap})",
                va="center", fontsize=9, color=T["ink2"])
    ax.set_xlim(0, 1.38)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v * 100:.0f}%")
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=fill["helped"], label="schedule helped"),
                       Patch(color=fill["hurt"], label="schedule hurt"),
                       Patch(color=fill["even"], label="as deserved")],
              loc="lower right", frameon=False, fontsize=9)
    return _finish(fig, ax, "All-Play Standings",
                   "If everyone played everyone every week  ·  colour = did the real schedule flatter or rob them",
                   "All-Play Win %", caption=_cap(s))


def plot_power_rank(s: Season):
    """Composite power ranking (mirrors R sl_plot_power_rank)."""
    d = metrics.power_rank(s).sort_values("power").reset_index(drop=True)
    # An unstarted season has no power scores -- `span` is then NaN and the
    # set_xlim below raises "Axis limits cannot be NaN or Inf". Same guard the
    # other frame-derived charts carry.
    if d.empty or not d["power"].notna().any():
        return _no_data(f"No power ranking for {s.season} yet.")
    fig, ax = plt.subplots(figsize=(9.5, 6))
    colors = ["#2c7fb8" if v > 0 else "#c0563f" for v in d["power"]]
    ax.barh(range(len(d)), d["power"], color=colors, height=0.72, zorder=2)
    ax.axvline(0, color=T["rule"], zorder=3)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    span = d["power"].max() - d["power"].min()
    for i, (_, r) in enumerate(d.iterrows()):
        off = span * 0.012
        ha = "left" if r["power"] > 0 else "right"
        ax.text(r["power"] + (off if r["power"] > 0 else -off), i,
                f"{r['power']:+.2f}", va="center", ha=ha, fontsize=9, color=T["ink2"])
    ax.set_xlim(d["power"].min() - span * 0.18, d["power"].max() + span * 0.16)
    return _finish(fig, ax, "Power Rankings",
                   "Composite of points, all-play win%, recent form and lineup efficiency  ·  0 = league average",
                   "Power Score (standardised)", caption=_cap(s))


def plot_manager_profile(s: Season):
    """Manager-identity quadrant (mirrors R sl_plot_manager_profile)."""
    d = metrics.manager_profile(s)
    pal = palette(d["user_name"])
    mx, my = d["moves_per_wk"].median(), d["lineup_iq"].median()
    fig, ax = plt.subplots(figsize=(9, 6.4))
    ax.axvline(mx, ls="--", color=T["rule"], zorder=1)
    ax.axhline(my, ls="--", color=T["rule"], zorder=1)
    tmax = max(d["trades"].max(), 1)
    sizes = 60 + d["trades"] / tmax * 300
    ax.scatter(d["moves_per_wk"], d["lineup_iq"], s=sizes,
               c=[pal[n] for n in d["user_name"]], alpha=0.85, zorder=3,
               edgecolors=T["edge"], linewidths=1)
    # Avatar as each manager's marker (dot shows through where none loads).
    avatars = _point_avatars(ax, d["moves_per_wk"], d["lineup_iq"], d["user_name"], s, zoom=0.46)
    # Pad both axes (same idiom as plot_boom_bust) so a point sitting near the
    # data's own min/max doesn't leave the collision solver's left/right label
    # candidates with nowhere to go but through the y-axis tick labels.
    xr = (d["moves_per_wk"].max() - d["moves_per_wk"].min()) or 1
    yr = (d["lineup_iq"].max() - d["lineup_iq"].min()) or 1
    ax.set_xlim(d["moves_per_wk"].min() - xr * 0.15, d["moves_per_wk"].max() + xr * 0.15)
    ax.set_ylim(d["lineup_iq"].min() - yr * 0.15, d["lineup_iq"].max() + yr * 0.15)
    fig = _finish(fig, ax, "Manager Tendencies",
                   "Right = works the wire  ·  up = sets a sharp lineup  ·  bubble = trades made",
                   "Roster Moves per Week", "Lineup IQ (% of optimal)",
                   caption=_cap(s), grid_axis="both")
    # After _finish (tight_layout has settled the axes) so the collision
    # solver works with final geometry, and avoiding the avatar images
    # themselves -- same pattern as plot_boom_bust; two managers landing
    # close together (moves/wk, lineup IQ) used to print one name straight
    # through the other's avatar and label.
    _place_labels(fig, ax, list(d["moves_per_wk"]), list(d["lineup_iq"]),
                  list(d["user_name"]), avoid=avatars)
    return fig


def plot_transaction_volume(s: Season):
    """Player movements per week, stacked by type -- how busy the league was,
    and when. The dashed line is the season average total, covering "average"
    without a second chart; per-manager averages already live on
    `plot_manager_profile`'s moves_per_wk axis.
    """
    d = metrics.transaction_volume(s)
    if not d:
        return _no_data(f"No transactions in {s.season}.")
    weeks = [r["week"] for r in d]
    trades = [r["trades"] for r in d]
    waivers = [r["waivers"] for r in d]
    fa = [r["free_agent"] for r in d]
    totals = [r["total"] for r in d]
    avg = sum(totals) / len(totals) if totals else 0
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.bar(weeks, trades, width=0.68, color="#c0563f", zorder=2, label="Trades")
    bottom = list(trades)
    ax.bar(weeks, waivers, width=0.68, bottom=bottom, color="#2c7fb8", zorder=2, label="Waivers")
    bottom = [b + w for b, w in zip(bottom, waivers)]
    ax.bar(weeks, fa, width=0.68, bottom=bottom, color=T["neutral"], zorder=2, label="Free agent")
    ax.axhline(avg, ls="--", lw=1.4, color=T["rule"], zorder=3)
    ax.text(weeks[-1] + 0.6, avg, f"avg {avg:.1f}", va="center", fontsize=8.5, color=T["muted"])
    ax.set_xticks(weeks)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    return _finish(fig, ax, "Transaction Volume by Week",
                   "Player movements each week, split by type  ·  dashed line = season average",
                   "Week", "Movements", caption=_cap(s), grid_axis="y")


def plot_consistency(s: Season):
    order = metrics.consistency(s).sort_values("median")["user_name"].tolist()
    pal = palette(s.team_wk["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    data = [s.team_wk.loc[s.team_wk["user_name"] == n, "points"].values for n in order]
    bp = ax.boxplot(data, vert=False, patch_artist=True, widths=0.55,
                    showfliers=False, medianprops=dict(color=T["ink2"]))
    for patch, n in zip(bp["boxes"], order):
        patch.set_facecolor(pal[n])
        patch.set_alpha(0.5)
    for i, n in enumerate(order):
        pts = s.team_wk.loc[s.team_wk["user_name"] == n, "points"].values
        ax.scatter(pts, [i + 1] * len(pts), color=pal[n], alpha=0.65, s=20, zorder=3)
    ax.set_yticks(range(1, len(order) + 1))
    ax.set_yticklabels(order)
    return _finish(fig, ax, "Consistency: Weekly Score Distributions",
                   "Tight box = steady  ·  wide = boom-or-bust",
                   "Weekly Points", caption=_cap(s))


def plot_career(seasons: dict):
    """Career standings, ranked by win %. Colour is a sequential ramp on the
    bar's own value (darker = higher win %) rather than a categorical colour
    per manager -- one ranked series with names already on the axis, so
    hue-per-manager was decorative.
    """
    d = metrics.career(seasons).copy()
    d["rank"] = d["win_pct"].rank(ascending=False, method="first").astype(int)
    d = d.sort_values("win_pct").reset_index(drop=True)
    cmap = matplotlib.colormaps["Blues"]
    norm = mcolors.Normalize(vmin=-20, vmax=100)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(d)), d["win_pct"], color=[cmap(norm(v)) for v in d["win_pct"]],
            height=0.72, zorder=2)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _medals(ax, d, "rank", 3.5)
    for i, (_, r) in enumerate(d.iterrows()):
        stars = "★" * int(r["titles"])
        ax.text(r["win_pct"] + 1, i, f"{r['record']}  {r['win_pct']}%  {stars}",
                va="center", fontsize=8, color=T["ink2"])
    ax.set_xlim(0, 100)
    return _finish(fig, ax, "Career Standings (All Seasons)",
                   "Ranked by win %  ·  1-2-3 podium  ·  ★ per title", "Career Win %")


def plot_trajectory(seasons: dict):
    import pandas as pd
    frames = [s.standings.assign(season_int=int(s.season)) for s in seasons.values()]
    allst = pd.concat(frames, ignore_index=True)
    canon = (allst.sort_values("season_int", ascending=False)
             .groupby("user_id", as_index=False).agg(nm=("user_name", "first")))
    d = allst.merge(canon, on="user_id", how="left")
    pal = palette(d["nm"])
    mp = int(d["final_position"].max())
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.axhspan(0.5, 3.5, color="#f1c40f", alpha=0.08, zorder=0)
    for nm, g in d.sort_values("season_int").groupby("nm"):
        ax.plot(g["season_int"], g["final_position"], color=pal[nm], lw=2, alpha=0.85, zorder=2)
        champ = g["champion"] if "champion" in g else [False] * len(g)
        ax.scatter(g["season_int"], g["final_position"],
                   marker=["o", "*"][0], color=pal[nm], s=45, zorder=3)
        star = g[g["champion"]]
        ax.scatter(star["season_int"], star["final_position"], marker="*",
                   color=pal[nm], s=180, zorder=4, edgecolors=T["edge"], linewidths=0.5)
        last = g.loc[g["season_int"].idxmax()]
        ax.text(last["season_int"] + 0.08, last["final_position"], nm, va="center",
                fontsize=8, color=pal[nm])
    ax.set_ylim(mp + 0.5, 0.5)
    ax.set_yticks(range(1, mp + 1))
    ax.set_xticks(sorted(d["season_int"].unique()))
    ax.text(d["season_int"].min(), 1, " podium", va="center", fontsize=8, color=T["faint"])
    return _finish(fig, ax, "Finish Trajectory by Season",
                   "1 = top  ·  gold band = podium  ·  ★ = champion",
                   "Season", "Final Position", grid_axis="y")


# --- Roster & position charts (ported from ddbmFF.R) ----------------------
POSITIONS = list(POS_COLORS)


def plot_position_scoring(s: Season):
    d = metrics.position_scoring(s)
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(d)), d["points"],
            color=[POS_COLORS[str(p)] for p in d["position"]], height=0.7)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels([str(p) for p in d["position"]])
    ax.invert_yaxis()  # QB on top
    xmax = d["points"].max()
    for i, (_, r) in enumerate(d.iterrows()):
        ax.text(r["points"] + xmax * 0.01, i, f"{round(r['points'])} pts  ·  {r['share']:.0f}%",
                va="center", fontsize=9, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.22)
    return _finish(fig, ax, "Where the Points Come From",
                   "Total started points by position  ·  share of league scoring",
                   "Starter Points", caption=_cap(s))


def plot_roster_heatmap(s: Season):
    """Roster-building depth: how many weeks each position held a roster spot
    (starters + bench combined), by team and position.

    Color is keyed to WEEKS ROSTERED, not scoring -- that's what "construction"
    means here (how a team builds its roster/bench across the season), and it
    was previously the reverse (color = avg points, weeks relegated to small
    text), which pictured scoring quality more than roster-building habit. Avg
    points stays in the cell label as secondary context.
    """
    d = metrics.roster(s)
    users = sorted(d["user_name"].unique())
    piv_avg = d.pivot(index="user_name", columns="position", values="avg").reindex(
        index=users, columns=POSITIONS)
    piv_spots = d.pivot(index="user_name", columns="position", values="spots").reindex(
        index=users, columns=POSITIONS)
    cmap = mcolors.LinearSegmentedColormap.from_list("sl", ["#eaf2f8", "#1f6f8b"])
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(piv_spots.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(POSITIONS)))
    ax.set_xticklabels(POSITIONS)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(users)))
    ax.set_yticklabels(users)
    vmax = piv_spots.values.max()
    for i in range(len(users)):
        for j in range(len(POSITIONS)):
            sp, av = piv_spots.values[i, j], piv_avg.values[i, j]
            if sp == sp:  # not NaN
                col = "white" if sp > vmax * 0.6 else "#1a1a1a"
                ax.text(j, i, f"{int(sp)} wk\n{av:.1f}", ha="center", va="center",
                        fontsize=7.5, color=col, linespacing=0.95)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Weeks rostered")
    ax.set_title("Roster Construction", loc="left", fontsize=16, fontweight="bold",
                 color=T["ink"], pad=24)
    # This is a matrix chart with its column labels (positions) on the TOP axis,
    # same as plot_schedule_swap/plot_head_to_head -- an explanatory subtitle up
    # there collides with either the tick labels or the title (measured: it sat
    # inside the title's own bounding box). Put it at the bottom instead, like
    # those two charts already do.
    fig.text(0.01, 0.01, "Weeks each position held a roster spot (color) and its "
             "average points (label), by team", ha="left", fontsize=8.5, color=T["muted"])
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_starter_bench(s: Season):
    """Bench-share heatmap: what share of each position's average points a
    team left unstarted, team x position.

    Kept as a chart (mirrors R's `sl_plot_starter_bench`) even though the
    webapp's Roster tab now shows `plot_flex_usage` instead -- bench-share
    across all six positions buried the RB/WR/TE flex-allocation signal under
    QB/K/DEF cells that were mostly a flat 0% (no bench depth there, not a
    real decision, since flex doesn't apply to those positions at all).
    """
    import pandas as pd
    d = metrics.starter_bench(s)
    users = sorted(d["user_name"].unique())
    st = (d[d["status"] == "Starters"].pivot(index="user_name", columns="position", values="avg")
          .reindex(index=users, columns=POSITIONS).fillna(0))
    bn = (d[d["status"] == "Bench"].pivot(index="user_name", columns="position", values="avg")
          .reindex(index=users, columns=POSITIONS).fillna(0))
    total = st + bn
    share = (bn / total.mask(total == 0) * 100)
    cmap = matplotlib.colormaps["OrRd"]
    vmax = float(share.max(numeric_only=True).max()) if share.notna().any().any() else 1.0
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(share.values.astype(float), aspect="auto", cmap=cmap, vmin=0, vmax=max(vmax, 1))
    ax.set_xticks(range(len(POSITIONS)))
    ax.set_xticklabels(POSITIONS)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(users)))
    ax.set_yticklabels(users)
    for i in range(len(users)):
        for j, pos in enumerate(POSITIONS):
            v = share.iloc[i, j]
            if pd.notna(v):
                col = "white" if v > vmax * 0.6 else "#1a1a1a"
                ax.text(j, i, f"{v:.0f}%\n{bn.iloc[i, j]:.1f} pts", ha="center", va="center",
                        fontsize=7.5, color=col, linespacing=0.95)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Bench share %")
    ax.set_title("Starters vs Bench", loc="left", fontsize=16, fontweight="bold",
                 color=T["ink"], pad=24)
    fig.text(0.01, 0.01,
             "Share of each position's average points left on the bench, by team  ·  "
             "darker = more stranded",
             ha="left", fontsize=8.5, color=T["muted"])
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_flex_usage(s: Season):
    """Grouped dot plot: which position fills a manager's flex slot(s), and
    how often. Replaces a bench-share heatmap that spanned all six positions
    (`plot_starter_bench`) -- flex allocation is only a question for RB/WR/TE,
    and the old chart's QB/K/DEF columns were mostly a flat 0% (no bench depth
    to speak of at those spots, not a real decision), which buried the real
    RB/WR/TE signal under structural noise.

    Reconstructed from each manager's REAL started lineup via
    `metrics.flex_usage` (`assign_slots`), not the optimal one -- Sleeper's own
    slot assignment isn't stored, so this is the same reconstruction technique
    the week/lineup drilldowns already use for display, applied here as an
    aggregate.
    """
    d = metrics.flex_usage(s)
    if d.empty:
        return _no_data(f"No flex-slot data for {s.season}.")
    users = sorted(d["user_name"].unique())
    positions = ["RB", "WR", "TE"]
    piv_share = d.pivot(index="user_name", columns="position", values="share").reindex(
        index=users, columns=positions).fillna(0)
    piv_weeks = d.pivot(index="user_name", columns="position", values="weeks").reindex(
        index=users, columns=positions).fillna(0)
    offsets = {"RB": -0.22, "WR": 0.0, "TE": 0.22}
    fig, ax = plt.subplots(figsize=(9, 6))
    for pos in positions:
        y = [i + offsets[pos] for i in range(len(users))]
        x = piv_share[pos].values
        ax.scatter(x, y, s=70, color=POS_COLORS[pos], zorder=3,
                   edgecolors=T["edge"], linewidths=0.8, label=pos)
        for i, (xi, wk) in enumerate(zip(x, piv_weeks[pos].values)):
            if wk > 0:
                ax.text(xi + 2, i + offsets[pos], f"{xi:.0f}%", va="center",
                        fontsize=7, color=POS_COLORS[pos])
    ax.set_yticks(range(len(users)))
    ax.set_yticklabels(users)
    # imshow (plot_roster_heatmap, which this reads as a pair with) puts row 0
    # at the TOP by default; a bare scatter doesn't, so without inverting, the
    # two charts would list managers in opposite vertical order.
    ax.invert_yaxis()
    _row_avatars(ax, users, s)
    hi = float(piv_share.values.max()) if piv_share.size else 100.0
    ax.set_xlim(0, max(hi * 1.2, 20))
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in positions]
    # "best" (not a fixed corner) -- shares cluster near both 0% and 100%
    # depending on the manager, so no fixed corner is reliably clear of data.
    ax.legend(handles, positions, loc="best", frameon=False, fontsize=9, ncol=3)
    return _finish(fig, ax, "Flex Allocation",
                   "Share of each manager's flex-slot starts filled by RB, WR or TE",
                   "Share of flex-slot weeks", caption=_cap(s), grid_axis="x")


# --- Weekly-standings & transaction charts (ported from ddbmFF.R) ----------

def plot_table_position(s: Season):
    d = metrics.table_position(s)
    last = d[d["week"] == d["week"].max()].sort_values("table_position")
    order = last["user_name"].tolist()
    pal = palette(order)
    nteams = len(last)
    playoff = nteams / 2 if nteams >= 8 else None
    fig, ax = plt.subplots(figsize=(10, 6))
    if playoff is not None:
        ax.axhspan(0.5, playoff + 0.5, color="#2f9e44", alpha=0.06, zorder=0)
    weeks = sorted(d["week"].unique())
    for nm in order:
        g = d[d["user_name"] == nm].sort_values("week")
        ax.plot(g["week"], g["table_position"], color=pal[nm], lw=2, alpha=0.85, zorder=2)
        ax.scatter(g["week"], g["table_position"], color=pal[nm], s=32, zorder=3)
        r = last[last["user_name"] == nm].iloc[0]
        ax.text(weeks[-1] + 0.15, r["table_position"],
                f"{nm} ({int(r['wins'])}-{int(r['losses'])})", va="center",
                fontsize=8, color=pal[nm])
    ax.set_ylim(nteams + 0.5, 0.5)
    ax.set_yticks(range(1, nteams + 1))
    ax.set_xticks(weeks)
    sub = ("Standing after each week  ·  1 = top  ·  green band = playoff spots"
           if playoff is not None else "Standing after each week  ·  1 = top")
    return _finish(fig, ax, "Table-Position Trajectory", sub,
                   "Week", "Table Position", caption=_cap(s), grid_axis="y")


def plot_team_points(s: Season):
    import pandas as pd
    tot = (s.team_wk.groupby("user_name", as_index=False)["points"].sum()
           .sort_values("points", ascending=False))
    order = tot["user_name"].tolist()
    weeks = sorted(s.team_wk["week"].unique())
    piv = (s.team_wk.pivot_table(index="user_name", columns="week", values="points",
                                 aggfunc="sum", fill_value=0).reindex(order))
    ramp = mcolors.LinearSegmentedColormap.from_list("wk", ["#1f6f8b", "#8ecae6"])
    fig, ax = plt.subplots(figsize=(11, 6))
    y = range(len(order))
    left = pd.Series(0.0, index=order)
    for i, wk in enumerate(weeks):
        vals = piv[wk]
        ax.barh(list(y), vals.values, left=left.values, height=0.7,
                color=mcolors.to_hex(ramp(i / max(len(weeks) - 1, 1))),
                edgecolor=T["edge"], linewidth=0.3)
        left += vals
    for i, nm in enumerate(order):
        t = tot.loc[tot["user_name"] == nm, "points"].iloc[0]
        ax.text(t * 1.01, i, f"{round(t)}", va="center", fontsize=8.5,
                fontweight="bold", color=T["ink2"])
    ax.set_yticks(list(y))
    ax.set_yticklabels(order)
    ax.invert_yaxis()
    ax.set_xlim(0, tot["points"].max() * 1.12)
    return _finish(fig, ax, "Total Points by Team",
                   "Season points, stacked by week  ·  bold = season total",
                   "Points", caption=_cap(s))


def plot_position_box(s: Season):
    d = metrics.roster(s)
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    data = [d.loc[d["position"] == p, "avg"].values for p in POSITIONS]
    ax.boxplot(data, positions=range(len(POSITIONS)), widths=0.55, showfliers=False,
               patch_artist=True, boxprops=dict(facecolor=T["grid"], color=T["rule"]),
               medianprops=dict(color=T["ink2"]), whiskerprops=dict(color=T["rule"]),
               capprops=dict(color=T["rule"]))
    import numpy as np
    seen = set()
    for j, p in enumerate(POSITIONS):
        sub = d[d["position"] == p]
        for _, r in sub.iterrows():
            lab = r["user_name"] if r["user_name"] not in seen else None
            seen.add(r["user_name"])
            ax.scatter(j + np.random.uniform(-0.16, 0.16), r["avg"], color=pal[r["user_name"]],
                       alpha=0.8, s=32, zorder=3, label=lab)
    ax.set_xticks(range(len(POSITIONS)))
    ax.set_xticklabels(POSITIONS)
    ax.legend(loc="upper right", frameon=False, fontsize=7, title="Team", ncol=2)
    return _finish(fig, ax, "Average Weekly Position Points",
                   "Each dot is a team's per-week average at a position  ·  spread = positional inequality",
                   "Position", "Average Points", caption=_cap(s), grid_axis="y")


def plot_roster_counts(s: Season):
    d = metrics.roster_counts(s)
    fig, ax = plt.subplots(figsize=(9, 6))
    x = range(len(POSITIONS))
    bench = [d[(d["position"] == p) & (d["status"] == "Bench")]["avg_count"].sum() for p in POSITIONS]
    start = [d[(d["position"] == p) & (d["status"] == "Starters")]["avg_count"].sum() for p in POSITIONS]
    ax.bar(list(x), start, width=0.7, color="#2f9e44",
           edgecolor=T["bg"], linewidth=1.2, label="Starters")
    ax.bar(list(x), bench, width=0.7, bottom=start, color=T["neutral"], alpha=0.85,
           edgecolor=T["bg"], linewidth=1.2, label="Bench")
    for j in x:
        if start[j] > 0:
            ax.text(j, start[j] / 2, f"{start[j]:.1f}", ha="center", va="center",
                    fontsize=8, fontweight="bold", color="white")
        if bench[j] > 0:
            ax.text(j, start[j] + bench[j] / 2, f"{bench[j]:.1f}", ha="center",
                    va="center", fontsize=8, fontweight="bold", color="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(POSITIONS, fontweight="bold")
    # Tick labels tinted by POS_COLORS -- the same position-identity colour
    # `plot_position_scoring`/`plot_position_box` key their own data on, so a
    # position reads as the same colour everywhere on this tab. The bars
    # themselves stay green/grey (Starters/Bench is the thing THIS chart
    # encodes in colour); tinting the axis instead of the bars adds that
    # shared identity without competing with that encoding.
    for tick, p in zip(ax.get_xticklabels(), POSITIONS):
        tick.set_color(POS_COLORS[p])
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    return _finish(fig, ax, "Average Roster Composition",
                   "Mean roster slots per team each week, by position",
                   "Position", "Slots per Team-Week", caption=_cap(s), grid_axis="y")


def _plot_acq(d, s: Season, title, subtitle):
    import pandas as pd
    if d is None or len(d) == 0 or not pd.to_numeric(
            d.get("total"), errors="coerce").fillna(0).gt(0).any():
        # No acquisitions with any scored points yet (e.g. a season that has
        # only just kicked off) -- `weeks`/`total` are NaN/0 and the bar +
        # `int(weeks)` math below would raise.
        return _no_data(f"No {title.split(':')[0].lower()} to show for {s.season} yet.")
    players = (d.drop_duplicates("player_name").sort_values("total")["player_name"].tolist())
    totals = {p: d[d["player_name"] == p]["total"].iloc[0] for p in players}
    span = max(totals.values()) if totals else 1
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(11, max(5, len(players) * 0.42)))
    y = {p: i for i, p in enumerate(players)}
    left = pd.Series(0.0, index=players)
    for nm in sorted(d["user_name"].unique()):
        row = d[d["user_name"] == nm].set_index("player_name")["points"].reindex(players).fillna(0)
        wk = d[d["user_name"] == nm].set_index("player_name")["weeks"].reindex(players)
        ax.barh([y[p] for p in players], row.values, left=left.values, height=0.72,
                color=pal[nm], edgecolor=T["edge"], linewidth=0.3, label=nm)
        for p in players:
            if row[p] >= span * 0.06:
                wkn = int(wk[p]) if pd.notna(wk[p]) else 0
                ax.text(left[p] + row[p] / 2, y[p], f"{round(row[p])} ({wkn}w)",
                        ha="center", va="center", fontsize=7, color="#1a1a1a")
        left += row.values
    for p in players:
        ax.text(totals[p] + span * 0.01, y[p], f"{round(totals[p])}", va="center",
                fontsize=8, fontweight="bold", color=T["ink2"])
    ax.set_yticks(list(y.values()))
    ax.set_yticklabels(players, fontsize=8.5)
    # One id/position per player row (a traded player appears under several
    # managers, so take the first -- it is the same player either way).
    first = d.drop_duplicates("player_name").set_index("player_name")
    _portraits(ax, players, first["player_id"].reindex(players),
               first["position"].reindex(players), zoom=0.28)
    ax.set_xlim(0, span * 1.12)
    ax.legend(loc="lower right", frameon=False, fontsize=8, title="Team", ncol=2)
    return _finish(fig, ax, title, subtitle, "Points While Rostered", caption=_cap(s))


# --- Playoff charts (mirror R plots.R) -------------------------------------

def _ref_label(ref_scores: dict | None, team, weeks) -> str:
    """"(148.6)" for a node with no bracket score, or a dash if none is known.

    A multi-week round sums, matching how the engine scores one. Anything
    missing (no season handed in, a team with no row that week) falls back to
    the dash rather than inventing a zero.
    """
    from .playoffs import _week_nums
    if not ref_scores or team is None:
        return "–"
    wks = _week_nums(weeks)
    vals = [ref_scores.get((team, w)) for w in wks]
    vals = [v for v in vals if v is not None]
    return f"({sum(vals):.1f})" if vals else "–"


# Shared footprint for the Playoffs-tab pair (`plot_playoff_bracket` and
# `plot_consolation_bracket`) so they render the same size beside each other. Neither
# chart's title/caption text is allowed to change these dimensions -- long
# strings wrap or truncate instead of stretching the figure.
# Height was 5.2; bumped to 6.0 so a wide, shallow bracket (few games but many
# rounds, e.g. a 12-team pick-your-opponent bracket with a full placement
# slate) renders each card tall enough for its two text lines to clear the
# border -- at 5.2 a card was ~14px, shorter than two stacked 7pt lines, and
# the top line clipped the outline (glaring in dark mode).
_PLAYOFF_FIG = (8.5, 6.0)
_PLAYOFF_CAPTION_BAND = 0.14        # fraction of the figure height kept for the caption


def plot_playoff_bracket(p, ref_scores: dict | None = None, consolation: dict | None = None,
                         variant: str = "championship"):
    """Rounds left to right; winner green, loser reddish, bye grey, champion gold.

    Each slot is a two-line card (seed + name above, score below).
    Connectors are horizontal-first right angles (a short stub out of the
    source card, the turn near it, then the run into the target at the
    target's row -- the printed-bracket look, two winners converging making
    the "]" join). A game WIN is a solid green line (gold on the champion's
    path); a BYE is a thin grey dotted one (matching the bye card), drawn
    from the team's LAST idle card into the very next round -- never hauled
    back to its first idle round. A LOSS is a thin reddish dashed line, but
    only when that loser actually plays again next round (a placement /
    consolation game), so a beaten team can be followed down into the
    losers' side rather than just disappearing. This league's "pick your
    opponent" format leaves the top seeds idle for a round or two, each
    idle round its own card.

    The **whole bracket is drawn, not just the title path**: the
    losers-bracket placement games (`bracket == "losers"`) sit in their
    round columns like any other game but on a muted fill, tagged with the
    place they decide (`config["_placements"]`: `{matchup_id: 3}` ->
    "3rd-place game"), and wrapped in a faint band so the tier reads at a
    glance.

    The one card the bracket points at -- the CHAMPION (winner of the
    `config["final"]` game) -- gets a gold fill + heavier gold border + a
    "*" on its name; every other winner gets a green fill + a firmer green
    border + bold name; losers stay flat grey. The bottom band carries a
    single gold "CHAMPION <name>" pill; 3rd/last place are deliberately NOT
    shown -- the graphic is about the winner. `variant="consolation"`
    switches the title word to "Consolation" and the pill to a blue
    "WINNER <name>" (best consolation finish).

    `consolation` is accepted for call-site compatibility but no longer read.

    `ref_scores` is `{(manager, week): points}` (see `reference_scores`). A card
    with no bracket score of its own -- a bye, or a team waiting out a round --
    shows what it **actually scored** that week in parentheses instead of a bare
    dash, which reads as missing data when the number is right there in the
    season. Parenthesised because it decides nothing: the team advanced on the
    bye, not on those points.
    """
    import pandas as pd
    d = p.results.copy()
    rounds = list(dict.fromkeys(d["round_id"]))
    _ridx = {r: i for i, r in enumerate(rounds)}
    seeds = (p.config.get("_seeds") or {})
    seed_of = {v: k for k, v in seeds.items()}
    # {matchup_id: place} for the placement games -- Sleeper tags each with the
    # position its winner earns (`_placements`, set in `sleeper_bracket`). A
    # hand-authored config without one still gets the generic "Consolation" tag
    # off the `bracket` column, just no rank number.
    placements = {str(k): int(v) for k, v in (p.config.get("_placements") or {}).items()}
    _bracket_of = (d.drop_duplicates("matchup_id").set_index("matchup_id")["bracket"].to_dict()
                   if "bracket" in d else {})

    def _ord(pl):
        suf = {1: "st", 2: "nd", 3: "rd"}.get(pl if not 10 <= pl % 100 <= 20 else 0, "th")
        return f"{pl}{suf}"

    def _place_tag(mid):
        pl = placements.get(str(mid))
        if pl:
            return f"{_ord(pl)}-place game"
        return "Placement game" if _bracket_of.get(mid) == "losers" else None

    # A TERMINAL matchup decides two consecutive finishing places: its winner
    # takes `place`, its loser `place + 1`. The `final` game is place 1 (so
    # 1st / 2nd); each `_placements` game is its tagged place (3rd / 4th,
    # 5th / 6th, ...). `_place_of(mid, result)` -> the int place, or None for
    # any non-terminal matchup. Shown as a colour-tiered chip inside BOTH
    # cards so a bracket reader can see every settled placement at a glance,
    # not just the champion.
    _final_mid = str(p.config.get("final")) if p.config.get("final") is not None else None

    def _place_of(mid, result):
        base = 1 if str(mid) == _final_mid else placements.get(str(mid))
        if base is None or result not in ("W", "L", "T"):
            return None
        return base if result == "W" else base + 1

    # place -> (chip fill, chip text colour). Deliberately SATURATED hues, not
    # a metal-grey ramp: a "silver" 2nd and a grey 4th+ read as the neutral
    # bye card (`#d1d4d8`). 1st gold, 2nd cool blue, 3rd bronze/orange, 4th+
    # violet -- each clearly distinct from the bye grey, the win green and the
    # loss pink, and from each other. White chip text on the darker fills.
    _PLACE_CHIP = {1: ("#f1c40f", "#242424"), 2: ("#4f86c6", "#ffffff"),
                   3: ("#c9752e", "#ffffff")}
    _PLACE_CHIP_DEFAULT = ("#8f6fc0", "#ffffff")

    # Every BYE row is kept and drawn -- an idle "pick" seed that sits out
    # two rounds shows a card in each. The connectors then chain one column
    # at a time (bye -> bye -> the game it re-enters), so LuckyHarm and
    # SimonSmith still appear in Round 1 even though their live connector
    # starts from their Round 2 card.
    mu = d.drop_duplicates("matchup_id")[["round_id", "matchup_id"]].copy()
    mu["j"] = mu.groupby("round_id").cumcount() + 1
    mu["n"] = mu.groupby("round_id")["matchup_id"].transform("size")
    span = int(mu["n"].max())
    mu["rx"] = mu["round_id"].map({r: i for i, r in enumerate(rounds)})
    mu["cy"] = (mu["j"] - 0.5) * span / mu["n"]
    d = d.merge(mu[["matchup_id", "rx", "cy"]], on="matchup_id", how="left")
    d["side"] = d.groupby("matchup_id").cumcount()
    d["sides"] = d.groupby("matchup_id")["team"].transform("size")
    # The two cards of a matchup sit CARD_GAP apart, one above `cy` and one
    # below. CARD_GAP (0.62) > CARD_H (0.42) leaves a visible band of
    # background between the pair so they read as two cards, not a split
    # block, and LANE (0.78) opens a clear gutter between adjacent matchups
    # so each pair reads as one unit -- widened per request for legibility.
    CARD_H = 0.42                       # full card height, data units
    CARD_HH = CARD_H / 2               # half, for centring the rectangle on `y`
    CARD_GAP = 0.62                    # vertical centre-to-centre of a matchup's two cards
    LANE = 0.78                        # min centre-to-centre of adjacent cards in a column
    PAIR_STEP = CARD_GAP + LANE        # a 2-card matchup's own footprint, centre to centre
    HALF_W = 0.45                      # card half-width, data units (card is HALF_W*2 wide)
    PAD_X = 0.085                      # inner text margin from a card's left/right edge

    # ---- Vertical layout. Each UNIT is a full matchup (two cards locked
    # CARD_GAP apart) or one idle "pick"-seed card. The arrangement:
    #   * In every column the real MATCHUPS form one contiguous, centred
    #     block, evenly spaced -- so a bracket always reads as a bracket.
    #   * The idle "pick" seed cards sit OUTSIDE that block, split above and
    #     below it, ordered so the one whose team re-enters HIGHEST is
    #     nearest the top of the block (and likewise below) -- their dotted
    #     connectors then reach straight in with no crossing.
    #   * Later-round matchup blocks are recentred on the mean of their
    #     feeders, then the whole column is despaced, so the columns line
    #     up round to round.
    def _prior_unit(team, rx):
        # The card this team came from in the immediately preceding column
        # (a game it played, or an idle/bye card if it was still waiting).
        pr = d[(d["team"] == team) & (d["rx"] == rx - 1)]
        return pr.iloc[0]["matchup_id"] if len(pr) else None

    def _next_unit(team, rx):
        nx = d[(d["team"] == team) & (d["rx"] == rx + 1)]
        return nx.iloc[0]["matchup_id"] if len(nx) else None

    unit_ids = {u: list(g.index) for u, g in d.groupby("matchup_id")}
    unit_rx = {u: int(d.loc[ix[0], "rx"]) for u, ix in unit_ids.items()}
    unit_is_game = {u: len(ix) == 2 for u, ix in unit_ids.items()}
    unit_y = {u: float(d.loc[ix, "cy"].iloc[0]) for u, ix in unit_ids.items()}
    unit_feed = {}                                  # unit -> feeder units (prior round)
    for u, ix in unit_ids.items():
        fs = set()
        for i in ix:
            v = _prior_unit(d.loc[i, "team"], d.loc[i, "rx"])
            if v is not None and v != u:
                fs.add(v)
        unit_feed[u] = fs

    # Placement priority for the vertical ordering: when the bracket carries
    # ranked placement games (`_placements`, i.e. a default Sleeper bracket),
    # the games in a column are stacked BEST PLACEMENT AT THE TOP -- the
    # title path (championship, unplaced title-path games) first, then the
    # 3rd-place game, then 5th, 7th, ... Custom brackets with no `_placements`
    # get `0` for every unit, so this is a no-op and the original config /
    # feeder ordering stands unchanged.
    _final_cfg = str(p.config.get("final")) if p.config.get("final") is not None else None

    def _unit_place_rank(u):
        if not placements:
            return 0
        pl = placements.get(str(u))
        if pl:
            return pl                        # 3rd-place game -> 3, 5th -> 5, ...
        if str(u) == _final_cfg:
            return 0                         # the title game rides at the very top
        return 0 if _bracket_of.get(u) != "losers" else 1_000
    unit_place_rank = {u: _unit_place_rank(u) for u in unit_ids}

    cols = {}
    for u, rx in unit_rx.items():
        cols.setdefault(rx, []).append(u)

    def _despace(us):
        order = sorted(us, key=lambda u: unit_y[u])
        for a, b in zip(order, order[1:]):
            gap = (PAIR_STEP if unit_is_game[a] and unit_is_game[b]
                   else (CARD_GAP / 2 + LANE if unit_is_game[a] or unit_is_game[b]
                         else LANE))
            if unit_y[b] - unit_y[a] < gap:
                unit_y[b] = unit_y[a] + gap

    # Pass 1: place every column's real-MATCHUP block -- contiguous, centred,
    # evenly spaced -- ordered top-to-bottom by placement rank first (title
    # path above 3rd-place above 5th-place ...; a no-op unless the bracket
    # has `_placements`), then within a rank by config order (round 1) or
    # feeder mean (later rounds).
    #
    # For a DEFAULT SLEEPER bracket (one carrying `_placements`) the block's
    # STEP grows with the round: round r spaces its games
    # `PAIR_STEP * TREE_FAN**r` apart. A tournament tree has fewer games each
    # round, each at the midpoint of its two feeders, so successive rounds
    # are drawn progressively FURTHER apart -- this reproduces that widening
    # fan even for Sleeper's "pick your opponent" brackets whose feeder graph
    # is really 2-2-2-1 rather than 8-4-2-1. A custom / hand-authored bracket
    # (no `_placements`, e.g. DDBM 2025) keeps the flat PAIR_STEP it always
    # had -- those configs are laid out deliberately and are left alone.
    TREE_FAN = 1.55 if placements else 1.0
    _last_cx = max(cols) if cols else 0
    for cx in sorted(cols):
        games = [u for u in cols[cx] if unit_is_game[u]]
        if cx == 0:
            games.sort(key=lambda u: (unit_place_rank[u], min(unit_ids[u])))
        else:
            games.sort(key=lambda u: (unit_place_rank[u],
                                      sum(unit_y[f] for f in unit_feed[u])
                                      / max(len(unit_feed[u]), 1)))
        step = PAIR_STEP * min(TREE_FAN ** cx, 4.0)
        for k, u in enumerate(games):
            unit_y[u] = span / 2 + (k - (len(games) - 1) / 2) * step
        # For a fanned default bracket, pull the FINAL round's single title
        # game onto the mean of its own feeders -- the classic tree apex,
        # instead of the placement-rank sink leaving it stranded above its
        # two semifinals with the champion connector doubling back up.
        if placements and cx == _last_cx and cx > 0:
            for u in games:
                if unit_place_rank[u] == 0 and unit_feed[u]:
                    unit_y[u] = sum(unit_y[f] for f in unit_feed[u]) / len(unit_feed[u])
            _despace(games)

    # Pass 2: hang each column's idle "pick" cards OUTSIDE its matchup block
    # -- half above, half below -- ordered so the one whose team's NEXT card
    # sits highest is nearest the top of this block (and mirror below), so
    # every dotted hop into the next column is short and un-crossed. Done
    # RIGHT TO LEFT so a bye's next card (a game, or another bye) already
    # has its y when we place this one.
    def _next_card_y(u):
        i = unit_ids[u][0]
        v = _next_unit(d.loc[i, "team"], d.loc[i, "rx"])
        return unit_y.get(v, 1e9)

    for cx in sorted(cols, reverse=True):
        games = [u for u in cols[cx] if unit_is_game[u]]
        byes = [u for u in cols[cx] if not unit_is_game[u]]
        if not byes:
            continue
        gc = span / 2 if not games else sum(unit_y[u] for u in games) / len(games)
        block_top = min((unit_y[u] for u in games), default=gc) - CARD_GAP / 2
        block_bot = max((unit_y[u] for u in games), default=gc) + CARD_GAP / 2
        byes.sort(key=_next_card_y)
        half = (len(byes) + 1) // 2
        above, below = byes[:half][::-1], byes[half:]
        for k, u in enumerate(above):
            unit_y[u] = block_top - (k + 1) * LANE
        for k, u in enumerate(below):
            unit_y[u] = block_bot + (k + 1) * LANE
        _despace(cols[cx])

    # A couple of gentle relaxation sweeps so a deep bracket's later blocks
    # settle onto their feeders without breaking the block structure.
    for _ in range(6):
        for cx in sorted(cols):
            if cx == 0:
                continue
            games = [u for u in cols[cx] if unit_is_game[u]]
            if not games:
                continue
            want = sum(sum(unit_y[f] for f in unit_feed[u]) / max(len(unit_feed[u]), 1)
                       for u in games) / len(games)
            have = sum(unit_y[u] for u in games) / len(games)
            for u in cols[cx]:
                unit_y[u] += want - have
            _despace(cols[cx])

    # Column by column, left to right: place each unit's card(s), and within
    # a matchup put the team whose FEEDER card sits higher on top so the two
    # connectors into that matchup don't cross. Feeders in the previous
    # column already have their y by the time we reach this one.
    #
    # A TERMINAL matchup is the exception: its WINNER card is floated to the
    # top of the pair regardless of feeder order, so the better finisher
    # always sits above the worse one -- the champion above the runner-up in
    # the final, the 3rd above the 4th in the 3rd-place game, and so on for
    # every placement game.
    _terminal_mids = {_final_cfg} | {str(k) for k in placements}
    d["y"] = float("nan")
    for cx in sorted(cols):
        for u in cols[cx]:
            ix = unit_ids[u]
            if len(ix) == 2:
                a, b = ix
                if str(u) in _terminal_mids and set(d.loc[ix, "result"]) & {"W"}:
                    # Winner on top.
                    if d.loc[a, "result"] != "W":
                        a, b = b, a
                else:
                    pa = d[(d["team"] == d.loc[a, "team"]) & (d["rx"] == cx - 1)]
                    pb = d[(d["team"] == d.loc[b, "team"]) & (d["rx"] == cx - 1)]
                    fa = float(pa.iloc[0]["y"]) if len(pa) else None
                    fb = float(pb.iloc[0]["y"]) if len(pb) else None
                    if fa is not None and fb is not None and fb < fa:
                        a, b = b, a                    # b fed from higher -> b on top
                d.loc[a, "y"] = unit_y[u] - CARD_GAP / 2
                d.loc[b, "y"] = unit_y[u] + CARD_GAP / 2
            else:
                d.loc[ix[0], "y"] = unit_y[u]
    d["side"] = (d.groupby("matchup_id")["y"].rank(method="first").astype(int) - 1)
    y_lo, y_hi = float(d["y"].min()), float(d["y"].max())
    d["y"] -= (y_lo + y_hi) / 2 - span / 2
    y_span_lo = float(d["y"].min()) - 0.30
    y_span_hi = float(d["y"].max()) + 0.30
    # Floor the drawn y-extent at ~4 matchup-rows so a shallow bracket (a
    # 1- or 2-game consolation bracket, e.g. DDBM 2025) keeps normal card
    # proportions with honest empty space rather than 2 cards stretched to
    # fill the fixed figure height. A deep bracket is already past this.
    _MIN_SPAN = 5.4
    if (y_span_hi - y_span_lo) < _MIN_SPAN:
        pad = (_MIN_SPAN - (y_span_hi - y_span_lo)) / 2
        y_span_lo -= pad
        y_span_hi += pad

    # Card palette. Win = green, loss = a soft warm pink (reads as "lost"
    # without shouting), bye = a neutral dark-ish grey -- deliberately NOT
    # amber (would blend with the CHAMPION gold) and NOT the pink loss (a bye
    # is not a loss). Tie = the loss fill.
    COL = {"W": "#a5d6a7", "L": "#f0dede", "BYE": "#d1d4d8",
           "PENDING": "#f4f6f8", "T": "#f0dede"}
    # Losers-bracket placement games render on the SAME shapes but a muted
    # (desaturated) version of each fill, so they read as a lower tier
    # without leaving the grid.
    COL_CONS = {"W": "#d6e8d6", "L": "#f4ecec", "BYE": "#e2e4e6",
                "PENDING": "#f4f6f8", "T": "#f4ecec"}
    cons_mids = {m for m in d["matchup_id"].unique()
                 if str(m) in placements or _bracket_of.get(m) == "losers"}
    # Fixed footprint (`_PLAYOFF_FIG` = 8.5 x 5.2) so this and the companion
    # `plot_consolation_bracket` are the same size side by side in one `.grid` row on
    # the Playoffs tab. The bracket's data-coordinate `ylim` (set below from the
    # relaxed y-extent) maps onto that fixed axes height, so a taller bracket
    # just packs its rows denser rather than growing the figure.
    fig, ax = plt.subplots(figsize=_PLAYOFF_FIG)
    # Connectors trace how each team reached its NEXT game. Every one meets a
    # card FLUSH AT THE ROW OF THE TEAM IT BELONGS TO at both ends: it leaves
    # the source card's right edge at that team's y, turns at a vertical leg
    # ~40% across the gutter between the two columns, and runs into the
    # target card's left edge at that team's y. Which of a matchup's two
    # teams sits on top was chosen above so these feeders cross as little as
    # possible (fed-from-higher on top).
    # Every connector spans exactly ONE round: source column to the very
    # next column. For each team's card, find its own card in the NEXT
    # column (a game it plays, or another idle/bye card if it sits out
    # again) and connect the two. A win-sourced connector is solid green
    # (gold on the champion's path); a bye-sourced one is grey dotted
    # (matching the grey bye card); a LOSS-sourced one is a thin reddish
    # dashed line -- drawn only when that loser actually plays on next round
    # (a placement / consolation game), so the eye can follow a beaten team
    # down into the losers' side instead of it just vanishing.
    feeds: dict = {}   # (rx, y) of target card -> [(src rx, src y, kind, team), ...]
    for _, a in d.iterrows():
        if a["result"] not in ("W", "BYE", "L", "T"):
            continue
        nxt = d[(d["team"] == a["team"]) & (d["rx"] == a["rx"] + 1)]
        if not len(nxt):
            continue
        n = nxt.iloc[0]
        kind = ("bye" if a["result"] == "BYE"
                else "win" if a["result"] == "W"
                else "loss")
        feeds.setdefault((float(n["rx"]), float(n["y"])), []).append(
            (float(a["rx"]), float(a["y"]), kind, a["team"]))
    # Every connector is a horizontal-first right angle that meets a card
    # FLUSH AT THE ROW OF THE TEAM IT BELONGS TO at both ends: it leaves the
    # source card's right edge at that team's y, a short vertical leg turns
    # in the gutter between the two columns, then it runs into the target
    # card's left edge at that team's y. The turn sits ~40% across the gap
    # so the leg clears both cards' rounded corners.
    #
    # Connectors are COLOUR-CODED to match the cards they link:
    #   the CHAMPION's whole path -- gold, thicker.
    #   any other WIN -- green.
    #   a BYE -- thin grey dotted (matching the grey bye card).
    #   a LOSS that plays on -- thin reddish dashed (matching the loss card).
    BYE_LINE = "#8b9096"
    WIN_LINE, GOLD_LINE, LOSS_LINE = "#8bbf8f", "#e6b800", "#d99b9b"
    _champ_name = p.champion
    for (nrx, ny), fs in feeds.items():
        x_in = nrx - HALF_W                           # target card's left edge, at ny
        for frx, fy, kind, team in fs:
            x_out = frx + HALF_W                      # source card's right edge, at fy
            x_turn = x_out + (x_in - x_out) * 0.4     # vertical leg, in the gutter
            if kind == "bye":
                kw = dict(color=BYE_LINE, lw=1.4, linestyle=(0, (1, 2)))
            elif kind == "loss":
                kw = dict(color=LOSS_LINE, lw=1.5, linestyle=(0, (4, 2)))
            elif _champ_name and team == _champ_name:
                kw = dict(color=GOLD_LINE, lw=2.6)
            else:
                kw = dict(color=WIN_LINE, lw=2.2)
            ax.plot([x_out, x_turn, x_turn, x_in], [fy, fy, ny, ny],
                    zorder=1 if kind != "loss" else 0,
                    solid_capstyle="round", solid_joinstyle="round", **kw)
    from matplotlib.patches import FancyBboxPatch, Rectangle
    # Faint band behind each consolation matchup's y-range, with a tier label at
    # its left, so the placement games read as their own tier even though the
    # layout engine interleaves them into the round columns by feeder position.
    # A faint tint behind each consolation matchup so the placement tier reads
    # at a glance; the per-matchup "Nth-place game" tag below carries the label.
    for _mid in cons_mids:
        _rows = d[d["matchup_id"] == _mid]
        if not len(_rows):
            continue
        # Top margin matches the placement-tag offset below (0.20) plus a
        # little headroom for the label's own glyph height, so the tag reads
        # as INSIDE its tinted band rather than poking out above it.
        lo = float(_rows["y"].min()) - CARD_HH - 0.30
        hi = float(_rows["y"].max()) + CARD_HH + 0.14
        rx0 = float(_rows["rx"].iloc[0])
        ax.add_patch(FancyBboxPatch(
            (rx0 - HALF_W - 0.16, lo), HALF_W * 2 + 0.30, hi - lo,
            boxstyle="round,pad=0.004,rounding_size=0.04",
            facecolor=T["rule"], alpha=0.11, edgecolor="none", zorder=0))
    # The overall CHAMPION (winner of the `final` game) is the one card the
    # bracket exists to point at: gold fill + a heavier gold border + a star.
    # Everything else: winner = green fill + a firmer green border; bye = a
    # blue fill + blue border; loser = the reddish fill + a soft red border.
    _final_id = p.config.get("final")
    champ_key = None
    if _final_id is not None:
        _fw = d[(d["matchup_id"] == _final_id) & (d["result"] == "W")]
        if len(_fw):
            champ_key = (str(_fw.iloc[0]["matchup_id"]), _fw.iloc[0]["team"])
    GOLD_FILL, GOLD_EDGE = "#ffe9a8", "#d9a400"
    WIN_EDGE, BYE_EDGE, LOSS_EDGE = "#5fae63", "#8b9096", "#d99b9b"
    for _, r in d.iterrows():
        res = r["result"]
        win = res == "W"
        is_bye = res == "BYE"
        is_cons = r["matchup_id"] in cons_mids
        is_champ = champ_key is not None and (str(r["matchup_id"]), r["team"]) == champ_key
        pal = COL_CONS if is_cons else COL
        if is_champ:
            fc, ec, elw = GOLD_FILL, GOLD_EDGE, 1.8
        elif is_bye:
            fc, ec, elw = pal.get("BYE"), BYE_EDGE, 1.2
        elif win:
            fc, ec, elw = pal.get("W"), (WIN_EDGE if not is_cons else T["edge"]), 1.5
        else:
            fc, ec, elw = pal.get(res, "#f0dede"), LOSS_EDGE, 1.1
        ax.add_patch(FancyBboxPatch(
            (r["rx"] - HALF_W, r["y"] - CARD_HH), HALF_W * 2, CARD_H,
            boxstyle="round,pad=0.006,rounding_size=0.05",
            facecolor=fc, edgecolor=ec, lw=elw, zorder=2))
        # Placement tag ("3rd-place game" / "Consolation") once per matchup,
        # HORIZONTAL and IN-LINE with the cards -- left-aligned to the card's
        # own left edge, sitting just above the matchup's top card. The wider
        # LANE gutter opened above leaves room for it there without colliding
        # with the matchup above. (Replaces a rotated 6pt label jammed into
        # the connector gutter that was effectively unreadable.)
        if is_cons and r["side"] == 0:
            tag = _place_tag(r["matchup_id"])
            if tag:
                _pair = d[d["matchup_id"] == r["matchup_id"]]
                _top = float(_pair["y"].min())
                # va="bottom" (not "center") so the WHOLE glyph sits above the
                # anchor with no downward bleed, and the offset (0.13 -> 0.20)
                # gives a real cleared margin -- at this figure's fixed 8.5x5.2
                # footprint, 0.13 data-units measured under ~3pt of actual
                # clearance, less than the label's own rendered height, so it
                # clipped into its own top card. Verified against a shallow
                # 3-round bracket (the tightest real case: y-span far above
                # _MIN_SPAN, so no compression was masking this).
                ax.text(r["rx"] - HALF_W + PAD_X, _top - CARD_HH - 0.20, tag,
                        ha="left", va="bottom", fontsize=6.5, style="italic",
                        color=T["muted"], zorder=3)
        # A future round's node can still hold a raw "W:<matchup_id>"/"L:<matchup_id>"
        # reference (season/README.md's own documented authoring convention: the
        # commissioner writes it in before the source round resolves, and it's
        # meant to auto-resolve once that round has a winner). Live mid-bracket,
        # an unresolved reference reaches here unresolved -- showing it verbatim
        # ("W:R1M1") reads as a team name, not a placeholder, so it's translated
        # to "TBD" for display only; `team` itself is untouched everywhere else
        # (seed/ref-score lookups on the raw string already degrade safely, since
        # neither dict has a "W:..." key).
        team_label = "TBD" if str(r["team"]).startswith(("W:", "L:")) else r["team"]
        sd = seed_of.get(r["team"], "")
        if not pd.isna(r["points"]):
            pts = f"{r['points']:.1f}"
        else:
            pts = _ref_label(ref_scores, r["team"], r["weeks"])
        # Two bands inside the card, split SYMMETRICALLY around the card
        # centre: "#seed  Team" on the upper band (left-aligned, bold for the
        # winner), the score on the lower band (right-aligned, monospace so
        # decimals line up). The +/- offset (0.17 * CARD_H) and the 7pt size
        # are tuned so BOTH lines clear the card edges at this figure's fixed
        # footprint even for a wide, shallow bracket where each card renders
        # only ~22px tall (a bigger offset / font clipped the top line into
        # the border -- very visible in dark mode where the card outline is
        # high-contrast). A tiny gold "*" prefixes the champion's name. Fills
        # are always light, so text is a dark literal on both themes.
        badge = f"#{sd}  " if sd else ""
        star = "★ " if is_champ else ""
        band = CARD_H * 0.17
        ax.text(r["rx"] - HALF_W + PAD_X, r["y"] - band, f"{star}{badge}{team_label}",
                ha="left", va="center", fontsize=7, zorder=3,
                fontweight="bold" if (win or is_champ) else "normal",
                color="#242424")
        ax.text(r["rx"] + HALF_W - PAD_X, r["y"] + band, pts,
                ha="right", va="center", fontsize=7, zorder=3,
                family="monospace",
                color="#242424" if (win or is_champ) else "#5a5a5a")
        # Finishing-place chip on the upper band's right edge, for a
        # TERMINAL matchup only (the final, and each placement game). Both
        # the winner and the loser get one -- "1st"/"2nd", "3rd"/"4th",
        # ... -- colour-tiered (gold/silver/bronze/slate) so every settled
        # placement in the bracket is legible, not just the champion.
        _place = _place_of(r["matchup_id"], res)
        if _place is not None:
            _cfill, _ctext = _PLACE_CHIP.get(_place, _PLACE_CHIP_DEFAULT)
            ax.text(r["rx"] + HALF_W - PAD_X, r["y"] - band, _ord(_place),
                    ha="right", va="center", fontsize=6.5, zorder=4,
                    fontweight="bold", color=_ctext,
                    bbox=dict(boxstyle="round,pad=0.28", facecolor=_cfill,
                              edgecolor="none"))
    ax.set_xlim(-0.6, len(rounds) - 0.4)
    ax.set_ylim(y_span_hi, y_span_lo)          # inverted: row 0 at top
    ax.set_xticks(range(len(rounds)))
    # Round headers carry the week(s) that round was played: "Round 1  |
    # Week 15", "Final  |  Weeks 17-18". Weeks come from the `weeks` column
    # (a scalar or a list per row); a round with no week data just shows its
    # name. Two lines so a long round name ("Round 2 (seeds 3-4 pick)")
    # doesn't crowd the week against its neighbour.
    def _round_header(rid):
        rows = d[d["round_id"] == rid]
        name = str(rows["round"].iloc[0]) if len(rows) else str(rid)
        wks: set = set()
        for v in rows.get("weeks", []):
            for w in (v if isinstance(v, (list, tuple, set)) else [v]):
                try:
                    wks.add(int(w))
                except (TypeError, ValueError):
                    pass
        if not wks:
            return name
        ws = sorted(wks)
        wk_txt = f"Week {ws[0]}" if len(ws) == 1 else f"Weeks {ws[0]}-{ws[-1]}"
        return f"{name}\n{wk_txt}"
    ax.set_xticklabels([_round_header(r) for r in rounds],
                       fontweight="bold", fontsize=8.5)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"])
    # The round names are TOP-axis tick labels, so ANY text between the title
    # and the axes runs straight through them -- there is no subtitle band. The
    # title is kept SIMPLE ("<League> <Season> Playoff Bracket" /
    # "<League> <Season> Consolation Bracket"); the winner is already the visual
    # focus of the graphic itself (gold champion card), so it is not repeated
    # in the title. `variant` only switches "Playoff" <-> "Consolation".
    is_cons_variant = variant == "consolation"
    kind_word = "Consolation" if is_cons_variant else "Playoff"
    # Simple title: "<League> <Season> Playoff Bracket". `p.name` can carry a
    # generator suffix like " (Sleeper bracket)" / " (consolation bracket)"
    # and may already include the season -- strip the suffix, dedupe the year.
    import re as _re
    _nm = _re.sub(r"\s*\([^)]*\bbracket\b[^)]*\)\s*$", "", p.name or "").strip()
    _season = str(p.season)
    lead = _nm if _season and _season in _nm else f"{_nm} {_season}".strip()
    ax.set_title(f"{lead} {kind_word} Bracket", loc="left", fontsize=12,
                 fontweight="bold", color=T["ink"], pad=18)

    # Bottom band: ONE pill, the winner the bracket points at -- gold
    # CHAMPION for a playoff bracket, green WINNER for a consolation bracket
    # (there its "champion" is the best consolation finish; green matches its
    # winner cards and stays clear of the grey bye colour). No 3rd/last
    # pills: the graphic is about the winner.
    winner = p.champion
    if is_cons_variant:
        badge, fc, tc = "WINNER", "#4f9a54", "#ffffff"
    else:
        badge, fc, tc = "CHAMPION", "#f1c40f", "#242424"
    note = ("Scores from submitted lineups.  "
            + ("Green = win, red dashed = loser plays on, grey dotted = bye."
               if is_cons_variant else
               "Gold = champion, green = win, red dashed = loser plays on, "
               "grey dotted = bye, muted cards = placement games."))
    if ref_scores:
        note += "  (Bracketed) = a bye team's own score that week."

    bot = _PLAYOFF_CAPTION_BAND
    fig.tight_layout(rect=(0, bot, 1, 1))
    fig.canvas.draw()
    y_badge = bot * 0.60
    if winner:
        tb = fig.text(0.012, y_badge, f" {badge} ", fontsize=7, fontweight="bold",
                      color=tc, va="center", ha="left",
                      bbox=dict(boxstyle="round,pad=0.34", facecolor=fc,
                                edgecolor="none"))
        fig.canvas.draw()
        x_after = fig.transFigure.inverted().transform(
            (tb.get_window_extent().x1, 0))[0]
        fig.text(x_after + 0.008, y_badge, winner, fontsize=8.5,
                 fontweight="bold", color=T["ink2"], va="center", ha="left")
    fig.text(0.012, bot * 0.16, note, fontsize=6.5, color=T["muted"],
             va="bottom", wrap=True)
    return fig


def plot_consolation_bracket(p, consolation: dict, ref_scores: dict | None = None,
                     losers_bracket=None):
    """The consolation bracket: the teams that MISSED the championship bracket.

    A companion to `plot_playoff_bracket` (rendered beside it on the Playoffs
    tab).

    **Preferred rendering** -- when `losers_bracket` is a resolved `Playoff`
    (from `sm.playoff(sm.sleeper_losers_bracket(...))`), the consolation
    bracket is drawn as a real tree via `plot_playoff_bracket(..., variant=
    "consolation")`: clean left-to-right rounds, winner/bye connectors, the
    same card style as the championship bracket. Sleeper stores this bracket
    for most leagues, and it is the honest structure (winners advance, byes,
    placement games).

    **Fallback** -- when there is no coherent `losers_bracket` (a custom /
    incoherent one, or a season Sleeper never scored), the flat weekly
    layout below is used: week COLUMNS, each stacking that week's games, with
    the missed teams' byes shown as blue cards. Less structured, but it
    always works from `consolation["games"]` alone.

    `consolation` is `sm.consolation_bracket(s, p)`. `p` supplies the season label (and, in
    the fallback, the `_seeds` map for `#N` badges).
    """
    if losers_bracket is not None and len(getattr(losers_bracket, "results", [])):
        fig = plot_playoff_bracket(losers_bracket, ref_scores,
                                   consolation=consolation, variant="consolation")
        return fig

    from matplotlib.patches import FancyBboxPatch, Rectangle
    games = sorted((consolation or {}).get("games") or [], key=lambda g: g.get("week", 0))
    by_wk: dict = {}
    for g in games:
        by_wk.setdefault(g.get("week"), []).append(g)
    wks = sorted(by_wk)
    seeds = (getattr(p, "config", {}) or {}).get("_seeds") or {}
    seed_of = {v: k for k, v in seeds.items()}
    last_team = (consolation or {}).get("last")
    basis = (consolation or {}).get("basis")
    missed = set((consolation or {}).get("missed") or [])
    ref = ref_scores or {}

    # Byes: a missed-bracket team that DID NOT play a consolation bracket game a given
    # week sat that week out (Coin Flip and FF 2025: 6 missed teams, 4 play
    # each of weeks 15 and 17). Its own real weekly score is shown in
    # parentheses, exactly as the bracket shows a bye team's score.
    byes_by_wk: dict = {wk: [] for wk in wks}
    for wk in wks:
        played = {sd.get("team") for g in by_wk[wk] for sd in g.get("sides", [])}
        for t in sorted(missed - played):
            byes_by_wk[wk].append(t)

    # Card geometry matched to `plot_playoff_bracket` (CARD_H 0.40, the same
    # 0.88-wide card via +/-0.44). The bracket makes a matchup read as one
    # unit by locking its two cards close together with a WIDER gap before the
    # next -- so the consolation bracket does the same: PAIR_GAP holds a game's two
    # cards nearly touching, GAME_STEP puts a real gutter between games,
    # BYE_STEP stacks the (single-card) bye nodes below the games.
    CARD_H = 0.40
    CARD_HH = CARD_H / 2
    PAIR_GAP = 0.44                    # the two cards of ONE game, centre to centre
    GAME_STEP = PAIR_GAP + 0.52       # game to game in a week -- a visible gutter
    BYE_STEP = 0.56                    # bye card to bye card (single cards, tighter than a game)
    GAME_TO_BYE = 0.62                # last game's lower card -> first bye card

    # Same fixed footprint as `plot_playoff_bracket` so the two sit as an
    # equal-size pair.
    fig, ax = plt.subplots(figsize=_PLAYOFF_FIG)
    if not games:
        ax.text(0.5, 0.5, "No consolation bracket this season\n(every team reached the "
                "bracket)", ha="center", va="center", fontsize=10,
                color=T["muted"], transform=ax.transAxes)
        ax.set_axis_off()
        fig.tight_layout()
        return fig

    # Match the bracket's palette: win green, loss a soft reddish, bye a
    # neutral dark-ish grey (not amber, not the pink loss), last place its
    # own deeper red.
    COL_W, COL_L, COL_BYE = "#a5d6a7", "#f0dede", "#d1d4d8"
    COL_LAST = "#e7cfcc"
    WIN_EDGE, LOSS_EDGE, BYE_EDGE, LAST_EDGE = "#5fae63", "#d99b9b", "#8b9096", "#9b4a3f"
    BYE_LINE = "#8b9096"

    # ---- Vertical layout, per week column. A column is: its games (each a
    # tight card pair) stacked with GAME_STEP, then its bye cards stacked
    # below with BYE_STEP. The whole column's content is CENTRED in the
    # figure's y-extent so weeks with different game/bye counts sit balanced
    # rather than top-anchored and ragged -- mirroring the bracket, whose
    # matchup block is centred in each round column. `col_centre_span` is the
    # distance between the FIRST and LAST card centres in a column; the full
    # pixel extent is that plus 2*CARD_HH.
    def _centre_span(wk):
        ng, nb = len(by_wk[wk]), len(byes_by_wk[wk])
        s = (ng - 1) * GAME_STEP + PAIR_GAP if ng else 0.0
        if nb:
            s += (GAME_TO_BYE if ng else 0.0) + (nb - 1) * BYE_STEP
        return s
    col_centre_span = {wi: _centre_span(wk) for wi, wk in enumerate(wks)}
    tallest = max(col_centre_span.values(), default=0.0)
    # Fixed y-extent. Floored at ~4.4 data units so the cards render at the
    # SAME pixel size as the bracket's (whose own y-span for a full 4-round
    # bracket is ~4.5), rather than the consolation's smaller stack being blown up
    # to fill the panel. A sparse consolation bracket just gets empty space below,
    # exactly as a shallow bracket round does beside a deep one.
    span = max(tallest + 2 * CARD_HH, 4.4)
    y_lo = -0.36
    y_hi = span + 0.36
    mid = (y_lo + y_hi) / 2

    card_y: dict = {}                  # (team, week) -> y of that team's card
    game_spans: list = []             # (wi, top_sy, bot_sy) per game, for the join bracket

    for wi, wk in enumerate(wks):
        top = mid - col_centre_span[wi] / 2       # first card's centre
        cur = top
        for g in by_wk[wk]:
            sides = g.get("sides") or []
            n = len(sides[:2])
            g_top, g_bot = cur - CARD_HH, cur + (n - 1) * PAIR_GAP + CARD_HH
            game_spans.append((wi, cur, cur + (n - 1) * PAIR_GAP))
            ax.add_patch(Rectangle((wi - 0.5, g_top - 0.05), 1.0,
                                   (g_bot - g_top) + 0.10,
                                   facecolor=T["rule"], alpha=0.05,
                                   edgecolor="none", zorder=0))
            for si, sd in enumerate(sides[:2]):
                sy = cur + si * PAIR_GAP
                nm = sd.get("team", "")
                card_y[(nm, wk)] = sy
                is_last = (nm == last_team and wk == wks[-1]
                           and sd.get("result") == "L" and basis == "game")
                win = sd.get("result") == "W"
                pts = sd.get("points")
                _fc, _ec = ((COL_LAST, LAST_EDGE) if is_last
                            else (COL_W, WIN_EDGE) if win
                            else (COL_L, LOSS_EDGE))
                ax.add_patch(FancyBboxPatch(
                    (wi - 0.44, sy - CARD_HH), 0.88, CARD_H,
                    boxstyle="round,pad=0.006,rounding_size=0.05",
                    facecolor=_fc, edgecolor=_ec, lw=1.3 if (win or is_last) else 1.1,
                    zorder=2))
                sr = seed_of.get(nm, "")
                badge = f"#{sr}  " if sr else ""
                ax.text(wi - 0.40, sy - CARD_HH * 0.30, f"{badge}{nm}", ha="left",
                        va="center", fontsize=7.5, zorder=3,
                        fontweight="bold" if (win or is_last) else "normal",
                        color="#242424")
                ax.text(wi + 0.40, sy + CARD_HH * 0.42,
                        f"{pts:.1f}" if isinstance(pts, (int, float)) else "–",
                        ha="right", va="center", fontsize=7, family="monospace",
                        color="#3a3a3a", zorder=3)
                if is_last:
                    ax.text(wi + 0.48, sy, "◄ last place", ha="left",
                            va="center", fontsize=7, style="italic",
                            fontweight="bold", color="#9b4a3f", zorder=3)
            cur += (n - 1) * PAIR_GAP + GAME_STEP
        # Bye cards below the games -- single cards, grey, the team's own
        # weekly score parenthesised (same convention as the bracket).
        if byes_by_wk[wk]:
            cur += (GAME_TO_BYE - GAME_STEP) if by_wk[wk] else 0.0
            for bt in byes_by_wk[wk]:
                card_y[(bt, wk)] = cur
                ax.add_patch(FancyBboxPatch(
                    (wi - 0.44, cur - CARD_HH), 0.88, CARD_H,
                    boxstyle="round,pad=0.006,rounding_size=0.05",
                    facecolor=COL_BYE, edgecolor=BYE_EDGE, lw=1.2, zorder=2))
                sr = seed_of.get(bt, "")
                badge = f"#{sr}  " if sr else ""
                ax.text(wi - 0.40, cur - CARD_HH * 0.30, f"{badge}{bt}", ha="left",
                        va="center", fontsize=7.5, zorder=3, color="#242424")
                bp = ref.get((bt, wk))
                ax.text(wi + 0.40, cur + CARD_HH * 0.42,
                        f"({bp:.1f})" if isinstance(bp, (int, float)) else "bye",
                        ha="right", va="center", fontsize=7, family="monospace",
                        color="#5a5f66", zorder=3, style="italic")
                cur += BYE_STEP

    # Join bracket: a small "[" on the LEFT edge of each game, tying its two
    # cards -- the explicit "these two played each other" mark.
    for wi, top_sy, bot_sy in game_spans:
        if abs(bot_sy - top_sy) < 1e-6:
            continue
        xb = wi - 0.47
        ax.plot([xb + 0.04, xb, xb, xb + 0.04],
                [top_sy, top_sy, bot_sy, bot_sy],
                color=T["tick"], lw=1.4, zorder=1,
                solid_capstyle="round", solid_joinstyle="round")

    # Advance connectors, colour-coded to match the cards: a bye = blue
    # dotted; the consolation bracket WINNER's path = gold; any other week's winner
    # advancing = green.
    _tb_winner = None
    # The overall consolation winner is whoever wins the LAST game.
    if games:
        _lastg = max(games, key=lambda g: g.get("week", 0))
        _tb_winner = next((sd.get("team") for sd in _lastg.get("sides", [])
                           if sd.get("result") == "W"), None)
    WIN_LINE, GOLD_LINE = "#8bbf8f", "#e6b800"

    def _connect(team, wk, dotted):
        try:
            nxt = wks[wks.index(wk) + 1]
        except (ValueError, IndexError):
            return
        src, dst = card_y.get((team, wk)), card_y.get((team, nxt))
        if src is None or dst is None:
            return
        wi = wks.index(wk)
        x_out, x_in = wi + 0.44, wi + 1 - 0.44
        x_turn = x_out + (x_in - x_out) * 0.4
        if dotted:
            kw = dict(color=BYE_LINE, lw=1.4, linestyle=(0, (1, 2)))
        elif _tb_winner and team == _tb_winner:
            kw = dict(color=GOLD_LINE, lw=2.6)
        else:
            kw = dict(color=WIN_LINE, lw=2.2)
        ax.plot([x_out, x_turn, x_turn, x_in], [src, src, dst, dst], zorder=1,
                solid_capstyle="round", solid_joinstyle="round", **kw)

    for g in games:
        wk = g.get("week")
        w_team = next((sd.get("team") for sd in g.get("sides", [])
                       if sd.get("result") == "W"), None)
        if w_team is not None:
            _connect(w_team, wk, dotted=False)
    for wk in wks:
        for bt in byes_by_wk[wk]:
            _connect(bt, wk, dotted=True)

    # Faint vertical splitters between week columns.
    for wi in range(len(wks) - 1):
        ax.plot([wi + 0.5, wi + 0.5], [y_lo + 0.15, y_hi - 0.15],
                color=T["grid"], lw=1.0, zorder=0)

    # A minimum x-span so a one- or two-week consolation bracket doesn't render its
    # cards blown up to fill the fixed-width panel; extra weeks pack tighter.
    ax.set_xlim(-0.6, max(len(wks) - 0.4, 2.6))
    ax.set_ylim(y_hi, y_lo)                    # inverted: week labels on top
    # Week columns as TOP-axis tick labels -- the same treatment the bracket
    # gives its "Round 1 / Round 2 / ..." headers, so the two charts' column
    # headings sit at the same place and in the same style.
    ax.set_xticks(range(len(wks)))
    ax.set_xticklabels([f"Week {w}" for w in wks], fontweight="bold", fontsize=8.5)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"])
    # Title in the bracket's own shape ("<league> · <season> <thing>: <headline>")
    # and size, so the pair reads as one family.
    _last_txt = last_team or "undecided"
    ax.set_title(f"{getattr(p, 'name', 'Consolation bracket')} · {getattr(p, 'season', '')} "
                 f"Consolation bracket: Last place, {_last_txt}", loc="left",
                 fontsize=11.5, fontweight="bold", color=T["ink"], pad=18)
    any_byes = any(byes_by_wk[wk] for wk in wks)
    bye_note = "  Grey = a week off (score in parentheses)." if any_byes else ""
    if last_team and basis == "game":
        outcome = f"Last place: {last_team}"
        note = ("Scores from submitted lineups.  Green = win, red = loss." + bye_note +
                f"  {last_team} lost the final game.")
    elif last_team:
        outcome = f"Last place: {last_team}"
        note = ("Worst regular-season finish among the teams that missed the "
                "bracket; no game decided it." + bye_note)
    else:
        outcome = "Last place: undecided"
        note = "Teams that missed the championship bracket." + bye_note
    # Same two-line fixed caption band as the bracket (bold outcome line, muted
    # note under it), so the text sits at the same height and can't resize the
    # figure.
    bot = _PLAYOFF_CAPTION_BAND
    fig.text(0.012, bot * 0.62, outcome, fontsize=8, fontweight="bold",
             color=T["ink2"], va="bottom")
    fig.text(0.012, bot * 0.18, note, fontsize=6.5, color=T["muted"],
             va="bottom", wrap=True)
    fig.tight_layout(rect=(0, bot, 1, 1))
    return fig


def plot_consolation_players_splice(tb: dict, n: int = 15):
    """Best Consolation bracket Players: each player's total consolation bracket points drawn
    as one SEGMENT PER GAME (earliest week at left), so a total reads as the
    games that built it -- the consolation bracket counterpart to
    `plot_playoff_players_splice`. Single season, no rings, no round depth
    (the consolation bracket has no sub-brackets), so segment colour is just the game
    slot (1st consolation game, 2nd, ...), using `_MANAGER_HUES` as an ordered
    categorical set the same way the bracket splice chart keys its own
    segments by round depth. Position rides in the row label. Best-effort:
    an empty consolation bracket degrades to a titled blank panel.
    """
    from .playoffs import consolation_performances, consolation_players
    top = consolation_players(tb).head(n).iloc[::-1].reset_index(drop=True)
    if top.empty:
        return _no_data("No consolation bracket games this season.")
    perf = consolation_performances(tb)
    perf = perf[perf["player_id"].isin(top["player_id"])].sort_values(
        ["player_id", "week"])
    # Game slot per player (0 = their first consolation bracket game by week), the
    # colour key -- the consolation bracket has no rounds to colour by.
    perf = perf.assign(slot=perf.groupby("player_id").cumcount())
    fig, ax = plt.subplots(figsize=(10, 6.4))
    labels = [f"{r['player_name']}  ·  {r['position']}" for _, r in top.iterrows()]
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(labels, fontsize=8.5)
    for t in ax.get_yticklabels():
        t.set_ha("right")
    ax.tick_params(axis="y", pad=4)
    _portraits(ax, labels, top["player_id"], top["position"], zoom=0.30)
    xmax = float(top["points"].max())
    seen_slots: set = set()
    for i, r in top.iterrows():
        games = perf[perf["player_id"] == r["player_id"]]
        left = 0.0
        for _, g in games.iterrows():
            pts = float(g["points"])
            slot = int(g["slot"])
            seen_slots.add(slot)
            color = _MANAGER_HUES[slot % len(_MANAGER_HUES)]
            ax.barh(i, pts, left=left, height=0.72, color=color,
                    edgecolor=T["bg"], linewidth=1.0, zorder=2)
            if pts >= xmax * 0.045:
                ax.text(left + pts / 2, i, f"{pts:.0f}", ha="center", va="center",
                        fontsize=7, fontweight="bold", color="white", zorder=3)
            left += pts
        ax.text(left + xmax * 0.01, i, f"{r['points']:.0f} total  ({r['ppg']:.1f} ppg)",
                va="center", fontsize=8.5, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.34)
    from matplotlib.patches import Patch
    handles = [Patch(facecolor=_MANAGER_HUES[sl % len(_MANAGER_HUES)],
                     label=f"Game {sl + 1}") for sl in sorted(seen_slots)]
    if handles:
        ax.legend(handles=handles, loc="lower right", frameon=True,
                  framealpha=0.92, edgecolor=T["grid"], facecolor=T["bg"],
                  fontsize=7.5, title="Consolation bracket game", title_fontsize=7.5,
                  borderpad=0.7, labelspacing=0.5)
    yrs = sorted({str(g.get("week")) for g in tb.get("games", [])})
    span = "the consolation bracket"
    return _finish(fig, ax, "Best Consolation bracket Players",
                   f"Points across {span}  ·  each slice is one game, earliest at "
                   "left, width = that game's points", "Consolation bracket Points")


def plot_consolation_clutch(s, tb: dict):
    """Consolation bracket PPG vs Regular-Season PPG -- did a team score more once it
    was out of the running? The consolation bracket counterpart to `plot_clutch`
    (one season, missed-bracket teams). Best-effort: no consolation games degrades
    to a titled blank panel.
    """
    from .playoffs import consolation_clutch
    d = consolation_clutch(s, tb)
    # Ordered by consolation bracket scoring itself (the coloured dot), highest at the
    # top -- matches plot_clutch, which sorts by its own postseason PPG.
    d = d[d["reg_ppg"].notna()].sort_values("to_ppg").reset_index(drop=True)
    if d.empty:
        return _no_data("No consolation bracket games this season.")
    fig, ax = plt.subplots(figsize=(10, 6))
    cols = ["#2ca02c" if v > 0 else "#d62728" for v in d["clutch"]]
    for i, r in d.iterrows():
        ax.plot([r["reg_ppg"], r["to_ppg"]], [i, i], color=cols[i], lw=2.5,
                alpha=0.5, zorder=1)
    ax.scatter(d["reg_ppg"], range(len(d)), color="#a6a6a6", s=65, zorder=2)
    ax.scatter(d["to_ppg"], range(len(d)), color=cols, s=95, zorder=3)
    for i, r in d.iterrows():
        off, ha = (2, "left") if r["clutch"] > 0 else (-2, "right")
        ax.text(r["to_ppg"] + off, i, f"{r['clutch']:+.1f}", va="center", ha=ha,
                fontsize=8, fontweight="bold", color=cols[i])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    lo = min(d["reg_ppg"].min(), d["to_ppg"].min())
    hi = max(d["reg_ppg"].max(), d["to_ppg"].max())
    pad = max((hi - lo) * 0.15, 1.5)
    ax.set_xlim(lo - pad, hi + pad)
    return _finish(fig, ax, "Clutch: Consolation bracket vs Regular-Season Scoring",
                   "Grey dot = regular-season PPG; coloured = consolation bracket PPG  ·  "
                   "the consolation bracket", "Points per Game")


def _po_span(playoffs: dict) -> tuple:
    """(title suffix, subtitle phrase) for a playoff chart.

    These charts aggregate whatever brackets they are handed, so the same
    function serves both the all-time view and a single-season one -- the
    caller scopes by passing a one-entry dict. The labels have to follow, or a
    2025-only chart still claims to be career-wide.
    """
    yrs = sorted(str(y) for y in playoffs)
    if len(yrs) == 1:
        return f" ({yrs[0]})", f"the {yrs[0]} postseason"
    return " (All Time)", f"{len(yrs)} postseasons"


def plot_playoff_stats(playoffs: dict, scope: str = "title"):
    """Playoff win %, gold for managers with a title."""
    from .playoffs import playoff_stats
    d = playoff_stats(playoffs, scope)
    d = d[d["games"] > 0].sort_values("win_pct").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.barh(range(len(d)), d["win_pct"], height=0.72,
            color=["#f1c40f" if t > 0 else "#9fb8c8" for t in d["titles"]])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    for i, r in d.iterrows():
        stars = "★" * int(r["titles"])
        ax.text(r["win_pct"] + 1, i, f"{int(r['wins'])}-{int(r['losses'])}  "
                f"{r['win_pct']:.0f}%  {stars}", va="center", fontsize=8.5, color=T["ink2"])
    ax.set_xlim(0, 100)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Playoff Record{suffix}",
                   f"Win % across {span}  ·  {sub}  ·  "
                   "gold = won a title  ·  ★ per title", "Playoff Win %")


def plot_playoff_players(playoffs: dict, n: int = 15, scope: str = "title"):
    """Career playoff scoring leaders -- who actually produces in January."""
    from .playoffs import playoff_players
    d = playoff_players(playoffs, scope).head(n).iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.barh(range(len(d)), d["points"], height=0.72,
            color=[POS_COLORS.get(str(p), "#999999") for p in d["position"]])
    labels = [f"{n}  ·  {p}" for n, p in zip(d["player_name"], d["position"])]
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(labels, fontsize=8.5)
    _portraits(ax, labels, d["player_id"], d["position"])
    xmax = float(d["points"].max())
    for i, r in d.iterrows():
        rings = "★" * int(r["rings"])
        ax.text(r["points"] + xmax * 0.01, i,
                f"{r['points']:.0f}  ({r['ppg']:.1f} ppg)  {rings}",
                va="center", fontsize=8.5, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.34)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    seen = [p for p in POSITIONS if p in set(d["position"])]
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in seen]
    ax.legend(handles, seen, loc="lower right", frameon=False, fontsize=8, ncol=3)
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Best Playoff Players{suffix}",
                   f"Points scored across {span}  ·  {sub}  ·  ★ per title",
                   "Playoff Points")


def plot_playoff_players_splice(seasons: dict, playoffs: dict, n: int = 15,
                                scope: str = "title", consolation: list | None = None,
                                consolation_label: str = "Consolation bracket"):
    """Best Playoff Players, spliced-bar version (2026-08, promoted out of the
    Testing tab onto the Playoffs tab itself, replacing `plot_playoff_players`
    there -- that function stays as-is for the Career tab's `_all` scope,
    which hasn't been asked to make the same jump): each player's
    total-points bar is cut into one SEGMENT PER GAME instead of drawn as one
    solid block -- e.g. a player whose 80 total points came from games of 20,
    20, and 40 shows three visible slices of those exact widths, left to
    right, rather than a single 80-wide bar that hides how that total was
    actually built. Reads `playoff_performances()` directly (the row-per-
    player-week grain `playoff_players()` itself aggregates FROM) rather than
    the aggregated table, since the per-game rows are exactly what's missing
    from that simpler chart.

    Slices are ordered CHRONOLOGICALLY (earliest game first, sorted by season
    then week) -- left to right traces the player's whole playoff career in
    order, so a late-career hot streak (or early-career quiet stretch) is
    visible as a shape, not just implied by the total. A player's games can
    span MULTIPLE SEASONS (this is a CAREER leaderboard, same scope as the
    original chart), so "game 1" means their first career playoff game, not
    game 1 of any single bracket.

    Colour is ROUND DEPTH (that season's Round 1, Round 2, Final, ...), NOT
    raw game slot (2026-08, changed from an earlier "1st game, 2nd game,
    3rd..." scheme) -- game slot couldn't tell apart two players who each
    have exactly ONE playoff game on the board: under game slot both were
    simply "game 1" and got the identical colour, even when one of those
    games was a Round 1 loss and the other a Final appearance. Depth is
    read from each season's own `config["rounds"]` list order (already
    depth-ordered) via a `{(season, round_id): depth}` lookup built once per
    call -- NOT the `round` display name, which isn't comparable across
    seasons/leagues (2025's "Round 1 (seeds 5-8)" vs 2022's plain
    "Round 1"). Reuses `_MANAGER_HUES` purely as an ordered categorical set
    here (same "index by position, not by manager identity" precedent
    `plot_trade_single_contribution` already uses for its own per-player
    segments) -- this replaces position-as-color entirely, so position moves
    into the label instead (same "position as text, not bar color"
    convention the `_postext` prototype in this same round already
    established). A compact legend keys the colours: one swatch per round
    DEPTH that actually appears in the charted data (not every possible
    depth), labelled by the round's own display name with any parenthetical
    seeding qualifier stripped ("Round 1 (seeds 5-8)" -> "Round 1"), or a
    generic "Round N" if seasons disagree on the bare name; the two star
    colours (title / runner-up) are folded into the same box. Each slice's
    own points value is still labelled inside it when there's room.

    `seasons` ({season_str: Season}, the same dict `plot_clutch` already
    takes) is needed for the label's `pos_rank` badge -- that rank is a
    SEASON-scoped fact (`metrics.season_position_ranks`), and this is a
    CAREER chart, so a player who scored playoff points in more than one
    season has no single "the" rank; the label shows their MOST RECENT
    scoring season's rank (highest season key each player's own rows touch)
    rather than their best-ever or a blended figure, matching how an
    identity is normally read as "current." Best-effort: a season key with
    no matching `Season` in `seasons`, or no rank for that player, degrades
    to no badge rather than failing the whole chart.
    """
    import pandas as pd
    from .playoffs import playoff_performances, playoff_players
    # `consolation` (a list of consolation_bracket() dicts) folds the consolation bracket into the
    # same leaderboard for the Postseason view -- see playoff_performances'
    # own `consolation=` argument. Only pooled when scope == "all".
    top = playoff_players(playoffs, scope, consolation=consolation).head(n).iloc[::-1].reset_index(drop=True)
    if top.empty:
        return _no_data("No playoff performances recorded.")
    perf = playoff_performances(playoffs, scope, consolation=consolation)
    perf = perf[perf["player_id"].isin(top["player_id"])]
    perf = perf.sort_values(["player_id", "season", "week"])
    # Round DEPTH (0 = that season's first round, 1 = second, ...), not raw
    # game count -- a player with exactly one playoff game in the Final and
    # another with exactly one game in Round 1 need visibly different
    # colours, which game-slot colouring (this chart's original scheme)
    # couldn't do: both would be "game 1" and get the same hue. Depth is
    # read from each season's OWN `config["rounds"]` list order (already
    # depth-ordered: R1 before R2 before R3...) rather than the `round`
    # display NAME, which isn't comparable across seasons/leagues (2025's
    # "Round 1 (seeds 5-8)" vs 2022's plain "Round 1").
    round_depth: dict = {}
    depth_names: dict = {}   # depth -> set of display names seen at that depth
    max_depth = -1
    for s, p in playoffs.items():
        rids = [rd["id"] for rd in p.config.get("rounds", [])]
        for depth, rid in enumerate(rids):
            round_depth[(str(s), rid)] = depth
            max_depth = max(max_depth, depth)
            nm = next((rd.get("name") for rd in p.config.get("rounds", [])
                       if rd["id"] == rid), None)
            if nm:
                depth_names.setdefault(depth, set()).add(str(nm))
    # Postseason segments outside the championship bracket, present only when
    # `consolation=` was passed and scope == "all". Two shapes:
    #   * a genuine missed-teams CONSOLATION BRACKET -- no bracket structure, every
    #     row `round_id is None`: one flat depth past the deepest real round,
    #     one legend entry (`consolation_label`, "Consolation bracket").
    #   * a real CONSOLATION BRACKET (Sleeper's `losers_bracket`, resolved by
    #     the webapp) -- rows carry `round_id == "C<week>"`: each consolation
    #     round gets its OWN depth (past the real rounds, in week order) and
    #     its own legend entry ("<consolation_label> R1", ...), so the graphic
    #     shows the consolation bracket's rounds, not one lump.
    _cons_rids = sorted({rid for rid in perf["round_id"].dropna().unique()
                         if str(rid).startswith("C")},
                        key=lambda r: int(str(r)[1:]))
    consolation_flat_depth = max_depth + 1                    # flat consolation bracket only
    cons_depth: dict = {}                           # "C<week>" -> depth
    for k, rid in enumerate(_cons_rids):
        cons_depth[rid] = max_depth + 1 + k
        # Legend label: "Consolation Round 1", "Consolation Round 2", ... when
        # the consolation bracket has multiple rounds; a bare "Consolation
        # bracket" when it is a single game.
        if len(_cons_rids) > 1:
            lbl = f"Consolation Round {k + 1}"
        else:
            lbl = consolation_label
        depth_names.setdefault(cons_depth[rid], set()).add(lbl)
    if not perf.empty and perf["round_id"].isna().any():
        depth_names.setdefault(consolation_flat_depth, set()).add(consolation_label)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    pos_ranks: dict = {}
    for pid, g in perf.groupby("player_id"):
        latest = str(g["season"].max())
        s_obj = seasons.get(latest)
        if s_obj is None:
            continue
        try:
            r = metrics.season_position_ranks(s_obj).get(str(pid))
        except Exception:
            r = None
        if r:
            pos_ranks[pid] = r["rank"]
    # A player gets a star next to their NAME (not buried mid-bar on whichever
    # slice happened to be a title-game season) if ANY of their playoff games
    # were played on that season's champion roster (gold) or runner-up roster
    # (silver) -- both can apply to the same player (won it one year, lost
    # the final another), so this is an "ever" flag per colour, not a single
    # per-player outcome. Scoped to season-level champion/runner-up, not a
    # whole-career rings tally (that's `plot_playoff_players`'s own, separate
    # "rings" reading).
    honors = perf.groupby("player_id")[["champion", "runner_up"]].any()
    labels = []
    for _, r in top.iterrows():
        badge = f" #{pos_ranks[r['player_id']]}" if r["player_id"] in pos_ranks else ""
        labels.append(f"{r['player_name']}  ·  {r['position']}{badge}")
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(labels, fontsize=8.5)
    # Right-aligned so the label text hugs the bars it names -- text ends
    # flush at the same x for every row, and a SHORT name (e.g. "Puka
    # Nacua") is the one that shifts right, not the long ones trailing off
    # into open space the way a left-aligned column would.
    #
    # This can't reuse `_portraits`/`_identity_rows`: that helper hangs
    # every row's portrait icon at ONE SHARED x offset (sized off the
    # WIDEST label), which only stays adjacent to the text when every row's
    # text also starts at that same shared x -- true for a left-aligned
    # column, false here, where each row's text starts at a DIFFERENT x
    # depending on that row's own width. Reimplemented inline so each
    # icon's offset is measured from its OWN row's text, not the shared
    # column edge.
    for t in ax.get_yticklabels():
        t.set_ha("right")
    # A SMALL fixed pad, not one sized off the widest label -- that was the
    # actual bug behind an earlier version's huge dead space on the left of
    # this whole chart. `_identity_rows`'s own `maxw_px`-sized pad exists to
    # reserve room for LEFT-aligned text, which all starts flush at the tick
    # position and needs the tick pulled left by the WIDEST row's full width
    # so nothing collides with the axis. Right-aligned text is the opposite:
    # every row's text already ENDS at a fixed point regardless of its own
    # length, so the tick only needs a small fixed clearance (past the tick
    # mark's own dash), never the longest label's width -- reusing that
    # left-aligned formula here anchored every row's tick (and therefore
    # every row's right-aligned text) `maxw_px` points from the axis, which
    # is why "Puka Nacua" rendered with a huge gap before its own text: the
    # tick itself, not the text, was pushed that far left.
    ax.tick_params(axis="y", pad=4)
    # Portrait icons are placed as the very LAST step in this function (after
    # bars/xlim/_finish have all settled), not here -- `xlim` isn't final
    # yet at this point (no bars drawn, no margin computed), so converting a
    # measured pixel position to DATA coordinates now would be stale the
    # moment `xlim` changes later. Only the LABEL geometry (ha, tick pad) is
    # locked in at this point; the icon x-per-row is computed once real
    # data-space is stable, same principle as the star markers below.
    xmax = float(top["points"].max())
    # Star markers, when a row earns one, ride right after the row's own
    # trailing "N total (X ppg)" text -- see the honor_rows loop below.
    # markersize=11 stars render ~15.3px wide and are CENTRE-anchored, not
    # left-anchored (measured via get_window_extent(); an earlier
    # name-column version of this placed a star's centre only 10px past the
    # text it followed, leaving barely ~2px of true clearance to the star's
    # own left edge -- close enough to read as sitting on the text, worse in
    # dark mode where the lower-contrast silver tone made the two harder to
    # tell apart). STAR_HALF_PX/GAP_PX/STAR_STEP_PX below are sized off that
    # measured footprint, not the marker's centre coordinate.
    STAR_HALF_PX = 8.0
    GAP_PX = 6.0 + STAR_HALF_PX          # text end -> first star's LEFT edge
    STAR_STEP_PX = 2 * STAR_HALF_PX + 2  # star centre -> next star centre
    honor_rows = {}
    for i, (_, r) in enumerate(top.iterrows()):
        pid = r["player_id"]
        gold = silver = False
        if pid in honors.index:
            gold, silver = bool(honors.loc[pid, "champion"]), bool(honors.loc[pid, "runner_up"])
        if gold or silver:
            honor_rows[i] = (gold, silver)
    label_texts = {}
    seen_depths: set = set()
    for i, r in top.iterrows():
        games = perf[perf["player_id"] == r["player_id"]]
        left = 0.0
        for _, g in games.iterrows():
            pts = float(g["points"])
            _rid = g["round_id"]
            if pd.isna(_rid):
                depth = consolation_flat_depth
            elif str(_rid).startswith("C"):
                depth = cons_depth.get(_rid, consolation_flat_depth)
            else:
                depth = round_depth.get((g["season"], _rid), 0)
            seen_depths.add(depth)
            color = _MANAGER_HUES[depth % len(_MANAGER_HUES)]
            ax.barh(i, pts, left=left, height=0.72, color=color,
                    edgecolor=T["bg"], linewidth=1.0, zorder=2)
            if pts >= xmax * 0.045:
                ax.text(left + pts / 2, i, f"{pts:.0f}", ha="center", va="center",
                        fontsize=7, fontweight="bold", color="white", zorder=3)
            left += pts
        label_texts[i] = ax.text(left + xmax * 0.01, i,
                                 f"{r['points']:.0f} total  ({r['ppg']:.1f} ppg)",
                                 va="center", fontsize=8.5, color=T["ink2"])
    # Right margin is measured EXACTLY off the single widest label-plus-star
    # requirement (up to 2 stars) rather than a flat guessed fraction of
    # xmax, which either wasted space on every row or clipped stars on the
    # longest one depending which way the guess erred -- same "measure the
    # actual rendered extent, then place relative to it" technique
    # `_identity_rows`' portrait placement already uses (there: left of the
    # label; here: past the trailing "total (ppg)" text).
    if honor_rows:
        fig.canvas.draw()
        px_per_data = ax.transData.transform((1, 0))[0] - ax.transData.transform((0, 0))[0]
        needed_px = 0.0
        for i in honor_rows:
            n_stars = sum(honor_rows[i])
            text_end_px = label_texts[i].get_window_extent().x1
            star_end_px = (text_end_px + GAP_PX + STAR_HALF_PX
                           + (n_stars - 1) * STAR_STEP_PX + STAR_HALF_PX)
            needed_px = max(needed_px, star_end_px)
        widest_text_end_px = max(t.get_window_extent().x1 for t in label_texts.values())
        extra_data = max(0.0, (needed_px - widest_text_end_px + 6) / px_per_data)
        ax.set_xlim(0, xmax * 1.34 + extra_data)
    else:
        ax.set_xlim(0, xmax * 1.34)
    if consolation is not None:
        sub = "playoffs + consolation bracket"
        title_word, axis_word = "Postseason", "Postseason"
    elif scope == "title":
        sub = "championship path"
        title_word = axis_word = "Playoff"
    else:
        sub = f"scope: {scope}"
        title_word = axis_word = "Playoff"
    suffix, span = _po_span(playoffs)
    fig = _finish(fig, ax, f"Best {title_word} Players{suffix}",
                  f"{sub}  ·  each slice is one game, earliest at left, "
                  "width = that game's points",
                  f"{axis_word} Points")

    # Colour key: one entry per round DEPTH that actually shows up in the
    # drawn segments, plus the two star meanings -- folded into a single
    # legend box rather than spelled out in the subtitle. The legend only
    # needs to say WHICH ROUND a slice's points came from, so the label is
    # the round's own display name with any parenthetical seeding qualifier
    # ("Round 1 (seeds 5-8)" -> "Round 1") stripped; if seasons disagree on
    # the bare name it falls back to a generic "Round N".
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    def _depth_label(depth: int) -> str:
        bare = {re.sub(r"\s*\(.*\)\s*$", "", nm).strip()
                for nm in (depth_names.get(depth) or set())}
        return next(iter(bare)) if len(bare) == 1 else f"Round {depth + 1}"
    handles = [Patch(facecolor=_MANAGER_HUES[dp % len(_MANAGER_HUES)],
                     label=_depth_label(dp)) for dp in sorted(seen_depths)]
    if honor_rows:
        any_gold = any(g for g, _ in honor_rows.values())
        any_silver = any(s for _, s in honor_rows.values())
        star = lambda c, lbl: Line2D([0], [0], marker="*", linestyle="none",
                                     markerfacecolor=c, markeredgecolor="white",
                                     markeredgewidth=1.0, markersize=11, label=lbl)
        if any_gold:
            handles.append(star("#f1c40f", "★ = on a title team"))
        if any_silver:
            handles.append(star("#c8cdd0", "★ = on a runner-up"))
    if handles:
        ax.legend(handles=handles, loc="lower right", frameon=True,
                  framealpha=0.92, edgecolor=T["grid"], facecolor=T["bg"],
                  fontsize=7.5, title="Round", title_fontsize=7.5,
                  borderpad=0.7, labelspacing=0.5)

    # `_finish` calls `tight_layout`, which resizes the axes box within the
    # figure -- any pixel<->data measurement taken before it is stale by the
    # time the figure is actually drawn, so both the icons and the stars
    # below are placed AFTER this point, not before.
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    fig.canvas.draw()
    inv = ax.transData.inverted()
    # Portrait icons, one per row, positioned relative to that row's own
    # (now right-aligned, so ragged-LEFT) tick-label text -- can't reuse
    # `_portraits`/`_identity_rows`: that helper hangs every icon at ONE
    # SHARED x offset sized off the WIDEST label, which only stays adjacent
    # to the text when every row's text also starts at that same shared x
    # (true for a left-aligned column, false here, where each row's text
    # starts at a DIFFERENT x depending on that row's own width).
    icon_gap_px = 7.4 * fig.dpi / 72.0
    for i, (pid, pos) in enumerate(zip(top["player_id"], top["position"])):
        img = headshots.load(pid, pos, size=72)
        if img is None:
            continue
        label_x0_px = ax.get_yticklabels()[i].get_window_extent().x0
        icon_x_data = inv.transform((label_x0_px - icon_gap_px, 0))[0]
        ab = AnnotationBbox(OffsetImage(img, zoom=0.30), (icon_x_data, i),
                            xycoords="data", frameon=False,
                            box_alignment=(1.0, 0.5), pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)

    # Drawn via marker="*" + white ring -- same convention
    # `_highlight_eff_extremes` established for a gold star -- rather than a
    # plain text glyph: a bare colored "★" glyph at silver's shade all but
    # disappeared against this chart's white background, and the white ring
    # is what actually fixes that, not a darker fill on its own.
    for i, (gold, silver) in honor_rows.items():
        text_end_px = label_texts[i].get_window_extent().x1
        stars = (["#f1c40f"] if gold else []) + (["#c8cdd0"] if silver else [])
        for k, star_color in enumerate(stars):
            star_px = text_end_px + GAP_PX + STAR_HALF_PX + k * STAR_STEP_PX
            star_x_data = inv.transform((star_px, 0))[0]
            ax.plot(star_x_data, i, marker="*", markersize=11,
                    markerfacecolor=star_color, markeredgecolor="white",
                    markeredgewidth=1.0, zorder=5, linestyle="none",
                    clip_on=False, transform=ax.transData)
    return fig


# --- Playoff bracket appearance prototypes (Testing tab) ---------------------
# Four proposed restylings of `plot_playoff_bracket`, each an isolated variable
# to judge before any of it lands in the real chart. They share `_bracket_geom`
# (the same node layout the production function builds inline) so only the
# DRAWING differs between them. All obey the production chart's own rule:
# nothing between the title and the top-axis round labels -- the champion rides
# in the title, and any explanation goes to the bottom via `fig.text`.

def _bracket_geom(p):
    """Node layout for a bracket chart: one row per team-per-matchup, with
    `rx` (round column), `y` (row within the figure), `cy` (matchup centre)
    and `side`. Lifted from `plot_playoff_bracket` (including its side-order
    pass that keeps feeder connectors from crossing) so the appearance
    prototypes don't each re-derive it. Returns `(d, rounds, span, seed_of)`.
    """
    import pandas as pd
    GAP = 0.46
    d = p.results.copy()
    rounds = list(dict.fromkeys(d["round_id"]))
    seeds = (p.config.get("_seeds") or {})
    seed_of = {v: k for k, v in seeds.items()}
    mu = d.drop_duplicates("matchup_id")[["round_id", "matchup_id"]].copy()
    mu["j"] = mu.groupby("round_id").cumcount() + 1
    mu["n"] = mu.groupby("round_id")["matchup_id"].transform("size")
    span = int(mu["n"].max())
    mu["rx"] = mu["round_id"].map({r: i for i, r in enumerate(rounds)})
    mu["cy"] = (mu["j"] - 0.5) * span / mu["n"]
    d = d.merge(mu[["matchup_id", "rx", "cy"]], on="matchup_id", how="left")
    d["side"] = d.groupby("matchup_id").cumcount()
    d["sides"] = d.groupby("matchup_id")["team"].transform("size")
    d["y"] = d["cy"] + (d["sides"] > 1) * (d["side"] * GAP - GAP / 2)

    def _src_y(team, rx, placed):
        prior = placed[(placed["team"] == team) & (placed["rx"] < rx)]
        if not len(prior):
            return None
        wins = prior[prior["result"] == "W"]
        row = wins.iloc[-1] if len(wins) else prior.sort_values("rx").iloc[0]
        return float(row["y"])

    for ri in range(1, len(rounds)):
        placed = d[d["rx"] < ri]
        for _, grp in d[d["rx"] == ri].groupby("matchup_id"):
            if len(grp) != 2:
                continue
            (i0, r0), (i1, r1) = list(grp.iterrows())
            s0, s1 = _src_y(r0["team"], ri, placed), _src_y(r1["team"], ri, placed)
            if s0 is None or s1 is None or s0 == s1:
                continue
            want_top = i0 if s0 < s1 else i1
            top_now = i0 if r0["side"] == 0 else i1
            if want_top != top_now:
                d.loc[[i0, i1], "side"] = d.loc[[i1, i0], "side"].values
                d.loc[[i0, i1], "y"] = d.loc[[i1, i0], "y"].values
    return d, rounds, span, seed_of


def _bracket_axes(fig, ax, p, rounds, d, span, note):
    """Shared frame for the bracket prototypes: hide spines/ticks, round names
    on the TOP axis, champion in the title, explanation at the figure bottom.
    """
    ax.set_xlim(-0.6, len(rounds) - 0.4)
    ax.set_ylim(span + 0.25, -0.25)
    ax.set_xticks(range(len(rounds)))
    ax.set_xticklabels(list(dict.fromkeys(d["round"])), fontweight="bold")
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"])
    ax.set_title(f"{p.name} · {p.season} Bracket: Champion, "
                 f"{p.champion or 'undecided'}", loc="left", fontsize=16,
                 fontweight="bold", color=T["ink"], pad=26)
    fig.text(0.01, 0.015, note, fontsize=9, color=T["muted"], va="bottom")
    fig.tight_layout(rect=(0, 0.055, 1, 1))


def _bracket_team_label(team):
    return "TBD" if str(team).startswith(("W:", "L:")) else team


def _bracket_node_pts(r, ref_scores):
    import pandas as pd
    if not pd.isna(r["points"]):
        return f"{r['points']:.1f}"
    return _ref_label(ref_scores, r["team"], r["weeks"])


# The production `plot_playoff_bracket` now ships items 1 (elbow connectors)
# and 2 (two-line node cards), so the two prototypes below build on THAT
# baseline -- same geometry, same elbows, same cards -- and isolate only what
# they still propose changing on top of it.
#
# `_accent`: item 3 -- drop the green-for-every-winner fill (a Round 1 game
#   reads as loud as the Final) for one neutral fill plus a short accent bar
#   marking the side that advanced, and a gold champion card.
# `_full`  : `_accent` PLUS the two smaller ideas from the suggestion list --
#   alternating faint column bands so the eye tracks rounds, and byes drawn
#   as a lighter borderless pill rather than a full matchup card.

_BRK_H = 0.40            # card height, matching the live chart's CARD_H
_BRK_HH = _BRK_H / 2
_BRK_GAP = 0.46          # matchup card centre-to-centre, matching CARD_GAP


def _bracket_elbows(ax, d):
    """The live chart's connectors, factored out for the prototypes: both a
    horizontal-first right angle (turn near the source). A game WIN is a
    thick solid grey line; a BYE is a thin amber dotted one from the team's
    LAST idle card into the very next round only. Kept in sync with
    `plot_playoff_bracket`'s own connector block."""
    import pandas as pd
    played = d[d["result"].isin(["W", "L", "T"])]
    srcs = d[d["result"] == "W"][["team", "rx", "y", "result"]].copy()
    byes = d[d["result"] == "BYE"].sort_values("rx").drop_duplicates("team", keep="last")
    srcs = pd.concat([srcs, byes[["team", "rx", "y", "result"]]], ignore_index=True)
    feeds: dict = {}
    for _, a in srcs.iterrows():
        after = played[(played["team"] == a["team"]) & (played["rx"] > a["rx"])].sort_values("rx")
        if not len(after):
            continue
        n = after.iloc[0]
        if a["result"] == "BYE" and int(n["rx"]) != int(a["rx"]) + 1:
            continue
        feeds.setdefault((float(n["rx"]), float(n["y"])), []).append(
            (float(a["rx"]), float(a["y"]), a["result"] == "BYE"))
    BYE_LINE = "#e0a53a"
    for (nrx, ny), fs in feeds.items():
        x_in = nrx - 0.44
        for frx, fy, is_bye in fs:
            x_out = frx + 0.44
            x_turn = x_out + (x_in - x_out) * 0.4
            kw = (dict(color=BYE_LINE, lw=1.3, linestyle=(0, (1, 2))) if is_bye
                  else dict(color=T["rule"], lw=2.2))
            ax.plot([x_out, x_turn, x_turn, x_in], [fy, fy, ny, ny], zorder=1,
                    solid_capstyle="round", solid_joinstyle="round", **kw)


def _bracket_card_text(ax, r, seed_of, ref_scores, bold, star=False):
    """The live chart's two-line card text (badge+name upper-left, score
    lower-right), factored out so a prototype only overrides the fill.
    `star` appends a gold ★ after the name (the champion card)."""
    sd = seed_of.get(r["team"], "")
    badge = f"#{sd}  " if sd else ""
    name = _bracket_team_label(r["team"]) + ("  ★" if star else "")
    ax.text(r["rx"] - 0.40, r["y"] - _BRK_HH * 0.30, f"{badge}{name}",
            ha="left", va="center", fontsize=9, zorder=4,
            fontweight="bold" if bold else "normal", color="#242424")
    ax.text(r["rx"] + 0.40, r["y"] + _BRK_HH * 0.42, _bracket_node_pts(r, ref_scores),
            ha="right", va="center", fontsize=8.5, zorder=4,
            family="monospace", color="#3a3a3a")


def plot_playoff_bracket_accent(p, ref_scores: dict | None = None):
    """PROTOTYPE (item 3) -- neutral fill + accent bar, gold champion, on top
    of the now-live elbow + card baseline. Resolved matchups no longer fill
    green for every winner (which makes a Round 1 game as loud as the
    Final): every decided card sits on ONE neutral surface, and the side
    that advanced is marked by a short green accent bar down its left edge
    plus bold text. Byes keep the amber card. The tournament winner's card
    fills gold with a ★ and a "Champion" caption to its right -- the one
    place strong colour earns its keep.
    """
    from matplotlib.patches import FancyBboxPatch
    d, rounds, span, seed_of = _bracket_geom(p)
    NEUTRAL, BYE, GOLD, ACCENT = "#eef0f2", "#ffe0a3", "#f6d365", "#4caf50"
    champ = p.champion
    final_rx = len(rounds) - 1
    fig, ax = plt.subplots(figsize=(12.5, max(5.8, span * 1.22)))
    _bracket_elbows(ax, d)
    for _, r in d.iterrows():
        win = r["result"] == "W"
        is_champ = bool(champ) and r["team"] == champ and r["rx"] == final_rx
        fill = BYE if r["result"] == "BYE" else GOLD if is_champ else NEUTRAL
        ax.add_patch(FancyBboxPatch(
            (r["rx"] - 0.44, r["y"] - _BRK_HH), 0.88, _BRK_H,
            boxstyle="round,pad=0.006,rounding_size=0.05",
            facecolor=fill, edgecolor=T["edge"], lw=1.2, zorder=2))
        if win and not is_champ:
            ax.add_patch(FancyBboxPatch(
                (r["rx"] - 0.44, r["y"] - _BRK_HH), 0.055, _BRK_H,
                boxstyle="round,pad=0,rounding_size=0.0",
                facecolor=ACCENT, edgecolor="none", zorder=3))
        _bracket_card_text(ax, r, seed_of, ref_scores, bold=win or is_champ,
                           star=is_champ)
    if champ:
        crow = d[(d["team"] == champ) & (d["rx"] == final_rx)]
        if len(crow):
            ax.text(final_rx + 0.5, float(crow.iloc[0]["y"]), "Champion",
                    ha="left", va="center", fontsize=9, fontweight="bold",
                    color="#b8860b", zorder=4)
    note = ("Every score is computed from the submitted lineups under the "
            "league's own scoring chart.  PROTOTYPE: neutral card fill, a "
            "green accent bar marks the side that advanced, gold card = champion.")
    _bracket_axes(fig, ax, p, rounds, d, span, note)
    return fig


def plot_playoff_bracket_full(p, ref_scores: dict | None = None):
    """PROTOTYPE -- `_accent` plus the two smaller list items: alternating
    faint column bands behind the rounds so the eye tracks columns, and
    byes drawn as a lighter, narrower borderless pill rather than a full
    matchup card (a bye has no opponent, so it should not read as a game).
    """
    from matplotlib.patches import FancyBboxPatch
    d, rounds, span, seed_of = _bracket_geom(p)
    NEUTRAL, GOLD, ACCENT = "#eef0f2", "#f6d365", "#4caf50"
    champ = p.champion
    final_rx = len(rounds) - 1
    fig, ax = plt.subplots(figsize=(12.8, max(5.8, span * 1.22)))
    for i in range(len(rounds)):
        if i % 2 == 1:
            ax.axvspan(i - 0.5, i + 0.5, color=T["grid"], alpha=0.45, zorder=0)
    _bracket_elbows(ax, d)
    for _, r in d.iterrows():
        win = r["result"] == "W"
        is_champ = bool(champ) and r["team"] == champ and r["rx"] == final_rx
        if r["result"] == "BYE":
            name = _bracket_team_label(r["team"])
            sd = seed_of.get(r["team"], "")
            pts = _bracket_node_pts(r, ref_scores)  # already parenthesised
            ax.add_patch(FancyBboxPatch(
                (r["rx"] - 0.30, r["y"] - _BRK_HH * 0.62), 0.60, _BRK_H * 0.62,
                boxstyle="round,pad=0.004,rounding_size=0.06",
                facecolor="#fff2d9", edgecolor="none", zorder=2))
            ax.text(r["rx"], r["y"], f"{('#' + sd + '  ') if sd else ''}{name}"
                    f"  ·  bye  {pts}", ha="center", va="center", fontsize=8.5,
                    zorder=3, color="#7a5c1e")
            continue
        fill = GOLD if is_champ else NEUTRAL
        ax.add_patch(FancyBboxPatch(
            (r["rx"] - 0.44, r["y"] - _BRK_HH), 0.88, _BRK_H,
            boxstyle="round,pad=0.006,rounding_size=0.05",
            facecolor=fill, edgecolor=T["edge"], lw=1.2, zorder=2))
        if win and not is_champ:
            ax.add_patch(FancyBboxPatch(
                (r["rx"] - 0.44, r["y"] - _BRK_HH), 0.055, _BRK_H,
                boxstyle="round,pad=0,rounding_size=0.0",
                facecolor=ACCENT, edgecolor="none", zorder=3))
        _bracket_card_text(ax, r, seed_of, ref_scores, bold=win or is_champ,
                           star=is_champ)
    if champ:
        crow = d[(d["team"] == champ) & (d["rx"] == final_rx)]
        if len(crow):
            ax.text(final_rx + 0.5, float(crow.iloc[0]["y"]), "Champion",
                    ha="left", va="center", fontsize=9, fontweight="bold",
                    color="#b8860b", zorder=4)
    note = ("Every score is computed from the submitted lineups under the "
            "league's own scoring chart.  PROTOTYPE: `_accent` plus round "
            "column bands and byes drawn as a lighter pill.")
    _bracket_axes(fig, ax, p, rounds, d, span, note)
    return fig


def plot_clutch(seasons: dict, playoffs: dict, scope: str = "title",
                consolation: list | None = None):
    """Playoff PPG vs regular-season PPG -- who raises their game.

    `consolation` (a list of consolation_bracket() dicts) folds the consolation bracket games into
    the postseason PPG for the Postseason view -- see `playoffs.clutch`'s own
    `consolation=` argument. Only pooled when scope == "all".
    """
    from .playoffs import clutch as _clutch
    # Ordered by postseason scoring itself (the coloured dot), highest at the
    # top -- the "who actually put up points when it counted" read -- rather
    # than by the clutch delta.
    d = _clutch(seasons, playoffs, scope, consolation=consolation)
    if d.empty:
        return _no_data("No playoff games scored yet.")
    d = d.sort_values("po_ppg").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    cols = ["#2ca02c" if v > 0 else "#d62728" for v in d["clutch"]]
    for i, r in d.iterrows():
        ax.plot([r["reg_ppg"], r["po_ppg"]], [i, i], color=cols[i], lw=2.5,
                alpha=0.5, zorder=1)
    ax.scatter(d["reg_ppg"], range(len(d)), color="#a6a6a6", s=65, zorder=2)
    ax.scatter(d["po_ppg"], range(len(d)), color=cols, s=95, zorder=3)
    for i, r in d.iterrows():
        off, ha = (2, "left") if r["clutch"] > 0 else (-2, "right")
        ax.text(r["po_ppg"] + off, i, f"{r['clutch']:+.1f}", va="center", ha=ha,
                fontsize=8, fontweight="bold", color=cols[i])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    # No ax.legend() here -- redundant with the subtitle, which already states
    # the grey/coloured encoding (same fix as plot_mgr_sos/plot_draft_grades_value
    # for the identical redundant-legend pattern).
    # A negative-clutch label sits to the LEFT of po_ppg (ha="right"), which can
    # crowd the y-axis/tick labels with no xlim padding -- same collision shape
    # as plot_efficiency's low-side labels, same fix: pad by 15% of the span.
    lo = min(d["reg_ppg"].min(), d["po_ppg"].min())
    hi = max(d["reg_ppg"].max(), d["po_ppg"].max())
    pad = max((hi - lo) * 0.15, 1.5)
    ax.set_xlim(lo - pad, hi + pad)
    _, span = _po_span(playoffs)
    # With `consolation` merged in the coloured dot is the WHOLE postseason
    # (bracket + consolation bracket), so the subtitle says so.
    po_label = "postseason PPG" if consolation is not None else "playoff PPG"
    return _finish(fig, ax, "Clutch: Playoff vs Regular-Season Scoring",
                   f"Grey dot = regular-season PPG; coloured = {po_label}  ·  "
                   f"{span}", "Points per Game")


def plot_playoff_matchup(p, matchup_id):
    """Both submitted lineups facing each other, player by player."""
    d = p.players[p.players["matchup_id"] == matchup_id]
    if not len(d):
        raise ValueError(f"No scored players for matchup '{matchup_id}'")
    g = (d.groupby(["team", "player_id", "player_name", "position"],
                   as_index=False)["points"].sum())
    teams = list(dict.fromkeys(g["team"]))
    pal = palette(teams)
    tot = g.groupby("team")["points"].sum()
    g["signed"] = g.apply(lambda r: -r["points"] if r["team"] == teams[0] else r["points"], axis=1)
    g["lbl"] = g["player_name"] + " (" + g["position"].astype(str) + ")"
    g = g.sort_values("points")
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.barh(range(len(g)), g["signed"], height=0.72,
            color=[pal[t] for t in g["team"]])
    for i, (_, r) in enumerate(g.iterrows()):
        off = -1.5 if r["signed"] < 0 else 1.5
        ha = "right" if r["signed"] < 0 else "left"
        ax.text(r["signed"] + off, i, f"{r['points']:.1f}", va="center", ha=ha,
                fontsize=8, color=T["ink2"])
    ax.axvline(0, color=T["rule"], lw=1)
    ax.set_yticks(range(len(g)))
    ax.set_yticklabels(g["lbl"], fontsize=8.5)
    _portraits(ax, list(g["lbl"]), g["player_id"], g["position"], zoom=0.22)
    lim = float(g["points"].max()) * 1.35
    ax.set_xlim(-lim, lim)
    ax.set_xticklabels([f"{abs(t):.0f}" for t in ax.get_xticks()])
    hdr = "   vs   ".join(f"{t}: {tot[t]:.1f}" for t in teams)
    handles = [plt.Rectangle((0, 0), 1, 1, color=pal[t]) for t in teams]
    ax.legend(handles, teams, loc="lower right", frameon=False, fontsize=9)
    return _finish(fig, ax, f"Matchup {matchup_id}", hdr, "Points")


def plot_trade_performance(s: Season, top_n=12):
    d = metrics.trade_performance(s)
    keep = d.drop_duplicates("player_name").nlargest(top_n, "total")["player_name"]
    return _plot_acq(d[d["player_name"].isin(keep)], s,
                     "Traded Players: Value While Rostered",
                     "Points each team got from players it acquired in trades  ·  segment = one manager's stint")


def plot_waiver_performance(s: Season, top_n=15):
    d = metrics.waiver_performance(s)
    keep = d.drop_duplicates("player_name").nlargest(top_n, "total")["player_name"]
    return _plot_acq(d[d["player_name"].isin(keep)], s,
                     "Best Waiver & Free-Agent Pickups",
                     "Points managers got from players added off waivers / FA")


def plot_trade_single_contribution(s: Season, transaction_id: str):
    """Live in the Transactions tab, inline with that deal's own card: a
    stacked bar per side, segmented by what each RECEIVED player
    individually contributed (gross, not netted against what that side
    gave up) -- so a side that got several role players reads differently
    from one that got a single stud for the same total.
    """
    deal = next((d for d in metrics.trade_deals(s)
                if d["transaction_id"] == transaction_id), None)
    if deal is None:
        return _no_data("No data for this trade.")
    sides = sorted(deal["sides"], key=lambda sd: sd["got_pts"], reverse=True)
    fig, ax = plt.subplots(figsize=(6.5, max(1.8, 0.6 * len(sides) + 0.6)))
    y = list(range(len(sides)))
    max_total = max((sd["got_pts"] for sd in sides), default=0) or 1
    for yi, sd in zip(y, sides):
        left = 0.0
        for j, p in enumerate(sd.get("received_players") or []):
            color = _MANAGER_HUES[j % len(_MANAGER_HUES)]
            ax.barh([yi], [p["points"]], left=left, color=color,
                    edgecolor=T["edge"], linewidth=0.4, height=0.55)
            if p["points"] >= max_total * 0.08:
                ax.text(left + p["points"] / 2, yi, p["player_name"].split()[-1],
                        ha="center", va="center", fontsize=7, color="#1a1a1a")
            left += p["points"]
        # round()-then-format, not "+d" on the raw float directly -- a
        # genuinely tiny net (e.g. -0.2) must not format as the confusing "-0".
        net_r = round(sd["net"])
        net_lbl = f"{net_r:+d}" if net_r != 0 else "0"
        ax.text(left + max_total * 0.02, yi,
                f"{sd['got_pts']:.0f} pts  (net {net_lbl})",
                va="center", fontsize=8, fontweight="bold", color=T["ink2"])
    ax.set_yticks(y)
    ax.set_yticklabels([sd["user_name"] for sd in sides], fontsize=8.5)
    ax.set_xlim(0, max_total * 1.4)
    title = " ↔ ".join(sd["user_name"] for sd in sides)
    return _finish(fig, ax, title,
                   "Points received, by player  ·  net alongside each bar",
                   "Points", caption=_cap(s))


def plot_trade_single_cumulative(s: Season, transaction_id: str):
    """Live in the Transactions tab, inline with that deal's own card: a
    "race" view for one deal -- each SIDE's cumulative points from its
    received players, running since the trade, one line per side.
    Complements the deal card's own net-points summary (a single snapshot)
    by showing the TRAJECTORY behind that final number -- a side that
    jumped ahead in the first two weeks and coasted reads differently from
    one that only pulled ahead at the very end.

    Deliberately per-SIDE, not per-player -- summing each side's players
    keeps this a 2-4 line chart regardless
    of a blockbuster's player count, and "who's ahead" is fundamentally a
    question about the two (or three) sides of the deal, not any one
    player. Cumulative points are read straight off `pl_wk`, filtered to
    that side's received player ids on that side's own roster -- the same
    "points while rostered" convention every other trade metric uses, so a
    week a player sat on the OTHER team (pre-trade) never counts here.
    """
    deal = next((d for d in metrics.trade_deals(s)
                if d["transaction_id"] == transaction_id), None)
    if deal is None:
        return _no_data("No data for this trade.")
    name_to_rid = dict(zip(s.user_map["user_name"], s.user_map["roster_id"]))
    pl = s.pl_wk
    pal = palette(sd["user_name"] for sd in deal["sides"])
    fig, ax = plt.subplots(figsize=(7, 4))
    lines, x_start, x_end = [], None, None
    for sd in deal["sides"]:
        rid = name_to_rid.get(sd["user_name"])
        ids = [str(p["player_id"]) for p in (sd.get("received_players") or [])]
        if not ids:
            continue
        w = pl[(pl["roster_id"] == rid) & (pl["player_id"].astype(str).isin(ids))]
        wk = w.groupby("week")["points"].sum().sort_index()
        if wk.empty:
            continue
        cum = wk.cumsum()
        color = pal[sd["user_name"]]
        ax.plot(cum.index, cum.values, color=color, lw=2.2, marker="o",
               markersize=4, zorder=2)
        lines.append({"user_name": sd["user_name"], "color": color,
                      "y": float(cum.values[-1])})
        x_start = cum.index[0] if x_start is None else min(x_start, cum.index[0])
        x_end = cum.index[-1] if x_end is None else max(x_end, cum.index[-1])
    if not lines:
        plt.close(fig)
        return _no_data("No post-trade points data for this deal.")
    # Explicit integer, one-tick-per-week ticks -- matplotlib's default
    # locator subdivides a short 2-3 week span into fractional ticks
    # (12.00, 12.25, 12.50, ...), which reads as a real time axis with
    # sub-week granularity that doesn't exist in the underlying data.
    ax.set_xticks(range(int(x_start), int(x_end) + 1))
    # End-of-line labels, separated so two sides that finished close together
    # (e.g. 116 vs 113) don't render on top of each other -- a plain
    # va="center" text at each line's true y-value collided for at least one
    # real 2025 deal. Walking sorted-ascending and pushing each label up past
    # the previous one keeps the label near its real value except where two
    # are genuinely too close, matching the same "measure, then nudge only
    # what collides" approach used for the scatter-label solver elsewhere.
    lines.sort(key=lambda r: r["y"])
    span = max((r["y"] for r in lines), default=1) or 1
    min_gap = span * 0.09
    lines[0]["label_y"] = lines[0]["y"]
    for i in range(1, len(lines)):
        lines[i]["label_y"] = max(lines[i]["y"], lines[i - 1]["label_y"] + min_gap)
    for r in lines:
        ax.text(x_end + 0.15, r["label_y"], f"{r['user_name']}: {r['y']:.0f}",
                va="center", ha="left", fontsize=8.5, fontweight="bold", color=r["color"])
    title = " ↔ ".join(sd["user_name"] for sd in deal["sides"])
    return _finish(fig, ax, title,
                   "Cumulative points from each side's received players, since the trade",
                   "Week", "Cumulative Points", caption=_cap(s))


def plot_waiver_position_churn(s: Season):
    """Grouped bar: total waiver/FA moves vs. unique players involved, by
    position -- a position streamed week to week (many moves, few unique
    players -- K, DEF) reads differently from mostly one-and-done pickups
    (moves close to unique players -- RB, WR).
    """
    d = metrics.waiver_position_churn(s)
    if d.empty:
        return _no_data(f"No waiver/FA activity in {s.season}.")
    d = d.set_index("position").reindex(POSITIONS).fillna(0)
    x = list(range(len(POSITIONS)))
    w = 0.36
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar([i - w / 2 for i in x], d["moves"], width=w,
           color=[POS_COLORS[p] for p in POSITIONS], label="Total moves", zorder=2)
    ax.bar([i + w / 2 for i in x], d["unique_players"], width=w, alpha=0.4,
           color=[POS_COLORS[p] for p in POSITIONS], label="Unique players", zorder=2)
    for i, p in enumerate(POSITIONS):
        ax.text(i - w / 2, d.loc[p, "moves"] + 0.6, f"{int(d.loc[p, 'moves'])}",
                ha="center", fontsize=8, color=T["ink2"])
        ax.text(i + w / 2, d.loc[p, "unique_players"] + 0.6,
                f"{int(d.loc[p, 'unique_players'])}", ha="center", fontsize=8, color=T["muted"])
    ax.set_xticks(x)
    ax.set_xticklabels(POSITIONS)
    # Headroom + upper-left (not upper-right): whichever position gets
    # streamed hardest varies by league/season, and a tall bar under a
    # fixed upper-right legend collided with it (2025: DEF's "51" label
    # rendered right through the legend box).
    ax.set_ylim(0, max(d["moves"].max(), d["unique_players"].max()) * 1.22)
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    return _finish(fig, ax, f"{s.season}: Waiver-Wire Streaming by Position",
                   "Solid = total add moves, faded = unique players  ·  "
                   "a big gap means that spot got streamed, not just filled once",
                   "Position", "Count", caption=_cap(s), grid_axis="y")


def plot_waiver_activity(s: Season):
    """Line per manager: cumulative waiver/FA adds through each week
    (`metrics.waiver_activity_over_time`) -- who's constantly working the
    wire and WHEN, distinct from total value (`plot_waiver_value`) or which
    positions get streamed (`plot_waiver_position_churn`).
    """
    d = metrics.waiver_activity_over_time(s)
    if d.empty:
        return _no_data(f"No waiver/FA activity in {s.season}.")
    last_wk = int(d["week"].max())
    final = d[d["week"] == last_wk].set_index("user_name")["moves"]
    order = final.sort_values(ascending=False).index.tolist()
    pal = palette(order)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    weeks = sorted(d["week"].unique())
    for nm in order:
        g = d[d["user_name"] == nm].sort_values("week")
        ax.plot(g["week"], g["moves"], color=pal[nm], lw=2, alpha=0.85, zorder=2)
        ax.scatter(g["week"], g["moves"], color=pal[nm], s=24, zorder=3)
    ax.set_xticks(weeks)
    fig = _finish(fig, ax, f"{s.season}: Waiver-Wire Activity Over Time",
                  "Cumulative waiver/FA adds through each week, by manager",
                  "Week", "Cumulative Adds", caption=_cap(s), grid_axis="y")
    # A fixed offset (as plot_table_position uses) prints one label straight
    # through another whenever two managers end the season tied on adds --
    # real here (2025: two pairs tied), so this needs the same collision
    # solver the Weekly tab's scatter charts use, not a bespoke fix.
    _place_labels(fig, ax, [last_wk] * len(order), [final[nm] for nm in order],
                  [f"{nm} ({int(final[nm])})" for nm in order])
    return fig


def plot_loyalty(seasons: dict, top_n: int = 14, min_seasons: int = 2):
    """Manager-player bonds: who a manager keeps re-rostering, season after season.

    A career-scope chart (reads the whole season chain via `player_loyalty`).
    Best-effort: a league where no one has re-rostered the same player yet gets a
    plain "nothing to show" panel instead of an empty axis.
    """
    from matplotlib.ticker import MaxNLocator
    d = metrics.player_loyalty(seasons, min_seasons=min_seasons)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    if d.empty:
        ax.axis("off")
        ax.set_title("Manager · Player Loyalty", loc="left", fontsize=16,
                     fontweight="bold", color=T["ink"], pad=20)
        ax.text(0.5, 0.5, "No player has been re-rostered by the same manager in "
                f"{min_seasons}+ seasons yet.", ha="center", va="center",
                transform=ax.transAxes, fontsize=11.5, color=T["muted"])
        return fig
    d = d.head(top_n).iloc[::-1].reset_index(drop=True)
    ax.barh(range(len(d)), d["seasons_kept"], height=0.72, zorder=2,
            color=[POS_COLORS.get(str(p), T["neutral"]) for p in d["position"]])
    labels = [f"{pn}  ·  {un}" for pn, un in zip(d["player_name"], d["user_name"])]
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(labels, fontsize=8.5)
    _portraits(ax, labels, d["player_id"], d["position"])
    xmax = float(d["seasons_kept"].max())
    for i, r in d.iterrows():
        ax.text(r["seasons_kept"] + xmax * 0.02, i,
                f"{int(r['seasons_kept'])} seasons  ({r['season_list']})",
                va="center", fontsize=8, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.6)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    seen = [p for p in POSITIONS if p in set(d["position"])]
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in seen]
    ax.legend(handles, seen, loc="lower right", frameon=False, fontsize=8, ncol=3)
    return _finish(fig, ax, "Manager · Player Loyalty",
                   f"Players a manager kept re-rostering in {min_seasons}+ seasons"
                   "  ·  bar = seasons kept  ·  colour = position",
                   "Seasons Rostered")


# --- Schedule, rivalry & records charts -----------------------------------

def plot_boom_bust(s: Season):
    """Scoring average vs volatility -- steady teams vs boom-or-bust ones."""
    d = metrics.boom_bust(s)
    if d.empty:
        return _no_data(f"No scored weeks for {s.season} yet.")
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    mx, my = d["avg"].median(), d["sd"].median()
    ax.axvline(mx, ls="--", color=T["rule"], zorder=1)
    ax.axhline(my, ls="--", color=T["rule"], zorder=1)
    ax.scatter(d["avg"], d["sd"], s=95, c=[pal[n] for n in d["user_name"]],
               edgecolors=T["edge"], linewidths=1, zorder=3)
    avatars = _point_avatars(ax, d["avg"], d["sd"], d["user_name"], s, zoom=0.44)
    xr = (d["avg"].max() - d["avg"].min()) or 1
    yr = (d["sd"].max() - d["sd"].min()) or 1
    ax.set_xlim(d["avg"].min() - xr * 0.12, d["avg"].max() + xr * 0.12)
    ax.set_ylim(d["sd"].min() - yr * 0.18, d["sd"].max() + yr * 0.2)
    corners = [
        ax.text(x, y, txt, ha=ha, va=va, fontsize=8, style="italic",
                color=T["faint"], zorder=1)
        for x, y, ha, va, txt in [
            (ax.get_xlim()[1], ax.get_ylim()[1], "right", "top", "boom or bust"),
            (ax.get_xlim()[1], ax.get_ylim()[0], "right", "bottom", "elite & steady"),
            (ax.get_xlim()[0], ax.get_ylim()[0], "left", "bottom", "quietly steady"),
            (ax.get_xlim()[0], ax.get_ylim()[1], "left", "top", "low & volatile")]]
    fig = _finish(fig, ax, "Boom or Bust: Average vs Volatility",
                   "Right = scores more  ·  up = swingier week to week",
                   "Average points per week", "Std. dev of weekly points",
                   caption=_cap(s), grid_axis="both")
    # After _finish (tight_layout has settled the axes) so the collision
    # solver works with the geometry that will actually be drawn -- and
    # avoiding the avatar images themselves, not just the raw data points,
    # since a name used to print straight through its own team's avatar.
    _place_labels(fig, ax, list(d["avg"]), list(d["sd"]), list(d["user_name"]),
                  avoid=(*avatars, *corners))
    return fig


def plot_sos(s: Season):
    """Strength of schedule: how strong the opponents each team faced were."""
    d = metrics.strength_of_schedule(s).sort_values("sos").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    mean_sos = d["sos"].mean()
    cmap = matplotlib.colormaps["OrRd"]
    lo, hi = d["sos"].min(), d["sos"].max()
    norm = mcolors.Normalize(vmin=lo - (hi - lo) * 0.2, vmax=hi)
    ax.barh(range(len(d)), d["sos"], height=0.72, zorder=2,
            color=[cmap(norm(v)) for v in d["sos"]])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    ax.axvline(mean_sos, ls="--", color=T["rule"], zorder=3)
    ax.text(mean_sos, len(d) - 0.4, "league avg", ha="center", va="top",
            fontsize=8, color=T["muted"])
    for i, r in d.iterrows():
        ax.scatter([r["own_ppg"]], [i], marker="D", s=42, color=T["ink2"],
                   zorder=4, edgecolors=T["edge"], linewidths=0.8)
        ax.text(r["sos"] + (hi - lo) * 0.02, i, f"{r['sos']:.1f}", va="center",
                fontsize=8, color=T["ink2"])
    ax.set_xlim(lo - (hi - lo) * 0.35, hi + (hi - lo) * 0.18)
    return _finish(fig, ax, "Strength of Schedule",
                   "Bar = average PPG of opponents faced (higher = tougher)  ·  "
                   "◆ = the team's own PPG", "Avg opponent points per game",
                   caption=_cap(s))


def plot_schedule_swap(s: Season):
    """Each team's win total under every other team's schedule (diagonal = real)."""
    d = metrics.schedule_swap(s)
    order = (d[d["team"] == d["schedule_of"]]
             .sort_values("wins", ascending=False)["team"].tolist())
    piv = d.pivot(index="team", columns="schedule_of", values="wins").reindex(
        index=order, columns=order)
    fig, ax = plt.subplots(figsize=(9.5, 7.5))
    cmap = mcolors.LinearSegmentedColormap.from_list("sw", ["#c0563f", "#f0f0e6", "#2c7fb8"])
    im = ax.imshow(piv.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(order)))
    # 60 (not 40) so adjacent column names clear each other -- at 40 a run of
    # longer names (e.g. two 13+ character managers back to back) overlaps,
    # since the rotated label's horizontal footprint shrinks with a steeper angle.
    ax.set_xticklabels(order, rotation=60, ha="left")
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    for i in range(len(order)):
        for j in range(len(order)):
            v = piv.values[i, j]
            if v != v:
                continue
            ax.text(j, i, f"{int(v)}", ha="center", va="center", fontsize=8.5,
                    color="#1a1a1a", fontweight="bold" if i == j else "normal")
            if i == j:                                    # ring the real record
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False,
                                           edgecolor=T["ink"], lw=1.8, zorder=4))
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9)
    ax.set_ylabel("this team's scores", fontsize=10, color=T["muted"])
    ax.set_title("Schedule Swap: Wins Under Everyone's Schedule", loc="left",
                 fontsize=15.5, fontweight="bold", color=T["ink"], pad=40)
    ax.set_xlabel("…played against this team's schedule", fontsize=10, color=T["muted"])
    ax.xaxis.set_label_position("top")
    # Explanation goes at the bottom so it can't collide with the rotated column
    # labels along the top edge.
    fig.text(0.01, 0.01, "Row = a team's own weekly scores replayed against each "
             "column team's opponents  ·  boxed = real record", ha="left",
             fontsize=8.5, color=T["muted"])
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_head_to_head(seasons: dict):
    """All-time manager-vs-manager win% matrix, W-L annotated."""
    d = metrics.head_to_head(seasons)
    if d.empty:
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.axis("off")
        ax.text(0.5, 0.5, "No head-to-head games yet.", ha="center", va="center",
                transform=ax.transAxes, fontsize=12, color=T["muted"])
        return fig
    order = (d.groupby("user_name")["wins"].sum()
             .sort_values(ascending=False).index.tolist())
    win = d.pivot(index="user_name", columns="opp_name", values="win_pct").reindex(
        index=order, columns=order)
    rec = {(r["user_name"], r["opp_name"]): f"{r['wins']}-{r['losses']}"
           for _, r in d.iterrows()}
    fig, ax = plt.subplots(figsize=(9.5, 7.8))
    cmap = mcolors.LinearSegmentedColormap.from_list("h2h", ["#c0563f", "#f0f0e6", "#2c7fb8"])
    im = ax.imshow(win.values, aspect="auto", cmap=cmap, vmin=0, vmax=100)
    ax.set_xticks(range(len(order)))
    # 60 (not 40) so adjacent column names clear each other -- at 40 a run of
    # longer names (e.g. two 13+ character managers back to back) overlaps,
    # since the rotated label's horizontal footprint shrinks with a steeper angle.
    ax.set_xticklabels(order, rotation=60, ha="left")
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    for i, a in enumerate(order):
        for j, b in enumerate(order):
            if i == j:
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                           facecolor=T["grid"], zorder=2))
                continue
            lab = rec.get((a, b))
            if lab:
                ax.text(j, i, lab, ha="center", va="center", fontsize=8.5,
                        color="#1a1a1a", zorder=3)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9)
    ax.set_title("Head to Head (All Time)", loc="left", fontsize=16,
                 fontweight="bold", color=T["ink"], pad=40)
    # Explanation at the bottom, clear of the rotated column labels up top.
    fig.text(0.01, 0.01, "Each cell = the row manager's record vs the column "
             "manager  ·  blue = row wins the rivalry", ha="left",
             fontsize=8.5, color=T["muted"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_draft_value(s: Season):
    """Pick number vs roster points returned -- where the steals and busts landed."""
    from . import draft as _draft
    d = _draft.draft_board(s)
    fig, ax = plt.subplots(figsize=(10, 6))
    if d.empty:
        ax.axis("off")
        ax.set_title("Draft Value", loc="left", fontsize=16, fontweight="bold",
                     color=T["ink"], pad=20)
        ax.text(0.5, 0.5, "No draft data for this season.", ha="center",
                va="center", transform=ax.transAxes, fontsize=11.5, color=T["muted"])
        return fig
    ax.scatter(d["pick_no"], d["points"], s=55, zorder=3, edgecolors=T["edge"],
               linewidths=0.5, c=[POS_COLORS.get(str(p), T["neutral"]) for p in d["position"]])
    # A faint decay trend: rolling median of points by pick order.
    dd = d.sort_values("pick_no")
    trend = dd["points"].rolling(10, min_periods=3, center=True).median()
    ax.plot(dd["pick_no"], trend, color=T["rule"], lw=1.6, zorder=2, alpha=0.8)
    xr = d["pick_no"].max()
    for _, r in d.nlargest(3, "steal").iterrows():
        ax.annotate(f"{r['player_name']} (#{int(r['pick_no'])})",
                    (r["pick_no"], r["points"]), textcoords="offset points",
                    xytext=(6, 4), fontsize=7.5, color="#2ca02c", fontweight="bold")
    early = d[d["pick_no"] <= max(24, xr * 0.25)]
    for _, r in early.nsmallest(2, "points").iterrows():
        ax.annotate(f"{r['player_name']} (#{int(r['pick_no'])})",
                    (r["pick_no"], r["points"]), textcoords="offset points",
                    xytext=(6, -8), fontsize=7.5, color="#d62728", fontweight="bold")
    seen = [p for p in POSITIONS if p in set(d["position"].dropna())]
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in seen]
    ax.legend(handles, seen, loc="upper right", frameon=False, fontsize=8, ncol=3)
    return _finish(fig, ax, f"{s.season} Draft Value",
                   "Each dot = a pick  ·  green tags = biggest steals  ·  "
                   "red = early busts  ·  line = value decay by pick",
                   "Overall pick number", "Roster points returned", caption=_cap(s))


def plot_draft_grades_value(s: Season):
    """Draft grades as a dumbbell: roster points kept vs. the SAME picks'
    true full season output, one connecting line per manager (same idiom as
    `plot_mgr_sos`). A long red line is value that got away -- traded or
    dropped before the team ever benefited from it; a short grey line means
    they drafted, and kept, close to what they got.

    Ordered by `points` (roster points actually kept), not `total` (true
    value) -- the bar that used to anchor the old bar-chart grade is the
    honest "what did this manager actually bank" number, so reading top to
    bottom traces perceived loss: rows near the top banked close to what
    their picks were worth, rows sliding down the page gave more of it away.
    """
    from . import draft as _draft
    d = _draft.draft_grades(s)
    fig, ax = plt.subplots(figsize=(9, 6))
    if d.empty:
        ax.axis("off")
        ax.set_title("Draft Grades vs. True Value", loc="left", fontsize=16,
                     fontweight="bold", color=T["ink"], pad=20)
        ax.text(0.5, 0.5, "No draft data for this season.", ha="center",
                va="center", transform=ax.transAxes, fontsize=11.5, color=T["muted"])
        return fig
    d = d.sort_values("points").reset_index(drop=True)
    d["gap"] = (d["total"] - d["points"]).round(1)
    hi = float(d["total"].max())
    # A line colours red once the gap clears the league's own median -- so
    # "notable" scales with how leaky drafts are THIS season, not a fixed
    # point cutoff that reads differently in a high- vs low-scoring year.
    med_gap = d["gap"].median()
    line_cols = ["#e03131" if g > med_gap else T["rule"] for g in d["gap"]]
    for i, r in d.iterrows():
        ax.plot([r["points"], r["total"]], [i, i], color=line_cols[i],
                lw=2.4, alpha=0.8, zorder=2)
    ax.scatter(d["points"], range(len(d)), color=T["neutral"], s=60, zorder=3,
               edgecolors=T["edge"], linewidths=0.6, label="roster points kept")
    ax.scatter(d["total"], range(len(d)), color="#2ca02c", s=75, zorder=4,
               edgecolors=T["edge"], linewidths=0.6, label="players' true season value")
    for i, r in d.iterrows():
        note = f"+{r['gap']:.0f} lost" if r["gap"] > hi * 0.02 else "kept"
        ax.text(r["total"] + hi * 0.015, i, note, va="center", fontsize=7.5, color=T["muted"])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    # No ax.legend() here -- a fixed lower-right legend used to sit directly on
    # top of whichever manager's own row/label landed there (rows are sorted
    # by `points` ascending, so the bottom row is always adjacent to it, and
    # that row's own "+X lost" label often extends into the same corner).
    # Same fix as `plot_mgr_sos`'s identical collision: the subtitle already
    # states the grey/green/red encoding, so the legend was redundant as well
    # as the thing colliding -- dropping it fixes both.
    ax.set_xlim(0, hi * 1.25)
    return _finish(fig, ax, f"{s.season} Draft Grades vs. True Value",
                   "Grey = points kept  ·  green = players' true value  ·  "
                   "red line = value given away",
                   "Points", caption=_cap(s))


def plot_redraft_standings(s: Season, basis: str = "value"):
    """Dumbbell: each manager's REAL win total against what they'd have won
    with a redraft (`draft.redraft_standings`) -- the expected outcome of
    altering the draft, replaying the same schedule with both sides'
    redrafted, optimally-started rosters (same idiom as
    `plot_mgr_sos`/`plot_draft_grades_value`). Sorted by simulated finish so
    the chart reads top-to-bottom the same way the simulation table does.

    `basis` -- `"value"` (true season value, the default) or `"adp"`
    (Sleeper's own ADP) -- picks which of `draft.redraft_standings()`'s two
    bases this draws, and is reflected in the chart's own title so a viewer
    can't mistake one basis' chart for the other's.
    """
    from matplotlib.ticker import MaxNLocator

    from . import draft as _draft
    d = _draft.redraft_standings(s, basis)
    if d.empty:
        return _no_data(f"No draft data to simulate against in {s.season}.")
    d = d.sort_values("sim_position", ascending=False).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, max(4, len(d) * 0.55)))
    line_cols = ["#2ca02c" if wd > 0 else "#d62728" if wd < 0 else T["rule"]
                for wd in d["win_delta"]]
    for i, r in d.iterrows():
        ax.plot([r["real_wins"], r["wins"]], [i, i], color=line_cols[i],
                lw=2.4, alpha=0.75, zorder=2)
    # No ax.legend() -- the subtitle already spells out grey/green, and
    # (unlike plot_draft_grades_value, sorted by points ascending so its
    # bottom-right corner stays clear) this chart is sorted by SIMULATED
    # position, so the worst-simulated team can still have a high REAL win
    # total and land right where a fixed-corner legend would sit -- shipped
    # for 2025, where SimonSmith's real 10 wins collided with a lower-right
    # legend.
    ax.scatter(d["real_wins"], range(len(d)), color=T["neutral"], s=60, zorder=3,
               edgecolors=T["edge"], linewidths=0.6)
    ax.scatter(d["wins"], range(len(d)), color="#2ca02c", s=75, zorder=4,
               edgecolors=T["edge"], linewidths=0.6)
    hi = float(max(d["real_wins"].max(), d["wins"].max()))
    for i, r in d.iterrows():
        note = f"{r['win_delta']:+.0f}" if r["win_delta"] != 0 else "even"
        ax.text(max(r["real_wins"], r["wins"]) + hi * 0.02, i, note,
                va="center", fontsize=7.5, fontweight="bold",
                color=line_cols[i] if r["win_delta"] != 0 else T["muted"])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"], fontsize=8.5)
    _row_avatars(ax, d["user_name"], s)
    ax.set_xlim(0, hi * 1.2)
    ax.xaxis.set_major_locator(MaxNLocator(integer=True))
    basis_label = "ADP" if basis == "adp" else "True Value"
    return _finish(fig, ax, f"{s.season}: Redraft Simulation, Wins Real vs. {basis_label}",
                   "Grey = real wins, green = simulated  ·  green line = gained wins, red = lost",
                   "Wins", caption=_cap(s))


def plot_redraft_finish_slope(s: Season, basis: str = "value"):
    """Live in the redraft simulation section, beside `plot_redraft_standings`
    -- the standings RESHUFFLE itself, which the wins dumbbell doesn't show
    (only the table's own Delta Finish column did before this). A two-point
    slope per manager, real finish on the left against simulated finish on
    the right, y inverted so 1st sits at the top like a real standings
    board.

    `basis` -- see `plot_redraft_standings`'s docstring; same two options,
    same reflection in the chart's own title.

    Same figsize (width AND the height formula) as `plot_redraft_standings`
    deliberately -- the two sit side by side in a shared grid, whose columns
    are scaled to equal WIDTH, not equal aspect ratio; a narrower figsize
    here rendered visibly taller once scaled to match that column width
    (same height in native pixels, but a much more square aspect than the
    wide dumbbell), throwing the row's bottom edge off. Matching both
    dimensions keeps the two frames scaling identically.
    """
    from . import draft as _draft
    d = _draft.redraft_standings(s, basis)
    if d.empty:
        return _no_data(f"No draft data to simulate against in {s.season}.")
    d = d.sort_values("real_position").reset_index(drop=True)
    n = len(d)
    fig, ax = plt.subplots(figsize=(9, max(4, n * 0.55)))
    pal = palette(d["user_name"])
    for _, r in d.iterrows():
        moved = r["real_position"] - r["sim_position"]
        color = "#2ca02c" if moved > 0 else "#d62728" if moved < 0 else T["rule"]
        ax.plot([0, 1], [r["real_position"], r["sim_position"]], color=color,
                lw=2.2, alpha=0.8, zorder=2, marker="o", markersize=6,
                markerfacecolor=pal[r["user_name"]], markeredgecolor=T["edge"])
        ax.text(-0.04, r["real_position"], r["user_name"], ha="right", va="center",
                fontsize=8.5, color=T["ink"])
        ax.text(1.04, r["sim_position"], f"#{int(r['sim_position'])}", ha="left",
                va="center", fontsize=8.5, fontweight="bold", color=color)
    ax.set_xlim(-0.55, 1.3)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Real finish", "Simulated finish"], fontsize=9.5)
    ax.set_ylim(n + 0.6, 0.4)
    ax.set_yticks(range(1, n + 1))
    ax.tick_params(left=False, labelleft=False)
    basis_label = " (by ADP)" if basis == "adp" else ""
    return _finish(fig, ax, f"{s.season}: Redraft Simulation, Standings Reshuffle{basis_label}",
                   "Green = redraft finishes higher, red = lower  ·  1st place at top",
                   caption=_cap(s), grid_axis="y")


# --- manager-scoped charts -------------------------------------------------
# These take (season, manager) rather than just a season, so they are registered
# under the "season+manager" kind in report._CHART_FNS and the web app passes
# `manager` through to /chart. Everything below reads frames the season object
# already carries -- no new fetches, no metric changes.

def _no_data(msg: str):
    """A titled blank panel, so a missing scope degrades instead of erroring."""
    fig, ax = plt.subplots(figsize=(9, 3))
    ax.axis("off")
    ax.text(0.5, 0.5, msg, ha="center", va="center", fontsize=11.5,
            color=T["muted"], transform=ax.transAxes)
    return fig


def _mgr_rid(s: Season, manager: str):
    """roster_id for a manager name, or None if this season has no such team."""
    um = getattr(s, "user_map", None)
    if um is None or "user_name" not in getattr(um, "columns", []):
        return None
    m = um.loc[um["user_name"] == manager, "roster_id"]
    return None if m.empty else m.iloc[0]


def _mgr_weeks(s: Season, manager: str, through_week: int | None = None):
    """(their team_wk rows sorted by week, roster_id) or (None, None).

    `through_week` caps the rows at that week -- used when these season-wide
    charts are reused in a WEEKLY context (the weekly report), so viewing
    week 5 doesn't leak weeks 6-14 into a chart titled "week 5".
    """
    rid = _mgr_rid(s, manager)
    tw = s.team_wk
    if rid is None or not {"roster_id", "week", "points"}.issubset(
            getattr(tw, "columns", [])):
        return None, None
    mine = tw[tw["roster_id"] == rid]
    if through_week is not None:
        mine = mine[mine["week"] <= through_week]
    mine = mine.sort_values("week")
    return (None, None) if mine.empty else (mine, rid)


def plot_mgr_score_band(s: Season, manager: str, through_week: int | None = None):
    """Their weekly score against the band every other team scored that week.

    The band answers the question a bare points line can't: was a 95-point week
    bad, or was it just a low-scoring week league-wide? `through_week` caps the
    season at that week (see `_mgr_weeks`), for the weekly report's reuse of
    this otherwise season-wide chart.
    """
    mine, _ = _mgr_weeks(s, manager, through_week)
    if mine is None:
        return _no_data(f"No weekly scores for {manager} in {s.season}.")
    tw = s.team_wk
    if through_week is not None:
        tw = tw[tw["week"] <= through_week]
    band = (tw.groupby("week")["points"]
            .agg(lo="min", hi="max", mid="median").reset_index())
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.fill_between(band["week"], band["lo"], band["hi"], color=T["neutral"],
                    alpha=0.35, zorder=1, label="league range")
    ax.plot(band["week"], band["mid"], ls="--", lw=1.6, color=T["rule"],
            zorder=2, label="league median")
    ax.plot(mine["week"], mine["points"], lw=2, color=T["ink2"], zorder=3)
    res = list(mine["result"]) if "result" in mine.columns else [None] * len(mine)
    cols = ["#2ca02c" if r == "W" else "#d62728" if r == "L" else T["neutral"]
            for r in res]
    ax.scatter(mine["week"], mine["points"], s=90, c=cols, zorder=4,
               edgecolors=T["edge"], linewidths=1.2)
    ax.set_xticks(list(mine["week"]))
    ax.legend(loc="best", frameon=False, fontsize=8)
    return _finish(fig, ax, f"{manager} · Weekly Score vs the League",
                   "Band = every team's range that week  ·  green win, red loss",
                   "Week", "Points", caption=_cap(s), grid_axis="y")


def _eff_axis_floor(eff) -> int:
    """The ONE shared rule for a Started-vs-Optimal efficiency axis floor:
    the lowest real efficiency value in `eff`, rounded down to the nearest
    10 -- never a fixed constant (an earlier version defaulted to 50 unless
    data went lower, which on a season whose real low was e.g. 77% stranded
    the line in the top ~40% of its own axis with a large dead zone below it
    -- see git history), and never derived from an average either (a
    mean-based floor was tried and rejected for the same "not the actual
    rule" reason: the rule is the given series' own minimum, full stop).

    `eff` need not be the caller's own scope: `plot_season_optimal` (the
    league-wide average chart) passes its own per-week average series, so
    its floor is independent of every other chart. `plot_mgr_optimal` (the
    per-manager chart), as of 2026-08, deliberately passes the WHOLE
    league's efficiency series (every manager, every week, not just the one
    being drawn) so every per-manager chart shares one floor and stays
    comparable side by side -- see that function's own comment for why.
    Either way, this function itself stays a pure "min of what I was
    handed, floored to 10" -- don't reintroduce a hardcoded floor or a
    duplicate formula in either caller; change the rule (or which series
    gets passed in) at the call site, not here.
    """
    return max(int(float(eff.min()) // 10 * 10), 0)


def _highlight_eff_extremes(ax2, w, eff) -> None:
    """Mark the best and worst efficiency weeks on a Started-vs-Optimal
    trend line (shared by `plot_mgr_optimal`/`plot_season_optimal`, called
    right after each draws its own `ax2.plot(...)` line).

    Lowest week: a larger dot at its real value, labelled with that value --
    the week most worth asking "what happened here."  Highest week: a
    larger dot labelled with its value UNLESS it's a real 100% (efficiency
    is capped there, so a 100% week means "no lineup could have beaten
    this," not merely "the best of these weeks") -- a 100% week instead
    draws a star marker with no value label, since the axis top plus the
    "100%" tick already say the number and a star reads as "perfect" at a
    glance rather than requiring the reader to check a label. If the best
    week and worst week are the same single week (e.g. only one week of
    data), the low styling wins -- drawing a star over a real value would
    misrepresent a lone below-100% week as flawless.

    Colors are deliberately NOT the chart's existing green/red (the started
    bars and the bar-gap "-X" labels): gold for the high marker/star and
    blue for the low marker read as their own distinct layer instead of
    blending into the bars sitting directly underneath this twin axis --
    the original version used the same `#2ca02c` as the started bars for
    the high dot, which visually merged into the bar it was sitting on top
    of at a glance. A thick white ring around each marker (2026-08) gives it
    a hard edge against whichever bar color it happens to land on, and each
    value label sits in a solid `T["bg"]`-colored pill (same convention
    `_place_labels` uses for its own text-over-data labels) rather than bare
    colored text -- plain text in these colors was still hard to read
    against the green bar fill and the grey gridlines behind it.

    `w`/`eff` are the same week/efficiency series just handed to `ax2.plot`.
    Skips silently for fewer than 2 points -- there's no "best vs worst" to
    contrast with only one number.
    """
    if len(eff) < 2:
        return
    w = list(w)
    eff = list(eff)
    hi_i = max(range(len(eff)), key=lambda i: eff[i])
    lo_i = min(range(len(eff)), key=lambda i: eff[i])
    if hi_i == lo_i:
        return
    label_bbox = dict(facecolor=T["bg"], edgecolor="none", alpha=0.85,
                       boxstyle="round,pad=0.22")
    lo_val = eff[lo_i]
    ax2.plot(w[lo_i], lo_val, marker="o", markersize=10, markerfacecolor="#1f77b4",
              markeredgecolor="white", markeredgewidth=2, zorder=6, linestyle="none")
    ax2.annotate(f"{lo_val:.0f}%", (w[lo_i], lo_val), textcoords="offset points",
                 xytext=(0, -14), ha="center", va="top", fontsize=8.5,
                 fontweight="bold", color="#1f77b4", zorder=7, bbox=label_bbox)
    hi_val = eff[hi_i]
    if hi_val >= 100:
        ax2.plot(w[hi_i], hi_val, marker="*", markersize=18, markerfacecolor="#f1c40f",
                  markeredgecolor="white", markeredgewidth=1.6, zorder=6, linestyle="none")
    else:
        ax2.plot(w[hi_i], hi_val, marker="o", markersize=10, markerfacecolor="#f1c40f",
                  markeredgecolor="white", markeredgewidth=2, zorder=6, linestyle="none")
        ax2.annotate(f"{hi_val:.0f}%", (w[hi_i], hi_val), textcoords="offset points",
                     xytext=(0, 12), ha="center", va="bottom", fontsize=8.5,
                     fontweight="bold", color="#b8860b", zorder=7, bbox=label_bbox)


def plot_mgr_optimal(s: Season, manager: str, through_week: int | None = None):
    """Started vs optimal each week, with a weekly efficiency trend line.

    One panel, not the season-cumulative-cost panel this used to carry
    underneath: the bars already answer "how much got left on the bench and
    when," so the trend line (started / optimal, per week) adds "was that
    getting better or worse" without a second, differently-scaled axis for a
    running total. Efficiency rides `ax.twinx()`, zoomed to that WEEK-TO-WEEK
    range (not a fixed 0-100%) so the line's own shape -- which weeks trended
    up or down -- actually reads, rather than flattening into a near-straight
    band the way a full 0-100 axis would for a manager whose real efficiency
    lives in a tight 70-95% window. White-filled markers on a solid line at a
    high zorder keep it legible where it crosses in front of the bars (an
    earlier low-alpha/behind-the-bars treatment, borrowed from the count
    lines on the rejected position-pickups prototypes, was tried first and
    made the line's own shape unreadable -- this chart's whole point is
    "trending up or down," which a flattened, backgrounded line defeats).
    `through_week` caps the season at that week, for the weekly report's
    reuse of this otherwise season-wide chart.
    """
    lu = getattr(s, "lineup", None)
    if lu is None or not {"user_name", "week", "actual", "optimal"}.issubset(
            getattr(lu, "columns", [])):
        return _no_data(f"No lineup data for {manager} in {s.season}.")
    lu_scope = lu[lu["week"] <= through_week] if through_week is not None else lu
    d = lu_scope[lu_scope["user_name"] == manager]
    d = d.sort_values("week")
    if d.empty:
        return _no_data(f"No lineup data for {manager} in {s.season}.")
    lost = (d["optimal"] - d["actual"]).clip(lower=0)
    eff = (d["actual"] / d["optimal"].clip(lower=1e-9) * 100).clip(upper=100)
    # Floor is shared across EVERY per-manager chart (2026-08), not each
    # manager's own low: the lowest efficiency week ANY manager had (through
    # `through_week` when capped, so the floor matches what's actually
    # plottable at that cutoff) becomes the floor for ALL of them, so a
    # reader can compare two managers' charts side by side without the axis
    # itself changing scale underneath them. `plot_season_optimal` (the
    # league-wide average chart) is NOT part of this -- it stays scoped to
    # its own series via `_eff_axis_floor(eff)` directly, unchanged.
    league_eff = (lu_scope["actual"] / lu_scope["optimal"].clip(lower=1e-9) * 100).clip(upper=100)
    floor = _eff_axis_floor(league_eff) if len(league_eff) else _eff_axis_floor(eff)
    fig, ax = plt.subplots(figsize=(9.5, 6))
    w = d["week"]
    ax.bar(w, d["optimal"], width=0.68, color=T["neutral"], alpha=0.55,
           zorder=2, label="optimal")
    ax.bar(w, d["actual"], width=0.68, color="#2ca02c", zorder=3, label="started")
    # Only annotate weeks that actually cost something, so the labels stay scannable.
    top = float(d["optimal"].max())
    for wk, opt, gap in zip(w, d["optimal"], lost):
        if gap >= top * 0.04:
            ax.text(wk, opt + top * 0.015, f"-{gap:.0f}", ha="center",
                    fontsize=7.5, color="#d62728", fontweight="bold")
    ax.set_ylim(0, top * 1.12)
    ax.set_xticks(list(w))
    ax.set_xlabel("Week", fontsize=10, color=T["muted"])
    # No legend for the bars: they run full height, so any in-axes placement
    # sits on the data, and the subtitle already names both series.
    ax2 = ax.twinx()
    ax2.plot(w, eff, color="#6a51a3", lw=2, alpha=0.85, zorder=4,
             marker="o", markersize=4.5, markerfacecolor=T["bg"],
             markeredgecolor="#6a51a3", markeredgewidth=1.3)
    _highlight_eff_extremes(ax2, w, eff)
    # Fixed, evenly-ticked axis (2026-08, replacing an earlier zoomed-to-
    # real-range version -- see git history/CLAUDE.md for that prior
    # design's own reasoning). Efficiency is DEFINED on a 0-100 scale, so
    # this axis reads literally rather than relative to this one manager's
    # own season. Floor is the shared `floor` computed above -- the lowest
    # efficiency week ANY manager had (not just this one), rounded down to
    # the nearest 10 via `_eff_axis_floor`, so every per-manager chart uses
    # the SAME floor and is safe to compare side by side. See the comment
    # above `floor`'s computation for why this diverges from
    # `_eff_axis_floor`'s own docstring (written when both charts were
    # still purely self-scoped) -- `plot_season_optimal` is unaffected and
    # still passes its own series straight through.
    # MultipleLocator(10) from that floor forces clean ticks (e.g.
    # 50/60/70/80/90/100) rather than matplotlib's auto-placed ones (which
    # on the old zoomed range could land on odd values like 65/75/85). A
    # small top pad (102, not 100) keeps a real 100%-efficiency week's
    # marker/line from sitting flush on the axis edge, where it could
    # visually clip or collide with the plot border -- purely a rendering
    # buffer, the tick labels themselves still stop at 100 since
    # MultipleLocator(10) never places one at 102.
    from matplotlib.ticker import MultipleLocator
    ax2.set_ylim(floor, 102)
    ax2.yaxis.set_major_locator(MultipleLocator(10))
    ax2.set_ylabel("Efficiency %", fontsize=9, color="#6a51a3")
    ax2.tick_params(axis="y", colors="#6a51a3", labelsize=8.5)
    for sp in ("top", "left"):
        ax2.spines[sp].set_visible(False)
    ax2.spines["right"].set_color("#6a51a3")
    total = float(lost.sum())
    span_txt = f"through week {through_week}" if through_week is not None else "all season"
    return _finish(fig, ax, f"{manager} · Started vs Optimal",
                   "Grey = the best legal lineup that week; green = what they started  ·  "
                   f"purple line = efficiency %  ·  {total:.0f} pts left on the bench {span_txt}",
                   None, "Points", caption=_cap(s), grid_axis="y")


def plot_season_optimal(s: Season):
    """The LEAGUE-WIDE seasonal counterpart to `plot_mgr_optimal` -- same
    bar+twin-axis-line shape (grey optimal / green started bars, purple
    efficiency line), but each week's bars are the AVERAGE across every
    manager that week, not one manager's own total. Answers "how did the
    whole league's lineup-setting trend over the season" in one picture,
    rather than needing to flip between ten separate per-manager charts to
    notice a league-wide pattern (e.g. bye weeks/injury-heavy stretches
    dragging everyone's efficiency down at once). Efficiency axis floor
    comes from `_eff_axis_floor()`, the SAME shared helper `plot_mgr_optimal`
    calls -- not a separate formula here -- so both charts follow one rule
    (this scope's own real low, rounded down to the nearest 10) rather than
    two independently-tuned ones that could drift apart.

    Promoted out of the Testing tab (2026-08) onto the league-scope Roster
    tab itself, in the "Roster" section's chart slot `roster_counts` used
    to occupy -- see app.py's `_roster_part_ctx` for the full reshuffle
    ("Where the Points Come From" removed from this tab, `roster_counts`
    moved up to replace it, this chart filling `roster_counts`' old spot).
    """
    lu = getattr(s, "lineup", None)
    if lu is None or not {"user_name", "week", "actual", "optimal"}.issubset(
            getattr(lu, "columns", [])):
        return _no_data(f"No lineup data for {s.season}.")
    d = lu.groupby("week", as_index=False).agg(actual=("actual", "mean"), optimal=("optimal", "mean"))
    d = d.sort_values("week")
    if d.empty:
        return _no_data(f"No lineup data for {s.season}.")
    lost = (d["optimal"] - d["actual"]).clip(lower=0)
    eff = (d["actual"] / d["optimal"].clip(lower=1e-9) * 100).clip(upper=100)
    fig, ax = plt.subplots(figsize=(9.5, 6))
    w = d["week"]
    ax.bar(w, d["optimal"], width=0.68, color=T["neutral"], alpha=0.55,
           zorder=2, label="optimal")
    ax.bar(w, d["actual"], width=0.68, color="#2ca02c", zorder=3, label="started")
    top = float(d["optimal"].max())
    for wk, opt, gap in zip(w, d["optimal"], lost):
        if gap >= top * 0.04:
            ax.text(wk, opt + top * 0.015, f"-{gap:.0f}", ha="center",
                    fontsize=7.5, color="#d62728", fontweight="bold")
    ax.set_ylim(0, top * 1.12)
    ax.set_xticks(list(w))
    ax.set_xlabel("Week", fontsize=10, color=T["muted"])
    ax2 = ax.twinx()
    ax2.plot(w, eff, color="#6a51a3", lw=2, alpha=0.85, zorder=4,
             marker="o", markersize=4.5, markerfacecolor=T["bg"],
             markeredgecolor="#6a51a3", markeredgewidth=1.3)
    _highlight_eff_extremes(ax2, w, eff)
    # Floor is `_eff_axis_floor(eff)` -- the SAME shared rule
    # `plot_mgr_optimal` uses (see that function's own comment and
    # `_eff_axis_floor`'s docstring): this chart's own scope is the
    # league's per-week AVERAGE efficiency, so `eff` here is that series,
    # and the floor becomes the lowest such weekly league average, rounded
    # down to the nearest 10 (e.g. a lowest week of 65% -> floor 60). Two
    # earlier versions of this floor (a fixed 50, then a season-mean-based
    # formula) both got replaced once the actual rule was pinned down to
    # "the scope's own real low, nothing else" -- see _eff_axis_floor,
    # the single place that rule now lives for both charts.
    from matplotlib.ticker import MultipleLocator
    ax2.set_ylim(_eff_axis_floor(eff), 102)
    ax2.yaxis.set_major_locator(MultipleLocator(10))
    ax2.set_ylabel("Efficiency %", fontsize=9, color="#6a51a3")
    ax2.tick_params(axis="y", colors="#6a51a3", labelsize=8.5)
    for sp in ("top", "left"):
        ax2.spines[sp].set_visible(False)
    ax2.spines["right"].set_color("#6a51a3")
    total = float(lost.sum())
    return _finish(fig, ax, f"{s.season}: Started vs Optimal, League Average",
                   "Grey = the league's average best legal lineup that week; green = what "
                   "the league averaged starting  ·  purple line = average efficiency %  ·  "
                   f"{total:.0f} avg pts left on the bench all season",
                   None, "Points", caption=_cap(s), grid_axis="y")


def plot_mgr_margins(s: Season, manager: str, through_week: int | None = None):
    """Every week's margin as a diverging bar -- blowouts vs coin flips.

    A game log shows the same numbers, but only the shape tells you whether a
    losing season was four routs or four heartbreakers. `through_week` caps the
    season at that week, for the weekly report's reuse of this otherwise
    season-wide chart.
    """
    mine, _ = _mgr_weeks(s, manager, through_week)
    if mine is None or "pa" not in mine.columns:
        return _no_data(f"No margins for {manager} in {s.season}.")
    d = mine[mine["pa"].notna()].copy()
    if d.empty:
        return _no_data(f"No completed games for {manager} in {s.season}.")
    d["margin"] = d["points"] - d["pa"]
    cols = ["#2ca02c" if m > 0 else "#d62728" for m in d["margin"]]
    fig, ax = plt.subplots(figsize=(9.5, 5.5))
    ax.bar(d["week"], d["margin"], width=0.66, color=cols, zorder=2)
    ax.axhline(0, color=T["spine"], lw=1.2, zorder=3)
    span = float(d["margin"].abs().max()) or 1.0
    for wk, m in zip(d["week"], d["margin"]):
        va = "bottom" if m > 0 else "top"
        off = span * 0.03 * (1 if m > 0 else -1)
        ax.text(wk, m + off, f"{m:+.0f}", ha="center", va=va, fontsize=7.5,
                color=T["ink2"])
    # Fit the data rather than forcing symmetry: an all-wins season would spend
    # half the canvas on empty negative space. Zero stays in range, and the
    # drawn baseline keeps the sign unambiguous.
    lo, hi = float(d["margin"].min()), float(d["margin"].max())
    pad = span * 0.18
    ax.set_ylim(min(lo - pad, -pad), max(hi + pad, pad))
    ax.set_xticks(list(d["week"]))
    close = int((d["margin"].abs() <= 10).sum())
    rout = int((d["margin"].abs() >= 40).sum())
    return _finish(fig, ax, f"{manager} · Margin by Week",
                   f"Points scored minus points allowed  ·  {close} game(s) "
                   f"inside 10, {rout} decided by 40+",
                   "Week", "Margin", caption=_cap(s), grid_axis="y")


def plot_mgr_sos(s: Season, manager: str, through_week: int | None = None):
    """Strength of schedule as a dumbbell -- opponents' average PPG faced vs
    this team's own PPG -- with ONE manager's row picked out.

    The league-wide version (`plot_sos`) answers "who has it hardest"; this
    answers "is MY record inflated or deflated by who I've played" for the
    weekly report's manager view. A bare bar of `sos` alone wastes most of its
    own axis (schedule strength never approaches zero) and shows only half the
    question -- putting both numbers on one points scale, dumbbell-style
    (same idiom as `plot_clutch`), makes the GAP between them, not a bar's
    length, the thing you read. `through_week` caps it at that week, same as
    the other mgr_* charts, so a week-5 report doesn't leak weeks 6-14 of
    schedule into "strength of schedule so far".
    """
    d = metrics.strength_of_schedule(s, through_week).sort_values("sos").reset_index(drop=True)
    if not len(d):
        return _no_data(f"No schedule data for {manager} in {s.season}.")
    fig, ax = plt.subplots(figsize=(9, 6))
    cols = ["#2ca02c" if r["own_ppg"] >= r["sos"] else "#d62728" for _, r in d.iterrows()]
    for i, r in d.iterrows():
        hero = r["user_name"] == manager
        ax.plot([r["sos"], r["own_ppg"]], [i, i], color=cols[i],
                lw=(3 if hero else 1.8), alpha=(0.9 if hero else 0.45), zorder=2)
    ax.scatter(d["sos"], range(len(d)), color="#a6a6a6", s=65, zorder=3)
    ax.scatter(d["own_ppg"], range(len(d)), color=cols, s=95, zorder=4)
    mean_sos = d["sos"].mean()
    ax.axvline(mean_sos, ls="--", color=T["rule"], zorder=1)
    ax.text(mean_sos, len(d) - 0.4, "league avg", ha="center", va="top",
            fontsize=8, color=T["muted"])
    ax.set_yticks(range(len(d)))
    labels = ax.set_yticklabels(d["user_name"])
    for t, nm in zip(labels, d["user_name"]):
        if nm == manager:
            t.set_fontweight("bold")
    _row_avatars(ax, d["user_name"], s)
    # No ax.legend() here -- a fixed lower-right legend used to sit directly on
    # top of whichever manager's own dumbbell landed there (real, not
    # hypothetical: LuckyHarm's row on 2025 DDBM data). The subtitle already
    # states the grey/coloured encoding, so the legend was redundant as well
    # as the thing colliding -- dropping it fixes both.
    span_txt = f"through week {through_week}" if through_week is not None else "all season"
    return _finish(fig, ax, f"Strength of Schedule ({manager} highlighted)",
                   f"Grey = opponents' avg PPG faced, coloured = own PPG, {span_txt}  ·  "
                   "green when output beat the schedule, red when it didn't",
                   "Points per game",
                   caption=_cap(s))


def plot_mgr_efficiency_trend(s: Season, manager: str, through_week: int | None = None):
    """This manager's lineup efficiency THIS WEEK against the rest of the league.

    Originally a season-long trend line, but that arc buried the one thing a
    weekly report reader actually wants here: how did THIS week's coaching
    compare to the other nine teams' THIS week. `through_week` is
    reused as "the week to show" (the weekly report always passes the viewed
    week; this key isn't in the season report's chart set, so there's no
    season-wide caller to keep compatible). A Cleveland dot plot, not a
    zero-based bar: efficiency is a tight band (usually 75-100%), so an
    honestly-zoomed axis is what makes the spread readable at all.
    """
    lu = getattr(s, "lineup", None)
    if lu is None or not {"user_name", "week", "actual", "optimal"}.issubset(
            getattr(lu, "columns", [])):
        return _no_data(f"No lineup data for {manager} in {s.season}.")
    wk = int(through_week) if through_week is not None else s.last_week
    d = lu[lu["week"] == wk].copy()
    if d.empty or manager not in set(d["user_name"]):
        return _no_data(f"No lineup data for {manager}, week {wk}.")
    d["eff"] = (d["actual"] / d["optimal"].clip(lower=1e-9) * 100).clip(upper=100)
    d = d.sort_values("eff").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    mine_mask = d["user_name"] == manager
    cols = ["#2c7fb8" if m else T["neutral"] for m in mine_mask]
    sizes = [120 if m else 60 for m in mine_mask]
    ax.scatter(d["eff"], range(len(d)), s=sizes, c=cols, zorder=3,
               edgecolors=T["edge"], linewidths=1)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    for i, (_, r) in enumerate(d.iterrows()):
        mine = r["user_name"] == manager
        ax.text(r["eff"] + 0.4, i, f"{r['eff']:.1f}%", va="center", fontsize=8.5,
                color=T["ink2"] if mine else T["muted"],
                fontweight="bold" if mine else "normal")
    lo, hi = float(d["eff"].min()), float(d["eff"].max())
    pad = max((hi - lo) * 0.18, 3.0)
    ax.set_xlim(lo - pad, hi + pad * 1.7)
    return _finish(fig, ax, f"{manager} · Lineup Efficiency, Week {wk}",
                   "Started points as % of the best legal lineup this week  ·  vs the rest of the league",
                   "Efficiency %", caption=_cap(s))


def plot_mgr_roster_heatmap(s: Season, manager: str, through_week: int | None = None):
    """This manager's own scoring, by week and position -- the personal-timeline
    analogue of the league-wide `plot_roster_heatmap` (which is manager x
    position; this is week x position for the one manager). Counts every
    rostered player-week (bench included), same convention as `metrics.roster`.
    """
    rid = _mgr_rid(s, manager)
    pl = s.pl_wk
    if rid is None or not {"roster_id", "week", "position", "points"}.issubset(
            getattr(pl, "columns", [])):
        return _no_data(f"No roster data for {manager} in {s.season}.")
    d = pl[(pl["roster_id"] == rid) & (pl["position"].isin(POSITIONS))]
    if through_week is not None:
        d = d[d["week"] <= through_week]
    if d.empty:
        return _no_data(f"No roster data for {manager} in {s.season}.")
    weeks = sorted(d["week"].unique())
    piv = (d.groupby(["week", "position"])["points"].sum()
           .unstack("position").reindex(index=weeks, columns=POSITIONS).fillna(0))
    cmap = mcolors.LinearSegmentedColormap.from_list("sl", ["#eaf2f8", "#1f6f8b"])
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(piv.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(POSITIONS)))
    ax.set_xticklabels(POSITIONS)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(weeks)))
    ax.set_yticklabels([f"Wk {w}" for w in weeks])
    vmax = piv.values.max() if piv.values.size else 0
    for i in range(len(weeks)):
        for j in range(len(POSITIONS)):
            # Every cell here is a real value (already fillna(0)'d), so a
            # genuine 0.0 week (e.g. no DEF rostered) must still get a label
            # -- `if v > 0` used to skip it, and on the lightest heatmap step
            # that read as a blank gap rather than "zero," indistinguishable
            # from missing data.
            v = piv.values[i, j]
            col = "white" if v > vmax * 0.6 else "#1a1a1a"
            ax.text(j, i, f"{v:.1f}", ha="center", va="center",
                    fontsize=8, color=col)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Pts")
    ax.set_title(f"{manager} · Position Scoring by Week", loc="left", fontsize=16,
                 fontweight="bold", color=T["ink"], pad=24)
    fig.text(0.01, 0.01, "Points scored (starters and bench) by week and position",
             ha="left", fontsize=8.5, color=T["muted"])
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_week_matchups(s: Season, week: int):
    """The week's games as dumbbells on one points axis.

    A ranked bar chart of ten scores hides the only structure that matters in a
    week: WHO PLAYED WHOM. Here each game is one line -- both teams as dots, the
    line between them is the margin -- and every game shares the axis, so a
    narrow loss in a shoot-out and a narrow loss in a slog are visibly different
    things. The median marks whether the week was high or low scoring overall.
    """
    import pandas as pd          # plots.py imports pandas per-function

    d = s.team_wk[s.team_wk["week"] == int(week)].copy()
    if not len(d):
        return _no_data(f"No games in week {week}.")
    med = float(d["points"].median())
    games, seen = [], set()
    for r in d.itertuples(index=False):
        mid = r.matchup_id
        if pd.isna(mid):
            games.append((r.user_name, float(r.points), None, None))
            continue
        if mid in seen:
            continue
        seen.add(mid)
        pair = d[d["matchup_id"] == mid].sort_values("points", ascending=False)
        if len(pair) < 2:
            games.append((pair.iloc[0]["user_name"], float(pair.iloc[0]["points"]), None, None))
        else:
            w, l = pair.iloc[0], pair.iloc[1]
            games.append((w["user_name"], float(w["points"]),
                          l["user_name"], float(l["points"])))
    games.sort(key=lambda g: (g[1] + (g[3] or g[1])))
    fig, ax = plt.subplots(figsize=(11, max(4.2, len(games) * 0.72)))
    lo0, hi0 = float(d["points"].min()), float(d["points"].max())
    off = (hi0 - lo0) * 0.02 or 1
    for i, (wn, wp, ln, lp) in enumerate(games):
        if ln is not None:
            ax.plot([lp, wp], [i, i], color=T["rule"], lw=3.5, zorder=1,
                    solid_capstyle="round")
            ax.scatter([lp], [i], s=150, color="#c0603a", zorder=3)
            # Labels go OUTWARD from their own dot, never centred on it: a
            # 1.8-point game puts the two dots almost on top of each other and
            # centred labels overprint into "rezzvougz134.4".
            ax.text(lp - off, i, f"{lp:.1f}  {ln}", ha="right", va="center",
                    fontsize=8.6, color=T["muted"])
            ax.text((lp + wp) / 2, i + 0.34, f"+{wp - lp:.1f}", ha="center",
                    fontsize=8, fontweight="bold", color=T["muted"], zorder=4,
                    # Masked in the surface colour: the median line runs behind
                    # these and otherwise strikes through the digits.
                    bbox=dict(facecolor=T["bg"], edgecolor="none", pad=1.2))
        ax.scatter([wp], [i], s=170, color="#2ca02c", zorder=3)
        ax.text(wp + off, i, f"{wn}  {wp:.1f}", ha="left", va="center",
                fontsize=8.6, fontweight="bold", color=T["ink"])
    ax.axvline(med, color=T["ink"], lw=1.2, ls="--", zorder=2)
    ax.text(med, -0.66, f"  league median {med:.1f}", fontsize=8.5,
            color=T["ink"], va="bottom")
    ax.set_yticks([])
    ax.set_ylim(-0.75, len(games) - 0.25)
    # Wide margins so the outward labels have somewhere to go.
    ax.set_xlim(lo0 - (hi0 - lo0) * 0.62, hi0 + (hi0 - lo0) * 0.42)
    return _finish(fig, ax, f"Week {week}: The Games",
                   "Each line is one matchup: green won, orange lost, the line "
                   "between them is the margin", "Points", caption=_cap(s),
                   grid_axis="x")


def plot_week_luck(s: Season, week: int):
    """Points for vs points against, split by the line where a game is a tie.

    The luck question -- "was I beaten or did I just draw the wrong opponent?" --
    is really about two numbers at once, which no single-value chart can show.
    Every team is a point: **below** the diagonal it won, **above** it lost, and
    distance from the line is the margin. Colour carries merit (teams outscored
    that week), so an orange dot below the line is a team that got away with a
    bad score, and a green dot above it is the week's genuinely unlucky team.
    """
    d = s.team_wk[s.team_wk["week"] == int(week)].copy()
    d = d[d["pa"].notna()]
    if not len(d):
        return _no_data(f"No completed games in week {week}.")
    fig, ax = plt.subplots(figsize=(8.6, 7))
    lo = float(min(d["points"].min(), d["pa"].min()))
    hi = float(max(d["points"].max(), d["pa"].max()))
    pad = (hi - lo) * 0.14 or 5
    lo, hi = lo - pad, hi + pad
    ax.plot([lo, hi], [lo, hi], color=T["rule"], lw=1.4, ls="--", zorder=1)
    ax.fill_between([lo, hi], [lo, hi], [hi, hi], color="#c0603a", alpha=0.055, zorder=0)
    ax.fill_between([lo, hi], [lo, lo], [lo, hi], color="#2ca02c", alpha=0.055, zorder=0)
    lost_lbl = ax.text(lo + (hi - lo) * 0.03, hi - (hi - lo) * 0.04, "lost",
                       fontsize=10, color="#c0603a", fontweight="bold", va="top")
    won_lbl = ax.text(hi - (hi - lo) * 0.03, lo + (hi - lo) * 0.04, "won",
                      fontsize=10, color="#2ca02c", fontweight="bold", ha="right")
    n = int((d["allplay_w"] + d["allplay_l"]).max()) or 1
    cmap = matplotlib.colormaps["RdYlGn"]
    ax.scatter(d["points"], d["pa"], s=210, zorder=3, edgecolor=T["edge"], lw=1,
               c=[cmap(v / n) for v in d["allplay_w"]])
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    # x is your own score -- your performance against the WHOLE field (what drives
    # all-play), so it deliberately doesn't mirror the y-axis, which is just the
    # single opponent you happened to draw.
    fig = _finish(fig, ax, f"Week {week}: Beaten, or Just Unlucky?",
                  "Colour = teams outscored  ·  green in red = unlucky, orange in green = got away with one",
                  "Your score vs the field", "Points against", caption=_cap(s), grid_axis="both")
    # After _finish: tight_layout has settled the axes, so the collision solver
    # is working with the geometry that will actually be drawn.
    _place_labels(fig, ax, list(d["points"]), list(d["pa"]),
                  [f"{r.user_name}  ({int(r.allplay_w)}-{int(r.allplay_l)})"
                   for r in d.itertuples(index=False)],
                  avoid=(lost_lbl, won_lbl))
    return fig


def plot_week_race(s: Season, week: int):
    """The table position race, weeks 1 to `week`.

    A snapshot of the standings says where everyone is; this says how they got
    there. Reading week 5 against the race up to week 5 is the point of a weekly
    tab -- the finished-season version of this chart lives on Overview.

    Styled to match the rest of the report rather than a raw matplotlib
    cycle: `palette()` gives each manager the SAME colour they carry on every
    other chart, an avatar token marks their current-week position (same
    identity language as the standings/power charts), and end-of-line labels
    run through the shared collision solver -- a plain per-line annotate
    prints straight through a neighbour whenever two teams are tied or close
    at the final week, which happens often in a bump chart.
    """
    d = metrics.table_position(s)
    d = d[d["week"] <= int(week)]
    if not len(d):
        return _no_data(f"Nothing scored through week {week}.")
    n = int(d["table_position"].max())
    fig, ax = plt.subplots(figsize=(10.5, max(4.5, n * 0.5)))
    last = d[d["week"] == d["week"].max()].sort_values("table_position")
    cols = palette(last["user_name"])
    for nm in last["user_name"]:
        g = d[d["user_name"] == nm].sort_values("week")
        ax.plot(g["week"], g["table_position"], color=cols[nm], lw=2.2,
                marker="o", ms=5, zorder=3)
    ax.set_ylim(n + 0.6, 0.4)
    ax.set_yticks(range(1, n + 1))
    ax.set_xticks(sorted(d["week"].unique()))
    ax.set_xlim(0.6, int(week) + (int(week) * 0.30))
    ends = d[d["week"] == d["week"].max()].sort_values("table_position")
    if not _point_avatars(ax, ends["week"], ends["table_position"], ends["user_name"], s, zoom=0.34):
        # No avatars available (no network, no accounts) -- fall back to a
        # plain coloured dot at the same spot so the endpoint still reads.
        ax.scatter(ends["week"], ends["table_position"],
                   c=[cols[nm] for nm in ends["user_name"]], s=60, zorder=4,
                   edgecolors=T["edge"], linewidths=1)
    # Plain horizontal labels, one per row -- `table_position` is always a
    # unique integer 1..n, so every row already has its own dedicated y slot
    # the same width as every other (the y-ticks are spaced identically).
    # A general-purpose collision solver (tried first) sometimes bumped a
    # label up or down to dodge a neighbour, which sliced a team's name away
    # from its own row -- exactly the "1st/last place spliced above/below"
    # problem a bump chart can't afford, since the row IS the answer.
    # Medal-coloured names take the place of a separate podium disc for the
    # top 3, so their standing reads without adding more geometry to dodge.
    for r in ends.itertuples(index=False):
        rk = int(r.table_position)
        col = MEDAL[rk - 1] if rk <= 3 else T["ink"]
        ax.annotate(f" {r.user_name}", (r.week, r.table_position),
                   textcoords="offset points", xytext=(12, 0), va="center",
                   fontsize=9, color=col, fontweight="bold", zorder=5)
    return _finish(fig, ax, f"The Race Through Week {week}",
                   "Table position after each week; crossings are lead changes  ·  "
                   "gold/silver/bronze = this week's top 3",
                   "Week", "Table position", caption=_cap(s), grid_axis="both")


def plot_week_power(s: Season, week: int):
    """Power rankings, capped through `week` -- the weekly report's reuse of
    `plot_power_rank` (season-wide) so a week-5 report doesn't leak weeks 6-14
    into the composite score."""
    d = metrics.power_rank(s, through_week=week).sort_values("power").reset_index(drop=True)
    if not len(d):
        return _no_data(f"Nothing scored through week {week}.")
    fig, ax = plt.subplots(figsize=(9.5, 6))
    colors = ["#2c7fb8" if v > 0 else "#c0563f" for v in d["power"]]
    ax.barh(range(len(d)), d["power"], color=colors, height=0.72, zorder=2)
    ax.axvline(0, color=T["rule"], zorder=3)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    span = d["power"].max() - d["power"].min()
    _medals(ax, d, "power_rank", d["power"].min() - span * 0.04)
    for i, (_, r) in enumerate(d.iterrows()):
        off = span * 0.012
        ha = "left" if r["power"] > 0 else "right"
        ax.text(r["power"] + (off if r["power"] > 0 else -off), i,
                f"{r['power']:+.2f}", va="center", ha=ha, fontsize=9, color=T["ink2"])
    ax.set_xlim(d["power"].min() - span * 0.18, d["power"].max() + span * 0.16)
    return _finish(fig, ax, f"Power Rankings Through Week {week}",
                   "Composite of points, all-play win%, recent form and lineup efficiency  ·  0 = league average",
                   "Power Score (standardised)", caption=_cap(s))


