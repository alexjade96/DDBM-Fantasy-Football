"""Single source of truth for the paths tools/parity/export_py.py needs.

export_py.py and export_r.R each used to hardcode their own copies of the
repo-relative package path (`sys.path.insert(0, "python")` /
`pkgload::load_all("R/sleepermetrics", ...)`) and the season-data directory
(`apply_playoffs(ss, "playoffs")` -- a directory that never actually existed;
see the restructure notes in CLAUDE.md). Centralizing the Python side here
means a future rename only needs one edit instead of finding every literal.

There is no R equivalent module (R doesn't have a portable "this file's own
directory" primitive the way `Path(__file__)` is): export_r.R instead reads
these same literal values directly, kept in sync with this file by hand. If
you change PY_PACKAGE_DIR or SEASON_DIR here, update export_r.R's own
`pkgload::load_all(...)` and `sl_apply_playoffs(ss, ...)` calls to match.
"""
from __future__ import annotations

from pathlib import Path

# tools/parity/paths.py -> parent = tools/parity/ -> parent.parent = tools/ ->
# parent.parent.parent = repo root (this file is nested two levels deep).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: repo-root-relative dir name of the Python instance's package tree.
PY_PACKAGE_DIR = "fantasy-football-4-fun"

#: repo-root-relative dir name of the durable season-data tree.
SEASON_DIR = "data/seasons"
