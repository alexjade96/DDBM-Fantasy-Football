"""Network-free tests for the cross-platform ADP layer (python/ffadp)."""
import ffadp
from ffadp import board, identity
from ffadp.base import AdpProvider, AdpRow


# --- identity ---------------------------------------------------------------

def _fake_dump():
    return {
        "100": {"full_name": "Ja'Marr Chase", "position": "WR", "team": "CIN",
                "espn_id": "4262921", "yahoo_id": "33379"},
        "200": {"full_name": "Bijan Robinson", "position": "RB", "team": "ATL",
                "espn_id": "4430807", "yahoo_id": "40120"},
        "DEF_SF": {"position": "DEF", "team": "SF"},
    }


def test_identity_resolves_by_cross_id(monkeypatch):
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    assert identity.resolve("espn", espn_id="4262921") == "100"
    assert identity.resolve("yahoo", yahoo_id="40120") == "200"
    identity.reset()


def test_identity_name_fallback(monkeypatch):
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    # No cross-id, but the normalised name+pos still hits.
    assert identity.resolve("x", name="Ja'Marr Chase", position="WR") == "100"
    assert identity.resolve("x", name="jamarr chase", position="WR") == "100"
    assert identity.resolve("x", name="Nobody Here", position="WR") is None
    identity.reset()


# --- board.combine -------------------------------------------------------

class _StubA(AdpProvider):
    name, label, formats = "a", "A", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return [
            AdpRow("a", "Ja'Marr Chase", "WR", "CIN", adp=1.4, overall_rank=1, sleeper_id="100"),
            AdpRow("a", "Bijan Robinson", "RB", "ATL", adp=2.6, overall_rank=2, sleeper_id="200"),
        ]


class _StubB(AdpProvider):
    name, label, formats = "b", "B", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return [
            AdpRow("b", "Bijan Robinson", "RB", "ATL", adp=1.9, overall_rank=1, sleeper_id="200"),
            AdpRow("b", "Ja'Marr Chase", "WR", "CIN", adp=3.1, overall_rank=2, sleeper_id="100"),
        ]


class _StubEmpty(AdpProvider):
    name, label, formats = "c", "C", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return []


def test_combine_merges_and_computes_spread(monkeypatch):
    monkeypatch.setattr(board, "PROVIDERS", [_StubA(), _StubB(), _StubEmpty()])
    monkeypatch.setattr(board, "_BY_NAME",
                        {p.name: p for p in board.PROVIDERS})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)

    b = board.combine("2025", scoring="half_ppr", pos="ALL")
    # empty source dropped from columns, kept in sources with ok=False
    assert b["columns"] == ["a", "b"]
    assert {s["name"]: s["ok"] for s in b["sources"]} == {"a": True, "b": True, "c": False}
    assert len(b["rows"]) == 2

    chase = next(r for r in b["rows"] if r["player"] == "Ja'Marr Chase")
    bijan = next(r for r in b["rows"] if r["player"] == "Bijan Robinson")
    # Chase: ranks 1 (a) and 2 (b) -> consensus 1.5, spread 1
    assert chase["rank"] == {"a": 1, "b": 2}
    assert chase["consensus"] == 1.5
    assert chase["spread"] == 1
    # Bijan: ranks 2 (a) and 1 (b) -> consensus 1.5, spread 1
    assert bijan["consensus"] == 1.5 and bijan["spread"] == 1
    # sorted by consensus asc; tie -> stable, both present
    assert {r["player"] for r in b["rows"]} == {"Ja'Marr Chase", "Bijan Robinson"}
    identity.reset()


def test_combine_position_filter(monkeypatch):
    monkeypatch.setattr(board, "PROVIDERS", [_StubA(), _StubB()])
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in board.PROVIDERS})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    b = board.combine("2025", pos="RB")
    assert [r["player"] for r in b["rows"]] == ["Bijan Robinson"]
    identity.reset()


