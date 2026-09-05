"""Yahoo ADP provider -- STUB.

Yahoo's Fantasy API is OAuth2-only: there is no anonymous read path for
league or draft-analysis data, and this feature explicitly does NOT do auth.
A public Yahoo-specific ADP mirror has not been identified; the likely third
column is a public consensus source (FantasyPros-style) rather than Yahoo
itself. Left as a stub returning [] so the board simply omits the column.
"""
from __future__ import annotations

from .base import AdpProvider, AdpRow


EARLIEST = None   # no public no-auth history


class YahooAdp(AdpProvider):
    name = "yahoo"
    label = "Yahoo"
    formats = ("std", "half_ppr", "ppr")

    def fetch(self, season: str, scoring: str = "ppr",
              reload: bool = False) -> list[AdpRow]:
        return []
