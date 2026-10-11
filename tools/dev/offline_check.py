#!/usr/bin/env python
"""Prove that data derived from NFL sources comes from stored files, not the network.

    fantasy-football-4-fun/venv/Scripts/python tools/dev/offline_check.py [--state current|raw-only|render-image] [--only NAME ...]

Every action runs with the network switched off (any socket connect fails) and
under the load meter, which still counts an ATTEMPTED call.  So the result per
action is: did it try to reach the network, and did it still produce data?

* `--state current` (default): the real `data/sources/`.  Shows whether a normal
  run needs the network for anything stored.
* `--state raw-only`: a temporary copy of `data/sources/` holding ONLY the raw
  files (and the static scoring chart); every derived snapshot is missing.  Shows
  what can be rebuilt from raw alone.  Nothing in the repository is changed.

* `--state render-image`: a temporary copy of `data/sources/` as the Docker image
  holds it (everything except the play-by-play raw folders, which `.dockerignore`
  leaves out), run with `RENDER=true`.  Besides the network check it reports
  whether any file was WRITTEN (Render must write none), whether the load meter is
  off with `/loadmeter` answering 404, and the peak memory of the process.  Peak
  memory is measured on Windows and is not Render's accounting.

League and user calls (Sleeper league endpoints) are out of scope: they always go
to Sleeper by design.  The Sleeper player dump (`sleeperPlayerData_py.pkl`, a
daily cache in the repo root) is used as it is.

Exit code 1 if any action tried the network or came back empty.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fantasy-football-4-fun"))

KEEP_NAMES = {"raw", "default_scoring.json"}


def _raw_only_copy(src: Path) -> Path:
    """A copy of data/sources/ with only the raw folders and the scoring chart."""
    dst = Path(tempfile.mkdtemp(prefix="sources_rawonly_")) / "sources"
    dst.mkdir(parents=True)
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if p.is_file() and ("raw" in rel.parts or rel.name in KEEP_NAMES):
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)
    return dst


def _peak_mb() -> float | None:
    """Peak working set of this process in MB (Windows only)."""
    try:
        import ctypes
        from ctypes import wintypes

        class PMC(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]
        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.K32GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PMC), wintypes.DWORD]
        k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        if not k32.K32GetProcessMemoryInfo(k32.GetCurrentProcess(), ctypes.byref(pmc), pmc.cb):
            return None
        return pmc.PeakWorkingSetSize / 1e6
    except Exception:
        return None


def _image_copy(src: Path) -> Path:
    """data/sources/ as the Docker image holds it: .dockerignore leaves out the
    play-by-play raw folders."""
    dst = Path(tempfile.mkdtemp(prefix="sources_image_")) / "sources"
    skip = (("nflverse", "raw", "pbp"), ("nflverse", "raw", "pbp_participation"))
    for p in src.rglob("*"):
        rel = p.relative_to(src)
        if p.is_file() and not any(rel.parts[:3] == s for s in skip):
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst / rel)
    return dst


def _tree(root: Path) -> dict:
    return {str(f.relative_to(root)): (f.stat().st_size, f.stat().st_mtime_ns)
            for f in root.rglob("*") if f.is_file()}


def _block_network() -> None:
    def refuse(*a, **k):
        raise OSError("network is switched off for this check")
    socket.socket.connect = refuse          # type: ignore[assignment]
    socket.socket.connect_ex = refuse       # type: ignore[assignment]


def _actions():
    from webapp.sources import nflref
    from webapp.sources.nflref import summary
    from webapp.sources.ffadp import board, finish

    def n(x):
        try:
            return len(x)
        except TypeError:
            return 0

    def player_profile():
        from webapp import player_profile as pp
        p = pp.player_profile("4034", None, fresh=True)
        # every stored dataset row the profile pulled together
        return sum(n(v.get("rows") or []) for v in (p.get("real_nfl") or {}).values()
                   if isinstance(v, dict))

    def team_profile():
        from webapp import team_profile as tp
        p = tp.team_profile("DET", "2025", fresh=True)
        return n(p.get("roster") or []) + n(p.get("schedule") or [])

    def compare():
        from webapp import player_compare as pc
        a = pc.player_field_compare("2024", "RB", ["4034"])
        b = pc.player_trend(["4034"], "2024", "RB")
        return n(a) + n(b)

    def adp_board():
        b = board.combine("2024", scoring="ppr", reload=False)
        return n(b.get("rows") or [])

    def adp_finish():
        return n(finish.season_value_ranks("2024", "ppr"))

    return {
        "leaderboard_nflverse": lambda: n(summary.player_leaderboard("2024", "ALL", source="nflverse")),
        "leaderboard_sleeper": lambda: n(summary.player_leaderboard("2024", "ALL", source="sleeper")),
        "schedule": lambda: n(summary.schedule_grid("2024")),
        "compare_sources": lambda: n(summary.compare_sources("2024", "WR").get("rows") or []),
        "player_stats": lambda: n(nflref.load("player_stats", "2024")),
        "snap_counts": lambda: n(nflref.load("snap_counts", "2024")),
        "ngs_receiving": lambda: n(nflref.load("ngs_receiving", "2024")),
        "pfr_def": lambda: n(nflref.load("pfr_def", "2024")),
        "injuries": lambda: n(nflref.load("injuries", "2024")),
        "route_participation": lambda: n(nflref.load("route_participation", "2024")),
        "player_profile": player_profile,
        "team_profile": team_profile,
        "player_compare": compare,
        "adp_board": adp_board,
        "adp_finish_ranks": adp_finish,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--state", choices=["current", "raw-only", "render-image"], default="current")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()

    os.environ["DISABLE_REFRESH"] = "1"
    os.environ["SLEEPERMETRICS_NO_IMAGES"] = "1"
    tmp = None
    if a.state == "raw-only":
        # NOT via repo_paths: importing it here would fix the data folder to
        # the real one before the environment variable below is set.
        real = Path(os.environ.get("SLEEPERMETRICS_SOURCES_DIR") or ROOT / "data" / "sources")
        tmp = _raw_only_copy(real)
        os.environ["SLEEPERMETRICS_SOURCES_DIR"] = str(tmp)
        print(f"raw-only copy: {sum(f.stat().st_size for f in tmp.rglob('*') if f.is_file()) / 1e6:.0f} MB at {tmp}")
    before = None
    if a.state == "render-image":
        real = Path(os.environ.get("SLEEPERMETRICS_SOURCES_DIR") or ROOT / "data" / "sources")
        tmp = _image_copy(real)
        os.environ["SLEEPERMETRICS_SOURCES_DIR"] = str(tmp)
        os.environ["RENDER"] = "true"
        before = _tree(tmp)
        print(f"image copy: {sum(v[0] for v in before.values()) / 1e6:.0f} MB, "
              f"{len(before)} files, RENDER=true")
    # imports AFTER the environment is set: the modules read the data folder at import
    import repo_paths
    if tmp is not None and Path(repo_paths.SOURCES_DIR) != tmp:
        raise SystemExit("raw-only check is not using the temporary copy; refusing to run")
    from webapp import loadmeter
    _block_network()
    acts = _actions()
    names = a.only or list(acts)
    bad = 0
    print(f"state={a.state}\n{'action':24} {'tried net':>9} {'rows':>7} {'secs':>6}  note")
    for name in names:
        t0 = time.time()
        note = ""
        rows = 0
        with loadmeter.session(name) as m:
            try:
                rows = acts[name]()
            except Exception as exc:                       # noqa: BLE001
                note = f"{type(exc).__name__}: {str(exc)[:70]}"
        tried = len(m.calls)
        # on Render a route-participation build is skipped on purpose
        expected_empty = a.state == "render-image" and name == "route_participation"
        flag = tried > 0 or (rows == 0 and not expected_empty)
        bad += flag
        print(f"{name:24} {tried:>9} {rows:>7} {time.time() - t0:>6.1f}  "
              f"{'<-- ' if flag else ''}{note}")
        for r in m.by_endpoint()[:6]:
            print(f"{'':24}   {r['calls']:>3}x {r['host']}{r['endpoint']}  <- {r['caller']}")
    if a.state == "render-image":
        after = _tree(tmp)
        changed = sorted(k for k in after if before.get(k) != after[k])
        gone = sorted(k for k in before if k not in after)
        print(f"\nfiles written or changed under data/sources: {len(changed)}"
              f"{'  <-- Render must write none' if changed else ''}")
        for k in changed[:8]:
            print(f"   {k}")
        if gone:
            print(f"files removed: {len(gone)}")
        bad += bool(changed or gone)
        from webapp import loadmeter as lm
        from types import SimpleNamespace
        meter_off = lm.enabled() is False
        try:
            from webapp import app as appmod
            status = appmod.loadmeter_view(
                SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))).status_code
        except Exception as exc:                             # noqa: BLE001
            status = f"error {type(exc).__name__}"
        print(f"load meter enabled(): {not meter_off}; GET /loadmeter from localhost: {status}"
              f"{'' if meter_off and status == 404 else '  <-- expected off and 404'}")
        bad += not (meter_off and status == 404)
    peak = _peak_mb()
    if peak:
        print(f"peak memory of this process: {peak:.0f} MB (Windows working set)")
    if tmp:
        shutil.rmtree(tmp.parent, ignore_errors=True)
    print(f"\n{bad} of {len(names)} actions tried the network or returned nothing")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