def test_combine_all_sources_empty(monkeypatch):
    monkeypatch.setattr(board, "PROVIDERS", [_StubEmpty()])
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in board.PROVIDERS})
    b = board.combine("2099")
    assert b["columns"] == []
    assert b["rows"] == []


def test_sleeper_provider_degrades_offline(monkeypatch):
    # No committed snapshot + draft._fetch_adp_raw returns {} -> [].
    from sleepermetrics import draft
    from ffadp import sleeper as slp
    monkeypatch.setattr(slp, "_snapshot", lambda season: None)
    monkeypatch.setattr(draft, "_fetch_adp_raw", lambda season: {})
    assert slp.SleeperAdp().fetch("2099", "ppr") == []


def test_sleeper_provider_skips_prehistoric_years(monkeypatch):
    # A year before Sleeper's ADP history must not even call the endpoint
    # (a miss there writes an empty season/adp/<y>.json).
    from sleepermetrics import draft
    from ffadp.sleeper import SleeperAdp
    called = []
    monkeypatch.setattr(draft, "_fetch_adp_raw",
                        lambda season: called.append(season) or {})
    assert SleeperAdp().fetch("2015", "ppr") == []
    assert called == []


def test_sleeper_provider_snapshot_first(monkeypatch):
    # A committed snapshot is used as-is; the live endpoint is NOT hit.
    from sleepermetrics import draft
    from ffadp import sleeper as slp
    snap = {"100": {"player_name": "A", "position": "RB", "adp_ppr": 1.2},
            "200": {"player_name": "B", "position": "WR", "adp_ppr": 3.4}}
    monkeypatch.setattr(slp, "_snapshot", lambda season: dict(snap))
    called = []
    monkeypatch.setattr(draft, "_fetch_adp_raw",
                        lambda season: called.append(season) or {})
    rows = slp.SleeperAdp().fetch("2024", "ppr")
    assert [r.name for r in rows] == ["A", "B"] and called == []
    # reload bypasses the snapshot -> the endpoint IS hit.
    slp.SleeperAdp().fetch("2024", "ppr", reload=True)
    assert called == ["2024"]


def test_espn_provider_snapshot_first(monkeypatch):
    from ffadp import espn, cache
    cache.clear()
    hit = []
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False: (hit.append((sea, force)) or
                        [{"espn_id": "1", "name": "X", "position": "RB", "adp": 2.0}]))
    monkeypatch.setattr(espn.api, "espn_players",
                        lambda season: (_ for _ in ()).throw(AssertionError("live hit")))
    rows = espn.EspnAdp().fetch("2024", "ppr")
    assert len(rows) == 1 and hit == [("2024", False)]
    cache.clear()


# --- ESPN provider (fixture payload, no network) --------------------------

_ESPN_FIXTURE = [
    {"id": 3929630, "fullName": "Saquon Barkley", "defaultPositionId": 2,
     "ownership": {"averageDraftPosition": 3.4, "percentOwned": 98.0}},
    {"id": 4262921, "fullName": "Justin Jefferson", "defaultPositionId": 3,
     "ownership": {"averageDraftPosition": 9.0, "percentOwned": 100.0}},
    {"id": 999001, "fullName": "Deep Bench Guy", "defaultPositionId": 2,
     "ownership": {"averageDraftPosition": 170.0, "percentOwned": 0.0}},   # sentinel
    {"id": 999002, "fullName": "No ADP Guy", "defaultPositionId": 3,
     "ownership": {"averageDraftPosition": None, "percentOwned": 0.0}},
    {"id": 16, "fullName": "SF D/ST", "defaultPositionId": 16,
     "ownership": {"averageDraftPosition": 120.0, "percentOwned": 40.0}},
]


def test_espn_trim_filters_sentinel_and_maps_position():
    from ffadp import espn
    rows = espn._trim(_ESPN_FIXTURE)
    names = [r["name"] for r in rows]
    assert "Deep Bench Guy" not in names and "No ADP Guy" not in names
    assert names[0] == "Saquon Barkley"          # sorted by adp asc
    barkley = rows[0]
    assert barkley["position"] == "RB" and barkley["espn_id"] == "3929630"
    assert any(r["position"] == "DEF" for r in rows)


