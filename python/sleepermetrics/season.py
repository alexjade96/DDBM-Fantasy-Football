"""Assemble one season into a tidy object (mirrors R season.R)."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .api import sleeper_api
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
    slots = starter_slots(link["roster_positions"])
    pinfo = players()

    users_raw = sleeper_api(f"/league/{lid}/users")
    rosters_raw = sleeper_api(f"/league/{lid}/rosters")
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
    for wk in range(1, lw + 1):
        for m in sleeper_api(f"/league/{lid}/matchups/{wk}"):
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
    for wk in range(1, lw + 1):
        for t in sleeper_api(f"/league/{lid}/transactions/{wk}"):
            tid, typ, status = (t.get("transaction_id"), t.get("type"),
                                t.get("status"))
            for kind, col in (("add", "adds"), ("drop", "drops")):
                for pid, rid in (t.get(col) or {}).items():
                    tx_rows.append({"week": wk, "transaction_id": tid, "type": typ,
                                    "transaction": kind, "player_id": pid,
                                    "roster_id": rid, "status": status})
    transactions = _unnest_transactions(tx_rows, user_map, pinfo)

    base = pd.DataFrame(tw_rows)
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
    pl_named = pl.merge(user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    lineup_rows = []
    for (un, wk), g in pl_named.groupby(["user_name", "week"]):
        actual = float(g.loc[g["is_starter"], "points"].sum())
        opt = optimal_points(g[["player_id", "position", "points"]], slots)
        lineup_rows.append({"user_name": un, "week": wk, "actual": actual,
                            "optimal": opt, "left_on_bench": max(opt - actual, 0.0)})
    lineup = pd.DataFrame(lineup_rows)

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
                  tw, pl, lineup, standings, user_map, transactions, accounts)


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
