"""Player Comparison: same-position real-NFL players compared against the
full field and against each other, week by week -- built for in-season
lineup decisions, not a season-end leaderboard.

Deliberately LEAGUE-FREE (no Sleeper league/roster involved at all, unlike
an earlier design of this feature): every function here works off Sleeper's
own player_id and its own weekly-stat/leaderboard data directly, the same
way `nflstats.player_leaderboard`/`player_usage` already are. It lives on
the landing page alongside ADP Comparison and NFL Stats, not inside a
loaded-league dashboard tab -- a league only ever added a scoring-format
distinction (std/half_ppr/ppr/2qb), which the caller can already choose
directly via `player_field_compare`'s/`percentile_profile`'s own `source`/
format handling, so no roster lookup was actually needed for the comparison
itself.

Every function here is a thin wrapper over data this app already computes/
fetches, degrades independently, and never raises: a player with no
real-NFL leaderboard row for a season, or no row for a given week, is simply
absent from the result rather than failing the whole call. Mirrors the
discipline `player_profile.py`/`nflref.base` already establish.
"""
from __future__ import annotations

from sleepermetrics import nflstats

# Default stat_keys for player_trend() when the caller doesn't name their
# own -- one small, position-relevant subset of nflstats._USAGE_KEYS/
# _DEF_USAGE_KEYS per position, not the full ~25-key vocabulary (a trend
# LINE per stat per player gets unreadable past a handful of series). Keeps
# the "fantasy points" line first in every set so a caller charting just
# `stat_keys[0]` always gets the one universally-comparable series.
_DEFAULT_TREND_KEYS = {
    "QB": ("pts_ppr", "pass_yd", "pass_td", "pass_int"),
    "RB": ("pts_ppr", "rush_yd", "rush_att", "rec"),
    "WR": ("pts_ppr", "rec", "rec_yd", "rec_tgt"),
    "TE": ("pts_ppr", "rec", "rec_yd", "rec_tgt"),
    "K": ("pts_ppr",),
    "DEF": ("pts_ppr", "sack", "int", "pts_allow"),
}


def player_field_compare(season: str, position: str, player_ids: list[str],
                          weeks: list[int] | None = None,
                          source: str = "sleeper",
                          stat_mode: str = "total") -> dict:
    """Each of `player_ids`' percentile profile against the full real-NFL
    field at `position` for `season` -- the across-teams real-NFL view.

    A thin loop over `nflref.summary.percentile_profile()` (already computes
    one player's percentile at every stat for their position, against the
    full leaderboard, for one season) -- no new percentile math here, just
    fanning it out over several players so they can be shown side by side.
    `stat_mode` ("total" or "per_game") passes straight through to that
    function; see its own docstring for how a per-game radar is derived.

    `weeks` is accepted here as this function's forward-looking seam for a
    "recent weeks only" comparison, but `percentile_profile()` itself takes
    no such parameter yet (it is season-total only as of this module's
    introduction) -- so for now `weeks` is a NO-OP and every call reads the
    full season regardless of what's passed. Wiring it through requires
    `percentile_profile()`/`player_leaderboard()` to accept a week window
    themselves first; left as explicit follow-up work (see the Player
    Comparison plan's trend-framing step) rather than silently pretending to
    narrow the result today.

    Returns `{player_id: profile_dict_or_None}` -- a player with no
    leaderboard row for that season/position maps to `None` rather than
    being omitted, so a caller comparing a fixed player_ids list always gets
    one entry per id back.
    """
    from webapp.sources.nflref import summary as nflref_summary

    out: dict[str, dict | None] = {}
    for pid in player_ids:
        try:
            out[str(pid)] = nflref_summary.percentile_profile(
                season, position, pid, source=source, stat_mode=stat_mode)
        except Exception:
            out[str(pid)] = None
    return out


