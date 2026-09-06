"""CBS Sports ADP provider.

CBS publishes its draft-averages table as server-rendered HTML (a
"TableBase" table on fantasy/football/draft/averages/), no auth, no league
id. It is ONE current-season ADP list: CBS ignores every scoring / season
query parameter, so there is no format split and no history -- like the
ESPN and Yahoo columns, the single published ADP stands in for whatever
mode the board asks for. EARLIEST is the current NFL season at import.

Rows carry a clean name + position + team but no CBS -> Sleeper id, so
ffadp.identity.resolve() keys them by normalised name + position.

Snapshot-first: fetch() reads season/adp/cbs/<year>.json and only pulls
the live page when that is missing or reload=True; degrades to [].
"""
from __future__ import annotations

import datetime
import re

from . import api, cache
from .base import AdpProvider, AdpRow

# No history from the endpoint; "earliest" is the current NFL season. (The
# NFL league year rolls in March; Jan-Feb still belongs to the prior draft.)
_now = datetime.date.today()
EARLIEST = _now.year if _now.month >= 3 else _now.year - 1

# CBS position label -> canonical. DST -> DEF; there are no IDP rows.
_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "PK": "K",
        "DST": "DEF", "DEF": "DEF"}

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_A = re.compile(r"<a[^>]*>(.*?)</a>", re.S)
_POS_CELL = re.compile(r'CellPlayerName-position">\s*(.*?)\s*<', re.S)
_TEAM_CELL = re.compile(r'CellPlayerName-team">\s*(.*?)\s*<', re.S)
_LONG = re.compile(r"CellPlayerName--long(.*)$", re.S)
_TAGS = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub("", s)).strip()


def _parse(html: str) -> list[dict]:
    """CBS draft-averages HTML -> compact rows (name/pos/team/adp), sorted by
    adp. The columns are: rank, player (name + pos + team), trend, ADP,
    high/low, percent drafted."""
    m = re.search(r"<tbody[^>]*>(.*?)</tbody>", html or "", re.S)
    if not m:
        return []
    out: list[dict] = []
    for tr in _ROW.findall(m.group(1)):
        tds = _TD.findall(tr)
        if len(tds) < 4:
            continue
        seg = _LONG.search(tds[1])
        cell = seg.group(1) if seg else tds[1]
        a = _A.search(cell)
        name = _text(a.group(1)) if a else ""
        if not name:
            continue
        pm = _POS_CELL.search(cell)
        pos = _POS.get((pm.group(1).strip().upper() if pm else ""), None)
        if pos is None:
            continue
        tm = _TEAM_CELL.search(cell)
        try:
            adp = float(_text(tds[3]))
        except (TypeError, ValueError):
            continue
        if adp <= 0:
            continue
        out.append({
            "name": name,
            "position": pos,
            "team": (tm.group(1).strip().upper() if tm else None) or None,
            "adp": round(adp, 1),
        })
    out.sort(key=lambda r: r["adp"])
    return out


class CbsAdp(AdpProvider):
    name = "cbs"
    label = "CBS"
    group = "apps"
    # One published ADP; stands in for whatever format the board asks for.
    formats = ("half_ppr", "ppr", "std", "2qb")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        season = str(season)
        try:
            if int(season) < EARLIEST:
                return []
        except (TypeError, ValueError):
            pass

        rows: list[dict] | None = None
        if not reload:
            rows = cache.load(self.name, season)
        if not rows:
            try:
                rows = _parse(api.cbs_adp())
                if rows:
                    cache.save(self.name, season, rows)
            except Exception:
                rows = None
        if not rows and reload:
            rows = cache.load(self.name, season)
        if not rows:
            return []

        out: list[AdpRow] = []
        for i, r in enumerate(rows, 1):
            out.append(AdpRow(
                source=self.name,
                name=r["name"],
                position=r.get("position"),
                team=r.get("team"),
                adp=float(r["adp"]) if r.get("adp") is not None else None,
                overall_rank=i,
            ))
        return out
