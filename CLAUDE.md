# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An R analytics project for the "DDBM" Sleeper fantasy football redraft league. It pulls data from the public Sleeper API, reshapes it into tidy frames, and renders a set of `DDBM*.png` charts. There is no package, no test suite, and no build — scripts are run interactively in RStudio (`FantasyFootball.Rproj`) or headless via `Rscript`.

Two scripts:
- **`ddbmFF.R`** — single-season analytics (one season's matchups/rosters/transactions → ~26 charts in `results/<season>/`). This is the main program.
- **`leagueAnalytics.R`** — cross-season *career* analytics. Walks the whole season chain and aggregates by persistent `user_id` (same manager across seasons despite changing display names/rosters), writing `results/league/` (career standings, finish trajectory, points-per-season, manager-player loyalty, plus `league-career-summary.md` + `.csv`). It reuses the same hardened `callSleeper`/`ensure_cols`/`buildLeagueChain`/NA-matchup logic as `ddbmFF.R`.

## Running

Two ways to run:
- **RStudio (the author's way):** open `FantasyFootball.Rproj` and source/step through `ddbmFF.R` top to bottom. Most analysis blocks have a trailing `# view(...)` comment naming the frame to inspect with RStudio's `View()`.
- **Headless:** `Rscript ddbmFF.R` from the repo root works end to end (verified). Select a season with the `DDBM_SEASON` env var, e.g. `DDBM_SEASON=2024 Rscript ddbmFF.R`; unset/empty uses the most recent season. In RStudio instead set `targetSeason <- "2024"` in the Config block (`NULL` = current).

Notes:
- The package install lines at the top of `ddbmFF.R` are commented out; install them once into your R library before first run (notably `tidyverse`, `httr2`, `ggplot2`, `treemapify`, `tidytext`, `patchwork`, `RColorBrewer`, and the `nflverse` family).
- `getSleeperPlayers.ps1` is a standalone PowerShell helper that downloads the full Sleeper player dump to a JSON file; it is not called by the R script and writes to a hardcoded absolute path under `~/Documents/Data/FantasyFootball`.

Each chart block ends in a `ggsave(out("DDBM*.png"), ...)`, where `out()` resolves to `results/<season>/`. Chart PNGs are gitignored build artifacts (regenerate by running the script); only `results/<season>/player-patch-log.md` is tracked.

## Data flow / architecture

`ddbmFF.R` is the whole program. It runs in four stages:

0. **Config (season selection).** Near the top, after the `/state/nfl` fetch, a Config block sets `currentLeagueId` (head of the chain) and `targetSeason`. Sleeper stores each season as a *separate* league object chained backwards by `previous_league_id`, so `buildLeagueChain()` walks that chain into a `season -> {league_id, last_scored_leg}` map. The selected `season` (default = most recent) resolves `leagueId`, `lastWeek` (= that season's `last_scored_leg`, the correct loop cap — see "Things that will bite you"), and `outDir`/`out()` for `results/<season>/` output.

1. **General Sleeper data** — `callSleeper(objectId, endpoint)` wraps `https://api.sleeper.app/v1`. Player metadata is the largest payload, so it is cached to `sleeperPlayerData.rds` and only re-fetched when the file's mtime is not today (see the `fileDate == today` guard). The raw nested player list is flattened into `playerDF`, then into two lookups: `playerMap` (team-filtered, `player_id -> name/position/team`, used where "currently on a team" matters) and **`playerInfo`** (team-INDEPENDENT `player_id -> name/position`, used for all name/position joins so released/team-less players resolve without manual patches).

2. **League-specific data** — keyed off `leagueId` (from the Config block, not a hardcoded literal). Rosters and users are merged into `userMap` (`roster_id -> user_name`). The script then loops `1:lastWeek` over `/matchups/{week}` and `/transactions/{week}` to build the three central frames everything downstream depends on:
   - `matchupResults` — one row per team per week with cumulative W/L, points, and computed league `table_position`.
   - `DDBMRosters` — one row per player per team per week, with `position`, `player_points`, and `is_starter`. This is the workhorse frame.
   - `allTransactionsDF` — adds/drops/trades unnested to one row per player movement.

   After `DDBMRosters` is built, `applyPlayerPatches()` applies any `seasonPatches[[season]]` (an id-keyed `tribble`, normally empty — `playerInfo` resolves almost everything) and a per-season patch log is written to `results/<season>/player-patch-log.md`.

3. **Analysis + charts** — built from the `Filter*` versions of those frames (`FilterDDBMRosters`, `FilterMatchupResults`, etc.). Because the week loops only cover scored weeks (`1:lastWeek`), the `Filter*` frames no longer drop a week — they just set the `position` factor ordering. Derived frames (`*OfTheWeek`, `playerRosterPerformances`, `playerTradePerformances`, `playerWaiverPerformances`, roster/position breakdowns) feed the `ggplot` blocks.

## Things that will bite you

- **Week cap = `last_scored_leg`, not `state.week`.** The week loops are capped by `lastWeek`, taken from the league object's `settings.last_scored_leg` (the last fully-scored week, e.g. 17 for 2025; 16 for 2024). Do **not** swap this for `currentSeason$week` (`/state/nfl`) — that value collapses to `0` in the offseason (which breaks `1:lastWeek`) and is phase-dependent. `last_scored_leg` is live-safe and per-season. (Historical note: this replaced an earlier hardcoded `currentWeek`/`latestWeek = 18` plus a `-1` exclusion filter.)
- **Player resolution / patches are id-keyed now.** Name/position come from `playerInfo` (team-independent), so released/team-less players resolve automatically — there are no more fragile `DDBMRosters[<row>, ...]` row-index patches. If a player is *genuinely* missing from the Sleeper player DB, add an id-keyed row to `seasonPatches[[season]]`; the run-generated `results/<season>/player-patch-log.md` lists any unresolved `player_id`s. The old row-index comments (e.g. `row 1872 -> 1672`) are retained in `ddbmFF.R` purely as a historical changelog — they are intentional, not stale; preserve them.
- **Playoff weeks have teams with `matchup_id = NA`** (eliminated/bye). The matchup self-join uses `na_matches = "never"` so those teams are *not* paired against each other — they get a single no-result row, and the cumulative record uses `cumsum(coalesce(result == "W", FALSE))` so a no-game week doesn't poison the standings. Removing this guard reintroduces phantom playoff matchups (it silently corrupted records for eliminated teams in every season, e.g. 2025 rezzu was 5-12 → corrected to 3-12).
- **Seasons vary in shape — keep it tolerant.** Across the season chain the league has different team counts (2022/2024 = 6 teams, 2023 = 8, 2025 = 10) and different transaction/user column sets. Drop-selects use `-any_of(...)` and `ensure_cols()` backfills missing metadata/settings columns, so don't reintroduce bare `select(-col)` or `select(where(~ !any(is.na(.))))` for optional fields (the latter dropped `team_name` whenever any user left it blank). The per-team chart loop iterates the season's actual users, so a season simply renders fewer per-team charts.
- **Position handling.** `sortPosition <- c("QB","RB","WR","TE","K","DEF")` is the canonical ordering used throughout for sorting and factor levels; `"FLEX"` is synthesized in the `*OfTheWeek` blocks (best leftover RB/WR/TE), it is not a real Sleeper position.
- **Working directory.** `readRDS`/`ggsave` use bare filenames, so the R working directory must be the repo root (RStudio sets this from the `.Rproj`).
- The `.RData*`, `.Rhistory*`, and `.Rproj.user/` files are RStudio session state, not source.
