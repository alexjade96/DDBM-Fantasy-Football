"""Descriptive metric tables (pure compute; mirrors R metrics.R)."""
from __future__ import annotations

import pandas as pd

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


def efficiency(s: Season) -> pd.DataFrame:
    g = s.lineup.groupby("user_name", as_index=False).agg(
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


def power_rank(s: Season, weights: dict | None = None, recent: int = 3) -> pd.DataFrame:
    """Composite power ranking (mirrors R sl_power_rank).

    A z-scored blend of points for, all-play win%, recent form, and lineup
    efficiency. The composite is left unrounded (mean/sd derived); round on
    display, per the project's parity discipline.
    """
    w = weights or {"points": 0.35, "allplay": 0.30, "form": 0.20, "eff": 0.15}

    def z(x: pd.Series) -> pd.Series:
        sd = x.std()
        if pd.isna(sd) or sd == 0:
            return pd.Series(0.0, index=x.index)
        return (x - x.mean()) / sd

    maxwk = s.team_wk["week"].max()
    form = (s.team_wk[s.team_wk["week"] > maxwk - recent]
            .groupby("user_name", as_index=False).agg(form=("points", "mean")))
    eff = efficiency(s)[["user_name", "eff"]]
    d = s.standings[["user_name", "points", "allplay_w", "allplay_l"]].copy()
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


def strength_of_schedule(s: Season) -> pd.DataFrame:
    """Average scoring strength of the opponents each team actually faced.

    Opponent strength is that opponent's season-long PPG (not their score in the
    one week you met), so a team that keeps drawing the league's best has a high
    SOS regardless of the weekly noise.
    """
    ppg = s.team_wk.groupby("roster_id")["points"].mean()
    d = s.team_wk.dropna(subset=["opp"]).copy()
    d["opp_ppg"] = d["opp"].map(ppg)
    g = d.groupby("user_name", as_index=False).agg(sos=("opp_ppg", "mean"))
    own = (s.team_wk.groupby("user_name", as_index=False)["points"].mean()
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
_WAIVER_COLS = ["week", "user_name", "player_name", "position", "via",
                "times", "points", "starts", "weeks_rostered"]


def _pts_by_player_roster(s: Season) -> dict:
    """{(player_id, roster_id): points scored while on that roster}.

    pl_wk records roster membership week by week, so this already splits a
    traded player's season between the teams that held him -- no transaction
    stint reconstruction needed.
    """
    pl = s.pl_wk
    if not {"player_id", "roster_id", "points"}.issubset(getattr(pl, "columns", [])):
        return {}
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


def waiver_ledger(s: Season, top_n: int | None = 30) -> pd.DataFrame:
    """Waiver / free-agent pickups, one row per player per manager.

    Collapsed to unique (manager, player): a player picked up, cut and picked up
    again is one story, and `points` is already a per-(player, roster) total, so
    separate rows would repeat the same figure. `times` records the churn.
    """
    t = _live_tx(s, ["waiver", "free_agent"])
    if t.empty:
        return pd.DataFrame(columns=_WAIVER_COLS)
    adds = t[t["transaction"] == "add"]
    if adds.empty:
        return pd.DataFrame(columns=_WAIVER_COLS)
    pts = _pts_by_player_roster(s)
    names = dict(zip(s.user_map["roster_id"], s.user_map["user_name"]))
    pl = s.pl_wk
    have = {"roster_id", "player_id", "is_starter", "week"}.issubset(
        getattr(pl, "columns", []))
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
            "player_name": first["player_name"],
            "position": first.get("position"),
            "via": "/".join(kinds), "times": len(g),
            "points": round(pts.get((pid, rid), 0.0), 1),
            "starts": starts, "weeks_rostered": weeks,
        })
    d = (pd.DataFrame(rows).sort_values("points", ascending=False)
         .reset_index(drop=True))
    return d.head(top_n) if top_n else d
