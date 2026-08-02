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
         "player_id", "player_name", "position", "points", "weeks", "ppg",
         "pos_pick_rank", "pos_value_rank", "steal", "total", "mixed", "pos_rank",
         "pos_repl", "pos_repl_ppg", "pos_adj", "pos_steal",
         "value_rank", "redraft_round"]


def _position_share(s: Season) -> dict:
    """Per-team starter allocation at each position: fixed roster slots plus
    a share of any FLEX-type slot the position is eligible for, split evenly
    across however many positions share that FLEX label. Shared by
    `_replacement_level` (times team count, for the LEAGUE-WIDE startable
    pool size) and `redraft_board` (as a per-TEAM bench-cap unit) -- both
    are really asking the same question, "how many of this position does a
    roster actually have room for", just at different scopes.

    Returns {position: starter_share}.
    """
    share = {p: float(s.slots.get(p, 0)) for p in POSITIONS}
    for lab, elig in _FLEX_ELIG.items():
        pool = [p for p in elig if p in POSITIONS]
        n = float(s.slots.get(lab, 0))
        if pool and n:
            for p in pool:
                share[p] += n / len(pool)
    return share


def _replacement_level(s: Season, ranks: dict) -> dict:
    """Replacement-level true-season points at each position -- the value of
    the Nth-ranked player leaguewide, N sized to how many starting slots
    this league actually has for that position (fixed slots, plus a share of
    any FLEX-type slot the position is eligible for), times the team count.
    Standard fantasy VORP ("value over replacement") definition: what you
    could get for free off the wire, not an average of the startable tier.

    `ranks` (from `metrics.season_position_ranks`) prices EVERY real NFL
    player who recorded a stat line that season -- hundreds deep, most of
    them practice-squad-level. This asks "how much better than the WORST
    startable option at the position was he", the same bar a manager
    actually drafts against.

    Deliberately NOT the mean of the top N (an earlier version of this used
    the mean, and it was wrong): the mean is skewed upward by elite outliers,
    so even a legitimately good top-half starter can read as "below average"
    purely because a stud at the top pulls the mean up. Confirmed on real
    2025 data: Matthew Stafford finished the season as the league's QB6 (a
    clearly startable season in an only-10-team league) with 326.7 true
    points, yet the OLD mean-of-top-10 baseline was 328.5 -- ahead of him --
    purely because Josh Allen's outlier 385.6 pulled the mean up. The
    10th-ranked QB's own total (287.9, this function's actual output) sits
    correctly below QB6, with no such distortion.

    Returns {position: replacement_level_points}.
    """
    team_count = max(len(s.user_map), 1)
    share = _position_share(s)

    by_pos: dict = {}
    for r in ranks.values():
        by_pos.setdefault(r["position"], []).append(r["points"])

    out: dict = {}
    for pos in POSITIONS:
        vals = sorted(by_pos.get(pos, []), reverse=True)
        pool_size = max(1, round(team_count * share.get(pos, 0)))
        top = vals[:pool_size] if vals else []
        out[pos] = round(top[-1], 1) if top else 0.0
    return out


def _value_ranks(s: Season, ranks: dict) -> dict:
    """{player_id: 1-indexed rank by TRUE value across EVERY position, most
    valuable first -- the order a "redraft by results" would use. Ranked by
    `pos_adj` (points above that player's OWN position's replacement level,
    see `_replacement_level`), not raw points: raw points would reintroduce
    the exact cross-position volume bias `pos_steal` was built to avoid (a
    mediocre QB outscoring a good RB/WR/TE purely on this format's scoring
    scale, the 2025 Cam Ward bug -- see `draft_board`'s docstring). `pos_adj`
    is already normalized to be comparable across positions, which is what
    makes a single flat cross-position board defensible here where it
    wasn't for `pos_steal`.

    Returns {player_id: rank}; feeds both the actual board's round-based
    highlight and `redraft_board()`'s player pool.
    """
    repl = _replacement_level(s, ranks)
    scored = sorted(ranks.items(),
                     key=lambda kv: kv[1]["points"] - repl.get(kv[1]["position"], 0.0),
                     reverse=True)
    return {pid: i + 1 for i, (pid, _) in enumerate(scored)}


