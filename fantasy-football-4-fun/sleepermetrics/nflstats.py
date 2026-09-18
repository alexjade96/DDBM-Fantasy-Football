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
`data/sources/sleeper_stats/<season>/week_<week>.json` -- named for the
source (Sleeper's own feed), a sibling tree next to `data/sources/adp/`, under the
SAME SOURCES_DIR (see repo_paths.py) and the SAME `SLEEPERMETRICS_SOURCES_DIR`
override, so all durable non-league-scoped data still lives in one place. It
is the offline / cold-host fallback, same durable-JSON idea as the ADP cache:
written on every successful live fetch, read back when the network is gone.
The source is labelled `"sleeper"` throughout (`SOURCE`), so a later
multi-source usage board can tell where a row came from.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from repo_paths import SOURCES_DIR

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
# Offense/kicker only -- see `_DEF_USAGE_KEYS` for team defense's own,
# structurally different vocabulary.
_USAGE_KEYS = (
    "gp", "gms_active",
    "off_snp", "tm_off_snp",
    "rec", "rec_tgt", "rec_yd", "rec_air_yd", "rec_rz_tgt", "rec_yar", "rec_td",
    "rush_att", "rush_yd", "rush_rz_att", "rush_yac", "rush_td",
    "pass_att", "pass_cmp", "pass_yd", "pass_air_yd", "pass_rz_att",
    "pass_td", "pass_int", "pass_rtg",
    "pts_std", "pts_half_ppr", "pts_ppr",
)

# Team defense (DEF) has NO overlap with `_USAGE_KEYS` -- a DEF `player_id` is
# a team abbreviation (see players.py), and Sleeper's line for it carries a
# wholly different vocabulary: takeaways, sacks/tackles, points/yards allowed
# (tiered, matching data/sources/default_scoring.json's DST weights exactly),
# special-teams/return production, and its own `pts_*`. Confirmed live off a
# real Sleeper week (2024 wk1-5, all 32 teams) before adding this -- every key
# below was actually observed on a real DEF line, not guessed from the
# scoring chart alone. No snap_share/tgt_share/adot equivalent exists for a
# team unit, so DEF rows are aggregated on a separate path throughout this
# module rather than forced through the offense shape.
_DEF_USAGE_KEYS = (
    "gp", "gms_active",
    "sack", "sack_yd", "int", "ff", "fum_rec", "fum_rec_td", "blk_kick",
    "safe", "def_td", "qb_hit", "tkl", "tkl_solo", "tkl_ast", "tkl_loss",
    "def_3_and_out", "def_4_and_stop", "def_forced_punts", "def_pass_def",
    "def_st_ff", "def_st_fum_rec", "def_st_td",
    "pts_allow", "pts_allow_0", "pts_allow_1_6", "pts_allow_7_13",
    "pts_allow_14_20", "pts_allow_21_27", "pts_allow_28_34", "pts_allow_35p",
    "yds_allow",
    "pts_std", "pts_half_ppr", "pts_ppr",
)

# Same durable-data root the ADP cache uses (data/sources/, not data/seasons/
# -- this is a source-organized cache, not a league-scoped bracket config).
# Named for the source (Sleeper's own weekly feed), distinct from nflverse's
# own differently-shaped player_stats dataset under data/sources/nflverse/.
_STATS_DIR = SOURCES_DIR / "sleeper_stats"

# {(season, week): {player_id: {key: value}}} -- trimmed lines, for the life
# of the process. Separate from scoring.py's own `_stats_cache` (that one
# holds the FULL untrimmed line); this is the trimmed usage view.
_week_cache: dict = {}
# {(league_id, season, weeks_key): DataFrame} -- computed usage frames.
_usage_cache: dict = {}


def _snapshot_path(season, week) -> Path:
    return _STATS_DIR / str(season) / f"week_{int(week)}.json"


def _trim(lines: dict) -> dict:
    """Raw {pid: full_line} -> {pid: usage-subset line}.

    Keeps a player only if his position is a fantasy one AND his line has at
    least one usage key actually present (Sleeper emits a metadata-only stub
    -- `gms_active` / `pos_rank_*` and nothing else -- for a player who was on
    an NFL roster but never took a snap; the same shape `metrics._position_
    totals` guards against). `gp` / `gms_active` alone do not count as usage.

    A DEF `pid` (a team abbreviation, never an offensive player) is trimmed
    against `_DEF_USAGE_KEYS` instead -- Sleeper's own vocabulary for a team
    defense's line shares no keys with the offense/kicker one.
    """
    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))["position"]
    real = set(_USAGE_KEYS) - {"gp", "gms_active"}
    def_real = set(_DEF_USAGE_KEYS) - {"gp", "gms_active"}
    out: dict = {}
    for pid, line in (lines or {}).items():
        if not isinstance(line, dict):
            continue
        pos = pos_map.get(str(pid))
        if pos not in _POSITIONS:
            continue
        if pos == "DEF":
            if not any(k in line for k in def_real):
                continue
            out[str(pid)] = {k: float(line[k]) for k in _DEF_USAGE_KEYS if k in line}
        else:
            if not any(k in line for k in real):
                continue
            out[str(pid)] = {k: float(line[k]) for k in _USAGE_KEYS if k in line}
    return out


