"""Keeps the in-season snapshot sources current, with a progress status.

Two triggers, both read-only against the network until something really
changed:

  * **Sleeper weekly feed** (`data/sources/sleeper_stats/`): no change check
    exists, so Sleeper's own week indicator is the trigger. When the
    indicator moves (season type + week, e.g. `2026:regular:4` to
    `2026:regular:5`), weeks 1 through the last completed week are re-pulled
    once. Within one indicator nothing refreshes.
  * **nflverse datasets** (`data/sources/nflverse/`): each is asked at most
    every `refresh_policy.CHECK_INTERVAL` whether its release asset changed
    (a conditional HEAD; `304` costs no body). Only a changed dataset is
    downloaded again.

A past season gets one final refresh after the new season starts, then is
marked `final` and never touched again.

Everything runs on one background thread. Pages keep reading the old
snapshots until each new file is swapped in (the writers are atomic), and
`status()` feeds the banner. A failed source keeps its old file and retries
after `refresh_policy.RETRY_COOLDOWN`. Set `DISABLE_REFRESH=1` to
turn the whole thing off.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass

from sleepermetrics import draft as adp_draft
from sleepermetrics import nflstats, refresh_policy as rp, scoring
from webapp.sources.ffadp import api as adp_api
from webapp.sources.ffadp import board as adp_board
from webapp.sources.ffadp import cache as adp_cache
from webapp.sources.ffadp import rotowire as adp_rotowire
from webapp.sources.nflref import api as nflref_api
from webapp.sources.nflref import cache as nflref_cache
from webapp.sources.nflref.base import DATASETS

#: derived from two ~20MB play-by-play assets that nflverse freezes in
#: season; not worth polling.
_SKIP_DATASETS = {"route_participation"}
#: a season's last Sleeper stats week; a finished season is refreshed through it.
_LAST_WEEK = 18
#: minimum gap between planning passes, so a burst of requests plans once.
_PLAN_GAP = 60

_lock = threading.Lock()
_last_plan = 0.0
_status: dict = {"phase": "idle", "run": 0, "done": 0, "total": 0,
                 "label": "", "failed": 0, "indicator": None}


@dataclass
class Item:
    """One thing to download: a Sleeper stats week or an nflverse dataset."""
    kind: str                 # "sleeper" | "nflverse"
    key: str                  # refresh_policy key
    season: str
    label: str
    week: int | None = None   # sleeper only
    dataset: object = None    # nflverse: the dataset; adp: the provider name
    validators: dict | None = None
    final: bool = False
    fmt: str | None = None    # adp only: the scoring format


def enabled() -> bool:
    return os.environ.get("DISABLE_REFRESH", "") not in ("1", "true", "yes")


def status() -> dict:
    with _lock:
        return dict(_status)


def _set(**kw) -> None:
    with _lock:
        _status.update(kw)


def _completed_weeks(state: dict) -> list[int]:
    if state["season_type"] == "regular":
        return list(range(1, max(state["week"], 1)))
    if state["season_type"] == "post":
        return list(range(1, _LAST_WEEK + 1))
    return []


def plan() -> tuple[list[Item], dict | None]:
    """What needs downloading right now. Does the cheap checks (state file,
    conditional HEADs) and returns only real work, so an up-to-date site
    plans nothing."""
    state = rp.current_state()
    if not state:
        return [], None
    season, indicator = state["season"], state["indicator"]
    items: list[Item] = []

    # Sleeper weekly feed: indicator-driven, one record per season.
    key = f"sleeper_stats/{season}"
    if not rp.in_cooldown(key) and rp.indicator_changed(key, indicator):
        for wk in _completed_weeks(state):
            items.append(Item("sleeper", key, season, f"Sleeper week {wk}", week=wk))

    # nflverse: ask each dataset whether its asset changed.
    for name, ds in DATASETS.items():
        if name in _SKIP_DATASETS:
            continue
        key = f"nflverse/{name}/{season}"
        if rp.in_cooldown(key) or not rp.check_due(key):
            continue
        earliest = ds._earliest()
        if earliest is not None and int(season) < earliest:
            continue
        try:
            asset = ds._asset(season)
        except Exception:
            continue
        entry = rp.get(key) or {}
        verdict, validators = nflref_api.head_release(asset, entry.get("validators"))
        if verdict == "unchanged":
            rp.record_check(key)
        elif verdict == "changed":
            items.append(Item("nflverse", key, season, ds.label or name,
                              dataset=ds, validators=validators))
        else:
            rp.mark_failed(key)

    # A finished season gets one last refresh, then is frozen.
    for key, entry in rp.items().items():
        parts = key.split("/")
        if entry.get("status") == "final" or parts[-1] >= season:
            continue
        past = parts[-1]
        if parts[0] == "sleeper_stats" and not rp.in_cooldown(key):
            items.extend(Item("sleeper", key, past, f"Sleeper {past} week {wk}",
                              week=wk, final=True)
                         for wk in range(1, _LAST_WEEK + 1))
        elif parts[0] == "nflverse" and len(parts) == 3 and parts[1] in DATASETS \
                and parts[1] not in _SKIP_DATASETS and not rp.in_cooldown(key):
            ds = DATASETS[parts[1]]
            items.append(Item("nflverse", key, past, f"{ds.label or parts[1]} {past}",
                              dataset=ds, final=True))
    return items, state


# -- ADP sources (silent: no banner, they only feed the pre-season ADP tab) ----
#
# (provider, scoring formats kept as separate snapshots, probe kind). Only the
# CURRENT draft season is touched; past seasons are frozen history. A probe of
# "sleeper"/"ffc"/"cbs" is a conditional GET (verified live to answer 304);
# None means the host gives no validators, so the source is simply re-pulled
# once its interval is up.
_ADP_TARGETS = [
    ("sleeper", ("ppr",), "sleeper"),
    ("ffc", ("std", "half_ppr", "ppr", "2qb"), "ffc"),
    ("cbs", ("ppr",), "cbs"),
    ("yahoo", ("ppr",), None),
    ("espn", ("ppr",), None),
    ("rotowire", ("ppr", "std"), None),
]
_DAY, _WEEK = 86400, 7 * 86400


def _adp_interval(name: str, state: dict) -> int:
    """Daily while the draft season is live; weekly once the regular season is
    past week 1. ESPN's ~20MB file is weekly regardless."""
    if name == "espn":
        return _WEEK
    if state["season_type"] == "regular" and state["week"] > 1:
        return _WEEK
    return _DAY


