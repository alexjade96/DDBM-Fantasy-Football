"""Draft data: the historical draft board + pick-value analytics.

Sleeper exposes a league's draft(s) at `/league/{id}/drafts` and the picks at
`/draft/{id}/picks`. None of the rest of the package touches this, so it lives
here and is fetched lazily (only when the Draft tab / a draft chart is drawn),
not baked into the hot season-assembly path.

Pick *value* is what the drafting team actually got: every point the player put
up while on that roster, started or benched (from the season's `pl_wk`). That
lets a pick be called a steal or a bust relative to where it was taken.
"""
from __future__ import annotations

import pandas as pd

from . import metrics
from .api import sleeper_api
from .players import players
from .season import Season, POSITIONS, _FLEX_ELIG

# Small cache so re-opening the Draft tab doesn't re-hit the API each time.
_cache: dict = {}

_COLS = ["round", "pick_no", "pick_in_round", "draft_slot", "roster_id", "user_name",
         "player_id", "player_name", "position", "points", "value_rank",
         "steal", "total", "total_rank", "total_steal", "mixed", "pos_rank",
         "pos_avg", "pos_adj", "adj_rank", "adj_steal"]


def _startable_pool_avg(s: Season, ranks: dict) -> dict:
    """Average true-season points among the STARTABLE tier at each position --
    the top N players leaguewide, N sized to how many starting slots this
    league actually has for that position (fixed slots, plus a share of any
    FLEX-type slot the position is eligible for), times the team count.

    `ranks` (from `metrics.season_position_ranks`) prices EVERY real NFL
    player who recorded a stat line that season -- hundreds deep, most of
    them practice-squad-level. A flat average across that whole pool sits
    near zero and would make every real fantasy starter look like a huge
    "position-adjusted" outperformer; this instead asks "how much better
    than a startable option at the position was he", the same bar a manager
    actually drafts against.

    Returns {position: avg_points}.
    """
    team_count = max(len(s.user_map), 1)
    share = {p: float(s.slots.get(p, 0)) for p in POSITIONS}
    for lab, elig in _FLEX_ELIG.items():
        pool = [p for p in elig if p in POSITIONS]
        n = float(s.slots.get(lab, 0))
        if pool and n:
            for p in pool:
                share[p] += n / len(pool)

    by_pos: dict = {}
    for r in ranks.values():
        by_pos.setdefault(r["position"], []).append(r["points"])

    out: dict = {}
    for pos in POSITIONS:
        vals = sorted(by_pos.get(pos, []), reverse=True)
        pool_size = max(1, round(team_count * share.get(pos, 0)))
        top = vals[:pool_size] if vals else []
        out[pos] = round(sum(top) / len(top), 1) if top else 0.0
    return out


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=_COLS)


