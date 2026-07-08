#!/usr/bin/env python
"""Cross-language test harness.

Runs and verifies BOTH implementations operate correctly and produce mirrored
outputs:

  1. Python unit tests (pytest, python/tests)
  2. R unit tests (testthat, R/sleepermetrics)
  3. Both exporters (parity/export_{py,r}.py/R) -> canonical metric JSON
  4. A field-by-field parity diff of the two JSONs (numbers within tolerance,
     summary text exact)

    python verify.py [league_id]

Exit code 0 only if every check passes.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = BASE / "python" / ("venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python")
TOL = 0.011


def _rscript() -> str:
    c = shutil.which("Rscript")
    if c:
        return c
    hits = sorted(glob.glob(r"C:\Program Files\R\*\bin\x64\Rscript.exe"), reverse=True)
    if not hits:
        sys.exit("Rscript not found.")
    return hits[0]


def _run(label, cmd, cwd=None, env=None) -> bool:
    print(f"\n>>> {label}")
    ok = subprocess.run(cmd, cwd=cwd, env=env).returncode == 0
    print(f"    [{'PASS' if ok else 'FAIL'}] {label}")
    return ok


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _cmp(path, a, b, errs):
    if isinstance(a, bool) or isinstance(b, bool):
        if a != b:
            errs.append(f"{path}: {a!r} != {b!r}")
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            errs.append(f"{path}: length {len(a)} != {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _cmp(f"{path}[{i}]", x, y, errs)
    elif isinstance(a, dict) and isinstance(b, dict):
        for k in set(a) | set(b):
            _cmp(f"{path}.{k}", a.get(k), b.get(k), errs)
    else:
        na, nb = _num(a), _num(b)
        if na is not None and nb is not None:
            if abs(na - nb) > TOL:
                errs.append(f"{path}: {a} != {b}")
        elif a != b:
            errs.append(f"{path}: {a!r} != {b!r}")


def _compare(rj, pj):
    errs = []
    for k in [k for k in rj if k != "impl"]:
        _cmp(k, rj.get(k), pj.get(k), errs)
    return errs


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    league = argv[0] if argv else "1252770181306929152"
    rs = _rscript()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if not PY.exists():
        sys.exit(f"Python venv missing at {PY}. Create it: "
                 "python -m venv python/venv && "
                 "python/venv/Scripts/pip install -r python/requirements.txt")
    res = {}

    res["pytest"] = _run("pytest (Python unit tests)",
                         [str(PY), "-m", "pytest", "tests", "-q"], cwd=str(BASE / "python"))
    res["testthat"] = _run("testthat (R unit tests)", [rs, "-e", (
        'r <- as.data.frame(testthat::test_local("R/sleepermetrics", reporter="minimal"));'
        ' quit(status = as.integer(sum(r$failed) + sum(r$error) > 0))')], cwd=str(BASE))
    res["export_py"] = _run("export metrics (Python)",
                            [str(PY), "parity/export_py.py", league, "parity/out_py.json"],
                            cwd=str(BASE), env=env)
    res["export_r"] = _run("export metrics (R)",
                           [rs, "parity/export_r.R", league, "parity/out_r.json"], cwd=str(BASE))

    print("\n>>> parity diff (R vs Python)")
    if not (res["export_py"] and res["export_r"]):
        print("    [FAIL] exporters did not both succeed; skipping diff")
        res["parity"] = False
    else:
        rj = json.loads((BASE / "parity" / "out_r.json").read_text(encoding="utf-8"))
        pj = json.loads((BASE / "parity" / "out_py.json").read_text(encoding="utf-8"))
        errs = _compare(rj, pj)
        if errs:
            print(f"    [FAIL] {len(errs)} mismatch(es):")
            for e in errs[:30]:
                print("      -", e)
            res["parity"] = False
        else:
            nrec = sum(len(v) for v in rj.values() if isinstance(v, list))
            print(f"    [PASS] R and Python mirror: season {rj['season']}, "
                  f"{nrec} metric records + 3 summaries identical")
            res["parity"] = True

    print("\n==== VERIFY SUMMARY ====")
    for k, v in res.items():
        print(f"  [{'PASS' if v else 'FAIL'}]  {k}")
    ok = all(res.values())
    print(f"\n{'ALL CHECKS PASSED' if ok else 'SOME CHECKS FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
