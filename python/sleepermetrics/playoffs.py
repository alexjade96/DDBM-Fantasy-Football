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


def sleeper_bracket(league_id, season=None) -> dict:
    """Rebuild Sleeper's own winners_bracket as an engine config.

    This is the "default Sleeper bracket" a user rolls back to. Note Sleeper's
    stored bracket can be incoherent (DDBM 2025) or, mid-season, incomplete --
    the config is faithful to whatever Sleeper holds, warts and all.
    """
    key = f"sleeper:{league_id}:{season}"
    if key in _gen_cache:
        return copy.deepcopy(_gen_cache[key])
    link, lid, lg, name_of = _bracket_context(league_id, season)
    wb = sleeper_api(f"/league/{lid}/winners_bracket") or []
    start = int((lg.get("settings") or {}).get("playoff_week_start") or 0)
    cfg = _bracket_base(link, lid, lg, f"{lg['name']} {link['season']} (Sleeper bracket)")
    for r in sorted({m["r"] for m in wb}):
        wk = start + r - 1
        starters = _week_starters(lid, wk) if start else {}
        mus = []
        for m in sorted((x for x in wb if x["r"] == r), key=lambda x: x["m"]):
            home, away = _sleeper_side(m.get("t1"), name_of), _sleeper_side(m.get("t2"), name_of)
            if home is None or away is None:
                continue
            mus.append({
                "id": f"M{m['m']}",
                "home": {"team": home,
                         "starters": starters.get(m.get("t1"), []) if isinstance(m.get("t1"), int) else []},
                "away": {"team": away,
                         "starters": starters.get(m.get("t2"), []) if isinstance(m.get("t2"), int) else []},
                "_sleeper_winner": name_of.get(m["w"]) if m.get("w") else None})
        cfg["rounds"].append({"id": f"R{r}", "name": f"Round {r}",
                              "weeks": [wk], "matchups": mus})
    title = next((m for m in wb if m.get("p") == 1), None)
    if title:
        cfg["final"] = f"M{title['m']}"
    _gen_cache[key] = copy.deepcopy(cfg)
    return cfg


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

    Sleeper's winners_bracket stores 3rd-place and placement games alongside the
    real thing, so counting every game as a "playoff win" inflates records. A
    game is on the title path only if BOTH teams are still alive going into it;
    once you lose a title-path game you are out, and anything you play afterwards
    is consolation. Rounds are walked in order and eliminations applied at the
    END of a round, so games within a round cannot affect each other.
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
            results.loc[i, "bracket"] = "title" if title else "consolation"
            if title:
                fresh |= set(results.loc[i & (results["result"] == "L"), "team"])
        elim |= fresh
    return results


def scope_frame(d: pd.DataFrame, scope: str = "title") -> pd.DataFrame:
    """Keep the title path (default), the consolation games, or everything."""
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


def playoff_performances(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Every started player-week across all brackets (the player-metric grain)."""
    frames = []
    for s, p in playoffs.items():
        if not len(p.players):
            continue
        d = p.players.merge(p.results[["matchup_id", "round"]].drop_duplicates(),
                            on="matchup_id", how="left")
        d = d.assign(season=str(s), champion=d["team"] == (p.champion or ""))
        frames.append(d)
    if not frames:
        return pd.DataFrame()
    d = scope_frame(pd.concat(frames, ignore_index=True), scope)
    # player_id rides along: it is the only safe key for a portrait (names are
    # neither unique nor stable).
    cols = ["season", "round", "bracket", "matchup_id", "team", "player_id",
            "player_name", "position", "week", "points", "champion"]
    return d[cols].sort_values("points", ascending=False).reset_index(drop=True)


def playoff_players(playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Career playoff scoring leaders -- who actually produces in January."""
    d = playoff_performances(playoffs, scope)
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


def clutch(seasons: dict, playoffs: dict, scope: str = "title") -> pd.DataFrame:
    """Playoff PPG vs regular-season PPG -- who raises their game."""
    frames = [scope_frame(p.results, scope).assign(season=str(s))
              for s, p in playoffs.items()]
    if not frames:
        return pd.DataFrame()
    po = pd.concat(frames, ignore_index=True)
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
        return "Still alive" if not p.champion else "—"

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

    The toilet bowl is a plain Sleeper matchup, so its lineups live in `pl_wk`,
    not in the bracket engine's `players`. Ordering goes through `assign_slots`
    so the drill reads QB, RB1, RB2, WR1, WR2, TE, FLEX, K, DEF like every other
    roster table, rather than in whatever order the frame happens to hold.

    `ranks` is optional, same shape/purpose as `_lineup_from_players`' own --
    stamped onto each row as `pos_rank` so the toilet bowl's own matchup
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
    concept exists), the toilet bowl is a plain Sleeper matchup with real
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


