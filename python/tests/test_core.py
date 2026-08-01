import os

import pandas as pd
import pytest

from sleepermetrics import metrics, plots, summaries
from sleepermetrics.discord_bot import _render_command
from sleepermetrics.league import starter_slots
from sleepermetrics.season import optimal_points
from sleepermetrics.weekly import summary_week

from conftest import make_season


def test_boom_bust_has_avg_and_spread():
    d = metrics.boom_bust(make_season())
    assert set(["user_name", "avg", "sd", "floor", "ceiling"]).issubset(d.columns)
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["avg"] == 115.0                      # mean(100, 130)
    assert al["ceiling"] == 130.0 and al["floor"] == 100.0


def test_strength_of_schedule_uses_opponent_ppg():
    d = metrics.strength_of_schedule(make_season())
    # Al faced Bo both weeks; Bo's season PPG = mean(90, 70) = 80.
    assert d[d["user_name"] == "Al"].iloc[0]["sos"] == 80.0
    assert list(d["rank"]) == sorted(d["rank"])


def test_schedule_swap_diagonal_is_the_real_record():
    d = metrics.schedule_swap(make_season())
    # Al under Al's own schedule = the real record: beat Bo twice.
    al = d[(d["team"] == "Al") & (d["schedule_of"] == "Al")].iloc[0]
    assert al["wins"] == 2 and al["losses"] == 0
    # Al under Cy's schedule: Cy had no opponent, so no games are counted.
    alcy = d[(d["team"] == "Al") & (d["schedule_of"] == "Cy")].iloc[0]
    assert alcy["wins"] == 0 and alcy["losses"] == 0


def test_head_to_head_is_symmetric_and_named():
    d = metrics.head_to_head({"2025": make_season()})
    ab = d[(d["user_name"] == "Al") & (d["opp_name"] == "Bo")].iloc[0]
    ba = d[(d["user_name"] == "Bo") & (d["opp_name"] == "Al")].iloc[0]
    assert ab["wins"] == 2 and ab["losses"] == 0    # Al beat Bo twice
    assert ba["wins"] == 0 and ba["losses"] == 2    # ...and the mirror


def test_record_book_reports_superlatives():
    recs = metrics.record_book({"2025": make_season()})
    labels = {r["label"]: r for r in recs}
    assert labels["Highest score"]["holder"] == "Al"       # 130 in wk2
    assert labels["Highest score"]["value"] == "130.0"


def test_undrafted_standouts_excludes_drafted_and_ranks_by_started_points(monkeypatch):
    """The best players who went undrafted, ranked by roster-accumulated points
    -- drafted players are excluded, and a churned pickup is attributed to
    whoever got the most out of him. Seeds a fake draft board so 'undrafted' is
    well defined."""
    import dataclasses

    import pandas as pd
    from sleepermetrics import draft, metrics as _metrics
    # undrafted_standouts also computes true-season total/pos_rank via
    # metrics.season_position_ranks, which prices every real NFL stat line --
    # a real network call this fixture's fake league_id can't serve. Not what
    # this test is checking, so stub it out rather than pull in the whole
    # scoring/players mocking chain test_playoffs.py uses for that.
    monkeypatch.setattr(_metrics, "season_position_ranks", lambda s: {})
    s = make_season()
    # A populated pl_wk: pDraft was drafted; pFA and pStash were not.
    pl = pd.DataFrame({
        "week":       [1, 1, 2, 2, 1, 2],
        "roster_id":  [1, 2, 1, 3, 2, 2],
        "player_id":  ["pDraft", "pFA", "pDraft", "pFA", "pStash", "pStash"],
        "points":     [30.0, 25.0, 20.0, 40.0, 5.0, 3.0],
        "is_starter": [True, True, True, True, True, True],
        "player_name": ["Drafted Guy", "Waiver Ace", "Drafted Guy",
                        "Waiver Ace", "Deep Stash", "Deep Stash"],
        "position":   ["RB", "WR", "RB", "WR", "TE", "TE"],
    })
    s = dataclasses.replace(s, pl_wk=pl)
    # Seed the draft cache so pDraft is the only drafted player.
    board = pd.DataFrame([{c: None for c in draft._COLS}])
    board.loc[0, ["player_id", "pick_no", "round"]] = ["pDraft", 1, 1]
    draft._cache[f"{s.league_id}:{s.season}"] = board

    out = draft.undrafted_standouts(s)
    names = list(out["player_name"])
    assert "Drafted Guy" not in names            # drafted -> excluded
    assert names[0] == "Waiver Ace"              # 25+40 = 65, ranks first
    ace = out.iloc[0]
    assert ace["points"] == 65.0 and ace["teams"] == 2   # started for rosters 2 and 3
    assert ace["user_name"] == "Cy"              # roster 3 got 40 > roster 2's 25
    draft._cache.clear()


