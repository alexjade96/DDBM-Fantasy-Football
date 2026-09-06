"""Yahoo ADP provider.

Yahoo's OAuth Fantasy API has a public read-only mirror at
pub-api-ro.fantasysports.yahoo.com that serves platform-wide, non-league
resources with NO auth -- including `players;out=draft_analysis`, which
carries a real average draft pick per player. So Yahoo is a first-party
source here, not a proxy column: rows are keyed by Yahoo player id
(identity.resolve maps that onto the canonical Sleeper id), and the value
is `preseason_average_pick` -- the pre-draft consensus, which stays fixed
for a past season (the live `average_pick` drifts all year).

History runs back to 2022: earlier NFL game keys resolve, but Yahoo only
kept the drifted end-of-season `average_pick` for those years, not the
pre-draft `preseason_average_pick` this provider wants (it comes back "-").
Yahoo publishes ONE ADP; like the ESPN column it stands in for whatever
scoring mode the board asks for. Snapshot-first: fetch() reads
season/adp/yahoo/<year>.json and only pages the live endpoint when that is
missing or reload=True; degrades to [] when both are unavailable.
"""
from __future__ import annotations

from . import api, cache
from .base import AdpProvider, AdpRow

EARLIEST = 2022

# Yahoo display_position -> the codebase's canonical set. A row can carry a
# multi-slot string ("DB,CB"); IDP / special-teams slots map to None (dropped).
_POS = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "K": "K", "PK": "K",
        "DEF": "DEF", "DST": "DEF", "D": "DEF"}

# Yahoo's "no draft data" sentinels for a pick value.
_BAD = {"", "-", None}


def _pick(da: dict):
    """A draft_analysis block -> the pre-draft average pick as a float, or
    None. Only `preseason_average_pick` is used: `average_pick` drifts all
    season and, for a past year, is a final-standings figure, not an ADP."""
    v = da.get("preseason_average_pick")
    if v in _BAD:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= 0 or f >= 999 else round(f, 1)


def _canon_pos(raw: str) -> str | None:
    for tok in (raw or "").upper().replace("/", ",").split(","):
        if tok.strip() in _POS:
            return _POS[tok.strip()]
    return None


def _trim(raw: list[dict]) -> list[dict]:
    """Raw flattened `player` dicts -> compact snapshot rows (id/name/pos/
    team/adp), IDP + no-pick rows dropped, sorted by adp."""
    out: list[dict] = []
    for p in raw or []:
        da = p.get("draft_analysis") or {}
        adp = _pick(da)
        if adp is None:
            continue
        pos = _canon_pos(p.get("display_position") or "")
        if pos is None:
            continue
        nm = (p.get("name") or {})
        name = nm.get("full") or f"{nm.get('first', '')} {nm.get('last', '')}".strip()
        if not name:
            continue
        out.append({
            "yahoo_id": str(p.get("player_id") or "") or None,
            "name": name,
            "position": pos,
            "team": (p.get("editorial_team_abbr") or "").upper() or None,
            "adp": adp,
        })
    out.sort(key=lambda r: r["adp"])
    return out


class YahooAdp(AdpProvider):
    name = "yahoo"
    label = "Yahoo"
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
                rows = _trim(api.yahoo_adp(season, scoring))
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
                name=r.get("name") or str(r.get("yahoo_id")),
                position=r.get("position"),
                team=r.get("team"),
                adp=float(r["adp"]) if r.get("adp") is not None else None,
                overall_rank=i,
                yahoo_id=str(r.get("yahoo_id")) if r.get("yahoo_id") else None,
            ))
        return out