def toilet_bowl(s, p=None) -> dict:
    """The race at the bottom -- who finished last, and the game that decided it.

    The toilet bowl is the teams that **missed the championship bracket** and the
    games they played once the postseason started -- ordinary Sleeper matchups
    that never appear in the bracket config, so reading the config alone reports
    no toilet bowl at all (2025: sparky1335 beat rezzu in wk15).

    The config's **consolation games are deliberately NOT counted here.** In this
    league they are placement games between teams already in the bracket -- a
    3rd-place game, not a race for the basement -- so the loser of the last one
    is frequently a strong team: in 2022 it was diogenesthecat, who finished
    *first* in the regular season. Reporting that as last place is simply wrong.
    Those games remain visible, correctly labelled, in the bracket walk.

    Last place goes to the **loser** of the final toilet-bowl game. With no game
    to decide it, the worst regular-season finish stands in -- and that fallback
    is labelled as such rather than presented as a result. A season where every
    team reached the bracket has no toilet bowl, and says so.

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
    # Postseason weeks: the toilet bowl lives outside the regular season.
    tw = getattr(s, "team_wk_all", None)
    in_bracket, po_start, games = set(), None, []
    # `season_rank` -- a MANAGER's own final regular-season standing, shown
    # next to their name in the toilet bowl's own matchup rows, same as the
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
    # matchups in team_wk, which is the only place a 2025-shaped toilet bowl lives.
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
    last, basis = None, None
    decided = [g for g in games if g["loser"]]
    if decided:
        last, basis = max(decided, key=wk_of)["loser"], "game"
    elif missed and st is not None and "final_position" in st:
        pool = st[st["user_name"].isin(missed)]
        if len(pool):
            last, basis = pool.sort_values("final_position").iloc[-1]["user_name"], "standings"

    # Each missed team's OWN postseason record -- rate stats from the toilet-bowl
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
                          # None (not 0) when the team never had a toilet game --
                          # keeps every po_* field blank together in the combined
                          # board rather than a stray "0" beside a "—".
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
    return {"games": games, "teams": teams, "last": last, "basis": basis,
            "missed": missed}



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
    games, byes, toilet-bowl games and teams simply not playing, all at once,
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
                role, note = "bye", "bye — advanced without playing"
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
    whether it's a real bracket game, the toilet bowl, or the redraft sim.

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


def game_log(s, p, toilet=None) -> list[dict]:
    """The whole postseason as ONE game log: bracket games grouped by round, each
    expandable to both submitted lineups, with byes and the toilet bowl folded in.

    This is the single scoreboard->lineups drilldown the Playoffs tab reads from --
    the same idiom the Weekly tab and toilet bowl already use -- replacing the old
    trio (the bracket walk, the per-matchup chart, and a separate week table) that
    each re-drew the same games. The bracket graphic stays as the visual map; this
    is the readable log beneath it.

    Returns a list of round groups in bracket order:
      {key, label, weeks, kind, games:[{id, bracket, weeks, sides, winner, margin,
       pending}], byes:[{team, points, pending}]}
    where each side is {team, points, result, season_rank, lineup:[{slot,
    player_id, player_name, position, points, pos_rank, cmp}]}. `pos_rank`
    is each starter's FINAL season-long position finish (best-effort -- a
    season this Season stand-in can't fully price degrades to no ranks
    rather than failing the whole log, same "never blocks rendering"
    contract as the headshot/avatar lookups elsewhere in this app). `cmp`
    ('up'/'down'/'even') is that slot's own win/loss against the OTHER
    side's same slot (see `_stamp_slot_cmp`); a bracket game's lineup has
    no `bench` (the commissioner's config only ever records starters), but
    a toilet-bowl game's does (real `pl_wk` roster data). The toilet-bowl /
    outside-bracket games are appended as a final `kind == "toilet"` group
    so a league whose playoff runs outside Sleeper is bracketed here too,
    not stranded in a
    separate section.
    """
    import pandas as pd

    groups: list[dict] = []
    cfg = p.config if isinstance(getattr(p, "config", None), dict) else {}
    results = getattr(p, "results", None)
    players = getattr(p, "players", None)
    ref = reference_scores(s)
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

    if results is not None and len(results):
        by_mid = {mid: g for mid, g in results.groupby("matchup_id")}
        for rd in cfg.get("rounds", []):
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
                groups.append({
                    "key": rd.get("id"), "label": rd.get("name") or rd.get("id"),
                    "weeks": wk_lbl, "kind": kind, "games": games, "byes": byes})

    # Toilet bowl / outside-bracket games as their own trailing group.
    tb = toilet if toilet is not None else toilet_bowl(s, p)
    tgames = (tb or {}).get("games") or []
    if tgames:
        out_games, wks = [], set()
        for gm in tgames:
            wks.add(gm.get("week"))
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
            out_games.append({"id": None, "bracket": "toilet",
                              "weeks": str(gm.get("week")), "sides": sides,
                              "winner": winner, "margin": margin, "pending": False})
        wlbl = ", ".join(str(w) for w in sorted(x for x in wks if x is not None))
        groups.append({"key": "toilet", "label": "Toilet bowl", "weeks": wlbl,
                       "kind": "toilet", "games": out_games, "byes": []})

    return groups
