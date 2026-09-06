"""MyFantasyLeague ADP provider.

MFL's developer API exposes a season-wide aggregate ADP report with no auth
(see ffadp.api.mfl_adp). It is drawn from thousands of MFL drafts each year
and goes back well over a decade. Two limitations shape this provider:

  * The report keys players by MFL id only, so ffadp.api.mfl_players() is
    fetched once per season for the id -> name/position/team map. MFL names
    come back "Last, First" and are flipped here to "First Last" before
    ffadp.identity.resolve() keys them onto the canonical Sleeper player_id.
  * MFL only distinguishes PPR from non-PPR (IS_PPR=1/0). `formats` lists
    "ppr" and "std"; a half_ppr / 2qb ask falls back to the PPR report.

Snapshot-first under season/adp/mfl/<year>.json (PPR by default; a non-PPR
ask fetches live and caches under the "std" variant). Degrades to [] when
neither the snapshot nor the network is available.
"""
from __future__ import annotations

from . import api, cache
from .base import AdpProvider, AdpRow

EARLIEST = 2010

_POS = {"PK": "K", "DEF": "DEF", "TMWR": None, "TMQB": None, "TMRB": None,
        "TMTE": None, "TMPK": None, "Off": None, "ST": None, "TMDL": None,
        "CB": None, "S": None, "LB": None, "DE": None, "DT": None}


def _flip_name(n: str) -> str:
    """"McCaffrey, Christian" -> "Christian McCaffrey"; a team-defense name
    ("Bills, Buffalo") is left alone (identity keys DEF by team anyway)."""
    if "," not in n:
        return n
    last, first = (s.strip() for s in n.split(",", 1))
    return f"{first} {last}".strip()


def _rows(adp_rows: list, players: dict) -> list[dict]:
    """MFL id-keyed ADP rows + the id->meta map -> compact snapshot rows."""
    out: list[dict] = []
    for r in adp_rows or []:
        pid = str(r.get("id") or "")
        try:
            adp = float(r.get("averagePick"))
        except (TypeError, ValueError):
            continue
        if adp <= 0:
            continue
        meta = players.get(pid) or {}
        pos = (meta.get("position") or "").upper()
        if pos in _POS and _POS[pos] is None:
            continue
        out.append({
            "mfl_id": pid,
            "name": _flip_name(meta.get("name") or ""),
            "position": _POS.get(pos, pos) or None,
            "team": meta.get("team") or None,
            "adp": round(adp, 1),
        })
    out.sort(key=lambda r: r["adp"])
    return out


class MflAdp(AdpProvider):
    name = "mfl"
    label = "MFL"
    # A draft platform, but the published ADP is a cross-league aggregate and
    # MFL skews high-stakes / industry.
    group = "highstakes"
    formats = ("ppr", "std")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        season = str(season)
        try:
            if int(season) < EARLIEST:
                return []
        except (TypeError, ValueError):
            pass

        fmt = self._format_or_fallback(scoring)   # "ppr" or "std"
        is_ppr = 0 if fmt == "std" else 1
        rows: list[dict] | None = None
        if not reload:
            rows = cache.load(self.name, season, variant=fmt)
        if not rows:
            try:
                players = api.mfl_players(season)
                rows = _rows(api.mfl_adp(season, is_ppr=is_ppr), players)
                if rows:
                    cache.save(self.name, season, rows, variant=fmt)
            except Exception:
                rows = None
        if not rows and reload:
            rows = cache.load(self.name, season, variant=fmt)
        if not rows:
            return []

        out: list[AdpRow] = []
        for i, r in enumerate(rows, 1):
            out.append(AdpRow(
                source=self.name,
                name=r.get("name") or "",
                position=r.get("position"),
                team=r.get("team"),
                adp=float(r["adp"]) if r.get("adp") is not None else None,
                overall_rank=i,
                extra={"mfl_id": r.get("mfl_id")},
            ))
        return out
