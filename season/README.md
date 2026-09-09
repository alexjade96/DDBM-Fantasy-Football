# season/: playoff brackets Sleeper can't run, plus cached stat data

This directory is the one durable-data location for everything that isn't
re-derivable straight from the Sleeper API: custom playoff bracket configs
(one subfolder per league id), a cache of Sleeper's own ADP data (one shared
file per year), a cache of Sleeper's weekly usage/stat lines, a cache of
nflverse's public data releases, and a set of canonical default scoring
charts. The brackets are plain checked-in JSON read by both the R and Python
engines; the three stat caches and the scoring charts are Python-only for
now (see below).

```
season/
  <root_league_id>/<season>.json   # one subfolder per REAL league (its
                                    # chain's oldest/root id, see below),
                                    # every season it's ever played under
  adp/<season>.json                # shared across every league (Sleeper
                                    # publishes one ADP set per year, not
                                    # per league)
  adp/finish/<season>-<fmt>.json    # each player's overall end-of-season
                                    # value rank, per scoring format; feeds
                                    # the ADP Comparison tab's Final/Diff
                                    # columns, Python-only, see below
  stats/<season>/<week>.json        # trimmed Sleeper weekly usage lines
                                    # (snap share, targets, air yards, RZ);
                                    # Python-only, see below
  nflverse/<dataset>/<season>.parquet  # snapshots of nflverse's own public
                                    # data releases (player_stats, schedules);
                                    # Python-only, see below
  scoring/default_scoring.json     # canonical Sleeper DEFAULT point-calc
                                    # charts (std / half_ppr / ppr / 2qb);
                                    # a stand-in when no league is loaded,
                                    # Python-only, see below
  fixtures/                        # manually-referenced ground-truth fixtures
  scaffold.py                      # generates a bracket config for the
                                    # workflow below; prints the root id
```

## Playoff brackets

