# data/sources/: source-organized caches, shared across every league

This directory holds everything that is durable data but NOT scoped to one
league's own season history: a cache of Sleeper's own ADP data (one shared
file per year), a cache of Sleeper's weekly usage/stat lines, a cache of
nflverse's public data releases, and a set of canonical default scoring
charts. Everything here is organized by SOURCE first (which ADP provider,
which nflverse dataset, the scoring chart itself), with season only as a
leaf underneath -- the opposite of `data/seasons/`, which is a directory of
per-league season history where season really is the top-level organizing
idea. See `data/seasons/README.md` for that sibling directory.

Python-only for now (see below); nothing here is hand-edited.

```
data/sources/
  adp/<season>.json                # Sleeper's own ADP, shared across every
                                    # league (Sleeper publishes one ADP set
                                    # per year, not per league)
  adp/finish/<season>-<fmt>.json    # each player's overall end-of-season
                                    # value rank, per scoring format; feeds
                                    # the ADP Comparison tab's Final/Diff
                                    # columns, see below
  sleeper_stats/<season>/week_<week>.json  # trimmed Sleeper weekly usage
                                    # lines (snap share, targets, air yards,
                                    # RZ); named for the source -- see below
  nflverse/<dataset>/<season>.parquet  # snapshots of nflverse's own public
                                    # data releases (player_stats, schedules);
                                    # see below
  default_scoring.json             # canonical Sleeper DEFAULT point-calc
                                    # chart: `base` + per-format `rec`
                                    # (std/half_ppr/ppr/2qb); a stand-in
                                    # when no league is loaded -- a single
                                    # static file, not season-varying, so it
                                    # sits directly under data/sources/
                                    # rather than its own subfolder
```

