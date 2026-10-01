"""Refresh state, the conditional HEAD helper, and the refresher's plan/run.

Network-free: the Sleeper indicator, the HTTP responses and the downloads are
all faked.
"""
import pytest

from sleepermetrics import refresh_policy as rp
from webapp import refresher
from webapp.sources.nflref import api as nflref_api


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(rp, "STATE_PATH", tmp_path / "refresh_state.json")
    rp.reset()
    monkeypatch.setattr(refresher, "_last_plan", 0.0)
    monkeypatch.setattr(refresher, "_running", False)
    refresher._status.update(phase="idle", run=0, done=0, total=0, label="", failed=0)
    yield
    rp.reset()


class FakeDataset:
    def __init__(self, name, earliest=2016):
        self.name, self.label, self._e = name, name.title(), earliest

    def _earliest(self):
        return self._e

    def _asset(self, season):
        return f"{self.name}/{self.name}_{season}.parquet"


def _state(week=4, season_type="regular", season="2026"):
    return {"season": season, "season_type": season_type, "week": week,
            "indicator": f"{season}:{season_type}:{week}"}


# -- state file --------------------------------------------------------------

def test_record_refresh_round_trips_through_the_file():
    rp.record_refresh("nflverse/snap_counts/2026", validators={"etag": '"a"'})
    rp.reset()                                  # force a re-read from disk
    entry = rp.get("nflverse/snap_counts/2026")
    assert entry["validators"] == {"etag": '"a"'}
    assert entry["status"] == "ok"
    assert entry["last_refreshed"] and entry["last_checked"]


def test_unrecorded_source_is_due_and_indicator_changed():
    assert rp.check_due("nflverse/x/2026")
    assert rp.indicator_changed("sleeper_stats/2026", "2026:regular:4")


def test_check_due_waits_for_the_interval(monkeypatch):
    monkeypatch.setattr(rp, "_now", lambda: 1000.0)
    rp.record_refresh("k")
    assert not rp.check_due("k")
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + rp.CHECK_INTERVAL + 1)
    assert rp.check_due("k")


def test_indicator_changed_compares_the_recorded_indicator():
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    assert not rp.indicator_changed("sleeper_stats/2026", "2026:regular:4")
    assert rp.indicator_changed("sleeper_stats/2026", "2026:regular:5")


def test_failed_source_is_in_cooldown_until_it_succeeds(monkeypatch):
    rp.mark_failed("k")
    assert rp.in_cooldown("k")
    rp.record_refresh("k")
    assert not rp.in_cooldown("k")


def test_current_state_parses_sleepers_indicator(monkeypatch):
    monkeypatch.setattr(rp, "sleeper_api", lambda path: {
        "league_season": "2026", "season_type": "regular", "week": 4})
    assert rp.current_state() == _state()


def test_current_state_is_none_when_sleeper_is_unreachable(monkeypatch):
    monkeypatch.setattr(rp, "sleeper_api", lambda path: None)
    assert rp.current_state() is None


# -- conditional HEAD ---------------------------------------------------------

class _Resp:
    def __init__(self, status, headers=None):
        self.status_code, self.headers = status, headers or {}


def test_head_release_304_is_unchanged(monkeypatch):
    seen = {}

    def fake_head(url, headers, timeout, allow_redirects):
        seen.update(headers)
        return _Resp(304)
    monkeypatch.setattr(nflref_api.requests, "head", fake_head)
    v = {"etag": '"a"', "last_modified": "Tue, 29 Sep 2026 11:01:26 GMT"}
    assert nflref_api.head_release("x/y.parquet", v) == ("unchanged", v)
    assert seen["If-None-Match"] == '"a"'
    assert seen["If-Modified-Since"] == v["last_modified"]


def test_head_release_200_with_new_etag_is_changed(monkeypatch):
    monkeypatch.setattr(nflref_api.requests, "head", lambda *a, **k: _Resp(
        200, {"ETag": '"b"', "Last-Modified": "now"}))
    verdict, v = nflref_api.head_release("x/y.parquet", {"etag": '"a"'})
    assert verdict == "changed" and v["etag"] == '"b"'


def test_head_release_200_with_same_etag_is_unchanged(monkeypatch):
    monkeypatch.setattr(nflref_api.requests, "head", lambda *a, **k: _Resp(
        200, {"ETag": '"a"'}))
    assert nflref_api.head_release("x/y.parquet", {"etag": '"a"'})[0] == "unchanged"


def test_head_release_with_no_recorded_validators_is_changed(monkeypatch):
    monkeypatch.setattr(nflref_api.requests, "head", lambda *a, **k: _Resp(
        200, {"ETag": '"a"'}))
    assert nflref_api.head_release("x/y.parquet")[0] == "changed"


