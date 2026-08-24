"""Charts (matplotlib; mirrors R plots.R theme, palette + flair)."""
from __future__ import annotations

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
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(d)), d["points"], color=[pal[n] for n in d["user_name"]],
            height=0.72, zorder=2)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    xmax = d["points"].max()
    _medals(ax, d, "final_position", xmax * 0.035)
    for i, (_, r) in enumerate(d.iterrows()):
        star = "  ★" if r["champion"] else ""
        ax.text(r["points"] + xmax * 0.01, i, f"{r['wins']}-{r['losses']}{star}",
                va="center", fontsize=9, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.16)
    return _finish(fig, ax, f"{s.season} Standings",
                   "Bars = total points, in standing order  ·  1-2-3 podium  ·  ★ champion",
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
    if d.empty:
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
                   "Darker = better  ·  faint bar = that manager's worst-to-best week  ·  "
                   "caps mark their single best/worst week",
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
    fig, ax = plt.subplots(figsize=(9.5, 6))
    colors = ["#2c7fb8" if v > 0 else "#c0563f" for v in d["power"]]
    ax.barh(range(len(d)), d["power"], color=colors, height=0.72, zorder=2)
    ax.axvline(0, color=T["rule"], zorder=3)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    span = d["power"].max() - d["power"].min()
    # d is already in bar order (power ascending); _medals positions by row index,
    # so it must NOT be re-sorted or the medals land on the wrong rows.
    _medals(ax, d, "power_rank", d["power"].min() - span * 0.04)
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
                   "Share of each manager's flex-slot starts filled by RB, WR or TE  ·  "
                   "reconstructed from their actual started lineups",
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
                ax.text(left[p] + row[p] / 2, y[p], f"{round(row[p])} ({int(wk[p])}w)",
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


def plot_playoff_bracket(p, ref_scores: dict | None = None):
    """Rounds left to right; winner filled, loser grey, bye amber, pending hollow.

    `ref_scores` is `{(manager, week): points}` (see `reference_scores`). A node
    with no bracket score of its own -- a bye, or a team waiting out a round --
    shows what it **actually scored** that week in parentheses instead of a bare
    dash, which reads as missing data when the number is right there in the
    season. Parenthesised because it decides nothing: the team advanced on the
    bye, not on those points.
    """
    import pandas as pd
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
    d["y"] = d["cy"] + (d["sides"] > 1) * (d["side"] * 0.38 - 0.19)

    COL = {"W": "#a5d6a7", "L": "#e6e8ea", "BYE": "#ffe0a3", "PENDING": "#f4f6f8", "T": "#e6e8ea"}
    fig, ax = plt.subplots(figsize=(12.5, max(5.5, span * 1.05)))
    # connectors: each advancing team flows into the next matchup that holds it
    for _, a in d[d["result"].isin(["W", "BYE"])].iterrows():
        nxt = d[(d["team"] == a["team"]) & (d["rx"] > a["rx"])].sort_values("rx")
        if len(nxt):
            n = nxt.iloc[0]
            ax.plot([a["rx"] + 0.44, n["rx"] - 0.44], [a["cy"], n["y"]],
                    color=T["rule"], lw=1, zorder=1)
    for _, r in d.iterrows():
        ax.add_patch(plt.Rectangle((r["rx"] - 0.43, r["y"] - 0.15), 0.86, 0.30,
                                   facecolor=COL.get(r["result"], "#e6e8ea"),
                                   edgecolor=T["edge"], lw=1.2, zorder=2))
        sd = seed_of.get(r["team"], "")
        if not pd.isna(r["points"]):
            pts = f"{r['points']:.1f}"
        else:
            pts = _ref_label(ref_scores, r["team"], r["weeks"])
        # Node fills (COL) are always light, so their label stays dark on both
        # themes -- following T["ink"] here would vanish on a light node in dark.
        ax.text(r["rx"], r["y"], f"{sd}  {r['team']}   {pts}".strip(), ha="center",
                va="center", fontsize=9, zorder=3,
                fontweight="bold" if r["result"] == "W" else "normal", color="#242424")
    ax.set_xlim(-0.6, len(rounds) - 0.4)
    ax.set_ylim(span + 0.25, -0.25)
    ax.set_xticks(range(len(rounds)))
    ax.set_xticklabels(list(dict.fromkeys(d["round"])), fontweight="bold")
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"])
    # The round names are TOP-axis tick labels, so ANY text between the title and
    # the axes runs straight through them -- there is no subtitle band here. The
    # champion rides in the title and the explanation goes to the bottom of the
    # figure (same rule as the matrix charts).
    ax.set_title(f"{p.name} · {p.season} Bracket  —  Champion: "
                 f"{p.champion or 'undecided'}", loc="left", fontsize=16,
                 fontweight="bold", color=T["ink"], pad=26)
    note = ("Every score is computed from the submitted lineups under the "
            "league's own scoring chart.")
    if ref_scores:
        note += ("   (Bracketed) is what a bye/idle team happened to score that "
                 "week — shown for reference; it decides nothing.")
    fig.text(0.01, 0.015, note, fontsize=9, color=T["muted"], va="bottom")
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    return fig


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


def plot_playoff_players_splice(seasons: dict, playoffs: dict, n: int = 15, scope: str = "title"):
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

    Colour is GAME SLOT (1st game, 2nd game, 3rd...), the same fixed hue at
    that slot for every player, reusing `_MANAGER_HUES` purely as an ordered
    categorical set here (same "index by position, not by manager identity"
    precedent `plot_trade_single_contribution` already uses for its own
    per-player segments) -- this replaces position-as-color entirely, so
    position moves into the label instead (same "position as text, not bar
    color" convention the `_postext` prototype in this same round already
    established) and there is no swatch legend, since a "game 1/2/3..." key
    would need as many entries as the deepest career run and still not tell
    a reader anything a hover/label doesn't already say better -- each
    slice's own points value is labelled inside it when there's room.

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
    top = playoff_players(playoffs, scope).head(n).iloc[::-1].reset_index(drop=True)
    if top.empty:
        return _no_data("No playoff performances recorded.")
    perf = playoff_performances(playoffs, scope)
    perf = perf[perf["player_id"].isin(top["player_id"])]
    perf = perf.sort_values(["player_id", "season", "week"])
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
    labels = []
    for _, r in top.iterrows():
        badge = f" #{pos_ranks[r['player_id']]}" if r["player_id"] in pos_ranks else ""
        labels.append(f"{r['player_name']}  ·  {r['position']}{badge}")
    ax.set_yticks(range(len(top)))
    ax.set_yticklabels(labels, fontsize=8.5)
    _portraits(ax, labels, top["player_id"], top["position"])
    xmax = float(top["points"].max())
    for i, r in top.iterrows():
        games = perf[perf["player_id"] == r["player_id"]]
        left = 0.0
        for j, (_, g) in enumerate(games.iterrows()):
            pts = float(g["points"])
            color = _MANAGER_HUES[j % len(_MANAGER_HUES)]
            ax.barh(i, pts, left=left, height=0.72, color=color,
                    edgecolor=T["bg"], linewidth=1.0, zorder=2)
            if pts >= xmax * 0.045:
                ax.text(left + pts / 2, i, f"{pts:.0f}", ha="center", va="center",
                        fontsize=7, fontweight="bold", color="white", zorder=3)
            left += pts
        ax.text(left + xmax * 0.01, i, f"{r['points']:.0f} total  ({r['ppg']:.1f} ppg)",
                va="center", fontsize=8.5, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.34)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Best Playoff Players{suffix}",
                   f"Points scored across {span}  ·  {sub}  ·  each slice = one playoff "
                   "game, earliest first, width = that game's points",
                   "Playoff Points")


def plot_playoff_players_topband(playoffs: dict, n: int = 15, scope: str = "title"):
    """Best Playoff Players (PROTOTYPE), legend variant: the position-color key
    moves to a horizontal strip ABOVE the axes (bbox_to_anchor) instead of
    `loc="lower right"` sitting in-axes -- the original's legend currently
    clears the shortest bars by luck (15 real players), not by any
    guarantee, and is the exact collision shape already fixed on `plot_mgr_sos`/
    `plot_clutch`/`plot_draft_grades_value` this session. Everything else
    (rings, portraits, labels) is untouched, so this is a single isolated
    variable to judge.
    """
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
    ax.legend(handles, seen, loc="lower left", frameon=False, fontsize=8, ncol=6,
              bbox_to_anchor=(0.0, 1.02))
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Best Playoff Players{suffix} (PROTOTYPE: top legend)",
                   f"Points scored across {span}  ·  {sub}  ·  ★ per title",
                   "Playoff Points")


