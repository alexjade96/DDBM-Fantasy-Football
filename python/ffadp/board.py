"""Combine several sources' ADP into one comparison board."""
from __future__ import annotations

import pandas as pd

from . import identity
from .base import GROUP_LABEL, GROUP_ORDER, GROUPS, AdpProvider
from .espn import EspnAdp
from .fantasypros import FantasyProsAdp
from .ffc import FfcAdp
from .rotowire import RotowireAdp
from .sleeper import SleeperAdp
from .yahoo import YahooAdp

# The source registry, in display order. TO ADD A SOURCE: write a module with
# an AdpProvider subclass (a `name`, `label`, `formats` tuple, an `EARLIEST`
# year -- module-level, or a class attribute when one module backs several
# sources -- and a `fetch(season, scoring, reload=False)` that snapshots via
# ffadp.cache and degrades to []), then add it here. Everything else (id
# keying, merge, consensus/spread, the season range, the coverage notes,
# CSV/Excel export) picks it up automatically. A source whose fetch() returns
# [] is dropped from the board and noted as unavailable.
PROVIDERS: list[AdpProvider] = [
    SleeperAdp(), EspnAdp(), YahooAdp(),
    FfcAdp(), RotowireAdp(), FantasyProsAdp(),
]
_BY_NAME = {p.name: p for p in PROVIDERS}


def _earliest_of(p: AdpProvider):
    """The oldest season a provider has public no-auth ADP for. A class
    attribute wins (used when one module backs several columns); otherwise
    the provider's own module's EARLIEST; else None (a stub)."""
    if getattr(p, "EARLIEST", None) is not None:
        return p.EARLIEST
    try:
        mod = __import__(f"ffadp.{p.name}", fromlist=["EARLIEST"])
        return getattr(mod, "EARLIEST", None)
    except Exception:
        return None


# Earliest season each source has public, no-auth ADP for, so the UI can say
# "from <year>" instead of just dropping the column. None -> no public
# history (a stub, or an auth-gated source).
FIRST_SEASON = {p.name: _earliest_of(p) for p in PROVIDERS}
# The oldest season ANY source can cover -- the season picker's lower bound.
EARLIEST_ANY = min((y for y in FIRST_SEASON.values() if y), default=2020)


def provider(name: str) -> AdpProvider | None:
    return _BY_NAME.get(name)


def _key_of(row) -> str:
    """Merge key for a row: canonical sleeper id when known, else a
    normalised name+position so cross-source rows still line up."""
    if row.sleeper_id:
        return f"sid:{row.sleeper_id}"
    return f"nm:{identity._norm(row.name)}|{(row.position or '').upper()}"


