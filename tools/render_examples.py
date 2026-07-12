#!/usr/bin/env python
"""Regenerate every analytics graphic + summary from the Python package.

    python/venv/Scripts/python tools/render_examples.py [league_id]

Champions come from the stored playoff brackets (see playoffs/README.md), not
Sleeper's winners_bracket -- so crowns, titles and champion stars are correct.
Output: results/examples/py/ (gitignored build artifacts).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, "python")

import sleepermetrics as sm  # noqa: E402
from sleepermetrics import metrics, plots, summaries, weekly  # noqa: E402

OUT = Path("results/examples/py")


def save(name, fig):
    plots.save(fig, str(OUT / f"{name}.png"))
    print(f"  {name}")


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "1252770181306929152"
    OUT.mkdir(parents=True, exist_ok=True)

    print("Loading league...")
    ss = sm.apply_playoffs(sm.seasons(league), "playoffs")
    latest = list(ss.values())[-1]
    pos = sm.load_playoffs("playoffs")

    print(f"Season charts ({latest.season})")
    for nm, fn in [
        ("standings", plots.plot_standings), ("luck", plots.plot_luck),
        ("efficiency", plots.plot_efficiency), ("consistency", plots.plot_consistency),
        ("pf_pa", plots.plot_pf_pa), ("table_position", plots.plot_table_position),
        ("team_points", plots.plot_team_points),
        ("position_scoring", plots.plot_position_scoring),
        ("roster_heatmap", plots.plot_roster_heatmap),
        ("starter_bench", plots.plot_starter_bench),
        ("position_box", plots.plot_position_box),
        ("roster_counts", plots.plot_roster_counts),
        ("trade_performance", plots.plot_trade_performance),
        ("waiver_performance", plots.plot_waiver_performance),
    ]:
        save(nm, fn(latest))

    print("Career charts")
    save("career", plots.plot_career(ss))
    save("trajectory", plots.plot_trajectory(ss))

    print("Playoff charts")
    for s, p in pos.items():
        save(f"bracket_{s}", plots.plot_playoff_bracket(p))
    save("playoff_stats", plots.plot_playoff_stats(pos))
    fin = list(pos.values())[-1]
    save("playoff_final", plots.plot_playoff_matchup(fin, fin.config["final"]))

    print("Summaries + metric tables")
    (OUT / "summaries.md").write_text(
        summaries.summary_season(latest) + "\n\n" + summaries.summary_career(ss),
        encoding="utf-8")
    sm.playoff_stats(pos).to_csv(OUT / "playoff_stats.csv", index=False)
    metrics.career(ss).to_csv(OUT / "career.csv", index=False)
    print("  summaries.md, playoff_stats.csv, career.csv")

    print("\nchampions (from the brackets):")
    for s, p in pos.items():
        print(f"  {s}: {p.champion}")
    print(f"\nDone -> {OUT}")


if __name__ == "__main__":
    main()