def raw_week(season, week, reload: bool = False) -> dict:
    """Trimmed usage lines for one week: {player_id: {key: value}}.

    Snapshot-first: the in-process cache, then
    `data/sources/sleeper_stats/<season>/week_<week>.json`, then a live pull via
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

    # accumulate per player, and per (nfl_team, ) so tgt_share has a denominator.
    # DEF is skipped here: every column this function computes (snap_share,
    # tgt_share, adot) is an offense-usage concept with no team-defense
    # equivalent -- accumulating a DEF's `_DEF_USAGE_KEYS` line against these
    # offense keys would silently produce an all-zero, meaningless row rather
    # than erroring. `player_leaderboard` is the DEF-aware entry point.
    acc: dict = {}
    team_tgt: dict = {}
    for w in wl:
        lines = raw_week(s.season, w, reload=reload)
        for pid, ln in lines.items():
            if pos_map.get(pid) == "DEF":
                continue
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
# Offense/kicker only -- see `_LB_DEF_SUMS` for team defense's own leaderboard.
_LB_SUMS = {
    "targets": "rec_tgt", "receptions": "rec", "rec_yards": "rec_yd",
    "rec_td": "rec_td", "carries": "rush_att", "rush_yards": "rush_yd",
    "rush_td": "rush_td", "pass_att": "pass_att", "pass_cmp": "pass_cmp",
    "pass_yards": "pass_yd", "pass_td": "pass_td", "pass_int": "pass_int",
    "fpts_ppr": "pts_ppr",
}

# Team defense's own leaderboard sums -- no overlap with `_LB_SUMS` (see
# `_DEF_USAGE_KEYS`). `pts_allow`/`yds_allow` are season TOTALS (points/yards
# a defense actually gave up), distinct from the tiered `pts_allow_*` keys
# (how many WEEKS landed in each Sleeper scoring bracket, used for reference
# only -- not summed into a leaderboard column since a tier count isn't a
# stat a reader compares across teams the way a raw total is).
_LB_DEF_SUMS = {
    "sacks": "sack", "ints": "int", "forced_fumbles": "ff",
    "fumble_rec": "fum_rec", "def_td": "def_td", "safeties": "safe",
    "blk_kick": "blk_kick", "tackles": "tkl", "qb_hits": "qb_hit",
    "pts_allow": "pts_allow", "yds_allow": "yds_allow",
    "fpts_ppr": "pts_ppr",
}


def _leaderboard_pool():
    """The player pool + lookup maps every `player_leaderboard` branch needs,
    factored out since both the offense and DEF paths build it identically."""
    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pool = pool.set_index(pool["player_id"].astype(str))
    gsis_map = pool["gsis_id"] if "gsis_id" in pool.columns else None
    return pool, pool["position"], pool["team"], pool["player_name"], gsis_map


def _clean_team(tm):
    return None if isinstance(tm, float) and pd.isna(tm) else tm   # NaN -> None (Jinja)


def _clean_gsis(gsis_map, pid):
    if gsis_map is None:
        return None
    gsis = gsis_map.get(pid)
    return None if isinstance(gsis, float) and pd.isna(gsis) else gsis


def _def_leaderboard(season, weeks_list, reload: bool) -> pd.DataFrame:
    """Team-defense season totals, the DEF counterpart to the offense
    aggregation below -- entirely separate columns (sacks/INTs/tackles/points
    & yards allowed) since a defense has no snap_share/tgt_share/adot
    equivalent. Ranked by PPR fantasy points, same convention as offense.
    """
    _, pos_map, team_map, name_map, gsis_map = _leaderboard_pool()

    acc: dict = {}
    for w in weeks_list:
        lines = raw_week(season, w, reload=reload)
        for pid, ln in lines.items():
            if pos_map.get(pid) != "DEF":
                continue
            a = acc.setdefault(pid, {k: 0.0 for k in list(_LB_DEF_SUMS) + ["games"]})
            a["games"] += 1
            for out, src in _LB_DEF_SUMS.items():
                a[out] += ln.get(src, 0.0)

    rows = []
    for pid, a in acc.items():
        row = {
            "source": SOURCE, "player_id": pid, "gsis_id": _clean_gsis(gsis_map, pid),
            "player": name_map.get(pid, pid), "position": "DEF",
            "team": _clean_team(team_map.get(pid)), "games": int(a["games"]),
        }
        for out in _LB_DEF_SUMS:
            row[out] = int(round(a[out])) if out != "fpts_ppr" else round(a[out], 1)
        row["ppg_ppr"] = round(a["fpts_ppr"] / a["games"], 2) if a["games"] else 0.0
        rows.append(row)

    cols = ["source", "rank", "player_id", "gsis_id", "player", "position", "team",
            "games", "sacks", "ints", "forced_fumbles", "fumble_rec", "def_td",
            "safeties", "blk_kick", "tackles", "qb_hits", "pts_allow", "yds_allow",
            "fpts_ppr", "ppg_ppr"]
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("fpts_ppr", ascending=False).reset_index(drop=True)
        df.insert(1, "rank", range(1, len(df) + 1))
        df = df[[c for c in cols if c in df.columns]]
    return df


def player_leaderboard(season, pos: str = "ALL", weeks=None, limit: int = 200,
                       reload: bool = False) -> pd.DataFrame:
    """Season-total player stats from Sleeper's own weekly feed, league-free.

    Unlike `player_usage` this needs NO `Season` -- it walks `raw_week` for
    `weeks` (default weeks 1..18), aggregates per player to season totals, and
    joins `players()` for name / position / team / **gsis_id** (the last is
    the nflverse cross-reference id, so `nflref.compare_sources` can line the
    two sources up). Ranked by PPR fantasy points.

    `pos="DEF"` returns a STRUCTURALLY DIFFERENT column set (sacks, INTs,
    tackles, points/yards allowed -- see `_def_leaderboard`) since a team
    defense has no snap_share/tgt_share/adot equivalent; `pos="ALL"` stays
    offense/kicker-only, same as before DEF support existed, so a mixed
    leaderboard never has to paper over two incompatible row shapes.

    Offense/kicker columns: rank, player_id, gsis_id, player, position, team,
    games, targets, receptions, rec_yards, rec_td, carries, rush_yards,
    rush_td, pass_att, pass_cmp, pass_yards, pass_td, pass_int, snap_share,
    tgt_share, rz_touches, air_yards, adot, fpts_ppr, ppg_ppr. `source` ==
    "sleeper" on every row. Empty frame when no week resolves.
    """
    wl = ([int(weeks)] if isinstance(weeks, int)
          else [int(w) for w in weeks] if weeks is not None
          else list(range(1, 19)))
    p = (pos or "ALL").upper()
    ck = (str(season), p, tuple(wl))
    if not reload and ck in _lb_cache:
        cached = _lb_cache[ck]
        return cached.head(int(limit)).copy() if not cached.empty else cached.copy()

    if p == "DEF":
        df = _def_leaderboard(season, wl, reload)
        _lb_cache[ck] = df
        return df.head(int(limit)).copy() if not df.empty else df.copy()

    pool, pos_map, team_map, name_map, gsis_map = _leaderboard_pool()

    acc: dict = {}
    team_tgt: dict = {}
    extra = ("games", "off_snp", "tm_off_snp", "rec_air_yd", "pass_air_yd",
             "rec_rz_tgt", "rush_rz_att", "pass_rz_att")
    for w in wl:
        lines = raw_week(season, w, reload=reload)
        for pid, ln in lines.items():
            if pos_map.get(pid) == "DEF":
                continue
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

    rows = []
    for pid, a in acc.items():
        position = pos_map.get(pid)
        if p != "ALL" and position != p:
            continue
        tm = _clean_team(team_map.get(pid))
        gsis = _clean_gsis(gsis_map, pid)
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
