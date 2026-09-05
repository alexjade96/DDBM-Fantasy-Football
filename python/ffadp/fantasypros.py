"""FantasyPros consensus-ADP provider -- STUB.

The intended third column: a public consensus ADP that aggregates ESPN /
Yahoo / Sleeper / CBS / NFL etc., which is more useful for draft prep than any
single platform and needs no auth. FantasyPros publishes redraft consensus
ADP per scoring format (STD / HALF / PPR) and per year.

Not wired yet -- returns [] so the board omits the column. To implement:
add the fetch (a small JSON/CSV pull), trim to the AdpRow shape (carry a
cross-id if the feed has one, else a clean name+position for
identity.resolve), snapshot via ffadp.cache under season/adp/fantasypros/,
and set EARLIEST to the oldest year the feed covers.
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
