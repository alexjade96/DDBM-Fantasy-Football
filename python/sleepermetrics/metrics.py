"""Descriptive metric tables (pure compute; mirrors R metrics.R)."""
from __future__ import annotations

import pandas as pd

from .players import players
from .season import Season

POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def standings(s: Season) -> pd.DataFrame:
    return s.standings


def luck(s: Season) -> pd.DataFrame:
    d = s.standings.copy()
    games = d["wins"] + d["losses"]
    exp = (d["allplay_w"] / (d["allplay_w"] + d["allplay_l"]).clip(lower=1) * games).round(1)
    out = pd.DataFrame({
        "user_name": d["user_name"], "wins": d["wins"],
        "exp_w": exp, "luck": (d["wins"] - exp).round(1),
    })
    return out.sort_values("luck", ascending=False).reset_index(drop=True)


def efficiency(s: Season, through_week: int | None = None) -> pd.DataFrame:
    lu = s.lineup if through_week is None else s.lineup[s.lineup["week"] <= through_week]
    g = lu.groupby("user_name", as_index=False).agg(
        actual=("actual", "sum"), optimal=("optimal", "sum"), bench=("left_on_bench", "sum"))
    g["eff"] = (g["actual"] / g["optimal"] * 100).round(1)
    return g.sort_values("eff", ascending=False).reset_index(drop=True)


def consistency(s: Season) -> pd.DataFrame:
    g = s.team_wk.groupby("user_name", as_index=False).agg(
        median=("points", "median"), sd=("points", "std"),
        min=("points", "min"), max=("points", "max"))
    g["sd"] = g["sd"].round(1)
    return g.sort_values("sd").reset_index(drop=True)


def points_for_against(s: Season) -> pd.DataFrame:
    return s.standings[["user_name", "points", "pa", "wins"]].copy()


def high_scores(s: Season) -> pd.DataFrame:
    return (s.standings[["user_name", "highs"]]
            .sort_values("highs", ascending=False).reset_index(drop=True))


def _bind_standings(seasons: dict) -> pd.DataFrame:
    return pd.concat([s.standings for s in seasons.values()], ignore_index=True)


def _canonical_names(all_st: pd.DataFrame) -> pd.DataFrame:
    ordered = all_st.sort_values("season", ascending=False)
    return (ordered.groupby("user_id", as_index=False)
            .agg(user_name=("user_name", "first")))


def career(seasons: dict) -> pd.DataFrame:
    """Career standings across all seasons, aggregated by persistent user_id."""
    all_st = _bind_standings(seasons)
    canon = _canonical_names(all_st)
    g = all_st.groupby("user_id", as_index=False).agg(
        seasons=("season", "nunique"), wins=("wins", "sum"), losses=("losses", "sum"),
        points=("points", "sum"), titles=("champion", "sum"),
        best=("final_position", "min"))
    g["win_pct"] = (g["wins"] / (g["wins"] + g["losses"]).clip(lower=1) * 100).round(1)
    g["record"] = g["wins"].astype(str) + "-" + g["losses"].astype(str)
    g = g.merge(canon, on="user_id", how="left")
    return g.sort_values("win_pct", ascending=False).reset_index(drop=True)


def week_stats(s: Season, week: int | None = None) -> pd.DataFrame:
    """Per-team stats for one week (points, opponent, result, margin, bench)."""
    wk = week if week is not None else s.last_week
    lu = s.lineup[s.lineup["week"] == wk][["user_name", "optimal", "left_on_bench"]]
    tw = s.team_wk[s.team_wk["week"] == wk].merge(lu, on="user_name", how="left")
    out = pd.DataFrame({
        "week": wk, "user_name": tw["user_name"], "points": tw["points"],
        "opp_points": tw["pa"], "result": tw["result"],
        "margin": (tw["points"] - tw["pa"]).round(2),
        "optimal": tw["optimal"], "left_on_bench": tw["left_on_bench"].round(1),
    })
    return out.sort_values("points", ascending=False).reset_index(drop=True)


