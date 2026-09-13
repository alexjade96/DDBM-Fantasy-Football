"""Single source of truth for this instance's repo-relative paths.

sleepermetrics/ and webapp/ (plus webapp/sources/{ffadp,nflref}, nested under
webapp/ since they're webapp-only data integrations) all need to find
`data/seasons/` at the repo root, and each used to compute that independently
via `Path(__file__).resolve().parents[2]`. That meant a repo restructure (or
even just moving one of those packages a directory deeper/shallower) required
finding and fixing every occurrence by hand -- which is exactly the kind of
change that breaks silently if one copy is missed. This module computes it
once; everything else imports SEASON_DIR from here.

This file lives directly under fantasy-football-4-fun/ (the Python instance
dir, a sibling of sleepermetrics/ and the webapp/ FastAPI package), not inside
any one of them, so no package has to depend on another package's internals
just to find the repo root. `data/seasons/` is a SIBLING of
fantasy-football-4-fun/ at the repo root, one level up from this file.

The Dockerfile is a SEPARATE case, not the same computation at a different
depth: its COPY steps flatten everything into /app/ (repo_paths.py,
sleepermetrics/, webapp/ -- which still carries its own sources/ subtree --
all become direct siblings there), while data/seasons/ is copied to
/app/data/seasons -- a genuinely different relative shape than the real
repo's, not just a shifted depth. Rather than try to make one formula cover
both, the Dockerfile sidesteps this entirely by setting
SLEEPERMETRICS_SEASON_DIR explicitly (`ENV
SLEEPERMETRICS_SEASON_DIR=/app/data/seasons`), so the fallback below never
actually runs in that environment -- it only needs to be correct for the real
repo layout.
"""
from __future__ import annotations

import os
from pathlib import Path

# fantasy-football-4-fun/repo_paths.py -> parent = fantasy-football-4-fun/ -> parent.parent = repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent

SEASON_DIR = Path(os.environ.get(
    "SLEEPERMETRICS_SEASON_DIR", str(REPO_ROOT / "data" / "seasons")))
