"""Yahoo ADP provider.

Yahoo's own Fantasy API is OAuth2-only: there is no anonymous read path for
draft-analysis data, and this feature does no auth. Yahoo's redraft ADP is
still available publicly THROUGH RotoWire's comparison feed (the `yahooppr`
column), so the provider lives in ffadp.rotowire alongside the other columns
that feed shares; this module just re-exports it so the registry / imports
read naturally.

Current season only (RotoWire's feed has no history). Yahoo publishes a
single ADP; like the ESPN column it stands in for whichever scoring mode
the board asks for.
"""
from __future__ import annotations

from .rotowire import EARLIEST, YahooAdp

__all__ = ["YahooAdp", "EARLIEST"]