def player_loyalty(seasons: dict, min_seasons: int = 3) -> pd.DataFrame:
    """Players a manager re-rostered in >= min_seasons seasons."""
    from .players import players as _players
    pinfo = _players()
    frames = []
    for s in seasons.values():
        r = (s.pl_wk.merge(s.user_map[["roster_id", "user_id"]], on="roster_id", how="left")
             [["user_id", "player_id"]].drop_duplicates())
        r["season"] = s.season
        frames.append(r)
    rostered = pd.concat(frames, ignore_index=True)
    canon = _canonical_names(_bind_standings(seasons))
    g = rostered.groupby(["user_id", "player_id"], as_index=False).agg(
        seasons_kept=("season", "nunique"),
        season_list=("season", lambda x: ", ".join(sorted(set(x)))))
    g = g[g["seasons_kept"] >= min_seasons]
    g = (g.merge(pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
         .merge(canon, on="user_id", how="left"))
    g = g[g["player_name"].notna()]
    return g.sort_values(["seasons_kept", "user_name", "player_name"],
                         ascending=[False, True, True]).reset_index(drop=True)


# --- Roster & position analytics (ported from ddbmFF.R) -------------------

def _pos_cat(df):
    df = df.copy()
    df["position"] = pd.Categorical(df["position"], categories=POSITIONS, ordered=True)
    return df


def position_scoring(s: Season) -> pd.DataFrame:
    """Total started points by position + each position's share of scoring."""
    d = s.pl_wk[s.pl_wk["is_starter"] & s.pl_wk["position"].isin(POSITIONS)]
    g = d.groupby("position", as_index=False).agg(points=("points", "sum"))
    g["share"] = (g["points"] / g["points"].sum() * 100).round(1)
    return _pos_cat(g).sort_values("position").reset_index(drop=True)


def roster(s: Season) -> pd.DataFrame:
    """Player-weeks rostered, total and average points per team per position."""
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d[d["position"].isin(POSITIONS)]
    g = d.groupby(["user_name", "position"], as_index=False).agg(
        spots=("points", "size"), points=("points", "sum"))
    g["avg"] = g["points"] / g["spots"]
    return _pos_cat(g).sort_values(["user_name", "position"]).reset_index(drop=True)


def starter_bench(s: Season) -> pd.DataFrame:
    """Average points, starters vs bench, per team and position."""
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d[d["position"].isin(POSITIONS)].copy()
    d["status"] = d["is_starter"].map({True: "Starters", False: "Bench"})
    g = d.groupby(["user_name", "position", "status"], as_index=False).agg(avg=("points", "mean"))
    return _pos_cat(g).sort_values(["user_name", "position", "status"]).reset_index(drop=True)


def table_position(s: Season) -> pd.DataFrame:
    """Weekly table-position trajectory (cumulative record then points)."""
    d = s.team_wk.sort_values(["user_name", "week"]).copy()
    d["is_w"] = (d["result"] == "W").fillna(False).astype(int)
    d["is_l"] = (d["result"] == "L").fillna(False).astype(int)
    g = d.groupby("user_name")
    d["wins"] = g["is_w"].cumsum()
    d["losses"] = g["is_l"].cumsum()
    d["points"] = g["points"].cumsum()
    d = d.sort_values(["week", "wins", "points", "user_name"],
                      ascending=[True, False, False, True])
    d["table_position"] = d.groupby("week").cumcount() + 1
    return (d[["week", "user_name", "wins", "losses", "points", "table_position"]]
            .sort_values(["week", "table_position"]).reset_index(drop=True))


def roster_counts(s: Season) -> pd.DataFrame:
    """Average roster slots per position per team-week, starters vs bench."""
    denom = len(s.standings) * s.last_week
    d = s.pl_wk[s.pl_wk["position"].isin(POSITIONS)].copy()
    d["status"] = d["is_starter"].map({True: "Starters", False: "Bench"})
    g = d.groupby(["position", "status"], as_index=False).agg(avg_count=("points", "size"))
    g["avg_count"] = g["avg_count"] / denom
    return _pos_cat(g).sort_values(["position", "status"]).reset_index(drop=True)


# --- Composite / behavioural metrics -------------------------------------

def allplay(s: Season) -> pd.DataFrame:
    """Regular-season all-play standings (mirrors R sl_allplay).

    What the standings would be if every team played every other team every
    week. `rank_delta = allplay_rank - final_position`: positive means the real
    standing beats all-play merit (a friendly schedule), negative means the team
    was better than its record.
    """
    d = s.standings.copy()
    out = pd.DataFrame({
        "user_name": d["user_name"],
        "allplay_w": d["allplay_w"], "allplay_l": d["allplay_l"],
        "allplay_pct": d["allplay_w"] / (d["allplay_w"] + d["allplay_l"]).clip(lower=1),
        "final_position": d["final_position"],
    })
    out = out.sort_values(["allplay_pct", "allplay_w"], ascending=False).reset_index(drop=True)
    out["allplay_rank"] = out.index + 1
    out["rank_delta"] = out["allplay_rank"] - out["final_position"]
    return out


def power_rank(s: Season, weights: dict | None = None, recent: int = 3,
               through_week: int | None = None) -> pd.DataFrame:
    """Composite power ranking (mirrors R sl_power_rank).

    A z-scored blend of points for, all-play win%, recent form, and lineup
    efficiency. The composite is left unrounded (mean/sd derived); round on
    display, per the project's parity discipline.

    `through_week` recomputes points/all-play/form/efficiency from `team_wk`
    and `lineup` capped at that week instead of reading the season-end
    `standings` -- the weekly report's reuse of this otherwise season-wide
    ranking (a week-5 power ranking must not leak weeks 6-14).
    """
    w = weights or {"points": 0.35, "allplay": 0.30, "form": 0.20, "eff": 0.15}

    def z(x: pd.Series) -> pd.Series:
        sd = x.std()
        if pd.isna(sd) or sd == 0:
            return pd.Series(0.0, index=x.index)
        return (x - x.mean()) / sd

    if through_week is None:
        maxwk = s.team_wk["week"].max()
        form = (s.team_wk[s.team_wk["week"] > maxwk - recent]
                .groupby("user_name", as_index=False).agg(form=("points", "mean")))
        eff = efficiency(s)[["user_name", "eff"]]
        d = s.standings[["user_name", "points", "allplay_w", "allplay_l"]].copy()
    else:
        tw = s.team_wk[s.team_wk["week"] <= through_week]
        form = (tw[tw["week"] > through_week - recent]
                .groupby("user_name", as_index=False).agg(form=("points", "mean")))
        eff = efficiency(s, through_week)[["user_name", "eff"]]
        d = tw.groupby("user_name", as_index=False).agg(
            points=("points", "sum"), allplay_w=("allplay_w", "sum"),
            allplay_l=("allplay_l", "sum"))
    d["allplay_pct"] = d["allplay_w"] / (d["allplay_w"] + d["allplay_l"]).clip(lower=1)
    d = d.merge(form, on="user_name", how="left").merge(eff, on="user_name", how="left")
    d["power"] = (w["points"] * z(d["points"]) + w["allplay"] * z(d["allplay_pct"])
                  + w["form"] * z(d["form"]) + w["eff"] * z(d["eff"]))
    d = d.sort_values("power", ascending=False).reset_index(drop=True)
    d["power_rank"] = d.index + 1
    return d[["user_name", "points", "allplay_pct", "form", "eff", "power", "power_rank"]]


def manager_profile(s: Season) -> pd.DataFrame:
    """Manager tendencies (mirrors R sl_manager_profile).

    Behavioural profile from transactions and lineups: roster churn, trades,
    drops, and mean weekly start/sit efficiency. `lineup_iq` is mean-derived and
    returned unrounded; round on display.
    """
    tx = s.transactions
    weeks = s.team_wk["week"].max()
    managers = s.standings[["user_name"]].drop_duplicates()

    def tally(mask_fn, name):
        # mask_fn is deferred so a column-less empty transactions frame (a season
        # with no moves) short-circuits before any column is touched.
        if not len(tx):
            return pd.DataFrame({"user_name": [], name: []})
        sub = tx[mask_fn(tx) & (tx["status"] != "failed")]
        return sub.groupby("user_name", as_index=False).size().rename(columns={"size": name})

    moves = tally(lambda t: t["type"].isin(["waiver", "free_agent"]) & (t["transaction"] == "add"), "moves")
    trades = tally(lambda t: (t["type"] == "trade") & (t["transaction"] == "add"), "trades")
    drops = tally(lambda t: t["transaction"] == "drop", "drops")
    iq = (s.lineup.assign(r=s.lineup["actual"] / s.lineup["optimal"].clip(lower=1e-9))
          .groupby("user_name", as_index=False).agg(lineup_iq=("r", "mean")))
    iq["lineup_iq"] = iq["lineup_iq"] * 100

    out = (managers.merge(moves, on="user_name", how="left")
           .merge(trades, on="user_name", how="left")
           .merge(drops, on="user_name", how="left")
           .merge(iq, on="user_name", how="left"))
    for c in ("moves", "trades", "drops"):
        out[c] = out[c].fillna(0).astype(int)
    out["moves_per_wk"] = out["moves"] / weeks
    return out.sort_values(["moves", "lineup_iq"], ascending=False).reset_index(drop=True)


def mgr_allplay_snapshot(s: Season, manager: str, through_week: int) -> dict | None:
    """One manager's schedule-independent (all-play) record through a given
    week, and how it compares to their actual table position that week.

    Webapp-only addition (not parity-gated, same precedent as `boom_bust` /
    `strength_of_schedule`) mirroring `allplay`'s math, but capped at
    `through_week` and compared against the table position AT that week
    rather than `allplay`'s season-end `final_position` -- a week-5 report
    can't leak weeks 6-14 into "deserved record so far" the way that
    season-end comparison would.
    """
    wk = int(through_week)
    tw = s.team_wk[s.team_wk["week"] <= wk]
    if not len(tw) or "allplay_w" not in tw.columns:
        return None
    g = tw.groupby("user_name", as_index=False).agg(
        allplay_w=("allplay_w", "sum"), allplay_l=("allplay_l", "sum"))
    if not len(g):
        return None
    g["allplay_pct"] = g["allplay_w"] / (g["allplay_w"] + g["allplay_l"]).clip(lower=1)
    g = g.sort_values(["allplay_pct", "allplay_w"], ascending=False).reset_index(drop=True)
    g["allplay_rank"] = g.index + 1
    row = g[g["user_name"] == manager]
    if not len(row):
        return None
    r = row.iloc[0]
    tp = table_position(s)
    cur = tp[(tp["week"] == wk) & (tp["user_name"] == manager)]
    pos = int(cur["table_position"].iloc[0]) if len(cur) else None
    return {
        "allplay_w": int(r["allplay_w"]), "allplay_l": int(r["allplay_l"]),
        "allplay_rank": int(r["allplay_rank"]), "table_position": pos,
        "rank_delta": (int(r["allplay_rank"]) - pos) if pos is not None else None,
    }


def mgr_activity_snapshot(s: Season, manager: str, through_week: int) -> dict:
    """One manager's moves/trades/drops and lineup IQ, capped at a given week.

    Webapp-only addition mirroring `manager_profile`'s math for a single
    manager, week-capped so a week-5 report doesn't count moves or lineup
    weeks from 6-14.
    """
    wk = int(through_week)
    tx = s.transactions
    moves = trades = drops = 0
    if len(tx):
        mine = tx[(tx["user_name"] == manager) & (tx["status"] != "failed")]
        if "week" in mine.columns:
            mine = mine[mine["week"] <= wk]
        moves = int(len(mine[mine["type"].isin(["waiver", "free_agent"])
                             & (mine["transaction"] == "add")]))
        trades = int(len(mine[(mine["type"] == "trade") & (mine["transaction"] == "add")]))
        drops = int(len(mine[mine["transaction"] == "drop"]))
    lu = s.lineup
    lineup_iq = None
    if len(lu) and {"user_name", "week", "actual", "optimal"}.issubset(lu.columns):
        mine_lu = lu[(lu["user_name"] == manager) & (lu["week"] <= wk)]
        if len(mine_lu):
            r = mine_lu["actual"] / mine_lu["optimal"].clip(lower=1e-9)
            lineup_iq = round(float(r.mean()) * 100, 1)
    return {"moves": moves, "trades": trades, "drops": drops, "lineup_iq": lineup_iq,
            "moves_per_wk": round(moves / wk, 2) if wk else None}


# --- Transaction analytics (ported from ddbmFF.R) -------------------------

def transactions(s: Season) -> pd.DataFrame:
    """The season's unnested add/drop transactions frame."""
    return s.transactions


def _rostered_perf(s: Season, keep: pd.DataFrame, on: list) -> pd.DataFrame:
    """Points scored while rostered, by player x manager (from pl_wk).

    `on` sets the join grain: ["player_id"] (trades -> every team that held the
    player) or ["player_id", "roster_id"] (waivers -> the acquiring team only).
    """
    d = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    d = d.merge(keep, on=on, how="inner")
    d = d[d["position"].isin(POSITIONS) & d["player_name"].notna()]
    # player_id rides along: it is the only safe key for a portrait (names are
    # neither unique nor stable).
    g = d.groupby(["player_id", "player_name", "position", "user_name"],
                  as_index=False).agg(
        weeks=("week", "nunique"), points=("points", "sum"))
    g["avg"] = g["points"] / g["weeks"]
    g["total"] = g.groupby("player_name")["points"].transform("sum")
    return g


def trade_performance(s: Season) -> pd.DataFrame:
    """Traded players' points on each team that rostered them (movers only)."""
    tx = s.transactions
    keep = (tx[(tx["type"] == "trade") & (tx["transaction"] == "add")
               & (tx["status"] != "failed")][["player_id"]].drop_duplicates())
    g = _rostered_perf(s, keep, ["player_id"])
    g = g[g.groupby("player_name")["user_name"].transform("nunique") > 1]
    return _pos_cat(g).sort_values(["total", "player_name", "user_name"],
                                   ascending=[False, True, True]).reset_index(drop=True)


def waiver_performance(s: Season) -> pd.DataFrame:
    """Waiver / free-agent pickups' points while on the acquiring roster."""
    tx = s.transactions
    keep = (tx[(tx["type"].isin(["waiver", "free_agent"])) & (tx["transaction"] == "add")
               & (tx["status"] != "failed")][["player_id", "roster_id"]]
            .drop_duplicates())
    g = _rostered_perf(s, keep, ["player_id", "roster_id"])
    return _pos_cat(g).sort_values(["total", "player_name", "user_name"],
                                   ascending=[False, True, True]).reset_index(drop=True)


# --- Schedule, rivalry & records (webapp analytics) ----------------------

def boom_bust(s: Season) -> pd.DataFrame:
    """Each team's scoring average vs its week-to-week volatility.

    Separates the steady teams (high floor) from the boom-or-bust ones (high
    ceiling, high spread) -- the two axes a single average hides.
    """
    g = s.team_wk.groupby("user_name", as_index=False).agg(
        avg=("points", "mean"), sd=("points", "std"),
        floor=("points", "min"), ceiling=("points", "max"))
    g["avg"] = g["avg"].round(1)
    g["sd"] = g["sd"].fillna(0.0).round(1)
    return g.sort_values("avg", ascending=False).reset_index(drop=True)


def strength_of_schedule(s: Season, through_week: int | None = None) -> pd.DataFrame:
    """Average scoring strength of the opponents each team actually faced.

    Opponent strength is that opponent's season-long PPG (not their score in the
    one week you met), so a team that keeps drawing the league's best has a high
    SOS regardless of the weekly noise. `through_week` caps `team_wk` at that
    week (both the opponents' PPG baseline and the games counted), for the
    weekly report's reuse of this otherwise season-wide read.
    """
    tw = s.team_wk if through_week is None else s.team_wk[s.team_wk["week"] <= through_week]
    ppg = tw.groupby("roster_id")["points"].mean()
    d = tw.dropna(subset=["opp"]).copy()
    d["opp_ppg"] = d["opp"].map(ppg)
    g = d.groupby("user_name", as_index=False).agg(sos=("opp_ppg", "mean"))
    own = (tw.groupby("user_name", as_index=False)["points"].mean()
           .rename(columns={"points": "own_ppg"}))
    g = g.merge(own, on="user_name", how="left")
    g["sos"] = g["sos"].round(1)
    g["own_ppg"] = g["own_ppg"].round(1)
    g = g.sort_values("sos", ascending=False).reset_index(drop=True)
    g["rank"] = range(1, len(g) + 1)
    return g


def schedule_swap(s: Season) -> pd.DataFrame:
    """Every team's record played against every other team's schedule.

    For team A under team B's schedule: each week, replace A's real opponent
    with the one B faced that week and re-decide with A's own scores. The
    diagonal (A under A's schedule) is the real record; the row spread shows how
    much the actual schedule flattered or robbed a team.
    """
    tw = s.team_wk
    pts = {(w, r): p for w, r, p in zip(tw["week"], tw["roster_id"], tw["points"])}
    opp = {(w, r): o for w, r, o in zip(tw["week"], tw["roster_id"], tw["opp"])}
    weeks = sorted(tw["week"].unique())
    name = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    rosters = sorted(tw["roster_id"].unique())
    rows = []
    for a in rosters:
        for b in rosters:
            w = l = 0
            for wk in weeks:
                o = opp.get((wk, b))
                if pd.isna(o) or o == a:          # bye week, or would face self
                    continue
                pa_, po = pts.get((wk, a)), pts.get((wk, o))
                if pa_ is None or po is None:
                    continue
                if pa_ > po:
                    w += 1
                elif pa_ < po:
                    l += 1
            rows.append({"team": name.get(a), "schedule_of": name.get(b),
                         "wins": w, "losses": l})
    return pd.DataFrame(rows)


def head_to_head(seasons: dict) -> pd.DataFrame:
    """All-time manager-vs-manager record, keyed on the persistent user_id.

    Every decided game across the whole chain (regular season + playoffs),
    aggregated both ways so the matrix is complete. Names are the managers'
    current display names (they change season to season; the id does not).
    """
    canon = _canonical_names(_bind_standings(seasons))
    frames = []
    for s in seasons.values():
        um = s.user_map.rename(columns={
            "roster_id": "opp", "user_id": "opp_user_id"})
        d = (s.team_wk.dropna(subset=["opp", "result"])
             .merge(um[["opp", "opp_user_id"]], on="opp", how="left"))
        frames.append(d[["user_id", "opp_user_id", "points", "pa", "result"]])
    allg = pd.concat(frames, ignore_index=True).dropna(subset=["opp_user_id"])
    g = allg.groupby(["user_id", "opp_user_id"], as_index=False).agg(
        wins=("result", lambda x: int((x == "W").sum())),
        losses=("result", lambda x: int((x == "L").sum())),
        ties=("result", lambda x: int((x == "T").sum())),
        pf=("points", "sum"), pa=("pa", "sum"))
    g["games"] = g["wins"] + g["losses"] + g["ties"]
    g["win_pct"] = (g["wins"] / g["games"].clip(lower=1) * 100).round(1)
    g["margin"] = ((g["pf"] - g["pa"]) / g["games"].clip(lower=1)).round(1)
    g = (g.merge(canon, on="user_id", how="left")
         .merge(canon.rename(columns={"user_id": "opp_user_id",
                                      "user_name": "opp_name"}), on="opp_user_id", how="left"))
    return g.reset_index(drop=True)


def record_book(seasons: dict) -> list[dict]:
    """League superlatives across every season -- the screenshot-and-argue page.

    Each entry is {label, value, holder, detail} so it renders as a tile without
    the template knowing how it was computed.
    """
    tw = []
    for s in seasons.values():
        d = s.team_wk.dropna(subset=["result"]).copy()
        d["season"] = s.season
        d["margin"] = d["points"] - d["pa"]
        tw.append(d)
    g = pd.concat(tw, ignore_index=True) if tw else pd.DataFrame()
    out: list[dict] = []
    if g.empty:
        return out

    def tile(label, row, value, extra=""):
        wk = f"wk {int(row['week'])}" if "week" in row and pd.notna(row["week"]) else ""
        detail = "  ·  ".join(x for x in (f"{row['season']} {wk}".strip(), extra) if x)
        out.append({"label": label, "value": value,
                    "holder": row["user_name"], "detail": detail})

    hi = g.loc[g["points"].idxmax()]
    tile("Highest score", hi, f"{hi['points']:.1f}")
    blow = g.loc[g["margin"].idxmax()]
    tile("Biggest blowout", blow, f"+{blow['margin']:.1f}", f"beat by {blow['margin']:.0f}")
    losses = g[g["result"] == "L"]
    if len(losses):
        tl = losses.loc[losses["points"].idxmax()]
        tile("Highest-scoring loss", tl, f"{tl['points']:.1f}", "and still lost")
    wins = g[g["result"] == "W"]
    if len(wins):
        lw = wins.loc[wins["points"].idxmin()]
        tile("Lowest-scoring win", lw, f"{lw['points']:.1f}", "and still won")

    # Best single-season points total.
    season_tot = (g.groupby(["season", "user_name"], as_index=False)["points"].sum()
                  .sort_values("points", ascending=False))
    if len(season_tot):
        st = season_tot.iloc[0]
        out.append({"label": "Best season total", "value": f"{st['points']:.0f}",
                    "holder": st["user_name"], "detail": str(st["season"])})

    # Longest win streak within a season (chronological by week).
    best = {"len": 0}
    for (sea, uid), grp in g.sort_values("week").groupby(["season", "user_id"]):
        run = 0
        for res, nm in zip(grp["result"], grp["user_name"]):
            run = run + 1 if res == "W" else 0
            if run > best["len"]:
                best = {"len": run, "holder": nm, "season": sea}
    if best["len"] >= 2:
        out.append({"label": "Longest win streak", "value": f"{best['len']} in a row",
                    "holder": best["holder"], "detail": str(best["season"])})
    return out


# --- transaction ledgers (webapp analytics) ------------------------------
# The Transactions tab's detail tables. These read the same frames as
# trade_performance / waiver_performance but keep the *deal* intact -- who
# traded with whom, and what each side got -- rather than reducing everything to
# per-player rows. Webapp-only, so they are not part of the parity contract.

_TRADE_COLS = ["week", "transaction_id", "user_name", "with", "received",
               "gave", "got_pts", "gave_pts", "net"]
_WAIVER_COLS = ["week", "user_name", "player_id", "player_name", "position",
                "via", "times", "points", "starts", "weeks_rostered",
                "trend", "trend_total", "trend_avg"]


def _pts_by_player_roster(s: Season, through_week: int | None = None) -> dict:
    """{(player_id, roster_id): points scored while on that roster}.

    pl_wk records roster membership week by week, so this already splits a
    traded player's season between the teams that held him -- no transaction
    stint reconstruction needed. `through_week` caps that sum at a given week,
    for the weekly report's reuse of these otherwise season-wide ledgers (a
    week-3 report must not credit a pickup with weeks 4-14's points, which
    hadn't happened yet as of that week).
    """
    pl = s.pl_wk
    if not {"player_id", "roster_id", "points"}.issubset(getattr(pl, "columns", [])):
        return {}
    if through_week is not None:
        pl = pl[pl["week"] <= through_week]
    g = pl.groupby([pl["player_id"].astype(str), pl["roster_id"]])["points"].sum()
    return {k: float(v) for k, v in g.items()}


def _live_tx(s: Season, kinds: list) -> pd.DataFrame:
    """Completed transactions of the given types, with string player ids."""
    tx = getattr(s, "transactions", None)
    need = {"week", "transaction_id", "type", "transaction", "player_id",
            "roster_id", "player_name"}
    if tx is None or not need.issubset(getattr(tx, "columns", [])):
        return pd.DataFrame()
    t = tx[tx["type"].isin(kinds)]
    if "status" in t.columns:
        t = t[t["status"] != "failed"]
    if t.empty:
        return pd.DataFrame()
    t = t.copy()
    t["player_id"] = t["player_id"].astype(str)
    return t


def trade_ledger(s: Season) -> pd.DataFrame:
    """Every completed trade, one row per team involved in it.

    `net` is what the players a team received scored FOR THEM, minus what the
    players they gave up scored for whoever received them -- so the two sides of
    a two-team deal are mirror images, and a three-way deal still attributes
    each player's points to the roster that actually got him.
    """
    t = _live_tx(s, ["trade"])
    if t.empty:
        return pd.DataFrame(columns=_TRADE_COLS)
    pts = _pts_by_player_roster(s)
    names = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    rows = []
    for tid, ev in t.groupby("transaction_id"):
        adds = ev[ev["transaction"] == "add"]
        dest = dict(zip(adds["player_id"], adds["roster_id"]))
        wk = int(ev["week"].min())
        for rid, g in ev.groupby("roster_id"):
            got = g[g["transaction"] == "add"]
            gave = g[g["transaction"] == "drop"]
            got_pts = sum(pts.get((p, rid), 0.0) for p in got["player_id"])
            gave_pts = sum(pts.get((p, dest.get(p)), 0.0) for p in gave["player_id"])
            others = sorted({names.get(r, str(r)) for r in ev["roster_id"]
                             if r != rid})
            rows.append({
                "week": wk, "transaction_id": str(tid),
                "user_name": names.get(rid, str(rid)),
                "with": ", ".join(others) or "—",
                "received": ", ".join(got["player_name"].astype(str)) or "—",
                "gave": ", ".join(gave["player_name"].astype(str)) or "—",
                "got_pts": round(got_pts, 1), "gave_pts": round(gave_pts, 1),
                "net": round(got_pts - gave_pts, 1),
            })
    return (pd.DataFrame(rows)
            .sort_values(["week", "transaction_id", "net"],
                         ascending=[True, True, False])
            .reset_index(drop=True))


def waiver_ledger(s: Season, top_n: int | None = 30, through_week: int | None = None,
                  trend_weeks: int = 4) -> pd.DataFrame:
    """Waiver / free-agent pickups, one row per player per manager.

    Collapsed to unique (manager, player): a player picked up, cut and picked up
    again is one story, and `points` is already a per-(player, roster) total, so
    separate rows would repeat the same figure. `times` records the churn.
    `through_week` caps `points`/`starts`/`weeks_rostered` at a given week (see
    `_pts_by_player_roster`) -- the weekly report's reuse of this otherwise
    season-wide ledger.

    `trend`/`trend_total`/`trend_avg` mimic the free-agent trend exactly
    (`_fa_trend`, shared): the player's real stat line priced with the
    league's own scoring chart over the trailing `trend_weeks` through
    `through_week` (or the latest scored week, season-wide), regardless of
    WHICH roster (if any) held him in those earlier weeks. A pickup added
    this week otherwise showed only a single bar (their one week on THIS
    roster), which reads as "no history" for a player who may well have been
    heating up on the wire before anyone grabbed him.
    """
    t = _live_tx(s, ["waiver", "free_agent"])
    if t.empty:
        return pd.DataFrame(columns=_WAIVER_COLS)
    adds = t[t["transaction"] == "add"]
    if adds.empty:
        return pd.DataFrame(columns=_WAIVER_COLS)
    pts = _pts_by_player_roster(s, through_week)
    names = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    pl = s.pl_wk
    if through_week is not None:
        pl = pl[pl["week"] <= through_week]
    have = {"roster_id", "player_id", "is_starter", "week"}.issubset(
        getattr(pl, "columns", []))
    anchor = through_week if through_week is not None else (
        int(pl["week"].max()) if have and len(pl) else None)
    rows = []
    for (rid, pid), g in adds.groupby(["roster_id", "player_id"]):
        first = g.iloc[0]
        kinds = sorted({("waiver" if k == "waiver" else "FA") for k in g["type"]})
        starts = weeks = 0
        if have:
            w = pl[(pl["roster_id"] == rid) & (pl["player_id"].astype(str) == pid)]
            starts = int(w["is_starter"].sum())
            weeks = int(w["week"].nunique())
        rows.append({
            "week": int(g["week"].min()), "user_name": names.get(rid, str(rid)),
            "player_id": pid, "player_name": first["player_name"],
            "position": first.get("position"),
            "via": "/".join(kinds), "times": len(g),
            "points": round(pts.get((pid, rid), 0.0), 1),
            "starts": starts, "weeks_rostered": weeks,
        })
    if rows and anchor is not None:
        from . import scoring
        _fa_trend(s, anchor, rows, scoring.rules_from(s.league_id), trend_weeks)
    else:
        for r in rows:
            r["trend"], r["trend_total"], r["trend_avg"] = [], 0.0, 0.0
    d = (pd.DataFrame(rows).sort_values("points", ascending=False)
         .reset_index(drop=True))
    return d.head(top_n) if top_n else d


def trade_deals(s: Season) -> list[dict]:
    """Every trade as ONE entry, carrying a side per team involved.

    `trade_ledger` is one row per team, so a two-team deal appears twice as
    mirror images -- convenient for sorting and filtering, roundabout to read,
    and it prints every player's name twice. This folds each `transaction_id`
    into a single deal whose sides list only what that team RECEIVED, so each
    player appears exactly once, under whoever got him. Sides are ordered best
    net first, which is also who "won" the deal.
    """
    led = trade_ledger(s)
    if led.empty:
        return []
    out = []
    for tid, g in led.groupby("transaction_id", sort=False):
        g = g.sort_values("net", ascending=False)
        sides = g[["user_name", "received", "got_pts", "net"]].to_dict("records")
        best = sides[0]
        margin = round(abs(float(best["net"])), 1)
        out.append({
            "week": int(g["week"].iloc[0]),
            "transaction_id": str(tid),
            "sides": sides,
            "n_teams": len(sides),
            # A near-even deal shouldn't crown anybody; 10 points across a whole
            # season is noise.
            "winner": best["user_name"] if margin >= 10 else None,
            "margin": margin,
        })
    return sorted(out, key=lambda x: (x["week"], x["transaction_id"]))


# --- roster detail (webapp analytics) ------------------------------------
# The Roster tab's drill-downs: the same pl_wk frame the roster charts use,
# aggregated per manager, per week, and into a handful of superlatives.

def _roster_ok(s: Season) -> bool:
    return {"roster_id", "week", "player_name", "position", "points",
            "is_starter"}.issubset(getattr(s.pl_wk, "columns", []))


def roster_detail(s: Season) -> list[dict]:
    """Per manager: roster shape, plus every player they rostered.

    `bench_pts` is points scored by players on their bench that week -- the
    cost of the roster, not of the lineup decision (that is `efficiency`).
    """
    if not _roster_ok(s):
        return []
    pl = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id",
                       how="left")
    out = []
    for name, g in pl.groupby("user_name"):
        st, bn = g[g["is_starter"]], g[~g["is_starter"]]
        players = []
        for (pn, pos), pg in g.groupby(["player_name", "position"]):
            pst = pg[pg["is_starter"]]
            players.append({
                "player_name": pn, "position": pos,
                "weeks": int(pg["week"].nunique()), "starts": int(len(pst)),
                "started_pts": round(float(pst["points"].sum()), 1),
                "bench_pts": round(float(pg.loc[~pg["is_starter"], "points"].sum()), 1),
            })
        players.sort(key=lambda x: -x["started_pts"])
        counts = (st["position"].value_counts().to_dict() if len(st) else {})
        out.append({
            "user_name": name,
            "players_used": int(g["player_name"].nunique()),
            "starts": int(len(st)),
            "started_pts": round(float(st["points"].sum()), 1),
            "bench_pts": round(float(bn["points"].sum()), 1),
            "bench_share": round(float(bn["points"].sum())
                                 / max(float(g["points"].sum()), 1) * 100, 1),
            "pos_counts": {p: int(counts.get(p, 0)) for p in POSITIONS},
            "players": players,
        })
    return sorted(out, key=lambda x: -x["started_pts"])


