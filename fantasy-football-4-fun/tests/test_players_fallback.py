"""players(): a failed daily refresh falls back to the stored dump.  Network-free."""
import os
import pickle
import time

import pytest

from sleepermetrics import players as players_fn   # the function (shadows the module)
import sys

pm = sys.modules["sleepermetrics.players"]

RAW = {"1": {"full_name": "A One", "position": "RB", "team": "AAA", "gsis_id": "g1"}}


@pytest.fixture
def stale_dump(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_cache", None)
    p = tmp_path / "dump.pkl"
    p.write_bytes(pickle.dumps(RAW))
    old = time.time() - 3 * 86400
    os.utime(p, (old, old))
    yield p
    monkeypatch.setattr(pm, "_cache", None)


def _down(path):
    raise ConnectionError("down")


def test_a_failed_refresh_uses_the_stale_dump(stale_dump, monkeypatch):
    monkeypatch.setattr(pm, "sleeper_api", _down)
    with pytest.warns(UserWarning):
        df = players_fn(cache_path=str(stale_dump))
    assert list(df["player_name"]) == ["A One"]
    assert time.time() - stale_dump.stat().st_mtime > 86400      # not rewritten


def test_no_stored_dump_still_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(pm, "_cache", None)
    monkeypatch.setattr(pm, "sleeper_api", _down)
    with pytest.raises(ConnectionError):
        players_fn(cache_path=str(tmp_path / "missing.pkl"))


def test_an_explicit_refresh_still_raises(stale_dump, monkeypatch):
    monkeypatch.setattr(pm, "sleeper_api", _down)
    with pytest.raises(ConnectionError):
        players_fn(refresh=True, cache_path=str(stale_dump))


def test_a_successful_refresh_rewrites_the_dump(stale_dump, monkeypatch):
    fresh = {"2": {"full_name": "B Two", "position": "WR", "team": "BBB", "gsis_id": None}}
    monkeypatch.setattr(pm, "sleeper_api", lambda path: fresh)
    df = players_fn(cache_path=str(stale_dump))
    assert list(df["player_name"]) == ["B Two"]
    assert pickle.loads(stale_dump.read_bytes()) == fresh