def _season_trend(s: Season, player_ids) -> dict:
    """{player_id: [weekly points, ...]} across the WHOLE season (postseason
    included, one entry per week regardless of roster status) for the small
    inline sparkline on gems/busts/undrafted.

    Same pricing primitive as `total`/`pos_adj` -- every real NFL stat line,
    priced by the league's own scoring chart -- not `pl_wk`, which would go
    missing for weeks a player sat unrostered and break the shape. Cheap
    despite spanning the whole season: `scoring.nfl_stats` caches one fetch
    per week regardless of how many ids ask for it, and this is normally
    called once for the whole gems/busts/undrafted batch (tens of ids, not
    hundreds), not per row.
    """
    from . import scoring

    ids = list(dict.fromkeys(str(p) for p in player_ids if pd.notna(p)))
    if not ids:
        return {}
    rules = scoring.rules_from(s.league_id)
    sc = scoring.score_lineup(ids, s.season, range(1, s.last_week_all + 1), rules)
    return {pid: g.sort_values("week")["points"].round(1).tolist()
            for pid, g in sc.groupby("player_id")}


def _sparkline(weekly: list, ref: float, width: float = 56, height: float = 16,
               pad: float = 1.5) -> dict:
    """A ready-to-render sparkline for `weekly`: short line segments coloured
    green above / red below `ref`, plus `ref`'s own y position for a dashed
    reference line.

    `ref` is the position's replacement-level PPG (see `_replacement_level`),
    NOT this player's own average: a player who
    scored zero every week has an own-average of zero too, so a "0 >= own
    average" test reads every scoreless week as "above average" and colours
    the whole flat line green -- exactly backwards for someone who did
    nothing. Grading against an external, position-appropriate bar instead
    means a zero week reads as red (below a startable option), which is what
    it actually was.

    Floored at 0 (not the row's own min) so a scoreless week reads as flat
    baseline rather than being stretched into a false dip. The vertical
    scale is `max(this player's own best week, ref)`, not just his own max
    (unlike the free-agent trend bars, which share one batch-wide max for
    cross-player magnitude) -- a player who never once reached `ref` still
    needs it to fit on the chart, or the dashed line would sit off the top
    edge instead of visibly above every week's bar.

    A segment that crosses `ref` is split at the exact crossing point
    (screen-space `y` is a linear function of value, so the split is exact,
    not approximated) so the green/red boundary lands where the line
    actually crosses, not at the nearest week.

    Returns {} for an empty series (nothing to draw), otherwise
    {"avg_y": float, "segs": [{"x1","y1","x2","y2","up": bool}, ...]}.
    """
    if not weekly:
        return {}
    n = len(weekly)
    hi = max(max(weekly), ref, 0.0) or 1.0
    step = width / max(n - 1, 1)
    usable = height - 2 * pad

    def y_of(v: float) -> float:
        return pad + usable * (1 - max(v, 0) / hi)

    xs = [round(i * step, 1) for i in range(n)]
    ys = [round(y_of(v), 1) for v in weekly]
    ref_y = round(y_of(ref), 1)

    segs = []
    for i in range(n - 1):
        x0, y0, v0 = xs[i], ys[i], weekly[i]
        x1, y1, v1 = xs[i + 1], ys[i + 1], weekly[i + 1]
        side0, side1 = v0 >= ref, v1 >= ref
        if side0 == side1 or y0 == y1:
            segs.append({"x1": x0, "y1": y0, "x2": x1, "y2": y1, "up": side0})
        else:
            t = (y0 - ref_y) / (y0 - y1)
            xc = round(x0 + t * (x1 - x0), 1)
            segs.append({"x1": x0, "y1": y0, "x2": xc, "y2": ref_y, "up": side0})
            segs.append({"x1": xc, "y1": ref_y, "x2": x1, "y2": y1, "up": side1})
    return {"avg_y": ref_y, "segs": segs}


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
    rostered = (s.pl_wk.groupby(["roster_id", "player_id"], as_index=False)
                .agg(points=("points", "sum"), weeks=("week", "nunique")))
    d = d.merge(rostered, on=["roster_id", "player_id"], how="left")
    d["points"] = d["points"].fillna(0.0).round(1)
    # ppg = points per week actually on THIS roster -- a rate, not a total,
    # so a pick traded/dropped mid-season doesn't read as unproductive next
    # to one that sat on the same roster all year.
    d["ppg"] = (d["points"] / d["weeks"].fillna(0).clip(lower=1)).round(1)

    # Standard "round.pick" draft notation needs the pick WITHIN the round
    # (1..team count), not the overall pick_no -- `pick_no` is sequential
    # across the whole draft, so round 13's pick_no ranges into the 100s+ and
    # printing it straight as "13.123" was never a real draft slot. Derived
    # from pick_no/team_count directly rather than round arithmetic, so it's
    # right regardless of any round-numbering quirk in the source data.
    d = d.sort_values("pick_no").reset_index(drop=True)
    team_count = int(d["draft_slot"].nunique()) or 1
    d["pick_in_round"] = (((d["pick_no"] - 1) % team_count) + 1).astype("Int64")

    # `total` is the player's TRUE full season output -- every real NFL stat
    # line he had, priced by the league's own scoring chart, regardless of
    # whether anyone in this league rostered or started him that week.
    # Deliberately NOT `pl_wk`-derived (unlike `points`, the drafting team's
    # own roster-accumulated total): `pl_wk` only has rows for weeks a player
    # was actually on a roster in this league, so a player who got dropped
    # and sat unrostered for a stretch would silently lose those weeks.
    ranks = metrics.season_position_ranks(s)
    pid = d["player_id"].astype(str)
    d["total"] = pid.map(lambda p: ranks[p]["points"] if p in ranks else 0.0).round(1)
    # `pos_rank`: where he finished at his position leaguewide -- "RB #4" --
    # from the SAME true-season pricing as `total`, so the two numbers can't
    # disagree with each other. A player who never recorded a stat line has
    # no rank (nullable; filled below only for the `pos_steal` arithmetic,
    # never shown filled -- an unresolved rank stays genuinely blank).
    d["pos_rank"] = pid.map(lambda p: ranks[p]["rank"] if p in ranks else None).astype("Int64")

    # Steal metrics are POSITION-scoped, not draft-wide: ranking a QB's
    # points against a draft full of RB/WR/TE picks compares different
    # currencies (QBs score far more raw points in this format), which let a
    # legitimately bad late QB (2025's Cam Ward: pick 162, the WORST QB
    # drafted by both `total` and `pos_adj`) still read as a huge "gem" by
    # merely out-scoring RB/WR bench fliers taken in the same range. Ranking
    # WITHIN position instead means every comparison below is QB-vs-QB,
    # RB-vs-RB, etc. -- and once ranking is scoped that way, there is no
    # longer a separate "adjust for position, THEN re-rank" step needed
    # (an earlier version of this had one, `adj_steal`): subtracting a
    # position's own constant baseline before ranking can't change the
    # order versus ranking the raw value directly within that same
    # position, so the two-step version collapsed into this one-step one.
    #
    # `pos_pick_rank`: this player's order among picks AT HIS OWN POSITION
    # (1 = first QB taken, etc). `.fillna("UNK")` on the GROUPING key (not
    # the data) guards a pick whose position never resolved from silently
    # losing its rank -- it still ranks, just within its own one-pick group.
    grp_pos = d["position"].fillna("UNK")
    d["pos_pick_rank"] = d.groupby(grp_pos)["pick_no"].rank(method="first").astype(int)
    # `pos_value_rank`: this player's rank WITHIN position by `points` (what
    # the drafting team actually banked) -- the team-realized counterpart to
    # `pos_rank` (his true finish).
    d["pos_value_rank"] = (d.groupby(grp_pos)["points"]
                            .rank(ascending=False, method="first").astype(int))
    # `steal`: team-realized value vs draft slot, now position-scoped.
    d["steal"] = (d["pos_pick_rank"] - d["pos_value_rank"]).astype(int)
    # `pos_steal`: the TRUE-value equivalent -- `pos_pick_rank` vs `pos_rank`
    # instead of `pos_value_rank`. Pairing `steal`/`pos_steal` isolates a bad
    # PLAYER (both negative) from a bad DECISION (pos_steal fine, steal
    # deeply negative -- the team gave up on someone who kept producing). A
    # player with no stat line at all (`pos_rank` null) is filled with a
    # rank one worse than the deepest ranked player at that position, not
    # left null (which would silently drop him from the comparison) --
    # "never recorded a stat line" is itself the worst possible outcome.
    #
    # The finish side (`pos_rank`) is then capped at how many players were
    # actually DRAFTED at this position, not left at the full real-NFL
    # universe's raw size -- that universe is hundreds of players deep and a
    # very different size per position (2025: 337 real WRs recorded a stat
    # line vs. 193 real RBs, simply because more NFL teams roll out
    # replacement-level WRs than RBs on a given week). Left uncapped, that
    # size mismatch alone can make a deep-universe position's bust dwarf an
    # equally- or more-deserved bust at a shallower one: 2025's Brandon
    # Aiyuk (WR, pick 14.07, 0 true points) read -219, while Joe Mixon (RB,
    # pick 9.02, also 0 points but drafted with real mid-draft capital --
    # 30th of 48 RBs taken, a full 5 rounds earlier than Aiyuk's 50th of 58
    # WRs) read only -129 -- backwards from what actually happened once you
    # account for how much draft capital each represented. Once a player is
    # worse than the LAST one anyone at his position actually bothered to
    # draft, further real-world bench depth doesn't make the pick any more
    # of a bust, so capping there -- not an arbitrary multiplier, this is
    # already a real, known number -- fixes it: Mixon reads -18, worse than
    # Aiyuk's -8, while Cam Ward (the cross-position case above) stays
    # correctly negative (-1) rather than flipping to a false gem.
    worst_rank: dict = {}
    for r in ranks.values():
        worst_rank[r["position"]] = max(worst_rank.get(r["position"], 0), r["rank"])
    fallback_rank = d["position"].map(lambda p: worst_rank.get(str(p).upper(), 0) + 1)
    drafted_n = d["position"].dropna().astype(str).str.upper().value_counts()
    finish_cap = d["position"].map(lambda p: drafted_n.get(str(p).upper(), 1))
    pos_rank_for_steal = (d["pos_rank"].astype(float).fillna(fallback_rank)
                           .clip(upper=finish_cap.astype(float)))
    d["pos_steal"] = (d["pos_pick_rank"] - pos_rank_for_steal).astype(int)
    # `mixed`: `steal` and `pos_steal` disagree in sign -- a good pick FOR
    # THIS TEAM that wasn't actually a good player at his position, or the
    # reverse (a fine player this team just didn't get value from, usually
    # via trade/drop). Either way the verdict depends on which number you
    # look at, which is worth flagging rather than leaving buried in two
    # side-by-side columns.
    d["mixed"] = (((d["steal"] > 0) & (d["pos_steal"] < 0))
                  | ((d["steal"] < 0) & (d["pos_steal"] > 0)))

    # Position-adjusted value: how far above/below REPLACEMENT LEVEL at his
    # position his true season output was, rather than raw points -- see
    # `_replacement_level`. Rewards value found at a scarce position (a
    # strong TE clears a lower bar than a strong RB) instead of just volume.
    repl = _replacement_level(s, ranks)
    d["pos_repl"] = d["position"].map(lambda p: repl.get(str(p).upper(), 0.0)).round(1)
    d["pos_adj"] = (d["total"] - d["pos_repl"]).round(1)
    # Same baseline as a per-week rate -- the reference the Trend sparkline
    # grades against, since a player's own average is meaningless for
    # someone who did nothing all season (see _sparkline's docstring).
    d["pos_repl_ppg"] = (d["pos_repl"] / max(s.last_week_all, 1)).round(1)

    # `value_rank`/`redraft_round`: where this player's TRUE cross-position
    # value (see `_value_ranks`) would place him in a redraft using the SAME
    # round size as the real draft -- what the board's highlight and the
    # Redraft toggle (`redraft_board()`) both compare against `round`. A
    # player who never recorded a stat line has no value_rank; he's filled
    # one worse than the whole ranked universe (same "never produced = worst
    # possible outcome" convention as `pos_steal`'s fallback above), not left
    # null, so a bust that scored zero doesn't silently drop out of the
    # comparison.
    vranks = _value_ranks(s, ranks)
    d["value_rank"] = pid.map(vranks).fillna(len(ranks) + 1).astype(int)
    d["redraft_round"] = (((d["value_rank"] - 1) // team_count) + 1).astype(int)
    return _cache.setdefault(key, d[_COLS].copy())


def redraft_board(s: Season) -> pd.DataFrame:
    """The Draft tab's round x slot grid, but filled by a SIMULATED
    value-based draft instead of the order picks were actually made: walking
    the real draft's own pick sequence and team ownership in order, each
    team takes the best remaining player BY TRUE VALUE (see `_value_ranks`)
    at a position it hasn't already filled -- so a team still ends up with a
    real, playable roster, not just the globally best-ranked names crammed
    into its slots regardless of position. `orig_round`/`orig_pick` record
    where (if anywhere) that player really went -- both `None` when he
    actually went undrafted -- so a cell can be annotated "(originally R3)"
    or "(undrafted)" for direct comparison against the real board.

    Per-team position caps come from the SAME starter-slot share
    `_replacement_level` already computes (fixed slots plus a FLEX-eligible
    share), doubled as a bench allowance: a position with 1 real starter
    slot (K, DEF) caps at 2 per team, a RB/WR-type slot with FLEX sharing
    caps around 4-5. Without a cap, an earlier version of this just laid the
    globally-ranked list straight into the real pick sequence regardless of
    which team owned each slot, which could easily stack one team with, say,
    4 defenses -- there is only ever 1 DEF START.

    Answers "if this draft happened again knowing the results, who would
    each team actually draft, playing to win" -- e.g. a player taken in
    round 3 whose season was round-1-worthy shows up in round 1 here.

    Returns the same empty-frame shape as `draft_board()` when there's no
    real draft to size the grid against.
    """
    board = draft_board(s)
    if board.empty:
        return board
    ranks = metrics.season_position_ranks(s)
    repl = _replacement_level(s, ranks)
    vranks = _value_ranks(s, ranks)
    pos_of = {pid: r["position"] for pid, r in ranks.items()}

    # Per-team, per-position cap: 2x the position's own starter share (see
    # `_position_share`) -- a real bench allowance for a skill position,
    # effectively "starter + one backup" for a single-slot position like
    # K/DEF where a second one has no value.
    share = _position_share(s)
    pos_cap = {p: max(1, round(2 * share.get(p, 0))) for p in POSITIONS}

    pinfo = players()
    names = (pinfo.dropna(subset=["player_id"]).drop_duplicates("player_id")
             .assign(player_id=lambda x: x["player_id"].astype(str))
             .set_index("player_id")["player_name"])
    orig = board.set_index(board["player_id"].astype(str))

    seats = board.sort_values("pick_no")[
        ["pick_no", "round", "pick_in_round", "draft_slot", "roster_id", "user_name"]
    ].reset_index(drop=True)

    remaining = [pid for pid, _ in sorted(vranks.items(), key=lambda kv: kv[1])]
    team_counts: dict = {}
    rows = []
    for _, seat_row in seats.iterrows():
        seat = seat_row.to_dict()
        counts = team_counts.setdefault(int(seat["draft_slot"]), {})
        pick_idx = next(
            (i for i, pid in enumerate(remaining)
             if counts.get(pos_of.get(pid), 0) < pos_cap.get(pos_of.get(pid), 1)),
            0 if remaining else None)  # fall back to best-remaining if every
        if pick_idx is None:            # candidate is capped for this team
            break
        pid = remaining.pop(pick_idx)
        pos = pos_of.get(pid)
        counts[pos] = counts.get(pos, 0) + 1
        o = orig.loc[pid] if pid in orig.index else None
        rows.append({
            **seat,
            "player_id": pid,
            "player_name": names.get(pid, pid),
            "position": pos,
            "total": round(ranks[pid]["points"], 1),
            "pos_rank": ranks[pid]["rank"],
            "pos_adj": round(ranks[pid]["points"] - repl.get(pos, 0.0), 1),
            "orig_round": int(o["round"]) if o is not None and pd.notna(o["round"]) else None,
            "orig_pick": (f"{int(o['round'])}.{int(o['pick_in_round']):02d}"
                          if o is not None and pd.notna(o["round"]) else None),
        })
    return pd.DataFrame(rows)


def draft_extremes(s: Season, n: int | None = None) -> dict:
    """The draft's biggest gems and busts, by TRUE value against draft
    position AT THAT PLAYER'S OWN POSITION.

    Ranked and gated on `pos_steal` alone -- draft-slot rank vs. finish
    rank AT HIS OWN POSITION (see `draft_board`'s docstring) -- not `steal`
    (the team-realized equivalent, which a trade or drop can starve
    regardless of how good the player actually was: `steal`/`points` still
    ride along on every row, and `mixed` flags where the two disagree, but
    neither decides who makes the list) and deliberately not blended with
    `pos_adj` either. A "bust" is about whether the pick lived up to WHERE
    HE WAS TAKEN, not whether he happened to still be a useful position-wise
    contributor in absolute terms -- those are different questions, and
    `pos_adj` answers the second one (it still rides along on every row so a
    reader can check it, just doesn't decide inclusion or rank). An earlier
    version blended the two into a single `pos_grade`, but that let a mild,
    even negligible, `pos_steal` still top the list purely on `pos_adj`'s
    raw points (2025's Josh Allen, pick 2.06, `pos_steal` of just +1 --
    essentially no real rank surprise -- still read as the #1 "gem" under
    the blend, because he's simply a great player in absolute terms). Pure
    `pos_steal` avoids that at the cost of a real, known artifact: two picks
    who both fall out of the drafted pool read identically once `pos_steal`
    is capped there, however differently bad their real outputs were (2025's
    Joe Mixon, 0 points, and Omarion Hampton, 149.2 points, both landed at
    -18) -- accepted as the tradeoff for keeping the metric strictly about
    draft-slot performance.

    GEMS and BUSTS are each gated on `pos_steal` clearing a full ROUND's
    worth of rank movement (this season's team count) before being ranked --
    a pick must have beaten (gems) or missed (busts) his OWN draft slot by a
    real, non-trivial margin to qualify at all, not just any nonzero amount.
    A bare sign check (`pos_steal` > 0 / < 0) let Josh Allen's negligible +1
    through as easily as a real 20-spot swing; a full round is the same
    "one round" unit this season's `_replacement_level` pool sizing and the
    draft board's own highlight threshold already use, so a 1-spot beat
    doesn't count as a surprise.

    n=None (the default) means NO cap beyond the gate itself -- every pick
    that clears the round-magnitude bar is included, however many that is;
    the table scrolls, and the draft's own size already hard-caps how many
    picks COULD qualify. An earlier version capped the list at a 15%-of-draft
    share (10-30 picks) on top of the gate, which silently dropped real,
    gate-clearing picks once a season had more than that many notable ones --
    verified wrong on real data across all 4 seasons (2024: 52 busts cleared
    the gate, only 21 were ever shown). `n` still accepts an explicit count
    for callers that want a fixed-size slice (e.g. `draft_standouts()`'s
    `n=1` for its headline tile).

    `trend` is a ready-to-render sparkline of the player's real weekly output
    all season -- see `_sparkline` -- green above / red below `pos_repl_ppg`
    (the position's own replacement-level PPG, not this player's own
    average, which is meaningless for someone who scored nothing all
    season), split at the exact crossing point, so a boom/bust or
    slow-build shape is visible at a glance without a separate chart.

    Returns {"gems": [...], "busts": [...]} as plain records, or empty lists
    for a season with no draft data.
    """
    empty = {"gems": [], "busts": []}
    d = draft_board(s)
    if d.empty:
        return empty
    d = d[d["player_name"].notna()].copy()
    if d.empty:
        return empty
    d["pick"] = d.apply(
        lambda r: f"{int(r['round'])}.{int(r['pick_in_round']):02d}"
        if pd.notna(r["round"]) and pd.notna(r["pick_in_round"]) else "—", axis=1)
    # `points`/`total`/`steal`/`pos_steal`/`mixed`/`pos_rank`/`pos_adj`/
    # `pos_repl_ppg` all come straight from draft_board() -- see its
    # docstring for what each compares.
    cols = ["pick", "pick_no", "player_id", "player_name", "position", "pos_rank",
            "user_name", "points", "ppg", "pos_repl_ppg", "total", "steal", "pos_steal",
            "pos_adj", "mixed", "trend"]
    # Gate + rank, both on `pos_steal` -- see docstring for why a full round
    # (this season's team count) is the gate and why `pos_adj` isn't blended in.
    # `n` (default None) only trims further if a caller explicitly asks for a
    # fixed-size slice; otherwise every gate-clearing pick is kept.
    team_count = int(d["draft_slot"].nunique()) or 1
    gems = d[d["pos_steal"] >= team_count].sort_values(
        ["pos_steal", "total"], ascending=[False, False]).copy()
    busts = d[d["pos_steal"] <= -team_count].sort_values(
        ["pos_steal", "total"], ascending=[True, True]).copy()
    if n is not None:
        gems = gems.head(n)
        busts = busts.head(n)
    weekly_by_id = _season_trend(s, pd.concat([gems["player_id"], busts["player_id"]]))
    for frame in (gems, busts):
        frame["trend"] = frame.apply(
            lambda r: _sparkline(weekly_by_id.get(str(r["player_id"]), []), r["pos_repl_ppg"]),
            axis=1)
    # Selected by `pos_grade` above, but DISPLAYED in draft order (pick_no)
    # rather than re-sorted by severity -- once the list is already narrowed
    # to the notable picks, reading it in the order the draft actually
    # happened is easier to scan (the ranked-by-severity view is already a
    # click away via the sortable header).
    gems = gems.sort_values("pick_no")
    busts = busts.sort_values("pick_no")
    return {"gems": gems[cols].to_dict("records"),
            "busts": busts[cols].to_dict("records")}


def undrafted_standouts(s: Season, n: int = 25) -> pd.DataFrame:
    """The best players who went UNDRAFTED -- the flip side of gems & busts.

    Nobody spent a pick on them, yet they produced. `points` is what he
    accumulated on a roster in this league -- every week he sat on one,
    started or benched, same "roster-accumulated" definition draft_board()
    uses for its own `points`; `ppg` is that same total as a rate (points
    per week actually rostered), which the UI shows instead since it reads
    better for pickups that were only rostered for part of the season. A
    churned pickup can touch several rosters, so `teams` counts how many
    rostered him and `user_name` is the manager who got the most out of
    him. `total`/`pos_rank` are his TRUE full season output and leaguewide
    position finish, same pricing as draft_board()'s (regardless of
    rostering at all). Returns an empty frame when there is no draft to
    define "undrafted" against, or no roster data.

    n=25 (up from an earlier 10): the table scrolls in the UI now, so there's
    room to show more without the tab getting longer.

    `pos_adj` is the same position-adjusted read draft_board() computes for
    drafted picks -- `total` minus a replacement-level baseline at the
    position -- so an undrafted find and a drafted pick can be compared on
    the same footing there too. `pos_steal` extends that comparison to the
    same RANK-based metric drafted picks get: an undrafted player has no
    real pick to compare against, so his implicit `pos_pick_rank` is one
    worse than the LAST player drafted at his position (going undrafted at
    all is worse than being the last pick at that position) -- against
    which `pos_rank` (his true finish) reads exactly like a drafted pick's
    `pos_steal` does. This is what makes Matthew Stafford, undrafted but the
    season's QB6, read as a large legitimate steal instead of the negative
    number the old absolute-only comparison gave him. `pos_repl_ppg` (the
    replacement baseline as a rate) and `trend` are the same ready-to-render
    weekly-shape sparkline draft_extremes() attaches to gems/busts.
    """
    cols = ["player_id", "player_name", "position", "pos_rank", "user_name",
            "teams", "weeks", "points", "ppg", "pos_repl_ppg", "total", "pos_adj",
            "pos_steal", "trend"]
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
    repl = _replacement_level(s, ranks)
    pos_repl = per["position"].map(lambda p: repl.get(str(p).upper(), 0.0) if pd.notna(p) else 0.0)
    per["pos_adj"] = (per["total"] - pos_repl).round(1)
    per["pos_repl_ppg"] = (pos_repl / max(s.last_week_all, 1)).round(1)
    # `pos_steal`: same formula draft_board() uses -- implicit `pos_pick_rank`
    # is one worse than the LAST player actually drafted at this position
    # (going undrafted is worse than being that last pick), against `pos_rank`
    # (his true finish), capped at that same drafted count -- see
    # draft_board()'s docstring for why the finish side is capped there
    # (the WR-universe-vs-RB-universe size mismatch).
    drafted_pos_counts = (board["position"].dropna().astype(str).str.upper()
                           .value_counts().to_dict())
    per["pos_pick_rank"] = per["position"].map(
        lambda p: drafted_pos_counts.get(str(p).upper(), 0) + 1 if pd.notna(p) else 0)
    worst_rank: dict = {}
    for r in ranks.values():
        worst_rank[r["position"]] = max(worst_rank.get(r["position"], 0), r["rank"])
    fallback_rank = per["position"].map(lambda p: worst_rank.get(str(p).upper(), 0) + 1)
    finish_cap = per["position"].map(
        lambda p: drafted_pos_counts.get(str(p).upper(), 1) if pd.notna(p) else 1)
    pos_rank_for_steal = (per["pos_rank"].astype(float).fillna(fallback_rank)
                           .clip(upper=finish_cap.astype(float)))
    per["pos_steal"] = (per["pos_pick_rank"] - pos_rank_for_steal).astype(int)
    per = (per.sort_values("points", ascending=False).head(n)
           .reset_index().rename(columns={"pid": "player_id"}))
    weekly_by_id = _season_trend(s, per["player_id"])
    per["trend"] = per.apply(
        lambda r: _sparkline(weekly_by_id.get(str(r["player_id"]), []), r["pos_repl_ppg"]),
        axis=1)
    # Selected above by roster-accumulated `points` (who actually delivered
    # for a real team), but DISPLAYED by `pos_steal` -- the same "+/-" rank
    # read drafted picks are ordered by, so a reader scanning down the table
    # sees the biggest true finds first rather than whoever happened to sit
    # on the most productive roster longest.
    per = per.sort_values("pos_steal", ascending=False).reset_index(drop=True)
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