def roster_weeks(s: Season) -> list[dict]:
    """Per week: who got the most out of their roster, and who left the most on it."""
    if not _roster_ok(s):
        return []
    pl = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id",
                       how="left")
    lu = s.lineup if {"user_name", "week", "actual", "optimal"}.issubset(
        getattr(s.lineup, "columns", [])) else None
    out = []
    for wk, g in pl.groupby("week"):
        teams = []
        for name, tg in g.groupby("user_name"):
            st = tg[tg["is_starter"]]
            row = {"user_name": name,
                   "started": round(float(st["points"].sum()), 1),
                   "bench": round(float(tg.loc[~tg["is_starter"], "points"].sum()), 1)}
            if lu is not None:
                m = lu[(lu["user_name"] == name) & (lu["week"] == wk)]
                if len(m):
                    row["optimal"] = round(float(m["optimal"].iloc[0]), 1)
                    row["eff"] = round(row["started"]
                                       / max(row["optimal"], 1) * 100, 1)
            teams.append(row)
        teams.sort(key=lambda x: -x["started"])
        st = g[g["is_starter"]]
        top = st.loc[st["points"].idxmax()] if len(st) else None
        benched = g[~g["is_starter"]]
        bb = benched.loc[benched["points"].idxmax()] if len(benched) else None
        out.append({
            "week": int(wk), "teams": teams,
            "league_pts": round(float(st["points"].sum()), 1),
            "best": teams[0] if teams else None,
            "worst": teams[-1] if teams else None,
            "top_player": (None if top is None else
                           {"player_name": top["player_name"],
                            "position": top["position"],
                            "user_name": top["user_name"],
                            "points": round(float(top["points"]), 1)}),
            "best_benched": (None if bb is None else
                             {"player_name": bb["player_name"],
                              "position": bb["position"],
                              "user_name": bb["user_name"],
                              "points": round(float(bb["points"]), 1)}),
        })
    return out