def _adp_key(name: str, fmt: str, season: str) -> str:
    multi = {"ffc", "rotowire"}
    return f"adp/{name}/{fmt}/{season}" if name in multi else f"adp/{name}/{season}"


def _adp_probe(kind, season, fmt, validators):
    if kind == "sleeper":
        from sleepermetrics.api import adp_request
        url, params = adp_request(season)
        return adp_api.probe_unchanged(url, params, validators)
    if kind == "ffc":
        return adp_api.probe_unchanged(adp_api.ffc_url(fmt),
                                       {"teams": 12, "year": int(season)}, validators)
    if kind == "cbs":
        return adp_api.probe_unchanged(adp_api._CBS_URL, None, validators)
    return "changed", None            # no validators: re-pull on the timer


def plan_adp(state: dict) -> list[Item]:
    season = state["season"]
    items: list[Item] = []
    for name, fmts, kind in _ADP_TARGETS:
        first = adp_board.FIRST_SEASON.get(name)
        if first is not None and int(season) < first:
            continue
        for fmt in fmts:
            key = _adp_key(name, fmt, season)
            if rp.in_cooldown(key) or not rp.check_due(key, _adp_interval(name, state)):
                continue
            entry = rp.get(key) or {}
            verdict, validators = _adp_probe(kind, season, fmt, entry.get("validators"))
            if verdict == "unchanged":
                rp.record_check(key)
            elif verdict == "changed":
                items.append(Item("adp", key, season, f"{name} {fmt}",
                                  dataset=name, fmt=fmt, validators=validators))
            else:
                rp.mark_failed(key)
    return items