def plot_playoff_players_postext(playoffs: dict, n: int = 15, scope: str = "title"):
    """Best Playoff Players (PROTOTYPE), no-legend variant: position is
    plain text next to each player's name instead of encoded in bar color --
    every bar is one neutral color, so there is no legend to place (and
    therefore no collision risk at all, the most direct fix of the three
    prototypes here) and no need to cross-reference a color swatch back to a
    position name. Trade-off: scanning "which rows are RBs" at a glance is
    slower than reading bar color -- judge whether that's a real loss or not.
    """
    from .playoffs import playoff_players
    d = playoff_players(playoffs, scope).head(n).iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.barh(range(len(d)), d["points"], height=0.72, color=T["neutral"])
    labels = list(d["player_name"])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(labels, fontsize=8.5)
    _portraits(ax, labels, d["player_id"], d["position"])
    xmax = float(d["points"].max())
    for i, r in d.iterrows():
        rings = "★" * int(r["rings"])
        ax.text(r["points"] + xmax * 0.01, i,
                f"{r['position']}  ·  {r['points']:.0f}  ({r['ppg']:.1f} ppg)  {rings}",
                va="center", fontsize=8.5, color=T["ink2"])
    ax.set_xlim(0, xmax * 1.42)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Best Playoff Players{suffix} (PROTOTYPE: no legend)",
                   f"Points scored across {span}  ·  {sub}  ·  ★ per title  ·  "
                   "position shown as text, not bar color",
                   "Playoff Points")