def roster_standouts(s: Season) -> list[dict]:
    """Roster superlatives as {label, value, holder, detail} tiles."""
    if not _roster_ok(s):
        return []
    pl = s.pl_wk.merge(s.user_map[["roster_id", "user_name"]], on="roster_id",
                       how="left")
    st, bn = pl[pl["is_starter"]], pl[~pl["is_starter"]]
    out = []

    def tile(label, value, holder, detail=""):
        out.append({"label": label, "value": value, "holder": holder,
                    "detail": detail})

    if len(st):
        r = st.loc[st["points"].idxmax()]
        tile("Best player-week", f"{r['points']:.1f}", r["user_name"],
             f"{r['player_name']} · {r['position']} · wk {int(r['week'])}")
    if len(bn):
        r = bn.loc[bn["points"].idxmax()]
        tile("Most points benched (one player)", f"{r['points']:.1f}",
             r["user_name"], f"{r['player_name']} · {r['position']} · wk {int(r['week'])}")
        g = bn.groupby("user_name")["points"].sum()
        tile("Most points on the bench (season)", f"{g.max():.0f}", g.idxmax(),
             "across every week")
    used = pl.groupby("user_name")["player_name"].nunique()
    if len(used):
        tile("Most players used", f"{int(used.max())}", used.idxmax(),
             "roster churn")
        tile("Fewest players used", f"{int(used.min())}", used.idxmin(),
             "stood pat")
    if len(st):
        # The most lopsided team: the largest share of started points from one
        # position group.
        share = (st.groupby(["user_name", "position"])["points"].sum()
                 / st.groupby("user_name")["points"].sum())
        if len(share):
            idx = share.idxmax()
            tile("Most one-position team", f"{share.max() * 100:.0f}%", idx[0],
                 f"of started points from {idx[1]}")
        ppw = st.groupby(["user_name", "week"])["points"].sum()
        if len(ppw):
            tile("Best starting week", f"{ppw.max():.1f}", ppw.idxmax()[0],
                 f"week {int(ppw.idxmax()[1])}")
    return out


