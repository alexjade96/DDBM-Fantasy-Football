"""Charts (matplotlib; mirrors R plots.R theme, palette + flair)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import headshots, metrics  # noqa: E402
from .season import Season  # noqa: E402


def _identity_rows(ax, labels, images, zoom=0.30, gap_pt=6):
    """Icon-then-name axis: every row reads [icon] name  |  bar.

    The names stay real tick labels (so nothing has to re-implement them) but are
    left-aligned into a column, and each row's circular token is hung just to
    their left. Finding where that column starts needs the *rendered* label
    width, so this draws once and measures rather than guessing from character
    counts.

    Best-effort: a row with no image keeps its plain name, and if nothing loaded
    at all the axis is left exactly as it was.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.transforms import blended_transform_factory
    if not any(im is not None for im in images):
        return
    fig = ax.figure
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels)
    for t in ax.get_yticklabels():
        t.set_ha("left")
    fig.canvas.draw()                       # realise the text extents
    maxw_px = max(t.get_window_extent().width for t in ax.get_yticklabels())
    pad = maxw_px * 72.0 / fig.dpi + gap_pt   # px -> pt: where the name column starts
    ax.tick_params(axis="y", pad=pad)
    tr = blended_transform_factory(ax.transAxes, ax.transData)  # x=axes, y=data
    for i, img in enumerate(images):
        if img is None:
            continue
        # 7.4pt clear of the name column -- matches the R side's 2.6mm.
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (0, i), xycoords=tr,
                            xybox=(-(pad + 7.4), 0), boxcoords="offset points",
                            frameon=False, box_alignment=(1.0, 0.5),
                            pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)


def _portraits(ax, labels, ids, positions, zoom=0.30):
    """Icon-then-name axis for a player chart (token = the player's headshot)."""
    _identity_rows(ax, list(labels),
                   [headshots.load(pid, pos, size=72) for pid, pos in zip(ids, positions)],
                   zoom=zoom)

POS_COLORS = {"QB": "#d62728", "RB": "#2ca02c", "WR": "#1f77b4",
              "TE": "#ff7f0e", "K": "#9467bd", "DEF": "#8c564b"}
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
    their coloured dot underneath. Returns True if any avatar was drawn.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    urls = _avatar_map(s)
    drawn = False
    for x, y, n in zip(xs, ys, names):
        img = headshots.avatar_image(urls.get(n))
        if img is None:
            continue
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (x, y), frameon=False,
                            pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)
        drawn = True
    return drawn


def palette(names) -> dict:
    """A stable colour per manager (matplotlib 'Paired', like R sl_palette)."""
    names = sorted(set(names))
    cmap = matplotlib.colormaps["Paired"].resampled(max(len(names), 1))
    return {n: mcolors.to_hex(cmap(i)) for i, n in enumerate(names)}


