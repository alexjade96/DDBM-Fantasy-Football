"""Draft data: the historical draft board + pick-value analytics.

Sleeper exposes a league's draft(s) at `/league/{id}/drafts` and the picks at
`/draft/{id}/picks`. None of the rest of the package touches this, so it lives
here and is fetched lazily (only when the Draft tab / a draft chart is drawn),
not baked into the hot season-assembly path.

Pick *value* is what the drafting team actually got: the player's started points
for that roster over the season (from the season's `pl_wk`). That lets a pick be
called a steal or a bust relative to where it was taken.
"""
from __future__ import annotations

import pandas as pd

from .api import sleeper_api
from .players import players
from .season import Season

# Small cache so re-opening the Draft tab doesn't re-hit the API each time.
_cache: dict = {}

_COLS = ["round", "pick_no", "draft_slot", "roster_id", "user_name",
         "player_id", "player_name", "position", "points", "value_rank",
         "steal"]


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLS)


def draft_board(s: Season) -> pd.DataFrame:
    """One row per pick for a season's draft, valued by started points.

    Best-effort: a league/season with no draft (or a private one) returns an
    empty frame, and the caller shows a "no draft" panel rather than erroring.
    """
    key = f"{s.league_id}:{s.season}"
    if key in _cache:
        return _cache[key]
    try:
        drafts = sleeper_api(f"/league/{s.league_id}/drafts") or []
        if not drafts:
            _cache[key] = _empty()
            return _cache[key]
        # A league season normally has exactly one draft; if more, take the
        # completed one with the most picks.
        did = sorted(drafts, key=lambda dr: dr.get("settings", {}).get("rounds", 0),
                     reverse=True)[0]["draft_id"]
        picks = sleeper_api(f"/draft/{did}/picks") or []
    except Exception:
        _cache[key] = _empty()
        return _cache[key]
    if not picks:
        _cache[key] = _empty()
        return _cache[key]

    pinfo = players()
    rows = []
    for p in picks:
        meta = p.get("metadata") or {}
        pid = p.get("player_id")
        rows.append({
            "round": p.get("round"),
            "pick_no": p.get("pick_no"),
            "draft_slot": p.get("draft_slot"),
            "roster_id": p.get("roster_id"),
            "player_id": pid,
            # Prefer the season player DB, fall back to the pick's own metadata.
            "meta_name": " ".join(x for x in (meta.get("first_name"),
                                              meta.get("last_name")) if x).strip(),
            "meta_pos": meta.get("position"),
        })
    d = pd.DataFrame(rows)
    d["roster_id"] = pd.to_numeric(d["roster_id"], errors="coerce").astype("Int64")
    d = d.merge(pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
    d["player_name"] = d["player_name"].fillna(d["meta_name"]).replace("", pd.NA)
    d["position"] = d["position"].fillna(d["meta_pos"])
    d = d.merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left")

    # Value = started points the drafting roster got from the pick this season.
    started = (s.pl_wk[s.pl_wk["is_starter"]]
               .groupby(["roster_id", "player_id"], as_index=False)["points"].sum()
               .rename(columns={"points": "points"}))
    d = d.merge(started, on=["roster_id", "player_id"], how="left")
    d["points"] = d["points"].fillna(0.0).round(1)

    # Steal score: how far the pick outperformed its slot. Rank picks by value
    # (1 = most points); a positive gap over the overall pick number means the
    # player returned more than where they were taken.
    d = d.sort_values("pick_no").reset_index(drop=True)
    d["value_rank"] = d["points"].rank(ascending=False, method="first").astype(int)
    d["steal"] = (d["pick_no"] - d["value_rank"]).astype(int)
    return _cache.setdefault(key, d[_COLS].copy())


def _points_elsewhere(s: Season, d: pd.DataFrame) -> pd.Series:
    """Started points each drafted player scored for OTHER rosters that season.

    "Was he dropped?" is nearly circular for a bust -- returning little to the
    drafting team usually means being cut. What actually separates a misjudged
    player from a misjudged *decision* is whether he went on to produce for
    somebody else, which is what this measures.
    """
    pl = s.pl_wk
    if not {"roster_id", "player_id", "is_starter",
            "points"}.issubset(getattr(pl, "columns", [])):
        return pd.Series(0.0, index=d.index)
    st = pl[pl["is_starter"]]
    tot = st.groupby(st["player_id"].astype(str))["points"].sum()
    mine = (st.groupby([st["player_id"].astype(str), st["roster_id"]])["points"]
            .sum())
    out = []
    for pid, rid in zip(d["player_id"], d["roster_id"]):
        pid = str(pid)
        here = float(mine.get((pid, rid), 0.0))
        out.append(round(float(tot.get(pid, 0.0)) - here, 1))
    return pd.Series(out, index=d.index)


def draft_extremes(s: Season, n: int = 8) -> dict:
    """The draft's biggest gems and busts, by value against draft position.

    Ranked on `steal` (pick number minus value rank), which self-corrects for
    where a pick was taken: a late flier that returns nothing scores near zero,
    while a first-rounder that returns nothing scores deeply negative. So busts
    surface early picks that failed, not merely players who scored little.

    Returns {"gems": [...], "busts": [...]} as plain records, or empty lists for
    a season with no draft data.
    """
    d = draft_board(s)
    if d.empty:
        return {"gems": [], "busts": []}
    d = d[d["player_name"].notna()].copy()
    if d.empty:
        return {"gems": [], "busts": []}
    d["pick"] = d.apply(
        lambda r: f"{int(r['round'])}.{int(r['pick_no'])}"
        if pd.notna(r["round"]) and pd.notna(r["pick_no"]) else "—", axis=1)
    # Value counts points started FOR THE DRAFTING ROSTER, so a player traded
    # away in week 5 scores near zero here however well he played afterwards.
    # Carrying what he scored elsewhere keeps that visible: it distinguishes a
    # player who was simply bad from one the team gave up on.
    d["elsewhere"] = _points_elsewhere(s, d)
    cols = ["pick", "pick_no", "player_id", "player_name", "position", "user_name",
            "points", "steal", "elsewhere"]
    gems = d.sort_values(["steal", "points"], ascending=[False, False]).head(n)
    busts = d.sort_values(["steal", "points"], ascending=[True, True]).head(n)
    return {"gems": gems[cols].to_dict("records"),
            "busts": busts[cols].to_dict("records")}


def undrafted_standouts(s: Season, n: int = 10) -> pd.DataFrame:
    """The best players who went UNDRAFTED -- the flip side of gems & busts.

    Nobody spent a pick on them, yet they started and scored. `points` is a
    player's total started points across the regular season; a churned pickup can
    touch several rosters, so `teams` counts how many started him and `user_name`
    is the manager who got the most out of him. Returns an empty frame when there
    is no draft to define "undrafted" against, or no starter data.
    """
    cols = ["player_id", "player_name", "position", "user_name", "teams", "starts", "points"]
    board = draft_board(s)
    # Without a draft, every player looks "undrafted" -- which is meaningless, so
    # only compute this against a real draft board.
    if board.empty:
        return pd.DataFrame(columns=cols)
    drafted = set(board["player_id"].dropna().astype(str))
    pl = s.pl_wk
    if not {"player_id", "is_starter", "points", "roster_id",
            "week"}.issubset(getattr(pl, "columns", [])):
        return pd.DataFrame(columns=cols)
    st = pl[pl["is_starter"]].copy()
    if st.empty:
        return pd.DataFrame(columns=cols)
    st["pid"] = st["player_id"].astype(str)
    st = st[~st["pid"].isin(drafted)]
    if st.empty:
        return pd.DataFrame(columns=cols)
    per = st.groupby("pid").agg(
        points=("points", "sum"), starts=("week", "nunique"),
        player_name=("player_name", "first"), position=("position", "first"))
    # Primary manager = whoever the player scored the most STARTED points for.
    by_team = (st.groupby(["pid", "roster_id"], as_index=False)["points"].sum()
               .merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left"))
    top = by_team.sort_values("points", ascending=False).drop_duplicates("pid").set_index("pid")
    per["user_name"] = top["user_name"]
    per["teams"] = by_team.groupby("pid")["roster_id"].nunique()
    per = per[per["player_name"].notna()]
    if per.empty:
        return pd.DataFrame(columns=cols)
    per["points"] = per["points"].round(1)
    per = (per.sort_values("points", ascending=False).head(n)
           .reset_index().rename(columns={"pid": "player_id"}))
    return per[cols]


def draft_grades(s: Season) -> pd.DataFrame:
    """Per-manager draft production: total started points from drafted players."""
    d = draft_board(s)
    if d.empty:
        return pd.DataFrame(columns=["user_name", "picks", "points", "ppp", "hits"])
    g = d.groupby("user_name", as_index=False).agg(
        picks=("pick_no", "count"), points=("points", "sum"),
        hits=("points", lambda x: int((x >= 100).sum())))   # 100+ pt seasons
    g["points"] = g["points"].round(1)
    g["ppp"] = (g["points"] / g["picks"].clip(lower=1)).round(1)
    return g.sort_values("points", ascending=False).reset_index(drop=True)


def clear_draft_cache() -> None:
    _cache.clear()