# --- coaching detail (webapp analytics) ----------------------------------
# The Coaching tab's drill-downs. `efficiency` says how well a manager set
# lineups; these say WHICH weeks and WHICH decisions, and what they cost.

def _coach_frames(s: Season):
    """(lineup, team_wk) if both carry what the coaching views need, else None."""
    lu, tw = s.lineup, s.team_wk
    if not {"user_name", "week", "actual", "optimal",
            "left_on_bench"}.issubset(getattr(lu, "columns", [])):
        return None
    if not {"user_name", "week", "points"}.issubset(getattr(tw, "columns", [])):
        return None
    return lu, tw


def coaching_detail(s: Season) -> list[dict]:
    """Per manager: their lineup weeks, and what the misses actually cost.

    `cost_losses` counts weeks they LOST while their best legal lineup would
    have won -- the only benched points that changed an outcome. `perfect`
    counts weeks they left nothing on the bench at all.
    """
    fr = _coach_frames(s)
    if fr is None:
        return []
    lu, tw = fr
    res = (tw[["user_name", "week", "points", "pa", "result"]]
           if {"pa", "result"}.issubset(tw.columns) else None)
    out = []
    for name, g in lu.groupby("user_name"):
        g = g.sort_values("week")
        weeks, flipped = [], 0
        for r in g.itertuples():
            row = {"week": int(r.week), "actual": round(float(r.actual), 1),
                   "optimal": round(float(r.optimal), 1),
                   "cost": round(float(r.left_on_bench), 1),
                   "eff": round(float(r.actual) / max(float(r.optimal), 1) * 100, 1)}
            if res is not None:
                m = res[(res["user_name"] == name) & (res["week"] == r.week)]
                if len(m) and pd.notna(m["pa"].iloc[0]):
                    pa = float(m["pa"].iloc[0])
                    row["pa"] = round(pa, 1)
                    row["result"] = str(m["result"].iloc[0])
                    row["would_have_won"] = bool(row["result"] == "L"
                                                 and float(r.optimal) > pa)
                    flipped += row["would_have_won"]
            weeks.append(row)
        act, opt = float(g["actual"].sum()), float(g["optimal"].sum())
        worst = max(weeks, key=lambda w: w["cost"]) if weeks else None
        out.append({
            "user_name": name,
            "eff": round(act / max(opt, 1) * 100, 1),
            "actual": round(act, 1), "optimal": round(opt, 1),
            "bench": round(float(g["left_on_bench"].sum()), 1),
            "perfect": int((g["left_on_bench"] < 0.05).sum()),
            "cost_losses": int(flipped),
            "worst_week": worst,
            "weeks": weeks,
        })
    return sorted(out, key=lambda x: -x["eff"])


def bench_regrets(s: Season, top_n: int = 15) -> list[dict]:
    """The season's costliest single bench calls, league-wide.

    For each team-week, the benched player who most outscored a same-position
    starter -- a swap that was legal at the time. `flipped` marks the ones where
    that one change alone would have turned a loss into a win.
    """
    pl = s.pl_wk
    need = {"roster_id", "week", "player_name", "position", "points", "is_starter"}
    if not need.issubset(getattr(pl, "columns", [])) or s.user_map.empty:
        return []
    d = pl.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
    tw = s.team_wk
    have_res = {"user_name", "week", "points", "pa", "result"}.issubset(
        getattr(tw, "columns", []))
    out = []
    for (name, wk), g in d.groupby(["user_name", "week"]):
        starters, bench = g[g["is_starter"]], g[~g["is_starter"]]
        if starters.empty or bench.empty:
            continue
        best = None
        for b in bench.itertuples():
            same = starters[starters["position"] == b.position]
            if same.empty:
                continue
            weak = same.loc[same["points"].idxmin()]
            gain = float(b.points) - float(weak["points"])
            if gain > 0 and (best is None or gain > best["swing"]):
                best = {"swing": round(gain, 1), "benched": b.player_name,
                        "benched_pts": round(float(b.points), 1),
                        "position": b.position, "started": weak["player_name"],
                        "started_pts": round(float(weak["points"]), 1)}
        if best is None:
            continue
        best.update({"user_name": name, "week": int(wk), "flipped": False,
                     "margin": None})
        if have_res:
            m = tw[(tw["user_name"] == name) & (tw["week"] == wk)]
            if len(m) and pd.notna(m["pa"].iloc[0]):
                margin = float(m["points"].iloc[0]) - float(m["pa"].iloc[0])
                best["margin"] = round(margin, 1)
                best["flipped"] = bool(margin < 0 and best["swing"] >= abs(margin))
        out.append(best)
    # Decisions that changed a result first, then by raw cost.
    out.sort(key=lambda x: (not x["flipped"], -x["swing"]))
    return out[:top_n]


def coaching_standouts(s: Season) -> list[dict]:
    """Coaching superlatives as {label, value, holder, detail} tiles."""
    det = coaching_detail(s)
    if not det:
        return []
    out = []

    def tile(label, value, holder, detail=""):
        out.append({"label": label, "value": value, "holder": holder,
                    "detail": detail})

    tile("Best lineup efficiency", f"{det[0]['eff']:.1f}%", det[0]["user_name"],
         f"{det[0]['bench']:.0f} pts left on the bench")
    tile("Worst lineup efficiency", f"{det[-1]['eff']:.1f}%", det[-1]["user_name"],
         f"{det[-1]['bench']:.0f} pts left on the bench")
    pf = max(det, key=lambda x: x["perfect"])
    if pf["perfect"]:
        tile("Most perfect lineups", str(pf["perfect"]), pf["user_name"],
             "weeks with nothing left on the bench")
    cl = max(det, key=lambda x: x["cost_losses"])
    if cl["cost_losses"]:
        tile("Losses the bench cost", str(cl["cost_losses"]), cl["user_name"],
             "lost while the optimal lineup would have won")
    worst = max((x for x in det if x["worst_week"]),
                key=lambda x: x["worst_week"]["cost"], default=None)
    if worst:
        tile("Worst single week", f"{worst['worst_week']['cost']:.1f}",
             worst["user_name"],
             f"benched in wk {worst['worst_week']['week']}")
    reg = bench_regrets(s, top_n=1)
    if reg:
        r = reg[0]
        tile("Costliest bench call", f"{r['swing']:.1f}", r["user_name"],
             f"{r['benched']} over {r['started']} · wk {r['week']}")
    return out


def transaction_standouts(s: Season) -> list[dict]:
    """Roster-move superlatives as {label, value, holder, detail} tiles.

    Built from the ledgers rather than the raw frame, so "best trade" means the
    deal whose incoming players outscored the outgoing ones by the most -- not
    simply the busiest manager.
    """
    out = []

    def tile(label, value, holder, detail=""):
        out.append({"label": label, "value": value, "holder": holder,
                    "detail": detail})

    deals = trade_deals(s)
    wl = waiver_ledger(s, top_n=None)
    tx = _live_tx(s, ["trade", "waiver", "free_agent"])

    won = [d for d in deals if d["winner"]]
    if won:
        b = max(won, key=lambda d: d["margin"])
        got = next(sd["received"] for sd in b["sides"]
                   if sd["user_name"] == b["winner"])
        # A four-player haul would wrap the tile into a paragraph.
        names = [x.strip() for x in str(got).split(",") if x.strip()]
        if len(names) > 2:
            got = f"{names[0]}, {names[1]} +{len(names) - 2} more"
        tile("Best trade", f"+{b['margin']:.0f}", b["winner"],
             f"week {b['week']} · got {got}")
    if deals:
        from collections import Counter
        cnt = Counter(sd["user_name"] for d in deals for sd in d["sides"])
        nm, n = cnt.most_common(1)[0]
        tile("Most trades", str(n), nm,
             f"of {len(deals)} deal{'' if len(deals) == 1 else 's'} league-wide")
    if len(wl):
        r = wl.iloc[0]
        tile("Best pickup", f"{r['points']:.0f}", r["user_name"],
             f"{r['player_name']} · {r['via']} in wk {int(r['week'])}")
        # A pickup that was actually used, not just stashed.
        used = wl[wl["starts"] > 0]
        if len(used):
            tile("Waiver hits", str(int((wl["points"] >= 100).sum())), "league-wide",
                 "pickups that returned 100+ points")
    if not tx.empty:
        adds = tx[tx["transaction"] == "add"]
        if len(adds):
            c = adds.groupby("user_name").size()
            tile("Busiest manager", str(int(c.max())), c.idxmax(),
                 "adds across the season")
            tile("Quietest manager", str(int(c.min())), c.idxmin(),
                 "adds across the season")
    return out


