"""Re-derive every stored playoff champion from the lineups.

Configs persist an engine-derived `champion` so season loads stay cheap. That
value is only trustworthy if it still falls out of the bracket, so this re-runs
each bracket from its stored lineups and asserts the two agree. It also checks
no bracket has left-over PENDING games.

    python parity/check_playoffs.py [playoffs_dir]

Exit 0 only if every stored champion is reproducible.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "python")
import sleepermetrics as sm  # noqa: E402
from sleepermetrics import playoffs as po  # noqa: E402


def main() -> int:
    d = sys.argv[1] if len(sys.argv) > 1 else "playoffs"
    paths = po.config_paths(d)
    if not paths:
        print(f"    no bracket configs in {d}/")
        return 1
    bad = 0
    for season, path in sorted(paths.items()):
        cfg = po.playoff_config(path)
        stored = cfg.get("champion")
        p = sm.playoff(cfg, validate=False)
        pending = int((p.results["result"] == "PENDING").sum())
        ok = stored == p.champion and pending == 0
        bad += not ok
        note = "" if ok else f"  <-- stored={stored!r} recomputed={p.champion!r}"
        if pending:
            note += f" [{pending} PENDING rows]"
        print(f"    [{'OK' if ok else 'XX'}] {season}: {p.champion} "
              f"({p.results['round_id'].nunique()} rounds){note}")
    print(f"    {len(paths) - bad}/{len(paths)} stored champions reproduce from the lineups")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
