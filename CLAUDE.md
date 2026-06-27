# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

An R analytics project for the "DDBM" Sleeper fantasy football redraft league. It pulls data from the public Sleeper API, reshapes it into tidy frames, and renders a set of `DDBM*.png` charts. There is no package, no test suite, and no build — it is a single script run interactively in RStudio (`FantasyFootball.Rproj`).

## Running

There is no CLI entry point. Work the way the author does:
- Open `FantasyFootball.Rproj` in RStudio and source/step through `ddbmFF.R` top to bottom. Most analysis blocks have a trailing `# view(...)` comment naming the frame to inspect with RStudio's `View()`.
- The package install lines at the top of `ddbmFF.R` are commented out; install them once into your R library before first run (notably `tidyverse`, `httr2`, `ggplot2`, `treemapify`, `tidytext`, `patchwork`, `RColorBrewer`, and the `nflverse` family).
- `getSleeperPlayers.ps1` is a standalone PowerShell helper that downloads the full Sleeper player dump to a JSON file; it is not called by the R script and writes to a hardcoded absolute path under `~/Documents/Data/FantasyFootball`.

Each chart block ends in a `ggsave("results/DDBM*.png", ...)` that writes into the `results/` subdirectory.

## Data flow / architecture

`ddbmFF.R` is the whole program. It runs in three stages:

1. **General Sleeper data** — `callSleeper(objectId, endpoint)` wraps `https://api.sleeper.app/v1`. Player metadata is the largest payload, so it is cached to `sleeperPlayerData.rds` and only re-fetched when the file's mtime is not today (see the `fileDate == today` guard). The raw nested player list is flattened into `playerDF`, then narrowed to `playerMap` (the canonical `player_id -> name/position/team` lookup).

2. **League-specific data** — keyed off the hardcoded league ID `1252770181306929152`. Rosters and users are merged into `userMap` (`roster_id -> user_name`). The script then loops week-by-week over `/matchups/{week}` and `/transactions/{week}` to build the three central frames everything downstream depends on:
   - `matchupResults` — one row per team per week with cumulative W/L, points, and computed league `table_position`.
   - `DDBMRosters` — one row per player per team per week, with `position`, `player_points`, and `is_starter`. This is the workhorse frame.
   - `allTransactionsDF` — adds/drops/trades unnested to one row per player movement.

3. **Analysis + charts** — built from the `Filter*` versions of those frames (`FilterDDBMRosters`, `FilterMatchupResults`, etc.), which drop the in-progress `latestWeek`. Derived frames (`*OfTheWeek`, `playerRosterPerformances`, `playerTradePerformances`, `playerWaiverPerformances`, roster/position breakdowns) feed the `ggplot` blocks.

`FantasyFunctions.R` is a scratch copy holding only `callSleeper` (with `simplifyVector` instead of the `simplifyDataFrame` variant used in `ddbmFF.R`). It is not sourced by the main script — `callSleeper` is defined inline there.

## Things that will bite you

- **Hardcoded week numbers.** `currentWeek` and `latestWeek` are set to `18` in several places, with the live `currentSeason$week` versions commented out next to them. When working with a live/in-progress season you must update these or re-enable the `currentSeason$week` lines, or week loops and the `Filter*` frames will be wrong.
- **Manual data patches by row index.** Around the "Manually add players here" section, `DDBMRosters[<row>, ...] <- list(...)` hardcodes fixes for players the Sleeper player map can't resolve (kickers who changed teams, etc.). These row numbers are specific to the current data snapshot and silently break if upstream data shifts — re-derive them from the `filter(if_any(everything(), is.na))` View block above, don't trust the existing indices.
- **Position handling.** `sortPosition <- c("QB","RB","WR","TE","K","DEF")` is the canonical ordering used throughout for sorting and factor levels; `"FLEX"` is synthesized in the `*OfTheWeek` blocks (best leftover RB/WR/TE), it is not a real Sleeper position.
- **Working directory.** `readRDS`/`ggsave` use bare filenames, so the R working directory must be the repo root (RStudio sets this from the `.Rproj`).
- The `.RData*`, `.Rhistory*`, and `.Rproj.user/` files are RStudio session state, not source.
