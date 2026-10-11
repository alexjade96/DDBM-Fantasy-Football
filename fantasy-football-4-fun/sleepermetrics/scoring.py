"""League scoring rules -> player points (mirrors R scoring.R).

Sleeper stores each league's "point calculation chart" as `scoring_settings`
(stat key -> weight). Applying it to the raw weekly stat lines reproduces
Sleeper's own player points exactly, which lets us score ANY lineup -- including
one a commissioner collected by hand that Sleeper never had on a roster.
"""
from __future__ import annotations

import json

import pandas as pd

from repo_paths import SOURCES_DIR, on_render

from .api import sleeper_api

_stats_cache: dict = {}
_RENDER_MAX_WEEKS = 6   # cap on untrimmed weeks held in memory when on_render()
_chart_cache: dict = {}
_default_rules_cache: dict = {}

_DEFAULT_SCORING_FILE = SOURCES_DIR / "default_scoring.json"

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


def _raw_stats_path(season, week):
    """data/sources/sleeper_stats/raw/<season>/week_<week>.json.gz -- the whole
    week as Sleeper sent it (about 0.6 MB of JSON), gzip-compressed."""
    return SOURCES_DIR / "sleeper_stats" / "raw" / str(season) / f"week_{int(week)}.json.gz"


#: how long an EMPTY answer for the current season is trusted before Sleeper is
#: asked again (the week may simply not have been played yet)
_EMPTY_RECHECK_SECONDS = 6 * 3600


def _current_nfl_season() -> int:
    """The NFL season under way: the calendar year from March, else the last."""
    from datetime import date
    d = date.today()
    return d.year if d.month >= 3 else d.year - 1


def _load_raw_stats(season, week) -> dict | None:
    """The stored week, or None when Sleeper must be asked.

    A stored EMPTY week ({}) means "asked, nothing there".  For a past season
    that is final (e.g. a week 18 that season never had), so it is never asked
    again.  For the current season it is trusted for `_EMPTY_RECHECK_SECONDS`,
    since the week may just not have been played."""
    import gzip, time
    p = _raw_stats_path(season, week)
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        if data:
            return data
        try:
            past = int(season) < _current_nfl_season()
        except (TypeError, ValueError):
            past = False
        if past or time.time() - p.stat().st_mtime < _EMPTY_RECHECK_SECONDS:
            return {}
        return None
    except Exception:
        return None


def _save_raw_stats(season, week, lines: dict) -> None:
    """Keep the complete week (best-effort, atomic); an empty answer is kept as
    a marker so it is not asked for again.  Not on Render: its disk is
    discarded, and the committed raw files ship in the image instead."""
    if on_render():
        return
    import gzip, os
    try:
        p = _raw_stats_path(season, week)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=6) as f:
            json.dump(lines, f, separators=(",", ":"))
        os.replace(tmp, p)
    except Exception:
        pass


def nfl_stats(season: str, week: int, reload: bool = False) -> dict:
    """Raw NFL stat lines for one week: {player_id: {stat: value}} (cached).

    Order: memory, then the stored raw week, then Sleeper (and the complete
    answer is stored as raw).  `reload=True` skips both caches and asks
    Sleeper again, replacing the raw week.  Everything that needs a week of
    stat lines goes through here, so each week is downloaded once."""
    key = (str(season), int(week))
    if reload:
        _stats_cache.pop(key, None)
    if key not in _stats_cache:
        lines = None if reload else _load_raw_stats(season, week)
        if lines is None:
            lines = sleeper_api(f"/stats/nfl/regular/{season}/{week}") or {}
            _save_raw_stats(season, week, lines)
        _stats_cache[key] = lines
        # Render's 512MB instances: each untrimmed week is ~2.3MB held, and
        # callers sweep weeks one at a time, so keep only the most recent few.
        if on_render():
            while len(_stats_cache) > _RENDER_MAX_WEEKS:
                _stats_cache.pop(next(iter(_stats_cache)))
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

    The file stores the chart once as `base` (every rule except
    points-per-reception -- the only thing that differs between the standard
    formats) plus `rec_by_format`; this merges the two: `base` + the format's
    `rec` weight. Read from `data/sources/default_scoring.json` (see
    `data/sources/README.md`). Cached in-process. Returns `{}` if the file is
    missing or malformed.
    """
    key = (fmt or "").lower()
    if key not in DEFAULT_SCORING_FORMATS:
        key = _DEFAULT_SCORING_FALLBACK
    if key in _default_rules_cache:
        return dict(_default_rules_cache[key])
    try:
        data = json.loads(_DEFAULT_SCORING_FILE.read_text(encoding="utf-8"))
        chart = {k: float(v) for k, v in data.get("base", {}).items()}
        rec = data.get("rec_by_format", {}).get(key)
        if rec is not None:
            chart["rec"] = float(rec)
        if not chart:
            raise ValueError("empty base")
    except Exception:
        chart = {}
    _default_rules_cache[key] = chart
    return dict(chart)
