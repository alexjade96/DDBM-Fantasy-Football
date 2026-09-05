"""Cross-platform pre-season ADP (average draft position).

A webapp-only data layer, deliberately OUTSIDE the parity-gated
`sleepermetrics` package: it has no `Season` context and no R counterpart. It
pulls each platform's PUBLIC, platform-wide ADP for a season (the same kind of
data `sleepermetrics.draft` already reads from Sleeper's undocumented ADP
endpoint), keys every source's players onto one canonical id via the Sleeper
player dump's `espn_id` / `yahoo_id` cross-reference fields, and combines them
into one comparison board.

No auth, no cookies, no OAuth, no per-user data -- every source here is
season-wide published draft data. Snapshots are written under
`season/adp/<source>/<year>.json` (same durable-fallback pattern as
`season/adp/<year>.json`) so the board still renders offline / on a cold host.

Public entry point: `combine(season, sources=None, scoring="half_ppr", pos="ALL")`.
"""
from .board import combine
from .base import AdpProvider, AdpRow

__all__ = ["combine", "AdpProvider", "AdpRow"]