def test_head_release_errors_degrade(monkeypatch):
    def boom(*a, **k):
        raise OSError("offline")
    monkeypatch.setattr(nflref_api.requests, "head", boom)
    assert nflref_api.head_release("x/y.parquet") == ("error", None)
    monkeypatch.setattr(nflref_api.requests, "head", lambda *a, **k: _Resp(404))
    assert nflref_api.head_release("x/y.parquet") == ("error", None)


# -- planning -----------------------------------------------------------------

def _plan(monkeypatch, state, datasets=None, head=None):
    monkeypatch.setattr(rp, "current_state", lambda: state)
    monkeypatch.setattr(refresher, "DATASETS",
                        datasets if datasets is not None else {})
    monkeypatch.setattr(refresher.nflref_api, "head_release",
                        head or (lambda asset, v=None: ("unchanged", v)))
    return refresher.plan()


def test_no_indicator_means_nothing_to_do(monkeypatch):
    assert _plan(monkeypatch, None) == ([], None)


def test_same_week_refreshes_nothing(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    items, _ = _plan(monkeypatch, _state(week=4))
    assert items == []


def test_new_week_refreshes_every_completed_sleeper_week(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    items, _ = _plan(monkeypatch, _state(week=5))
    assert [(i.kind, i.week) for i in items] == [("sleeper", w) for w in (1, 2, 3, 4)]


def test_unrecorded_sleeper_season_is_caught_up(monkeypatch):
    items, _ = _plan(monkeypatch, _state(week=4))
    assert [i.week for i in items] == [1, 2, 3]


def test_postseason_refreshes_all_weeks(monkeypatch):
    items, _ = _plan(monkeypatch, _state(week=1, season_type="post"))
    assert [i.week for i in items] == list(range(1, 19))


def test_offseason_plans_no_sleeper_weeks(monkeypatch):
    items, _ = _plan(monkeypatch, _state(week=0, season_type="off"))
    assert items == []


def test_unchanged_nflverse_dataset_downloads_nothing_but_is_stamped(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    ds = FakeDataset("snap_counts")
    rp.record_refresh("nflverse/snap_counts/2026", validators={"etag": '"a"'})
    rp._state["sources"]["nflverse/snap_counts/2026"]["last_checked"] = 0   # due
    items, _ = _plan(monkeypatch, _state(),
                     {"snap_counts": ds},
                     head=lambda asset, v=None: ("unchanged", v))
    assert items == []
    assert rp.get("nflverse/snap_counts/2026")["last_checked"] > 0


def test_changed_nflverse_dataset_is_planned_with_new_validators(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    ds = FakeDataset("snap_counts")
    items, _ = _plan(monkeypatch, _state(), {"snap_counts": ds},
                     head=lambda asset, v=None: ("changed", {"etag": '"new"'}))
    assert [(i.kind, i.dataset, i.validators) for i in items] == [
        ("nflverse", ds, {"etag": '"new"'})]


def test_nflverse_check_is_skipped_until_due(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    rp.record_refresh("nflverse/snap_counts/2026", validators={"etag": '"a"'})
    calls = []
    items, _ = _plan(monkeypatch, _state(), {"snap_counts": FakeDataset("snap_counts")},
                     head=lambda asset, v=None: calls.append(asset) or ("changed", {}))
    assert items == [] and calls == []


def test_dataset_before_its_earliest_season_is_skipped(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    items, _ = _plan(monkeypatch, _state(),
                     {"old": FakeDataset("old", earliest=2030)},
                     head=lambda asset, v=None: ("changed", {}))
    assert items == []


def test_route_participation_is_never_polled(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    calls = []
    _plan(monkeypatch, _state(), {"route_participation": FakeDataset("route_participation")},
          head=lambda asset, v=None: calls.append(asset) or ("changed", {}))
    assert calls == []


def test_failed_head_starts_a_cooldown(monkeypatch):
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    items, _ = _plan(monkeypatch, _state(), {"snap_counts": FakeDataset("snap_counts")},
                     head=lambda asset, v=None: ("error", None))
    assert items == [] and rp.in_cooldown("nflverse/snap_counts/2026")


def test_past_season_gets_one_final_refresh(monkeypatch):
    rp.record_refresh("sleeper_stats/2025", indicator="2025:regular:17")
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    items, _ = _plan(monkeypatch, _state(week=4))
    assert [(i.season, i.week, i.final) for i in items] == [
        ("2025", w, True) for w in range(1, 19)]


def test_a_final_season_is_left_alone(monkeypatch):
    rp.record_refresh("sleeper_stats/2025", indicator="x", status="final")
    rp.record_refresh("sleeper_stats/2026", indicator="2026:regular:4")
    assert _plan(monkeypatch, _state(week=4))[0] == []


# -- running ------------------------------------------------------------------

def _sleeper_items(season="2026", weeks=(1, 2, 3)):
    return [refresher.Item("sleeper", f"sleeper_stats/{season}", season,
                           f"Sleeper week {w}", week=w) for w in weeks]


def test_run_records_the_season_only_when_every_week_succeeds(monkeypatch):
    monkeypatch.setattr(refresher, "_do_sleeper", lambda item: True)
    refresher.run(_sleeper_items(), _state())
    assert rp.get("sleeper_stats/2026")["indicator"] == "2026:regular:4"
    s = refresher.status()
    assert (s["phase"], s["done"], s["total"], s["failed"]) == ("done", 3, 3, 0)


def test_run_leaves_a_season_unrecorded_when_a_week_fails(monkeypatch):
    monkeypatch.setattr(refresher, "_do_sleeper", lambda item: item.week != 2)
    refresher.run(_sleeper_items(), _state())
    assert rp.get("sleeper_stats/2026") is None
    assert rp.in_cooldown("sleeper_stats/2026")
    assert refresher.status()["failed"] == 1


def test_run_records_an_nflverse_dataset_with_its_validators(monkeypatch):
    monkeypatch.setattr(refresher, "_do_nflverse", lambda item: True)
    item = refresher.Item("nflverse", "nflverse/snap_counts/2026", "2026", "Snap",
                          dataset=FakeDataset("snap_counts"),
                          validators={"etag": '"n"'})
    refresher.run([item], _state())
    assert rp.get("nflverse/snap_counts/2026")["validators"] == {"etag": '"n"'}


def test_run_marks_a_final_refresh_final(monkeypatch):
    monkeypatch.setattr(refresher, "_do_sleeper", lambda item: True)
    items = [refresher.Item("sleeper", "sleeper_stats/2025", "2025", "w", week=1,
                            final=True)]
    refresher.run(items, _state())
    assert rp.get("sleeper_stats/2025")["status"] == "final"


def test_run_survives_a_download_that_raises(monkeypatch):
    def boom(item):
        raise RuntimeError("network")
    monkeypatch.setattr(refresher, "_do_sleeper", boom)
    refresher.run(_sleeper_items(weeks=(1,)), _state())
    assert refresher.status()["phase"] == "done"
    assert refresher.status()["failed"] == 1


def test_maybe_start_respects_the_kill_switch(monkeypatch):
    monkeypatch.setenv("DISABLE_REFRESH", "1")
    assert refresher.maybe_start() is False


def test_maybe_start_plans_at_most_once_a_minute(monkeypatch):
    monkeypatch.delenv("DISABLE_REFRESH", raising=False)
    started = []

    class _T:
        def __init__(self, target, name, daemon):
            started.append(name)

        def start(self):
            pass
    monkeypatch.setattr(refresher.threading, "Thread", _T)
    assert refresher.maybe_start() is True
    assert refresher.maybe_start() is False          # one already running
    refresher._release()
    assert refresher.maybe_start() is False          # within the plan gap
    assert started == ["data-refresh"]


def test_atomic_writers_leave_no_temp_file(tmp_path, monkeypatch):
    import pandas as pd
    from webapp.sources.nflref import cache
    monkeypatch.setattr(cache, "_NFLVERSE_DIR", tmp_path)
    cache.save("snap_counts", "2026", pd.DataFrame({"a": [1]}))
    assert [p.name for p in (tmp_path / "snap_counts").iterdir()] == ["2026.parquet"]


# -- ADP sources (silent) -----------------------------------------------------

def _adp_plan(monkeypatch, state, probe=None):
    calls = []

    def fake_probe(url, params=None, validators=None):
        calls.append(url)
        return probe(url, params, validators) if probe else ("changed", {"etag": '"e"'})
    monkeypatch.setattr(refresher.adp_api, "probe_unchanged", fake_probe)
    return refresher.plan_adp(state), calls


def _adp_keys(items):
    return sorted(i.key for i in items)


def test_adp_plans_every_current_season_source_when_never_recorded(monkeypatch):
    items, _ = _adp_plan(monkeypatch, _state(week=0, season_type="pre"))
    assert _adp_keys(items) == sorted([
        "adp/sleeper/2026", "adp/cbs/2026", "adp/yahoo/2026", "adp/espn/2026",
        "adp/ffc/std/2026", "adp/ffc/half_ppr/2026", "adp/ffc/ppr/2026",
        "adp/ffc/2qb/2026", "adp/rotowire/ppr/2026", "adp/rotowire/std/2026"])


def test_adp_only_probes_sources_that_give_validators(monkeypatch):
    _, calls = _adp_plan(monkeypatch, _state(week=0, season_type="pre"))
    # sleeper + cbs once each, ffc four formats; yahoo/espn/rotowire have none.
    assert len(calls) == 6
    assert any("api.sleeper.com" in c for c in calls)
    assert any("cbssports" in c for c in calls)
    assert sum("fantasyfootballcalculator" in c for c in calls) == 4


def test_adp_unchanged_probe_is_stamped_not_downloaded(monkeypatch):
    items, _ = _adp_plan(monkeypatch, _state(week=0, season_type="pre"),
                         probe=lambda u, p, v: ("unchanged", v))
    assert "adp/sleeper/2026" not in _adp_keys(items)
    assert rp.get("adp/sleeper/2026")["last_checked"] > 0


def test_adp_waits_a_day_in_the_preseason(monkeypatch):
    monkeypatch.setattr(rp, "_now", lambda: 1000.0)
    for key in ("adp/sleeper/2026",):
        rp.record_refresh(key, validators={"etag": '"e"'})
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + 3600)
    items, calls = _adp_plan(monkeypatch, _state(week=0, season_type="pre"))
    assert "adp/sleeper/2026" not in _adp_keys(items)
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + 86400 + 1)
    items, _ = _adp_plan(monkeypatch, _state(week=0, season_type="pre"))
    assert "adp/sleeper/2026" in _adp_keys(items)


def test_adp_slows_to_weekly_once_the_season_is_underway(monkeypatch):
    monkeypatch.setattr(rp, "_now", lambda: 1000.0)
    rp.record_refresh("adp/sleeper/2026", validators={"etag": '"e"'})
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + 2 * 86400)
    items, _ = _adp_plan(monkeypatch, _state(week=4))
    assert "adp/sleeper/2026" not in _adp_keys(items)
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + 8 * 86400)
    items, _ = _adp_plan(monkeypatch, _state(week=4))
    assert "adp/sleeper/2026" in _adp_keys(items)


def test_adp_espn_is_always_weekly(monkeypatch):
    monkeypatch.setattr(rp, "_now", lambda: 1000.0)
    rp.record_refresh("adp/espn/2026")
    monkeypatch.setattr(rp, "_now", lambda: 1000.0 + 2 * 86400)
    items, _ = _adp_plan(monkeypatch, _state(week=0, season_type="pre"))
    assert "adp/espn/2026" not in _adp_keys(items)


def test_adp_failed_probe_starts_a_cooldown(monkeypatch):
    items, _ = _adp_plan(monkeypatch, _state(week=0, season_type="pre"),
                         probe=lambda u, p, v: ("error", None))
    assert "adp/sleeper/2026" not in _adp_keys(items)
    assert rp.in_cooldown("adp/sleeper/2026")


def test_run_adp_is_silent_and_records_successes(monkeypatch):
    monkeypatch.setattr(refresher, "_do_adp", lambda item: item.dataset != "cbs")
    items = [refresher.Item("adp", "adp/sleeper/2026", "2026", "s", dataset="sleeper",
                            fmt="ppr", validators={"etag": '"x"'}),
             refresher.Item("adp", "adp/cbs/2026", "2026", "c", dataset="cbs", fmt="ppr")]
    before = refresher.status()
    refresher.run_adp(items)
    assert refresher.status() == before                      # banner untouched
    assert rp.get("adp/sleeper/2026")["validators"] == {"etag": '"x"'}
    assert rp.get("adp/cbs/2026") is None and rp.in_cooldown("adp/cbs/2026")


def test_probe_unchanged_maps_status_codes(monkeypatch):
    from webapp.sources.ffadp import api as adp_api

    class R:
        def __init__(self, code, headers=None):
            self.status_code, self.headers = code, headers or {}

        def close(self):
            pass
    monkeypatch.setattr(adp_api.requests, "get", lambda *a, **k: R(304))
    v = {"etag": '"a"'}
    assert adp_api.probe_unchanged("u", None, v) == ("unchanged", v)
    monkeypatch.setattr(adp_api.requests, "get",
                        lambda *a, **k: R(200, {"ETag": '"b"'}))
    assert adp_api.probe_unchanged("u", None, v)[0] == "changed"
    monkeypatch.setattr(adp_api.requests, "get", lambda *a, **k: R(500))
    assert adp_api.probe_unchanged("u")[0] == "error"
