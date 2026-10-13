"""One row per player per game, regular season AND playoffs, with the game's context.

The base table for the Alternative Analytics section.  Built from two stored
nflverse files:

  * the raw weekly player stats from the `stats_player` release, for EVERY
    season (1999 on).  The older `player_stats` release has no kicker data and
    stops after 2024; `stats_player` carries the field goal and extra point
    columns back to 1999.  Both keep POST rows that the shared `player_stats`
    dataset drops;
  * the raw `schedules` file, which supplies opponent, home or away, game type
    and result.

The raw files are kept whole under `data/sources/nflverse/raw/`; this dataset
is the trimmed extract.  It keeps only the positions the builder has measures
for (QB, RB, FB, WR, TE, K) and, within them, only rows with at least one
recorded stat, which matches what the older release listed (the newer one also
lists every player who was on the field and recorded nothing).  Defenders,
punters and linemen are left out because no measure reads them.

Facts this module depends on (checked against the stored files, 2026-10-11):

  * The player files use CURRENT team codes for old seasons (LV, LAC, LA);
    `schedules` uses the codes of the time (OAK, SD, STL).  `_ALIAS` maps the
    schedule onto the current codes.  With it every player-game for 1999 to
    2024 matches exactly one scheduled game.
  * The player files' own `opponent_team` is wrong on 0.18% of rows (always
    the player's own team, mostly defenders and returners), so the opponent
    comes from the schedule.  The source value is kept as `opponent_src` for
    cross-checking and used only when the schedule has no match.
  * Neither player file says home or away.  The schedule does, and its
    `location` column marks neutral sites (the Super Bowl, international
    games), where "home" is only a label.

Snapshots are committed under `data/sources/nflverse/player_games/<season>.parquet`.
On Render a missing snapshot is NOT rebuilt (no raw parsing there); the frame
is simply empty.
"""
from __future__ import annotations

import pandas as pd

from .base import NflDataset
from .player_stats import _KEEP as _STAT_COLS, _RENAMES

EARLIEST = 1999

#: schedule team code of the time -> the code the player files use
_ALIAS = {"OAK": "LV", "SD": "LAC", "STL": "LA"}

# Stat columns kept from the player file (everything in the shared dataset's
# list except identity, which is handled explicitly below).
_IDENTITY = {"player_id", "player_display_name", "position", "recent_team",
             "season", "week", "season_type"}
_STATS = [c for c in _STAT_COLS if c not in _IDENTITY]

#: Kicking columns kept (counts only; percentages are computed from them).
_KICK = ["fg_made", "fg_att", "fg_missed", "fg_long",
         "fg_made_0_19", "fg_made_20_29", "fg_made_30_39", "fg_made_40_49",
         "fg_made_50_59", "fg_made_60_",
         "pat_made", "pat_att", "pat_missed"]

#: Positions the builder has measures for.
_POSITIONS = {"QB", "RB", "FB", "WR", "TE", "K"}

#: A row is kept when any of these is non-zero (the player recorded something).
_ACTIVITY = ["targets", "receptions", "receiving_yards", "receiving_tds", "carries",
             "rushing_yards", "rushing_tds", "attempts", "completions", "passing_yards",
             "passing_tds", "interceptions", "fantasy_points", "fantasy_points_ppr",
             "fg_att", "fg_made", "fg_missed", "pat_att", "pat_made", "pat_missed"]


#: Receiving columns that depend on target tracking.  nflverse records no
#: targets for 2005 to 2008 (and almost none for 2004), so those seasons come
#: through as zeros.  A zero there would read as "no targets", so the season is
#: blanked instead (NaN = not recorded), and the engine leaves NaN out of every
#: total and ratio.
_TARGET_COLS = ["targets", "receiving_air_yards", "target_share", "air_yards_share",
                "wopr", "racr"]
_MIN_LEAGUE_TARGETS = 100


def _blank_unrecorded(df: pd.DataFrame) -> pd.DataFrame:
    if "targets" not in df.columns:
        return df
    if pd.to_numeric(df["targets"], errors="coerce").fillna(0).sum() >= _MIN_LEAGUE_TARGETS:
        return df
    df = df.copy()
    for c in _TARGET_COLS:
        if c in df.columns:
            df[c] = float("nan")
    return df


def _extract(df: pd.DataFrame) -> pd.DataFrame:
    """The relevant rows of one season's raw player file: a position the builder
    knows and at least one recorded stat."""
    df = df[df["position"].isin(_POSITIONS)]
    cols = [c for c in _ACTIVITY if c in df.columns]
    if not cols:
        return df.iloc[0:0]
    active = (df[cols].apply(pd.to_numeric, errors="coerce").fillna(0) != 0).any(axis=1)
    return df[active]


