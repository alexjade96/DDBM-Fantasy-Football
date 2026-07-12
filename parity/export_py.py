"""Export a canonical JSON of metrics for a league (Python implementation).

Run from repo base via the python venv:
    python/venv/Scripts/python parity/export_py.py <league_id> parity/out_py.json

The R exporter (parity/export_r.R) emits the identical structure so verify.py
can assert the two implementations mirror each other.
"""
import json
import sys

sys.path.insert(0, "python")  # import the python-instance package
import pandas as pd  # noqa: E402
import sleepermetrics as sm  # noqa: E402
from sleepermetrics import metrics, summaries, weekly  # noqa: E402


def recs(df, cols):
    """Round numerics to 2dp and return JSON-native records (via pandas)."""
    d = df[cols].copy()
    for c in d.columns:
        if str(d[c].dtype) == "category":
            d[c] = d[c].astype(str)
        elif d[c].dtype.kind == "f":
            d[c] = d[c].round(2)
    return json.loads(d.to_json(orient="records"))


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else "1252770181306929152"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "parity/out_py.json"
    ss = sm.seasons(league)
    # Playoff brackets are authoritative for a season's champion (Sleeper's own
    # bracket is wrong for 2025), so career titles must be computed from them.
    ss = sm.apply_playoffs(ss, "playoffs")
    pos = sm.load_playoffs("playoffs")
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
        "position_scoring": recs(metrics.position_scoring(latest).sort_values("position"),
                                 ["position", "points", "share"]),
        "roster": recs(metrics.roster(latest).sort_values(["user_name", "position"]),
                       ["user_name", "position", "spots", "points", "avg"]),
        "starter_bench": recs(
            metrics.starter_bench(latest).sort_values(["user_name", "position", "status"]),
            ["user_name", "position", "status", "avg"]),
        "table_position": recs(
            metrics.table_position(latest).sort_values(["week", "table_position"]),
            ["week", "user_name", "table_position", "wins"]),
        "roster_counts": recs(
            metrics.roster_counts(latest).sort_values(["position", "status"]),
            ["position", "status", "avg_count"]),
        "trade_performance": recs(
            metrics.trade_performance(latest).sort_values(["player_name", "user_name"]),
            ["player_name", "user_name", "weeks", "points", "avg", "total"]),
        "waiver_performance": recs(
            metrics.waiver_performance(latest).sort_values(["player_name", "user_name"]),
            ["player_name", "user_name", "weeks", "points", "avg", "total"]),
        "playoff_stats": recs(
            sm.playoff_stats(pos).sort_values("user_name"),
            ["user_name", "appearances", "games", "wins", "losses",
             "titles", "finals", "win_pct", "ppg"]),
        "playoff_champions": recs(
            pd.DataFrame({"season": list(pos),
                          "champion": [p.champion for p in pos.values()]})
            .sort_values("season"), ["season", "champion"]),
        "summary_season": summaries.summary_season(latest),
        "summary_career": summaries.summary_career(ss),
        "summary_week": weekly.summary_week(latest),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"wrote {out_path} (season {latest.season}, {len(out['standings'])} teams)")


if __name__ == "__main__":
    main()