def _finish(fig, ax, title, subtitle=None, xlabel=None, ylabel=None, caption=None,
            grid_axis="x"):
    ax.set_title(title, loc="left", fontsize=16, fontweight="bold",
                 color=T["ink"], pad=24)
    if subtitle:
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
        ax.text(0, 1.0, subtitle, transform=trans, fontsize=9.5,
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
    # Seed with any fixed artists that must also be dodged (zone captions etc.),
    # otherwise the solver treats their space as free.
    boxes: list = [a.get_window_extent(rend) for a in avoid]

    def clashes(bb):
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
            ann.remove()
        if best is None:      # every spot taken -- fall back to directly above
            ann = ax.annotate(texts[i], (xs[i], ys[i]), textcoords="offset points",
                              xytext=(0, 16), ha="center", va="bottom",
                              fontsize=fontsize, color=color or T["ink"], zorder=5,
                              bbox=dict(facecolor=T["bg"], edgecolor="none",
                                        alpha=.75, pad=1.4))
            best = (ann, ann.get_window_extent(rend))
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
    d = metrics.efficiency(s).sort_values("eff").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = matplotlib.colormaps["Greens"]
    norm = mcolors.Normalize(vmin=70, vmax=100)
    ax.barh(range(len(d)), d["eff"], height=0.72,
            color=[cmap(norm(min(max(v, 70), 100))) for v in d["eff"]])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    ax.axvline(100, ls="--", color=T["rule"], zorder=1)
    ax.text(100, len(d) - 0.4, "optimal", ha="right", va="top", fontsize=8, color=T["rule"])
    for i, (_, r) in enumerate(d.iterrows()):
        ax.text(r["eff"] + 0.5, i, f"{r['eff']:.1f}%  ({round(r['bench'])} pts benched)",
                va="center", fontsize=8, color=T["ink2"])
    ax.set_xlim(0, 100)
    return _finish(fig, ax, "Lineup Efficiency (Coaching)",
                   "Started points as % of the optimal lineup each week (darker = better)",
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
    _point_avatars(ax, d["points"], d["pa"], d["user_name"], s, zoom=0.44)
    for _, r in d.iterrows():
        ax.annotate(f"{r['user_name']} ({r['wins']}W)", (r["points"], r["pa"]),
                    textcoords="offset points", xytext=(21, 0), va="center",
                    fontsize=8, color=T["ink2"])
    xr = ax.get_xlim(); yr = ax.get_ylim()
    for (xx, yy, ha, va, lab) in [
        (xr[1], yr[0], "right", "bottom", "Dominant"),
        (xr[0], yr[1], "left", "top", "Snakebit"),
        (xr[1], yr[1], "right", "top", "Shootouts"),
        (xr[0], yr[0], "left", "bottom", "Low-event")]:
        ax.text(xx, yy, lab, ha=ha, va=va, fontsize=9, style="italic", color="#bfbfbf")
    return _finish(fig, ax, "Points For vs Points Against",
                   "Lower-right beats up the league; upper-left gets snakebit  ·  size = wins",
                   "Points For", "Points Against", caption=_cap(s), grid_axis="both")


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
    _point_avatars(ax, d["moves_per_wk"], d["lineup_iq"], d["user_name"], s, zoom=0.46)
    for _, r in d.iterrows():
        ax.annotate(r["user_name"], (r["moves_per_wk"], r["lineup_iq"]),
                    textcoords="offset points", xytext=(22, 0), va="center",
                    fontsize=8, color=T["ink2"])
    return _finish(fig, ax, "Manager Tendencies",
                   "Right = works the wire  ·  up = sets a sharp lineup  ·  bubble = trades made",
                   "Roster Moves per Week", "Lineup IQ (% of optimal)",
                   caption=_cap(s), grid_axis="both")


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
    d = metrics.career(seasons).copy()
    d["rank"] = d["win_pct"].rank(ascending=False, method="first").astype(int)
    d = d.sort_values("win_pct").reset_index(drop=True)
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(range(len(d)), d["win_pct"], color=[pal[n] for n in d["user_name"]],
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
    d = metrics.roster(s)
    users = sorted(d["user_name"].unique())
    piv_avg = d.pivot(index="user_name", columns="position", values="avg").reindex(
        index=users, columns=POSITIONS)
    piv_spots = d.pivot(index="user_name", columns="position", values="spots").reindex(
        index=users, columns=POSITIONS)
    cmap = mcolors.LinearSegmentedColormap.from_list("sl", ["#eaf2f8", "#1f6f8b"])
    fig, ax = plt.subplots(figsize=(9, 6))
    im = ax.imshow(piv_avg.values, aspect="auto", cmap=cmap)
    ax.set_xticks(range(len(POSITIONS)))
    ax.set_xticklabels(POSITIONS)
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks(range(len(users)))
    ax.set_yticklabels(users)
    vmax = piv_avg.values.max()
    for i in range(len(users)):
        for j in range(len(POSITIONS)):
            sp, av = piv_spots.values[i, j], piv_avg.values[i, j]
            if sp == sp:  # not NaN
                col = "white" if av > vmax * 0.6 else "#1a1a1a"
                ax.text(j, i, f"{int(sp)} wk\n{av:.1f}", ha="center", va="center",
                        fontsize=7.5, color=col, linespacing=0.95)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors=T["tick"], labelsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Avg pts")
    ax.set_title("Roster Construction", loc="left", fontsize=16, fontweight="bold",
                 color=T["ink"], pad=24)
    # This is a matrix chart with its column labels (positions) on the TOP axis,
    # same as plot_schedule_swap/plot_head_to_head -- an explanatory subtitle up
    # there collides with either the tick labels or the title (measured: it sat
    # inside the title's own bounding box). Put it at the bottom instead, like
    # those two charts already do.
    fig.text(0.01, 0.01, "Player-weeks rostered and average points, by team and position",
             ha="left", fontsize=8.5, color=T["muted"])
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    return fig


def plot_starter_bench(s: Season):
    d = metrics.starter_bench(s)
    users = sorted(d["user_name"].unique())
    fig, axes = plt.subplots(1, len(POSITIONS), figsize=(15, 6), sharey=True)
    yy = list(range(len(users)))
    for ax, p in zip(axes, POSITIONS):
        sub = d[d["position"] == p]
        st = sub[sub["status"] == "Starters"].set_index("user_name")["avg"].reindex(users).fillna(0)
        bn = sub[sub["status"] == "Bench"].set_index("user_name")["avg"].reindex(users).fillna(0)
        ax.barh([y + 0.2 for y in yy], st.values, height=0.38, color="#2f9e44", label="Starters")
        ax.barh([y - 0.2 for y in yy], bn.values, height=0.38, color=T["neutral"], label="Bench")
        ax.set_title(p, fontsize=12, fontweight="bold", color=T["ink2"])
        ax.grid(axis="x", color=T["grid"], linewidth=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, colors=T["tick"], labelsize=9)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color(T["spine"])
    axes[0].set_yticks(yy)
    axes[0].set_yticklabels(users)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", frameon=False, fontsize=9,
               bbox_to_anchor=(0.99, 1.0))
    # Explicit y for both: the default suptitle y and a fixed subtitle y were
    # only ~3.5% of figure height apart (measured: they overlapped outright),
    # since neither accounts for the other's actual rendered height. Pin them
    # far enough apart here, and pull the subplot area's top boundary (in
    # tight_layout's rect) down to clear both.
    fig.suptitle("Starters vs Bench   ", x=0.01, y=0.99, ha="left", va="top",
                 fontsize=16, fontweight="bold", color=T["ink"])
    fig.text(0.01, 0.895, "Average points by position  ·  are the right players in the lineup?",
             fontsize=9.5, color=T["muted"], va="top")
    fig.text(0.99, 0.005, _cap(s), ha="right", fontsize=7, color=T["faint"])
    fig.tight_layout(rect=[0, 0.01, 1, 0.855])
    return fig


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
    ax.bar(list(x), start, width=0.7, color="#2f9e44", label="Starters")
    ax.bar(list(x), bench, width=0.7, bottom=start, color=T["neutral"], label="Bench")
    for j in x:
        if start[j] > 0:
            ax.text(j, start[j] / 2, f"{start[j]:.1f}", ha="center", va="center",
                    fontsize=8, fontweight="bold", color="white")
        if bench[j] > 0:
            ax.text(j, start[j] + bench[j] / 2, f"{bench[j]:.1f}", ha="center",
                    va="center", fontsize=8, fontweight="bold", color="white")
    ax.set_xticks(list(x))
    ax.set_xticklabels(POSITIONS)
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


def plot_clutch(seasons: dict, playoffs: dict, scope: str = "title"):
    """Playoff PPG vs regular-season PPG -- who raises their game."""
    from .playoffs import clutch as _clutch
    d = _clutch(seasons, playoffs, scope).sort_values("clutch").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6))
    cols = ["#2ca02c" if v > 0 else "#d62728" for v in d["clutch"]]
    for i, r in d.iterrows():
        ax.plot([r["reg_ppg"], r["po_ppg"]], [i, i], color=cols[i], lw=2.5,
                alpha=0.5, zorder=1)
    ax.scatter(d["reg_ppg"], range(len(d)), color="#a6a6a6", s=65, zorder=2,
               label="regular season")
    ax.scatter(d["po_ppg"], range(len(d)), color=cols, s=95, zorder=3, label="playoffs")
    for i, r in d.iterrows():
        off, ha = (2, "left") if r["clutch"] > 0 else (-2, "right")
        ax.text(r["po_ppg"] + off, i, f"{r['clutch']:+.1f}", va="center", ha=ha,
                fontsize=8, fontweight="bold", color=cols[i])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    ax.legend(loc="lower right", frameon=False, fontsize=8)
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
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    mx, my = d["avg"].median(), d["sd"].median()
    ax.axvline(mx, ls="--", color=T["rule"], zorder=1)
    ax.axhline(my, ls="--", color=T["rule"], zorder=1)
    ax.scatter(d["avg"], d["sd"], s=95, c=[pal[n] for n in d["user_name"]],
               edgecolors=T["edge"], linewidths=1, zorder=3)
    _point_avatars(ax, d["avg"], d["sd"], d["user_name"], s, zoom=0.44)
    for _, r in d.iterrows():
        ax.text(r["avg"], r["sd"] + (d["sd"].max() - d["sd"].min()) * 0.03,
                r["user_name"], ha="center", va="bottom", fontsize=8, color=T["ink2"])
    xr = (d["avg"].max() - d["avg"].min()) or 1
    yr = (d["sd"].max() - d["sd"].min()) or 1
    ax.set_xlim(d["avg"].min() - xr * 0.12, d["avg"].max() + xr * 0.12)
    ax.set_ylim(d["sd"].min() - yr * 0.18, d["sd"].max() + yr * 0.2)
    for x, y, ha, va, txt in [
        (ax.get_xlim()[1], ax.get_ylim()[1], "right", "top", "boom or bust"),
        (ax.get_xlim()[1], ax.get_ylim()[0], "right", "bottom", "elite & steady"),
        (ax.get_xlim()[0], ax.get_ylim()[0], "left", "bottom", "quietly steady"),
        (ax.get_xlim()[0], ax.get_ylim()[1], "left", "top", "low & volatile")]:
        ax.text(x, y, txt, ha=ha, va=va, fontsize=8, style="italic",
                color=T["faint"], zorder=1)
    return _finish(fig, ax, "Boom or Bust: Average vs Volatility",
                   "Right = scores more  ·  up = swingier week to week",
                   "Average points per week", "Std. dev of weekly points",
                   caption=_cap(s), grid_axis="both")


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
    """Pick number vs points returned -- where the steals and busts landed."""
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
                   "Overall pick number", "Started points returned", caption=_cap(s))


