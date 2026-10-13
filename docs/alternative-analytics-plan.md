# Alternative Analytics: plan

Status: phase 1 built (2026-10-11), uncommitted.  Written 2026-10-10, revised 2026-10-11 after checking the stored data.  Phases 2 and 3 are not started.

## Goal

A section that answers arbitrarily specified questions about a player's real NFL history.  Examples:

- Career receiving yards and yards per game against a specific team.
- Targets per unique quarterback over a receiver's career.
- Splits by season, home or away, game type.

Python webapp only.  No R counterpart, outside `sleepermetrics`, so `verify.py` is unaffected.

## Checked facts (2026-10-11, from the stored raw files)

- **Playoff rows exist in raw.**  The raw `player_stats` / `stats_player` files carry `season_type` (REG and POST, about 250 POST rows a season) back to 1999.  The derived `player_stats` dataset drops them (`_tidy` keeps REG only and removes `season_type`) and starts at 2016, so a playoff-aware table needs no download, only a new derived dataset.
- **Raw `player_stats` has `opponent_team` but no home or away.**  No location, stadium or neutral-site column.  `game_id` appears only in the 2025 and later release.  The derived dataset drops `opponent_team` as well.
- **`opponent_team` is not fully reliable.**  Against the schedule it disagrees on 278 of 158,409 player-games (0.18%, 1999 to 2024), and every disagreement has the opponent equal to the player's own team.  Mostly defensive players and returners; 11 are postseason rows.  Nothing is null.
- **The schedule join is exact once team codes are aliased.**  `player_stats` uses current codes for old seasons (LV, LAC, LA); `schedules` uses the codes of the time (OAK, SD, STL).  With `{OAK: LV, SD: LAC, STL: LA}` all 134,470 player-games for 1999 to 2024 match exactly one game, with no duplicates.
- **`schedules` covers every game type** (REG, WC, DIV, CON, SB, from 1999) and raw `schedules` has a `location` column (Home or Neutral).  103 neutral-site games: 27 Super Bowls, 75 regular season, 1 wild card.  The derived `schedules` dataset trims `location`.

## Design

**Query spec.**  A small structure of measures, a filter, and a group-by:

- Measures: yards, targets, receptions, TDs, carries, and so on.  Each declares how it aggregates (sum, mean, per game, game count).
- Filters: opponent, season range, home or away, game type (REG, WC, DIV, CON, SB).
- Group-by: opponent, season, week, home or away, game type, and (phase 2) quarterback.

One generic filter, group and aggregate function runs every spec.  A new question means adding a measure or a grouping, not a new function.  The measures and groupings are a fixed menu, not free text.

**Base table (phase 1): a new dataset, `player_games`.**  One row per player-game, built from the raw files:

- Raw `player_stats` / `stats_player`, REG and POST, 1999 onward, keeping `season_type`.
- Joined to raw `schedules` on `(season, week, team)` after the alias map above, adding opponent, home or away, neutral site, game type, result, spread and roof.
- **Opponent comes from the schedule, not from `opponent_team`.**  `opponent_team` is kept only as a cross-check column, because it is wrong on 278 rows.
- Home or away: Home when the player's team is the schedule's home team and `location` is Home; Away for the away team; Neutral when `location` is Neutral, regardless of which side is listed as home.
- The shared `player_stats` and `schedules` datasets are left unchanged, so the NFL Stats tab, the profiles and their tests cannot be affected.
- Optional extra measures from `snap_counts`, `ngs_*` and `pfr_*`, joined through the existing identity bridge.  Not in the first menu: name matching can mis-join, and gsis matching is exact only for `player_stats`.

**Pass-play table (phase 2).**  One row per `(game, passer, receiver)`: attempts, completions, yards, air yards, TDs, defending team.  It is derived from the nflverse `pbp` release (raw `pbp` is stored locally and gitignored) and is the only source for targets per QB.  It plugs in as another base table behind the same spec.

