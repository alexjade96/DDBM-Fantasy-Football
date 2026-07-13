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
        "playoff_players": recs(
            sm.playoff_players(pos).head(25).sort_values("player_name"),
            ["player_name", "position", "seasons", "games", "points", "ppg",
             "best", "rings"]),
        "playoff_all_stars": recs(
            sm.playoff_all_stars(pos).sort_values("position"),
            ["position", "player_name", "points", "ppg"]),
        "playoff_clutch": recs(sm.clutch(ss, pos).sort_values("user_name"),
                               ["user_name", "reg_ppg", "po_ppg", "clutch", "games"]),
        "playoff_seeding": recs(
            sm.playoff_seeding(pos, ss).sort_values("user_name"),
            ["user_name", "runs", "avg_seed", "best_seed", "upsets",
             "upset_losses", "cinderella", "chokes"]),
        "playoff_margins": recs(
            sm.playoff_margins(pos).sort_values("user_name"),
            ["user_name", "games", "avg_margin", "best_win", "worst_loss"]),
        "playoff_path": recs(sm.playoff_path(pos).sort_values("user_name"),
                             ["user_name", "games", "opp_ppg", "opp_total"]),
        "playoff_allplay": recs(
            sm.playoff_allplay(pos).sort_values("user_name"),
            ["user_name", "games", "allplay_w", "allplay_l", "allplay_pct"]),
        "playoff_carry": recs(
            sm.playoff_carry(pos).sort_values(["season", "team"]),
            ["season", "team", "points", "top_player", "top_points", "share"]),
        "playoff_replay": recs(
            sm.playoff_replay(pos, ss).sort_values(["season", "matchup_id"]),
            ["season", "matchup_id", "actual_winner", "optimal_winner", "flipped"]),
        "playoff_stats_all": recs(
            sm.playoff_stats(pos, "all").sort_values("user_name"),
            ["user_name", "games", "wins", "losses"]),
        # Exported in engine order, NOT re-sorted: the grouping and the reading
        # order within a group are part of what the dashboards render, so parity
        # should catch a divergence in either.
        "scoring_readable": sm.scoring_readable(
            (pos[latest.season].config.get("scoring_settings", {})
             if latest.season in pos else {})
        ).round(4).to_dict("records"),
        "summary_season": summaries.summary_season(latest),
        "summary_career": summaries.summary_career(ss),
        "summary_week": weekly.summary_week(latest),
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
    print(f"wrote {out_path} (season {latest.season}, {len(out['standings'])} teams)")


if __name__ == "__main__":
    main()