def week_matchups(s: Season, week: int) -> list[dict]:
    """The week's games as GAMES -- both lineups, and what decided each one.

    The weekly scoreboard was a flat list of teams, which makes you pair the
    rows up by eye to see who actually played whom. This groups by matchup so a
    game is one row, and hangs the detail that explains it off each: both
    lineups in scoreboard slot order, the standout and quietest starter, what
    was left on the bench, and -- the sharp one -- whether a single legal
    same-position swap would have flipped the result.

    A team with no opponent (a bye, or an eliminated team in a postseason week)
    is kept as a one-sided entry rather than dropped: "they scored 158 and had
    nobody to play" is a real state, and silently omitting the row makes the
    scoreboard disagree with the standings.
    """
    from .season import assign_slots, optimal_lineup

    tw, pl = s.team_wk, s.pl_wk
    if not len(tw) or "week" not in tw:
        return []
    d = tw[tw["week"] == int(week)]
    if not len(d):
        return []
    lu = s.lineup if {"user_name", "week", "actual", "optimal",
                      "left_on_bench"}.issubset(getattr(s.lineup, "columns", [])) else None
    plw = (pl[pl["week"] == int(week)]
           .merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
           if len(pl) else pl)

    def side(r) -> dict:
        nm = r["user_name"]
        g = plw[plw["user_name"] == nm] if len(plw) else plw
        st = g[g["is_starter"]] if len(g) else g
        bn = g[~g["is_starter"]] if len(g) else g
        # team_wk carries points and pa, NOT margin -- deriving it is the whole
        # basis of the flip check below, and reading a "margin" column that does
        # not exist silently made every game look undecided.
        pa = r.get("pa")
        row = {
            "user_name": nm,
            "points": float(r["points"]),
            "pa": float(pa) if pd.notna(pa) else None,
            "result": r["result"] if pd.notna(r["result"]) else None,
            "margin": (float(r["points"]) - float(pa)) if pd.notna(pa) else None,
            "lineup": [], "bench": [],
            "optimal": None, "left_on_bench": None, "eff": None,
        }
        if len(st):
            ls = assign_slots(st, getattr(s, "slots", {}) or {})
            row["lineup"] = [{"slot": x.slot, "player_id": x.player_id,
                              "player_name": x.player_name,
                              "position": x.position, "points": float(x.points)}
                             for x in ls.itertuples(index=False)]
        # The best legal lineup this team's OWN full roster (bench included)
        # could have started -- lets the matchup drilldown toggle "what
        # actually happened" against "what if they'd played it perfectly",
        # same idea as the free-agent comparison's Actual/Optimized switch.
        row["opt_lineup"] = []
        if len(g):
            opt_picks = optimal_lineup(g, getattr(s, "slots", {}) or {})
            if not opt_picks.empty:
                opt_picks = assign_slots(opt_picks, getattr(s, "slots", {}) or {})
                row["opt_lineup"] = [{"slot": x.slot, "player_id": x.player_id,
                                      "player_name": x.player_name,
                                      "position": x.position, "points": float(x.points)}
                                     for x in opt_picks.itertuples(index=False)]
        row["opt_points"] = (round(sum(p["points"] for p in row["opt_lineup"]), 2)
                             if row["opt_lineup"] else None)
        if len(bn):
            b = bn.sort_values("points", ascending=False).head(6)
            # `would_start`: this bench player alone outscored the worst starter
            # at their own position -- i.e. a legal swap that upgrades the
            # lineup. Marked per-player (not just the single costliest one, see
            # `regret` below) so the drilldown can flag every player who
            # mattered, not just the headline swap.
            worst_by_pos = (st.groupby("position")["points"].min()
                            if len(st) else pd.Series(dtype=float))
            row["bench"] = [{"player_id": x.player_id, "player_name": x.player_name,
                             "position": x.position, "points": float(x.points),
                             "would_start": bool(x.position in worst_by_pos.index
                                                  and float(x.points) > worst_by_pos[x.position])}
                            for x in b.itertuples(index=False)]
        if lu is not None:
            m = lu[(lu["user_name"] == nm) & (lu["week"] == int(week))]
            if len(m):
                row["optimal"] = round(float(m["optimal"].iloc[0]), 2)
                row["left_on_bench"] = round(float(m["left_on_bench"].iloc[0]), 2)
                row["eff"] = round(row["points"] / max(row["optimal"], 1e-9) * 100, 1)
        # The single legal same-position swap that cost the most -- and whether
        # it alone would have changed the result (same rule as bench_regrets).
        row["regret"] = None
        if len(st) and len(bn):
            best = None
            for b in bn.itertuples(index=False):
                pool = st[st["position"] == b.position]
                if not len(pool):
                    continue
                w = pool.loc[pool["points"].idxmin()]
                gain = float(b.points) - float(w["points"])
                if gain > 0 and (best is None or gain > best["gain"]):
                    best = {"gain": round(gain, 2), "In": b.player_name,
                            "in_id": b.player_id, "out": w["player_name"],
                            "out_id": w["player_id"], "position": b.position}
            if best:
                mg = row["margin"]
                best["flips"] = bool(mg is not None and mg < 0 and best["gain"] > -mg)
                row["regret"] = best
        return row

    games, seen = [], set()
    for _, r in d.iterrows():
        mid = r.get("matchup_id")
        key = ("m", mid) if pd.notna(mid) else ("solo", r["user_name"])
        if key in seen:
            continue
        seen.add(key)
        rows = (d[d["matchup_id"] == mid] if pd.notna(mid)
                else d[d["user_name"] == r["user_name"]])
        sides = [side(x) for _, x in rows.iterrows()]
        sides.sort(key=lambda x: -x["points"])
        played = len(sides) > 1
        # Per-slot "who won that position" -- matched by slot (QB vs QB, RB1 vs
        # RB1, ...), not by index, since a slot list is already position-order.
        # Only meaningful head-to-head, so bench is untouched.
        if played:
            opp_pts = [{p["slot"]: p["points"] for p in sd["lineup"]} for sd in sides]
            for i, sd in enumerate(sides):
                other = opp_pts[1 - i]
                for p in sd["lineup"]:
                    opp = other.get(p["slot"])
                    p["cmp"] = (None if opp is None else
                               "up" if p["points"] > opp else
                               "down" if p["points"] < opp else "even")
            opt_opp_pts = [{p["slot"]: p["points"] for p in sd["opt_lineup"]} for sd in sides]
            for i, sd in enumerate(sides):
                other = opt_opp_pts[1 - i]
                for p in sd["opt_lineup"]:
                    opp = other.get(p["slot"])
                    p["cmp"] = (None if opp is None else
                               "up" if p["points"] > opp else
                               "down" if p["points"] < opp else "even")
        games.append({
            "matchup_id": mid if pd.notna(mid) else None,
            "sides": sides,
            "played": played,
            "winner": next((x["user_name"] for x in sides if x["result"] == "W"), None),
            "margin": (round(abs(sides[0]["points"] - sides[1]["points"]), 2)
                       if played else None),
            "total": round(sum(x["points"] for x in sides), 2),
        })
    games.sort(key=lambda g: (-g["total"] if g["played"] else 1e9))
    return games


def week_trade_players(s: Season, week: int) -> list[dict]:
    """That week's trades, per player -- no winner/net verdict.

    `trade_deals` (season-wide) aggregates each side into a single net figure
    to call a "winner," which the weekly report deliberately drops: a trade a
    week old hasn't had time to prove anything. This lists what each traded
    player actually did instead -- their points in the trade's own week, and
    their season total through that week (any roster, for context on who was
    moved) -- so the reader draws their own read rather than being handed a
    verdict.
    """
    wk = int(week)
    t = _live_tx(s, ["trade"])
    if t.empty:
        return []
    # Every roster INVOLVED that week, not just those with an add -- a side
    # that gave up a player for nothing back (no return piece, just picks/FAAB,
    # or literally nothing) only ever appears as a "drop" row, and filtering to
    # adds alone silently erased that side of the deal entirely (shipped: a
    # 2-team trade rendered as a 1-team "trade", the give-away side vanishing
    # rather than showing the existing "no players" fallback).
    ev = t[t["week"] == wk]
    if ev.empty:
        return []
    pl = s.pl_wk
    have = {"player_id", "week", "points"}.issubset(getattr(pl, "columns", []))
    wk_pts = (pl[pl["week"] == wk].groupby(pl["player_id"].astype(str))["points"].sum()
             if have else pd.Series(dtype=float))
    season_pts = (pl[pl["week"] <= wk].groupby(pl["player_id"].astype(str))["points"].sum()
                 if have else pd.Series(dtype=float))
    names = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))

    out = []
    for tid, g in ev.groupby("transaction_id"):
        sides = []
        # Who a player was dropped BY within this same transaction -- the
        # source side of the move. In a 2-team trade it's always just "the
        # other side" (not worth stating); in a 3+-team trade a received
        # player could have come from either other team, so this is the only
        # way to tell which.
        drop_from = {str(r["player_id"]): r["roster_id"]
                    for _, r in g[g["transaction"] == "drop"].iterrows()}
        for rid, gg in g.groupby("roster_id"):
            players_ = []
            for _, r in gg[gg["transaction"] == "add"].iterrows():
                pid = str(r["player_id"])
                from_rid = drop_from.get(pid)
                players_.append({
                    "player_id": pid, "player_name": r["player_name"],
                    "week_pts": round(float(wk_pts.get(pid, 0.0)), 1),
                    "season_pts": round(float(season_pts.get(pid, 0.0)), 1),
                    "from_team": names.get(from_rid) if from_rid is not None else None,
                })
            sides.append({"user_name": names.get(rid, str(rid)), "players": players_})
        out.append({"week": wk, "transaction_id": str(tid),
                    "sides": sides, "n_teams": len(sides)})
    return sorted(out, key=lambda x: x["transaction_id"])