def test_validate_config_catches_structural_errors():
    """A custom bracket must be checked before it's scored: missing rounds,
    duplicate ids, and unresolved W:/final references are hard errors; a
    league-id mismatch is a soft warning. Kept roster_positions out so the
    lineup slot-check (which needs the player DB) doesn't run offline."""
    from sleepermetrics import validate_config

    good = {"season": "2026", "league_id": "0", "rounds": [
        {"id": "R1", "weeks": [15], "matchups": [
            {"id": "R1M1", "home": {"team": "A", "starters": []},
             "away": {"team": "B", "starters": []}},
            {"id": "R1B1", "bye": "C"}]},
        {"id": "R2", "weeks": [16], "matchups": [
            {"id": "R2M1", "home": {"team": "W:R1M1", "starters": []},
             "away": {"team": "W:R1B1", "starters": []}}]}],
        "final": "R2M1"}
    assert validate_config(good, league_id="0")["errors"] == []

    assert "missing or empty 'rounds'" in validate_config({"season": "2026"})["errors"]

    bad = {"season": "2026", "final": "NOPE", "rounds": [
        {"id": "R1", "weeks": [15], "matchups": [
            {"id": "M1", "home": {"team": "A", "starters": []},
             "away": {"team": "W:GHOST", "starters": []}},
            {"id": "M1", "bye": "B"}]}]}   # duplicate id
    errs = validate_config(bad)["errors"]
    assert any("duplicate matchup id 'M1'" in e for e in errs)
    assert any("unknown matchup 'GHOST'" in e for e in errs)
    assert any("unknown matchup 'NOPE'" in e for e in errs)

    warns = validate_config(good, league_id="999")["warnings"]
    assert any("!= current league 999" in w for w in warns)


def test_bracket_token_is_stable_and_content_addressed():
    """The webapp keys an ad-hoc bracket by a hash of its config, so identical
    brackets share a token and an unknown token resolves to nothing."""
    from webapp.app import _bracket_from_token, _bracket_token
    cfg = {"season": "2026", "rounds": [{"id": "R1", "weeks": [15], "matchups": []}]}
    assert _bracket_token(cfg) == _bracket_token(dict(cfg))          # order-independent
    assert _bracket_token(cfg) != _bracket_token({**cfg, "season": "2025"})
    assert _bracket_from_token("deadbeef") is None                  # unknown token


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


def test_allplay(season_obj):
    d = metrics.allplay(season_obj)
    assert set(["user_name", "allplay_pct", "allplay_rank", "rank_delta"]).issubset(d.columns)
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["allplay_pct"] == 1.0 and al["allplay_rank"] == 1
    # rank_delta is the gap between all-play rank and actual finish.
    assert (d["rank_delta"] == d["allplay_rank"] - d["final_position"]).all()


def test_power_rank(season_obj):
    d = metrics.power_rank(season_obj)
    assert list(d.columns) == ["user_name", "points", "allplay_pct", "form",
                               "eff", "power", "power_rank"]
    assert d.loc[d["power_rank"] == 1, "user_name"].iloc[0] == "Al"   # best team
    assert abs(d["power"].sum()) < 1e-9                               # z-scores centre at 0


def test_manager_profile(season_obj):
    d = metrics.manager_profile(season_obj)
    # No transactions in the fixture -> all move counts zero, lineup IQ from lineup.
    assert (d[["moves", "trades", "drops"]].sum().sum()) == 0
    al = d[d["user_name"] == "Al"].iloc[0]
    assert al["lineup_iq"] == pytest.approx((100 / 110 + 130 / 140) / 2 * 100)


