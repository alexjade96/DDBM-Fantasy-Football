"""FantasyPros consensus-ADP provider -- STUB.

FantasyPros would be the ideal consensus column, but there is no no-auth
path to its ADP data:

  * The ADP pages (fantasypros.com/nfl/adp/ppr-overall.php etc.) do NOT
    contain the table in their HTML. The server-rendered markup holds only a
    ~5-row preview blob (integer ranks, no decimal ADP); the full table is
    fetched client-side from api.fantasypros.com, which returns 403 without
    an x-api-key. That key is issued only to "Hall of Fame" subscribers.
  * Getting the real numbers would need either the gated key (violates the
    feature's no-auth / no-secrets rule) or a headless browser to run the
    page JS (a dependency this feature avoids).

RotoWire's `average` / consensus column (ffadp.rotowire.RotowireAdp) is the
public substitute now wired in. If FantasyPros ever exposes a public feed,
implement fetch() here: trim to AdpRow (clean name+position for
identity.resolve), snapshot via ffadp.cache under season/adp/fantasypros/,
set EARLIEST.
"""
from __future__ import annotations

from .base import AdpProvider, AdpRow

EARLIEST = None   # set when wired


class FantasyProsAdp(AdpProvider):
    name = "fantasypros"
    label = "FantasyPros"
    # Consensus is published per scoring format; declare all so the board's
    # selector maps cleanly once real data is in.
    formats = ("std", "half_ppr", "ppr")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        return []
