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

import json
import os
from pathlib import Path

import pandas as pd

from . import metrics
from .api import sleeper_api, sleeper_adp
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


_ADP_FIELDS = ("adp_std", "adp_half_ppr", "adp_ppr", "adp_2qb")
# season/adp/ -- a sibling of season/<league_id>/ (the custom playoff bracket
# configs -- see playoffs.py's config_paths()), under the SAME repo-root
# `season/` directory and the SAME SLEEPERMETRICS_SEASON_DIR override, so
# both kinds of durable season data live in one place instead of two
# separate directories. ADP itself stays season-scoped, not league-scoped
# (Sleeper publishes one ADP set per season for the whole platform, unlike a
# playoff bracket, which genuinely differs per league) -- hence its own
# subfolder rather than living inside any one league's own files. Checked
# into the repo, not gitignored: its whole purpose is to be the fallback a
# later offline run (or a future run after Sleeper changes/removes the
# endpoint) can still read.
_SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR", str(Path(__file__).resolve().parents[2] / "season")))
_ADP_CACHE_DIR = _SEASON_DIR / "adp"
_adp_cache: dict = {}   # {season: {player_id: {...}}} -- see _fetch_adp_raw


def _adp_snapshot_path(season) -> Path:
    return _ADP_CACHE_DIR / f"{season}.json"


def _fetch_adp_raw(season) -> dict:
    """{player_id: {"player_name", "position", "adp_std", "adp_half_ppr",
    "adp_ppr", "adp_2qb"}} for a season, from Sleeper's undocumented
    per-season ADP endpoint (see api.sleeper_adp) -- the same data its own
    draft lobby reads from. Season-scoped, not league-scoped (Sleeper
    publishes one ADP set per season across the whole platform).

    Live-fetched first; on success the trimmed result is written to a
    per-season on-disk snapshot (`season/adp/<season>.json`) so a later run
    with no network -- or after Sleeper ever changes/removes this
    undocumented endpoint -- still has the latest successfully-captured
    data to fall back to, the same durable-JSON-file idea `season/<league_id>/
    <season>.json` uses for hand-submitted brackets (this snapshot is instead
    auto-refreshed, not hand-edited). Only players with a real ADP in AT
    LEAST ONE format are kept (Sleeper's sentinel for "no ADP here" is a
    literal 999.0, not a missing key) -- the rest are draft/mock-only depth
    that would just bloat the snapshot for no benefit.

    Falls back to the on-disk snapshot if the live fetch fails for any
    reason (network, non-2xx, malformed body); returns {} only if BOTH the
    live fetch and the snapshot are unavailable -- same "degrade, don't
    error" contract as draft_board(). Memoized per season for the life of
    the process.
    """
    season = str(season)
    if season in _adp_cache:
        return _adp_cache[season]
    path = _adp_snapshot_path(season)
    try:
        raw = sleeper_adp(season)
        out = {}
        for row in raw:
            pid = row.get("player_id")
            if not pid:
                continue
            stats = row.get("stats") or {}
            vals = {f: stats.get(f) for f in _ADP_FIELDS}
            if not any(v is not None and v < 999 for v in vals.values()):
                continue
            p = row.get("player") or {}
            out[str(pid)] = {
                "player_name": (" ".join(x for x in (p.get("first_name"), p.get("last_name"))
                                         if x).strip() or None),
                "position": p.get("position"),
                **vals,
            }
        _ADP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
        return _adp_cache.setdefault(season, out)
    except Exception:
        pass
    try:
        out = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        out = {}
    return _adp_cache.setdefault(season, out)


def _adp_field_for(s: Season) -> str:
    """Which of Sleeper's four ADP variants matches this league's own
    format -- from its actual roster slots and scoring, not assumed. A
    league starting 2+ QB-eligible players (a fixed 2-QB slot, or a
    SUPER_FLEX/QB-eligible flex) uses `adp_2qb` (Sleeper doesn't cross that
    with a PPR axis -- one field covers it); otherwise picked by the
    league's own `rec` (reception) scoring weight: >=0.75 full PPR, <=0.25
    standard, else half-PPR.
    """
    from . import scoring

    slots = getattr(s, "slots", {}) or {}
    qb_slots = slots.get("QB", 0) + sum(
        slots.get(lab, 0) for lab, elig in _FLEX_ELIG.items() if "QB" in elig)
    if qb_slots >= 2:
        return "adp_2qb"
    rec = scoring.rules_from(s.league_id).get("rec") or 0.0
    if rec >= 0.75:
        return "adp_ppr"
    if rec <= 0.25:
        return "adp_std"
    return "adp_half_ppr"


