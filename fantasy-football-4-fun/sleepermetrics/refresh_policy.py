"""When a snapshot source was last refreshed, and when it is due again.

One small JSON file, `data/sources/refresh_state.json`, records for each
snapshot source (`sleeper_stats/<season>`, `nflverse/<dataset>/<season>`):

    last_refreshed  epoch seconds of the last successful live fetch
    last_checked    epoch seconds of the last "has it changed?" check
    indicator       the Sleeper season-type:week the data was fetched under
    validators      {"etag", "last_modified"} the host returned (nflverse)
    status          "ok" | "final"  ("final": a finished season, never again)

A central file rather than a marker beside each snapshot because the Sleeper
weekly files are plain {player_id: line} dicts with nowhere to put one. A
missing entry means "never recorded", which callers treat as stale.

Policy lives with the callers (`webapp/refresher.py`); this module only holds
the state and the Sleeper week indicator, so another source can be added by
declaring its own policy against the same file.
"""
from __future__ import annotations

import json
import os
import threading
import time

from repo_paths import SOURCES_DIR

from .api import sleeper_api

STATE_PATH = SOURCES_DIR / "refresh_state.json"

#: how often a source with a cheap "changed?" check is asked (seconds).
CHECK_INTERVAL = int(os.environ.get("SLEEPERMETRICS_REFRESH_CHECK_SECS", str(6 * 3600)))
#: after a failed refresh, how long before the same source is tried again.
RETRY_COOLDOWN = 30 * 60
#: how long the Sleeper week indicator is trusted before re-reading it.
_INDICATOR_TTL = 300

_lock = threading.RLock()
_state: dict | None = None
_failed_at: dict[str, float] = {}
_indicator_cache: tuple[float, dict | None] = (0.0, None)


def _now() -> float:
    return time.time()


# -- the state file ---------------------------------------------------------

def _load() -> dict:
    global _state
    if _state is None:
        try:
            data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            _state = data if isinstance(data, dict) else {}
        except Exception:
            _state = {}
        _state.setdefault("sources", {})
    return _state


def _save() -> None:
    """Atomic write (temp file + replace); best-effort, a read-only FS is
    not fatal."""
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(_state, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass


def reset() -> None:
    """Forget the in-process copy (tests, or after the file was edited)."""
    global _state, _indicator_cache
    with _lock:
        _state = None
        _indicator_cache = (0.0, None)
        _failed_at.clear()


def get(key: str) -> dict | None:
    with _lock:
        entry = _load()["sources"].get(key)
        return dict(entry) if entry else None


def items() -> dict[str, dict]:
    with _lock:
        return {k: dict(v) for k, v in _load()["sources"].items()}


def record_refresh(key: str, indicator: str | None = None,
                   validators: dict | None = None, status: str = "ok") -> None:
    """A successful live fetch of `key`: stamps both times and clears any
    failure cooldown."""
    now = _now()
    with _lock:
        entry = _load()["sources"].setdefault(key, {})
        entry["last_refreshed"] = now
        entry["last_checked"] = now
        entry["status"] = status
        if indicator is not None:
            entry["indicator"] = indicator
        if validators:
            entry["validators"] = validators
        _failed_at.pop(key, None)
        _save()


def record_check(key: str) -> None:
    """`key` was asked "has it changed?" and the answer was no."""
    with _lock:
        entry = _load()["sources"].setdefault(key, {})
        entry["last_checked"] = _now()
        _save()


def mark_failed(key: str) -> None:
    """A refresh of `key` failed: keep the old file, retry after a cooldown.
    In-process only, so a restart simply retries."""
    with _lock:
        _failed_at[key] = _now()


def in_cooldown(key: str) -> bool:
    with _lock:
        t = _failed_at.get(key)
    return t is not None and _now() - t < RETRY_COOLDOWN


def check_due(key: str, interval: float | None = None) -> bool:
    """True when `key` has never been recorded or was last checked more than
    `interval` (default CHECK_INTERVAL) seconds ago."""
    entry = get(key)
    if not entry or "last_checked" not in entry:
        return True
    return _now() - entry["last_checked"] >= (CHECK_INTERVAL if interval is None else interval)


def indicator_changed(key: str, indicator: str) -> bool:
    """True when `key` was fetched under a different Sleeper indicator (or
    never recorded)."""
    entry = get(key)
    return not entry or entry.get("indicator") != indicator


# -- Sleeper's week indicator ------------------------------------------------

def current_state() -> dict | None:
    """`{"season", "season_type", "week", "indicator"}` from Sleeper's
    `/state/nfl`, e.g. indicator `"2026:regular:4"`. Trusted for five
    minutes; `None` when Sleeper can't be reached (callers then refresh
    nothing)."""
    global _indicator_cache
    with _lock:
        at, cached = _indicator_cache
        if cached is not None and _now() - at < _INDICATOR_TTL:
            return dict(cached)
    try:
        raw = sleeper_api("/state/nfl")
    except Exception:
        raw = None
    if not isinstance(raw, dict) or not raw.get("league_season"):
        return None
    season = str(raw["league_season"])
    season_type = str(raw.get("season_type") or "")
    week = int(raw.get("week") or 0)
    out = {"season": season, "season_type": season_type, "week": week,
           "indicator": f"{season}:{season_type}:{week}"}
    with _lock:
        _indicator_cache = (_now(), out)
    return dict(out)