def plot_draft_grades(s: Season):
    """Total started points each manager got out of their draft."""
    from . import draft as _draft
    d = _draft.draft_grades(s)
    fig, ax = plt.subplots(figsize=(9, 6))
    if d.empty:
        ax.axis("off")
        ax.set_title("Draft Grades", loc="left", fontsize=16, fontweight="bold",
                     color=T["ink"], pad=20)
        ax.text(0.5, 0.5, "No draft data for this season.", ha="center",
                va="center", transform=ax.transAxes, fontsize=11.5, color=T["muted"])
        return fig
    d = d.sort_values("points").reset_index(drop=True)
    cmap = matplotlib.colormaps["Greens"]
    lo, hi = d["points"].min(), d["points"].max()
    norm = mcolors.Normalize(vmin=lo - (hi - lo) * 0.5, vmax=hi)
    ax.barh(range(len(d)), d["points"], height=0.72, zorder=2,
            color=[cmap(norm(v)) for v in d["points"]])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    for i, r in d.iterrows():
        ax.text(r["points"] + hi * 0.01, i,
                f"{r['points']:.0f}  ({int(r['hits'])} hits · {r['ppp']:.0f}/pick)",
                va="center", fontsize=8, color=T["ink2"])
    ax.set_xlim(0, hi * 1.28)
    return _finish(fig, ax, f"{s.season} Draft Grades",
                   "Total started points from drafted players  ·  "
                   "hit = a 100+ point season", "Started points from the draft",
                   caption=_cap(s))


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