`adp/` and `nflverse/` are genuinely multi-thing directories (adp/ has 7
different provider sources underneath; nflverse/ has 2 datasets from that one
source), so a subfolder per provider/dataset earns its keep there.
`sleeper_stats/` is single-source (only Sleeper's own feed) but still
season/week-shaped underneath, so it keeps its own directory; a single FLAT
file like the scoring chart does not, and lives directly under `data/sources/`
instead.

## ADP cache (`adp/`)

The Python Draft tab's redraft-by-ADP simulation (`sleepermetrics.draft.redraft_board_adp`)
draws its draft order from Sleeper's own **undocumented** per-season ADP/projections
endpoint (`api.sleeper.com/projections/nfl/<season>`), reverse-engineered, not
part of Sleeper's documented v1 API. `data/sources/adp/<season>.json` is a trimmed,
auto-refreshed snapshot of that response (player name/position + `adp_std`/
`adp_half_ppr`/`adp_ppr`/`adp_2qb`), written on every successful live fetch so a
later run with no network, or after Sleeper ever changes or removes the
endpoint, still has the latest successfully-captured data to fall back to.

ADP is **season-scoped, not league-scoped**: Sleeper publishes one ADP set per
year for the whole platform, so it lives in its own shared subfolder rather
than duplicated into every league's own files.

Same durable-fallback pattern also backs the webapp's own cross-platform ADP
Comparison tab (`fantasy-football-4-fun/webapp/sources/ffadp/`), which snapshots
each additional source under its own `adp/<source>/<year>.json` (or
`adp/<source>/<variant>/<year>.json` when a source keeps a separate snapshot
per scoring format, e.g. FFC).

### Finish ranks (`adp/finish/`)

`data/sources/adp/finish/<season>-<fmt>.json` is a `{sleeper_id: rank}` map giving
each player's **overall end-of-season value rank** for that season (1 = the
year's top scorer, all positions together), one file per scoring format
(`std` / `half_ppr` / `ppr` / `2qb`). It backs the ADP Comparison tab's
**Final** column, and **Diff** (`consensus - final`: positive = the field
drafted the player later than he finished, i.e. a value; negative = a reach).

Only standard fantasy positions are ranked (`QB`/`RB`/`WR`/`TE`/`K`/`DEF`,
with `FB` folded in); IDP, punters and unpositioned rows are excluded, the
same filter `ffadp.board.combine()` applies to the ADP rows themselves.

Priced league-free from raw NFL stat lines (`/stats/nfl/regular/<season>/
<week>`) times the canonical **default** scoring chart for the format
(`data/sources/default_scoring.json`, via
`sleepermetrics.scoring.default_rules()`), since the ADP tab has no league
context. Built by `ffadp.finish.season_value_ranks(season, fmt)` -- snapshot
first, live compute only on a miss, and a completed season's compute is
written back here (an in-progress season's is not: it would churn week to
week, and the tab shows a "fills in once the season is complete" note
instead). `ffadp.finish.rebuild_season(season)` regenerates every format for a
season; it is a **backend maintenance function**, not wired to any UI control,
for when the stat feed or the default chart changes. `2qb` is currently a
duplicate of `ppr` (the default charts are identical -- superflex is a
roster-slot difference, not a scoring one); it becomes distinct for free if a
real 6-pt-passing-TD superflex chart is ever added.

Committed as a durable fallback, same as the rest of `adp/`. Sleeper's stat
feed only reaches back to ~2009, so earlier seasons in the picker simply show
`-` for Final. Python-webapp-only.

## Weekly usage cache (`sleeper_stats/`)

`sleepermetrics.nflstats` surfaces the volume/usage stats that Sleeper's
weekly stat line already carries but nothing else in the app reads: snap
share (`off_snp` / `tm_off_snp`), targets, air yards, red-zone touches,
efficiency rates. It is the **same** `/stats/nfl/regular/<season>/<week>`
feed `scoring.py` fetches to price lineups; this module just keeps the
volume keys instead of only the scoring ones.

`data/sources/sleeper_stats/<season>/week_<week>.json` is a trimmed per-week
snapshot (one file per season+week, e.g. `week_1.json`), written on every
successful live fetch so a later offline / cold-host run still resolves.
Named for the source (Sleeper's own weekly feed) since it's a single-source
cache, distinct from nflverse's own differently-shaped `player_stats` dataset
below. The source is labelled `"sleeper"` on every row (`nflstats.SOURCE`),
so a future multi-source usage board can tell where a figure came from.
Python-webapp-only, not in the parity-diffed metric contract; nothing here is
hand-edited.

## nflverse data cache (`nflverse/`)

`fantasy-football-4-fun/webapp/sources/nflref/` is a thin, dataset-oriented layer over **nflverse's own
public data releases** -- the `.parquet` files nflverse publishes on GitHub
(`nflverse/nflverse-data`), the same ones the R `nflreadr` and Python
`nflreadpy` / `nfl_data_py` packages download. No auth, no API key, CC-BY-4.0
data. It fetches the release assets directly (`nflref.api.read_release_parquet`)
rather than take a library dependency.

`data/sources/nflverse/<dataset>/<season>.parquet` snapshots each tidied frame
(same durable-fallback pattern as `adp/`). Datasets wired so far:

- **`player_stats`** -- nflverse weekly player stats: `target_share` /
  `air_yards_share` / `wopr` / `racr` / `pacr`, which Sleeper's feed does not
  carry. `EARLIEST = 2016`.
- **`schedules`** -- real game results + roof/surface/rest, for a true
  strength-of-schedule (one all-seasons file, sliced per season on fetch).
  `EARLIEST = 1999`.
- **`snap_counts`** -- per-player-per-week snap share split by
  **offense/defense/special-teams** (`offense_pct`/`defense_pct`/`st_pct`),
  from PFR's own snap-count tables. Genuinely new versus Sleeper's own feed
  (`sleepermetrics.nflstats`), which only carries offensive snap share.
  `EARLIEST = 2012` (the 2012 release asset itself is empty -- verified --
  so real coverage starts 2013).
- **`ngs_passing`** / **`ngs_receiving`** / **`ngs_rushing`** -- real NFL
  Next Gen Stats tracking-derived metrics (three all-seasons files, sliced
  per season on fetch): `avg_time_to_throw` / `completion_percentage_
  above_expectation` (CPOE) for passing; `avg_cushion` / `avg_separation` /
  `avg_yac_above_expectation` for receiving; `rush_yards_over_expected` /
  `efficiency` for rushing. The closest free equivalent to PFF's tracking-
  based grades -- real player-tracking-chip data, not box-score derivatives.
  `EARLIEST = 2016`. `ngs_rushing` is missing 2023 entirely in the upstream
  release (verified: every other season 2016-2026 has real rows).
- **`pfr_pass`** / **`pfr_rec`** / **`pfr_rush`** / **`pfr_def`** -- Pro
  Football Reference's advanced weekly stats (four separate role-specific
  datasets, since each has a near-disjoint column set): pressure rate /
  times blitzed/hurried/hit for passing; drop rate / broken tackles /
  receiver rating for receiving; yards before/after contact / broken
  tackles for rushing; missed tackles / pressures / passer rating allowed
  for defense (IDP-relevant). Already player-level and per-game -- the best
  value-to-effort PFF-comparable data available, no play-level explode/join
  needed. `EARLIEST = 2018`.
- **`injuries`** -- weekly official injury reports: the SPECIFIC injury
  (`report_primary_injury`/`report_secondary_injury`, e.g. "Hamstring",
  "Concussion", "Illness" -- 20+ categories, not just a flag), the final
  game-status designation (`report_status`: Out/Doubtful/Questionable), and
  daily practice-report detail. Context data (explains a bad week, tracks a
  recurring injury) rather than a rankable stat. `gsis_id` join key verified
  zero-null across this league's real seasons. `EARLIEST = 2009`.

It surfaces on the opening screen as the **NFL Stats** landing tab (next to
ADP Comparison): a per-season player leaderboard (from EITHER nflverse's own
weekly release OR Sleeper's own weekly feed -- a Source toggle), the game
schedule/results, and a **Source comparison** that lines the two feeds up
player-by-player and reports every season-total stat they disagree on
(`nflref.compare_sources`). Season-only, CSV/Excel export. `snap_counts`/
`ngs_*`/`pfr_*`/`injuries` are wired at the data layer (`nflref.load(name,
season)`, cached, backfilled to each dataset's own EARLIEST) but not yet
surfaced in the NFL Stats tab UI -- a deliberate, smaller first step; adding
them to the leaderboard/a new view is a follow-up. Python-webapp-only,
outside `sleepermetrics`, `verify.py` unaffected. Needs `pyarrow` (in
`requirements.txt`).

## Default scoring chart (`default_scoring.json`)

`data/sources/default_scoring.json` holds the canonical **Sleeper default**
point-calculation chart in Sleeper's own `scoring_settings` vocabulary -- the
same shape `sleepermetrics.scoring.rules_from(league_id)` returns -- so it can
stand in for a league's live `scoring_settings` anywhere a scoring chart is
needed but no league is loaded (e.g. pricing a season from raw stat lines for
the ADP tab, or a league-free leaderboard). A single static file, not even
season-varying, so it lives directly under `data/sources/` rather than its
own subfolder -- unlike `adp/`, `sleeper_stats/` and `nflverse/`, there is
nothing here to organize BY.

**Points-per-reception is the only thing that differs between the standard
scoring formats**, so the file stores the chart once:

- `base` -- every scoring rule except `rec` (41 keys).
- `rec_by_format` -- the per-format reception weight: `std` 0, `half_ppr` 0.5,
  `ppr` 1.0, `2qb` 1.0.

`sleepermetrics.scoring.default_rules(fmt)` merges the two (`base` + that
format's `rec`) and returns a plain `{stat: weight}` dict, in-process cached.
Superflex / 2QB is a roster-slot difference, not a scoring one, so its chart
equals PPR. A TE-premium variant would add a `bonus_rec_te` key (a
per-position reception boost that stacks on `rec`); no ADP source this project
reads publishes TEP, so it is not included.

How it was built: the weights were reconciled from 39 real public Sleeper
leagues (modal weight per stat key), with `pass_int` set to Sleeper's true
default of -1, then cross-checked against ESPN's published standard scoring and
the profootballnetwork / fantasypointcalculators / Sleeper-support references.
**Verified**: `base` plus the `std` / `half_ppr` / `ppr` rec weight reproduces
Sleeper's own `pts_std` / `pts_half_ppr` / `pts_ppr` **exactly** for every
offensive player (5008/5008 player-format-weeks across 2023-2025) and every
kicker. The DST keys
are the documented Sleeper defaults but do **not** reproduce Sleeper's DST
`pts_*` exactly -- Sleeper scores team defense from a richer vocabulary
(yards-allowed tiers, forced punts, 3-and-outs, return TDs folded into `td`)
that a linear chart over the basic keys can't express; this is the same reason
`sleepermetrics.scoring` only scores offensive lineups.

Not league-specific, not a parity artifact, hand-verified once and stable.
Python-only for now.

## Location override

Resolved from the environment variable `SLEEPERMETRICS_SOURCES_DIR` (default:
`data/sources/` under the repo root), set by `launch.py`, the `Dockerfile`,
and `repo_paths.py`'s own fallback alike, so the ADP cache, the Sleeper stats
cache, the nflverse cache, and the default scoring chart always move together.
This is a SEPARATE env var and constant from `SLEEPERMETRICS_SEASON_DIR`/
`SEASON_DIR` (see `data/seasons/README.md`), which governs only the
league-scoped playoff bracket configs -- the two roots are deliberately
independent, since one is organized by league+season and the other by
source+season.