def player_trend(player_ids: list[str], season: str, position: str | None = None,
                  stat_keys: list[str] | None = None,
                  weeks: list[int] | None = None,
                  zero_fill: bool = False) -> dict:
    """Week-by-week real-NFL production for `player_ids`, one row per week
    per player -- the week-by-week trend-line chart's input, and the data
    the week-range picker narrows for the snapshot views (see the Player
    Comparison plan). The one genuinely new data function in this module:
    every other function here wraps an existing season-total call, but
    nothing in this codebase currently walks `nflstats.raw_week()` across a
    RANGE of weeks per player rather than aggregating it away into a season
    total (`player_leaderboard`) or a single week (`raw_week` itself).

    `stat_keys` defaults to a small position-relevant subset
    (`_DEFAULT_TREND_KEYS`) rather than every key `raw_week` carries -- a
    trend chart with 25 overlaid stat lines per player is unreadable; `pos`
    is required to pick that default when `stat_keys` is omitted, but not
    when the caller names their own keys explicitly. `weeks` defaults to
    the same `range(1, 19)` convention `player_leaderboard` already uses
    (Sleeper's own full-season upper bound); this function is league-free
    (works off Sleeper's own player_id directly, no Season/roster needed),
    same as `player_leaderboard`.

    A week where `raw_week` has no row for a player (bye, didn't play, or
    the week hasn't been scored yet) is simply ABSENT from that player's
    week list rather than a zero-filled row -- a trend chart reading this
    should treat gaps as "no game," not "scored zero," since those read
    very differently for a lineup decision.

    Returns `{player_id: [{"week": int, stat_key: value, ...}, ...]}`, each
    player's list sorted by week ascending. A stat key `raw_week` doesn't
    carry for that player/week (e.g. a QB-only key on a RB) is simply
    omitted from that week's dict rather than included as `None`.

    `zero_fill=True` changes that for a week the player DID play (he has a
    line): a requested key the line lacks becomes 0.0.  Sleeper omits a stat
    that is zero (Gibbs's `rush_td` is absent in every week he scored none),
    so without this a counting stat charted for one stat would show a gap in
    every week it was zero.  A week with no line at all is still absent.
    """
    if stat_keys is None:
        keys = _DEFAULT_TREND_KEYS.get((position or "").upper(), ("pts_ppr",))
    else:
        keys = tuple(stat_keys)
    wl = [int(w) for w in weeks] if weeks is not None else list(range(1, 19))

    ids = {str(pid) for pid in player_ids}
    out: dict[str, list[dict]] = {pid: [] for pid in ids}
    for wk in wl:
        try:
            week_data = nflstats.raw_week(season, wk)
        except Exception:
            continue
        for pid in ids:
            line = week_data.get(pid) or week_data.get(str(pid))
            if not line:
                continue
            row = {"week": wk}
            for key in keys:
                if key in line:
                    row[key] = line[key]
                elif zero_fill:
                    row[key] = 0.0
            out[pid].append(row)
    return out


def trend_raw_key(table_key: str | None, position: str | None) -> str | None:
    """The weekly Sleeper key behind one of the comparison table's metrics, or
    None when that metric has no simple weekly series (snap share, target
    share, RZ touches, aDOT are rates or need team totals) or is not a table
    metric at all.  Uses the same maps the leaderboard sums its season totals
    from (`nflstats._LB_SUMS` / `_LB_DEF_SUMS`), so a table row and its trend
    line can never disagree about what the stat is.  Fantasy points are not a
    table metric: the trend chart's default (PPR points) is how you get back
    to them."""
    if not table_key or table_key == "fpts_ppr":
        return None
    sums = nflstats._LB_DEF_SUMS if (position or "").upper() == "DEF" else nflstats._LB_SUMS
    return sums.get(table_key)


def trend_choices(position: str | None) -> list[tuple[str, str]]:
    """`[(table key, label)]` of every metric the trend chart can show for this
    position, in leaderboard order (for the 3+ player dropdown, where there is
    no table to click)."""
    from webapp.sources.nflref import summary
    return [(key, label) for key, label in summary.leaderboard_columns(position or "", "sleeper")
            if key not in summary._RADAR_EXCLUDED_KEYS and trend_raw_key(key, position)]
