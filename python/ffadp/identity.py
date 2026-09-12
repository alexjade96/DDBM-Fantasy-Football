"""Cross-platform player identity.

Sleeper's player dump carries `espn_id` and `yahoo_id` for (almost) every
player, so mapping an ESPN or Yahoo ADP row onto the canonical Sleeper
`player_id` is a lookup, not a fuzzy match. Name + position is only the
fallback when a source row has no cross-id (rare) or the id is unknown to
Sleeper (a just-added rookie).

This reads the SAME on-disk dump `sleepermetrics.players()` caches
(`sleeperPlayerData_py.pkl`, refreshed at most daily) rather than adding a
second copy; it just keeps the id fields that `players()`'s DataFrame
projection drops.
"""
from __future__ import annotations

import datetime
import os
import pickle
import re

from sleepermetrics.api import sleeper_api

_PKL = "sleeperPlayerData_py.pkl"
_idx: dict | None = None


def _norm(name: str) -> str:
    """Loose name key: lowercased, punctuation and common suffixes stripped."""
    n = (name or "").lower().strip()
    n = re.sub(r"[.’']", "", n)
    n = re.sub(r"\s+(jr|sr|ii|iii|iv|v)$", "", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


# Team defenses arrive named a dozen ways across ADP sources -- "SF", "49ers",
# "San Francisco", "San Francisco Defense", "49ers D/ST", "Niners" -- and only
# Sleeper carries a cross-id, so every other source's DEF row was merging on
# its own name and the board showed ~95 rows for 32 teams. This maps any of
# those spellings to the abbreviation so all of a team's DEF rows collapse.
_DEF_ABBR = {
    "ari": "ARI", "arizona": "ARI", "cardinals": "ARI",
    "atl": "ATL", "atlanta": "ATL", "falcons": "ATL",
    "bal": "BAL", "baltimore": "BAL", "ravens": "BAL",
    "buf": "BUF", "buffalo": "BUF", "bills": "BUF",
    "car": "CAR", "carolina": "CAR", "panthers": "CAR",
    "chi": "CHI", "chicago": "CHI", "bears": "CHI",
    "cin": "CIN", "cincinnati": "CIN", "bengals": "CIN",
    "cle": "CLE", "cleveland": "CLE", "browns": "CLE",
    "dal": "DAL", "dallas": "DAL", "cowboys": "DAL",
    "den": "DEN", "denver": "DEN", "broncos": "DEN",
    "det": "DET", "detroit": "DET", "lions": "DET",
    "gb": "GB", "gnb": "GB", "green bay": "GB", "packers": "GB",
    "hou": "HOU", "houston": "HOU", "texans": "HOU",
    "ind": "IND", "indianapolis": "IND", "colts": "IND",
    "jax": "JAX", "jac": "JAX", "jacksonville": "JAX", "jaguars": "JAX",
    "kc": "KC", "kan": "KC", "kansas city": "KC", "chiefs": "KC",
    "lv": "LV", "lvr": "LV", "las vegas": "LV", "oakland": "LV",
    "raiders": "LV",
    "lac": "LAC", "los angeles chargers": "LAC", "san diego": "LAC",
    "chargers": "LAC",
    "lar": "LAR", "la": "LAR", "los angeles rams": "LAR",
    "st louis": "LAR", "rams": "LAR",
    "mia": "MIA", "miami": "MIA", "dolphins": "MIA",
    "min": "MIN", "minnesota": "MIN", "vikings": "MIN",
    "ne": "NE", "nwe": "NE", "new england": "NE", "patriots": "NE",
    "no": "NO", "nor": "NO", "new orleans": "NO", "saints": "NO",
    "nyg": "NYG", "ny giants": "NYG", "new york giants": "NYG",
    "giants": "NYG",
    "nyj": "NYJ", "ny jets": "NYJ", "new york jets": "NYJ", "jets": "NYJ",
    "phi": "PHI", "philadelphia": "PHI", "eagles": "PHI",
    "pit": "PIT", "pittsburgh": "PIT", "steelers": "PIT",
    "sf": "SF", "sfo": "SF", "san francisco": "SF", "49ers": "SF",
    "niners": "SF",
    "sea": "SEA", "seattle": "SEA", "seahawks": "SEA",
    "tb": "TB", "tam": "TB", "tampa bay": "TB", "buccaneers": "TB",
    "bucs": "TB",
    "ten": "TEN", "tennessee": "TEN", "titans": "TEN",
    "was": "WAS", "wsh": "WAS", "washington": "WAS",
    "commanders": "WAS", "football team": "WAS", "redskins": "WAS",
}


def def_team(name: str | None, team: str | None = None) -> str | None:
    """The NFL abbreviation for a team-defense row, from its `team` field or by
    stripping "defense" / "d/st" / "dst" off its name and looking up the rest.
    None if nothing matches."""
    if team and str(team).upper() in _DEF_ABBR.values():
        return str(team).upper()
    n = _norm(name or "")
    n = re.sub(r"\b(defense|def|dst|d st|special teams)\b", "", n).strip()
    n = re.sub(r"\s+", " ", n)
    if n in _DEF_ABBR:
        return _DEF_ABBR[n]
    # last word (nickname) often resolves even in "the new york jets defense"
    if n:
        last = n.split()[-1]
        if last in _DEF_ABBR:
            return _DEF_ABBR[last]
    return None


def _raw_players() -> dict:
    """The raw Sleeper player dump (dict keyed by sleeper id), from the shared
    daily cache file; fetched only if that file is missing or stale."""
    fresh = (
        os.path.exists(_PKL)
        and datetime.date.fromtimestamp(os.path.getmtime(_PKL)) == datetime.date.today()
    )
    if fresh:
        try:
            with open(_PKL, "rb") as fh:
                return pickle.load(fh)
        except Exception:
            pass
    raw = sleeper_api("/players/nfl")
    try:
        with open(_PKL, "wb") as fh:
            pickle.dump(raw, fh)
    except Exception:
        pass
    return raw


def _build() -> dict:
    raw = _raw_players()
    by_espn: dict[str, str] = {}
    by_yahoo: dict[str, str] = {}
    by_name: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for pid, p in raw.items():
        if not isinstance(p, dict):
            continue
        pos = p.get("position")
        name = pid if pos == "DEF" else (p.get("full_name") or "")
        team = pid if pos == "DEF" else p.get("team")
        meta[str(pid)] = {"name": name, "position": pos, "team": team}
        e, y = p.get("espn_id"), p.get("yahoo_id")
        if e:
            by_espn[str(e)] = str(pid)
        if y:
            by_yahoo[str(y)] = str(pid)
        if name:
            by_name.setdefault(f"{_norm(name)}|{(pos or '').upper()}", str(pid))
    return {"espn": by_espn, "yahoo": by_yahoo, "name": by_name, "meta": meta}


def _index() -> dict:
    global _idx
    if _idx is None:
        _idx = _build()
    return _idx


def resolve(source: str, *, espn_id=None, yahoo_id=None,
            name=None, position=None) -> str | None:
    """Best canonical Sleeper player_id for a source row, or None.

    Order: exact cross-id (espn/yahoo) first, then a normalised name+position
    match, then None (the board still merges such a row on its own name key).
    """
    ix = _index()
    if espn_id and str(espn_id) in ix["espn"]:
        return ix["espn"][str(espn_id)]
    if yahoo_id and str(yahoo_id) in ix["yahoo"]:
        return ix["yahoo"][str(yahoo_id)]
    if name:
        return ix["name"].get(f"{_norm(name)}|{(position or '').upper()}")
    return None


def meta(sleeper_id: str) -> dict:
    """{'name','position','team'} for a canonical id, or an empty dict."""
    return _index()["meta"].get(str(sleeper_id), {})


def reset() -> None:
    global _idx
    _idx = None