Sleeper can only express *its own* bracket: a fixed `playoff_week_start`, its own
team count, and lineups locked to whatever the app had. When a league runs the
playoff by hand (a different week range, a custom bracket, and starters handed
to the commissioner because the app wouldn't let managers set them), none of
that fits, and Sleeper's stored bracket becomes unreliable.

(For DDBM 2025 it *is* unreliable: in Sleeper's own `winners_bracket`, the team
recorded as losing in round 1 **and** round 2 is also recorded as winning the
`p == 1` championship game. That bracket is not a coherent elimination tree.)

This engine takes the bracket as **config** and needs only **roster inputs** per
elimination matchup. Everything else (points, winners, advancement) is computed.

### Why one subfolder per league, keyed by the chain's ROOT id

A bracket config is keyed by season, but a season *number* is not unique across
leagues, and Sleeper gives every season of a league its own, DIFFERENT league
id (a new league object each year, chained backwards via `previous_league_id`),
so even DDBM's own history has a different league id every season. Naively
keying the folder by each season's own id would scatter one real league's
brackets across as many folders as it has seasons, exactly the opposite of
"grouped by league."

Instead the folder key is the chain's **root** (oldest) league_id.
`sl_root_league_id()` / `root_league_id()` walks `previous_league_id` all the
way back to the season with none, which never changes: new seasons only ever
extend the chain forward, so today's root is next year's root too. For DDBM
that's 2022's own id (`870378308704141312`, its earliest tracked season), so
its whole history lives under `season/870378308704141312/`. Each file's own
`league_id` field still holds THAT season's real, individual id (needed for
`config_paths()`'s league-filtering, and for `sl_playoff()`/`sm.playoff()` to
fetch that season's own data); only the surrounding folder is grouped by root.

`config_paths()`/`sl_playoff_configs()` walk `season/<root_league_id>/*.json`,
filtering to only numeric-named subfolders. `season/adp/` and
`season/fixtures/` are siblings holding unrelated data and are skipped by that
same rule, not by an explicit denylist. `season/scaffold.py` prints the
resolved root id after writing a config, so a brand-new season lands in the
right existing folder instead of a fresh one.

### How points are computed

Not read from Sleeper's matchup rows (they only know the lineup Sleeper had).
Instead each submitted starter is priced from raw NFL stat lines under the
league's own **point-calculation chart** (`scoring_settings`):

```
points = Σ (stat × league weight)
```

This is verified faithful: replaying Sleeper's own 2025 bracket through the
engine reproduced **all 12 of its matchup winners and the champion, with zero
mismatches**, and the per-player scoring matched Sleeper's own numbers on
175/175 players in week 15.

The chart is **snapshotted into the config**, so a finished bracket keeps scoring
the same even if league settings change later.

Sleeper keys the chart by internal stat code (`pass_yd`, `bonus_rec_te`,
`pts_allow_7_13`), which is fine for arithmetic and unreadable to a human. Both
dashboards therefore render it through `sl_scoring_readable()` /
`sm.scoring_readable()`, which groups the rules and states each one in plain
English: `pass_yd: 0.04` becomes **Passing yards, 1 point per 25 yards**, while
still showing the raw code beside it. Unknown keys are never dropped; they land in
an "Other" group under their raw name, so a new Sleeper stat shows up rather than
silently vanishing from the chart the season was decided by.

### Workflow

```bash
# 1. scaffold a bracket (seeds from standings; pre-fills starters as a baseline)
#    -- prints the root league id to use as the folder; DDBM's is
#    870378308704141312, so its 2025 bracket goes under that folder, not
#    under 2025's own (different) league_id.
python season/scaffold.py custom <league_id> season/870378308704141312/2025.json \
    --weeks 14 15 16 17 18 --teams 8

# 2. edit season/870378308704141312/2025.json: replace each side's `starters`
#    with the lineup actually submitted to the commissioner. Ids or player
#    names both work.

# 3. score it
```

```r
pkgload::load_all("R/sleepermetrics")
p <- sl_playoff("season/870378308704141312/2025.json")
p$champion
sl_playoff_summary(p)
sl_plot_playoff_bracket(p)
sl_plot_playoff_matchup(p, "R1M1")   # the receipts: both lineups, player by player
```

```python
import sleepermetrics as sm
p = sm.playoff("season/870378308704141312/2025.json")
sm.playoff_summary(p)
```

Or watch it live in the dashboard: the **Playoffs** tab renders the bracket,
per-matchup breakdowns and the stored scoring chart, and re-scores from current
stats on every refresh:

```r
sl_dashboard(playoffs = "season", port = 8100)
```

### Config schema

```jsonc
{
  "season": "2025",
  "league_id": "1252770181306929152",   // THIS season's own real id -- NOT
                                         // the folder's root id (see above)
  "roster_positions": ["QB","RB","RB","WR","WR","TE","FLEX","K","DEF","BN", ...],
  "scoring_settings": { "pass_td": 4.0, "rec": 1.0, ... },   // snapshot; 48 rules
  "final": "R3M1",                    // which matchup is the TITLE game
  "rounds": [
    {
      "id": "R1", "name": "Round 1",
      "weeks": [14],                  // several weeks = one cumulative round
      "matchups": [
        { "id": "R1M1",
          "home": { "team": "LuckyHarm", "starters": ["4034", "Bijan Robinson", "SEA"] },
          "away": { "team": "xPsyD",     "starters": [...] } },
        { "id": "R1M2", "bye": "SimonSmith" }
      ]
    },
    {
      "id": "R2", "name": "Final", "weeks": [16],
      "matchups": [
        { "id": "R2M1",
          "home": { "team": "W:R1M1", "starters": [...] },   // winner of R1M1
          "away": { "team": "W:R1M2", "starters": [...] } }
      ]
    }
  ]
}
```

Notes:

- **`starters`** accept player ids *or* player names (`"SEA"` for a defense).
  They are the only thing you must supply.
- **`W:<matchup_id>`** / **`L:<matchup_id>`** advance winners/losers automatically,
  so later rounds wire themselves up. `L:` lets you build a consolation bracket.
- **`weeks`** with more than one entry makes a cumulative multi-week round.
- **`final`** must name the title game; a last round can also hold consolation
  and placement games, so "last matchup" is not a safe assumption.
- **`bye`** passes a team through unscored.
- A matchup whose teams aren't decided yet, or whose lineups haven't been handed
  in, is reported as **`PENDING`** rather than scored as 0–0, which is what makes
  the bracket safe to run live, week by week, as rounds resolve.
- Submitted lineups are checked against the league's starting slots; anything
  short, over, or flex-illegal is warned about (`sl_check_lineup()`).

### Files

Every season has a stored bracket, holding the **finalized lineups** each team
started. The dashboard's Playoffs tab follows the season picker and loads the
matching one automatically.

All four live under the same root folder, `870378308704141312/` (DDBM's 2022
id, its chain's origin); the "season's own league_id" column below is each
year's genuinely different real id, still stored inside that file's own
`league_id` field: the exact mismatch `sl_root_league_id()` exists to paper
over at the folder level.

| File | Season's own league_id | Season | Bracket | Champion |
|---|---|---|---|---|
| `870378308704141312/2022.json` | 870378308704141312 | 2022 (6 teams) | standard Sleeper | sparky1335 |
| `870378308704141312/2023.json` | 1003483425623355392 | 2023 (8 teams) | standard Sleeper | rezzu |
| `870378308704141312/2024.json` | 1107490594215063552 | 2024 (6 teams) | standard Sleeper | SearingShadow |
| `870378308704141312/2025.json` | 1252770181306929152 | 2025 (10 teams) | **custom** choose-your-opponent, wks 15–18 | LuckyHarm |
| `fixtures/2025-sleeper-bracket.json` | - | - | Sleeper's own 2025 bracket, replayed; the engine's ground-truth fixture | - |
| `scaffold.py` | - | - | generates any of the above from the league | - |

For 2022–2024 the engine reproduces **Sleeper's own recorded champion** from the
stored lineups, which is the check that the scoring is right.

#### 2025 is deliberately different

2025's playoff was run by hand, so its bracket comes from config, not the API:

- **Seeding is the regular season (through wk14)**, *not* the final standings,
  which are polluted by the playoff weeks themselves. This is the subtle bit: it
  makes SearingShadow the 3-seed (not the 5-seed), so they took an R1 bye and
  *picked* xPsyD. Seed off the wrong table and the bracket cannot be made to
  resolve at all.
- Seeds 5–8 play R1; seeds 3–4 then **pick** from the R1 winners; seeds 1–2 pick
  from the R2 winners; then the final. Seeds 1 and 2 therefore get **two byes**.
- All 7 games reproduce the known outcomes from the recorded lineups.

Note Sleeper's *own* stored 2025 bracket disagrees (it crowns SimonSmith), but
that bracket is incoherent: the team it records as losing rounds 1 **and** 2 is
also its `p == 1` champion. The config is the accurate record.

## ADP cache (`adp/`)

The Python Draft tab's redraft-by-ADP simulation (`sleepermetrics.draft.redraft_board_adp`)
draws its draft order from Sleeper's own **undocumented** per-season ADP/projections
endpoint (`api.sleeper.com/projections/nfl/<season>`), reverse-engineered, not
part of Sleeper's documented v1 API. `season/adp/<season>.json` is a trimmed,
auto-refreshed snapshot of that response (player name/position + `adp_std`/
`adp_half_ppr`/`adp_ppr`/`adp_2qb`), written on every successful live fetch so a
later run with no network, or after Sleeper ever changes or removes the
endpoint, still has the latest successfully-captured data to fall back to.

Unlike the playoff configs, ADP is **season-scoped, not league-scoped**: Sleeper
publishes one ADP set per year for the whole platform, so it lives in its own
shared subfolder rather than duplicated into every league's own files.

This is Python-only for now (same precedent as this codebase's other newer
draft analytics; see `CLAUDE.md`); nothing here is hand-edited.

### Finish ranks (`adp/finish/`)

`season/adp/finish/<season>-<fmt>.json` is a `{sleeper_id: rank}` map giving
each player's **overall end-of-season value rank** for that season (1 = the
year's top scorer, all positions together), one file per scoring format
(`std` / `half_ppr` / `ppr` / `2qb`). It backs the ADP Comparison tab's
**Final** column, and **Diff** (`consensus - final`: positive = the field
drafted the player later than he finished, i.e. a value; negative = a reach).

Priced league-free from raw NFL stat lines (`/stats/nfl/regular/<season>/
<week>`) times the canonical **default** scoring chart for the format
(`season/scoring/default_scoring.json`, via
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

## Weekly usage cache (`stats/`)

`sleepermetrics.nflstats` surfaces the volume/usage stats that Sleeper's
weekly stat line already carries but nothing else in the app reads: snap
share (`off_snp` / `tm_off_snp`), targets, air yards, red-zone touches,
efficiency rates. It is the **same** `/stats/nfl/regular/<season>/<week>`
feed `scoring.py` fetches to price lineups; this module just keeps the
volume keys instead of only the scoring ones.

`season/stats/<season>/<week>.json` is a trimmed per-week snapshot (one file
per season+week), written on every successful live fetch so a later offline /
cold-host run still resolves. The source is labelled `"sleeper"` on every row
(`nflstats.SOURCE`), so a future multi-source usage board can tell where a
figure came from. Python-webapp-only, not in the parity-diffed metric
contract; nothing here is hand-edited.

## nflverse data cache (`nflverse/`)

`python/nflref/` is a thin, dataset-oriented layer over **nflverse's own
public data releases** -- the `.parquet` files nflverse publishes on GitHub
(`nflverse/nflverse-data`), the same ones the R `nflreadr` and Python
`nflreadpy` / `nfl_data_py` packages download. No auth, no API key, CC-BY-4.0
data. It fetches the release assets directly (`nflref.api.read_release_parquet`)
rather than take a library dependency.

`season/nflverse/<dataset>/<season>.parquet` snapshots each tidied frame
(same durable-fallback pattern as `adp/`). Datasets wired so far:
`player_stats` (nflverse weekly player stats -- carries `target_share` /
`air_yards_share` / `wopr`, which Sleeper's feed does not) and `schedules`
(real game results + roof/surface/rest, for a true strength-of-schedule).
It surfaces on the opening screen as the **NFL Stats** landing tab (next to
ADP Comparison): a per-season player leaderboard (from EITHER nflverse's own
weekly release OR Sleeper's own weekly feed -- a Source toggle), the game
schedule/results, and a **Source comparison** that lines the two feeds up
player-by-player and reports every season-total stat they disagree on
(`nflref.compare_sources`). Season-only, CSV/Excel export. Still scaffolding
for deeper analytics later. Python-webapp-only, outside `sleepermetrics`,
`verify.py` unaffected. Needs `pyarrow` (in `requirements.txt`).

## Default scoring charts (`scoring/`)

`season/scoring/default_scoring.json` holds four canonical **Sleeper default**
point-calculation charts, keyed by the scoring-format ids this project already
uses elsewhere: `std`, `half_ppr`, `ppr`, `2qb`. Each is a flat
`{stat: weight}` dict in Sleeper's own `scoring_settings` vocabulary -- the
same shape `sleepermetrics.scoring.rules_from(league_id)` returns -- so a chart
can stand in for a league's live `scoring_settings` anywhere a scoring chart is
needed but no league is loaded (e.g. pricing a season from raw stat lines for
the ADP tab, or a league-free leaderboard).

The four charts differ **only** by the `rec` weight (0 / 0.5 / 1 / 1);
superflex / 2QB is a roster-slot difference, not a scoring one, so `2qb` is
identical to `ppr` here.

How it was built: the weights were reconciled from 39 real public Sleeper
leagues (modal weight per stat key), with `pass_int` set to Sleeper's true
default of -1, then cross-checked against ESPN's published standard scoring and
the profootballnetwork / fantasypointcalculators / Sleeper-support references.
**Verified**: the `std` / `half_ppr` / `ppr` charts reproduce Sleeper's own
`pts_std` / `pts_half_ppr` / `pts_ppr` **exactly** for every offensive player
(5008/5008 player-format-weeks across 2023-2025) and every kicker. The DST keys
are the documented Sleeper defaults but do **not** reproduce Sleeper's DST
`pts_*` exactly -- Sleeper scores team defense from a richer vocabulary
(yards-allowed tiers, forced punts, 3-and-outs, return TDs folded into `td`)
that a linear chart over the basic keys can't express; this is the same reason
`sleepermetrics.scoring` only scores offensive lineups.

Not league-specific, not a parity artifact, hand-verified once and stable.
Python-only for now.

## Location override

Both engines resolve this whole directory from one environment variable,
`SLEEPERMETRICS_SEASON_DIR` (default: `season/` under the repo root), set by
`launch.py`, the `Dockerfile`, and `sl_dashboard(playoffs = ...)` alike, so the
playoff configs, the ADP cache, the stat caches, and the default scoring
charts always move together.
