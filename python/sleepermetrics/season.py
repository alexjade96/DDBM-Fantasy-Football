"""Assemble one season into a tidy object (mirrors R season.R)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .api import sleeper_api, sleeper_api_many
from .league import league_chain, starter_slots
from .players import players

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]

# How a lineup reads on a scoreboard: QB, RB1/RB2, WR1/WR2, TE, FLEX, K, DEF.
# Note this is NOT POSITIONS order -- the flex slots sit before K/DEF here,
# whereas optimal_lineup fills every fixed position (K and DEF included) before
# any flex. That fill order is parity-sensitive and stays as it is; this is
# purely how the result is presented.
SLOT_ORDER = ["QB", "RB", "WR", "TE", "REC_FLEX", "FLEX", "WRRB_FLEX",
              "SUPER_FLEX", "K", "DEF"]
_FLEX_ELIG = {
    "REC_FLEX": ["WR", "TE"],
    "FLEX": ["RB", "WR", "TE"],
    "WRRB_FLEX": ["RB", "WR", "TE"],
    "SUPER_FLEX": ["QB", "RB", "WR", "TE"],
}


def slot_sort_key(slot) -> tuple:
    """Sort key placing a slot label in lineup order (`RB2` after `RB1`)."""
    s = str(slot)
    base = s.rstrip("0123456789")
    num = s[len(base):]
    idx = SLOT_ORDER.index(base) if base in SLOT_ORDER else len(SLOT_ORDER)
    return (idx, int(num) if num else 0, base)


def assign_slots(df: pd.DataFrame, slots: dict) -> pd.DataFrame:
    """Label an already-chosen lineup with the slot each player fills.

    Unlike `optimal_lineup`, which *selects* players, this takes the lineup as
    given -- the players someone actually started -- and works out which slot
    each one occupies, so the roster can be shown in scoreboard order rather
    than by position or points. Repeated slots are numbered (RB1, RB2).

    Fixed positions fill first, then the flex slots from whoever is left, both
    highest-scoring first, so RB1 outscores RB2. Anyone who fits no slot (odd
    data, or more of a position than the league rosters) is kept and appended,
    never dropped.
    """
    if df.empty or "position" not in df.columns:
        return df
    d = df.dropna(subset=["position"]).sort_values("points", ascending=False)
    used: set = set()
    picks: list = []

    def take(elig, n, label):
        if not n:
            return
        avail = d[d["position"].isin(elig) & ~d["player_id"].isin(used)].head(int(n))
        used.update(avail["player_id"])
        multi = int(n) > 1
        for i, (_, r) in enumerate(avail.iterrows(), start=1):
            picks.append({**r.to_dict(), "slot": f"{label}{i}" if multi else label})

    for p in POSITIONS:
        take([p], slots.get(p, 0), p)
    for lab, elig in _FLEX_ELIG.items():
        take(elig, slots.get(lab, 0), lab)
    for _, r in d[~d["player_id"].isin(used)].iterrows():
        picks.append({**r.to_dict(), "slot": str(r["position"])})
    out = pd.DataFrame(picks)
    if out.empty:
        return out
    return (out.assign(_k=out["slot"].map(slot_sort_key))
            .sort_values("_k").drop(columns="_k").reset_index(drop=True))


def slot_template(slots: dict) -> list:
    """The league's empty starting slots in scoreboard order, for a lineup picker.

    [{"slot": "RB1", "eligible": ["RB"]}, ..., {"slot": "FLEX", "eligible":
    [...]}, ...] -- numbered repeats (RB1, RB2) and flex slots carrying which
    positions can fill them, ordered like a scoreboard (QB, RB, WR, TE, FLEX, K,
    DEF) via slot_sort_key. Derived from starter_slots so it adapts per league.
    """
    out = []
    for p in POSITIONS:
        n = int(slots.get(p, 0))
        for i in range(1, n + 1):
            out.append({"slot": f"{p}{i}" if n > 1 else p, "eligible": [p]})
    for lab, elig in _FLEX_ELIG.items():
        n = int(slots.get(lab, 0))
        for i in range(1, n + 1):
            out.append({"slot": f"{lab}{i}" if n > 1 else lab, "eligible": list(elig)})
    out.sort(key=lambda x: slot_sort_key(x["slot"]))
    return out


def order_by_slot(df: pd.DataFrame) -> pd.DataFrame:
    """Sort a frame that already carries `slot` into lineup order."""
    if df.empty or "slot" not in df.columns:
        return df
    return (df.assign(_k=df["slot"].map(slot_sort_key))
            .sort_values("_k").drop(columns="_k").reset_index(drop=True))


def optimal_lineup(df: pd.DataFrame, slots: dict) -> pd.DataFrame:
    """The best legal lineup for one team-week: the players picked, per slot.

    Fills the fixed positions first, then the flex slots from what's left --
    greedy by points, which is optimal because every flex is a superset of the
    fixed positions it draws from. Rows carry the input's columns plus `slot`.
    """
    d = df.dropna(subset=["position"]).sort_values("points", ascending=False)
    used: set = set()
    picks: list = []

    def take(elig, n, label):
        nonlocal used
        if not n:
            return
        avail = d[d["position"].isin(elig) & ~d["player_id"].isin(used)].head(int(n))
        used |= set(avail["player_id"])
        for _, r in avail.iterrows():
            picks.append({**r.to_dict(), "slot": label})

    for p in POSITIONS:
        take([p], slots.get(p, 0), p)
    take(["WR", "TE"], slots.get("REC_FLEX", 0), "REC_FLEX")
    take(["RB", "WR", "TE"], slots.get("FLEX", 0), "FLEX")
    take(["RB", "WR", "TE"], slots.get("WRRB_FLEX", 0), "WRRB_FLEX")
    take(["QB", "RB", "WR", "TE"], slots.get("SUPER_FLEX", 0), "SUPER_FLEX")
    return pd.DataFrame(picks)


def optimal_points(df: pd.DataFrame, slots: dict) -> float:
    """Best legal lineup points for one team-week given starter-slot counts."""
    lu = optimal_lineup(df, slots)
    return float(lu["points"].sum()) if len(lu) else 0.0


@dataclass
class Season:
    season: str
    name: str
    league_id: str
    last_week: int
    slots: dict
    team_wk: pd.DataFrame
    pl_wk: pd.DataFrame
    lineup: pd.DataFrame
    standings: pd.DataFrame
    user_map: pd.DataFrame
    transactions: pd.DataFrame = field(default_factory=pd.DataFrame)
    accounts: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Sleeper's own phase signals. `status` is pre_draft/drafting/in_season/
    # complete; `playoff_week_start` is the first postseason week, so the
    # regular season is weeks 1..playoff_week_start-1. Nothing else in the
    # codebase knew whether a season was finished -- every "finished Nth"
    # reads the same in week 6 as in week 17 without these.
    status: str | None = None
    playoff_week_start: int | None = None
    # Every scored week, postseason included. `team_wk`/`pl_wk` are the REGULAR
    # season; these are for the postseason features only (toilet bowl, bracket
    # reference scores, playoff-week lineups). Default to the scoped frames so a
    # hand-built Season (tests, fixtures) still behaves.
    team_wk_all: pd.DataFrame | None = None
    pl_wk_all: pd.DataFrame | None = None
    # Last scored week overall (postseason included); `last_week` is the last
    # REGULAR-season week, so the two differ once a postseason has been played.
    last_week_all: int | None = None

    def __post_init__(self):
        if self.team_wk_all is None:
            self.team_wk_all = self.team_wk
        if self.pl_wk_all is None:
            self.pl_wk_all = self.pl_wk
        if self.last_week_all is None:
            self.last_week_all = self.last_week

    @property
    def in_progress(self) -> bool:
        """True while the season is still being played."""
        return self.status not in (None, "complete")

    @property
    def reg_weeks(self) -> int:
        """Last regular-season week, capped at what has actually been scored."""
        if not self.playoff_week_start:
            return self.last_week
        return min(self.last_week, int(self.playoff_week_start) - 1)

    @property
    def current_week(self) -> int:
        """The week to treat as 'now' -- the latest regular-season week with data.

        During a live season `last_scored_leg` lags an in-progress week until it
        finishes, so this is the most recently *scored* week, which is the one the
        standings currently reflect and the sensible landing week for a weekly
        view opened mid-season. On a finished season it is simply the final week.
        A single home for the notion so a live view has one thing to open on.
        """
        return self.last_week

    def __repr__(self):
        return (f"<Season {self.name} {self.season} | teams: "
                f"{len(self.standings)} | weeks 1:{self.last_week}>")


_TX_COLS = ["week", "transaction_id", "type", "transaction", "player_id",
            "roster_id", "user_name", "player_name", "position", "status"]

_ACCT_COLS = ["roster_id", "user_id", "user_name", "team_name",
              "avatar_url", "team_avatar_url", "team"]

AVATAR_CDN = "https://sleepercdn.com/avatars"


def avatar_url(avatar: str | None, thumb: bool = False) -> str | None:
    """CDN url for a Sleeper *account* avatar id.

    Note the two avatar fields have different shapes and are easy to confuse: a
    user's `avatar` is a bare id that has to be turned into a url, while a
    league-specific `metadata.avatar` (the custom team picture) is already a full
    url. Pass each to the right place.
    """
    if not avatar:
        return None
    a = str(avatar)
    if a.startswith("http"):          # already a url -- don't double-prefix it
        return a
    return f"{AVATAR_CDN}/{'thumbs/' if thumb else ''}{a}"


def _account(u: dict) -> dict:
    """One league member: who they are, what they called their team, their icons."""
    meta = u.get("metadata") or {}
    name = u.get("display_name")
    team_name = (meta.get("team_name") or "").strip() or None
    return {
        "user_id": u.get("user_id"),
        "user_name": name,
        "team_name": team_name,
        "avatar_url": avatar_url(u.get("avatar")),          # the account's picture
        "team_avatar_url": avatar_url(meta.get("avatar")),  # a custom team picture
        # What to actually show: a manager who named their team gets that name.
        "team": team_name or name,
    }


def _unnest_transactions(tx_rows: list, user_map: pd.DataFrame,
                         pinfo: pd.DataFrame) -> pd.DataFrame:
    """One row per player add/drop, named + positioned (mirrors R)."""
    if not tx_rows:
        return pd.DataFrame(columns=_TX_COLS)
    tx = pd.DataFrame(tx_rows)
    tx["transaction_id"] = tx["transaction_id"].astype(str)
    tx["roster_id"] = pd.to_numeric(tx["roster_id"], errors="coerce").astype("Int64")
    tx = tx.dropna(subset=["player_id", "roster_id"])
    tx = tx.merge(user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    tx = tx.merge(pinfo[["player_id", "player_name", "position"]],
                  on="player_id", how="left")
    tx["roster_id"] = tx["roster_id"].astype(int)
    return (tx[_TX_COLS]
            .sort_values(["week", "transaction_id", "transaction", "roster_id"])
            .reset_index(drop=True))


def _result(points, pa):
    if pd.isna(pa):
        return None
    if points > pa:
        return "W"
    if points < pa:
        return "L"
    return "T"


def assemble_season(link: dict) -> Season:
    lid = link["league_id"]
    lw = max(int(link["last_scored_leg"]), 1)
    pws = int(link.get("playoff_week_start") or 0)
    slots = starter_slots(link["roster_positions"])
    pinfo = players()

    # users/rosters plus every week's matchups/transactions are all independent
    # of each other, so fetch them in one concurrent batch instead of one
    # sequential round trip at a time -- this is what used to make assembling a
    # 17-week season ~37 sequential Sleeper calls (tens of seconds) before any
    # of a tab's content could render. Row order below is rebuilt by zipping
    # against `range(1, lw + 1)` in ascending order regardless of which
    # request actually completed first, so the resulting frames are identical
    # to what the old sequential loops produced.
    matchup_paths = [f"/league/{lid}/matchups/{wk}" for wk in range(1, lw + 1)]
    tx_paths = [f"/league/{lid}/transactions/{wk}" for wk in range(1, lw + 1)]
    users_raw, rosters_raw, *rest = sleeper_api_many(
        [f"/league/{lid}/users", f"/league/{lid}/rosters", *matchup_paths, *tx_paths])
    matchups_by_week = rest[:lw]
    tx_by_week = rest[lw:]
    by_id = {u["user_id"]: _account(u) for u in users_raw}
    user_map = pd.DataFrame([
        {"roster_id": r["roster_id"], "user_id": r.get("owner_id"),
         "user_name": by_id.get(r.get("owner_id"), {}).get("user_name")}
        for r in rosters_raw
    ])
    # Identity is kept OUT of user_map on purpose: user_map is merged into
    # team_wk, and every column added there would ride along into the metrics.
    accounts = pd.DataFrame([
        {"roster_id": r["roster_id"],
         **by_id.get(r.get("owner_id"),
                     {"user_id": None, "user_name": None, "team_name": None,
                      "avatar_url": None, "team_avatar_url": None, "team": None})}
        for r in rosters_raw
    ], columns=_ACCT_COLS)

    tw_rows, pl_rows = [], []
    for wk, matchups in zip(range(1, lw + 1), matchups_by_week):
        for m in matchups:
            tw_rows.append({"week": wk, "roster_id": m["roster_id"],
                            "matchup_id": m.get("matchup_id"),
                            "points": m.get("points") or 0.0})
            pp = m.get("players_points") or {}
            starters = set(m.get("starters") or [])
            for pid in (m.get("players") or []):
                pts = pp.get(pid)
                pl_rows.append({"week": wk, "roster_id": m["roster_id"], "player_id": pid,
                                "points": 0.0 if pts is None else float(pts),
                                "is_starter": pid in starters})

    tx_rows = []
    for wk, txs in zip(range(1, lw + 1), tx_by_week):
        for t in txs:
            tid, typ, status = (t.get("transaction_id"), t.get("type"),
                                t.get("status"))
            for kind, col in (("add", "adds"), ("drop", "drops")):
                for pid, rid in (t.get(col) or {}).items():
                    tx_rows.append({"week": wk, "transaction_id": tid, "type": typ,
                                    "transaction": kind, "player_id": pid,
                                    "roster_id": rid, "status": status})
    transactions = _unnest_transactions(tx_rows, user_map, pinfo)

    base = pd.DataFrame(tw_rows)
    if base.empty:
        # Nothing scored yet -- a brand-new league whose draft is done but
        # week 1 hasn't been played/locked, or (defensively) any season
        # whose recorded last_scored_leg is 0. `lw` is forced to at least 1
        # above so a week-1 fetch is always attempted; Sleeper answers an
        # empty matchups list for a week nobody has played, which makes
        # `tw_rows` empty and `base` a ZERO-COLUMN frame -- the very next
        # line used to call `.dropna(subset=["matchup_id"])` on that, which
        # raises KeyError (that column doesn't exist on a columnless frame),
        # crashing the whole Season assembly rather than just leaving this
        # one season empty. Every downstream metric/template already
        # tolerates an empty `pl_wk`/`team_wk` via column-presence checks
        # (see `_roster_ok` in metrics.py, and the same pattern throughout
        # plots.py/app.py) -- they just need the RIGHT COLUMNS to exist on
        # an otherwise-empty frame, not any rows. So: skip the opponent
        # merge/groupby/standings computation entirely (all of which assume
        # at least one real matchup row) and return a Season with correctly
        # shaped, empty frames -- the app then renders the same "no data"
        # states it already shows for a manager/week with nothing in it,
        # instead of failing to load the league at all.
        # Explicit dtypes, not a bare `columns=[...]` list: a columns-only
        # DataFrame defaults every column to `object`, and several downstream
        # functions call numeric ops (e.g. table_position()'s `.cumsum()`)
        # that pandas refuses on an empty object-dtype column (verified: it
        # raises TypeError, not just a silently-wrong result).
        empty_tw = pd.DataFrame({
            "week": pd.Series(dtype="int64"), "roster_id": pd.Series(dtype="int64"),
            "matchup_id": pd.Series(dtype="float64"), "points": pd.Series(dtype="float64"),
            "opp": pd.Series(dtype="float64"), "pa": pd.Series(dtype="float64"),
            "result": pd.Series(dtype="object"), "allplay_w": pd.Series(dtype="int64"),
            "allplay_l": pd.Series(dtype="int64"), "is_high": pd.Series(dtype="bool"),
            "user_id": pd.Series(dtype="object"), "user_name": pd.Series(dtype="object"),
        })
        empty_pl = pd.DataFrame({
            "week": pd.Series(dtype="int64"), "roster_id": pd.Series(dtype="int64"),
            "player_id": pd.Series(dtype="object"), "points": pd.Series(dtype="float64"),
            "is_starter": pd.Series(dtype="bool"), "player_name": pd.Series(dtype="object"),
            "position": pd.Series(dtype="object"),
        })
        empty_lineup = pd.DataFrame({
            "user_name": pd.Series(dtype="object"), "week": pd.Series(dtype="int64"),
            "actual": pd.Series(dtype="float64"), "optimal": pd.Series(dtype="float64"),
            "left_on_bench": pd.Series(dtype="float64"),
        })
        empty_standings = pd.DataFrame({
            "roster_id": pd.Series(dtype="int64"), "user_id": pd.Series(dtype="object"),
            "user_name": pd.Series(dtype="object"), "wins": pd.Series(dtype="int64"),
            "losses": pd.Series(dtype="int64"), "points": pd.Series(dtype="float64"),
            "pa": pd.Series(dtype="float64"), "allplay_w": pd.Series(dtype="int64"),
            "allplay_l": pd.Series(dtype="int64"), "highs": pd.Series(dtype="int64"),
            "final_position": pd.Series(dtype="int64"), "champion": pd.Series(dtype="bool"),
            "season": pd.Series(dtype="object"),
        })
        return Season(link["season"], link.get("name"), lid, lw, slots,
                      empty_tw, empty_pl, empty_lineup, empty_standings, user_map,
                      transactions, accounts, link.get("status"), pws or None,
                      empty_tw, empty_pl, lw)
    # Opponent via self-merge on (week, matchup_id) EXCLUDING NaN matchup_id, so
    # eliminated/bye teams never get a phantom opponent (== R na_matches="never").
    opp = (base.dropna(subset=["matchup_id"])[["week", "matchup_id", "roster_id", "points"]]
           .rename(columns={"roster_id": "opp", "points": "pa"}))
    tw = base.merge(opp, on=["week", "matchup_id"], how="left")
    tw = tw[tw["opp"].isna() | (tw["roster_id"] != tw["opp"])].copy()
    tw["result"] = [_result(p, a) for p, a in zip(tw["points"], tw["pa"])]

    tw["allplay_w"] = 0
    tw["allplay_l"] = 0
    tw["is_high"] = False
    for _, g in tw.groupby("week"):
        pts = g["points"].values
        for idx in g.index:
            p = tw.at[idx, "points"]
            tw.at[idx, "allplay_w"] = int((pts < p).sum())
            tw.at[idx, "allplay_l"] = int((pts > p).sum())
            tw.at[idx, "is_high"] = bool(p == pts.max())
    tw = tw.merge(user_map, on="roster_id", how="left")

    # pl_wk stays user_name-free to mirror R's schema; the lineup build joins it.
    pl = (pd.DataFrame(pl_rows)
          .merge(pinfo[["player_id", "player_name", "position"]], on="player_id", how="left"))
    # SPLIT THE SEASON HERE. Everything downstream -- standings, luck,
    # efficiency, all-play, power rank, the weekly tab -- is a REGULAR-season
    # metric, so it must not count postseason weeks. Where a league runs its
    # playoff outside Sleeper those weeks are phantom matchups nobody played
    # (2025: LuckyHarm read 16-1 against an actual 13-1); even where it doesn't,
    # a playoff game is not a regular-season result. Filtering once here is what
    # keeps R and Python in step -- the mirror does the same, so every derived
    # metric stays identical without either side special-casing anything.
    # The *_all frames keep every scored week for the postseason features
    # (toilet bowl, bracket reference scores, playoff-week lineups).
    tw_all, pl_all = tw.copy(), pl.copy()
    lw_all = lw
    if pws:
        tw = tw[tw["week"] < pws].copy()
        pl = pl[pl["week"] < pws].copy()
        # last_week must name a week that EXISTS in the scoped frames -- it is
        # the default for "the latest week" all over (summary_week, the weekly
        # tab, "did they keep him?"), and leaving it at the last scored leg
        # indexed an empty frame the moment the postseason was split off.
        lw = min(lw, pws - 1)

    pl_named = pl.merge(user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    lineup_rows = []
    for (un, wk), g in pl_named.groupby(["user_name", "week"]):
        actual = float(g.loc[g["is_starter"], "points"].sum())
        opt = optimal_points(g[["player_id", "position", "points"]], slots)
        lineup_rows.append({"user_name": un, "week": wk, "actual": actual,
                            "optimal": opt, "left_on_bench": max(opt - actual, 0.0)})
    lineup = pd.DataFrame(lineup_rows)

    # `tw` is already regular-season only, so these ARE the regular-season
    # figures -- no separate reg_* columns, which would only invite two
    # competing notions of "the record". Verified against ground truth: on 2025
    # this final_position reproduces all eight of the bracket's stored seeds,
    # where the old all-weeks version matched only four.
    st_rows = []
    for rid, g in tw.groupby("roster_id"):
        st_rows.append({
            "roster_id": rid, "user_id": g["user_id"].iloc[0],
            "user_name": g["user_name"].iloc[0],
            "wins": int((g["result"] == "W").sum()),
            "losses": int((g["result"] == "L").sum()),
            "points": float(g["points"].sum()), "pa": float(g["pa"].sum(skipna=True)),
            "allplay_w": int(g["allplay_w"].sum()), "allplay_l": int(g["allplay_l"].sum()),
            "highs": int(g["is_high"].sum()),
        })
    standings = (pd.DataFrame(st_rows)
                 .sort_values(["wins", "points"], ascending=False)
                 .reset_index(drop=True))
    standings["final_position"] = range(1, len(standings) + 1)

    champ = None
    try:
        for match in sleeper_api(f"/league/{lid}/winners_bracket"):
            if match.get("p") == 1:
                champ = match.get("w")
                break
    except Exception:
        champ = None
    standings["champion"] = standings["roster_id"] == champ
    standings["season"] = link["season"]

    return Season(link["season"], link.get("name"), lid, lw, slots,
                  tw, pl, lineup, standings, user_map, transactions, accounts,
                  link.get("status"), pws or None, tw_all, pl_all, lw_all)


def league_accounts(seasons: dict) -> pd.DataFrame:
    """Every manager in the league's history: who they are *now*, and their record.

    Keyed on `user_id`, which persists across seasons even as display names and
    team names change -- so a manager who renamed themselves is one row, not two,
    and the name/icon shown is the one from their most recent season.
    """
    cols = ["user_id", "user_name", "team_name", "team", "avatar_url",
            "team_avatar_url", "seasons", "first_season", "last_season", "titles"]
    rows = []
    for s in seasons.values():                     # oldest -> newest
        if s.accounts.empty:
            continue
        a = s.accounts.copy()
        a["season"] = s.season
        champs = set(s.standings.loc[s.standings["champion"], "user_name"])
        a["title"] = a["user_name"].isin(champs)
        rows.append(a)
    if not rows:
        return pd.DataFrame(columns=cols)

    d = pd.concat(rows, ignore_index=True)
    d = d[d["user_id"].notna()]
    out = []
    for uid, g in d.groupby("user_id", sort=False):
        cur = g.iloc[-1]                           # most recent season = current identity
        out.append({
            "user_id": uid, "user_name": cur["user_name"],
            "team_name": cur["team_name"], "team": cur["team"],
            "avatar_url": cur["avatar_url"], "team_avatar_url": cur["team_avatar_url"],
            "seasons": g["season"].nunique(),
            "first_season": g["season"].min(), "last_season": g["season"].max(),
            "titles": int(g["title"].sum()),
        })
    return (pd.DataFrame(out, columns=cols)
            .sort_values(["titles", "seasons", "user_name"],
                         ascending=[False, False, True])
            .reset_index(drop=True))


def season(league_id, season: str | None = None) -> Season:
    """Assemble one season (default = most recent) of a league."""
    chain = league_chain(league_id)
    keys = list(chain.keys())
    link = chain[keys[-1]] if season is None else chain[str(season)]
    return assemble_season(link)


def seasons(league_id) -> dict:
    """Assemble every season in the chain -> {season: Season}."""
    chain = league_chain(league_id)
    return {s: assemble_season(link) for s, link in chain.items()}
