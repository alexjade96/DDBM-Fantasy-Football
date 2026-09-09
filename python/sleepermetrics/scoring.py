"""League scoring rules -> player points (mirrors R scoring.R).

Sleeper stores each league's "point calculation chart" as `scoring_settings`
(stat key -> weight). Applying it to the raw weekly stat lines reproduces
Sleeper's own player points exactly, which lets us score ANY lineup -- including
one a commissioner collected by hand that Sleeper never had on a roster.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from .api import sleeper_api

_stats_cache: dict = {}
_chart_cache: dict = {}
_default_rules_cache: dict = {}

# season/ root (same override every other season/ consumer honours).
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_DEFAULT_SCORING_FILE = _SEASON_DIR / "scoring" / "default_scoring.json"

#: the format ids `default_scoring.json` carries, and what a bad ask falls to.
DEFAULT_SCORING_FORMATS = ("std", "half_ppr", "ppr", "2qb")
_DEFAULT_SCORING_FALLBACK = "ppr"


def scoring_chart(league_id: str) -> pd.DataFrame:
    """The league's point-calculation chart: one row per stat rule (cached --
    a league's scoring_settings don't change mid-season, and this was being
    re-fetched over the network on every call: `rules_from` is called from
    several places per report render, and the position-rank helpers alone
    call it twice more, which made an uncached fetch a real, measured
    slowdown -- not just theoretical waste)."""
    if league_id not in _chart_cache:
        sc = sleeper_api(f"/league/{league_id}")["scoring_settings"]
        _chart_cache[league_id] = (
            pd.DataFrame({"stat": list(sc), "weight": [float(v) for v in sc.values()]})
            .sort_values("stat").reset_index(drop=True))
    return _chart_cache[league_id]


def nfl_stats(season: str, week: int) -> dict:
    """Raw NFL stat lines for one week: {player_id: {stat: value}} (cached)."""
    key = (str(season), int(week))
    if key not in _stats_cache:
        _stats_cache[key] = sleeper_api(f"/stats/nfl/regular/{season}/{week}") or {}
    return _stats_cache[key]


def clear_stats_cache() -> None:
    """Drop cached stat lines. Call before re-scoring a week still in progress,
    otherwise a live playoff would keep showing stale points."""
    _stats_cache.clear()


def score_player(player_id: str, season: str, week: int, rules: dict) -> float:
    """Fantasy points for one player in one week under `rules` (stat -> weight)."""
    line = nfl_stats(season, week).get(str(player_id)) or {}
    return round(sum(v * rules[k] for k, v in line.items() if k in rules), 2)


def score_lineup(player_ids, season: str, weeks, rules: dict) -> pd.DataFrame:
    """Score a submitted lineup across one or more weeks.

    Returns one row per player x week with `points`; sum it for the team total.
    """
    rows = []
    for wk in ([weeks] if isinstance(weeks, int) else list(weeks)):
        for pid in player_ids:
            rows.append({"player_id": str(pid), "week": int(wk),
                         "points": score_player(pid, season, wk, rules)})
    return pd.DataFrame(rows, columns=["player_id", "week", "points"])


def rules_from(league_id: str) -> dict:
    """Fetch the league's scoring rules as a plain {stat: weight} dict."""
    return {r.stat: r.weight for r in scoring_chart(league_id).itertuples()}


def default_rules(fmt: str = "ppr") -> dict:
    """A canonical Sleeper DEFAULT point-calculation chart as a {stat: weight}
    dict -- same shape as `rules_from()` but needs NO league. `fmt` is one of
    `DEFAULT_SCORING_FORMATS` (std / half_ppr / ppr / 2qb); an unknown value
    falls back to ppr.

    Read from `season/scoring/default_scoring.json` (see `season/README.md`).
    Cached in-process. Returns `{}` if the file is missing or malformed.
    """
    key = (fmt or "").lower()
    if key not in DEFAULT_SCORING_FORMATS:
        key = _DEFAULT_SCORING_FALLBACK
    if key in _default_rules_cache:
        return dict(_default_rules_cache[key])
    try:
        data = json.loads(_DEFAULT_SCORING_FILE.read_text(encoding="utf-8"))
        formats = data.get("formats", {})
        chart = {k: float(v) for k, v in formats.get(key, {}).items()}
    except Exception:
        chart = {}
    _default_rules_cache[key] = chart
    return dict(chart)
