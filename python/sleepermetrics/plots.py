"""Charts (matplotlib; mirrors R plots.R theme, palette + flair)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import headshots, metrics  # noqa: E402
from .season import Season  # noqa: E402


def _portraits(ax, ids, positions, zoom=0.28, x=-0.018):
    """Hang each row's player portrait just outside the axis, beside its bar.

    Best-effort: a player with no photo (or no network) simply has no portrait
    and keeps their text label. Charts must render offline.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.transforms import blended_transform_factory
    tr = blended_transform_factory(ax.transAxes, ax.transData)  # x=axes, y=data
    for i, (pid, pos) in enumerate(zip(ids, positions)):
        img = headshots.load(pid, pos, size=72)
        if img is None:
            continue
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (x, i), xycoords=tr,
                            frameon=False, box_alignment=(1.0, 0.5),
                            pad=0, annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)

POS_COLORS = {"QB": "#d62728", "RB": "#2ca02c", "WR": "#1f77b4",
              "TE": "#ff7f0e", "K": "#9467bd", "DEF": "#8c564b"}
MEDAL = ["#f1c40f", "#c8cdd0", "#cd7f32"]  # gold, silver, bronze


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


def _row_avatars(ax, names, s, zoom=0.30, x=-0.012):
    """Hang each manager's avatar in the gap between their name and their bar.

    Mirrors the player-portrait treatment: a circular token just outside the
    axis, with the tick labels padded left to open a gap for it. Best-effort --
    a manager with no avatar (or no network) keeps their plain text label, and
    the labels are only padded when a token actually landed.
    """
    from matplotlib.offsetbox import AnnotationBbox, OffsetImage
    from matplotlib.transforms import blended_transform_factory
    urls = _avatar_map(s)
    tr = blended_transform_factory(ax.transAxes, ax.transData)  # x=axes, y=data
    placed = False
    for i, n in enumerate(names):
        img = headshots.avatar_image(urls.get(n))
        if img is None:
            continue
        ab = AnnotationBbox(OffsetImage(img, zoom=zoom), (x, i), xycoords=tr,
                            frameon=False, box_alignment=(1.0, 0.5), pad=0,
                            annotation_clip=False)
        ab.set_zorder(5)
        ax.add_artist(ab)
        placed = True
    if placed:
        ax.tick_params(axis="y", pad=34)   # open a gap wide enough for the token


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
                 color="#262626", pad=20)
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=9.5,
                color="#666666", va="bottom")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10, color="#666666")
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10, color="#666666")
    if caption:
        fig.text(0.99, 0.01, caption, ha="right", fontsize=7, color="#999999")
    ax.grid(axis=grid_axis, color="#ececec", linewidth=0.7)
    ax.set_axisbelow(True)
    ax.tick_params(colors="#4d4d4d", labelsize=9.5)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color("#cccccc")
    fig.tight_layout()
    return fig


def _cap(s: Season) -> str:
    return f"Data: Sleeper API  ·  {s.name} {s.season}"


def _medals(ax, d, rank_col, x0):
    """Podium discs (gold/silver/bronze) with rank number for top-3 rows."""
    for i, (_, r) in enumerate(d.iterrows()):
        rk = int(r[rank_col])
        if rk <= 3:
            ax.scatter([x0], [i], s=200, c=MEDAL[rk - 1], edgecolors="white",
                       linewidths=1.2, zorder=5)
            ax.text(x0, i, str(rk), ha="center", va="center", fontsize=8,
                    fontweight="bold", color="#333333", zorder=6)


def save(fig, path: str) -> str:
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
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
                va="center", fontsize=9, color="#333333")
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
    ax.axvline(100, ls="--", color="#b0b0b0", zorder=1)
    ax.text(100, len(d) - 0.4, "optimal", ha="right", va="top", fontsize=8, color="#8c8c8c")
    for i, (_, r) in enumerate(d.iterrows()):
        ax.text(r["eff"] + 0.5, i, f"{r['eff']:.1f}%  ({round(r['bench'])} pts benched)",
                va="center", fontsize=8, color="#333333")
    ax.set_xlim(0, 100)
    return _finish(fig, ax, "Lineup Efficiency (Coaching)",
                   "Started points as % of the optimal lineup each week (darker = better)",
                   "Efficiency %", caption=_cap(s))