def test_espn_provider_uses_snapshot_when_fetch_fails(monkeypatch):
    from ffadp import espn, cache
    cache.clear()
    monkeypatch.setattr(espn.api, "espn_players",
                        lambda season: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(cache, "load", lambda src, sea: [
        {"espn_id": "3929630", "name": "Saquon Barkley", "position": "RB", "adp": 3.4},
    ])
    rows = espn.EspnAdp().fetch("2024", "ppr")
    assert len(rows) == 1 and rows[0].espn_id == "3929630" and rows[0].overall_rank == 1
    cache.clear()


def test_espn_provider_degrades_to_empty(monkeypatch):
    from ffadp import espn, cache
    cache.clear()
    monkeypatch.setattr(espn.api, "espn_players",
                        lambda season: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(cache, "load", lambda src, sea: None)
    assert espn.EspnAdp().fetch("2099", "ppr") == []
    cache.clear()


# --- FFC provider (fixture payload, no network) --------------------------

_FFC_FIXTURE = {
    "status": "Success",
    "meta": {"type": "PPR", "teams": 12},
    "players": [
        {"name": "Christian McCaffrey", "position": "RB", "team": "SF",
         "adp": 1.4},
        {"name": "Justin Jefferson", "position": "WR", "team": "MIN",
         "adp": 3.2},
        {"name": "Harrison Butker", "position": "PK", "team": "KC",
         "adp": 130.0},                       # PK -> K
        {"name": "Bad Row", "position": "RB", "team": "X", "adp": 0},   # dropped
    ],
}


def test_ffc_trim_normalises_and_sorts():
    from ffadp import ffc
    rows = ffc._trim(_FFC_FIXTURE["players"])
    assert [r["name"] for r in rows] == [
        "Christian McCaffrey", "Justin Jefferson", "Harrison Butker"]
    assert rows[2]["position"] == "K"          # PK normalised
    assert all(r["adp"] > 0 for r in rows)     # adp<=0 dropped


def test_ffc_provider_snapshot_first(monkeypatch):
    from ffadp import ffc, cache
    cache.clear()
    seen = []
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False, variant=None:
                        (seen.append((src, sea, variant)) or
                         [{"name": "A", "position": "RB", "team": "SF", "adp": 1.1}]))
    monkeypatch.setattr(ffc.api, "ffc_adp",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live hit")))
    rows = ffc.FfcAdp().fetch("2024", "ppr")
    assert len(rows) == 1 and seen == [("ffc", "2024", "ppr")]
    cache.clear()


def test_ffc_provider_format_fallback_and_skip(monkeypatch):
    from ffadp import ffc, cache
    cache.clear()
    # an unsupported ask still resolves via _format_or_fallback (all 4 listed)
    assert ffc.FfcAdp()._format_or_fallback("half_ppr") == "half_ppr"
    # a year before FFC history returns [] without any fetch
    monkeypatch.setattr(ffc.api, "ffc_adp",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    assert ffc.FfcAdp().fetch("2008", "ppr") == []
    cache.clear()


def test_ffc_provider_degrades_to_empty(monkeypatch):
    from ffadp import ffc, cache
    cache.clear()
    monkeypatch.setattr(ffc.api, "ffc_adp",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False, variant=None: None)
    assert ffc.FfcAdp().fetch("2024", "ppr") == []
    cache.clear()


# --- MFL provider (fixture payloads, no network) ------------------------

def test_mfl_flip_name_and_rows():
    from ffadp import mfl
    assert mfl._flip_name("McCaffrey, Christian") == "Christian McCaffrey"
    assert mfl._flip_name("Bills, Buffalo") == "Buffalo Bills"
    adp = [{"id": "1", "averagePick": "2.8"},
           {"id": "2", "averagePick": "1.5"},
           {"id": "3", "averagePick": "9.0"},   # a team-slot pos -> dropped
           {"id": "4", "averagePick": "0"}]     # adp<=0 -> dropped
    players = {
        "1": {"name": "McCaffrey, Christian", "position": "RB", "team": "SFO"},
        "2": {"name": "Taylor, Jonathan", "position": "RB", "team": "IND"},
        "3": {"name": "Bills, Buffalo", "position": "TMWR", "team": "BUF"},
        "4": {"name": "Nobody, Zero", "position": "WR", "team": "FA"},
    }
    rows = mfl._rows(adp, players)
    assert [r["name"] for r in rows] == ["Jonathan Taylor", "Christian McCaffrey"]
    assert rows[0]["adp"] == 1.5 and rows[0]["mfl_id"] == "2"


def test_mfl_provider_snapshot_first(monkeypatch):
    from ffadp import mfl, cache
    cache.clear()
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False, variant=None:
                        [{"mfl_id": "1", "name": "A", "position": "RB",
                          "team": "SF", "adp": 1.2}])
    monkeypatch.setattr(mfl.api, "mfl_adp",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live hit")))
    monkeypatch.setattr(mfl.api, "mfl_players",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("live hit")))
    rows = mfl.MflAdp().fetch("2024", "ppr")
    assert len(rows) == 1 and rows[0].extra["mfl_id"] == "1"
    cache.clear()


def test_mfl_provider_std_maps_to_non_ppr(monkeypatch):
    from ffadp import mfl, cache
    cache.clear()
    got = {}
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False, variant=None: None)
    monkeypatch.setattr(mfl.api, "mfl_players", lambda season: {
        "1": {"name": "Doe, John", "position": "RB", "team": "SF"}})
    monkeypatch.setattr(mfl.api, "mfl_adp",
                        lambda season, is_ppr=1: got.update(is_ppr=is_ppr) or
                        [{"id": "1", "averagePick": "3.0"}])
    mfl.MflAdp().fetch("2024", "std")
    assert got["is_ppr"] == 0
    cache.clear()


def test_mfl_provider_degrades_to_empty(monkeypatch):
    from ffadp import mfl, cache
    cache.clear()
    monkeypatch.setattr(mfl.api, "mfl_players",
                        lambda season: (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(cache, "load",
                        lambda src, sea, force=False, variant=None: None)
    assert mfl.MflAdp().fetch("2024", "ppr") == []
    cache.clear()


# --- RotoWire fan-out (fixture feed, no network) -----------------------

_RW_FIXTURE = [
    {"firstname": "Jahmyr", "lastname": "Gibbs", "position": "RB",
     "team": "DET", "playerID": "16808",
     "average": "1.6", "yahooppr": "1.3", "nffc12ppr": "1.4",
     "mfl12standard": "1.6", "ffpcoverall": "1.5", "underdoghalfppr": "1.0"},
    {"firstname": "Ja'Marr", "lastname": "Chase", "position": "WR",
     "team": "CIN", "playerID": "2799",
     "average": "3.8", "yahooppr": "3.5", "nffc12ppr": "3.2",
     "mfl12standard": "-", "ffpcoverall": "3.6", "underdoghalfppr": "3.1"},
    {"firstname": "Some", "lastname": "Linebacker", "position": "LB",
     "team": "KC", "playerID": "9", "average": "40.0"},      # IDP -> dropped
    {"firstname": "No", "lastname": "Data", "position": "WR",
     "team": "FA", "playerID": "8",
     "average": "", "yahooppr": "-", "ffpcoverall": "999.0"},  # all sentinel
]


def test_rotowire_trim_drops_idp_and_sentinels():
    from ffadp import rotowire
    rows = rotowire._trim(_RW_FIXTURE)
    assert [r["name"] for r in rows] == ["Jahmyr Gibbs", "Ja'Marr Chase"]
    assert rows[0]["position"] == "RB" and rows[0]["yahooppr"] == 1.3
    assert rows[1]["mfl12standard"] is None       # "-" sentinel


def test_rotowire_columns_fan_out(monkeypatch):
    from ffadp import rotowire
    rotowire._clear_feed_cache()
    monkeypatch.setattr(rotowire.api, "rotowire_adp", lambda slug="PPR": _RW_FIXTURE)
    monkeypatch.setattr(rotowire.cache, "load",
                        lambda *a, **k: None)   # force the (patched) live path
    monkeypatch.setattr(rotowire.cache, "save", lambda *a, **k: None)
    # each source slices its own column
    rw = rotowire.RotowireAdp().fetch("2026", "ppr")
    yh = rotowire.YahooAdp().fetch("2026", "ppr")
    nf = rotowire.NffcAdp().fetch("2026", "ppr")
    ud = rotowire.UnderdogAdp().fetch("2026", "ppr")
    assert [r.name for r in rw] == ["Jahmyr Gibbs", "Ja'Marr Chase"]
    assert rw[0].adp == 1.6 and rw[0].overall_rank == 1
    assert [r.adp for r in yh] == [1.3, 3.5]
    assert [r.adp for r in nf] == [1.4, 3.2]
    assert [r.adp for r in ud] == [1.0, 3.1]
    rotowire._clear_feed_cache()


def test_rotowire_one_fetch_feeds_all_columns(monkeypatch):
    from ffadp import rotowire
    rotowire._clear_feed_cache()
    calls = []
    monkeypatch.setattr(rotowire.api, "rotowire_adp",
                        lambda slug="PPR": calls.append(slug) or _RW_FIXTURE)
    monkeypatch.setattr(rotowire.cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(rotowire.cache, "save", lambda *a, **k: None)
    for cls in (rotowire.RotowireAdp, rotowire.NffcAdp, rotowire.FfpcAdp,
                rotowire.UnderdogAdp, rotowire.YahooAdp):
        cls().fetch("2026", "ppr")
    assert calls == ["PPR"]          # one HTTP call backs all five columns
    rotowire._clear_feed_cache()


def test_rotowire_std_slug_and_yahoo_ppr_only(monkeypatch):
    from ffadp import rotowire
    rotowire._clear_feed_cache()
    seen = []
    monkeypatch.setattr(rotowire.api, "rotowire_adp",
                        lambda slug="PPR": seen.append(slug) or _RW_FIXTURE)
    monkeypatch.setattr(rotowire.cache, "load", lambda *a, **k: None)
    monkeypatch.setattr(rotowire.cache, "save", lambda *a, **k: None)
    # NFFC in Standard maps to the mfl12standard column
    nf = rotowire.NffcAdp().fetch("2026", "std")
    assert seen == ["Standard"]
    assert [r.adp for r in nf] == [1.6]        # only Gibbs has mfl12standard
    # Yahoo publishes one ADP; a Standard ask still shows its yahooppr number
    yh = rotowire.YahooAdp().fetch("2026", "std")
    assert [r.adp for r in yh] == [1.3, 3.5]
    rotowire._clear_feed_cache()


def test_rotowire_predates_returns_empty(monkeypatch):
    from ffadp import rotowire
    monkeypatch.setattr(rotowire.api, "rotowire_adp",
                        lambda slug="PPR": (_ for _ in ()).throw(AssertionError("no call")))
    # a year before the feed's (current-season) EARLIEST
    assert rotowire.RotowireAdp().fetch(str(rotowire.EARLIEST - 1), "ppr") == []


def test_rotowire_degrades_to_empty(monkeypatch):
    from ffadp import rotowire
    rotowire._clear_feed_cache()
    monkeypatch.setattr(rotowire.api, "rotowire_adp",
                        lambda slug="PPR": (_ for _ in ()).throw(RuntimeError("no net")))
    monkeypatch.setattr(rotowire.cache, "load", lambda *a, **k: None)
    assert rotowire.RotowireAdp().fetch(str(rotowire.EARLIEST), "ppr") == []
    rotowire._clear_feed_cache()


def test_rotowire_derived_columns_never_write_their_own_snapshot(monkeypatch):
    # The Yahoo / NFFC / FFPC / Underdog columns are views over the one
    # "rotowire" snapshot; none may read or write a snapshot keyed on its own
    # source name (which could collide with a future first-party provider).
    from ffadp import rotowire
    rotowire._clear_feed_cache()
    seen_names = []
    monkeypatch.setattr(rotowire.cache, "load",
                        lambda src, *a, **k: seen_names.append(("load", src)) or None)
    monkeypatch.setattr(rotowire.cache, "save",
                        lambda src, *a, **k: seen_names.append(("save", src)))
    monkeypatch.setattr(rotowire.api, "rotowire_adp", lambda slug="PPR": _RW_FIXTURE)
    for cls in (rotowire.YahooAdp, rotowire.NffcAdp, rotowire.FfpcAdp,
                rotowire.UnderdogAdp, rotowire.RotowireAdp):
        cls().fetch("2026", "ppr")
    assert {src for _, src in seen_names} == {"rotowire"}
    rotowire._clear_feed_cache()


def test_board_registers_rotowire_family():
    from ffadp import board
    names = [p.name for p in board.PROVIDERS]
    for n in ("rotowire", "nffc", "ffpc", "underdog", "yahoo"):
        assert n in names
    # all five are current-season-only
    assert board.FIRST_SEASON["nffc"] == board.FIRST_SEASON["yahoo"]
    assert board.FIRST_SEASON["fantasypros"] is None


# --- source grouping --------------------------------------------------------

def test_every_provider_has_a_valid_group():
    from ffadp import board
    from ffadp.base import GROUP_ORDER
    for p in board.PROVIDERS:
        assert getattr(p, "group", None) in GROUP_ORDER, p.name


def test_expected_group_assignments():
    from ffadp import board
    g = {p.name: p.group for p in board.PROVIDERS}
    assert g["sleeper"] == g["espn"] == g["yahoo"] == "apps"
    assert g["mfl"] == g["nffc"] == g["ffpc"] == g["underdog"] == "highstakes"
    assert g["ffc"] == g["rotowire"] == g["fantasypros"] == "analyst"


class _AppStub(AdpProvider):
    name, label, group, formats = "app1", "App1", "apps", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return [AdpRow("app1", "Ja'Marr Chase", "WR", "CIN", adp=1.0,
                       overall_rank=1, sleeper_id="100")]


class _AnalystStub(AdpProvider):
    name, label, group, formats = "an1", "An1", "analyst", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return [AdpRow("an1", "Ja'Marr Chase", "WR", "CIN", adp=1.2,
                       overall_rank=1, sleeper_id="100")]


class _HighStakesStub(AdpProvider):
    name, label, group, formats = "hs1", "Hs1", "highstakes", ("half_ppr",)
    def fetch(self, season, scoring="half_ppr"):
        return [AdpRow("hs1", "Ja'Marr Chase", "WR", "CIN", adp=1.1,
                       overall_rank=1, sleeper_id="100")]


def test_combine_orders_columns_by_group_and_reports_groups(monkeypatch):
    # Register out of group order; combine() must still emit
    # apps -> highstakes -> analyst.
    provs = [_AnalystStub(), _AppStub(), _HighStakesStub()]
    monkeypatch.setattr(board, "PROVIDERS", provs)
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in provs})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)

    b = board.combine("2026", scoring="half_ppr")
    assert b["columns"] == ["app1", "hs1", "an1"]
    assert [g["key"] for g in b["groups"]] == ["apps", "highstakes", "analyst"]
    assert b["groups"][0]["columns"] == ["app1"]
    assert b["groups"][1]["label"] == "High-stakes & best-ball"
    # sources carry their group too
    assert {s["name"]: s["group"] for s in b["sources"]} == {
        "app1": "apps", "hs1": "highstakes", "an1": "analyst"}
    identity.reset()


def test_combine_groups_omits_empty_group(monkeypatch):
    provs = [_AppStub(), _AnalystStub()]     # no highstakes source
    monkeypatch.setattr(board, "PROVIDERS", provs)
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in provs})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    b = board.combine("2026", scoring="half_ppr")
    assert [g["key"] for g in b["groups"]] == ["apps", "analyst"]
    identity.reset()


