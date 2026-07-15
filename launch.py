#!/usr/bin/env python
"""Single access point to run the Sleeper analytics apps for either instance
(R or Python).

    python launch.py python dashboard            # Python web app (FastAPI + HTMX)
    python launch.py r dashboard                 # R web app (Shiny)

    python launch.py python report               # standalone HTML season report
    python launch.py r report <league> --all     # one report per season

    python launch.py python serve                # Python slash-command bot
    python launch.py python weekly --dry-run     # Python weekly recap (preview)
    python launch.py r serve                      # R interactions endpoint (plumber)
    python launch.py r weekly --dry-run           # R weekly recap (preview)

Instances live in separate subdirectories:
    python/   -> venv + Python package (sleepermetrics) + bot.py + webapp/
    r/        -> launcher for the R package (../sleepermetrics)

Anything after the mode is passed through to that instance's runner (e.g.
`dashboard --port 8000`). Config is read from each instance's .env
(python/.env, r/.env) or the environment.
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


def _parse_port(extra: list[str], default: int) -> tuple[int, list[str]]:
    port, rest = default, []
    it = iter(range(len(extra)))
    i = 0
    while i < len(extra):
        if extra[i] in ("--port", "-p") and i + 1 < len(extra):
            port = int(extra[i + 1])
            i += 2
            continue
        rest.append(extra[i])
        i += 1
    return port, rest


def _run_python(mode: str, extra: list[str]) -> int:
    venv_py = PY_DIR / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
    if not venv_py.exists():
        sys.exit("Python venv missing. Set it up:\n"
                 "  python -m venv python/venv && "
                 "python/venv/Scripts/pip install -r python/requirements.txt")
    if mode == "dashboard":
        port, rest = _parse_port(extra, 8000)
        env = dict(os.environ, SLEEPERMETRICS_PLAYOFFS=str(BASE / "playoffs"))
        # Jinja reloads templates on its own, so WITHOUT --reload a long-running
        # server picks up template edits while still holding the old app.py --
        # the two drift apart and blow up on the mismatch. Reload both together.
        # Pass --no-reload when serving for real (hosting, Docker).
        reload = [] if "--no-reload" in rest else ["--reload"]
        print(f"Dashboard: http://127.0.0.1:{port}  (Ctrl+C to stop)")
        return subprocess.run(
            [str(venv_py), "-m", "uvicorn", "webapp.app:app",
             "--host", "127.0.0.1", "--port", str(port), *reload],
            cwd=str(PY_DIR), env=env).returncode
    if mode == "report":
        env = dict(os.environ, SLEEPERMETRICS_PLAYOFFS=str(BASE / "playoffs"))
        # Reports land in the repo root, not python/, so run from BASE with the
        # package importable via the venv's site-packages editable install.
        return subprocess.run([str(venv_py), str(PY_DIR / "make_report.py"), *extra],
                              cwd=str(BASE), env=env).returncode
    return subprocess.run([str(venv_py), "bot.py", mode, *extra], cwd=str(PY_DIR)).returncode


def _run_r(mode: str, extra: list[str]) -> int:
    rscript = _find_rscript()
    if mode == "dashboard":
        port, _rest = _parse_port(extra, 8100)
        print(f"Dashboard: http://127.0.0.1:{port}  (Ctrl+C to stop)")
        return subprocess.run([rscript, "tools/run_dashboard.R", str(port)],
                              cwd=str(BASE)).returncode
    if mode == "report":
        env = dict(os.environ, SLEEPERMETRICS_PLAYOFFS=str(BASE / "playoffs"))
        return subprocess.run([rscript, "R/make_report.R", *extra],
                              cwd=str(BASE), env=env).returncode
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
