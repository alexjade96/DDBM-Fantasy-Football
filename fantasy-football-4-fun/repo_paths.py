"""Single source of truth for this instance's repo-relative paths.

sleepermetrics/ and webapp/ (plus webapp/sources/{ffadp,nflref}, nested under
webapp/ since they're webapp-only data integrations) all need to find
`data/seasons/` and `data/sources/` at the repo root, and each used to
compute that independently via `Path(__file__).resolve().parents[2]`. That
meant a repo restructure (or even just moving one of those packages a
directory deeper/shallower) required finding and fixing every occurrence by
hand -- which is exactly the kind of change that breaks silently if one copy
is missed. This module computes it once; everything else imports SEASON_DIR/
SOURCES_DIR from here.

This file lives directly under fantasy-football-4-fun/ (the Python instance
dir, a sibling of sleepermetrics/ and the webapp/ FastAPI package), not inside
any one of them, so no package has to depend on another package's internals
just to find the repo root. `data/seasons/` and `data/sources/` are SIBLINGS
of fantasy-football-4-fun/ at the repo root, one level up from this file.

**Two separate directories, deliberately not one.** `data/seasons/` holds
only league-scoped playoff bracket configs (`<root_league_id>/<season>_
season.json`, plus any reference file for that same league, e.g. a Sleeper-
bracket replay fixture) -- genuinely organized by season, one league at a
time. `data/sources/` holds everything else that used to live alongside it
(`adp/`, `stats/`, `nflverse/`, `scoring/`): caches and reference data keyed
by SOURCE first (which ADP provider, which nflverse dataset) with season only
as the leaf underneath, shared across every league rather than scoped to one.
Nesting the latter inside something named "seasons" read as though it were
organized by season, when it wasn't -- see data/seasons/README.md and
data/sources/README.md.

The Dockerfile is a SEPARATE case, not the same computation at a different
depth: its COPY steps flatten everything into /app/ (repo_paths.py,
sleepermetrics/, webapp/ -- which still carries its own sources/ subtree --
all become direct siblings there), while data/seasons/ and data/sources/ are
copied to /app/data/seasons and /app/data/sources -- a genuinely different
relative shape than the real repo's, not just a shifted depth. Rather than
try to make one formula cover both, the Dockerfile sidesteps this entirely by
setting SLEEPERMETRICS_SEASON_DIR/SLEEPERMETRICS_SOURCES_DIR explicitly, so
the fallback below never actually runs in that environment -- it only needs
to be correct for the real repo layout.
"""
from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path

# fantasy-football-4-fun/repo_paths.py -> parent = fantasy-football-4-fun/ -> parent.parent = repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR", str(REPO_ROOT / "data" / "seasons")))

SOURCES_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SOURCES_DIR", str(REPO_ROOT / "data" / "sources")))


def on_render() -> bool:
    """True only on a Render host (Render sets `RENDER=true`). Memory-saving
    behaviour that exists for Render's 512MB instances is gated on this, so a
    dev/test server behaves exactly as before."""
    return os.environ.get("RENDER", "").lower() == "true"


_heavy_build_lock = threading.Lock()


def heavy_build_guard():
    """Context manager for a memory-heavy cold build (a player/team profile).
    On Render it serialises them, since each holds ~190MB while building and two
    at once exceed the 512MB instance; elsewhere it does nothing."""
    return _heavy_build_lock if on_render() else contextlib.nullcontext()


def prune_cache(cache: dict, ttl: float, max_entries: int = 4) -> None:
    """Render only: drop expired `{"at": ts}` entries and keep at most
    `max_entries` of the newest, so a long-running instance does not accumulate
    one profile per visited player/team."""
    if not on_render():
        return
    now = time.time()
    for k in [k for k, v in cache.items() if now - v["at"] >= ttl]:
        cache.pop(k, None)
    for k in sorted(cache, key=lambda k: cache[k]["at"])[:-max_entries]:
        cache.pop(k, None)