def team_games(sched: pd.DataFrame) -> pd.DataFrame:
    """One row per (season, week, team) from the all-teams schedule.

    Columns: season, week, team, opponent, home_away (Home / Away / Neutral),
    game_id, game_type, gameday, roof, surface, team_score, opp_score, result
    (W / L / T, None for an unplayed game) and spread (the betting line from
    this team's side: negative = favoured).
    """
    s = sched.copy()
    for c in ("home_team", "away_team"):
        s[c] = s[c].replace(_ALIAS)
    neutral = (s["location"].eq("Neutral") if "location" in s.columns
               else pd.Series(False, index=s.index))
    common = ["season", "week", "game_id", "game_type", "gameday", "roof", "surface"]
    common = [c for c in common if c in s.columns]

    def side(own: str, other: str, own_score: str, opp_score: str, home: bool) -> pd.DataFrame:
        t = s[common].copy()
        t["team"] = s[own]
        t["opponent"] = s[other]
        t["team_score"] = s[own_score]
        t["opp_score"] = s[opp_score]
        t["home_away"] = "Home" if home else "Away"
        t.loc[neutral, "home_away"] = "Neutral"
        line = s["spread_line"] if "spread_line" in s.columns else pd.Series(float("nan"), index=s.index)
        # nflverse: spread_line is positive when the HOME team is favoured
        t["spread"] = -line if home else line
        return t

    both = pd.concat([side("home_team", "away_team", "home_score", "away_score", True),
                      side("away_team", "home_team", "away_score", "home_score", False)],
                     ignore_index=True)
    played = both["team_score"].notna() & both["opp_score"].notna()
    res = pd.Series([None] * len(both), index=both.index, dtype=object)
    res[played & (both["team_score"] > both["opp_score"])] = "W"
    res[played & (both["team_score"] < both["opp_score"])] = "L"
    res[played & (both["team_score"] == both["opp_score"])] = "T"
    both["result"] = res
    return both


def build(players: pd.DataFrame, sched: pd.DataFrame, season: int) -> pd.DataFrame:
    """Join one season's raw player rows to that season's games."""
    if players is None or players.empty or sched is None or sched.empty:
        return pd.DataFrame()
    df = players.rename(columns={k: v for k, v in _RENAMES.items()
                                 if k in players.columns and v not in players.columns})
    keep = [c for c in (*_IDENTITY, "opponent_team", *_STATS, *_KICK) if c in df.columns]
    df = _blank_unrecorded(_extract(df[keep]).copy())
    df["recent_team"] = df["recent_team"].replace(_ALIAS)
    games = team_games(sched[sched["season"] == season])
    m = df.merge(games, left_on=["season", "week", "recent_team"],
                 right_on=["season", "week", "team"], how="left")
    m = m.rename(columns={"opponent_team": "opponent_src"})
    m["opponent"] = m["opponent"].where(m["opponent"].notna(), m["opponent_src"])
    m = m.drop(columns=["team"])
    m = m.rename(columns={"recent_team": "team"})
    lead = ["player_id", "player_display_name", "position", "team", "season",
            "week", "season_type", "game_type", "opponent", "home_away"]
    rest = [c for c in m.columns if c not in lead]
    return m[[c for c in lead if c in m.columns] + rest].reset_index(drop=True)


class PlayerGames(NflDataset):
    name = "player_games"
    label = "nflverse player games with schedule context"
    EARLIEST = EARLIEST

    def _asset(self, season: str) -> str:
        # The combined release for every season (the older `player_stats` release
        # has no kicker data).  It is what changes during a season, so it is the
        # asset the refresher probes for this dataset too.
        return f"stats_player/stats_player_week_{season}.parquet"

    def fetch(self, season: str, reload: bool = False) -> pd.DataFrame:
        from . import api, cache

        season = str(season)
        try:
            yr = int(season)
        except (TypeError, ValueError):
            return pd.DataFrame()
        if yr < EARLIEST:
            return pd.DataFrame()

        if not reload:
            cached = cache.load(self.name, season)
            if cached is not None:
                return cached
        if api.on_render():
            # No raw parsing on Render: committed snapshots only.
            return pd.DataFrame()

        try:
            players = api.fetch_release_parquet(self._asset(season), reload=reload)
            sched = api.fetch_release_parquet("schedules/games.parquet")
        except Exception:
            players = sched = None

        out = build(players, sched, yr) if players is not None else pd.DataFrame()
        if out.empty:
            if reload:
                cached = cache.load(self.name, season)
                if cached is not None:
                    return cached
            return pd.DataFrame()
        cache.save(self.name, season, out)
        return out
