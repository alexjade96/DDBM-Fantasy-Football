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


# --- per-account import: team names + icons ---------------------------------
def test_avatar_url_handles_both_sleeper_shapes():
    from sleepermetrics.season import avatar_url
    # An account avatar is a bare id and must be turned into a CDN url...
    assert avatar_url("abc") == "https://sleepercdn.com/avatars/abc"
    assert avatar_url("abc", thumb=True) == "https://sleepercdn.com/avatars/thumbs/abc"
    # ...but a custom TEAM avatar is already a url: don't double-prefix it.
    u = "https://sleepercdn.com/uploads/xyz.jpg"
    assert avatar_url(u) == u
    assert avatar_url(None) is None and avatar_url("") is None


def test_account_prefers_team_name_and_falls_back_to_display_name():
    from sleepermetrics.season import _account
    named = _account({"user_id": "1", "display_name": "Al",
                      "avatar": "a1", "metadata": {"team_name": "The Als"}})
    assert named["team"] == "The Als"
    assert named["avatar_url"].endswith("/avatars/a1")

    # No team name (and a blank one) -> show the manager's display name.
    for meta in ({}, {"team_name": "   "}):
        bare = _account({"user_id": "2", "display_name": "Bo", "metadata": meta})
        assert bare["team_name"] is None and bare["team"] == "Bo"
        assert bare["avatar_url"] is None


def test_league_accounts_keys_on_the_persistent_user_id():
    import pandas as pd
    from sleepermetrics.season import league_accounts

    def s(season, name, team, champ):
        o = type("S", (), {})()
        o.season = season
        o.accounts = pd.DataFrame([{
            "roster_id": 1, "user_id": "u1", "user_name": name,
            "team_name": team, "avatar_url": f"pic-{season}",
            "team_avatar_url": None, "team": team}])
        o.standings = pd.DataFrame({"user_name": [name],
                                    "champion": [champ]})
        return o

    # Same account, renamed between seasons: one row, not two.
    d = league_accounts({"2024": s("2024", "Old", "Old FC", True),
                         "2025": s("2025", "New", "New FC", False)})
    assert len(d) == 1
    row = d.iloc[0]
    assert row["user_name"] == "New"          # current identity wins
    assert row["avatar_url"] == "pic-2025"    # ...including the current picture
    assert row["seasons"] == 2 and row["titles"] == 1
    assert row["first_season"] == "2024" and row["last_season"] == "2025"