def plot_pf_pa(s: Season):
    d = metrics.points_for_against(s)
    pal = palette(d["user_name"])
    mx, my = d["points"].median(), d["pa"].median()
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.axvline(mx, ls="--", color="#c0c0c0", zorder=1)
    ax.axhline(my, ls="--", color="#c0c0c0", zorder=1)
    sizes = 40 + (d["wins"] - d["wins"].min()) / max(d["wins"].max() - d["wins"].min(), 1) * 220
    ax.scatter(d["points"], d["pa"], s=sizes, c=[pal[n] for n in d["user_name"]],
               alpha=0.9, zorder=3, edgecolors="white", linewidths=1)
    _point_avatars(ax, d["points"], d["pa"], d["user_name"], s, zoom=0.44)
    for _, r in d.iterrows():
        ax.annotate(f"{r['user_name']} ({r['wins']}W)", (r["points"], r["pa"]),
                    textcoords="offset points", xytext=(21, 0), va="center",
                    fontsize=8, color="#404040")
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
    fill = {"helped": "#2ca02c", "hurt": "#d62728", "even": "#9aa0a6"}
    fig, ax = plt.subplots(figsize=(9.5, 6))
    colors = ["#9aa0a6" if v == 0 else ("#2ca02c" if v > 0 else "#d62728")
              for v in d["rank_delta"]]
    ax.barh(range(len(d)), d["allplay_pct"], color=colors, height=0.72, zorder=2)
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels(d["user_name"])
    _row_avatars(ax, d["user_name"], s)
    for i, (_, r) in enumerate(d.iterrows()):
        gap = "even" if r["rank_delta"] == 0 else f"{r['rank_delta']:+d}"
        ax.text(r["allplay_pct"] + 0.01, i,
                f"{r['allplay_pct'] * 100:.0f}%  ·  finished {int(r['final_position'])} ({gap})",
                va="center", fontsize=9, color="#333333")
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
    ax.axvline(0, color="#b0b0b0", zorder=3)
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
                f"{r['power']:+.2f}", va="center", ha=ha, fontsize=9, color="#404040")
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
    ax.axvline(mx, ls="--", color="#c7c7c7", zorder=1)
    ax.axhline(my, ls="--", color="#c7c7c7", zorder=1)
    tmax = max(d["trades"].max(), 1)
    sizes = 60 + d["trades"] / tmax * 300
    ax.scatter(d["moves_per_wk"], d["lineup_iq"], s=sizes,
               c=[pal[n] for n in d["user_name"]], alpha=0.85, zorder=3,
               edgecolors="white", linewidths=1)
    # Avatar as each manager's marker (dot shows through where none loads).
    _point_avatars(ax, d["moves_per_wk"], d["lineup_iq"], d["user_name"], s, zoom=0.46)
    for _, r in d.iterrows():
        ax.annotate(r["user_name"], (r["moves_per_wk"], r["lineup_iq"]),
                    textcoords="offset points", xytext=(22, 0), va="center",
                    fontsize=8, color="#404040")
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
                    showfliers=False, medianprops=dict(color="#555555"))
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
                va="center", fontsize=8, color="#333333")
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
                   color=pal[nm], s=180, zorder=4, edgecolors="white", linewidths=0.5)
        last = g.loc[g["season_int"].idxmax()]
        ax.text(last["season_int"] + 0.08, last["final_position"], nm, va="center",
                fontsize=8, color=pal[nm])
    ax.set_ylim(mp + 0.5, 0.5)
    ax.set_yticks(range(1, mp + 1))
    ax.set_xticks(sorted(d["season_int"].unique()))
    ax.text(d["season_int"].min(), 1, " podium", va="center", fontsize=8, color="#999999")
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
                va="center", fontsize=9, color="#333333")
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
    ax.tick_params(length=0, colors="#4d4d4d", labelsize=9.5)
    fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02, label="Avg pts")
    ax.set_title("Roster Construction", loc="left", fontsize=16, fontweight="bold",
                 color="#262626", pad=24)
    ax.text(0, 1.06, "Player-weeks rostered and average points, by team and position",
            transform=ax.transAxes, fontsize=9.5, color="#666666")
    fig.text(0.99, 0.01, _cap(s), ha="right", fontsize=7, color="#999999")
    fig.tight_layout()
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
        ax.barh([y - 0.2 for y in yy], bn.values, height=0.38, color="#c3c9d0", label="Bench")
        ax.set_title(p, fontsize=12, fontweight="bold", color="#404040")
        ax.grid(axis="x", color="#ececec", linewidth=0.7)
        ax.set_axisbelow(True)
        ax.tick_params(length=0, colors="#4d4d4d", labelsize=9)
        for sp in ("top", "right", "left"):
            ax.spines[sp].set_visible(False)
        ax.spines["bottom"].set_color("#cccccc")
    axes[0].set_yticks(yy)
    axes[0].set_yticklabels(users)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper right", frameon=False, fontsize=9,
               bbox_to_anchor=(0.99, 1.0))
    fig.suptitle("Starters vs Bench   ", x=0.01, ha="left", fontsize=16,
                 fontweight="bold", color="#262626")
    fig.text(0.01, 0.945, "Average points by position  ·  are the right players in the lineup?",
             fontsize=9.5, color="#666666")
    fig.text(0.99, 0.005, _cap(s), ha="right", fontsize=7, color="#999999")
    fig.tight_layout(rect=[0, 0.01, 1, 0.93])
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
                edgecolor="white", linewidth=0.3)
        left += vals
    for i, nm in enumerate(order):
        t = tot.loc[tot["user_name"] == nm, "points"].iloc[0]
        ax.text(t * 1.01, i, f"{round(t)}", va="center", fontsize=8.5,
                fontweight="bold", color="#404040")
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
               patch_artist=True, boxprops=dict(facecolor="#ececec", color="#8c8c8c"),
               medianprops=dict(color="#555555"), whiskerprops=dict(color="#8c8c8c"),
               capprops=dict(color="#8c8c8c"))
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
    ax.bar(list(x), bench, width=0.7, bottom=start, color="#c3c9d0", label="Bench")
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
                color=pal[nm], edgecolor="white", linewidth=0.3, label=nm)
        for p in players:
            if row[p] >= span * 0.06:
                ax.text(left[p] + row[p] / 2, y[p], f"{round(row[p])} ({int(wk[p])}w)",
                        ha="center", va="center", fontsize=7, color="#1a1a1a")
        left += row.values
    for p in players:
        ax.text(totals[p] + span * 0.01, y[p], f"{round(totals[p])}", va="center",
                fontsize=8, fontweight="bold", color="#4d4d4d")
    ax.set_yticks(list(y.values()))
    ax.set_yticklabels(players, fontsize=8.5)
    # One id/position per player row (a traded player appears under several
    # managers, so take the first -- it is the same player either way).
    first = d.drop_duplicates("player_name").set_index("player_name")
    _portraits(ax, first["player_id"].reindex(players),
               first["position"].reindex(players), zoom=0.28)
    ax.tick_params(axis="y", pad=34)
    ax.set_xlim(0, span * 1.12)
    ax.legend(loc="lower right", frameon=False, fontsize=8, title="Team", ncol=2)
    return _finish(fig, ax, title, subtitle, "Points While Rostered", caption=_cap(s))