def week_transactions(s: Season, week: int) -> dict:
    """That week's roster moves: trades finalized and waiver/FA adds made.

    Trades come from `week_trade_players` (per-player, no verdict -- see its
    docstring); waivers reuse the season-wide `waiver_ledger` with
    `through_week=week` so a week-3 report doesn't credit a pickup with points
    from weeks 4 onward that hadn't been played yet. Returns {"trades": [...],
    "waivers": [...]}, each empty when nothing happened that week (a quiet
    week is normal, not an error).

    Each waiver row also gets `week_points` -- what the pickup scored in THIS
    week specifically, not `points` (the ledger's season-to-date total while
    rostered) -- since every row here was added this same week, "was it worth
    it" is a single-week question, not a cumulative one.
    """
    wk = int(week)
    trades = week_trade_players(s, wk)
    wl = waiver_ledger(s, top_n=None, through_week=wk)
    waivers: list[dict] = []
    if not wl.empty:
        rows = wl[wl["week"] == wk].to_dict("records")
        name_to_rid = dict(zip(s.user_map["user_name"], s.user_map["roster_id"]))
        wk_pl = s.pl_wk[s.pl_wk["week"] == wk]
        wk_pts = {(str(r.player_id), r.roster_id): float(r.points) for r in wk_pl.itertuples()}
        for r in rows:
            rid = name_to_rid.get(r["user_name"])
            r["week_points"] = round(wk_pts.get((str(r["player_id"]), rid), 0.0), 1)
        waivers = sorted(rows, key=lambda r: -r["week_points"])
    return {"trades": trades, "waivers": waivers}


def _position_totals(s: Season, weeks: range) -> tuple[dict, pd.Series]:
    """(pid -> summed fantasy points over `weeks`, pid -> position). Split out
    of `week_position_ranks` so the "price every NFL player's stat line" work
    stays reusable if a cumulative read is ever needed again.
    """
    from . import scoring

    rules = scoring.rules_from(s.league_id)
    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))["position"]

    totals: dict = {}
    for w in weeks:
        lines = scoring.nfl_stats(s.season, w)
        if not lines:
            continue
        for pid, line in lines.items():
            if pos_map.get(pid) not in POSITIONS:
                continue
            pts = sum(v * rules[k] for k, v in line.items() if k in rules)
            totals[pid] = totals.get(pid, 0.0) + pts
    return totals, pos_map


def _rank_by_position(totals: dict, pos_map: pd.Series) -> dict:
    by_pos: dict = {}
    for pid, pts in totals.items():
        by_pos.setdefault(pos_map[pid], []).append((pid, pts))
    out: dict = {}
    for pos, lst in by_pos.items():
        lst.sort(key=lambda x: -x[1])
        for i, (pid, pts) in enumerate(lst, start=1):
            out[pid] = {"position": pos, "rank": i, "points": round(pts, 1)}
    return out


def week_position_ranks(s: Season, week: int) -> dict:
    """Position rank for a single week -- "the #3 RB THIS WEEK" -- for
    context wherever a player's name appears in the weekly report. Unlike
    `_fa_candidates`' `pos_rank` (that week's free agents only), this spans
    EVERY player who scored that week, rostered or not, on any team.

    Returns {player_id: {"position", "rank", "points"}}. Priced with the
    league's own scoring chart, same primitive as everywhere else a player is
    priced outside `pl_wk` (free agents, hand-submitted playoff lineups).
    """
    wk = int(week)
    totals, pos_map = _position_totals(s, range(wk, wk + 1))
    return _rank_by_position(totals, pos_map)


def _fa_candidates(s: Season, week: int) -> tuple[list[dict], dict]:
    """(candidate rows, scoring rules) -- every unrostered player who scored
    this week, positioned and priced. Shared by `free_agent_standouts`
    (league-wide) and `free_agent_impact` (one manager's own roster), so the
    "who's actually a free agent, and what did they score" half of the work
    isn't duplicated between them.
    """
    from . import scoring

    wk = int(week)
    pl = s.pl_wk[s.pl_wk["week"] == wk]
    if pl.empty:
        return [], {}
    rostered = set(pl["player_id"].astype(str))
    lines = scoring.nfl_stats(s.season, wk)
    if not lines:
        return [], {}
    rules = scoring.rules_from(s.league_id)
    pool = players().dropna(subset=["player_id"]).drop_duplicates("player_id")
    pos_map = pool.set_index(pool["player_id"].astype(str))[["player_name", "position", "team"]]

    rows = []
    for pid, line in lines.items():
        if pid in rostered or pid not in pos_map.index:
            continue
        info = pos_map.loc[pid]
        pos = info["position"]
        if pos not in POSITIONS:
            continue
        pts = round(sum(v * rules[k] for k, v in line.items() if k in rules), 2)
        if pts <= 0:
            continue
        # A player between NFL teams has a real, not-missing team of NaN --
        # scrub it to None here, at the boundary: pandas NaN is truthy in
        # Jinja, so `{% if fa.team %}` alone would still render the literal
        # "nan" (see CLAUDE.md's `records()` note -- same trap, same fix).
        team = info["team"] if pd.notna(info["team"]) else None
        rows.append({"player_id": pid, "player_name": info["player_name"],
                     "position": pos, "team": team, "points": pts})

    # Rank within position among EVERY free agent this week (1 = highest
    # scoring), computed here before any caller caps to a top-N -- "the 2nd
    # best RB free agent this week" needs the full pool, not just whichever
    # slice a caller kept.
    by_pos: dict = {}
    for r in rows:
        by_pos.setdefault(r["position"], []).append(r)
    for lst in by_pos.values():
        lst.sort(key=lambda r: -r["points"])
        for i, r in enumerate(lst, start=1):
            r["pos_rank"] = i
    return rows, rules


def _fa_trend(s: Season, week: int, entries: list[dict], rules: dict,
              trend_weeks: int) -> None:
    """Mutates `entries` in place, adding `trend`/`trend_total`/`trend_avg`.

    `trend` is each entry's points across the trailing `trend_weeks` weeks
    (through the viewed week), regardless of roster status in those earlier
    weeks -- free-agent status is too volatile week to week to gate a trend
    read on it, and the point is telling a hot streak from a one-week fluke.
    `pct` (0-100, floored at 6 so a scoreless week still shows a sliver) is
    each week normalized against the BEST WEEK ANY ENTRY IN THIS BATCH HAD,
    not that player's own best week -- a per-player scale made a 1-2-3-4 week
    render bar-for-bar identical to a 10-20-30-40 week (both close on their
    own personal high), which is exactly backwards: the bars should carry
    absolute magnitude, the same way the numeric columns beside them already
    do. `trend_total` sums the window and `trend_avg` (PPG over that same
    span) divides it back down -- a short early-season window otherwise makes
    `trend_total` look weak for reasons that have nothing to do with the
    player, and PPG is the fairer number to sort or compare by across
    different weeks.
    """
    from . import scoring

    if not entries:
        return
    wk = int(week)
    lo = max(1, wk - trend_weeks + 1)
    # Dedupe: a player picked up by more than one roster over the season (drop,
    # re-add elsewhere) appears as more than one `entries` row sharing the same
    # player_id (waiver_ledger is one row per manager x player). Scoring a
    # duplicated id list makes score_lineup emit that many copies of every
    # week's line, which groupby("player_id") then lumps together undeduped --
    # every entry sharing the id read a multiplied trend. Each id is only
    # priced once; every entry sharing it looks the single result up.
    ids = list(dict.fromkeys(e["player_id"] for e in entries))
    sc = scoring.score_lineup(ids, s.season, range(lo, wk + 1), rules)
    by_id = {pid: g.sort_values("week")[["week", "points"]].to_dict("records")
            for pid, g in sc.groupby("player_id")}
    top_pt = max((t["points"] for tr in by_id.values() for t in tr), default=0) or 1
    for r in entries:
        tr = by_id.get(r["player_id"], [])
        for t in tr:
            t["pct"] = round(max(6.0, min(100.0, t["points"] / top_pt * 100)), 0)
        r["trend"] = tr
        r["trend_total"] = round(sum(t["points"] for t in tr), 1)
        r["trend_avg"] = round(r["trend_total"] / len(tr), 1) if tr else 0.0


def _fa_who_could_use(starters: pd.DataFrame, pos: str, points: float) -> list[dict]:
    """Every manager this free agent would have outscored their OWN weakest
    same-position starter with that week, gain descending -- "who could have
    used this" as a full list (for the drilldown) rather than naming only the
    single weakest team league-wide. `starters` is that week's starters merged
    with user_name; one row per manager (their weakest starter at `pos`) is
    compared, so a manager appears at most once. Carries `started_player`/
    `started_pts` so the drilldown can say exactly who they'd have replaced,
    not just the point gain.
    """
    same_pos = starters[starters["position"] == pos]
    if not len(same_pos):
        return []
    weak = same_pos.loc[same_pos.groupby("user_name")["points"].idxmin()]
    out = []
    for r in weak.itertuples():
        gain = points - float(r.points)
        if gain > 0:
            out.append({"user_name": r.user_name, "gain": round(gain, 1),
                       "started_player": r.player_name,
                       "started_pts": round(float(r.points), 1)})
    out.sort(key=lambda x: -x["gain"])
    return out


