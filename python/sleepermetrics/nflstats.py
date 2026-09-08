"""Advanced player-usage stats off Sleeper's own weekly stat feed.

Sleeper's `/stats/nfl/regular/{season}/{week}` line (the one `scoring.py`
already fetches to price lineups) carries far more than fantasy points: snap
counts, targets, air yards, red-zone volume, efficiency rates. `scoring.py`
only ever reads the scoring keys out of it; this module surfaces the VOLUME
keys the rest of the app never sees.

Webapp-only, deliberately not in the parity-diffed metric contract -- it is a
new descriptive read layered on data already fetched, with no R counterpart
(same precedent as `metrics.boom_bust` / `strength_of_schedule` /
`record_book`). `verify.py` is unaffected.

Storage. A trimmed per-(season, week) snapshot lives under
`season/stats/<season>/<week>.json` -- a NEW sibling tree next to
`season/adp/`, under the SAME `SLEEPERMETRICS_SEASON_DIR` root, so all
durable season data still lives in one place. It is the offline / cold-host
fallback, same durable-JSON idea as the ADP cache: written on every
successful live fetch, read back when the network is gone. The source is
labelled `"sleeper"` throughout (`SOURCE`), so a later multi-source usage
board can tell where a row came from.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from . import scoring
from .players import players
from .season import Season

#: where every row in this module's output comes from.
SOURCE = "sleeper"

#: fantasy positions we keep a usage row for (same set as metrics.POSITIONS).
_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# The usage / volume keys we pull out of the ~85-key Sleeper line. Everything
# here is a raw count or a rate Sleeper already computed; nothing derived.
# `pts_*` are kept only so a caller can tie a trimmed snapshot back to
# `scoring.score_player` (the same self-check the playoff engine uses).
_USAGE_KEYS = (
    "gp", "gms_active",
    "off_snp", "tm_off_snp",
    "rec", "rec_tgt", "rec_yd", "rec_air_yd", "rec_rz_tgt", "rec_yar", "rec_td",
    "rush_att", "rush_yd", "rush_rz_att", "rush_yac", "rush_td",
    "pass_att", "pass_cmp", "pass_yd", "pass_air_yd", "pass_rz_att",
    "pass_td", "pass_int", "pass_rtg",
    "pts_std", "pts_half_ppr", "pts_ppr",
)

# Same durable-data root the ADP cache and the playoff configs use.
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR",
    str(Path(__file__).resolve().parents[2] / "season")))
_STATS_DIR = _SEASON_DIR / "stats"

# {(season, week): {player_id: {key: value}}} -- trimmed lines, for the life
# of the process. Separate from scoring.py's own `_stats_cache` (that one
# holds the FULL untrimmed line); this is the trimmed usage view.
_week_cache: dict = {}
# {(league_id, season, weeks_key): DataFrame} -- computed usage frames.
_usage_cache: dict = {}


def _snapshot_path(season, week) -> Path:
    return _STATS_DIR / str(season) / f"{int(week)}.json"


def _trim(lines: dict) -> dict:
    """Raw {pid: full_line} -> {pid: usage-subset line}.

    Keeps a player only if his position is a fantasy one AND his line has at
    least one usage key actually present (Sleeper emits a metadata-only stub
    -- `gms_active` / `pos_rank_*` and nothing else -- for a player who was on
    an NFL roster but never took a snap; the same shape `metrics._position_
    totals` guards against). `gp` / `gms_active` alone do not count as usage.
    """
    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))["position"]
    real = set(_USAGE_KEYS) - {"gp", "gms_active"}
    out: dict = {}
    for pid, line in (lines or {}).items():
        if not isinstance(line, dict):
            continue
        if pos_map.get(str(pid)) not in _POSITIONS:
            continue
        if not any(k in line for k in real):
            continue
        out[str(pid)] = {k: float(line[k]) for k in _USAGE_KEYS if k in line}
    return out


def raw_week(season, week, reload: bool = False) -> dict:
    """Trimmed usage lines for one week: {player_id: {key: value}}.

    Snapshot-first: the in-process cache, then
    `season/stats/<season>/<week>.json`, then a live pull via
    `scoring.nfl_stats` (which itself caches + hits the Sleeper API). A
    successful live pull rewrites the snapshot. Degrades to `{}` -- never
    raises -- when neither the network nor a snapshot is available.
    `reload=True` skips both caches and re-pulls live.
    """
    key = (str(season), int(week))
    if not reload and key in _week_cache:
        return _week_cache[key]

    path = _snapshot_path(season, week)
    if not reload:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                _week_cache[key] = rows
                return rows
        except Exception:
            pass

    try:
        trimmed = _trim(scoring.nfl_stats(str(season), int(week)))
    except Exception:
        trimmed = {}
    if trimmed:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(trimmed, indent=2, sort_keys=True),
                            encoding="utf-8")
        except Exception:
            pass
        _week_cache[key] = trimmed
        return trimmed

    # live pull produced nothing; last resort is a snapshot we skipped above
    if reload:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, dict):
                _week_cache[key] = rows
                return rows
        except Exception:
            pass
    _week_cache[key] = {}
    return {}


def _weeks_for(s: Season, weeks) -> list[int]:
    if weeks is None:
        return list(range(1, int(s.last_week) + 1))
    if isinstance(weeks, int):
        return [weeks]
    return [int(w) for w in weeks]


def player_usage(s: Season, weeks=None, reload: bool = False) -> pd.DataFrame:
    """Per-player usage over `weeks` (default: the regular season).

    One row per player who recorded usage in the window, with:
      * `games`        -- weeks with a real usage line
      * `snap_share`   -- Sigma off_snp / Sigma tm_off_snp (0..1, None if the
                          team-snap denominator is missing every week)
      * `targets` / `carries` / `pass_att` -- raw volume
      * `tgt_share`    -- this player's targets / his NFL team's targets that
                          same set of weeks (team from `players()`), 0..1
      * `rz_touches`   -- rec_rz_tgt + rush_rz_att + pass_rz_att
      * `air_yards`    -- summed rec_air_yd (or pass_air_yd for a passer)
      * `adot`         -- air_yards / targets (receivers only; None otherwise)
      * `ppg_ppr`      -- summed pts_ppr / games, so a usage row can be read
                          against production without a second call

    Cached per (league_id, season, weeks). The webapp clears it via
    `clear_cache()` on its live-refresh path (mirrors
    `scoring.clear_stats_cache()`), so a re-scored week is not served stale.
    Every row carries `source == SOURCE` ("sleeper").
    """
    wl = _weeks_for(s, weeks)
    ck = (s.league_id, str(s.season), tuple(wl))
    if not reload and ck in _usage_cache:
        return _usage_cache[ck].copy()

    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))["position"]
    team_map = pool.set_index(pool["player_id"].astype(str))["team"]

    # accumulate per player, and per (nfl_team, ) so tgt_share has a denominator
    acc: dict = {}
    team_tgt: dict = {}
    for w in wl:
        lines = raw_week(s.season, w, reload=reload)
        for pid, ln in lines.items():
            a = acc.setdefault(pid, {k: 0.0 for k in (
                "games", "off_snp", "tm_off_snp", "rec_tgt", "rush_att",
                "pass_att", "rec_air_yd", "pass_air_yd", "rec_rz_tgt",
                "rush_rz_att", "pass_rz_att", "pts_ppr")})
            a["games"] += 1
            for k in a:
                if k == "games":
                    continue
                a[k] += ln.get(k, 0.0)
            tm = team_map.get(pid)
            if tm and ln.get("rec_tgt"):
                team_tgt[tm] = team_tgt.get(tm, 0.0) + ln["rec_tgt"]

    rows = []
    for pid, a in acc.items():
        pos = pos_map.get(pid)
        tm = team_map.get(pid)
        tm_snp = a["tm_off_snp"]
        tgts = a["rec_tgt"]
        team_t = team_tgt.get(tm, 0.0)
        is_rec = pos in ("RB", "WR", "TE")
        air = a["rec_air_yd"] if is_rec else a["pass_air_yd"]
        rows.append({
            "source": SOURCE,
            "player_id": pid,
            "player_name": pool.set_index(pool["player_id"].astype(str))
                               ["player_name"].get(pid, pid),
            "position": pos,
            "team": tm,
            "games": int(a["games"]),
            "snap_share": round(a["off_snp"] / tm_snp, 3) if tm_snp else None,
            "targets": int(tgts),
            "carries": int(a["rush_att"]),
            "pass_att": int(a["pass_att"]),
            "tgt_share": round(tgts / team_t, 3) if team_t else None,
            "rz_touches": int(a["rec_rz_tgt"] + a["rush_rz_att"] + a["pass_rz_att"]),
            "air_yards": round(air, 1),
            "adot": round(a["rec_air_yd"] / tgts, 2) if (is_rec and tgts) else None,
            "ppg_ppr": round(a["pts_ppr"] / a["games"], 2) if a["games"] else 0.0,
        })
    df = (pd.DataFrame(rows, columns=[
            "source", "player_id", "player_name", "position", "team", "games",
            "snap_share", "targets", "carries", "pass_att", "tgt_share",
            "rz_touches", "air_yards", "adot", "ppg_ppr"])
          .sort_values(["ppg_ppr", "snap_share"], ascending=False)
          .reset_index(drop=True))
    _usage_cache[ck] = df
    return df.copy()


# --- league-free season leaderboard -----------------------------------------
# {(season, pos, weeks_key): DataFrame} -- computed leaderboards.
_lb_cache: dict = {}

# The (df_key, sum-or-mean, raw stat key(s)) the leaderboard aggregates.
# "sum" keys add across weeks; "rate" keys are recomputed from their own
# summed numerator/denominator (never a mean of weekly rates).
_LB_SUMS = {
    "targets": "rec_tgt", "receptions": "rec", "rec_yards": "rec_yd",
    "rec_td": "rec_td", "carries": "rush_att", "rush_yards": "rush_yd",
    "rush_td": "rush_td", "pass_att": "pass_att", "pass_cmp": "pass_cmp",
    "pass_yards": "pass_yd", "pass_td": "pass_td", "pass_int": "pass_int",
    "fpts_ppr": "pts_ppr",
}


def player_leaderboard(season, pos: str = "ALL", weeks=None, limit: int = 200,
                       reload: bool = False) -> pd.DataFrame:
    """Season-total player stats from Sleeper's own weekly feed, league-free.

    Unlike `player_usage` this needs NO `Season` -- it walks `raw_week` for
    `weeks` (default weeks 1..18), aggregates per player to season totals, and
    joins `players()` for name / position / team / **gsis_id** (the last is
    the nflverse cross-reference id, so `nflref.compare_sources` can line the
    two sources up). Ranked by PPR fantasy points.

    Columns: rank, player_id, gsis_id, player, position, team, games,
    targets, receptions, rec_yards, rec_td, carries, rush_yards, rush_td,
    pass_att, pass_cmp, pass_yards, pass_td, pass_int, snap_share, tgt_share,
    rz_touches, air_yards, adot, fpts_ppr, ppg_ppr. `source` == "sleeper" on
    every row. Empty frame when no week resolves.
    """
    wl = ([int(weeks)] if isinstance(weeks, int)
          else [int(w) for w in weeks] if weeks is not None
          else list(range(1, 19)))
    ck = (str(season), (pos or "ALL").upper(), tuple(wl))
    if not reload and ck in _lb_cache:
        cached = _lb_cache[ck]
        return cached.head(int(limit)).copy() if not cached.empty else cached.copy()

    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pool = pool.set_index(pool["player_id"].astype(str))
    pos_map = pool["position"]
    team_map = pool["team"]
    name_map = pool["player_name"]
    gsis_map = pool["gsis_id"] if "gsis_id" in pool.columns else None

    acc: dict = {}
    team_tgt: dict = {}
    extra = ("games", "off_snp", "tm_off_snp", "rec_air_yd", "pass_air_yd",
             "rec_rz_tgt", "rush_rz_att", "pass_rz_att")
    for w in wl:
        lines = raw_week(season, w, reload=reload)
        for pid, ln in lines.items():
            a = acc.setdefault(pid, {k: 0.0 for k in
                                    list(_LB_SUMS) + list(extra)})
            a["games"] += 1
            for out, src in _LB_SUMS.items():
                a[out] += ln.get(src, 0.0)
            for k in extra:
                if k != "games":
                    a[k] += ln.get(k, 0.0)
            tm = team_map.get(pid)
            if tm and ln.get("rec_tgt"):
                team_tgt[tm] = team_tgt.get(tm, 0.0) + ln["rec_tgt"]

    p = (pos or "ALL").upper()
    rows = []
    for pid, a in acc.items():
        position = pos_map.get(pid)
        if p != "ALL" and position != p:
            continue
        tm = team_map.get(pid)
        if isinstance(tm, float) and pd.isna(tm):      # NaN team -> None (Jinja)
            tm = None
        gsis = gsis_map.get(pid) if gsis_map is not None else None
        if isinstance(gsis, float) and pd.isna(gsis):
            gsis = None
        tm_snp = a["tm_off_snp"]
        tgts = a["targets"]
        team_t = team_tgt.get(tm, 0.0)
        is_rec = position in ("RB", "WR", "TE")
        air = a["rec_air_yd"] if is_rec else a["pass_air_yd"]
        row = {
            "source": SOURCE,
            "player_id": pid,
            "gsis_id": gsis,
            "player": name_map.get(pid, pid),
            "position": position,
            "team": tm,
            "games": int(a["games"]),
            "snap_share": round(a["off_snp"] / tm_snp, 3) if tm_snp else None,
            "tgt_share": round(tgts / team_t, 3) if team_t else None,
            "rz_touches": int(a["rec_rz_tgt"] + a["rush_rz_att"] + a["pass_rz_att"]),
            "air_yards": round(air, 1),
            "adot": round(a["rec_air_yd"] / tgts, 2) if (is_rec and tgts) else None,
        }
        for out in _LB_SUMS:
            row[out] = int(round(a[out])) if out != "fpts_ppr" else round(a[out], 1)
        row["ppg_ppr"] = round(a["fpts_ppr"] / a["games"], 2) if a["games"] else 0.0
        rows.append(row)

    cols = ["source", "rank", "player_id", "gsis_id", "player", "position",
            "team", "games", "targets", "receptions", "rec_yards", "rec_td",
            "carries", "rush_yards", "rush_td", "pass_att", "pass_cmp",
            "pass_yards", "pass_td", "pass_int", "snap_share", "tgt_share",
            "rz_touches", "air_yards", "adot", "fpts_ppr", "ppg_ppr"]
    df = pd.DataFrame(rows)
    if not df.empty:
        # Cache the FULL ranked board (limit-independent -- the key has no
        # `limit`), so a later call with a different `limit` still slices from
        # the right place; `head()` is applied on the way out.
        df = df.sort_values("fpts_ppr", ascending=False).reset_index(drop=True)
        df.insert(1, "rank", range(1, len(df) + 1))
        df = df[[c for c in cols if c in df.columns]]
    _lb_cache[ck] = df
    return df.head(int(limit)).copy() if not df.empty else df.copy()


def clear_cache() -> None:
    """Drop this module's in-process caches. Call on a live re-score
    (alongside `scoring.clear_stats_cache()`); the on-disk snapshots stay."""
    _week_cache.clear()
    _usage_cache.clear()
    _lb_cache.clear()
