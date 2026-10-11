"""ADP raw layer: each provider's response is kept exactly as received.

Network-free: requests.get is replaced inside the api modules and the ADP
folder is redirected to tmp, so nothing touches data/sources/adp/.
"""
from __future__ import annotations

import json

import pytest

from sleepermetrics import api as sapi
from sleepermetrics import rawfile
from webapp.sources.ffadp import api, cache


class _Resp:
    def __init__(self, body: bytes):
        self.content = body
        self.text = body.decode("utf-8")

    def raise_for_status(self):
        pass

    def json(self):
        return json.loads(self.content)


@pytest.fixture(autouse=True)
def _tmp_adp(monkeypatch, tmp_path):
    monkeypatch.setattr(cache, "_ADP_DIR", tmp_path / "adp")
    monkeypatch.setattr(cache, "on_render", lambda: False)
    cache._mem.clear()
    yield tmp_path / "adp"


def _serve(monkeypatch, body: bytes):
    monkeypatch.setattr(api.requests, "get", lambda *a, **k: _Resp(body))


def test_gzip_helper_round_trips_the_exact_bytes(tmp_path):
    p = tmp_path / "x" / "raw_1.json.gz"
    data = b'{"a": [1, 2,   3]}\n'                      # odd spacing must survive
    assert rawfile.save_gz(p, data) is True
    assert rawfile.load_gz(p) == data
    assert rawfile.save_gz(tmp_path / "e.gz", b"") is False   # nothing to keep
    assert rawfile.load_gz(tmp_path / "missing.gz") is None


def test_espn_keeps_the_complete_response(monkeypatch, _tmp_adp):
    body = json.dumps([{"id": 1, "fullName": "A B", "extra": {"deep": [1, 2, 3]}}]).encode()
    _serve(monkeypatch, body)
    assert api.espn_players(2024) == json.loads(body)
    assert cache.load_raw("espn", 2024) == body                  # byte for byte
    assert cache.raw_path("espn", 2024) == _tmp_adp / "espn" / "raw" / "raw_2024.json.gz"


def test_ffc_keeps_raw_per_format(monkeypatch):
    body = json.dumps({"status": "Success", "players": [{"name": "X", "adp": 1.0, "unused": 5}]}).encode()
    _serve(monkeypatch, body)
    api.ffc_adp(2024, "half_ppr")
    api.ffc_adp(2024, "ppr")
    assert cache.load_raw("ffc", 2024, variant="half_ppr") == body
    assert cache.load_raw("ffc", 2024, variant="ppr") == body


def test_yahoo_keeps_every_page(monkeypatch):
    page = {"fantasy_content": {"game": {"players": [
        {"player": {"player_id": "1", "draft_analysis": {"preseason_average_pick": "1.0"}}}]}}}
    _serve(monkeypatch, json.dumps(page).encode())
    api.yahoo_adp(2024)
    kept = json.loads(cache.load_raw("yahoo", 2024))
    assert isinstance(kept, list) and kept and kept[0] == page


def test_cbs_and_rotowire_keep_the_current_season(monkeypatch):
    monkeypatch.setattr(cache, "current_season", lambda: "2031")
    _serve(monkeypatch, b"<html>table</html>")
    api.cbs_adp()
    assert cache.load_raw("cbs", "2031", ext="html") == b"<html>table</html>"
    rows = json.dumps([{"firstname": "A"}]).encode()
    _serve(monkeypatch, rows)
    api.rotowire_adp("Standard")
    assert cache.load_raw("rotowire", "2031", variant="Standard") == rows
    assert cache.load_raw("rotowire", "2031", variant="PPR") is None


def test_sleeper_adp_keeps_raw(monkeypatch, tmp_path):
    import repo_paths
    monkeypatch.setattr(repo_paths, "SOURCES_DIR", tmp_path)
    monkeypatch.setattr(repo_paths, "on_render", lambda: False)
    body = json.dumps([{"player_id": "1", "stats": {"adp_ppr": 3.0}, "more": 1}]).encode()

    class _S:
        def get(self, *a, **k):
            return _Resp(body)
    monkeypatch.setattr(sapi, "_get_session", lambda: _S())
    assert sapi.sleeper_adp(2025) == json.loads(body)
    assert rawfile.load_gz(tmp_path / "adp" / "sleeper" / "raw" / "raw_2025.json.gz") == body


def test_render_writes_no_raw_files(monkeypatch, _tmp_adp):
    monkeypatch.setattr(cache, "on_render", lambda: True)
    _serve(monkeypatch, json.dumps([{"id": 1}]).encode())
    api.espn_players(2024)
    assert not (_tmp_adp / "espn").exists()