def redraft_board_adp(s: Season) -> pd.DataFrame:
    """Same round x slot grid as redraft_board(), but the draft order comes
    from Sleeper's own published ADP for the season (see _fetch_adp_raw)
    instead of TRUE season value -- "what a draft following the field's
    actual pre-season consensus would have looked like", as opposed to
    redraft_board()'s "what a draft knowing the results would have looked
    like". Same real pick sequence/team ownership and the same per-team
    position caps (`_position_share`, doubled -- see redraft_board's
    docstring) as redraft_board(); only the pool order differs, and
    POSITION for the walk comes from Sleeper's own player record on each
    ADP row (covers rookies/players who never recorded a real stat line
    this season, unlike `ranks`, which only has players who did) rather
    than `metrics.season_position_ranks`. The outcome columns
    (`total`/`pos_rank`/`pos_adj`, and `orig_round`/`orig_pick`) are still
    the player's TRUE season result, same as redraft_board()'s, so an ADP
    pick can still be judged against how the position actually played out.

    A player with no real ADP in this league's format (or not covered by
    the endpoint at all) sorts after every player who has one -- same
    "worse than the last real entry" fallback `_value_ranks()` uses for a
    player with no true-season stat line.

    Returns the same empty-frame shape as draft_board() when there's no
    real draft, or no ADP data at all (live fetch AND on-disk snapshot both
    unavailable), to build the grid against.
    """
    board = draft_board(s)
    if board.empty:
        return board
    adp_raw = _fetch_adp_raw(s.season)
    if not adp_raw:
        return _empty()
    field = _adp_field_for(s)

    ranks = metrics.season_position_ranks(s)
    repl = _replacement_level(s, ranks)
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

    pos_of = {pid: row.get("position") for pid, row in adp_raw.items()
             if row.get("position") in POSITIONS}

    def adp_of(pid):
        v = adp_raw.get(pid, {}).get(field)
        return v if v is not None and v < 999 else None

    remaining = sorted((pid for pid in pos_of if adp_of(pid) is not None), key=adp_of)
    remaining += sorted(pid for pid in pos_of if adp_of(pid) is None)

    team_counts: dict = {}
    rows = []
    for _, seat_row in seats.iterrows():
        seat = seat_row.to_dict()
        counts = team_counts.setdefault(int(seat["draft_slot"]), {})
        pick_idx = next(
            (i for i, pid in enumerate(remaining)
             if counts.get(pos_of.get(pid), 0) < pos_cap.get(pos_of.get(pid), 1)),
            0 if remaining else None)
        if pick_idx is None:
            break
        pid = remaining.pop(pick_idx)
        pos = pos_of.get(pid)
        counts[pos] = counts.get(pos, 0) + 1
        o = orig.loc[pid] if pid in orig.index else None
        r = ranks.get(pid)
        pts = r["points"] if r else 0.0
        rows.append({
            **seat,
            "player_id": pid,
            "player_name": names.get(pid, adp_raw.get(pid, {}).get("player_name", pid)),
            "position": pos,
            "total": round(pts, 1),
            "pos_rank": r["rank"] if r else None,
            "pos_adj": round(pts - repl.get(pos, 0.0), 1),
            "orig_round": int(o["round"]) if o is not None and pd.notna(o["round"]) else None,
            "orig_pick": (f"{int(o['round'])}.{int(o['pick_in_round']):02d}"
                          if o is not None and pd.notna(o["round"]) else None),
        })
    return pd.DataFrame(rows)


_SIM_COLS = ["roster_id", "user_name", "draft_slot", "wins", "losses", "points",
             "sim_position", "real_wins", "real_losses", "real_points", "real_position",
             "win_delta", "position_delta", "weeks"]

# Keyed like draft_board()'s own cache (league:season) -- redraft_standings()
# does a real optimal_lineup solve per team-week (~1.5s/season), so without
# this every chart/table that calls it separately (the live dumbbell plus
# three Testing-tab companions, all on the same page load) redoes the whole
# simulation from scratch each time. clear_draft_cache() clears both.
_sim_cache: dict = {}


