"""Player portraits for the charts (mirrors R headshots.R).

Sleeper hosts a headshot per player id, and a logo per team -- a team defense has
no face, so it gets its team's logo instead.

Everything here is best-effort by design. Chart rendering must never depend on
the network being up, so a fetch that fails (offline, 403 for a player with no
photo, slow CDN) returns None and the caller falls back to a plain text label.
Failures are cached too: a chart with 20 players must not re-attempt 20 dead
downloads on every redraw.

Set SLEEPERMETRICS_NO_IMAGES=1 to turn portraits off entirely (tests do this, so
the suite stays network-free).
"""
from __future__ import annotations

import os
from pathlib import Path

PLAYER_CDN = "https://sleepercdn.com/content/nfl/players"
TEAM_CDN = "https://sleepercdn.com/images/team_logos/nfl"

# Cached to disk across runs: a headshot is ~100KB and never changes.
CACHE_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_CACHE", Path.home() / ".cache" / "sleepermetrics")) / "headshots"

_misses: set[str] = set()      # ids known to have no image -- don't retry them


def disabled() -> bool:
    return os.environ.get("SLEEPERMETRICS_NO_IMAGES", "") not in ("", "0")


def headshot_url(player_id: str, position: str | None = None) -> str:
    """Portrait url for a player, or the team logo for a team defense."""
    pid = str(player_id)
    if position == "DEF" or (pid.isalpha() and len(pid) <= 4):
        return f"{TEAM_CDN}/{pid.lower()}.png"
    return f"{PLAYER_CDN}/{pid}.jpg"


def headshot(player_id, position: str | None = None) -> str | None:
    """Local path to a player's portrait, downloading it once. None if there is none."""
    if player_id is None or disabled():
        return None
    pid = str(player_id)
    if pid in _misses:
        return None

    url = headshot_url(pid, position)
    dest = CACHE_DIR / f"{pid}{Path(url).suffix}"
    if dest.exists():
        return str(dest)

    try:
        import requests
        r = requests.get(url, timeout=6)
        # A player with no photo answers 403 with an HTML error page, not a 404,
        # so status alone is not enough -- insist on actually being handed an image.
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            _misses.add(pid)
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return str(dest)
    except Exception:
        _misses.add(pid)          # offline, timeout, whatever: degrade to text
        return None


def load(player_id, position: str | None = None, size: int = 96):
    """The portrait as an RGBA array ready for matplotlib, or None.

    Cropped to a square and rounded off, so a portrait sits in the chart as a
    circular token rather than a photo with a hard rectangular edge.
    """
    path = headshot(player_id, position)
    if path is None:
        return None
    try:
        import numpy as np
        from PIL import Image, ImageDraw
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        s = min(w, h)                                   # centre-crop to a square
        im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
        im = im.resize((size, size), Image.LANCZOS)
        circle = Image.new("L", (size, size), 0)
        ImageDraw.Draw(circle).ellipse((0, 0, size - 1, size - 1), fill=255)
        # A team logo is a PNG with its own transparency; intersect with the
        # circle rather than replace it, or the logo sits on a black square.
        own = im.getchannel("A")
        im.putalpha(Image.fromarray(
            (np.asarray(own).astype(int) * np.asarray(circle).astype(int) // 255
             ).astype("uint8")))
        return np.asarray(im) / 255.0
    except Exception:
        return None


def clear_cache(disk: bool = False) -> None:
    """Forget the misses (and optionally the downloaded files)."""
    _misses.clear()
    if disk and CACHE_DIR.exists():
        for f in CACHE_DIR.iterdir():
            f.unlink()