def test_a_failed_download_stores_nothing(monkeypatch, _tmp_adp):
    def boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(api.requests, "get", boom)
    with pytest.raises(RuntimeError):
        api.espn_players(2024)
    assert cache.load_raw("espn", 2024) is None


def test_raw_names_are_not_read_as_season_snapshots():
    """The season scanners take four-digit stems; raw_<year>.json.gz must not
    look like one."""
    p = cache.raw_path("espn", 2024)
    stem = p.stem.split("-")[0]                  # what refresh_data._seasons_in does
    assert not (stem.isdigit() and len(stem) == 4)


# --- a missing snapshot is rebuilt from the stored raw response, offline ---------

def _no_network(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network used")
    monkeypatch.setattr(api.requests, "get", boom)


def test_espn_rebuilds_its_snapshot_from_raw_without_the_network(monkeypatch, _tmp_adp):
    from webapp.sources.ffadp import espn
    body = json.dumps([{"id": 7, "fullName": "A B", "defaultPositionId": 2,
                        "ownership": {"averageDraftPosition": 3.4, "percentOwned": 98.0}}]).encode()
    cache.save_raw("espn", 2024, body)
    _no_network(monkeypatch)
    rows = espn.EspnAdp().fetch("2024")
    assert [r.name for r in rows] == ["A B"]
    assert cache.load("espn", "2024")                       # derived snapshot written


def test_espn_raw_that_trims_to_nothing_is_final_for_a_past_season(monkeypatch):
    from webapp.sources.ffadp import espn
    sentinel = json.dumps([{"id": 1, "fullName": "X", "defaultPositionId": 2,
                            "ownership": {"averageDraftPosition": 170.0}}]).encode()
    cache.save_raw("espn", 2019, sentinel)
    _no_network(monkeypatch)
    assert espn.EspnAdp().fetch("2019") == []
    assert cache.load("espn", "2019") == []                  # the "checked, empty" marker


def test_ffc_yahoo_rotowire_cbs_rebuild_from_raw_offline(monkeypatch):
    from webapp.sources.ffadp import cbs, ffc, rotowire, yahoo
    _no_network(monkeypatch)
    cache.save_raw("ffc", 2024, json.dumps(
        {"status": "Success", "players": [{"name": "Z", "position": "WR", "team": "AAA", "adp": 2.0}]}
    ).encode(), variant="ppr")
    assert [r.name for r in ffc.FfcAdp().fetch("2024", "ppr")] == ["Z"]

    page = {"fantasy_content": {"game": {"players": [{"player": {
        "player_id": "9", "name": {"full": "Y Y"}, "display_position": "RB",
        "editorial_team_abbr": "Det",
        "draft_analysis": {"preseason_average_pick": "4.0"}}}]}}}
    cache.save_raw("yahoo", 2024, json.dumps([page]).encode())
    assert [r.name for r in yahoo.YahooAdp().fetch("2024")] == ["Y Y"]

    cache.save_raw("rotowire", 2024, json.dumps([{
        "firstname": "R", "lastname": "W", "position": "QB", "team": "KC",
        "playerID": "5", "average": "7.0"}]).encode(), variant="PPR")
    assert rotowire._feed("2024", "PPR", False)

    html = ('<table class="TableBase"><tbody><tr class="TableBase-bodyTr">'
            '<td>1</td><td><span class="CellPlayerName--long"><a>C D</a></span>'
            '<span class="CellPlayerName-position">RB</span></td><td></td><td>1.5</td></tr></tbody></table>')
    cur = cache.current_season()
    cache.save_raw("cbs", cur, html.encode(), ext="html")
    # parsing a hand-made table is the parser's own job; what matters here is that
    # the stored HTML is handed to it and no network is used
    seen = []
    monkeypatch.setattr(cbs, "_parse", lambda text: seen.append(text) or [
        {"name": "C D", "position": "RB", "team": None, "adp": 1.5}])
    assert [r.name for r in cbs.CbsAdp().fetch(cur)] == ["C D"] and seen == [html]


def test_nothing_is_rebuilt_from_raw_on_render_or_on_reload(monkeypatch, _tmp_adp):
    from webapp.sources.ffadp import espn
    body = json.dumps([{"id": 7, "fullName": "A B", "defaultPositionId": 2,
                        "ownership": {"averageDraftPosition": 3.4, "percentOwned": 98.0}}]).encode()
    cache.save_raw("espn", 2024, body)
    monkeypatch.setattr(cache, "on_render", lambda: True)
    assert cache.from_raw("espn", 2024, lambda b: [1]) is None          # Render: never parsed
    monkeypatch.setattr(cache, "on_render", lambda: False)
    calls = []
    monkeypatch.setattr(espn.api, "espn_players", lambda s: calls.append(s) or json.loads(body))
    espn.EspnAdp().fetch("2024", reload=True)
    assert calls == ["2024"]                                             # reload goes live