def redraft_standings(s: Season, basis: str = "value") -> pd.DataFrame:
    """The season's real standings, replayed with every team's roster
    swapped for its `redraft_board()` roster -- the "expected outcome" of
    altering the draft to true season value.

    `basis` picks which redrafted board to replay: `"value"` (default) uses
    `redraft_board()` (drafted by TRUE season value, "knowing the results");
    `"adp"` uses `redraft_board_adp()` (drafted by Sleeper's own ADP, "what
    the field at large would have done"). Both bases share this one function
    -- only which board feeds the walk differs -- so the two report tabs
    (By final season results / By ADP) can never drift out of sync with each
    other's simulation logic.

    Replays the SAME regular-season schedule (same weekly matchups, from
    `Season.team_wk`), but each team-week's score is the best legal lineup
    (`optimal_lineup`) its REDRAFTED roster could field that week, priced
    from the players' real weekly stat lines (`scoring.score_lineup` -- true
    production regardless of who, if anyone, actually rostered them that
    week, the same pricing `draft_board`/`redraft_board` already use, not
    `pl_wk`, which reflects the real roster history this simulation
    deliberately overrides). BOTH sides of every game are simulated, so a
    team's simulated win/loss is against its opponent's simulated score too
    -- a self-consistent alternate season, not one real team dropped into an
    otherwise-real schedule. Regular season only, matching every other
    standings-shaped metric in this codebase.

    Returns one row per team: `draft_slot` is the team's real draft seat
    (1-indexed, from `redraft_board()` -- a team owns the same seat for the
    whole draft, so it's a fixed identity column, not a simulated result).
    `wins`/`losses`/`points`/`sim_position` are the simulated outcome;
    `real_wins`/`real_losses`/`real_points`/`real_position` are what
    actually happened (from `Season.standings`). `win_delta` = simulated
    wins minus real wins. `position_delta` = real position minus simulated
    position, so POSITIVE means the redraft would have finished them HIGHER
    (a smaller position number) than they really did. `weeks` is that team's
    simulated game log -- one dict per regular-season week with `week`,
    `points`/`opp_points`/`result` (the simulated matchup) alongside
    `real_points`/`real_opp_points`/`real_result` (what actually happened
    that week), for a week-by-week sim-vs-real drilldown. Sorted by
    simulated finish. Empty (all-columns) frame when there's no real draft
    to simulate against. Memoized per league:season:basis -- see
    `_sim_cache`.
    """
    key = f"{s.league_id}:{s.season}:{basis}"
    if key in _sim_cache:
        return _sim_cache[key]
    board = redraft_board_adp(s) if basis == "adp" else redraft_board(s)
    if board.empty:
        return pd.DataFrame(columns=_SIM_COLS)
    from . import scoring
    from .season import optimal_points, _result

    board = board.copy()
    board["player_id"] = board["player_id"].astype(str)
    rules = scoring.rules_from(s.league_id)
    ids = board["player_id"].unique().tolist()
    weekly = scoring.score_lineup(ids, s.season, range(1, s.last_week + 1), rules)
    pts_by_pw = weekly.set_index(["player_id", "week"])["points"]

    roster_players: dict = {}
    for r in board.itertuples(index=False):
        roster_players.setdefault(r.roster_id, []).append((r.player_id, r.position))

    # Every redrafted team's best legal lineup, every regular-season week --
    # keyed once so both a team's own score AND its opponent's (looked up via
    # `opp`, below) come from this same simulated world.
    sim_pts: dict = {}
    for rid, plist in roster_players.items():
        for wk in range(1, s.last_week + 1):
            rows = [{"player_id": pid, "position": pos,
                     "points": pts_by_pw.get((pid, wk), 0.0)} for pid, pos in plist]
            sim_pts[(rid, wk)] = optimal_points(pd.DataFrame(rows), s.slots)

    tw = s.team_wk[["week", "roster_id", "opp", "user_name", "points", "pa", "result"]].copy()
    tw = tw.rename(columns={"points": "real_points", "pa": "real_pa", "result": "real_result"})
    tw["sim_points"] = [sim_pts.get((rid, wk), 0.0)
                        for rid, wk in zip(tw["roster_id"], tw["week"])]
    tw["sim_pa"] = [sim_pts.get((opp, wk)) if pd.notna(opp) else None
                    for opp, wk in zip(tw["opp"], tw["week"])]
    tw["sim_result"] = [_result(p, a) for p, a in zip(tw["sim_points"], tw["sim_pa"])]
    # Opponent's own name for each row -- so a team-week can print WHO the
    # simulated matchup was against, not just the score.
    rid_name = dict(zip(tw["roster_id"], tw["user_name"]))
    tw["opp_user_name"] = tw["opp"].map(rid_name)

    rows = []
    for rid, g in tw.sort_values("week").groupby("roster_id"):
        weeks = [{
            "week": int(r.week),
            "points": round(float(r.sim_points), 1),
            "opp_points": round(float(r.sim_pa), 1) if pd.notna(r.sim_pa) else None,
            "opp_user_name": r.opp_user_name if pd.notna(r.opp_user_name) else None,
            "result": r.sim_result,
            "real_points": round(float(r.real_points), 1) if pd.notna(r.real_points) else None,
            "real_opp_points": round(float(r.real_pa), 1) if pd.notna(r.real_pa) else None,
            "real_result": r.real_result if pd.notna(r.real_result) else None,
        } for r in g.itertuples(index=False)]
        rows.append({
            "roster_id": rid, "user_name": g["user_name"].iloc[0],
            "wins": int((g["sim_result"] == "W").sum()),
            "losses": int((g["sim_result"] == "L").sum()),
            "points": round(float(g["sim_points"].sum()), 1),
            "weeks": weeks,
        })
    sim = (pd.DataFrame(rows)
           .sort_values(["wins", "points"], ascending=False).reset_index(drop=True))
    sim["sim_position"] = range(1, len(sim) + 1)

    real = s.standings[["user_name", "wins", "losses", "points", "final_position"]].rename(
        columns={"wins": "real_wins", "losses": "real_losses",
                 "points": "real_points", "final_position": "real_position"})
    out = sim.merge(real, on="user_name", how="left")
    out["win_delta"] = out["wins"] - out["real_wins"]
    out["position_delta"] = out["real_position"] - out["sim_position"]
    # A team owns the same seat all draft, so this is one lookup per roster,
    # not a per-round value -- same board redraft_board() itself grouped by.
    slot_by_rid = board.drop_duplicates("roster_id").set_index("roster_id")["draft_slot"]
    out["draft_slot"] = out["roster_id"].map(slot_by_rid).astype(int)
    out = out.sort_values("sim_position").reset_index(drop=True)
    return _sim_cache.setdefault(key, out)