def test_season_report_is_self_contained_html(tmp_path, season_obj):
    from sleepermetrics import season_report
    out = tmp_path / "report.html"
    season_report(season_obj, str(out))
    doc = out.read_text(encoding="utf-8")
    assert doc.lower().startswith("<!doctype html>")
    assert "Test League" in doc
    assert "class='tile'" in doc                      # KPI tiles rendered
    assert doc.count("<td class='rank'>") == 3        # one row per team
    assert "data:image/png" in doc                    # >=1 chart embedded inline
    # Self-contained: no external assets to fetch (charts are data URIs).
    assert 'src="http' not in doc and "<script" not in doc


def test_season_report_scopes_to_one_manager(tmp_path, season_obj):
    from sleepermetrics import season_report
    out = tmp_path / "mgr.html"
    season_report(season_obj, str(out), seasons={"2025": season_obj}, manager="Al")
    doc = out.read_text(encoding="utf-8")
    assert "Manager Report" in doc              # header reframed for the manager
    assert "class='me'" in doc                  # the manager's row is highlighted
    assert "wins vs merit" in doc               # manager-scoped narrative
    # An unknown manager falls back to the whole-league report, not an error.
    out2 = tmp_path / "unknown.html"
    season_report(season_obj, str(out2), manager="Nobody")
    assert "Manager Report" not in out2.read_text(encoding="utf-8")


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


def test_season_metrics_and_charts_adapt_to_a_mid_season_week_cap(season_obj):
    """A mid-season run has its frames capped at the current week, so every
    season-so-far metric/chart must reflect only the scored weeks -- nothing may
    assume a full 14/17-week slate. Truncating the fixture to week 1 must leave
    strictly week-1 data, and the frame-derived charts must still render."""
    import dataclasses

    import matplotlib.pyplot as plt
    mid = dataclasses.replace(
        season_obj, last_week=1,
        team_wk=season_obj.team_wk[season_obj.team_wk["week"] == 1].copy(),
        lineup=season_obj.lineup[season_obj.lineup["week"] == 1].copy(),
    )
    assert mid.current_week == 1
    tp = metrics.table_position(mid)
    assert (tp["week"] == 1).all() and len(tp) == 3   # 3 teams, week 1 only
    # No minimum-week assumption: charts built from team_wk render on one week.
    for fn in (plots.plot_table_position, plots.plot_team_points):
        fig = fn(mid)
        assert fig is not None
        plt.close(fig)


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


# --- player portraits -------------------------------------------------------
def test_headshot_url_uses_the_team_logo_for_a_team_defense():
    from sleepermetrics.headshots import headshot_url
    assert headshot_url("4034") == "https://sleepercdn.com/content/nfl/players/4034.jpg"
    # A team defense has no face -- its "player_id" IS its team.
    assert headshot_url("SF", "DEF") == "https://sleepercdn.com/images/team_logos/nfl/sf.png"
    assert headshot_url("NE") == "https://sleepercdn.com/images/team_logos/nfl/ne.png"


def test_portraits_are_off_and_degrade_to_none_when_disabled(monkeypatch):
    from sleepermetrics import headshots
    monkeypatch.setenv("SLEEPERMETRICS_NO_IMAGES", "1")
    assert headshots.disabled()
    # Charts must render offline: no image is a None, never an exception.
    assert headshots.headshot("4034") is None
    assert headshots.load("4034") is None


def test_a_player_with_no_photo_is_remembered_as_a_miss(monkeypatch):
    """Sleeper answers 403 + text/html (not 404) for a player with no photo, so
    status alone is not enough -- and 20 dead players must not mean 20 retries."""
    from sleepermetrics import headshots
    monkeypatch.delenv("SLEEPERMETRICS_NO_IMAGES", raising=False)
    headshots.clear_cache()
    calls = []

    class Resp:
        status_code = 403
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html>nope</html>"

    def fake_get(url, timeout=None):
        calls.append(url)
        return Resp()

    monkeypatch.setattr("requests.get", fake_get)
    assert headshots.headshot("99999999") is None
    assert headshots.headshot("99999999") is None      # asked twice...
    assert len(calls) == 1                             # ...fetched once
