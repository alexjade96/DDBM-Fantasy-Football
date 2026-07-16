"""Player portraits and manager avatars for the charts (mirrors R headshots.R).

Sleeper hosts a headshot per player id, and a logo per team -- a team defense has
no face, so it gets its team's logo instead. Managers/teams have an account
avatar url (from the accounts frame), fetched the same way.

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


def _fetch(url: str, key: str) -> str | None:
    """Download `url` to the cache once, keyed by `key`. None on any failure."""
    if not url or disabled() or key in _misses:
        return None
    dest = CACHE_DIR / f"{key}{Path(url).suffix or '.png'}"
    if dest.exists():
        return str(dest)
    try:
        import requests
        r = requests.get(url, timeout=6)
        # A missing image answers 403 with an HTML error page, not a 404, so
        # status alone is not enough -- insist on actually being handed an image.
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("image/"):
            _misses.add(key)
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(r.content)
        return str(dest)
    except Exception:
        _misses.add(key)          # offline, timeout, whatever: degrade to text
        return None


def _circle(path: str | None, size: int):
    """A cached image file as a centre-cropped, circular RGBA array (or None).

    Rounding it off lets a portrait/avatar sit in a chart as a circular token
    rather than a photo with a hard rectangular edge.
    """
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


def headshot(player_id, position: str | None = None) -> str | None:
    """Local path to a player's portrait, downloading it once. None if there is none."""
    if player_id is None:
        return None
    pid = str(player_id)
    return _fetch(headshot_url(pid, position), pid)


def load(player_id, position: str | None = None, size: int = 96):
    """A player's portrait as a circular RGBA array ready for matplotlib, or None."""
    return _circle(headshot(player_id, position), size)


def avatar_thumb(url: str) -> str:
    """The small thumbnail form of a Sleeper avatar url.

    A full `/avatars/<id>` is served as application/octet-stream (~400KB) which
    the image-type guard rejects; the `/avatars/thumbs/<id>` form is a ~15KB
    image/png -- smaller and correctly typed, exactly what a chart token wants.
    Non-Sleeper (custom team) urls pass through unchanged.
    """
    u = str(url)
    if "sleepercdn.com/avatars/" in u and "/thumbs/" not in u:
        return u.replace("/avatars/", "/avatars/thumbs/")
    return u


def avatar_image(url, size: int = 96):
    """A manager/team account avatar (by url) as a circular RGBA array, or None.

    Keyed by a hash of the url since avatars have no stable id; same best-effort,
    same disk cache and miss-cache as player portraits.
    """
    if not url or (isinstance(url, float) and url != url):     # None / NaN
        return None
    u = avatar_thumb(url)
    # Key the cache on the avatar id (the url basename) -- unique and stable, and
    # matches the R side so both instances share one downloaded set.
    key = "av_" + os.path.basename(u.split("?")[0])
    return _circle(_fetch(u, key), size)


def clear_cache(disk: bool = False) -> None:
    """Forget the misses (and optionally the downloaded files)."""
    _misses.clear()
    if disk and CACHE_DIR.exists():
        for f in CACHE_DIR.iterdir():
            f.unlink()
