# Cross-language parity harness

Verifies the R (`r-analysis/sleepermetrics`) and Python
(`fantasy-football-4-fun/sleepermetrics`) implementations operate correctly
**and produce mirrored outputs**.

## Run

```sh
python verify.py [league_id]     # default: the DDBM league
```

`verify.py` (repo base):

1. runs the **Python** unit tests (`pytest`, `fantasy-football-4-fun/tests`),
2. runs the **R** unit tests (`testthat`, `r-analysis/sleepermetrics`),
3. runs both exporters below to produce canonical metric JSON, then
4. **diffs** the two JSONs field-by-field (numbers within a tolerance, summary
   text exact) and prints a PASS/FAIL summary. Exit code is 0 only if every
   check passes.

## Exporters

- `tools/parity/export_r.R` and `tools/parity/export_py.py` each compute the
  same canonical bundle for a league - latest-season `standings`, `luck`,
  `efficiency`, `consistency`, `high_scores`, `week_stats`, all-time `career`,
  and the three markdown summaries - and write `tools/parity/out_r.json` /
  `tools/parity/out_py.json` (gitignored; regenerated each run).

Because the exporters emit an identical structure with deterministic sorting and
2dp rounding, a clean diff proves the two engines are numerically equivalent on
live data. Run them standalone to inspect either side:

```sh
fantasy-football-4-fun/venv/Scripts/python tools/parity/export_py.py <league> tools/parity/out_py.json
Rscript tools/parity/export_r.R <league> tools/parity/out_r.json
```
