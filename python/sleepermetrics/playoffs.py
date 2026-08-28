"""Manual / custom playoff engine (mirrors R playoffs.R).

Sleeper can only express its own bracket shape (fixed playoff_week_start, team
count, and lineups locked to what the app had). When a league runs its playoff
by hand -- a different week range, a custom bracket, and starters collected by
the commissioner -- none of that fits.

This engine takes a bracket config (rounds -> matchups -> each side's submitted
starters) and prices every lineup under the league's own scoring chart (see
scoring.py), so the ONLY input needed per elimination matchup is the rosters.
Winners advance automatically via "W:<matchup_id>" references.
"""
from __future__ import annotations

import copy
import json
import re
import warnings

import pandas as pd

from . import metrics
from .api import sleeper_api
from .league import starter_slots
from .players import players as _players
from .scoring import rules_from, score_lineup

BYE = "BYE"
POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]


def playoff_config(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _resolve_players(x, pinfo: pd.DataFrame) -> list:
    """Accept starters as player ids OR player names; return ids."""
    out = []
    by_name = {n.lower(): i for n, i in
               zip(pinfo["player_name"].fillna(""), pinfo["player_id"])}
    for v in [str(v) for v in x]:
        if re.fullmatch(r"[0-9]+", v) or re.fullmatch(r"[A-Z]{2,3}", v):
            out.append(v)
        else:
            hit = by_name.get(v.lower())
            if hit is None:
                raise ValueError(f"Unknown player in lineup: '{v}'")
            out.append(hit)
    return out


def check_lineup(player_ids, roster_positions, pinfo: pd.DataFrame) -> list:
    """Problems with a submitted lineup vs the league's starting slots ([] = legal)."""
    slots = starter_slots(roster_positions)
    pos = (pinfo.set_index("player_id")["position"]
           .reindex([str(p) for p in player_ids]).dropna().tolist())
    probs = []
    need_total = sum(slots.values())
    if len(player_ids) != need_total:
        probs.append(f"lineup has {len(player_ids)} starters, league starts {need_total}")
    left = {p: pos.count(p) for p in POSITIONS}
    for p in POSITIONS:
        need = slots.get(p, 0)
        if need > 0:
            have = min(left[p], need)
            if have < need:
                probs.append(f"{need - have} {p} short")
            left[p] -= have
    flex = sum(slots.get(k, 0) for k in ("FLEX", "WRRB_FLEX", "REC_FLEX", "SUPER_FLEX"))
    spare = sum(left.values())
    if spare != flex:
        probs.append(f"{spare} players for {flex} flex slot(s)")
    return probs


# --- Bracket generators + validation -------------------------------------
# The webapp lets a user roll back to Sleeper's own bracket or scaffold a custom
# one; both produce a config the engine runs unchanged. These were previously in
# scaffold.py (a CLI, now at season/scaffold.py); promoted here so the webapp
# can call them without shelling out. scaffold.py now imports these.
_gen_cache: dict = {}


def _bracket_context(league_id, season=None):
    from .league import league_chain
    chain = league_chain(league_id)
    key = str(season) if season else list(chain)[-1]
    link = chain[key]
    lid = link["league_id"]
    lg = sleeper_api(f"/league/{lid}")
    rosters = sleeper_api(f"/league/{lid}/rosters")
    users = {u["user_id"]: u.get("display_name")
             for u in sleeper_api(f"/league/{lid}/users")}
    name_of = {r["roster_id"]: users.get(r.get("owner_id")) for r in rosters}
    return link, lid, lg, name_of


def _week_starters(lid, week) -> dict:
    """roster_id -> starters Sleeper recorded that week (a lineup baseline)."""
    return {m["roster_id"]: [p for p in (m.get("starters") or []) if p and p != "0"]
            for m in sleeper_api(f"/league/{lid}/matchups/{week}")}


def _bracket_base(link, lid, lg, name) -> dict:
    return {"name": name, "season": link["season"], "league_id": lid,
            "roster_positions": lg["roster_positions"],
            "scoring_settings": lg["scoring_settings"], "rounds": []}


def _sleeper_side(t, name_of):
    """Resolve a winners_bracket slot to a team name or a W:/L: reference.

    A live bracket stores unresolved slots as {"w": m} / {"l": m} rather than a
    roster id; translating those to the engine's own refs lets an in-progress
    Sleeper bracket rebuild too, not only a finished one.
    """
    if isinstance(t, dict):
        if "w" in t:
            return f"W:M{t['w']}"
        if "l" in t:
            return f"L:M{t['l']}"
        return None
    return name_of.get(t)


def _sleeper_seed_map(league_id, season, playoff_start) -> dict:
    """{seed(int): team name} for a Sleeper bracket -- regular-season seeding.

    Seeds come from the REGULAR season (weeks before `playoff_week_start`), the
    same rule `seeds()` uses and the same reason: the final standings fold in the
    playoff weeks and reorder the middle of the field. Best-effort -- any failure
    building the Season (offline, a stand-in) or a missing `playoff_week_start`
    returns {}, and every seed-based label downstream degrades to a plain team
    name.
    """
    if not playoff_start:
        return {}
    try:
        from .season import season as _season
        s = _season(league_id, season)
        sd = seeds(s, through_week=int(playoff_start) - 1)
        return {int(r.seed): r.user_name for r in sd.itertuples(index=False)}
    except Exception:
        return {}


def _sleeper_byes(wb, name_of, seed_map) -> dict:
    """{team name: entry_round(int)} for teams that sat out early rounds.

    Sleeper's winners_bracket has no explicit bye node: a team on a first-round
    bye simply isn't listed until the round it enters, where its slot is a raw
    roster id with NO `t1_from` / `t2_from` provenance ref (a side that came from
    a prior game always carries one). So a fresh raw-id side first seen in round
    r >= 2 was idle in rounds 1..r-1.

    Fallback (a malformed bracket with no `_from` refs anywhere, so the
    structural signal is unusable): the playoff field is `seed_map`; whichever of
    those seeds never appears in round 1 is presumed to have had a bye, entering
    at the earliest round where it does appear. Higher seeds sit out longer, so
    ordering the presumed byes by seed matches how Sleeper actually builds them.
    """
    rounds = sorted({m["r"] for m in wb})
    if not rounds:
        return {}
    r1 = min(rounds)
    # First round each team is seen in, and whether that first sighting was a
    # "fresh entry" (raw id, no provenance ref).
    first_round: dict = {}
    fresh_entry: dict = {}
    has_from_ref = False
    for m in sorted(wb, key=lambda x: (x["r"], x["m"])):
        for slot in ("t1", "t2"):
            t = m.get(slot)
            frm = m.get(f"{slot}_from")
            if frm is not None:
                has_from_ref = True
            nm = name_of.get(t) if isinstance(t, int) else _sleeper_side(t, name_of)
            if not nm or str(nm).startswith(("W:", "L:")):
                continue
            if nm not in first_round:
                first_round[nm] = m["r"]
                fresh_entry[nm] = frm is None and isinstance(t, int)

    byes: dict = {}
    for nm, fr in first_round.items():
        if fr > r1 and fresh_entry.get(nm):
            byes[nm] = fr

    if not byes and not has_from_ref and seed_map:
        # Presumption fallback: seeded playoff teams missing from round 1.
        r1_teams = {name_of.get(m.get(s)) for m in wb if m["r"] == r1
                    for s in ("t1", "t2") if isinstance(m.get(s), int)}
        for seed in sorted(seed_map):
            nm = seed_map[seed]
            if nm not in r1_teams and nm in first_round and first_round[nm] > r1:
                byes[nm] = first_round[nm]
    return byes


def sleeper_bracket(league_id, season=None) -> dict:
    """Rebuild Sleeper's own winners_bracket as an engine config.

    This is the "default Sleeper bracket" a user rolls back to. Note Sleeper's
    stored bracket can be incoherent (DDBM 2025) or, mid-season, incomplete --
    the config is faithful to whatever Sleeper holds, warts and all.

    First-round byes (a 6-team bracket seeds 1-2 through round 1, an 8-team
    one likewise) have no node in Sleeper's data; they are inferred here
    (`_sleeper_byes`) and materialised as `{"bye": team}` matchups in the rounds
    the team sat out, so the engine's own BYE handling, the bracket chart's bye
    connectors and the Games-log bye blurbs all light up for a stock Sleeper
    bracket exactly as they do for a hand-authored one.
    """
    key = f"sleeper:{league_id}:{season}"
    if key in _gen_cache:
        return copy.deepcopy(_gen_cache[key])
    link, lid, lg, name_of = _bracket_context(league_id, season)
    wb = sleeper_api(f"/league/{lid}/winners_bracket") or []
    start = int((lg.get("settings") or {}).get("playoff_week_start") or 0)
    cfg = _bracket_base(link, lid, lg, f"{lg['name']} {link['season']} (Sleeper bracket)")

    seed_map = _sleeper_seed_map(league_id, season, start) if wb else {}
    if seed_map:
        cfg["_seeds"] = {str(k): v for k, v in seed_map.items()}
    byes = _sleeper_byes(wb, name_of, seed_map) if wb else {}

    rounds = sorted({m["r"] for m in wb})
    r1 = min(rounds) if rounds else 1
    for r in rounds:
        wk = start + r - 1
        starters = _week_starters(lid, wk) if start else {}
        mus = []
        for m in sorted((x for x in wb if x["r"] == r), key=lambda x: x["m"]):
            home, away = _sleeper_side(m.get("t1"), name_of), _sleeper_side(m.get("t2"), name_of)
            if home is None or away is None:
                continue
            mid = f"M{m['m']}"
            mus.append({
                "id": mid,
                "home": {"team": home,
                         "starters": starters.get(m.get("t1"), []) if isinstance(m.get("t1"), int) else []},
                "away": {"team": away,
                         "starters": starters.get(m.get("t2"), []) if isinstance(m.get("t2"), int) else []},
                "_sleeper_winner": name_of.get(m["w"]) if m.get("w") else None})
            # Sleeper tags a placement game with the position its WINNER earns
            # (`p == 3` -> 3rd-place game, `p == 5` -> 5th, ...). Carried onto the
            # config so the bracket chart can label the consolation tier and the
            # outcome caption can name the 3rd-place finisher. `p == 1` is the
            # title game and is already handled by `final`.
            if m.get("p") and m["p"] != 1:
                cfg.setdefault("_placements", {})[mid] = int(m["p"])
        # A team that enters at round `e` sat out every round from r1..e-1; give
        # it a bye card in each of those. Bye ids are B-numbered to stay clear
        # of the M-numbered games in the same round.
        for nm, entry in sorted(byes.items(), key=lambda kv: kv[1]):
            if r1 <= r < entry:
                mus.append({"id": f"R{r}B{sum(1 for x in mus if x.get('bye')) + 1}",
                            "bye": nm})
        cfg["rounds"].append({"id": f"R{r}", "name": f"Round {r}",
                              "weeks": [wk], "matchups": mus})
    title = next((m for m in wb if m.get("p") == 1), None)
    if title:
        cfg["final"] = f"M{title['m']}"
    _gen_cache[key] = copy.deepcopy(cfg)
    return cfg


def sleeper_losers_bracket(league_id, season=None) -> dict | None:
    """Rebuild Sleeper's own `losers_bracket` (the consolation / consolation bracket
    bracket) as an engine config, the counterpart to `sleeper_bracket`.

    Sleeper stores the teams that missed the championship bracket as a proper
    tree in `/league/<id>/losers_bracket` -- same node shape as the winners
    bracket (`r`, `m`, `t1`, `t2`, `w`, `l`, `t1_from`, `t2_from`, `p`), with
    winner/loser advancement refs and first-round byes. `consolation_bracket()` reads
    the flat weekly matchups instead and so loses this structure; this
    function recovers it so the consolation bracket CHART can be drawn as a real
    bracket rather than ragged week columns.

    Returns `None` when the league has no `losers_bracket` (or an empty one),
    so the caller falls back to the flat week-column rendering. Best-effort:
    any API failure also returns `None`.

    `final` is set to the game Sleeper marks `p == 1` (the losers bracket's
    own top placement game); `_placements` carries the rest. `_seeds` IS
    attached -- for a consolation / consolation bracket the useful number is
    each team's SEASON RANK (its full regular-season standing, so #9, #11,
    ... for a 12-team league), which is what the `#N` card badges then show.
    This is a separate chart from the winners bracket, so there is no
    ambiguity with the playoff field's 1..N seeds.
    """
    key = f"sleeper-losers:{league_id}:{season}"
    if key in _gen_cache:
        return copy.deepcopy(_gen_cache[key])
    try:
        link, lid, lg, name_of = _bracket_context(league_id, season)
        lb = sleeper_api(f"/league/{lid}/losers_bracket") or []
    except Exception:
        return None
    if not lb:
        return None
    start = int((lg.get("settings") or {}).get("playoff_week_start") or 0)
    # Plain league name -- `plot_playoff_bracket(variant="consolation")` adds
    # its own " Consolation Bracket" to the title, so don't double it here.
    cfg = _bracket_base(link, lid, lg, lg["name"])

    # Season rank per team -- the FULL regular-season standing (`seeds()`
    # ranks the whole league, not just the playoff field), so consolation
    # teams read #9 / #11 / ... on their cards. Best-effort: any failure
    # building the Season leaves `_seeds` unset and the cards fall back to a
    # plain team name, exactly as before.
    if start:
        try:
            from .season import season as _season
            _sd = seeds(_season(league_id, season), through_week=int(start) - 1)
            cfg["_seeds"] = {str(int(r.seed)): r.user_name
                             for r in _sd.itertuples(index=False)}
        except Exception:
            pass

    # Byes reuse the winners-bracket inference: a raw roster id first seen in
    # round r >= 2 with no `_from` ref sat out rounds 1..r-1. The losers
    # bracket's own round-2 byes (Coin Flip and FF 2025: roster ids 10 and 11)
    # match that shape exactly.
    byes = _sleeper_byes(lb, name_of, {})

    rounds = sorted({m["r"] for m in lb})
    r1 = min(rounds) if rounds else 1
    for r in rounds:
        wk = start + r - 1
        starters = _week_starters(lid, wk) if start else {}
        mus = []
        for m in sorted((x for x in lb if x["r"] == r), key=lambda x: x["m"]):
            home = _sleeper_side(m.get("t1"), name_of)
            away = _sleeper_side(m.get("t2"), name_of)
            if home is None or away is None:
                continue
            mid = f"M{m['m']}"
            mus.append({
                "id": mid,
                "home": {"team": home,
                         "starters": starters.get(m.get("t1"), []) if isinstance(m.get("t1"), int) else []},
                "away": {"team": away,
                         "starters": starters.get(m.get("t2"), []) if isinstance(m.get("t2"), int) else []},
                "_sleeper_winner": name_of.get(m["w"]) if m.get("w") else None})
            if m.get("p") and m["p"] != 1:
                cfg.setdefault("_placements", {})[mid] = int(m["p"])
        for nm, entry in sorted(byes.items(), key=lambda kv: kv[1]):
            if r1 <= r < entry:
                mus.append({"id": f"R{r}B{sum(1 for x in mus if x.get('bye')) + 1}",
                            "bye": nm})
        if mus:
            cfg["rounds"].append({"id": f"R{r}", "name": f"Round {r}",
                                  "weeks": [wk], "matchups": mus})
    if not cfg["rounds"]:
        return None
    fin = next((m for m in lb if m.get("p") == 1), None)
    if fin:
        cfg["final"] = f"M{fin['m']}"
    else:
        cfg["final"] = cfg["rounds"][-1]["matchups"][-1]["id"]
    _gen_cache[key] = copy.deepcopy(cfg)
    return copy.deepcopy(cfg)


def scaffold_bracket(league_id, season=None, weeks=None, teams: int = 8) -> dict:
    """A seeded single-elim skeleton over a custom week range.

    Seeds come from the regular-season standings; each round pairs highest vs
    lowest with the odd team out getting a bye, winners advancing via W:refs, and
    every side's starters pre-filled from Sleeper -- a runnable baseline the user
    then edits (opponents, submitted lineups) rather than authoring from blank.
    """
    from .season import season as _season
    link, lid, lg, name_of = _bracket_context(league_id, season)
    weeks = [int(w) for w in (weeks or [15, 16, 17, 18])]
    s = _season(league_id, season)
    seeds = s.standings.sort_values("final_position")["user_name"].tolist()[:int(teams)]
    cfg = _bracket_base(link, lid, lg, f"{lg['name']} {link['season']} Playoffs (custom)")
    rid_of = {n: r for r, n in name_of.items()}
    alive = [f"{i + 1}:{n}" for i, n in enumerate(seeds)]   # keep seed order
    rnum = 0
    for wk in weeks:
        if len(alive) < 2:
            break
        rnum += 1
        starters = _week_starters(lid, wk)

        def side(tag):
            nm = tag.split(":", 1)[1] if ":" in tag and not tag.startswith("W:") else tag
            return {"team": nm,
                    "starters": starters.get(rid_of.get(nm), []) if not nm.startswith("W:") else []}
        mus, nxt = [], []
        while len(alive) > 1:
            hi, lo = alive.pop(0), alive.pop(-1)
            mid = f"R{rnum}M{len(mus) + 1}"
            mus.append({"id": mid, "home": side(hi), "away": side(lo)})
            nxt.append(f"W:{mid}")
        if alive:
            # Bye ids are B-numbered (R2B1), distinct from games (R2M1), so a
            # reference to one reads as "Round 2 Bye 1" rather than a game.
            mid = f"R{rnum}B1"
            nm = alive[0].split(":", 1)[1] if ":" in alive[0] else alive[0]
            mus.append({"id": mid, "bye": nm})
            nxt.append(f"W:{mid}")
        cfg["rounds"].append({"id": f"R{rnum}", "name": f"Round {rnum}",
                              "weeks": [int(wk)], "matchups": mus})
        alive = nxt
    if cfg["rounds"]:
        cfg["final"] = cfg["rounds"][-1]["matchups"][-1]["id"]
    return cfg


def validate_config(cfg, league_id=None) -> dict:
    """Check a bracket config: {"errors": [...], "warnings": [...]}.

    Errors are structural (unrunnable); warnings are soft (e.g. a lineup that
    doesn't fill the league's slots -- allowed, since the engine scores it
    anyway and reports PENDING/partial). Empty errors == safe to run.
    """
    errors: list[str] = []
    warnings_: list[str] = []
    if not isinstance(cfg, dict):
        return {"errors": ["config must be a JSON object"], "warnings": []}
    if not cfg.get("season"):
        errors.append("missing 'season'")
    rounds = cfg.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        errors.append("missing or empty 'rounds'")
        return {"errors": errors, "warnings": warnings_}
    if league_id and str(cfg.get("league_id", "")) not in ("", str(league_id)):
        warnings_.append(
            f"config league_id {cfg.get('league_id')} != current league {league_id}")

    ids: set = set()
    for rd in rounds:
        if not rd.get("id"):
            errors.append("a round is missing 'id'")
        if not rd.get("weeks"):
            errors.append(f"round {rd.get('id')} missing 'weeks'")
        for mu in rd.get("matchups", []):
            mid = mu.get("id")
            if not mid:
                errors.append(f"a matchup in round {rd.get('id')} is missing 'id'")
                continue
            if mid in ids:
                errors.append(f"duplicate matchup id '{mid}'")
            ids.add(mid)
            if mu.get("bye"):
                continue
            for k in ("home", "away"):
                side = mu.get(k)
                if not isinstance(side, dict):
                    errors.append(f"{mid}.{k} is malformed")
                elif not side.get("team"):
                    # Incomplete, not invalid: the engine scores it as PENDING, so
                    # a half-built bracket previews rather than erroring out.
                    warnings_.append(f"{mid}.{k} has no team yet")

    def ref(v):
        v = str(v)
        return v[2:] if v.startswith(("W:", "L:")) else None

    for rd in rounds:
        for mu in rd.get("matchups", []):
            for k in ("home", "away", "bye"):
                side = mu.get(k)
                team = side.get("team") if isinstance(side, dict) else side
                r = ref(team) if team is not None else None
                if r and r not in ids:
                    errors.append(f"{mu.get('id')} references unknown matchup '{r}'")
    fin = cfg.get("final")
    if fin and fin not in ids:
        errors.append(f"'final' references unknown matchup '{fin}'")

    # Soft lineup slot-check -- best-effort, skipped offline (no player DB).
    rposi = cfg.get("roster_positions")
    if rposi:
        try:
            pinfo = _players()
        except Exception:
            pinfo = None
        if pinfo is not None:
            for rd in rounds:
                for mu in rd.get("matchups", []):
                    for k in ("home", "away"):
                        side = mu.get(k)
                        st = side.get("starters") if isinstance(side, dict) else None
                        if not st:
                            continue
                        try:
                            probs = check_lineup(_resolve_players(st, pinfo), rposi, pinfo)
                            warnings_ += [f"{mu.get('id')} {side.get('team')}: {p}"
                                          for p in probs]
                        except ValueError as e:
                            errors.append(f"{mu.get('id')} {side.get('team')}: {e}")
    return {"errors": errors, "warnings": warnings_}


class Playoff:
    def __init__(self, results, players, champion, season, name, config):
        self.results = results
        self.players = players
        self.champion = champion
        self.season = season
        self.name = name
        self.config = config

    def __repr__(self):
        return (f"<Playoff {self.name} {self.season} | rounds: "
                f"{self.results['round_id'].nunique()} | "
                f"champion: {self.champion or '(undecided)'}>")


def playoff(config, rules: dict | None = None, validate: bool = True) -> Playoff:
    """Run a manual/custom playoff bracket from a config."""
    if isinstance(config, str):
        config = playoff_config(config)
    season = str(config["season"])
    lid = config.get("league_id")
    if rules is None:
        rules = config.get("scoring_settings") or rules_from(lid)
    pinfo = _players()
    rposi = config.get("roster_positions")
    if rposi is None and lid:
        try:
            rposi = sleeper_api(f"/league/{lid}")["roster_positions"]
        except Exception:
            rposi = None

    winners: dict = {}
    losers: dict = {}
    res, det = [], []

    def resolve_team(nm):
        """Resolve a team or a W:/L: reference; None if it isn't decided yet."""
        nm = str(nm)
        if nm.startswith("W:"):
            return winners.get(nm[2:])
        if nm.startswith("L:"):
            return losers.get(nm[2:])
        return nm

    def score_side(side, weeks, team, mid, rid):
        starters = _resolve_players(side["starters"], pinfo)
        if validate and rposi:
            probs = check_lineup(starters, rposi, pinfo)
            if probs:
                warnings.warn(f"[{mid}] {team}: {'; '.join(probs)}")
        d = score_lineup(starters, season, weeks, rules).merge(
            pinfo[["player_id", "player_name", "position"]], on="player_id", how="left")
        d["team"], d["matchup_id"], d["round_id"] = team, mid, rid
        return round(float(d["points"].sum()), 2), len(starters), d

    for rd in config["rounds"]:
        weeks = [int(w) for w in rd["weeks"]]
        wk_lbl = "+".join(str(w) for w in weeks)
        for mu in rd["matchups"]:
            mid = mu["id"]
            if mu.get("bye"):
                team = resolve_team(mu["bye"])
                if team is not None:
                    winners[mid] = team
                res.append({"round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                            "matchup_id": mid, "team": team, "starters": None,
                            "points": None, "opponent": BYE, "opp_points": None,
                            "result": "BYE" if team else "PENDING", "margin": None})
                continue
            sides = [mu["home"], mu["away"]]
            nms = [resolve_team(s["team"]) for s in sides]
            # A round only becomes playable once both teams are known AND both
            # lineups have been submitted -- otherwise it is simply not yet run.
            if any(n is None for n in nms) or any(not s.get("starters") for s in sides):
                for i in range(2):
                    res.append({
                        "round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                        "matchup_id": mid, "team": nms[i] or str(sides[i]["team"]),
                        "starters": len(sides[i].get("starters") or []), "points": None,
                        "opponent": nms[1 - i] or str(sides[1 - i]["team"]),
                        "opp_points": None, "result": "PENDING", "margin": None})
                continue
            scored = [score_side(sides[i], weeks, nms[i], mid, rd["id"]) for i in range(2)]
            pts = [s[0] for s in scored]
            wi = None if pts[0] == pts[1] else int(pts[1] > pts[0])
            if wi is None:
                warnings.warn(f"[{mid}] tie at {pts[0]} -- no winner advanced.")
            else:
                winners[mid] = nms[wi]
                losers[mid] = nms[1 - wi]
            for i in range(2):
                res.append({
                    "round_id": rd["id"], "round": rd["name"], "weeks": wk_lbl,
                    "matchup_id": mid, "team": nms[i], "starters": scored[i][1],
                    "points": pts[i], "opponent": nms[1 - i], "opp_points": pts[1 - i],
                    "result": "T" if wi is None else ("W" if i == wi else "L"),
                    "margin": round(pts[i] - pts[1 - i], 2)})
                det.append(scored[i][2])

    results = _tag_bracket(pd.DataFrame(res), [r["id"] for r in config["rounds"]])
    playersdf = pd.concat(det, ignore_index=True) if det else pd.DataFrame()
    if len(playersdf):
        playersdf = playersdf.merge(
            results[["matchup_id", "bracket"]].drop_duplicates(),
            on="matchup_id", how="left")
    # The championship must be named: a final round can also hold consolation
    # and placement games, so "last matchup" is not the title game.
    final_id = config.get("final") or config["rounds"][-1]["matchups"][-1]["id"]
    champion = winners.get(final_id)
    return Playoff(results, playersdf, champion, season,
                   config.get("name", "Playoffs"), config)


def _tag_bracket(results: pd.DataFrame, round_order: list) -> pd.DataFrame:
    """Split a bracket into the championship path and everything else.

    Sleeper's winners_bracket stores 3rd-place and placement games alongside
    the real thing, so counting every game as a "playoff win" inflates
    records. A game is on the title path only if BOTH teams are still alive
    going into it; once you lose a title-path game you are out, and anything
    you play afterwards is a LOSERS-bracket placement game (3rd/5th place,
    tagged `bracket == "losers"`). Rounds are walked in order and
    eliminations applied at the END of a round, so games within a round
    cannot affect each other.

    Note: this is distinct from the CONSOLATION bracket (`consolation_bracket()`
    / `bracket == "consolation"`), which is the teams that MISSED the
    playoffs entirely -- see that function's own docstring.
    """
    results = results.copy()
    results["bracket"] = None
    elim: set = set()
    for rid in round_order:
        fresh: set = set()
        for m in results.loc[results["round_id"] == rid, "matchup_id"].unique():
            i = results["matchup_id"] == m
            teams = [t for t in results.loc[i, "team"] if t]
            title = not any(t in elim for t in teams)
            results.loc[i, "bracket"] = "title" if title else "losers"
            if title:
                fresh |= set(results.loc[i & (results["result"] == "L"), "team"])
        elim |= fresh
    return results


def scope_frame(d: pd.DataFrame, scope: str = "title") -> pd.DataFrame:
    """Keep the title path (default), the losers-bracket placement games
    (`scope="losers"`), the missed-playoffs consolation games
    (`scope="consolation"`, only present once merged in), or everything
    (`scope="all"`)."""
    if scope == "all" or not len(d) or "bracket" not in d:
        return d
    return d[d["bracket"] == scope]


def config_paths(playoff_dir: str = "season", league_ids=None) -> dict:
    """{season: config path} for every stored season bracket.

    Configs live one level down, under `<playoff_dir>/<league_id>/<season>.json`
    -- Sleeper gives each season its own league id (see `league_ids` below), so
    a bracket is keyed by BOTH, not by season number alone. Only numeric-named
    subfolders are treated as league folders (a Sleeper league_id is always a
    numeric string); `<playoff_dir>/adp/` and `<playoff_dir>/fixtures/` are
    siblings holding unrelated data (the ADP cache, a manually-referenced
    ground-truth bracket) and are skipped by that same rule -- no denylist to
    keep in sync as new siblings are added.

    `league_ids` restricts the result to brackets belonging to those leagues.
    A bracket is keyed by season, but a season number is not unique across
    leagues -- without this filter, loading some *other* league into the
    dashboard would silently hand it DDBM's brackets and DDBM's champions.
    Sleeper gives each season its own league id, so pass the whole chain.
    """
    import glob
    import os
    ids = {str(i) for i in league_ids} if league_ids is not None else None
    out = {}
    for f in sorted(glob.glob(os.path.join(playoff_dir, "*", "*.json"))):
        if not os.path.basename(os.path.dirname(f)).isdigit():
            continue
        try:
            cfg = playoff_config(f)
        except Exception:
            continue
        if "rounds" not in cfg or not cfg.get("season"):
            continue
        if ids is not None and str(cfg.get("league_id", "")) not in ids:
            continue
        out[str(cfg["season"])] = f
    return out


def champion_of(config, recompute: bool = False):
    """The season's champion per its bracket.

    Configs persist the engine-derived `champion` so a season load is cheap;
    pass `recompute=True` to re-run the bracket from the stored lineups instead
    of trusting the stored value (verify.py does exactly this).
    """
    if isinstance(config, str):
        config = playoff_config(config)
    if not recompute and config.get("champion"):
        return config["champion"]
    return playoff(config, validate=False).champion


def apply_playoffs(seasons: dict, playoff_dir: str = "season",
                   recompute: bool = False) -> dict:
    """Let each season's playoff bracket decide that season's champion.

    Sleeper's `winners_bracket` is the default source of the champion flag, but
    it is only correct for playoffs Sleeper actually ran -- for DDBM 2025 it is
    demonstrably incoherent. Where a bracket config exists it is authoritative,
    and the corrected flag flows into career titles.

    Only brackets belonging to *these* seasons' leagues are applied, so pointing
    the dashboard at another league cannot stamp this league's champions onto it.
    """
    paths = config_paths(playoff_dir,
                         league_ids=[s.league_id for s in seasons.values()])
    for key, s in seasons.items():
        p = paths.get(str(s.season))
        if not p:
            continue
        champ = champion_of(p, recompute=recompute)
        if champ:
            s.standings["champion"] = s.standings["user_name"] == champ
    return seasons


def load_playoffs(playoff_dir: str = "season", league_ids=None) -> dict:
    """{season: Playoff} -- every stored bracket, scored.

    Pass `league_ids` (the league's season chain) to load only that league's
    brackets; see config_paths().
    """
    return {s: playoff(p, validate=False)
            for s, p in config_paths(playoff_dir, league_ids).items()}


def _runner_up(p: "Playoff") -> str | None:
    """The title game's loser -- same final-matchup logic `playoff_summary`'s
    own `outcome()` uses, but standalone since callers here only need the
    team name, not a full per-team outcome frame."""
    cfg = p.config if isinstance(p.config, dict) else {}
    rounds = cfg.get("rounds") or []
    final_id = cfg.get("final") or (
        rounds[-1]["matchups"][-1]["id"] if rounds and rounds[-1].get("matchups") else None)
    if final_id is None:
        return None
    d = p.results
    lost = d[(d["matchup_id"] == final_id) & (d["result"] == "L")]
    return lost.iloc[0]["team"] if len(lost) else None


def _consolation_performance_rows(consolation: list, seasons: list) -> pd.DataFrame:
    """The consolation bracket's started player-weeks in
    `playoff_performances`' own column shape, tagged `bracket == "consolation"`.
    `consolation` is a list of `consolation_bracket()` dicts, `seasons` the matching
    season labels (same order). Used only when a caller asks for the whole
    postseason (playoffs + consolation bracket) in one frame -- see
    `playoff_performances`' `consolation=` argument.

    When a dict carries a `week_rounds` map ({week: round name}), each game's
    `round` name is set from it and `round_id` to a synthetic `"C<week>"` --
    so the "best postseason" charts can colour the consolation bracket by its
    OWN rounds instead of one flat block. Absent it (no round structure)
    every row stays `round = "Consolation bracket"`, `round_id = None`.
    """
    rows = []
    for season, tb in zip(seasons, consolation):
        wk_rounds = (tb or {}).get("week_rounds") or {}
        for g in (tb or {}).get("games", []):
            wk = g.get("week")
            rname = wk_rounds.get(wk) or wk_rounds.get(str(wk)) or "Consolation bracket"
            rid = f"C{wk}" if wk_rounds else None
            for sd in g.get("sides", []):
                for pl in sd.get("lineup", []):
                    rows.append({
                        "season": str(season), "round": rname,
                        "round_id": rid, "bracket": "consolation",
                        "matchup_id": None, "team": sd.get("team"),
                        "player_id": pl.get("player_id"),
                        "player_name": pl.get("player_name"),
                        "position": pl.get("position"),
                        "week": wk, "points": float(pl.get("points") or 0.0),
                        "champion": False, "runner_up": False})
    return pd.DataFrame(rows)


def playoff_performances(playoffs: dict, scope: str = "title",
                         consolation: list | None = None) -> pd.DataFrame:
    """Every started player-week across all brackets (the player-metric grain).

    `round_id` (e.g. "R1"/"R2"/"R3") is already a column on `p.players`
    itself (stamped in `playoff()`) -- only the display `round` NAME is
    merged in here from `p.results`, since merging `round_id` too would
    collide with the one `p.players` already carries and get suffixed
    (`round_id_x`/`round_id_y`) instead of staying plain `round_id`. A
    season's own `config["rounds"]` list is already ordered by bracket
    depth (`R1` before `R2` before `R3`...), so `round_id`'s position
    within that season's own round list is a stable "how deep is this
    round" ordinal even though the display NAME varies per season/league
    (e.g. 2025's "Round 1 (seeds 5-8)" vs 2022's plain "Round 1") and can't
    be compared as a string across seasons the way `round_id` can be
    compared as a position.

    `consolation` (a list of `consolation_bracket()` dicts, one per season key in
    `playoffs`, same order) folds the consolation bracket games into the same
    frame, tagged `bracket == "consolation"` -- for the Postseason view, which
    wants the WHOLE postseason (bracket + consolation bracket) in one chart. It is
    only meaningful with `scope == "all"` (any other scope filters the
    consolation rows straight back out); passing it with `scope == "title"` is a
    harmless no-op.
    """
    frames = []
    for s, p in playoffs.items():
        if not len(p.players):
            continue
        d = p.players.merge(p.results[["matchup_id", "round"]].drop_duplicates(),
                            on="matchup_id", how="left")
        d = d.assign(season=str(s), champion=d["team"] == (p.champion or ""),
                     runner_up=d["team"] == (_runner_up(p) or ""))
        frames.append(d)
    if consolation is not None:
        trows = _consolation_performance_rows(list(consolation), [str(k) for k in playoffs])
        if len(trows):
            frames.append(trows)
    if not frames:
        return pd.DataFrame()
    d = scope_frame(pd.concat(frames, ignore_index=True), scope)
    # player_id rides along: it is the only safe key for a portrait (names are
    # neither unique nor stable).
    cols = ["season", "round", "round_id", "bracket", "matchup_id", "team", "player_id",
            "player_name", "position", "week", "points", "champion", "runner_up"]
    return d[cols].sort_values("points", ascending=False).reset_index(drop=True)


def playoff_players(playoffs: dict, scope: str = "title",
                    consolation: list | None = None) -> pd.DataFrame:
    """Career playoff scoring leaders -- who actually produces in January.

    `consolation` (see `playoff_performances`) folds the consolation bracket in for the
    Postseason view's whole-postseason leaderboard.
    """
    d = playoff_performances(playoffs, scope, consolation=consolation)
    if not len(d):
        return d
    # rings = SEASONS won while on the title roster, not champion player-weeks
    # (counting weeks gave players more rings than seasons played).
    d = d.copy()
    d["_champ_season"] = d["season"].where(d["champion"])
    g = d.groupby(["player_id", "player_name", "position"], as_index=False).agg(
        seasons=("season", "nunique"), games=("points", "size"),
        points=("points", "sum"), best=("points", "max"),
        rings=("_champ_season", "nunique"))
    g["ppg"] = g["points"] / g["games"]
    return g.sort_values("points", ascending=False).reset_index(drop=True)


def playoff_all_stars(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Top career playoff scorer at each position."""
    d = playoff_players(playoffs, scope)
    if not len(d):
        return d
    d = d[d["position"].isin(POSITIONS)]
    idx = d.groupby("position")["points"].idxmax()
    out = d.loc[idx].copy()
    out["position"] = pd.Categorical(out["position"], categories=POSITIONS, ordered=True)
    return out.sort_values("position").reset_index(drop=True)


def playoff_best_games(playoffs: dict, n: int = 15, scope: str = "title") -> pd.DataFrame:
    """The biggest individual playoff performances."""
    d = playoff_performances(playoffs, scope)
    return d.head(n) if len(d) else d


def playoff_busts(playoffs: dict, n: int = 15, scope: str = "title") -> pd.DataFrame:
    """Started, and did nothing."""
    d = playoff_performances(playoffs, scope)
    if not len(d):
        return d
    return d.nsmallest(n, "points").reset_index(drop=True)


def playoff_finals(playoffs: dict) -> pd.DataFrame:
    """Who shows up when the trophy is on the line."""
    frames = []
    for s, p in playoffs.items():
        fid = p.config.get("final")
        if not fid or not len(p.players):
            continue
        d = p.players[p.players["matchup_id"] == fid].copy()
        d["season"] = str(s)
        d["won"] = d["team"] == (p.champion or "")
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    return (d[["season", "team", "won", "player_name", "position", "week", "points"]]
            .sort_values("points", ascending=False).reset_index(drop=True))


def playoff_carry(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """How much of a playoff run came from one player."""
    d = playoff_performances(playoffs, scope)
    if not len(d):
        return d
    by_p = d.groupby(["season", "team", "player_name"], as_index=False)["points"].sum()
    tot = by_p.groupby(["season", "team"], as_index=False)["points"].sum().rename(
        columns={"points": "total"})
    top = by_p.loc[by_p.groupby(["season", "team"])["points"].idxmax()]
    out = top.merge(tot, on=["season", "team"])
    out["share"] = out["points"] / out["total"] * 100
    out = out.rename(columns={"player_name": "top_player", "points": "top_points",
                              "total": "points"})
    return (out[["season", "team", "points", "top_player", "top_points", "share"]]
            .sort_values("share", ascending=False).reset_index(drop=True))


def clutch(seasons: dict, playoffs: dict, scope: str = "title",
           consolation: list | None = None) -> pd.DataFrame:
    """Playoff PPG vs regular-season PPG -- who raises their game.

    `consolation` (a list of `consolation_bracket()` dicts, one per season key in
    `playoffs`, same order) folds each consolation bracket game in as one more
    team-week, for the Postseason view's whole-postseason PPG. Only
    meaningful with `scope == "all"`; a no-op otherwise (the consolation rows
    carry `bracket == "consolation"` and every other scope filters them out).
    """
    frames = [scope_frame(p.results, scope).assign(season=str(s))
              for s, p in playoffs.items()]
    if consolation is not None:
        trows = []
        for season, tb in zip([str(k) for k in playoffs], list(consolation)):
            for g in (tb or {}).get("games", []):
                for sd in g.get("sides", []):
                    if sd.get("team") is None or sd.get("points") is None:
                        continue
                    trows.append({"season": season, "team": sd["team"],
                                  "points": float(sd["points"]),
                                  "result": sd.get("result"),
                                  "bracket": "consolation"})
        if trows:
            frames.append(pd.DataFrame(trows))
    if not frames:
        return pd.DataFrame()
    po = pd.concat(frames, ignore_index=True)
    # Re-scope after the concat: the per-frame scope above ran BEFORE the
    # consolation rows were appended, so this second pass is what keeps the
    # consolation bracket team-weeks only when `scope == "all"` and filters them
    # out otherwise (idempotent for the bracket rows already scoped once).
    po = scope_frame(po, scope)
    po = po[po["result"].isin(["W", "L", "T"])]
    if not len(po):
        return pd.DataFrame()
    reg = pd.concat([s.team_wk for s in seasons.values()], ignore_index=True)
    reg = reg.groupby("user_name", as_index=False)["points"].mean().rename(
        columns={"points": "reg_ppg"})
    g = po.groupby("team", as_index=False).agg(games=("points", "size"),
                                               po_ppg=("points", "mean"))
    g = g.rename(columns={"team": "user_name"}).merge(reg, on="user_name", how="left")
    g["clutch"] = g["po_ppg"] - g["reg_ppg"]
    return (g[["user_name", "reg_ppg", "po_ppg", "clutch", "games"]]
            .sort_values("clutch", ascending=False).reset_index(drop=True))


# --- consolation bracket analytics ------------------------------------------------
# These mirror `playoff_performances` / `playoff_players` / `clutch` above, but
# read the consolation bracket's own games (from `consolation_bracket()`'s `games` list) rather
# than a bracket's `p.players` / `p.results`. The consolation bracket is a set of plain
# Sleeper matchups with no sub-brackets, so there is no `scope` parameter and no
# career span -- it is always one season. Webapp-only; no R counterpart, not in
# the parity export.

def consolation_performances(tb: dict) -> pd.DataFrame:
    """Every STARTED player-week across the consolation bracket -- the player-metric
    grain, the counterpart to `playoff_performances` for the missed-bracket
    games. One row per starter per consolation bracket game.

    `tb` is a `consolation_bracket()` result dict. Returns columns: `week`, `team`,
    `player_id`, `player_name`, `position`, `points`. Empty frame when the
    season has no consolation bracket.
    """
    rows = []
    for g in (tb or {}).get("games", []):
        wk = g.get("week")
        for sd in g.get("sides", []):
            team = sd.get("team")
            for pl in sd.get("lineup", []):
                rows.append({
                    "week": wk, "team": team,
                    "player_id": pl.get("player_id"),
                    "player_name": pl.get("player_name"),
                    "position": pl.get("position"),
                    "points": float(pl.get("points") or 0.0)})
    if not rows:
        return pd.DataFrame(
            columns=["week", "team", "player_id", "player_name", "position", "points"])
    return (pd.DataFrame(rows)
            .sort_values("points", ascending=False).reset_index(drop=True))


def consolation_players(tb: dict) -> pd.DataFrame:
    """Consolation bracket scoring leaders -- who actually produced in the games nobody
    wanted to be playing. The counterpart to `playoff_players`, minus `rings`
    (there is no title to win here) and `seasons` (always one).

    Columns: `player_id`, `player_name`, `position`, `games`, `points`,
    `best`, `ppg`.
    """
    d = consolation_performances(tb)
    if not len(d):
        return pd.DataFrame(
            columns=["player_id", "player_name", "position", "games",
                     "points", "best", "ppg"])
    g = d.groupby(["player_id", "player_name", "position"], as_index=False).agg(
        games=("points", "size"), points=("points", "sum"), best=("points", "max"))
    g["ppg"] = g["points"] / g["games"]
    return g.sort_values("points", ascending=False).reset_index(drop=True)


def consolation_clutch(s, tb: dict) -> pd.DataFrame:
    """Consolation bracket PPG set against each manager's regular-season PPG -- the
    counterpart to `clutch` for the missed-bracket teams. A positive `clutch`
    means the team scored MORE once the games stopped mattering.

    Columns: `user_name`, `reg_ppg`, `to_ppg`, `clutch`, `games`.
    """
    games = (tb or {}).get("games", [])
    rows = []
    for g in games:
        for sd in g.get("sides", []):
            if sd.get("team") is not None and sd.get("points") is not None:
                rows.append({"user_name": sd["team"], "points": float(sd["points"])})
    if not rows:
        return pd.DataFrame(columns=["user_name", "reg_ppg", "to_ppg", "clutch", "games"])
    to = pd.DataFrame(rows).groupby("user_name", as_index=False).agg(
        games=("points", "size"), to_ppg=("points", "mean"))
    reg = getattr(s, "team_wk", None)
    if reg is not None and len(reg) and "user_name" in reg.columns:
        reg = reg.groupby("user_name", as_index=False)["points"].mean().rename(
            columns={"points": "reg_ppg"})
        to = to.merge(reg, on="user_name", how="left")
    else:
        to["reg_ppg"] = pd.NA
    to["clutch"] = to["to_ppg"] - to["reg_ppg"]
    return (to[["user_name", "reg_ppg", "to_ppg", "clutch", "games"]]
            .sort_values("clutch", ascending=False).reset_index(drop=True))


def playoff_margins(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Average margin, best win, worst loss."""
    frames = [scope_frame(p.results, scope) for p in playoffs.values()]
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not len(d):
        return d
    d = d[d["result"].isin(["W", "L", "T"])]
    g = d.groupby("team", as_index=False).agg(
        games=("margin", "size"), avg_margin=("margin", "mean"),
        best_win=("margin", "max"), worst_loss=("margin", "min"))
    return (g.rename(columns={"team": "user_name"})
            .sort_values("avg_margin", ascending=False).reset_index(drop=True))


def playoff_path(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """How hard were the teams you had to beat."""
    frames = [scope_frame(p.results, scope) for p in playoffs.values()]
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not len(d):
        return d
    d = d[d["result"].isin(["W", "L", "T"])]
    g = d.groupby("team", as_index=False).agg(
        games=("opp_points", "size"), opp_ppg=("opp_points", "mean"),
        opp_total=("opp_points", "sum"))
    return (g.rename(columns={"team": "user_name"})
            .sort_values("opp_ppg", ascending=False).reset_index(drop=True))


def playoff_allplay(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Win rate against the whole playoff field each week (soft bracket detector)."""
    frames = [scope_frame(p.results, scope).assign(season=str(s))
              for s, p in playoffs.items()]
    if not frames:
        return pd.DataFrame()
    d = pd.concat(frames, ignore_index=True)
    d = d[d["result"].isin(["W", "L", "T"])].copy()
    if not len(d):
        return pd.DataFrame()
    d["allplay_w"] = 0
    d["allplay_l"] = 0
    for _, g in d.groupby(["season", "weeks"]):
        pts = g["points"].values
        for i in g.index:
            p_ = d.at[i, "points"]
            d.at[i, "allplay_w"] = int((pts < p_).sum())
            d.at[i, "allplay_l"] = int((pts > p_).sum())
    g = d.groupby("team", as_index=False).agg(
        games=("points", "size"), allplay_w=("allplay_w", "sum"),
        allplay_l=("allplay_l", "sum"))
    g["allplay_pct"] = (g["allplay_w"] /
                        (g["allplay_w"] + g["allplay_l"]).clip(lower=1) * 100)
    return (g.rename(columns={"team": "user_name"})
            .sort_values("allplay_pct", ascending=False).reset_index(drop=True))


def seeds(season, through_week: int | None = None, playoff=None) -> pd.DataFrame:
    """Regular-season playoff seeding.

    Seeds come from the REGULAR season, not the final standings -- the final
    table includes the playoff weeks themselves, which reorders the middle of the
    bracket and quietly breaks every seed-based metric.
    """
    if through_week is None:
        if playoff is None:
            raise ValueError("Give through_week or a playoff to infer it from.")
        wk1 = min(int(w) for r in playoff.config["rounds"] for w in r["weeks"])
        through_week = wk1 - 1
    d = season.team_wk[season.team_wk["week"] <= through_week].copy()
    d["w"] = (d["result"] == "W").fillna(False).astype(int)
    d["l"] = (d["result"] == "L").fillna(False).astype(int)
    g = (d.groupby("user_name", as_index=False)
         .agg(wins=("w", "sum"), losses=("l", "sum"), points=("points", "sum"))
         .sort_values(["wins", "points"], ascending=False).reset_index(drop=True))
    g["points"] = g["points"].round(2)
    g["seed"] = g.index + 1
    return g[["seed", "user_name", "wins", "losses", "points"]]


def playoff_seeding(playoffs: dict, seasons: dict) -> pd.DataFrame:
    """Upsets, Cinderellas and chokes, per manager."""
    rows = []
    for s, p in playoffs.items():
        se = seasons.get(str(s))
        if se is None:
            continue
        sd = seeds(se, playoff=p)
        seed_of = dict(zip(sd["user_name"], sd["seed"]))
        fid = p.config.get("final")
        finalists = set(p.results.loc[p.results["matchup_id"] == fid, "team"])
        r = scope_frame(p.results, "title")
        r = r[r["result"].isin(["W", "L", "T"])]
        for team, g in r.groupby("team"):
            sd_ = seed_of.get(team)
            ups = sum(1 for _, x in g.iterrows()
                      if x["result"] == "W" and sd_ and seed_of.get(x["opponent"])
                      and sd_ > seed_of[x["opponent"]])
            ul = sum(1 for _, x in g.iterrows()
                     if x["result"] == "L" and sd_ and seed_of.get(x["opponent"])
                     and sd_ < seed_of[x["opponent"]])
            rows.append({"user_name": team, "season": str(s), "seed": sd_,
                         "upsets": ups, "upset_losses": ul,
                         "in_final": team in finalists,
                         "champ": team == (p.champion or "")})
    if not rows:
        return pd.DataFrame()
    d = pd.DataFrame(rows)
    out = []
    for nm, g in d.groupby("user_name"):
        out.append({
            "user_name": nm, "runs": g["season"].nunique(),
            "avg_seed": float(g["seed"].mean()),
            "best_seed": int(g["seed"].min()),
            "upsets": int(g["upsets"].sum()),
            "upset_losses": int(g["upset_losses"].sum()),
            # Cinderella: deepest run relative to seed (a low seed in a final scores high)
            "cinderella": int(g.apply(
                lambda x: x["seed"] if x["in_final"] else 0, axis=1).max()),
            "chokes": int(((g["seed"] <= 2) & (~g["in_final"])).sum()),
        })
    return (pd.DataFrame(out)
            .sort_values(["upsets", "avg_seed"], ascending=[False, True])
            .reset_index(drop=True))


def playoff_replay(playoffs: dict, seasons: dict, scope: str = "title") -> pd.DataFrame:
    """Did the wrong team win? Re-score every game with optimal lineups.

    Only works where the season object holds that week's rosters. DDBM 2025's
    final is week 18, past last_scored_leg (17), so it cannot be replayed --
    those rows come back NA rather than being quietly dropped.
    """
    from .season import optimal_points
    rows = []
    for s, p in playoffs.items():
        se = seasons.get(str(s))
        if se is None:
            continue
        r = scope_frame(p.results, scope)
        r = r[r["result"].isin(["W", "L"])]
        for m, g in r.groupby("matchup_id"):
            if len(g) != 2:
                continue
            wks = [int(w) for w in str(g["weeks"].iloc[0]).split("+")]
            opt = []
            for tm in g["team"]:
                rid = se.user_map.loc[se.user_map["user_name"] == tm, "roster_id"]
                if not len(rid):
                    opt.append(None)
                    continue
                # Playoff weeks -- must read the unscoped frame.
                pw = getattr(se, "pl_wk_all", se.pl_wk)
                d = pw[(pw["roster_id"] == rid.iloc[0])
                       & (pw["week"].isin(wks))]
                if not len(d) or not set(wks).issubset(set(d["week"])):
                    opt.append(None)
                    continue
                opt.append(round(sum(
                    optimal_points(d[d["week"] == w], se.slots) for w in wks), 2))
            act_win = g.loc[g["result"] == "W", "team"].iloc[0]
            if None in opt:
                opt_win, flipped = None, None
            else:
                opt_win = g["team"].iloc[0] if opt[0] > opt[1] else g["team"].iloc[1]
                flipped = opt_win != act_win
            rows.append({
                "season": str(s), "matchup_id": m, "round": g["round"].iloc[0],
                "team_a": g["team"].iloc[0], "team_b": g["team"].iloc[1],
                "actual_a": g["points"].iloc[0], "actual_b": g["points"].iloc[1],
                "optimal_a": opt[0], "optimal_b": opt[1],
                "actual_winner": act_win, "optimal_winner": opt_win,
                "flipped": flipped})
    return pd.DataFrame(rows)


def playoff_stats(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Career playoff record per manager, across every stored bracket.

    Regular-season metrics say nothing about January. This is the postseason
    résumé: how often you got there, how you did once you did, and how deep.
    `scope` defaults to "title", so placement games are not counted as wins.
    """
    rows = []
    for season, p in playoffs.items():
        final_id = p.config.get("final")
        sc = scope_frame(p.results, scope)
        played = sc[sc["result"].isin(["W", "L", "T"])]
        for team, g in p.results.groupby("team"):
            gp = played[played["team"] == team]
            rows.append({
                "user_name": team, "season": str(season),
                "games": len(gp),
                "wins": int((gp["result"] == "W").sum()),
                "losses": int((gp["result"] == "L").sum()),
                "points": round(float(pd.to_numeric(gp["points"], errors="coerce").sum()), 2),
                "title": bool(p.champion == team),
                "final": bool((g["matchup_id"] == final_id).any()) if final_id else False,
            })
    d = pd.DataFrame(rows)
    if d.empty:
        return d
    out = (d.groupby("user_name", as_index=False)
           .agg(appearances=("season", "nunique"), games=("games", "sum"),
                wins=("wins", "sum"), losses=("losses", "sum"),
                points=("points", "sum"), titles=("title", "sum"),
                finals=("final", "sum")))
    out["win_pct"] = out["wins"] / out[["games"]].clip(lower=1)["games"] * 100
    out["ppg"] = out["points"] / out[["games"]].clip(lower=1)["games"]
    return out.sort_values(["titles", "win_pct", "ppg"],
                           ascending=False).reset_index(drop=True)


def playoff_summary(p: Playoff) -> pd.DataFrame:
    """Per-team run through the bracket.

    `outcome` narrates how each team's run ended and is **never null**: a team
    that never lost has no elimination round, and letting that fall through as a
    missing value renders as the literal "nan" (pandas NaN is truthy, so a
    template's `or` fallback never fires). The champion and the runner-up are
    named outright rather than described by the round they went out in, which
    for them is either nothing at all or the misleading "lost in Final".
    """
    d = p.results
    cfg = p.config if isinstance(p.config, dict) else {}
    rounds = cfg.get("rounds") or []
    final_id = cfg.get("final") or (
        rounds[-1]["matchups"][-1]["id"] if rounds and rounds[-1].get("matchups") else None)

    def outcome(team, g):
        if p.champion and team == p.champion:
            return "Champion"
        # Only the championship matchup makes a runner-up; a consolation final
        # is a different bracket and its loser was eliminated earlier.
        if final_id is not None and ((g["matchup_id"] == final_id)
                                     & (g["result"] == "L")).any():
            return "Runner-up"
        # Elimination is the last loss in the TITLE bracket, not the last loss
        # overall -- consolation games are played after a team is already out,
        # so ranking by them overstates the run ("lost in Round 3" for a team
        # knocked out of contention in Round 2). Fall back to any loss for a
        # team that somehow never appears in the title bracket.
        lost = g[g["result"] == "L"]
        title = lost[lost["bracket"] == "title"] if "bracket" in lost else lost
        out_in = (title if len(title) else lost)
        if len(out_in):
            return f"Lost in {out_in.iloc[-1]['round']}"
        # Never lost and no title: the bracket has not finished resolving.
        return "Still alive" if not p.champion else "N/A"

    # Seed is the commissioner's own seeding from the config -- which is the
    # REGULAR-season order (standings.reg_position), not the blended win/loss
    # position that counts postseason weeks. Verified: for 2025 reg_position
    # reproduces all eight stored seeds, final_position only four.
    seed_of = {v: int(k) for k, v in (cfg.get("_seeds") or {}).items()}

    rows = []
    for team, g in d.groupby("team"):
        pl = g[g["result"].isin(["W", "L", "T"])]
        played = int(len(pl))
        wins = int((g["result"] == "W").sum())
        pts = float(pd.to_numeric(g["points"], errors="coerce").sum())
        gp = pd.to_numeric(pl["points"], errors="coerce")
        gm = pd.to_numeric(pl["margin"], errors="coerce")
        rows.append({
            "team": team,
            "seed": seed_of.get(team),
            "games": played,
            "wins": wins,
            "losses": int((g["result"] == "L").sum()),
            "points": pts,
            # Rate stats live here so one table can carry the whole run; a team
            # with only byes has no played game, so guard the divide. These are
            # the postseason counterparts of the regular-season table, so a
            # two-game run can be read against a four-game one.
            "win_pct": (wins / played * 100) if played else 0.0,
            "ppg": (pts / played) if played else 0.0,
            "high": float(gp.max()) if played and gp.notna().any() else 0.0,
            "low": float(gp.min()) if played and gp.notna().any() else 0.0,
            "avg_margin": float(gm.mean()) if played and gm.notna().any() else 0.0,
            "outcome": outcome(team, g)})
    out = pd.DataFrame(rows)
    return out.sort_values(["wins", "points"], ascending=False).reset_index(drop=True)


def _week_nums(v) -> list[int]:
    """Week numbers out of a round's `weeks` field ("15", "15-16", "15,16")."""
    out = []
    for part in str(v).replace("+", ",").split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            if a.strip().isdigit() and b.strip().isdigit():
                out += list(range(int(a), int(b) + 1))
        elif part.isdigit():
            out.append(int(part))
    return out


def _lineup_of(s, roster_id, week: int, ranks=None) -> list[dict]:
    """The starters a roster fielded that week, in scoreboard slot order.

    The consolation bracket is a plain Sleeper matchup, so its lineups live in `pl_wk`,
    not in the bracket engine's `players`. Ordering goes through `assign_slots`
    so the drill reads QB, RB1, RB2, WR1, WR2, TE, FLEX, K, DEF like every other
    roster table, rather than in whatever order the frame happens to hold.

    `ranks` is optional, same shape/purpose as `_lineup_from_players`' own --
    stamped onto each row as `pos_rank` so the consolation bracket's own matchup
    drilldown carries the same season-rank decoration as the bracket's.
    """
    import pandas as pd

    from .season import assign_slots
    ranks = ranks or {}
    pw = getattr(s, "pl_wk_all", None)
    if pw is None or not len(pw):
        return []
    d = pw[(pw["roster_id"] == roster_id) & (pw["week"] == week)
           & pw["is_starter"].fillna(False)]
    if not len(d):
        return []
    d = d.sort_values("points", ascending=False)
    try:
        d = assign_slots(d, getattr(s, "slots", {}) or {})
    except Exception:
        d = d.assign(slot=d["position"])
    return [{"slot": r.slot, "player_id": str(r.player_id), "player_name": r.player_name,
             "position": r.position,
             "points": float(r.points) if pd.notna(r.points) else 0.0,
             "pos_rank": ranks.get(str(r.player_id), {}).get("rank")}
            for r in d.itertuples(index=False)]


def _bench_of(s, roster_id, week: int, ranks=None) -> list[dict]:
    """The bench a roster carried that week -- the counterpart to
    `_lineup_of`'s starters, everyone else on the roster that week.
    Unlike a bracket game (commissioner-submitted starters only, no bench
    concept exists), the consolation bracket is a plain Sleeper matchup with real
    `pl_wk` roster data, so its own bench is genuinely knowable. No slot
    (bench isn't scoreboard-ordered), same shape `_redraft_side_score`'s
    own bench rows use.
    """
    import pandas as pd

    ranks = ranks or {}
    pw = getattr(s, "pl_wk_all", None)
    if pw is None or not len(pw):
        return []
    d = pw[(pw["roster_id"] == roster_id) & (pw["week"] == week)
           & ~pw["is_starter"].fillna(False)]
    if not len(d):
        return []
    d = d.sort_values("points", ascending=False)
    return [{"player_id": str(r.player_id), "player_name": r.player_name,
             "position": r.position,
             "points": float(r.points) if pd.notna(r.points) else 0.0,
             "pos_rank": ranks.get(str(r.player_id), {}).get("rank")}
            for r in d.itertuples(index=False)]


def consolation_bracket(s, p=None) -> dict:
    """The race at the bottom -- who finished last, and the game that decided it.

    The consolation bracket is the teams that **missed the championship bracket** and the
    games they played once the postseason started -- ordinary Sleeper matchups
    that never appear in the bracket config, so reading the config alone reports
    no consolation bracket at all (2025: sparky1335 beat rezzu in wk15).

    The config's **consolation games are deliberately NOT counted here.** In this
    league they are placement games between teams already in the bracket -- a
    3rd-place game, not a race for the basement -- so the loser of the last one
    is frequently a strong team: in 2022 it was diogenesthecat, who finished
    *first* in the regular season. Reporting that as last place is simply wrong.
    Those games remain visible, correctly labelled, in the bracket walk.

    `winner` = the winner of the consolation bracket's FINAL game.  `last` =
    the team FIRST OUT of the consolation bracket -- the one whose run there
    ended earliest (fewest rounds survived), NOT the loser of the final game
    (that team went the deepest on the losers' side and finishes nearer
    mid-table).  With no game to decide either end, the best/worst
    regular-season finish among the missed teams stands in -- labelled as
    such rather than presented as a result.  A season where every team
    reached the championship bracket has no consolation bracket, and says so.

    Each game's `lineup` rows carry `pos_rank` (each starter's FINAL
    season-long position finish), best-effort -- same "never blocks
    rendering" contract as `game_log`'s own ranks. Each side also carries
    `bench` (everyone else that roster carried that week -- unlike a
    bracket game, a plain Sleeper matchup's full roster is genuinely
    knowable) and each `lineup` row gets `cmp` ('up'/'down'/'even', that
    slot's own win/loss against the other side's same slot).
    """
    import pandas as pd

    st = getattr(s, "standings", None)
    # Postseason weeks: the consolation bracket lives outside the regular season.
    tw = getattr(s, "team_wk_all", None)
    in_bracket, po_start, games = set(), None, []
    # `season_rank` -- a MANAGER's own final regular-season standing, shown
    # next to their name in the consolation bracket's own matchup rows, same as the
    # bracket's (see `game_log`).
    rank_by_team: dict = {}
    if st is not None and len(st):
        for r in st.itertuples(index=False):
            fp = getattr(r, "final_position", None)
            if pd.notna(fp):
                rank_by_team[r.user_name] = int(fp)

    if p is not None and len(getattr(p, "results", [])):
        in_bracket = {t for t in p.results["team"].dropna()}
        wks = [w for v in p.results.get("weeks", []) for w in _week_nums(v)]
        po_start = min(wks) if wks else None

    # Teams the bracket never included -- their postseason games are plain
    # matchups in team_wk, which is the only place a 2025-shaped consolation bracket lives.
    missed = []
    if st is not None and len(st):
        missed = [n for n in st["user_name"] if n not in in_bracket]
    if missed and tw is not None and len(tw) and po_start:
        try:
            ranks = metrics.season_position_ranks(s)
        except Exception:
            ranks = {}
        d = tw[(tw["week"] >= po_start) & tw["user_name"].isin(missed)
               & tw["matchup_id"].notna()]
        for (wk, mid), g in d.groupby(["week", "matchup_id"], sort=True):
            if len(g) < 2:
                continue
            sides = [{"team": r["user_name"], "points": float(r["points"]),
                      "roster_id": r["roster_id"],
                      "lineup": _lineup_of(s, r["roster_id"], int(wk), ranks),
                      "bench": _bench_of(s, r["roster_id"], int(wk), ranks),
                      "season_rank": rank_by_team.get(r["user_name"]),
                      "result": r["result"]} for _, r in g.iterrows()]
            _stamp_slot_cmp(sides)
            games.append({
                "week": int(wk), "round": f"Week {int(wk)}", "source": "missed",
                "sides": sides,
                "winner": next((x["team"] for x in sides if x["result"] == "W"), None),
                "loser": next((x["team"] for x in sides if x["result"] == "L"), None)})

    def wk_of(g) -> int:
        n = _week_nums(g["week"])
        return max(n) if n else 0

    games.sort(key=wk_of)
    last, winner, basis = None, None, None
    decided = [g for g in games if g["loser"]]
    if decided:
        # WINNER tops the consolation bracket: the winner of its FINAL game.
        winner = max(decided, key=wk_of)["winner"]
        basis = "game"
        # LAST PLACE is the team FIRST OUT of the consolation bracket -- the
        # one who finished WORST there, not the loser of the final game (that
        # team went the DEEPEST on the losers' side, so it is nearer
        # mid-table). Preferred signal: Sleeper's real `losers_bracket`, where
        # the loser of the highest-`p` placement game (`p == 5` in a 6-team
        # field decides 5th/6th) is dead last. Fallback (no coherent losers
        # bracket): the team whose consolation run ended earliest (smallest
        # last-week-played), ties broken by worse regular-season finish.
        lg_id = getattr(s, "league_id", None)
        ssn = getattr(s, "season", None)
        try:
            _lc = sleeper_losers_bracket(lg_id, ssn) if lg_id else None
            _pl = _lc.get("_placements") if _lc else None
        except Exception:
            _lc, _pl = None, None
        if _lc and _pl:
            worst_mid = max(_pl, key=lambda m: int(_pl[m]))     # highest place number
            for rd in _lc.get("rounds", []):
                for mu in rd.get("matchups", []):
                    if str(mu.get("id")) != str(worst_mid):
                        continue
                    w = mu.get("_sleeper_winner")
                    sides = [mu.get("home", {}).get("team"), mu.get("away", {}).get("team")]
                    last = next((t for t in sides if t and t != w), None)
        if last is None:
            last_wk_of: dict = {}
            for g in games:
                w = wk_of(g)
                for sd in g["sides"]:
                    nm = sd.get("team")
                    if nm:
                        last_wk_of[nm] = max(last_wk_of.get(nm, 0), w)
            fp_of = {}
            if st is not None and "final_position" in st:
                fp_of = {r.user_name: getattr(r, "final_position", 0)
                         for r in st.itertuples(index=False)}
            if last_wk_of:
                last = min(last_wk_of,
                           key=lambda nm: (last_wk_of[nm], -(fp_of.get(nm) or 0)))
        if last is None:
            basis = None
    elif missed and st is not None and "final_position" in st:
        pool = st[st["user_name"].isin(missed)].sort_values("final_position")
        if len(pool):
            last, basis = pool.iloc[-1]["user_name"], "standings"
            winner = pool.iloc[0]["user_name"]

    # Each missed team's OWN postseason record -- rate stats from the consolation bracket
    # games they actually played (`games` above), the same shape playoff_summary
    # gives a bracket team, so the two can share one combined board rather than
    # one side going blank. `wins`/`losses`/`points` alongside them stay the
    # season-long standings figures (context for who they were before missing
    # the cut), kept separate from the postseason-only `po_*` fields.
    po: dict = {}
    for g in games:
        for sd in g["sides"]:
            nm = sd["team"]
            other = next((x["points"] for x in g["sides"] if x["team"] != nm), None)
            rec = po.setdefault(nm, {"games": 0, "wins": 0, "losses": 0,
                                     "points": [], "margins": []})
            rec["games"] += 1
            if sd.get("result") == "W":
                rec["wins"] += 1
            elif sd.get("result") == "L":
                rec["losses"] += 1
            rec["points"].append(sd["points"])
            if other is not None:
                rec["margins"].append(sd["points"] - other)

    # Season context for the teams involved. The per-game detail (both lineups)
    # hangs off `games` instead -- the drill is a matchup drill, so a per-team
    # week log would be answering a question nobody asked here.
    teams = []
    if st is not None and len(st):
        pool = st[st["user_name"].isin(missed)] if missed else st.iloc[0:0]
        for r in pool.itertuples(index=False):
            rec = po.get(r.user_name)
            teams.append({"user_name": r.user_name,
                          "final_position": int(getattr(r, "final_position", 0) or 0),
                          "wins": int(r.wins), "losses": int(r.losses),
                          "points": float(r.points),
                          # None (not 0) when the team never had a consolation game --
                          # keeps every po_* field blank together in the combined
                          # board rather than a stray "0" beside a dash placeholder.
                          "po_games": rec["games"] if rec else None,
                          "po_wins": rec["wins"] if rec else None,
                          "po_losses": rec["losses"] if rec else None,
                          "po_ppg": (sum(rec["points"]) / rec["games"])
                                    if rec and rec["games"] else None,
                          "po_high": max(rec["points"]) if rec and rec["points"] else None,
                          "po_low": min(rec["points"]) if rec and rec["points"] else None,
                          "po_avg_margin": (sum(rec["margins"]) / len(rec["margins"]))
                                           if rec and rec["margins"] else None})
    teams.sort(key=lambda t: t["final_position"])
    return {"games": games, "teams": teams, "last": last, "winner": winner,
            "basis": basis, "missed": missed}



def reference_scores(s) -> dict:
    """`{(manager, week): points}` for every scored week of the season.

    The bracket chart uses it to show what a team **actually scored** in a week
    it had no bracket game -- a bye, or a round it was waiting out. Those nodes
    otherwise read as a dash, which looks like missing data when the score is
    right there in the season. It is reference only and the chart marks it as
    such: nothing here counts toward a bracket result.
    """
    tw = getattr(s, "team_wk_all", None)
    if tw is None or not len(tw):
        return {}
    return {(r.user_name, int(r.week)): float(r.points)
            for r in tw.itertuples(index=False)}


def postseason_weeks(s, p=None) -> list[dict]:
    """Week-by-week detail for the weeks the regular season no longer covers.

    The Weekly tab is regular-season only, so weeks 15+ have to be readable
    somewhere -- this is that view, and it belongs with the postseason. Each
    team's score is shown with WHAT IT WAS FOR, which is the whole point: in a
    league whose playoff runs outside Sleeper, a postseason week holds bracket
    games, byes, consolation bracket games and teams simply not playing, all at once,
    and an unlabelled column of points cannot be told apart.

    `bracket_points` come from the engine (the commissioner's submitted lineups,
    priced under the league's scoring chart) while `points` is Sleeper's own
    weekly total. They are computed from completely different inputs, so both
    are carried -- and across every stored season all 48 bracket team-weeks
    agree exactly, which is a standing corroboration that the engine and Sleeper
    price the same rosters the same way. A future season where they diverge is
    worth investigating, not papering over.

    Note the view can only cover weeks Sleeper actually scored: 2025's final is
    week 18, past `last_scored_leg`, so it appears in the bracket but not here.
    """
    tw = getattr(s, "team_wk_all", None)
    pws = getattr(s, "playoff_week_start", None)
    if tw is None or not len(tw) or not pws:
        return []

    # Bracket sides grouped by matchup (so pairings are visible, not just a flat
    # column of scores), plus byes and each matchup's round.
    playing, byes, po_pts = {}, {}, {}
    br_sides, br_round = {}, {}   # week -> {matchup_id: [team, ...]}, {matchup_id: round}
    if p is not None and len(getattr(p, "results", [])):
        for mid, g in p.results.groupby("matchup_id"):
            first = g.iloc[0]
            rnd = first.get("round") or first.get("round_id")
            for w in _week_nums(first["weeks"]):
                for _, r in g.iterrows():
                    if not pd.notna(r["team"]):
                        continue
                    if r["result"] in ("W", "L", "T"):
                        playing.setdefault(w, set()).add(r["team"])
                        br_sides.setdefault(w, {}).setdefault(mid, []).append(r["team"])
                        br_round.setdefault(w, {})[mid] = rnd
                        if pd.notna(r["points"]):
                            po_pts[(r["team"], w)] = float(r["points"])
                    elif r["result"] == "BYE":
                        byes.setdefault(w, set()).add(r["team"])

    def _side(nm, w):
        return {"user_name": nm, "points": pts.get(nm),
                "bracket_points": po_pts.get((nm, w))}

    out = []
    for w in sorted(int(x) for x in tw.loc[tw["week"] >= int(pws), "week"].unique()):
        wk = tw[tw["week"] == w]
        pts = {r.user_name: float(r.points) for r in wk.itertuples(index=False)}
        rows = []
        for r in wk.itertuples(index=False):
            nm = r.user_name
            if nm in playing.get(w, set()):
                role, note = "bracket", "bracket game"
            elif nm in byes.get(w, set()):
                role, note = "bye", "bye, advanced without playing"
            elif pd.notna(getattr(r, "matchup_id", None)):
                role, note = "outside", "played, but outside the bracket"
            else:
                role, note = "idle", "no game"
            rows.append({"user_name": nm, "points": float(r.points),
                         "bracket_points": po_pts.get((nm, w)), "role": role, "note": note})
        if not rows:
            continue

        # The week's games as pairings: bracket matchups, then games played
        # outside the bracket, then byes and idle teams.
        games, seen = [], set(byes.get(w, set()))
        for mid, teams in br_sides.get(w, {}).items():
            seen.update(teams)
            sides = sorted((_side(t, w) for t in teams),
                           key=lambda x: -(x["bracket_points"] if x["bracket_points"] is not None
                                           else (x["points"] or 0)))
            games.append({"kind": "bracket", "round": br_round[w].get(mid), "sides": sides})
        outside = wk[(~wk["user_name"].isin(seen)) & (wk["matchup_id"].notna())]
        for _mm, gg in outside.groupby("matchup_id"):
            sides = sorted(({"user_name": rr.user_name, "points": float(rr.points),
                             "bracket_points": None} for rr in gg.itertuples(index=False)),
                           key=lambda x: -(x["points"] or 0))
            games.append({"kind": "outside", "round": None, "sides": sides})
        byelist = [_side(t, w) for t in sorted(byes.get(w, set()))]
        idle = [{"user_name": r.user_name, "points": float(r.points)}
                for r in wk[(~wk["user_name"].isin(seen)) & (wk["matchup_id"].isna())].itertuples(index=False)]
        rvals = list({str(v) for v in br_round.get(w, {}).values()})
        out.append({"week": w, "round": rvals[0] if len(rvals) == 1 else None,
                    "rows": sorted(rows, key=lambda x: -x["points"]),
                    "games": games, "byes": byelist, "idle": idle})
    return out


def _stamp_slot_cmp(sides) -> None:
    """Per-slot win/loss highlight -- mutates each side's `lineup` rows in
    place with `cmp` ('up'/'down'/'even'), matching a slot against the
    OTHER side's same slot. Same idiom `draft.redraft_playoff` already uses
    for its own opt_lineup rows, so a matchup drilldown reads the same way
    whether it's a real bracket game, the consolation bracket, or the redraft sim.

    Only meaningful for exactly two sides -- a bye or a game missing its
    opponent leaves rows unstamped (`cmp` stays absent, same as
    `_lineupmacro.html`'s own "absent rows just don't highlight" contract).
    """
    if len(sides) != 2:
        return
    opp_pts = [{p["slot"]: p["points"] for p in sd.get("lineup") or []} for sd in sides]
    for i, sd in enumerate(sides):
        other = opp_pts[1 - i]
        for p in sd.get("lineup") or []:
            opp = other.get(p["slot"])
            p["cmp"] = (None if opp is None else
                       "up" if p["points"] > opp else
                       "down" if p["points"] < opp else "even")


def _lineup_from_players(players, s, mid, team, ranks=None) -> list[dict]:
    """One side of a bracket matchup as a scoreboard-ordered lineup.

    The engine's per-player frame (`Playoff.players`) already holds each submitted
    starter's points for a matchup; order it through `assign_slots` so the drill
    reads QB, RB1, RB2, ... like every other roster table in the app.

    `ranks` ({player_id: {"rank", ...}}, from `metrics.season_position_ranks`)
    is optional and stamped onto each row as `pos_rank` -- the player's FINAL
    season-long position finish, shown beside his name the same way the
    weekly report shows a THIS-WEEK rank. `player_id` rides along so the
    shared `_lineupmacro.html` can key headshots/season-rank off it.
    """
    import pandas as pd

    from .season import assign_slots
    ranks = ranks or {}
    if players is None or not len(players):
        return []
    d = players[(players["matchup_id"] == mid) & (players["team"] == team)]
    if not len(d):
        return []
    d = d.sort_values("points", ascending=False)
    try:
        d = assign_slots(d, getattr(s, "slots", {}) or {})
    except Exception:
        d = d.assign(slot=d["position"])
    return [{"slot": r.slot, "player_id": str(r.player_id), "player_name": r.player_name,
             "position": r.position,
             "points": float(r.points) if pd.notna(r.points) else 0.0,
             "pos_rank": ranks.get(str(r.player_id), {}).get("rank")}
            for r in d.itertuples(index=False)]


def game_log(s, p, consolation=None) -> list[dict]:
    """The whole postseason as ONE game log: bracket games grouped by round, each
    expandable to both submitted lineups, with byes and the consolation bracket folded in.

    This is the single scoreboard->lineups drilldown the Playoffs tab reads from --
    the same idiom the Weekly tab and consolation bracket already use -- replacing the old
    trio (the bracket walk, the per-matchup chart, and a separate week table) that
    each re-drew the same games. The bracket graphic stays as the visual map; this
    is the readable log beneath it.

    Returns a list of round groups in bracket order:
      {key, label, weeks, kind, games:[{id, bracket, weeks, sides, winner, margin,
       pending}], byes:[{team, points, pending}]}
    `label` is the bolded round title WITH its seeded matchups folded in, e.g.
    "Round 1 (#5 vs #8, #6 vs #7)"; `blurb`, when present, no longer restates
    those matchups -- it's the bye callout ("Seeds 1-4 on a bye.") plus, for a
    "choose-your-opponent" round (one whose display name says "pick", this
    league's own 2025 custom bracket), a sentence naming who picked whom
    ("Seed 3 chooses #8, leaving seed 4 to take on #7.").
    where each side is {team, points, result, season_rank, lineup:[{slot,
    player_id, player_name, position, points, pos_rank, cmp}]}. `pos_rank`
    is each starter's FINAL season-long position finish (best-effort -- a
    season this Season stand-in can't fully price degrades to no ranks
    rather than failing the whole log, same "never blocks rendering"
    contract as the headshot/avatar lookups elsewhere in this app). `cmp`
    ('up'/'down'/'even') is that slot's own win/loss against the OTHER
    side's same slot (see `_stamp_slot_cmp`); a bracket game's lineup has
    no `bench` (the commissioner's config only ever records starters), but
    a consolation bracket game's does (real `pl_wk` roster data). The consolation bracket /
    outside-bracket games are appended as trailing `kind == "consolation"` groups,
    one per postseason week (so the section reads round-by-round like the
    bracket above it), so a league whose playoff runs outside Sleeper is
    bracketed here too, not stranded in a separate section.
    """
    import pandas as pd

    groups: list[dict] = []
    cfg = p.config if isinstance(getattr(p, "config", None), dict) else {}
    results = getattr(p, "results", None)
    players = getattr(p, "players", None)
    ref = reference_scores(s)
    rounds_cfg = cfg.get("rounds") or []
    # Same convention as `playoff_summary`'s own `final_id` resolution: an
    # explicit `config["final"]` wins, falling back to the last matchup of the
    # last configured round for a config that never set one.
    final_id = cfg.get("final") or (
        rounds_cfg[-1]["matchups"][-1]["id"]
        if rounds_cfg and rounds_cfg[-1].get("matchups") else None)
    try:
        ranks = metrics.season_position_ranks(s)
    except Exception:
        ranks = {}
    # `season_rank` -- a MANAGER's own final regular-season standing, shown
    # next to their name in a matchup row the same way `pos_rank` (above)
    # is shown next to a player's. Plain attribute lookup (no stat pricing),
    # so no best-effort wrapping needed -- just degrades to no ranks for a
    # Season stand-in with no `standings`.
    st = getattr(s, "standings", None)
    rank_by_team: dict = {}
    if st is not None and len(st):
        for r in st.itertuples(index=False):
            fp = getattr(r, "final_position", None)
            if pd.notna(fp):
                rank_by_team[r.user_name] = int(fp)

    def _sort_sides(sides):
        # Winner first, then by points -- so a decided game reads "winner def. loser".
        sides.sort(key=lambda x: (x["result"] != "W",
                                  -(x["points"] if x["points"] is not None else -1)))

    def _margin(sides):
        if len(sides) == 2 and all(x["points"] is not None for x in sides):
            return round(abs(sides[0]["points"] - sides[1]["points"]), 2)
        return None

    def _matchup_label(game):
        # "#3 vs #8" from each side's own final regular-season seed; a side
        # with no resolvable seed (a TBD/pending slot) drops its own "#N" but
        # keeps the "vs" pairing, so a still-unresolved game still reads as a
        # game rather than being silently skipped.
        sides = game.get("sides") or []
        if len(sides) != 2:
            return None
        a, b = sides
        a_lbl = f"#{a['season_rank']}" if a.get("season_rank") else "TBD"
        b_lbl = f"#{b['season_rank']}" if b.get("season_rank") else "TBD"
        return f"{a_lbl} vs {b_lbl}"

    def _round_title(rd_num, name, games, is_final):
        # The bolded round header: "Round N (#5 vs #8, #6 vs #7)". Matchups
        # are named by seed ("#1 vs #4") rather than just counted, generalized
        # from the round's own shape rather than its display name -- names
        # vary by league/season (plain "Round 1" vs "Round 1 (seeds 5-8)"),
        # same reasoning `plot_playoff_players_splice` already applies to
        # round coloring (see CLAUDE.md). The week itself stays a separate
        # field (`grp.weeks`), rendered next to this title, not folded in here.
        # Any existing "(...)" suffix on the config's own display name (this
        # league's "Round 1 (seeds 5-8)" / "Round 2 (seeds 3-4 pick)") is
        # stripped here -- it's now redundant with the seeded matchups this
        # function appends, and the "pick" half is covered by `_pick_blurb`'s
        # own sentence instead. `_pick_blurb` still reads the UNSTRIPPED name
        # for its "pick" detection, so only the title display is affected.
        base = re.sub(r"\s*\([^)]*\)\s*$", "", name).strip() if name else ""
        base = base or f"Round {rd_num}"
        matchups = [m for m in (_matchup_label(g) for g in games) if m]
        if not matchups:
            return base
        return f"{base} ({', '.join(matchups)})"

    def _seed_ranges(seeds):
        # [1,2,3,4] -> "1-4"; [1,3,4] -> "1, 3-4"; [2] -> "2". Consecutive
        # integer seeds collapse into a range so a full top-seed bye block
        # reads as "Seeds 1-4" instead of "Seeds 1, 2, 3, 4".
        seeds = sorted(set(seeds))
        if not seeds:
            return ""
        parts, start, prev = [], seeds[0], seeds[0]
        for n in seeds[1:]:
            if n == prev + 1:
                prev = n
                continue
            parts.append(f"{start}-{prev}" if start != prev else f"{start}")
            start = prev = n
        parts.append(f"{start}-{prev}" if start != prev else f"{start}")
        return ", ".join(parts)

    def _bye_blurb(byes):
        # Just the bye callout now that matchups live in the round title --
        # "Seeds 1-4 on a bye." A bye with no resolvable seed is dropped from
        # the seed list but still counted, so the sentence never silently
        # disappears just because one team's rank couldn't be resolved.
        if not byes:
            return None
        seeds = [b["season_rank"] for b in byes if b.get("season_rank")]
        n_unseeded = sum(1 for b in byes if not b.get("season_rank"))
        bits = []
        if seeds:
            label = "Seed" if len(seeds) == 1 else "Seeds"
            bits.append(f"{label} {_seed_ranges(seeds)}")
        if n_unseeded:
            bits.append(f"{n_unseeded} more team{'s' if n_unseeded != 1 else ''}")
        return " and ".join(bits) + " on a bye."

    def _pick_blurb(name, games):
        # "Choose-your-opponent" rounds (this league's own 2025 custom
        # bracket: "Round 2 (seeds 3-4 pick)", "Round 3 (seeds 1-2 pick)")
        # aren't detectable from game shape alone -- a pick round and a
        # normal round both look like "N games, no byes" -- so this reads
        # the SAME signal the round's own display name already carries
        # ("pick" in the name), rather than inventing a second config field.
        # Within a pick round the higher seed (lower season_rank number) in
        # each game is the chooser; games are read out chooser-seed-first
        # ("best seed picks first"). Every pick but the last is a real choice
        # ("Seed 3 chooses #8"); the last pick seed has nothing left to
        # choose from, so it's stated as the automatic leftover ("leaving
        # seed 4 to take on #7") rather than a second "chooses". A game
        # where either side's seed can't be resolved is skipped -- there's
        # no chooser to name.
        if not name or "pick" not in name.lower():
            return None
        picks = []
        for g in games:
            sides = g.get("sides") or []
            if len(sides) != 2:
                continue
            a, b = sides
            ra, rb = a.get("season_rank"), b.get("season_rank")
            if not ra or not rb:
                continue
            chooser, other = (a, b) if ra < rb else (b, a)
            picks.append((chooser["season_rank"], other["season_rank"]))
        if not picks:
            return None
        picks.sort()
        bits = [f"Seed {c} chooses #{o}" for c, o in picks[:-1]]
        last_c, last_o = picks[-1]
        bits.append(f"leaving seed {last_c} to take on #{last_o}"
                    if len(picks) > 1 else f"Seed {last_c} chooses #{last_o}")
        return ", ".join(bits) + "."

    if results is not None and len(results):
        by_mid = {mid: g for mid, g in results.groupby("matchup_id")}
        for rd_num, rd in enumerate(cfg.get("rounds", []), start=1):
            try:
                weeks = [int(w) for w in rd.get("weeks", [])]
            except (TypeError, ValueError):
                weeks = _week_nums(",".join(str(w) for w in rd.get("weeks", [])))
            wk_lbl = ", ".join(str(w) for w in weeks) if weeks else ""
            games, byes = [], []
            for mu in rd.get("matchups", []):
                mid = mu.get("id")
                g = by_mid.get(mid)
                if mu.get("bye"):
                    team = None
                    if g is not None and len(g):
                        team = next((r["team"] for _, r in g.iterrows()
                                     if pd.notna(r["team"])), None)
                    pts = None
                    if team is not None and weeks:
                        vals = [ref.get((team, w)) for w in weeks]
                        vals = [v for v in vals if v is not None]
                        pts = round(sum(vals), 2) if vals else None
                    byes.append({"team": team, "points": pts, "pending": team is None,
                                 "season_rank": rank_by_team.get(team)})
                    continue
                if g is None or not len(g):
                    continue
                sides, pending = [], False
                for _, r in g.iterrows():
                    if not pd.notna(r["team"]):
                        continue
                    res = r["result"]
                    if res == "PENDING":
                        pending = True
                    sides.append({
                        "team": r["team"],
                        "points": float(r["points"]) if pd.notna(r["points"]) else None,
                        "result": res if res in ("W", "L", "T") else None,
                        "season_rank": rank_by_team.get(r["team"]),
                        "lineup": _lineup_from_players(players, s, mid, r["team"], ranks)})
                if not sides:
                    continue
                winner = next((x["team"] for x in sides if x["result"] == "W"), None)
                margin = _margin(sides)
                _sort_sides(sides)
                _stamp_slot_cmp(sides)
                games.append({
                    "id": mid,
                    "bracket": (g.iloc[0].get("bracket") if "bracket" in g else None),
                    "weeks": wk_lbl, "sides": sides, "winner": winner,
                    "margin": margin, "pending": pending})
            if games or byes:
                brs = {gm["bracket"] for gm in games if gm.get("bracket")}
                kind = brs.pop() if len(brs) == 1 else ("mixed" if brs else "title")
                is_final = final_id is not None and any(
                    gm["id"] == final_id for gm in games)
                base_name = rd.get("name") or rd.get("id") or f"Round {rd_num}"
                blurb_bits = [b for b in
                             (_pick_blurb(base_name, games), _bye_blurb(byes)) if b]
                groups.append({
                    "key": rd.get("id"),
                    "label": _round_title(rd_num, base_name, games, is_final),
                    "weeks": wk_lbl, "kind": kind, "games": games, "byes": byes,
                    "is_final": is_final,
                    "blurb": " ".join(blurb_bits) if blurb_bits else None})

    # Consolation bracket / outside-bracket games, split into one group PER WEEK so the
    # section reads with the same round-by-round shape as the bracket above it,
    # rather than one lump holding every week. Each week's group is a "round":
    # its label folds in the seeded matchups (`_matchup_label`, same as
    # `_round_title`), it carries that week's number in `weeks`, and it keeps
    # `kind == "consolation"` so the tag still renders.
    tb = consolation if consolation is not None else consolation_bracket(s, p)
    tgames = (tb or {}).get("games") or []
    if tgames:
        by_week: dict = {}
        for gm in tgames:
            wk = gm.get("week")
            sides = [{
                "team": sd.get("team"),
                "points": float(sd["points"]) if sd.get("points") is not None else None,
                "result": sd.get("result") if sd.get("result") in ("W", "L", "T") else None,
                "season_rank": sd.get("season_rank"),
                "lineup": sd.get("lineup") or [],
                "bench": sd.get("bench") or []} for sd in gm.get("sides", [])]
            winner = next((x["team"] for x in sides if x["result"] == "W"), None)
            margin = _margin(sides)
            _sort_sides(sides)
            by_week.setdefault(wk, []).append(
                {"id": None, "bracket": "consolation",
                 "weeks": str(wk) if wk is not None else "", "sides": sides,
                 "winner": winner, "margin": margin, "pending": False})
        ordered_weeks = sorted(by_week, key=lambda w: (w is None, w))
        n_weeks = len(ordered_weeks)
        # Last place goes to the loser of the LAST consolation bracket game, so that
        # callout rides on the final week's group only. The "games between the
        # teams that missed the bracket" framing sits on the first group.
        last_team = (tb or {}).get("last")
        for rd_i, wk in enumerate(ordered_weeks, start=1):
            wk_games = by_week[wk]
            wk_lbl = str(wk) if wk is not None else ""
            matchups = [m for m in (_matchup_label(g) for g in wk_games) if m]
            label = f"Consolation bracket, Round {rd_i}"
            if matchups:
                label += f" ({', '.join(matchups)})"
            blurb_bits = []
            if rd_i == 1:
                n_all = len(tgames)
                blurb_bits.append(
                    f"{n_all} game{'s' if n_all != 1 else ''} between the teams "
                    "that missed the championship bracket.")
            if rd_i == n_weeks:
                if last_team and (tb or {}).get("basis") == "game":
                    blurb_bits.append(f"{last_team} lost the final game and finishes last.")
                elif last_team:
                    blurb_bits.append(f"{last_team} finishes last.")
                else:
                    blurb_bits.append("Whoever loses the final game finishes last.")
            groups.append({
                "key": f"consolation-w{wk}", "label": label, "weeks": wk_lbl,
                "kind": "consolation", "games": wk_games, "byes": [],
                "is_final": rd_i == n_weeks,
                "blurb": " ".join(blurb_bits) if blurb_bits else None})

    return groups