def draft_board(s: Season) -> pd.DataFrame:
    """One row per pick for a season's draft, valued by points accumulated on
    the drafting roster.

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

    # Value = points the drafting roster accumulated from the pick this
    # season -- every week he sat on THIS roster, started or benched, not
    # just weeks he started. Distinct from `total` below (every point he
    # scored anywhere, on any roster or none).
    rostered = (s.pl_wk.groupby(["roster_id", "player_id"], as_index=False)["points"].sum())
    d = d.merge(rostered, on=["roster_id", "player_id"], how="left")
    d["points"] = d["points"].fillna(0.0).round(1)

    # Steal score: how far the pick outperformed its slot. Rank picks by value
    # (1 = most points); a positive gap over the overall pick number means the
    # player returned more than where they were taken.
    d = d.sort_values("pick_no").reset_index(drop=True)
    d["value_rank"] = d["points"].rank(ascending=False, method="first").astype(int)
    d["steal"] = (d["pick_no"] - d["value_rank"]).astype(int)
    # Standard "round.pick" draft notation needs the pick WITHIN the round
    # (1..team count), not the overall pick_no -- `pick_no` is sequential
    # across the whole draft, so round 13's pick_no ranges into the 100s+ and
    # printing it straight as "13.123" was never a real draft slot. Derived
    # from pick_no/team_count directly rather than round arithmetic, so it's
    # right regardless of any round-numbering quirk in the source data.
    team_count = int(d["draft_slot"].nunique()) or 1
    d["pick_in_round"] = (((d["pick_no"] - 1) % team_count) + 1).astype("Int64")

    # `total` is the player's TRUE full season output -- every real NFL stat
    # line he had, priced by the league's own scoring chart, regardless of
    # whether anyone in this league rostered or started him that week.
    # Deliberately NOT `pl_wk`-derived (unlike `points`, the drafting team's
    # own roster-accumulated total): `pl_wk` only has rows for weeks a player
    # was actually on a roster in this league, so a player who got dropped
    # and sat unrostered for a stretch would silently lose those weeks. `total_steal`
    # is the same pick-number-vs-rank comparison as `steal`, just ranked by
    # `total` instead: pairing the two isolates a bad PLAYER (both negative)
    # from a bad DECISION (total_steal fine, steal deeply negative -- the
    # team gave up on someone who kept producing).
    ranks = metrics.season_position_ranks(s)
    pid = d["player_id"].astype(str)
    d["total"] = pid.map(lambda p: ranks[p]["points"] if p in ranks else 0.0).round(1)
    d["total_rank"] = d["total"].rank(ascending=False, method="first").astype(int)
    d["total_steal"] = (d["pick_no"] - d["total_rank"]).astype(int)
    # `mixed`: steal and total_steal disagree in sign -- a good pick FOR THIS
    # TEAM that wasn't actually a good player, or the reverse (a fine player
    # this team just didn't get value from, usually via trade/drop). Either
    # way the verdict depends on which number you look at, which is worth
    # flagging rather than leaving buried in two side-by-side columns.
    d["mixed"] = (((d["steal"] > 0) & (d["total_steal"] < 0))
                  | ((d["steal"] < 0) & (d["total_steal"] > 0)))
    # `pos_rank`: where he finished at his position leaguewide -- "RB #4" --
    # from the SAME true-season pricing as `total`, so the two numbers can't
    # disagree with each other. A player who never recorded a stat line has
    # no rank.
    d["pos_rank"] = pid.map(lambda p: ranks[p]["rank"] if p in ranks else None).astype("Int64")
    # Position-adjusted value: how far above/below a STARTABLE option at his
    # position his true season output was, rather than raw points -- see
    # `_startable_pool_avg`. Rewards value found at a scarce position (a
    # strong TE clears a lower bar than a strong RB) instead of just volume,
    # and gives `total_steal` a second, position-aware read via `adj_steal`.
    baseline = _startable_pool_avg(s, ranks)
    d["pos_avg"] = d["position"].map(lambda p: baseline.get(str(p).upper(), 0.0)).round(1)
    d["pos_adj"] = (d["total"] - d["pos_avg"]).round(1)
    d["adj_rank"] = d["pos_adj"].rank(ascending=False, method="first").astype(int)
    d["adj_steal"] = (d["pick_no"] - d["adj_rank"]).astype(int)
    return _cache.setdefault(key, d[_COLS].copy())


def draft_extremes(s: Season, n: int | None = None) -> dict:
    """The draft's biggest gems and busts, by TRUE value against draft position.

    Ranked on `total_steal` (pick number minus the rank of `total`, the
    player's true full season output) rather than `steal` (ranked by roster-
    accumulated points, which a trade or drop can starve regardless of how
    good the player actually was) -- so a pick who was drafted well but
    mismanaged away still surfaces as a gem, and a genuinely bad pick can't
    hide behind having been kept on the bench. `steal`/`points` still ride
    along on every row (and `mixed` flags where the two disagree), so the
    team-realized side of the story isn't lost, just not what decides who
    makes the list.

    n defaults to a SHARE of the draft (15%, clamped to 10..30) rather than a
    flat count: a 9-team/10-round draft (~90 picks) and a 12-team/17-round one
    (~170) shouldn't surface the same absolute number of "notable" picks, and
    the list is meant to scroll rather than hard-cut at some arbitrary size.
    A value/|steal| floor was considered instead of a count, but steal is a
    rank difference and ties among 0-point picks (a large share of any draft)
    swing wildly despite being equally unremarkable, so a value cutoff
    wouldn't actually trim the list any more meaningfully than this does.

    `adj_gems`/`adj_busts` are the same picks re-ranked on `adj_steal` (pick
    number vs. the rank of `pos_adj` -- true points above a STARTABLE option
    at that position, not raw points) instead of `total_steal`: a grading
    variant that rewards value found at a scarce position rather than just
    volume, so a great TE finish can outrank a great RB finish even if the
    RB scored more raw points.

    Returns {"gems": [...], "busts": [...], "adj_gems": [...], "adj_busts":
    [...]} as plain records, or empty lists for a season with no draft data.
    """
    empty = {"gems": [], "busts": [], "adj_gems": [], "adj_busts": []}
    d = draft_board(s)
    if d.empty:
        return empty
    d = d[d["player_name"].notna()].copy()
    if d.empty:
        return empty
    if n is None:
        n = int(min(30, max(10, round(len(d) * 0.15))))
    d["pick"] = d.apply(
        lambda r: f"{int(r['round'])}.{int(r['pick_in_round']):02d}"
        if pd.notna(r["round"]) and pd.notna(r["pick_in_round"]) else "—", axis=1)
    # `points`/`total`/`steal`/`total_steal`/`mixed`/`pos_rank` all come
    # straight from draft_board() -- see its docstring for what each compares.
    cols = ["pick", "pick_no", "player_id", "player_name", "position", "pos_rank",
            "user_name", "points", "total", "steal", "total_steal", "mixed"]
    adj_cols = ["pick", "pick_no", "player_id", "player_name", "position", "pos_rank",
                "user_name", "total", "pos_avg", "pos_adj", "adj_steal"]
    gems = d.sort_values(["total_steal", "total"], ascending=[False, False]).head(n)
    busts = d.sort_values(["total_steal", "total"], ascending=[True, True]).head(n)
    adj_gems = d.sort_values(["adj_steal", "pos_adj"], ascending=[False, False]).head(n)
    adj_busts = d.sort_values(["adj_steal", "pos_adj"], ascending=[True, True]).head(n)
    return {"gems": gems[cols].to_dict("records"),
            "busts": busts[cols].to_dict("records"),
            "adj_gems": adj_gems[adj_cols].to_dict("records"),
            "adj_busts": adj_busts[adj_cols].to_dict("records")}


def undrafted_standouts(s: Season, n: int = 25) -> pd.DataFrame:
    """The best players who went UNDRAFTED -- the flip side of gems & busts.

    Nobody spent a pick on them, yet they produced. `points` is what he
    accumulated on a roster in this league -- every week he sat on one,
    started or benched, same "roster-accumulated" definition draft_board()
    uses for its own `points`. A churned pickup can touch several rosters, so
    `teams` counts how many rostered him and `user_name` is the manager who
    got the most out of him. `total`/`pos_rank` are his TRUE full season
    output and leaguewide position finish, same pricing as draft_board()'s
    (regardless of rostering at all). Returns an empty frame when there is no
    draft to define "undrafted" against, or no roster data.

    n=25 (up from an earlier 10): the table scrolls in the UI now, so there's
    room to show more without the tab getting longer.
    """
    cols = ["player_id", "player_name", "position", "pos_rank", "user_name",
            "teams", "weeks", "points", "ppg", "total"]
    board = draft_board(s)
    # Without a draft, every player looks "undrafted" -- which is meaningless, so
    # only compute this against a real draft board.
    if board.empty:
        return pd.DataFrame(columns=cols)
    drafted = set(board["player_id"].dropna().astype(str))
    pl = s.pl_wk
    if not {"player_id", "points", "roster_id",
            "week"}.issubset(getattr(pl, "columns", [])):
        return pd.DataFrame(columns=cols)
    st = pl.copy()
    if st.empty:
        return pd.DataFrame(columns=cols)
    st["pid"] = st["player_id"].astype(str)
    st = st[~st["pid"].isin(drafted)]
    if st.empty:
        return pd.DataFrame(columns=cols)
    per = st.groupby("pid").agg(
        points=("points", "sum"), weeks=("week", "nunique"),
        player_name=("player_name", "first"), position=("position", "first"))
    # Primary manager = whoever accumulated the most points off him.
    by_team = (st.groupby(["pid", "roster_id"], as_index=False)["points"].sum()
               .merge(s.user_map[["roster_id", "user_name"]], on="roster_id", how="left"))
    top = by_team.sort_values("points", ascending=False).drop_duplicates("pid").set_index("pid")
    per["user_name"] = top["user_name"]
    per["teams"] = by_team.groupby("pid")["roster_id"].nunique()
    per = per[per["player_name"].notna()]
    if per.empty:
        return pd.DataFrame(columns=cols)
    per["points"] = per["points"].round(1)
    per["ppg"] = (per["points"] / per["weeks"].clip(lower=1)).round(1)
    # `total`/`pos_rank`: same true-season pricing as draft_board(), so an
    # undrafted find and a drafted pick can be compared on equal footing.
    ranks = metrics.season_position_ranks(s)
    pid_series = per.index.to_series()
    total_vals = pid_series.map(lambda p: ranks[p]["points"] if p in ranks else None)
    per["total"] = pd.to_numeric(total_vals, errors="coerce").fillna(per["points"]).round(1)
    rank_vals = pid_series.map(lambda p: ranks[p]["rank"] if p in ranks else None)
    per["pos_rank"] = pd.to_numeric(rank_vals, errors="coerce").astype("Int64")
    per = (per.sort_values("points", ascending=False).head(n)
           .reset_index().rename(columns={"pid": "player_id"}))
    return per[cols]


def draft_grades(s: Season) -> pd.DataFrame:
    """Per-manager draft production: total roster points from drafted players,
    alongside `total` -- the SAME picks' true full season output, regardless
    of whether this team ever benefited from it. The gap between the two is
    value traded or dropped away; `plot_draft_grades_value` charts it.
    """
    d = draft_board(s)
    if d.empty:
        return pd.DataFrame(columns=["user_name", "picks", "points", "total", "ppp", "hits"])
    g = d.groupby("user_name", as_index=False).agg(
        picks=("pick_no", "count"), points=("points", "sum"), total=("total", "sum"),
        hits=("points", lambda x: int((x >= 100).sum())))   # 100+ pt seasons
    g["points"] = g["points"].round(1)
    g["total"] = g["total"].round(1)
    g["ppp"] = (g["points"] / g["picks"].clip(lower=1)).round(1)
    return g.sort_values("points", ascending=False).reset_index(drop=True)


def draft_standouts(s: Season) -> list[dict]:
    """Draft superlatives as {label, value, holder, detail} tiles.

    Every other tab (Coaching, Roster, Transactions, ...) leads with a row of
    headline tiles before its charts; Draft was the one exception. This reuses
    data draft_extremes()/draft_grades()/undrafted_standouts() already compute
    for the rest of the tab -- no new aggregation, just reshaped into tiles.
    """
    ex = draft_extremes(s, n=1)
    gems, busts = ex["gems"], ex["busts"]
    if not gems and not busts:
        return []
    out: list[dict] = []

    def tile(label, value, holder, detail=""):
        out.append({"label": label, "value": value, "holder": holder, "detail": detail})

    if gems:
        g = gems[0]
        tile("Best steal", f"{g['total']:.0f} pts", g["user_name"],
             f"{g['player_name']} · pick {g['pick']}")
    if busts:
        b = busts[0]
        tile("Worst bust", f"{b['total']:.0f} pts", b["user_name"],
             f"{b['player_name']} · pick {b['pick']}")
    grades = draft_grades(s)
    if len(grades):
        top = grades.iloc[0]
        tile("Top-grading manager", f"{top['points']:.0f} pts", top["user_name"],
             f"{int(top['hits'])} hits · {top['ppp']:.1f} pts/pick")
        worst = grades.iloc[-1]
        if worst["user_name"] != top["user_name"]:
            tile("Lowest-grading manager", f"{worst['points']:.0f} pts", worst["user_name"],
                 f"{int(worst['hits'])} hits · {worst['ppp']:.1f} pts/pick")
    und = undrafted_standouts(s, n=1)
    if len(und):
        u = und.iloc[0]
        tile("Best undrafted find", f"{u['points']:.0f} pts", u["user_name"],
             f"{u['player_name']} · went undrafted")
    return out


def clear_draft_cache() -> None:
    _cache.clear()
