"""End-of-season value rank for the ADP Comparison board.

Each player's "Final" is their overall end-of-season rank (1 = the year's
top scorer) among ALL players, priced from raw NFL stat lines times a
canonical Sleeper DEFAULT scoring chart (`sleepermetrics.scoring.default_rules`,
backed by `season/scoring/default_scoring.json`). This is league-free -- the
ADP tab has no `Season` -- so it uses the default chart, one per scoring
format, not any league's own `scoring_settings`.

`ffadp.board.combine()` joins this onto each row by Sleeper `player_id` and
adds `final` plus `diff` (`consensus - final`: positive = the field drafted
the player later than they finished, i.e. a value; negative = a reach).

Storage mirrors the rest of `ffadp`: one committed JSON snapshot per
`(season, format)` under `season/adp/finish/<season>-<fmt>.json`, the durable
offline fallback. A snapshot is only written for a season whose weeks are all
in (`nfl_state` season past the requested one); an in-progress season is
computed live and returned but not persisted.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from sleepermetrics import scoring
from sleepermetrics.league import nfl_state
from sleepermetrics.players import players

# Fantasy positions we rank (a stat-line row for anyone else -- an OL, a
# long-snapper -- is dropped, same as metrics._position_totals).
_FANTASY_POS = {"QB", "RB", "WR", "TE", "K", "DEF"}

# Weeks to sweep. 1..18 covers the full NFL regular season across every
# season this project sees; a week with no stat lines is simply skipped.
_WEEKS = range(1, 19)

_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_FINISH_DIR = _SEASON_DIR / "adp" / "finish"

_mem: dict[str, dict] = {}     # f"{season}:{fmt}" -> {sleeper_id: final_rank}


def _snap_path(season: str, fmt: str) -> Path:
    return _FINISH_DIR / f"{season}-{fmt}.json"


def _season_complete(season: str) -> bool:
    """True once the NFL has moved past `season` -- safe to snapshot then."""
    try:
        cur = int(str((nfl_state() or {}).get("league_season")
                       or (nfl_state() or {}).get("season") or "0"))
        return cur > int(str(season))
    except Exception:
        return False


def _compute(season: str, fmt: str) -> dict:
    """Price every fantasy player's stat lines for the season with the default
    `fmt` chart, sum, and rank OVERALL (all positions together). Returns
    {sleeper_id: rank}; empty when no week resolves or the chart is missing."""
    rules = scoring.default_rules(fmt)
    if not rules:
        return {}

    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))["position"].to_dict()

    totals: dict[str, float] = {}
    saw_a_week = False
    for wk in _WEEKS:
        lines = scoring.nfl_stats(str(season), wk)
        if not lines:
            continue
        saw_a_week = True
        for pid, line in lines.items():
            if pos_map.get(str(pid)) not in _FANTASY_POS:
                continue
            # a real stat line has >=1 key that's actually a scoring key;
            # Sleeper's "rostered but never played" stub has none (same guard
            # as metrics._position_totals).
            if not any(k in rules for k in line):
                continue
            pts = sum(v * rules[k] for k, v in line.items() if k in rules)
            totals[str(pid)] = totals.get(str(pid), 0.0) + pts

    if not saw_a_week or not totals:
        return {}

    ordered = sorted(totals.items(), key=lambda kv: -kv[1])
    return {pid: i for i, (pid, _pts) in enumerate(ordered, start=1)}


def season_value_ranks(season: str, scoring_fmt: str = "ppr",
                       reload: bool = False) -> dict:
    """{sleeper_id: overall end-of-season rank} for `season` in `scoring_fmt`.

    Snapshot-first: in-process cache -> `season/adp/finish/<season>-<fmt>.json`
    -> a live compute off `scoring.nfl_stats`. A completed season's live
    compute is written back to the snapshot; an in-progress season's is not
    (it would churn week to week). `reload=True` skips the caches and
    recomputes; for a completed season it also rewrites the snapshot.

    Empty dict when nothing resolves (no network + no snapshot, or a season
    with no scored weeks yet).
    """
    fmt = (scoring_fmt or "ppr").lower()
    if fmt not in scoring.DEFAULT_SCORING_FORMATS:
        fmt = "ppr"
    key = f"{season}:{fmt}"

    if not reload:
        if key in _mem:
            return dict(_mem[key])
        try:
            snap = json.loads(_snap_path(season, fmt).read_text(encoding="utf-8"))
            if isinstance(snap, dict) and snap:
                ranks = {str(k): int(v) for k, v in snap.items()}
                _mem[key] = ranks
                return dict(ranks)
        except Exception:
            pass

    ranks = _compute(str(season), fmt)
    _mem[key] = ranks
    if ranks and _season_complete(season):
        try:
            p = _snap_path(season, fmt)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(ranks, indent=2, sort_keys=True),
                         encoding="utf-8")
        except Exception:
            pass
    return dict(ranks)


def rebuild_season(season: str, formats=None) -> dict:
    """Backend-only: recompute and re-snapshot the finish ranks for `season`
    in every scoring format (or just `formats`). Not wired to any UI control;
    call it from a shell / a maintenance task when the underlying stat feed
    or the default scoring chart changes.

    Returns {fmt: n_players_ranked}.
    """
    fmts = formats or list(scoring.DEFAULT_SCORING_FORMATS)
    out: dict[str, int] = {}
    for fmt in fmts:
        ranks = season_value_ranks(season, fmt, reload=True)
        out[fmt] = len(ranks)
    return out


def clear_cache() -> None:
    _mem.clear()