def plot_mgr_optimal(s: Season, manager: str, through_week: int | None = None):
    """Started vs optimal each week, over the running cost of the bench.

    Two stacked panels rather than one chart with two y-scales: weekly points
    and a season-cumulative total are different magnitudes, and a dual axis
    would make their crossings meaningless. `through_week` caps the season at
    that week, for the weekly report's reuse of this otherwise season-wide
    chart (the cumulative panel should run through the viewed week, not the
    whole season).
    """
    lu = getattr(s, "lineup", None)
    if lu is None or not {"user_name", "week", "actual", "optimal"}.issubset(
            getattr(lu, "columns", [])):
        return _no_data(f"No lineup data for {manager} in {s.season}.")
    d = lu[lu["user_name"] == manager]
    if through_week is not None:
        d = d[d["week"] <= through_week]
    d = d.sort_values("week")
    if d.empty:
        return _no_data(f"No lineup data for {manager} in {s.season}.")
    lost = (d["optimal"] - d["actual"]).clip(lower=0)
    # No explicit hspace: _finish runs tight_layout, which warns and overrides
    # a hand-set gridspec spacing.
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(9.5, 6.4), sharex=True,
        gridspec_kw={"height_ratios": [3, 1]})
    w = d["week"]
    ax.bar(w, d["optimal"], width=0.68, color=T["neutral"], alpha=0.55,
           zorder=1, label="optimal")
    ax.bar(w, d["actual"], width=0.68, color="#2ca02c", zorder=2, label="started")
    # Only annotate weeks that actually cost something, so the labels stay scannable.
    top = float(d["optimal"].max())
    for wk, opt, gap in zip(w, d["optimal"], lost):
        if gap >= top * 0.04:
            ax.text(wk, opt + top * 0.015, f"-{gap:.0f}", ha="center",
                    fontsize=7.5, color="#d62728", fontweight="bold")
    ax.set_ylim(0, top * 1.12)
    # No legend: the bars run full height, so any in-axes placement sits on the
    # data, and the subtitle already names both series.
    ax2.fill_between(w, lost.cumsum(), color="#d62728", alpha=0.28, zorder=1)
    ax2.plot(w, lost.cumsum(), color="#d62728", lw=1.8, zorder=2)
    ax2.set_xticks(list(w))
    ax2.set_ylabel("Cumulative", fontsize=9, color=T["muted"])
    ax2.set_xlabel("Week", fontsize=10, color=T["muted"])
    ax2.grid(axis="y", color=T["grid"], linewidth=0.7)
    ax2.set_axisbelow(True)
    ax2.tick_params(colors=T["tick"], labelsize=9.5)
    for sp in ("top", "right", "left"):
        ax2.spines[sp].set_visible(False)
    ax2.spines["bottom"].set_color(T["spine"])
    total = float(lost.sum())
    span_txt = f"through week {through_week}" if through_week is not None else "all season"
    return _finish(fig, ax, f"{manager} · Started vs Optimal",
                   "Grey = the best legal lineup that week; green = what they "
                   f"started  ·  {total:.0f} pts left on the bench {span_txt}",
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
    ax.scatter(d["sos"], range(len(d)), color="#a6a6a6", s=65, zorder=3,
               label="opponents faced (PPG)")
    ax.scatter(d["own_ppg"], range(len(d)), color=cols, s=95, zorder=4, label="own PPG")
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
    ax.legend(loc="lower right", frameon=False, fontsize=8)
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


