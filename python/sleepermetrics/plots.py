"""Charts (matplotlib; mirrors R plots.R theme + palette)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from . import metrics  # noqa: E402
from .season import Season  # noqa: E402

POS_COLORS = {"QB": "#d62728", "RB": "#2ca02c", "WR": "#1f77b4",
              "TE": "#ff7f0e", "K": "#9467bd", "DEF": "#8c564b"}


def palette(names) -> dict:
    """A stable colour per manager (matplotlib 'Paired', like R sl_palette)."""
    names = sorted(set(names))
    cmap = matplotlib.colormaps["Paired"].resampled(max(len(names), 1))
    return {n: mcolors.to_hex(cmap(i)) for i, n in enumerate(names)}


def _finish(fig, ax, title, subtitle=None, xlabel=None, ylabel=None, caption=None):
    ax.set_title(title, loc="left", fontsize=15, fontweight="bold", pad=18)
    if subtitle:
        ax.text(0, 1.015, subtitle, transform=ax.transAxes, fontsize=9,
                color="#616161", va="bottom")
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=10)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=10)
    if caption:
        fig.text(0.99, 0.01, caption, ha="right", fontsize=7, color="#8c8c8c")
    ax.grid(axis="x", color="#e8e8e8", linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    return fig


def _cap(s: Season) -> str:
    return f"Data: Sleeper API  -  {s.name} {s.season}"


def save(fig, path: str) -> str:
    fig.savefig(path, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path


def plot_standings(s: Season):
    d = s.standings.sort_values("points")
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(d["user_name"], d["points"], color=[pal[n] for n in d["user_name"]], height=0.72)
    xmax = d["points"].max()
    for y, (_, r) in enumerate(d.iterrows()):
        star = "  ★" if r["champion"] else ""
        ax.text(r["points"] + xmax * 0.01, y, f"{r['wins']}-{r['losses']}{star}",
                va="center", fontsize=9)
    ax.set_xlim(0, xmax * 1.16)
    return _finish(fig, ax, f"{s.season} Standings",
                   "Total points; record labeled, ★ = champion",
                   "Season Points", caption=_cap(s))


def plot_luck(s: Season):
    d = metrics.luck(s).sort_values("luck")
    fig, ax = plt.subplots(figsize=(9, 6))
    y = range(len(d))
    ax.hlines(y, d["exp_w"], d["wins"], color="#bfbfbf", linewidth=2, zorder=1)
    ax.scatter(d["exp_w"], y, color="#8c8c8c", s=60, zorder=2, label="expected")
    colors = ["#2ca02c" if v > 0 else "#d62728" for v in d["luck"]]
    ax.scatter(d["wins"], y, color=colors, s=90, zorder=3, label="actual")
    for yi, (_, r) in enumerate(d.iterrows()):
        off = 0.15 if r["luck"] > 0 else -0.15
        ha = "left" if r["luck"] > 0 else "right"
        ax.text(r["wins"] + off, yi, f"{r['luck']:+.1f}", va="center", ha=ha,
                fontsize=8, fontweight="bold")
    ax.set_yticks(list(y))
    ax.set_yticklabels(d["user_name"])
    return _finish(fig, ax, "Luck: Actual vs All-Play Expected Wins",
                   "Grey = expected wins vs the whole league each week; colored = actual",
                   "Wins", caption=_cap(s))


def plot_efficiency(s: Season):
    d = metrics.efficiency(s).sort_values("eff")
    fig, ax = plt.subplots(figsize=(9, 6))
    cmap = matplotlib.colormaps["RdYlGn"]
    norm = mcolors.Normalize(vmin=70, vmax=100)
    ax.barh(d["user_name"], d["eff"], color=[cmap(norm(v)) for v in d["eff"]], height=0.72)
    for y, (_, r) in enumerate(d.iterrows()):
        ax.text(r["eff"] + 0.5, y, f"{r['eff']:.1f}%  ({round(r['bench'])} pts benched)",
                va="center", fontsize=8)
    ax.set_xlim(0, 100)
    return _finish(fig, ax, "Lineup Efficiency (Coaching)",
                   "Started points as % of the optimal lineup each week",
                   "Efficiency %", caption=_cap(s))


def plot_career(seasons: dict):
    d = metrics.career(seasons).sort_values("win_pct")
    pal = palette(d["user_name"])
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.barh(d["user_name"], d["win_pct"], color=[pal[n] for n in d["user_name"]], height=0.72)
    for y, (_, r) in enumerate(d.iterrows()):
        stars = "★" * int(r["titles"])
        ax.text(r["win_pct"] + 1, y, f"{r['record']}  {r['win_pct']}%  {stars}",
                va="center", fontsize=8)
    ax.set_xlim(0, 100)
    return _finish(fig, ax, "Career Standings (All Seasons)",
                   "Ranked by win %; ★ = title", "Career Win %")