**League-free.**  The engine needs no league or season context, so it can sit in the player profile now and become a landing tab later.

## Phases

1. **Dataset, engine and builder, in the Testing tab (built).**  One UI, the builder: search a player by name, then choose measures, a grouping and filters in one form.  The preset picker was dropped.
   - *Measures* sit under Passing, Rushing, Receiving and Fantasy headings, the player's own position first.  Every measure is always listed; one the player has no production in is greyed out and disabled (tooltip "No production for this player").
   - *Results*: Show (total or per game) and Group by (career, opponent, season, home or away, game type, week).
   - *Games*: opponent, site, season range and game type boxes.
   - *Preset chips* (8: Workload, Production, Efficiency, Fantasy output, Recent form, Home and away, By opponent, Playoff run) only fill the form in the browser.  They send no request; Run is the only thing that does.  The measure family a chip picks depends on position, and the opponent always stays Any.
   - The player is picked from search results, so nothing depends on a loaded league.
2. **Pass-play layer** (targets per QB and similar).  The data-loading refactor it depended on is done, so raw `pbp` is already saved once.
3. **Promote the builder** into the player profile as a lazy-loaded section (`GET /player/{id}/alt`) so it adds nothing to the cold profile build.

## Files

Phase 1:

- New: `fantasy-football-4-fun/webapp/sources/nflref/player_games.py`
- Modified: `fantasy-football-4-fun/webapp/sources/nflref/base.py` (registry entry only)
- New: `fantasy-football-4-fun/webapp/alt_analytics.py`
- New: `fantasy-football-4-fun/webapp/templates/_alt_builder.html`
- New: `fantasy-football-4-fun/tests/test_alt_analytics.py`
- Modified: `fantasy-football-4-fun/tests/test_landing_testing.py` (the Testing tab now holds the builder)
- Modified: `fantasy-football-4-fun/tests/test_nflref.py` (dataset tests: alias map, REG and POST kept, opponent from schedule, neutral site)
- Modified: `fantasy-football-4-fun/webapp/app.py` (Testing-tab routes, player search)
- Modified: `fantasy-football-4-fun/webapp/templates/tab_testing.html` (loads the builder panel)
- Modified: `fantasy-football-4-fun/webapp/static/style.css` (chips, measure groups, section layout)
- New data, separate commit: `data/sources/nflverse/player_games/<season>.parquet` (1999 to 2026, built locally)

Phase 2:

- New: `fantasy-football-4-fun/webapp/sources/nflref/pass_plays.py`
- Modified: `fantasy-football-4-fun/webapp/sources/nflref/base.py` (registry)
- New data: `data/sources/nflverse/pass_plays/<season>.parquet`

Phase 3:

- Modified: `fantasy-football-4-fun/webapp/templates/player_profile.html`, `app.py`
- Modified: `CLAUDE.md` (a bullet for the new section)

## Constraints

- Render's free tier is 512MB.  Nothing here may download or parse `pbp` at request time.  The pass-play table is built locally and committed small.
- `player_games` must read its committed snapshots on Render, never rebuild from raw there (same rule as ADP `from_raw`).
- No explanatory prose in result areas; use `title` tooltips (same rule as Player Comparison).
- Results show the covered season range as a tooltip, since the 2026 season is partial.
- Global rules apply: list the files and wait for confirmation before editing, stage named files only, no AI attribution in commits.

## Open questions

- Search scope: limit the builder to QB, RB, WR, TE and FB, or leave kickers and defenders in (their measures are all greyed).  Not decided.
- Position-based defaults beyond the measures (Show per game, Group by Season, a pre-applied chip).  Not decided.
- Does the builder need a saved or shareable query URL?  Not decided.
- Neutral-site games (international games, Super Bowls) are labelled Neutral for Site; confirm that is the wording wanted.

Decided: the 2026 partial season counts in career totals, and the covered range shows as a tooltip.  Results carry no explanatory prose.
