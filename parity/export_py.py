"""Export a canonical JSON of metrics for a league (Python implementation).

Run from repo base via the python venv:
    python/venv/Scripts/python parity/export_py.py <league_id> parity/out_py.json

The R exporter (parity/export_r.R) emits the identical structure so verify.py
can assert the two implementations mirror each other.
"""
import json
import sys

sys.path.insert(0, "python")  # import the python-instance package
import sleepermetrics as sm  # noqa: E402
from sleepermetrics import metrics, summaries, weekly  # noqa: E402


def recs(df, cols):
    """Round numerics to 2dp and return JSON-native records (via pandas)."""
    d = df[cols].copy()
    for c in d.columns:
        if d[c].dtype.kind == "f":
            d[c] = d[c].round(2)
    return json.loads(d.to_json(orient="records"))


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "1252770181306929152"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "parity/out_py.json"
    ss = sm.seasons(league)
    latest = list(ss.values())[-1]

    out = {
        "impl": "python",
        "league": league,
        "season": latest.season,
        "standings": recs(metrics.standings(latest).sort_values("final_position"),
                          ["user_name", "wins", "losses", "points", "final_position", "champion"]),
        "luck": recs(metrics.luck(latest).sort_values("user_name"),
                     ["user_name", "wins", "exp_w", "luck"]),
        "efficiency": recs(metrics.efficiency(latest).sort_values("user_name"),
                           ["user_name", "eff", "bench"]),
        "consistency": recs(metrics.consistency(latest).sort_values("user_name"),
                            ["user_name", "sd"]),
        "high_scores": recs(metrics.high_scores(latest).sort_values("user_name"),
                            ["user_name", "highs"]),
        "week_stats": recs(metrics.week_stats(latest).sort_values("user_name"),
                           ["user_name", "points", "margin"]),
        "career": recs(metrics.career(ss).sort_values("user_name"),
                       ["user_name", "seasons", "wins", "losses", "win_pct", "titles"]),
        "summary_season": summaries.summary_season(latest),
        "summary_career": summaries.summary_career(ss),
        "summary_week": weekly.summary_week(latest),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"wrote {out_path} (season {latest.season}, {len(out['standings'])} teams)")


if __name__ == "__main__":
    main()