# Keyed like _sim_cache -- redraft_week_matchups() is even more expensive
# than redraft_standings() (it does everything week_matchups() itself does,
# PER SIDE, plus a second optimal_lineup solve for the redrafted roster), so
# it gets its own cache rather than sharing _sim_cache's key (different
# return shape -- a dict, not a DataFrame).
_week_cache: dict = {}


def redraft_week_matchups(s: Season, basis: str = "value") -> dict:
    """Every regular-season week's games, real and simulated together --
    the per-week/per-matchup drilldown behind the redraft simulation's
    Weekly view.

    `basis` -- `"value"` (redraft_board(), the default) or `"adp"`
    (redraft_board_adp()) -- picks which redrafted board the "simulated"
    side of every game draws from; see redraft_standings()'s docstring for
    the fuller rationale (shared by all three redraft_* simulators).

    Reuses `metrics.week_matchups()` wholesale for each week's real side
    (both lineups, bench, the costliest swap -- already correct and tested)
    and overwrites each side's `opt_lineup`/`opt_points` with what the
    REDRAFTED roster would have scored that week instead of what the same
    real roster's own bench could have done -- so the shared per-game
    drilldown's existing Actual/Optimized toggle becomes Actual/Simulated
    almost for free. `opt_bench` is the redrafted roster's own leftover
    players that week (top 6 by points), carrying `was_started` -- reusing
    the SAME flag/label the real Optimized panel already has ("started in
    the actual lineup, swapped out here"), which turns out to mean exactly
    the right thing here too: this bench player DID start on the manager's
    REAL roster that week. Each side also gets `sim_result` (W/L from the
    simulated score alone) alongside its real `result`.

    For a played game, `sides` is re-sorted by SIMULATED points (descending)
    rather than left in `week_matchups()`'s real-points order, and `margin`
    on a played game becomes the SIMULATED one -- this whole table defaults
    its lineup toggle to Simulated (see the template's `opt_default`), so
    the summary row's Winner/Score/Margin needs to describe the SAME world
    as the drilldown beneath it. Leaving the real sort/margin in place while
    only the drilldown flipped to sim produced a real, confusing bug: a team
    could be labelled "Winner" (real result) while its own cumulative
    SIMULATED record (right next to its name) showed a loss for that exact
    week, because the record was sim-based but the summary/sort was still
    real-based.

    Returns {week: {"games": [...], "flips": n, "records": {...}, "high":
    {...}, "low": {...}}} -- `flips` is how many MATCHUPS that week had a
    different winner in the simulated world (one flipped 2-team game is 1,
    not 2, even though both of its sides individually changed result).
    `records` is each manager's cumulative SIMULATED win-loss record
    THROUGH that week (same shape/idiom as the real Weekly tab's own
    `records`, from `metrics.table_position`, just accumulated from
    `sim_result` instead). `high`/`low` are that week's top/bottom simulated
    scorer ({"user_name", "points"}), for the week-summary row. Empty dict
    when there's no real draft to simulate against. Memoized per
    league:season:basis.
    """
    key = f"{s.league_id}:{s.season}:{basis}"
    if key in _week_cache:
        return _week_cache[key]
    board = redraft_board_adp(s) if basis == "adp" else redraft_board(s)
    if board.empty:
        return {}
    from . import metrics, scoring
    from .season import assign_slots, optimal_lineup

    board = board.copy()
    board["player_id"] = board["player_id"].astype(str)
    names = dict(zip(board["player_id"], board["player_name"]))
    rules = scoring.rules_from(s.league_id)
    ids = board["player_id"].unique().tolist()
    weekly = scoring.score_lineup(ids, s.season, range(1, s.last_week + 1), rules)
    pts_by_pw = weekly.set_index(["player_id", "week"])["points"]

    roster_players: dict = {}
    for r in board.itertuples(index=False):
        roster_players.setdefault(r.roster_id, []).append((r.player_id, r.position))
    rid_by_name = dict(zip(s.user_map["user_name"], s.user_map["roster_id"]))

    out: dict = {}
    cum: dict = {}
    for wk in range(1, s.last_week + 1):
        games = metrics.week_matchups(s, wk)
        for g in games:
            sides = g["sides"]
            for sd in sides:
                plist = roster_players.get(rid_by_name.get(sd["user_name"]), [])
                rows = pd.DataFrame([{"player_id": pid, "position": pos,
                                      "points": pts_by_pw.get((pid, wk), 0.0)}
                                     for pid, pos in plist])
                picks = optimal_lineup(rows, s.slots) if len(rows) else rows
                if len(picks):
                    picks = assign_slots(picks, s.slots)
                    sd["opt_lineup"] = [
                        {"slot": x.slot, "player_id": x.player_id,
                         "player_name": names.get(x.player_id, x.player_id),
                         "position": x.position, "points": round(float(x.points), 1)}
                        for x in picks.itertuples(index=False)]
                    sd["opt_points"] = round(float(picks["points"].sum()), 2)
                    # The redrafted roster's own bench -- everyone not picked,
                    # top 6 by points. No "started in the real lineup" flag
                    # here (there used to be one): the simulated lineup IS
                    # already the optimal one by construction, so there is no
                    # "would have been optimal" question left to mark on it --
                    # a bench player here is simply worse than the picks made,
                    # full stop.
                    used_ids = set(picks["player_id"])
                    bn = (rows[~rows["player_id"].isin(used_ids)]
                          .sort_values("points", ascending=False).head(6))
                    sd["opt_bench"] = [
                        {"player_id": x.player_id,
                         "player_name": names.get(x.player_id, x.player_id),
                         "position": x.position, "points": round(float(x.points), 1)}
                        for x in bn.itertuples(index=False)]
                else:
                    sd["opt_lineup"], sd["opt_points"], sd["opt_bench"] = [], None, []
            if g["played"]:
                a, b = sides
                if a["opt_points"] is not None and b["opt_points"] is not None:
                    a["sim_result"] = ("W" if a["opt_points"] > b["opt_points"] else
                                       "L" if a["opt_points"] < b["opt_points"] else "T")
                    b["sim_result"] = ("W" if b["opt_points"] > a["opt_points"] else
                                       "L" if b["opt_points"] < a["opt_points"] else "T")
                else:
                    a["sim_result"] = b["sim_result"] = None
                # Per-slot who-won-that-slot, same as week_matchups() does for
                # its own opt_lineup -- matched by slot, not index.
                opt_opp_pts = [{p["slot"]: p["points"] for p in sd["opt_lineup"]} for sd in sides]
                for i, sd in enumerate(sides):
                    other = opt_opp_pts[1 - i]
                    for p in sd["opt_lineup"]:
                        opp = other.get(p["slot"])
                        p["cmp"] = (None if opp is None else
                                   "up" if p["points"] > opp else
                                   "down" if p["points"] < opp else "even")
                # Re-sort by SIM points (was real-points order from
                # week_matchups()) and derive a SIM margin -- see docstring:
                # the summary row must describe the same world as the
                # drilldown it opens on, not real results with a sim record
                # bolted on next to the name.
                sides.sort(key=lambda sd: -(sd["opt_points"]
                                            if sd["opt_points"] is not None else float("-inf")))
                g["sim_margin"] = (round(abs(sides[0]["opt_points"] - sides[1]["opt_points"]), 2)
                                   if sides[0]["opt_points"] is not None
                                   and sides[1]["opt_points"] is not None else None)
            else:
                sides[0]["sim_result"] = None
                g["sim_margin"] = None
            for sd in sides:
                if sd.get("sim_result") in ("W", "L"):
                    w, l = cum.setdefault(sd["user_name"], [0, 0])
                    cum[sd["user_name"]][0 if sd["sim_result"] == "W" else 1] += 1
        # One flipped MATCHUP, not one flipped side -- a 2-team game's sides
        # flip together (zero-sum), so checking just side 0 already counts
        # the game exactly once; checking every side would double-count it.
        # Stashed on the game itself (not just summed into `flips` below) so
        # the per-game template can mark WHICH game flipped, not just how
        # many did that week.
        for g in games:
            g["flipped"] = bool(g["played"]
                                and g["sides"][0]["sim_result"] != g["sides"][0]["result"])
        flips = sum(1 for g in games if g["flipped"])
        all_sides = [sd for g in games for sd in g["sides"] if sd["opt_points"] is not None]
        hi = max(all_sides, key=lambda sd: sd["opt_points"]) if all_sides else None
        lo = min(all_sides, key=lambda sd: sd["opt_points"]) if all_sides else None
        out[wk] = {
            "games": games, "flips": flips,
            "records": {nm: f"{w}-{l}" for nm, (w, l) in cum.items()},
            "high": {"user_name": hi["user_name"], "points": hi["opt_points"]} if hi else None,
            "low": {"user_name": lo["user_name"], "points": lo["opt_points"]} if lo else None,
        }
    return _week_cache.setdefault(key, out)


