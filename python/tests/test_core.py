import os

import pandas as pd

from sleepermetrics import metrics, plots, summaries
from sleepermetrics.discord_bot import _render_command
from sleepermetrics.league import starter_slots
from sleepermetrics.season import optimal_points
from sleepermetrics.weekly import summary_week

from conftest import make_season


def test_starter_slots():
    rp = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"]
    s = starter_slots(rp)
    assert s["QB"] == 1 and s["RB"] == 2 and s["FLEX"] == 1
    assert "BN" not in s


def test_optimal_points_with_flex():
    df = pd.DataFrame({
        "player_id": [str(i) for i in range(1, 9)],
        "position": ["QB", "RB", "RB", "RB", "WR", "WR", "TE", "K"],
        "points":   [20, 15, 12, 30, 10, 8, 5, 7],
    })
    slots = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "FLEX": 1}
    # QB20 + RB(30,15) + WR(10,8) + TE5 + K7 + FLEX(best leftover = RB12) = 107
    assert optimal_points(df, slots) == 107


def test_luck_and_efficiency(season_obj):
    lk = metrics.luck(season_obj)
    assert set(["user_name", "wins", "exp_w", "luck"]).issubset(lk.columns)
    eff = metrics.efficiency(season_obj)
    cy = eff.loc[eff["user_name"] == "Cy", "eff"].iloc[0]
    assert cy == round(200 / 240 * 100, 1)


def test_week_stats(season_obj):
    d = metrics.week_stats(season_obj, 2)
    assert len(d) == 3
    assert (d["week"] == 2).all()
    assert d.iloc[0]["user_name"] == "Al"  # top scorer week 2


def test_table_position(season_obj):
    d = metrics.table_position(season_obj)
    assert len(d) == 6  # 3 teams x 2 weeks
    wk2 = d[d["week"] == 2]
    assert wk2.loc[wk2["table_position"] == 1, "user_name"].iloc[0] == "Al"  # 2-0
    assert wk2.loc[wk2["table_position"] == 3, "user_name"].iloc[0] == "Bo"  # 0-2
    assert list(wk2["table_position"]) == [1, 2, 3]


def test_summary_week(season_obj):
    txt = summary_week(season_obj, 2)
    assert "Week 2 recap" in txt and "Top score" in txt


def test_summary_season(season_obj):
    txt = summaries.summary_season(season_obj)
    assert isinstance(txt, str) and "what the numbers say" in txt


def test_summary_career_ties():
    ss = {"2024": make_season("2024", champ_roster=1),
          "2025": make_season("2025", champ_roster=3)}  # two different champs -> tie
    txt = summaries.summary_career(ss)
    assert isinstance(txt, str) and "Most titles" in txt
    ct = metrics.career(ss)
    assert len(ct) == 3 and ct["titles"].max() == 1


def test_render_command_routes_and_renders(tmp_path, season_obj, monkeypatch):
    # text-only command (no fetch)
    content, path = _render_command("help", "x", out_dir=str(tmp_path))
    assert "Commands" in content and path is None
    # chart command: patch season() to avoid network
    import sleepermetrics.discord_bot as db
    monkeypatch.setattr(db, "season", lambda lid: season_obj)
    content, path = db._render_command("standings", "x", out_dir=str(tmp_path))
    assert path and os.path.exists(path)
    content, _ = db._render_command("weekly", "x", out_dir=str(tmp_path))
    assert "recap" in content


def test_plot_standings_renders(tmp_path, season_obj):
    p = plots.save(plots.plot_standings(season_obj), str(tmp_path / "s.png"))
    assert os.path.exists(p)