def plot_playoff_players_medal(playoffs: dict, n: int = 15, scope: str = "title"):
    """Best Playoff Players (PROTOTYPE), medal variant: ring count pulled OUT
    of the trailing text label into its own medal-colored badge (reusing the
    same MEDAL gold/silver/bronze palette this file already validates
    elsewhere), planted right after the value text -- a repeat champion is
    now visible without reading all the way to a trailing "★★★" at the very
    end of the row. 1 ring = gold circle, 2 = gold+silver, 3+ =
    gold+silver+bronze (caps at 3 markers regardless of ring count, labelled
    with the real count past that so a 5-time champion doesn't need 5 drawn
    circles to be legible).

    Dot x-position is measured from the value text's OWN rendered width
    (draw once, read `get_window_extent()`, same "measure, don't guess"
    technique `_identity_rows`' portrait placement already uses) rather than
    a fixed axis-fraction offset -- a fixed offset broke on the first real
    render here: it placed the dots in DATA coordinates near the y-axis
    origin, which overlapped the player-name tick labels `_portraits`
    already occupies that space with, instead of sitting in the open space
    after each bar's own value text where they were intended to go.
    """
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
    ax.set_xlim(0, xmax * 1.55)  # wider than the original 1.34: room for medal dots past the value text
    fig.canvas.draw()  # realise text extents before measuring below
    inv = ax.transData.inverted()
    for i, r in d.iterrows():
        rings = int(r["rings"])
        txt = ax.text(r["points"] + xmax * 0.01, i,
                       f"{r['points']:.0f}  ({r['ppg']:.1f} ppg)",
                       va="center", fontsize=8.5, color=T["ink2"])
        if not rings:
            continue
        # Right edge of the text just drawn, converted back to data x, plus a
        # small gap -- so the first dot always starts clear of the text
        # regardless of how wide the PPG number happens to render.
        text_right = inv.transform((txt.get_window_extent(fig.canvas.get_renderer()).x1, 0))[0]
        start = text_right + xmax * 0.02
        shown = min(rings, 3)
        for j in range(shown):
            ax.scatter(start + j * xmax * 0.035, i, s=60,
                       color=MEDAL[j], edgecolors=T["edge"], linewidths=0.6,
                       zorder=4, clip_on=False)
        if rings > 3:
            ax.text(start + shown * xmax * 0.035, i, f"+{rings - 3}",
                    va="center", fontsize=7.5, color=T["muted"])
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    seen = [p for p in POSITIONS if p in set(d["position"])]
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in seen]
    ax.legend(handles, seen, loc="lower right", frameon=False, fontsize=8, ncol=3)
    suffix, span = _po_span(playoffs)
    return _finish(fig, ax, f"Best Playoff Players{suffix} (PROTOTYPE: medal markers)",
                   f"Points scored across {span}  ·  {sub}  ·  "
                   "gold/silver/bronze dots = ring count",
                   "Playoff Points")


def plot_clutch(seasons: dict, playoffs: dict, scope: str = "title"):
    """Playoff PPG vs regular-season PPG -- who raises their game."""
    from .playoffs import clutch as _clutch
    d = _clutch(seasons, playoffs, scope).sort_values("clutch").reset_index(drop=True)
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
    _, span = _po_span(playoffs)
    return _finish(fig, ax, "Clutch: Playoff vs Regular-Season Scoring",
                   f"Grey dot = regular-season PPG; coloured = playoff PPG  ·  "
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
    return _finish(fig, ax, f"{s.season}: Redraft Simulation — Wins, Real vs. {basis_label}",
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
    return _finish(fig, ax, f"{s.season}: Redraft Simulation — Standings Reshuffle{basis_label}",
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
                   "Each line is one matchup — green won, orange lost, the line "
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
                   "Table position after each week — crossings are lead changes  ·  "
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