def test_to_frame_follows_grouped_column_order(monkeypatch):
    provs = [_AnalystStub(), _AppStub(), _HighStakesStub()]
    monkeypatch.setattr(board, "PROVIDERS", provs)
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in provs})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    df = board.to_frame(board.combine("2026", scoring="half_ppr"))
    cols = list(df.columns)
    # App1 ADP appears before Hs1 ADP before An1 ADP
    assert cols.index("App1 ADP") < cols.index("Hs1 ADP") < cols.index("An1 ADP")
    identity.reset()


def test_combine_tags_source_coverage(monkeypatch):
    # ESPN present for a year, Sleeper predates it -> Sleeper column dropped
    # with a "from <year>" note; ESPN column kept.
    from ffadp import board, espn, identity

    class _EspnStub(board.EspnAdp):
        def fetch(self, season, scoring="half_ppr"):
            return [AdpRow("espn", "Chris Johnson", "RB", "TEN", adp=1.5,
                           overall_rank=1, espn_id="e1")]

    monkeypatch.setattr(board, "PROVIDERS", [board.SleeperAdp(), _EspnStub()])
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in board.PROVIDERS})
    monkeypatch.setattr(board, "FIRST_SEASON", {"sleeper": 2020, "espn": 2004})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", lambda: {})
    b = board.combine("2010", scoring="ppr", pos="ALL")
    assert b["columns"] == ["espn"]
    sl = next(s for s in b["sources"] if s["name"] == "sleeper")
    assert sl["ok"] is False and sl["why"] == "from 2020"
    identity.reset()


