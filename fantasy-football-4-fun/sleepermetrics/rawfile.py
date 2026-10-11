"""Store a downloaded response exactly as received, gzip-compressed.

One tiny helper shared by the raw layers (see docs/data-loading-refactor-plan.md):
the bytes go to disk before anything parses or trims them, so a change to what
is derived later needs no download.  gzip is lossless; the stored file
decompresses to the same bytes that arrived.
"""
from __future__ import annotations

import gzip
import os
from pathlib import Path


def save_gz(path: Path, content: bytes) -> bool:
    """Write `content` gzip-compressed, atomically.  Best-effort: returns False
    (never raises) when the disk is read-only or full."""
    if not content:
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(gzip.compress(content, compresslevel=6))
        os.replace(tmp, path)
        return True
    except Exception:
        return False


def load_gz(path: Path) -> bytes | None:
    """The original bytes, or None when absent or unreadable."""
    try:
        return gzip.decompress(path.read_bytes())
    except Exception:
        return None