def free_agent_standouts(s: Season, week: int, per_position: int = 5,
                         trend_weeks: int = 4) -> list[dict]:
    """The week's best performances by players on NOBODY's roster.

    A single flattened top-N across the whole player pool would bury the
    shallow positions (a QB1 read and a kicker read are different questions),
    so this takes the `per_position` best AT EACH position -- but returns them
    flat, `position` included as a field on every entry, meant for a single
    sortable table (sort by position to see one position at a time; sort by
    points/trend_total/trend_avg for the league-wide read) rather than
    pre-grouped panels. Sleeper's stats endpoint carries every NFL player's
    raw stat line for the week regardless of roster status; `s.pl_wk` only
    ever has rostered players (every other week_* metric relies on that), so
    "free agent" here is simply "scored this week, but absent from every
    roster that week." Priced with the league's own scoring chart
    (`scoring.rules_from`) -- the same primitive `playoffs.py` uses to score
    hand-submitted lineups Sleeper never rostered either, so pricing an
    unrostered player this way is proven.

    `best_fit` lists EVERY manager (via `_fa_who_could_use`) whose own weakest
    same-position starter this standout would have beaten that week, gain
    descending -- not just the single weakest team league-wide, since more
    than one manager can usually stand to gain. For ONE manager's own view,
    see `free_agent_impact` instead.

    Returns a flat list sorted by `points` descending (a sensible default
    before the reader re-sorts); each position gets at most `per_position`
    entries, so a shallow position still shows up without flooding the table.
    """
    rows, rules = _fa_candidates(s, week)
    if not rows:
        return []

    by_pos: dict = {}
    for pos in POSITIONS:
        cand = sorted((r for r in rows if r["position"] == pos), key=lambda r: -r["points"])
        if cand:
            by_pos[pos] = cand[:per_position]
    all_top = [e for lst in by_pos.values() for e in lst]
    if not all_top:
        return []

    wk = int(week)
    pl = s.pl_wk[s.pl_wk["week"] == wk]
    starters = pl[pl["is_starter"]]
    if not s.user_map.empty:
        starters = starters.merge(s.user_map[["roster_id", "user_name"]],
                                  on="roster_id", how="left")
    for r in all_top:
        r["best_fit"] = _fa_who_could_use(starters, r["position"], r["points"])

    _fa_trend(s, week, all_top, rules, trend_weeks)
    return sorted(all_top, key=lambda r: -r["points"])


def free_agent_impact(s: Season, week: int, manager: str, per_position: int = 5,
                      trend_weeks: int = 4) -> list[dict]:
    """Free agents that would have beaten something in ONE manager's OWN
    starting lineup that week -- the manager-scoped view of the weekly
    report cuts straight to "would this have helped ME", rather than
    restating `free_agent_standouts`' league-wide top performers, most of
    whom have nothing to do with this manager's own roster.

    Unlike `free_agent_standouts`' `best_fit` (every manager who could have
    used it), this compares every unrostered scorer against only THIS
    manager's own same-position starter(s) that week. `best_fit` is still a
    list (kept the same shape as `free_agent_standouts` so both feed the same
    table template) but holds at most the one entry for `manager`.

    A weak starter (say a kicker who scored 4) clears a low bar for almost
    anyone -- so this keeps only the `per_position` biggest gains at each
    position, same shape as `free_agent_standouts`' cap, rather than every
    free agent that cleared it at all. Entries are sorted by gain descending
    -- the most impactful swaps first -- rather than by raw points, since
    "impact on this roster" is the question this view answers.
    """
    wk = int(week)
    rows, rules = _fa_candidates(s, week)
    if not rows or s.user_map.empty:
        return []
    m = s.user_map[s.user_map["user_name"] == manager]
    if not len(m):
        return []
    rid = m["roster_id"].iloc[0]
    pl = s.pl_wk[s.pl_wk["week"] == wk]
    mine = pl[(pl["is_starter"]) & (pl["roster_id"] == rid)]
    if mine.empty:
        return []

    by_pos: dict = {}
    for r in rows:
        same_pos = mine[mine["position"] == r["position"]]
        if not len(same_pos):
            continue
        weak = same_pos.loc[same_pos["points"].idxmin()]
        gain = r["points"] - float(weak["points"])
        if gain <= 0:
            continue
        r = dict(r)
        r["best_fit"] = [{"user_name": manager, "gain": round(gain, 1),
                          "started_player": weak["player_name"],
                          "started_pts": round(float(weak["points"]), 1)}]
        by_pos.setdefault(r["position"], []).append(r)
    if not by_pos:
        return []

    out = []
    for pos, cand in by_pos.items():
        cand.sort(key=lambda r: -r["best_fit"][0]["gain"])
        out.extend(cand[:per_position])

    out.sort(key=lambda r: -r["best_fit"][0]["gain"])
    _fa_trend(s, week, out, rules, trend_weeks)
    return out


def free_agent_best_team(s: Season, week: int) -> dict | None:
    """The best possible starting lineup built ENTIRELY from that week's free
    agents -- "what if you'd drafted the waiver wire" -- and whether it would
    have beaten any actual team's score.

    Reuses the same roster-aware solver every real lineup in this codebase is
    graded against (`optimal_lineup`/`assign_slots`, season.py), just handed
    the free-agent pool instead of a manager's roster, so it fills the
    league's actual slot counts (FLEX/SUPER_FLEX/etc. included) rather than
    assuming a fixed shape. `beats` lists every real team this hypothetical
    roster would have outscored that week, gain descending -- empty means it
    wouldn't have beaten anyone, which is itself the point some weeks.
    """
    from .season import assign_slots, optimal_lineup

    wk = int(week)
    rows, _ = _fa_candidates(s, week)
    if not rows:
        return None
    df = pd.DataFrame(rows)
    picks = optimal_lineup(df, s.slots)
    if picks.empty:
        return None
    picks = assign_slots(picks, s.slots)
    total = round(float(picks["points"].sum()), 1)

    tw = s.team_wk[s.team_wk["week"] == wk]
    beats = [{"user_name": r.user_name, "points": round(float(r.points), 1),
             "gain": round(total - float(r.points), 1)}
            for r in tw.sort_values("points").itertuples(index=False)
            if float(r.points) < total]
    beats.sort(key=lambda x: -x["gain"])

    fa_lineup = [{"slot": r.slot, "player_id": r.player_id,
                  "player_name": r.player_name, "position": r.position,
                  "points": round(float(r.points), 1)}
                 for r in picks.itertuples(index=False)]

    # Per-team comparison, slot-matched against the FA lineup and coloured the
    # same way as the scoreboard's own two-lineup drilldown (`cmp` up/down/even
    # per slot), so a manager can eyeball exactly where the FA team would have
    # beaten their real one.
    fa_pts_by_slot = {r["slot"]: r["points"] for r in fa_lineup}
    plw = (s.pl_wk[s.pl_wk["week"] == wk]
           .merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")
           if len(s.pl_wk) else s.pl_wk)
    teams = []
    for r in tw.sort_values("points", ascending=False).itertuples(index=False):
        g = plw[plw["user_name"] == r.user_name] if len(plw) else plw
        st = g[g["is_starter"]] if len(g) else g
        team_pts_by_slot, team_lineup = {}, []
        if len(st):
            for x in assign_slots(st, s.slots).itertuples(index=False):
                team_pts_by_slot[x.slot] = float(x.points)
                team_lineup.append({"slot": x.slot, "player_id": x.player_id,
                                    "player_name": x.player_name, "points": float(x.points)})
        for p in team_lineup:
            opp = fa_pts_by_slot.get(p["slot"])
            p["cmp"] = (None if opp is None else
                       "up" if p["points"] > opp else
                       "down" if p["points"] < opp else "even")
        cmp_fa = []
        for p in fa_lineup:
            opp = team_pts_by_slot.get(p["slot"])
            cmp_fa.append(dict(p, cmp=(None if opp is None else
                               "up" if p["points"] > opp else
                               "down" if p["points"] < opp else "even")))
        # Second comparison: the FA lineup against what this team's OWN full
        # roster (bench included) could have started -- "what if they'd
        # played it perfectly" rather than what they actually ran out. Same
        # solver as the FA lineup itself, just handed this team's players.
        opt_pts_by_slot, opt_lineup = {}, []
        if len(g):
            opt_picks = optimal_lineup(g, s.slots)
            if not opt_picks.empty:
                opt_picks = assign_slots(opt_picks, s.slots)
                for x in opt_picks.itertuples(index=False):
                    opt_pts_by_slot[x.slot] = float(x.points)
                    opt_lineup.append({"slot": x.slot, "player_id": x.player_id,
                                       "player_name": x.player_name, "points": float(x.points)})
        for p in opt_lineup:
            opp = fa_pts_by_slot.get(p["slot"])
            p["cmp"] = (None if opp is None else
                       "up" if p["points"] > opp else
                       "down" if p["points"] < opp else "even")
        cmp_fa_opt = []
        for p in fa_lineup:
            opp = opt_pts_by_slot.get(p["slot"])
            cmp_fa_opt.append(dict(p, cmp=(None if opp is None else
                              "up" if p["points"] > opp else
                              "down" if p["points"] < opp else "even")))
        opt_total = round(sum(p["points"] for p in opt_lineup), 1) if opt_lineup else None
        teams.append({"user_name": r.user_name, "points": round(float(r.points), 1),
                      "gain": round(total - float(r.points), 1),
                      "lineup": team_lineup, "fa_lineup": cmp_fa,
                      "opt_lineup": opt_lineup, "fa_opt_lineup": cmp_fa_opt,
                      "opt_points": opt_total,
                      "opt_gain": (round(total - opt_total, 1) if opt_total is not None else None)})

    # How many teams' OPTIMAL lineups (not just what they actually ran out)
    # the FA total would still have beaten -- the Optimized-mode counterpart
    # to `beats`, derived from `teams` rather than a second team_wk pass.
    opt_beats = sum(1 for t in teams if t["opt_points"] is not None and t["opt_points"] < total)

    return {
        "total": total, "lineup": fa_lineup,
        "beats": beats, "n_teams": int(len(tw)), "teams": teams,
        "opt_beats": opt_beats,
    }