# --- Playoff charts (mirror R plots.R) -------------------------------------

def plot_playoff_bracket(p):
    """Rounds left to right; winner filled, loser grey, bye amber, pending hollow."""
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
                    color="#d2d2d2", lw=1, zorder=1)
    for _, r in d.iterrows():
        ax.add_patch(plt.Rectangle((r["rx"] - 0.43, r["y"] - 0.15), 0.86, 0.30,
                                   facecolor=COL.get(r["result"], "#e6e8ea"),
                                   edgecolor="white", lw=1.2, zorder=2))
        sd = seed_of.get(r["team"], "")
        pts = "–" if pd.isna(r["points"]) else f"{r['points']:.1f}"
        ax.text(r["rx"], r["y"], f"{sd}  {r['team']}   {pts}".strip(), ha="center",
                va="center", fontsize=9, zorder=3,
                fontweight="bold" if r["result"] == "W" else "normal", color="#262626")
    ax.set_xlim(-0.6, len(rounds) - 0.4)
    ax.set_ylim(span + 0.25, -0.25)
    ax.set_xticks(range(len(rounds)))
    ax.set_xticklabels(list(dict.fromkeys(d["round"])), fontweight="bold")
    ax.xaxis.set_ticks_position("top")
    ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.tick_params(length=0, colors="#4d4d4d")
    ax.set_title(f"{p.name} · {p.season} Bracket", loc="left", fontsize=16,
                 fontweight="bold", color="#262626", pad=26)
    ax.text(0, 1.02, f"Champion: {p.champion or 'undecided'}  ·  every score computed "
            "from the submitted lineups under the league's own scoring chart",
            transform=ax.transAxes, fontsize=9.5, color="#666666", va="bottom")
    fig.tight_layout()
    return fig


