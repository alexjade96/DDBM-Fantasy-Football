# Alternative Analytics: plan

Status: planned, not started.  Written 2026-10-10.  Nothing in this plan has been implemented.

## Goal

A section that answers arbitrarily specified questions about a player's real NFL history.  Examples:

- Career receiving yards and yards per game against a specific team.
- Targets per unique quarterback over a receiver's career.
- Splits by season, home or away, game type.

Python webapp only.  No R counterpart, outside `sleepermetrics`, so `verify.py` is unaffected.

## Design

**Query spec.**  A small structure of measures, a filter, and a group-by:

- Measures: yards, targets, receptions, TDs, carries, snap share, and so on.  Each declares how it aggregates (sum, mean, per game, game count).
- Filters: opponent, season range, home or away, game type (REG, WC, DIV, CON, SB).
- Group-by: opponent, season, week, home or away, and (phase 2) quarterback.

One generic filter, group and aggregate function runs every spec.  A new question means adding a measure or a grouping, not a new function.  The measures and groupings are a fixed menu, not free text.

**Base table (phase 1).**  One row per player-game:

- `player_stats` (weekly box score, keyed by `recent_team`).
- Joined to `schedules` on `(season, week, team)` to add opponent, home or away, game type, result, spread and roof.  `player_stats` has no opponent column, so the join is required.
- Optional extra measures from `snap_counts`, `ngs_*` and `pfr_*`, joined through the existing identity bridge (gsis id first, normalised name and position as fallback).

**Pass-play table (phase 2).**  One row per `(game, passer, receiver)`: attempts, completions, yards, air yards, TDs, defending team.  It is derived from the nflverse `pbp` release and is the only source for targets per QB.  It plugs in as another base table behind the same spec.

**League-free.**  The engine needs no league or season context, so it can sit in the player profile now and become a landing tab later.

## Phases

1. **Engine and opponent splits, prototyped in the Testing tab.**  Two UIs side by side for comparison:
   - *Preset picker*: ready-made questions ("Production vs. an opponent", "Splits by season") with one or two inputs each.
   - *Builder*: dropdowns for measure, filter and group-by.  Meaningless combinations are hidden or disabled.
   - Likely outcome: the builder with a few preset shortcuts that fill it in.  Both go through the same code path.
   - Input is a player id or name search, so the prototypes do not depend on a loaded league.
2. **Pass-play layer** (targets per QB and similar).  Depends on the data-loading refactor so raw `pbp` is saved once.  See `docs/data-loading-refactor-plan.md`.
3. **Promote the winning UI** into the player profile as a lazy-loaded section (`GET /player/{id}/alt`) so it adds nothing to the cold profile build.

## Files

Phase 1 (Testing-tab prototypes):

- New: `fantasy-football-4-fun/webapp/alt_analytics.py`
- New: `fantasy-football-4-fun/webapp/templates/_alt_preset.html`
- New: `fantasy-football-4-fun/webapp/templates/_alt_builder.html`
- New: `fantasy-football-4-fun/tests/test_alt_analytics.py`
- Modified: `fantasy-football-4-fun/webapp/app.py` (Testing-tab routes, player input)
- Modified: `fantasy-football-4-fun/webapp/templates/tab_testing.html` (currently an empty shell)
- Modified: `fantasy-football-4-fun/webapp/static/style.css` (only if needed)

Phase 2:

- New: `fantasy-football-4-fun/webapp/sources/nflref/pass_plays.py`
- Modified: `fantasy-football-4-fun/webapp/sources/nflref/base.py` (registry)
- New data: `data/sources/nflverse/pass_plays/<season>.parquet`

Phase 3:

- Modified: `fantasy-football-4-fun/webapp/templates/player_profile.html`, `app.py`
- Modified: `CLAUDE.md` (a bullet for the new section)

## Constraints

- Render's free tier is 512MB.  Nothing here may download or parse `pbp` at request time.  The pass-play table is built locally and committed small.
- No explanatory prose in result areas; use `title` tooltips (same rule as Player Comparison).
- Global rules apply: list the files and wait for confirmation before editing, stage named files only, no AI attribution in commits.

## Open questions

- Which measures belong in the first menu?  Start with the `player_stats` columns and add others on request.
- Should kickers and team defenses be supported?  Probably not in phase 1.
- Does the builder need a saved or shareable query URL?  Not decided.
