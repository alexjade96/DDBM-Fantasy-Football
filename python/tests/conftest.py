import os

import pandas as pd
import pytest

# Portraits are fetched from a CDN. The suite is network-free, so turn them off
# for every test: charts fall back to plain text labels.
os.environ["SLEEPERMETRICS_NO_IMAGES"] = "1"

from sleepermetrics.season import Season  # noqa: E402


def make_season(season="2025", champ_roster=1):
    team_wk = pd.DataFrame({
        "week":       [1, 1, 1, 2, 2, 2],
        "roster_id":  [1, 2, 3, 1, 2, 3],
        "user_id":    ["1", "2", "3", "1", "2", "3"],
        "user_name":  ["Al", "Bo", "Cy", "Al", "Bo", "Cy"],
        "matchup_id": [1, 1, None, 1, 1, None],
        # opponent roster_id (self-join in the real assembler); Cy has no game.
        "opp":        [2, 1, None, 2, 1, None],
        "points":     [100.0, 90.0, 80.0, 130.0, 70.0, 120.0],
        "pa":         [90.0, 100.0, None, 70.0, 130.0, None],
        "result":     ["W", "L", None, "W", "L", None],
        "allplay_w":  [2, 1, 0, 2, 0, 1],
        "allplay_l":  [0, 1, 2, 0, 2, 1],
        "is_high":    [True, False, False, True, False, False],
    })
    standings = pd.DataFrame({
        "roster_id": [1, 3, 2],
        "user_id":   ["1", "3", "2"],
        "user_name": ["Al", "Cy", "Bo"],
        "wins":      [2, 0, 0],
        "losses":    [0, 0, 2],
        "points":    [230.0, 200.0, 160.0],
        "pa":        [160.0, 0.0, 230.0],
        "allplay_w": [4, 1, 1],
        "allplay_l": [0, 3, 3],
        "highs":     [2, 0, 0],
        "final_position": [1, 2, 3],
        "season":    season,
    })
    standings["champion"] = standings["roster_id"] == champ_roster
    lineup = pd.DataFrame({
        "user_name":     ["Al", "Al", "Bo", "Bo", "Cy", "Cy"],
        "week":          [1, 2, 1, 2, 1, 2],
        "actual":        [100.0, 130.0, 90.0, 70.0, 80.0, 120.0],
        "optimal":       [110.0, 140.0, 100.0, 80.0, 100.0, 140.0],
        "left_on_bench": [10.0, 10.0, 10.0, 10.0, 20.0, 20.0],
    })
    user_map = pd.DataFrame({
        "roster_id": [1, 2, 3], "user_id": ["1", "2", "3"],
        "user_name": ["Al", "Bo", "Cy"]})
    # Seed the draft cache empty so the manager report's draft section never
    # reaches for the network in tests (the suite stays offline).
    from sleepermetrics import draft as _draft
    _draft._cache[f"0:{season}"] = _draft._empty()
    return Season(season, "Test League", "0", 2, {},
                  team_wk, pd.DataFrame(), lineup, standings, user_map)


@pytest.fixture
def season_obj():
    return make_season()