def plot_playoff_stats(playoffs: dict, scope: str = "title"):
    """Career playoff win %, gold for managers with a title."""
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
                f"{r['win_pct']:.0f}%  {stars}", va="center", fontsize=8.5, color="#333333")
    ax.set_xlim(0, 100)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    return _finish(fig, ax, "Career Playoff Record",
                   f"Win % across {len(playoffs)} postseasons  ·  {sub}  ·  "
                   "gold = has won a title  ·  ★ per title", "Playoff Win %")


def plot_playoff_players(playoffs: dict, n: int = 15, scope: str = "title"):
    """Career playoff scoring leaders -- who actually produces in January."""
    from .playoffs import playoff_players
    d = playoff_players(playoffs, scope).head(n).iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.barh(range(len(d)), d["points"], height=0.72,
            color=[POS_COLORS.get(str(p), "#999999") for p in d["position"]])
    ax.set_yticks(range(len(d)))
    ax.set_yticklabels([f"{n}  ·  {p}" for n, p in zip(d["player_name"], d["position"])],
                       fontsize=8.5)
    # Portraits sit between the labels and the bars, so pad the labels out.
    _portraits(ax, d["player_id"], d["position"])
    ax.tick_params(axis="y", pad=36)
    xmax = float(d["points"].max())
    for i, r in d.iterrows():
        rings = "★" * int(r["rings"])
        ax.text(r["points"] + xmax * 0.01, i,
                f"{r['points']:.0f}  ({r['ppg']:.1f} ppg)  {rings}",
                va="center", fontsize=8.5, color="#333333")
    ax.set_xlim(0, xmax * 1.34)
    sub = "championship path only" if scope == "title" else f"scope: {scope}"
    seen = [p for p in POSITIONS if p in set(d["position"])]
    handles = [plt.Rectangle((0, 0), 1, 1, color=POS_COLORS[p]) for p in seen]
    ax.legend(handles, seen, loc="lower right", frameon=False, fontsize=8, ncol=3)
    return _finish(fig, ax, "Best Playoff Players (All Time)",
                   f"Total points scored in the postseason  ·  {sub}  ·  ★ per title",
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
    return _finish(fig, ax, "Clutch: Playoff vs Regular-Season Scoring",
                   "Grey dot = regular-season PPG; coloured = playoff PPG",
                   "Points per Game")


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
                fontsize=8, color="#404040")
    ax.axvline(0, color="#b0b0b0", lw=1)
    ax.set_yticks(range(len(g)))
    ax.set_yticklabels(g["lbl"], fontsize=8.5)
    _portraits(ax, g["player_id"], g["position"], zoom=0.20, x=-0.008)
    ax.tick_params(axis="y", pad=30)
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