_playoff_cache: dict = {}


def _redraft_side_score(plist, weeks, pts_by_pw, names, slots):
    """Best legal lineup + leftover bench, from a redrafted roster's `plist`
    ([(player_id, position), ...]), for one or more `weeks` (summed when a
    playoff round spans more than one -- none of this league's stored
    brackets do, but a round's `weeks` field is allowed to). Returns
    (opt_lineup, opt_points, bench_rows) where `bench_rows` are the raw
    leftover-player records (top 6 by points); the caller attaches
    `was_started` since only it knows which lineup to compare against.

    A multi-week round's own per-slot breakdown isn't tracked, only its
    total -- same "degrade rather than error" precedent as the rest of this
    module (e.g. `redraft_board`'s empty-frame fallback).
    """
    from .season import assign_slots, optimal_lineup, optimal_points

    if not plist:
        return [], None, []
    if len(weeks) == 1:
        wk = weeks[0]
        rows = pd.DataFrame([{"player_id": pid, "position": pos,
                              "points": pts_by_pw.get((pid, wk), 0.0)} for pid, pos in plist])
        picks = optimal_lineup(rows, slots)
        if not len(picks):
            return [], None, []
        picks = assign_slots(picks, slots)
        opt_lineup = [{"slot": x.slot, "player_id": x.player_id,
                       "player_name": names.get(x.player_id, x.player_id),
                       "position": x.position, "points": round(float(x.points), 1)}
                      for x in picks.itertuples(index=False)]
        opt_points = round(float(picks["points"].sum()), 2)
        used_ids = set(picks["player_id"])
        bn = (rows[~rows["player_id"].isin(used_ids)]
              .sort_values("points", ascending=False).head(6))
        return opt_lineup, opt_points, list(bn.itertuples(index=False))
    total = 0.0
    for wk in weeks:
        rows = pd.DataFrame([{"player_id": pid, "position": pos,
                              "points": pts_by_pw.get((pid, wk), 0.0)} for pid, pos in plist])
        total += optimal_points(rows, slots)
    return [], round(total, 2), []


