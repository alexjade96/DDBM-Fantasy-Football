"""Fantasy Football Calculator ADP provider.

FFC runs public mock + real drafts and publishes the aggregate ADP through a
free REST API (see ffadp.api.ffc_adp). It is the one non-Sleeper source that
splits ADP by the SAME four scoring formats the board offers -- standard,
half-PPR, PPR and 2QB/superflex -- so unlike the ESPN column, the board's
scoring selector genuinely changes this one.

Each FFC row already carries a clean name / position / team, so no
cross-platform id is needed; ffadp.identity.resolve() keys it onto the
canonical Sleeper player_id by a normalised name+position match.

Snapshot-first, with a SEPARATE snapshot per scoring format under
season/adp/ffc/<format>/<year>.json (the four formats are genuinely different
data). A live pull happens only when that snapshot is missing or reload=True,
and it rewrites the snapshot. Degrades to [] when both are unavailable.

Historical depth: FFC has real data from 2010 on (2009 and earlier error).
"""
from __future__ import annotations

from . import api, cache
from .base import AdpProvider, AdpRow

EARLIEST = 2010

# FFC position labels are already QB/RB/WR/TE/PK/DEF; normalise the two that
# differ from the rest of the codebase.
_POS = {"PK": "K", "DST": "DEF", "D/ST": "DEF"}


def _trim(players: list) -> list[dict]:
    """Raw FFC player rows -> compact snapshot rows (name/pos/team/adp)."""
    out: list[dict] = []
    for p in players or []:
        try:
            adp = float(p.get("adp"))
        except (TypeError, ValueError):
            continue
        if adp <= 0:
            continue
        pos = (p.get("position") or "").upper()
        out.append({
            "name": p.get("name") or "",
            "position": _POS.get(pos, pos) or None,
            "team": p.get("team") or None,
            "adp": round(adp, 1),
        })
    out.sort(key=lambda r: r["adp"])
    return out


class FfcAdp(AdpProvider):
    name = "ffc"
    label = "FFCalc"
    # Compiled from FFC's own free mock/real drafts across the site, not a
    # first-party league app.
    group = "analyst"
    formats = ("std", "half_ppr", "ppr", "2qb")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        season = str(season)
        try:
            if int(season) < EARLIEST:
                return []
        except (TypeError, ValueError):
            pass

        fmt = self._format_or_fallback(scoring)
        rows: list[dict] | None = None
        if not reload:
            rows = cache.load(self.name, season, variant=fmt)
        if not rows:
            try:
                rows = _trim(api.ffc_adp(season, fmt))
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
            ))
        return out
