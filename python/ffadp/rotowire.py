"""RotoWire ADP providers.

RotoWire publishes a single public JSON table (ffadp.api.rotowire_adp) that
lines up several sites' current-season ADP side by side plus RotoWire's own
`average` consensus. This module surfaces two columns from it:

  * RotowireAdp -- RotoWire's `average` blended consensus ("analyst" group).
  * YahooAdp    -- the feed's `yahooppr` column, the only public no-auth path
                   to a Yahoo redraft ADP ("apps" group).

One fetch, shared: `_feed(season, scoring, reload)` pulls + trims the table
once, memoised per season+slug and snapshotted to
season/adp/rotowire/<slug>/<year>.json; each provider slices its own column
out of that shared parse.

CURRENT SEASON ONLY. The endpoint ignores a year parameter -- it always
returns the live draft-season board -- so EARLIEST is the current NFL
season at import time and older years simply have no RotoWire data.

Names are matched by ffadp.identity.resolve() on a normalised
first+last / position (RotoWire's player id has no Sleeper cross-ref).
"""
from __future__ import annotations

import datetime

from . import api, cache
from .base import AdpProvider, AdpRow

# The feed has no history; treat "earliest" as the current NFL season. (The
# NFL league year rolls in March, so anything Jan-Feb still belongs to the
# previous season's draft board.)
_now = datetime.date.today()
EARLIEST = _now.year if _now.month >= 3 else _now.year - 1

# RotoWire position labels -> the codebase's canonical set; IDP / O-line
# rows are dropped (None).
_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K",
        "PK": "K", "DST": "DEF", "DEF": "DEF",
        "CB": None, "DB": None, "S": None, "LB": None, "DE": None,
        "DT": None, "DL": None, "C": None, "OG": None, "OT": None,
        "FB": None, "P": None}

# Sentinels RotoWire uses for "this site has no ADP for this player".
_BAD = {"", "-", None}


def _val(v):
    """A RotoWire cell -> float ADP, or None for a sentinel / 999 filler."""
    if v in _BAD:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= 0 or f >= 999 else round(f, 1)


# Board scoring key -> RotoWire slug. Only PPR / Standard exist; half_ppr and
# 2qb fall back to PPR.
_SLUG = {"std": "Standard", "half_ppr": "PPR", "ppr": "PPR", "2qb": "PPR"}

# The feed columns this module surfaces, per RotoWire scoring slug.
# {board source name: {"PPR": <col>, "Standard": <col>}}.
_COLUMN = {
    # RotoWire recomputes its own consensus per scoring mode.
    "rotowire": {"PPR": "average",  "Standard": "average"},
    # Yahoo publishes one ADP; like the ESPN column it stands in for
    # whichever mode the board asks for.
    "yahoo":    {"PPR": "yahooppr", "Standard": "yahooppr"},
}

# feed cache: f"{season}:{slug}" -> list[dict] (trimmed rows)
_feed_mem: dict[str, list] = {}


def _trim(raw: list) -> list[dict]:
    """Raw RotoWire rows -> compact rows: name/pos/team + the columns we use."""
    wanted = {c for m in _COLUMN.values() for c in m.values() if c}
    out: list[dict] = []
    for r in raw or []:
        pos = _POS.get((r.get("position") or "").upper(), None)
        if pos is None:
            continue
        name = f"{(r.get('firstname') or '').strip()} {(r.get('lastname') or '').strip()}".strip()
        if not name:
            continue
        row = {"name": name, "position": pos, "team": r.get("team") or None,
               "rotowire_id": str(r.get("playerID") or "") or None}
        keep = False
        for c in wanted:
            v = _val(r.get(c))
            row[c] = v
            keep = keep or v is not None
        if keep:
            out.append(row)
    return out


def _feed(season: str, scoring: str, reload: bool) -> list[dict]:
    """The trimmed RotoWire table for a season+scoring, snapshot-first.

    Memoised for the process; on a miss it reads
    season/adp/rotowire/<slug>/<year>.json and only calls the live endpoint
    when that is absent or `reload`. It is keyed on the "rotowire" source
    name + the RotoWire scoring slug -- NEVER on a derived column's own name
    -- so the Yahoo column is a pure view over the one upstream snapshot and
    there is no season/adp/yahoo/ datastream that could later collide with a
    real first-party Yahoo provider.
    """
    slug = _SLUG.get(scoring, "PPR")
    key = f"{season}:{slug}"
    if not reload and key in _feed_mem:
        return _feed_mem[key]

    rows = None if reload else cache.load("rotowire", season, variant=slug)
    if not rows:
        try:
            rows = _trim(api.rotowire_adp(slug))
            if rows:
                cache.save("rotowire", season, rows, variant=slug)
        except Exception:
            rows = None
    if not rows and reload:
        rows = cache.load("rotowire", season, variant=slug)
    rows = rows or []
    _feed_mem[key] = rows
    return rows


def _clear_feed_cache() -> None:
    _feed_mem.clear()


class _RotowireColumn(AdpProvider):
    """Base for a provider that is one column of the shared RotoWire feed."""
    #: key into _COLUMN
    col_key: str = ""
    formats = ("ppr", "std")
    #: board.py reads this (one module backs several source names, so a
    #: per-class attr is used instead of a module-level EARLIEST lookup).
    EARLIEST = EARLIEST

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        season = str(season)
        try:
            if int(season) < EARLIEST:
                return []
        except (TypeError, ValueError):
            pass

        slug = _SLUG.get(self._format_or_fallback(scoring), "PPR")
        col = _COLUMN[self.col_key].get(slug)
        if not col:
            return []
        rows = _feed(season, scoring, reload)

        picked = []
        for r in rows:
            v = r.get(col)
            if v is None:
                continue
            picked.append(AdpRow(
                source=self.name,
                name=r["name"],
                position=r["position"],
                team=r.get("team"),
                adp=float(v),
                extra={"rotowire_id": r.get("rotowire_id")},
            ))
        picked.sort(key=lambda x: x.adp)
        for i, x in enumerate(picked, 1):
            x.overall_rank = i
        return picked


class RotowireAdp(_RotowireColumn):
    name, label, col_key = "rotowire", "RotoWire", "rotowire"
    group = "analyst"          # RotoWire's own compiled consensus


class YahooAdp(_RotowireColumn):
    """Yahoo redraft ADP, sourced from RotoWire's `yahooppr` column (Yahoo's
    own API is OAuth-only with no anonymous read path). Yahoo publishes one
    ADP; like the ESPN column it stands in for whatever scoring mode the
    board asks for."""
    name, label, col_key = "yahoo", "Yahoo", "yahoo"
    group = "apps"             # a mainstream draft app