def _pl_lineup_by_week(players_df, team, week, slots) -> list[dict]:
    """A team's real submitted playoff lineup for ONE week, looked up by
    (team, week) rather than by matchup id -- see `redraft_playoff`'s
    docstring for why: a reseeded matchup can pair two teams who never
    actually played each other, but each side still has its OWN real week
    to show (if it made the real bracket that week at all). Keeps
    `player_id` (unlike `playoffs._lineup_from_players`, which drops it) so
    the shared `_lineupmacro.html` can still key headshots/posrank off it.
    `players_df` is `Playoff.players`, already priced.
    """
    from .season import assign_slots

    if players_df is None or not len(players_df):
        return []
    d = players_df[(players_df["team"] == team) & (players_df["week"] == week)]
    if not len(d):
        return []
    d = d.sort_values("points", ascending=False)
    try:
        d = assign_slots(d, slots or {})
    except Exception:
        d = d.assign(slot=d["position"])
    return [{"slot": x.slot, "player_id": str(x.player_id), "player_name": x.player_name,
             "position": x.position, "points": round(float(x.points), 1)}
            for x in d.itertuples(index=False)]


def redraft_playoff(s: Season, p, basis: str = "value") -> dict:
    """The playoff bracket, RESEEDED by simulated regular-season standings
    and walked round by round with each side's REDRAFTED roster -- the
    postseason counterpart to `redraft_week_matchups`.

    `basis` -- `"value"` (redraft_board()/redraft_standings(), the default)
    or `"adp"` (their redraft_board_adp()/redraft_standings(s, "adp")
    counterparts) -- picks which redrafted board AND which simulated
    standings (for reseeding) this walk uses; both must agree, or a team
    could be reseeded by one basis' standings while playing with the OTHER
    basis' roster. See redraft_standings()'s docstring for the fuller
    rationale (shared by all three redraft_* simulators).

    `redraft_standings()`'s `sim_position` is already computed over the same
    regular-season-only window `playoffs.seeds()` uses for the REAL seeds
    (see both docstrings), so "seed N" means the same thing on both sides.
    Every literal team name the real config assigns to a bracket slot is
    swapped for whichever team holds that SAME seed number under the
    simulation; a `W:`/`L:<matchup_id>` reference (a later round's winner)
    is left alone structurally and resolved from the SIMULATED result of
    that earlier matchup instead of the real one. This preserves the real
    bracket's SHAPE -- including a human "pick" like 2025's choose-your-
    opponent format, which becomes a fixed ROUTING decision ("this slot
    plays the winner of that earlier matchup") once identity is factored
    out -- while letting seeding and every round's outcome genuinely follow
    the simulation, which is what makes advancement (not just the score)
    something that can actually change.

    Because a reseeded matchup can pair two teams that never really played
    each other, "real" per-side facts are sourced two different ways:
    `flipped` compares the simulated winner against the REAL winner
    recorded AT THAT SAME BRACKET POSITION (matchup id) -- well-defined
    regardless of who's actually playing there now, since it is answering
    "did the outcome at this spot in the bracket change". The Actual lineup
    tab, on the other hand, looks each side's own real lineup/points/result
    up by (team, week) -- what that manager really did, independent of who
    the bracket says they're facing under simulation; a team that missed
    the real bracket entirely that week simply shows no roster data there,
    same as the shared lineup table already degrades for any missing side.

    Returns {"rounds": {round_id: {"label", "games": [...], "byes": [...],
    "flips": n, "high": {...}, "low": {...}}, ...}, "sim_champion",
    "real_champion", "champion_flipped"}, rounds in bracket order (dict
    insertion order, same idiom `redraft_week_matchups` already relies on).
    A round with nothing decided yet is omitted (same convention as
    `playoffs.game_log`). Empty dict when there's no playoff, no bracket
    config/rounds to walk, or no draft to simulate against. Memoized per
    league:season:basis.
    """
    key = f"{s.league_id}:{s.season}:{basis}"
    if key in _playoff_cache:
        return _playoff_cache[key]
    if p is None or not len(getattr(p, "results", [])):
        return {}
    cfg = p.config if isinstance(p.config, dict) else {}
    rounds_cfg = cfg.get("rounds") or []
    if not rounds_cfg:
        return {}
    board = redraft_board_adp(s) if basis == "adp" else redraft_board(s)
    if board.empty:
        return {}
    from . import playoffs as _playoffs
    from . import scoring

    sim_standings = redraft_standings(s, basis)
    if sim_standings.empty:
        return {}
    real_seeds = _playoffs.seeds(s, playoff=p)
    real_seed_of = dict(zip(real_seeds["user_name"], real_seeds["seed"]))
    sim_team_of_seed = dict(zip(sim_standings["sim_position"].astype(int),
                               sim_standings["user_name"]))

    def reseed(team_name):
        seed = real_seed_of.get(team_name)
        return sim_team_of_seed.get(seed, team_name) if seed is not None else team_name

    board = board.copy()
    board["player_id"] = board["player_id"].astype(str)
    names = dict(zip(board["player_id"], board["player_name"]))
    roster_players: dict = {}
    for r in board.itertuples(index=False):
        roster_players.setdefault(r.roster_id, []).append((r.player_id, r.position))
    rid_by_name = dict(zip(s.user_map["user_name"], s.user_map["roster_id"]))
    slots = getattr(s, "slots", {}) or {}

    rules = scoring.rules_from(s.league_id)
    ids = board["player_id"].unique().tolist()
    all_weeks = sorted({int(w) for rd in rounds_cfg for w in rd.get("weeks", [])})
    if not all_weeks:
        return {}
    weekly = scoring.score_lineup(ids, s.season, all_weeks, rules)
    pts_by_pw = weekly.set_index(["player_id", "week"])["points"]

    # Real per-(team, round-weeks-label) result/points -- keyed by TEAM
    # alone, not matchup id, for the Actual tab (see docstring).
    real_by_team_wk: dict = {}
    for r in p.results.itertuples(index=False):
        real_by_team_wk[(r.team, r.weeks)] = {
            "points": round(float(r.points), 2) if pd.notna(r.points) else None,
            "result": r.result if r.result in ("W", "L", "T") else None,
        }
    real_winner_of_mid = {
        mid: g.loc[g["result"] == "W", "team"].iloc[0]
        for mid, g in p.results.groupby("matchup_id") if (g["result"] == "W").any()
    }

    def side_score(team, weeks):
        rid = rid_by_name.get(team)
        plist = roster_players.get(rid, [])
        return _redraft_side_score(plist, weeks, pts_by_pw, names, slots)

    winners: dict = {}
    losers: dict = {}
    # A literal team name that ALSO recorded a REAL win in some STRICTLY
    # EARLIER round (built up round-by-round below, never looking ahead) is
    # really an implicit advancement reference -- a human "pick" written as
    # a name instead of "W:<matchup_id>" (2025's config does exactly this:
    # R2M1's away side is the literal string "xPsyD", not "W:R1M1", because
    # seed 3 picked xPsyD after they won R1M1). Routing it through `reseed()`
    # directly would substitute whoever now holds xPsyD's ORIGINAL SEED,
    # regardless of whether that team actually won ITS reseeded R1 game --
    # letting a team eliminated under simulation advance anyway. Resolving
    # through the matchup they really won instead keeps advancement tied to
    # the SIMULATED result, which is the whole point of reseeding. A byed
    # team is never in here (never recorded as winning an actual game), so
    # its own literal references still fall through to `reseed()` -- correct,
    # since a bye is a genuine fresh seed entry, not an advancement.
    implicit_winner_of: dict = {}

    def resolve(v):
        v = str(v)
        if v.startswith("W:"):
            return winners.get(v[2:])
        if v.startswith("L:"):
            return losers.get(v[2:])
        implicit_mid = implicit_winner_of.get(v)
        if implicit_mid is not None:
            return winners.get(implicit_mid)
        return reseed(v)

    rounds: dict = {}
    for rd in rounds_cfg:
        rid = rd["id"]
        weeks = [int(w) for w in rd.get("weeks", [])]
        wk_lbl = "+".join(str(w) for w in weeks)
        info = rounds.setdefault(rid, {"label": rd.get("name", rid), "games": [],
                                       "byes": [], "flips": 0})
        if not weeks:
            continue
        for mu in rd.get("matchups", []):
            mid = mu["id"]
            if mu.get("bye"):
                team = resolve(mu["bye"])
                if team is None:
                    continue
                winners[mid] = team
                _, opt_points, _ = side_score(team, weeks)
                if opt_points is not None:
                    info["byes"].append({"user_name": team, "points": opt_points})
                continue
            nms = [resolve(mu["home"]["team"]), resolve(mu["away"]["team"])]
            if any(n is None for n in nms):
                continue   # an upstream game hasn't resolved yet
            sides = []
            for team in nms:
                opt_lineup, opt_points, bench_rows = side_score(team, weeks)
                opt_bench = [{"player_id": x.player_id,
                             "player_name": names.get(x.player_id, x.player_id),
                             "position": x.position, "points": round(float(x.points), 1)}
                            for x in bench_rows]
                real = real_by_team_wk.get((team, wk_lbl), {})
                sides.append({
                    "user_name": team,
                    "points": real.get("points"),
                    "result": real.get("result"),
                    "lineup": (_pl_lineup_by_week(p.players, team, weeks[0], slots)
                              if len(weeks) == 1 else []),
                    "bench": [],
                    "opt_lineup": opt_lineup, "opt_points": opt_points, "opt_bench": opt_bench,
                })
            if any(sd["opt_points"] is None for sd in sides):
                continue
            a, b = sides
            a["sim_result"] = "W" if a["opt_points"] > b["opt_points"] else (
                "L" if a["opt_points"] < b["opt_points"] else "T")
            b["sim_result"] = "W" if b["opt_points"] > a["opt_points"] else (
                "L" if b["opt_points"] < a["opt_points"] else "T")
            if a["sim_result"] == "T":
                continue   # no winner to advance -- same rule the real engine follows
            winners[mid] = a["user_name"] if a["sim_result"] == "W" else b["user_name"]
            losers[mid] = b["user_name"] if a["sim_result"] == "W" else a["user_name"]
            opt_opp_pts = [{p_["slot"]: p_["points"] for p_ in sd["opt_lineup"]} for sd in sides]
            for i, sd in enumerate(sides):
                other = opt_opp_pts[1 - i]
                for p_ in sd["opt_lineup"]:
                    opp = other.get(p_["slot"])
                    p_["cmp"] = (None if opp is None else
                                "up" if p_["points"] > opp else
                                "down" if p_["points"] < opp else "even")
            sides.sort(key=lambda sd: -sd["opt_points"])
            real_winner = real_winner_of_mid.get(mid)
            sim_winner = winners[mid]
            flipped = bool(real_winner and sim_winner != real_winner)
            sim_margin = round(abs(sides[0]["opt_points"] - sides[1]["opt_points"]), 2)
            info["games"].append({
                "matchup_id": mid, "sides": sides, "played": True,
                "margin": None, "sim_margin": sim_margin,
                "flipped": flipped, "winner": real_winner, "sim_winner": sim_winner,
            })
            if flipped:
                info["flips"] += 1
        # Record THIS round's real winners for later rounds' literal-name
        # references to route through -- done only now, after the whole
        # round is processed, so a name is never treated as an implicit
        # advancement before the round it actually won has been walked (a
        # bye recipient's own later bye/game still resolves as a fresh seed
        # entry, not an advancement, exactly because it never appears here).
        for mu in rd.get("matchups", []):
            if mu.get("bye"):
                continue
            w = real_winner_of_mid.get(mu["id"])
            if w:
                implicit_winner_of[w] = mu["id"]

    rounds = {rid: info for rid, info in rounds.items() if info["games"] or info["byes"]}
    for info in rounds.values():
        all_sides = [sd for g in info["games"] for sd in g["sides"]]
        info["high"] = ({"user_name": max(all_sides, key=lambda sd: sd["opt_points"])["user_name"],
                         "points": max(sd["opt_points"] for sd in all_sides)}
                        if all_sides else None)
        info["low"] = ({"user_name": min(all_sides, key=lambda sd: sd["opt_points"])["user_name"],
                        "points": min(sd["opt_points"] for sd in all_sides)}
                       if all_sides else None)

    final_id = cfg.get("final")
    sim_champion = winners.get(final_id) if final_id else None
    real_champion = p.champion
    champion_flipped = (bool(sim_champion and real_champion and sim_champion != real_champion)
                        if final_id else None)

    return _playoff_cache.setdefault(key, {
        "rounds": rounds, "sim_champion": sim_champion,
        "real_champion": real_champion, "champion_flipped": champion_flipped,
    })


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
    _sim_cache.clear()
    _week_cache.clear()
    _playoff_cache.clear()
    _adp_cache.clear()
