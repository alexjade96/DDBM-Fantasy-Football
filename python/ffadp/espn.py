"""ESPN ADP provider.

Pulls ESPN's public, platform-wide pre-season ADP from the kona_player_info
players view (see ffadp.api.espn_players). No league id, no cookies. The value
is `ownership.averageDraftPosition` -- ESPN's standard public-game REDRAFT ADP
(10/12-team leagues). ESPN publishes ONE such number: it is NOT split by
scoring format the way Sleeper's four variants are, and there is no
TE-premium and no dynasty ADP in this view. The board's scoring selector
therefore does not change the ESPN column.

Snapshot-first: fetch() reads season/adp/espn/<year>.json (trimmed to
id/name/pos/adp) and only pulls the ~20 MB live payload when that snapshot is
missing or `reload=True`. Degrades to [] when both are unavailable -- the
board just drops the ESPN column.

Historical depth: ESPN returns real ADP for ~2015..present, with gaps some
years (e.g. 2019, 2025 come back all-sentinel).
"""
from __future__ import annotations

from . import api, cache
from .base import AdpProvider, AdpRow

# ESPN defaultPositionId -> fantasy position. 6-8 / 9-15 are IDP / team slots
# we don't surface.
_POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

# Undrafted players all cluster at ESPN's "just past the last pick" default
# (~170 for a 10-team, 17-round board). Anything at/above this with no
# ownership is depth noise, not a draft position.
_SENTINEL = 168.0

EARLIEST = 2004


def _trim(raw: list) -> list[dict]:
    """Raw ESPN player objects -> compact snapshot rows."""
    out: list[dict] = []
    for p in raw:
        own = p.get("ownership") or {}
        try:
            adp = float(own.get("averageDraftPosition"))
        except (TypeError, ValueError):
            continue
        if not adp or adp <= 0 or adp >= _SENTINEL:
            continue
        if not (own.get("percentOwned") or 0) > 0:
            continue
        out.append({
            "espn_id": str(p.get("id")),
            "name": p.get("fullName") or "",
            "position": _POS.get(p.get("defaultPositionId")),
            "adp": round(adp, 1),
        })
    out.sort(key=lambda r: r["adp"])
    return out


class EspnAdp(AdpProvider):
    name = "espn"
    label = "ESPN"
    group = "apps"
    # One published ADP; it stands in for whatever format the board asks for.
    formats = ("half_ppr", "ppr", "std", "2qb")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        season = str(season)
        rows: list[dict] | None = None
        # Snapshot first, unless a reload is asked for.
        if not reload:
            rows = cache.load(self.name, season)
        if not rows:
            try:
                rows = _trim(api.espn_players(season))
                if rows:
                    cache.save(self.name, season, rows)
            except Exception:
                rows = None
        if not rows and reload:
            # A failed reload still falls back to whatever is stored.
            rows = cache.load(self.name, season)
        if not rows:
            return []
        out: list[AdpRow] = []
        for i, r in enumerate(rows, 1):
            out.append(AdpRow(
                source=self.name,
                name=r.get("name") or str(r.get("espn_id")),
                position=r.get("position"),
                adp=float(r["adp"]) if r.get("adp") is not None else None,
                overall_rank=i,
                espn_id=str(r.get("espn_id")) if r.get("espn_id") else None,
            ))
        return out
