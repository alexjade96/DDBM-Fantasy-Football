#!/usr/bin/env python
"""Single access point to run the Sleeper analytics Discord bot for either
instance (R or Python).

    python launch.py python serve                # Python slash-command bot
    python launch.py python weekly --dry-run     # Python weekly recap (preview)
    python launch.py r serve                      # R interactions endpoint (plumber)
    python launch.py r weekly --dry-run           # R weekly recap (preview)

Instances live in separate subdirectories:
    python/   -> venv + Python package (sleepermetrics) + bot.py
    r/        -> launcher for the R package (../sleepermetrics)

Anything after the mode is passed through to that instance's runner. Config is
read from each instance's .env (python/.env, r/.env) or the environment.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY_DIR = BASE / "python"
R_DIR = BASE / "R"


def _find_rscript() -> str:
    cand = shutil.which("Rscript")
    if cand:
        return cand
    hits = sorted(glob.glob(r"C:\Program Files\R\*\bin\x64\Rscript.exe")
                  + glob.glob(r"C:\Program Files\R\*\bin\Rscript.exe"), reverse=True)
    if hits:
        return hits[0]
    sys.exit("Could not find Rscript on PATH or under C:\\Program Files\\R.")


def _run_python(mode: str, extra: list[str]) -> int:
    venv_py = PY_DIR / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    if not venv_py.exists():
        sys.exit("Python venv missing. Set it up:\n"
                 "  python -m venv python/venv && "
                 "python/venv/Scripts/pip install -r python/requirements.txt")
    return subprocess.run([str(venv_py), "bot.py", mode, *extra], cwd=str(PY_DIR)).returncode


def _run_r(mode: str, extra: list[str]) -> int:
    rscript = _find_rscript()
    return subprocess.run([rscript, "R/run_bot.R", mode, *extra], cwd=str(BASE)).returncode


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2 or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0 if argv[:1] in (["-h"], ["--help"]) else 2
    impl, mode, *extra = argv
    impl = impl.lower()
    if impl in ("py", "python"):
        return _run_python(mode, extra)
    if impl in ("r", "rlang"):
        return _run_r(mode, extra)
    sys.exit(f"Unknown instance '{impl}' (use 'r' or 'python').")


if __name__ == "__main__":
    raise SystemExit(main())