def test_to_frame_shape(monkeypatch):
    monkeypatch.setattr(board, "PROVIDERS", [_StubA(), _StubB()])
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in board.PROVIDERS})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)
    df = board.to_frame(board.combine("2025"))
    # Column order mirrors the table: rank, player, position, team, consensus,
    # then per-source ADP + rank (labelled), spread last.
    cols = list(df.columns)
    assert cols[:5] == ["rank", "player", "position", "team", "consensus"]
    assert cols[-1] == "spread"
    assert "A ADP" in cols and "A rank" in cols and "B ADP" in cols
    assert len(df) == 2 and df.iloc[0]["rank"] == 1
    identity.reset()


# --- export routes --------------------------------------------------------

def _mini_board(monkeypatch):
    monkeypatch.setattr(board, "PROVIDERS", [_StubA(), _StubB()])
    monkeypatch.setattr(board, "_BY_NAME", {p.name: p for p in board.PROVIDERS})
    identity.reset()
    monkeypatch.setattr(identity, "_raw_players", _fake_dump)


def test_export_csv_route(monkeypatch):
    _mini_board(monkeypatch)
    from webapp import app
    r = app.adp_export_csv(season="2025", scoring="half_ppr", pos="ALL")
    assert r.status_code == 200 and r.media_type == "text/csv"
    assert 'attachment; filename="adp-2025-half_ppr.csv"' in r.headers["content-disposition"]
    body = r.body.decode()
    assert body.splitlines()[0].startswith("rank,player,position,team,consensus")
    assert "Ja'Marr Chase" in body
    identity.reset()


def test_export_xlsx_route(monkeypatch):
    _mini_board(monkeypatch)
    from webapp import app
    r = app.adp_export_xlsx(season="2025", scoring="ppr", pos="RB")
    assert r.status_code == 200
    assert r.media_type.endswith("spreadsheetml.sheet")
    assert 'filename="adp-2025-ppr-rb.xlsx"' in r.headers["content-disposition"]
    import io
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(r.body))
    assert "ADP" in wb.sheetnames
    assert [c.value for c in wb["ADP"][1]][:4] == ["rank", "player", "position", "team"]
    identity.reset()