def _adp_snapshot(name: str, fmt: str, season: str):
    """The on-disk file a provider's refresh rewrites."""
    if name == "sleeper":
        return adp_draft._adp_snapshot_path(season)
    variant = {"ffc": fmt, "rotowire": adp_rotowire._SLUG.get(fmt, "PPR")}.get(name)
    return adp_cache._path(name, season, variant)


def _do_adp(item: Item) -> bool:
    path = _adp_snapshot(item.dataset, item.fmt, item.season)
    t0 = time.time() - 1
    if item.dataset == "sleeper":
        adp_draft._adp_cache.pop(item.season, None)   # reload must reach the network
    adp_board._BY_NAME[item.dataset].fetch(item.season, item.fmt, reload=True)
    return _mtime(path) >= t0


def run_adp(items: list[Item]) -> None:
    """Silent counterpart of `run`: never touches the banner status."""
    for item in items:
        try:
            ok = _do_adp(item)
        except Exception:
            ok = False
        if ok:
            rp.record_refresh(item.key, validators=item.validators)
        else:
            rp.mark_failed(item.key)


def _mtime(path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _do_nflverse(item: Item) -> bool:
    path = nflref_cache._path(item.dataset.name, item.season)
    t0 = time.time() - 1
    item.dataset.fetch(item.season, reload=True)
    return _mtime(path) >= t0


def _do_sleeper(item: Item) -> bool:
    path = nflstats._snapshot_path(item.season, item.week)
    t0 = time.time() - 1
    nflstats.raw_week(item.season, item.week, reload=True)
    return _mtime(path) >= t0


def run(items: list[Item], state: dict | None) -> None:
    """Download `items`, recording each source as it finishes. A Sleeper
    season is recorded only when all of its weeks came through."""
    indicator = state["indicator"] if state else None
    _set(phase="running", done=0, total=len(items), failed=0, label="",
         indicator=indicator, run=status()["run"] + 1)
    scoring.clear_stats_cache()          # reload must not read the process cache
    failed_keys: set[str] = set()
    for n, item in enumerate(items, 1):
        _set(label=item.label)
        try:
            ok = _do_sleeper(item) if item.kind == "sleeper" else _do_nflverse(item)
        except Exception:
            ok = False
        if not ok:
            failed_keys.add(item.key)
            _set(failed=len(failed_keys))
        elif item.kind == "nflverse":
            rp.record_refresh(item.key, validators=item.validators,
                              status="final" if item.final else "ok")
        _set(done=n)
    for key in {i.key for i in items if i.kind == "sleeper"}:
        if key in failed_keys:
            continue
        final = any(i.final for i in items if i.key == key)
        rp.record_refresh(key, indicator=None if final else indicator,
                          status="final" if final else "ok")
    for key in failed_keys:
        rp.mark_failed(key)
    nflstats.clear_cache()
    _set(phase="done", label="", failed=len(failed_keys), finished=time.time())


def _worker() -> None:
    try:
        items, state = plan()
        if items:
            run(items, state)
        if state:
            run_adp(plan_adp(state))        # silent: no banner
    except Exception:
        _set(phase="idle")
    finally:
        with _lock:
            if _status["phase"] == "running":
                _status["phase"] = "idle"
        _release()


_running = False


def _release() -> None:
    global _running
    with _lock:
        _running = False


def maybe_start() -> bool:
    """Called on requests and at boot; cheap and non-blocking. Starts one
    background planning/refresh pass if none is running and the last pass
    was over `_PLAN_GAP` seconds ago. Returns True when a pass was started."""
    global _running, _last_plan
    if not enabled():
        return False
    now = time.time()
    with _lock:
        if _running or now - _last_plan < _PLAN_GAP:
            return False
        _running = True
        _last_plan = now
    try:
        threading.Thread(target=_worker, name="data-refresh", daemon=True).start()
    except Exception:
        _release()
        return False
    return True