def combine(season: str, sources: list[str] | None = None,
            scoring: str = "ppr", pos: str = "ALL",
            reload: bool = False) -> dict:
    """Build the comparison board for a season.

    `reload=True` is threaded to every provider so it re-fetches live and
    rewrites its snapshot; otherwise each provider is snapshot-first.

    Returns a dict:
      {
        "season": str, "scoring": str, "pos": str,
        "sources":   [{"name","label","ok": bool, "group": str}, ...]
        "columns":   ["sleeper","espn", ...]   # live sources, grouped order
        "groups":    [{"key","label","columns":[names]}, ...]  # non-empty only
        "rows":      [ {player, position, team,
                        adp:  {src: float|None},
                        rank: {src: int|None},
                        consensus: float,   # mean available rank
                        spread: int|None},  # max-min available rank, None if <2
                       ... ]  sorted by consensus asc
      }
    """
    season = str(season)
    want = sources or [p.name for p in PROVIDERS]
    src_status: list[dict] = []
    per_source: dict[str, list] = {}
    for name in want:
        p = _BY_NAME.get(name)
        if p is None:
            continue
        try:
            rows = p.fetch(season, scoring, reload=reload)
        except TypeError:
            rows = p.fetch(season, scoring)   # a provider without reload=
        except Exception:
            rows = []
        # resolve canonical ids for any row that came without one
        for r in rows:
            if not r.sleeper_id:
                r.sleeper_id = identity.resolve(
                    p.name, espn_id=r.espn_id, yahoo_id=r.yahoo_id,
                    name=r.name, position=r.position)
        per_source[name] = rows
        first = FIRST_SEASON.get(p.name)
        st = {"name": p.name, "label": p.label, "ok": bool(rows),
              "first_season": first,
              "group": getattr(p, "group", "analyst")}
        # Distinguish "predates this source" from "fetch failed / not wired".
        if not rows:
            try:
                predates = first is not None and int(season) < first
            except (TypeError, ValueError):
                predates = False
            if first is None:
                st["why"] = "no public data"
            elif predates:
                st["why"] = f"from {first}"
            else:
                st["why"] = "unavailable"
        src_status.append(st)

    # Columns are grouped by source type (draft apps first, then high-stakes
    # / best-ball, then analyst consensus); within a group the registry order
    # holds. `groups` reports the same split so the UI can label and filter.
    reg_ix = {p.name: i for i, p in enumerate(PROVIDERS)}
    live = [s["name"] for s in src_status if s["ok"]]
    grp_of = {p.name: getattr(p, "group", "analyst") for p in PROVIDERS}
    columns = sorted(
        live,
        key=lambda n: (GROUP_ORDER.get(grp_of.get(n, "analyst"), 99),
                       reg_ix.get(n, 99)),
    )
    groups = [
        {"key": key, "label": GROUP_LABEL[key],
         "columns": [n for n in columns if grp_of.get(n) == key]}
        for key, _ in GROUPS
    ]
    groups = [g for g in groups if g["columns"]]

    # Fold every source's rows into one record per player key.
    merged: dict[str, dict] = {}
    for name in columns:
        for r in per_source[name]:
            k = _key_of(r)
            rec = merged.setdefault(k, {
                "player": r.name, "position": r.position, "team": r.team,
                "sleeper_id": r.sleeper_id,
                "adp": {}, "rank": {},
            })
            # Prefer a real name/pos/team over a placeholder as more sources chime in.
            if r.sleeper_id and not rec.get("sleeper_id"):
                rec["sleeper_id"] = r.sleeper_id
            m = identity.meta(r.sleeper_id) if r.sleeper_id else {}
            rec["player"] = m.get("name") or rec["player"] or r.name
            rec["position"] = m.get("position") or rec["position"] or r.position
            rec["team"] = m.get("team") or rec["team"] or r.team
            rec["adp"][name] = r.adp
            rec["rank"][name] = r.overall_rank

    rows_out = []
    for rec in merged.values():
        if pos != "ALL" and (rec["position"] or "").upper() != pos.upper():
            continue
        ranks = [v for v in rec["rank"].values() if v is not None]
        rec["consensus"] = round(sum(ranks) / len(ranks), 1) if ranks else None
        rec["spread"] = (max(ranks) - min(ranks)) if len(ranks) >= 2 else None
        rows_out.append(rec)

    rows_out.sort(key=lambda r: (r["consensus"] is None, r["consensus"] or 0.0))

    return {
        "season": season, "scoring": scoring, "pos": pos,
        "sources": src_status, "columns": columns, "groups": groups,
        "rows": rows_out,
    }


def to_frame(board: dict) -> pd.DataFrame:
    """Flat DataFrame view of combine()'s rows -- for tests and CSV/Excel
    export. Column order mirrors the on-screen table: board rank, player,
    position, team, consensus, then each source's ADP + that source's own
    overall rank (in the board's grouped column order: draft apps, then
    high-stakes / best-ball, then analyst consensus), and spread last."""
    recs = []
    for i, r in enumerate(board["rows"], 1):
        rec = {
            "rank": i,
            "player": r["player"],
            "position": r["position"],
            "team": r["team"],
            "consensus": r["consensus"],
        }
        for c in board["columns"]:
            lbl = next((s["label"] for s in board["sources"] if s["name"] == c), c)
            rec[f"{lbl} ADP"] = r["adp"].get(c)
            rec[f"{lbl} rank"] = r["rank"].get(c)
        rec["spread"] = r["spread"]
        recs.append(rec)
    return pd.DataFrame(recs)
