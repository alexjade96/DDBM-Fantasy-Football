# Alternative Analytics: comparison and game-context filters (plan)

Status: planned, NOT started (on hold at the user's request, 2026-10-13).  Nothing in this plan has been implemented.  Follows `docs/alternative-analytics-plan.md`, whose phases 1 and 3 (builder, landing tab) are built.

## Goal

Two things, built together:

1. **Compare.**  Put two sides next to each other in the builder:
   - the same player under two filter sets (away vs home, wins vs losses), or
   - two players under the same filters.
2. **More game context to filter and compare on:** head coaches, starting quarterbacks, referee, weather, rest, result, betting role, and later teammates and opposing defenders.

Python webapp only, outside `sleepermetrics`, so `verify.py` is unaffected.

## Decisions already made (user answers, 2026-10-13)

- **Two sides only** (A vs B).  No third side.
- **Group by in compare mode is allowed, with one tab per measure** (option c).  Ungrouped compare is one table.  Grouped compare is a tab strip, one tab per ticked measure, switched in the browser with no new request.  Each tab has a row per group with columns Games A, Games B, A, B, Diff.
- **Table only for now.**  No chart.
- **More filters wherever the data supports them**, kept out of the way under a "More filters" disclosure with an active-count badge, so the main filters line stays as it is (Opponent, Site, Seasons, Games).
- **Coaches means head coaches** for now.  Coordinators are parked (see below).
- **Staging:** compare plus the game-level filters first (Stage A), then teammate and opposing-defender presence (Stage B), then play-level data with phase 2 (Stage C).

## The compare feature

**Compare line** under Show: Off, Same player with two filter sets, Two players with the same filters.

**Result table (ungrouped):** one row per measure, a column per side, then Diff and %.  A Games row at the top shows the sample size.  The better side in each row is tinted green and the other red; a tie or a missing value is left plain.  Lower is better for interceptions, field goals missed and PATs missed.

```
                    Away      Home      Diff    %
Games                 41        42
Rec yds /g          78.2      86.9     +8.7   +11%
Catch %             66.1      69.4     +3.3
```

**Rules (the same as the main table):**
- A value that was not recorded stays blank.  No difference is computed against it.
- Ratios are sums over sums.  Long FG stays a maximum.  A percent measure shows its difference in points, with no %.
- A side with no matching games says "No games match".
- Sides are labelled automatically from what differs ("Home", "Away", "vs KC", "2022 to 2024"), or by player name.  Equal labels get "(A)" and "(B)".

**Mode 1, same player and two filter sets:** a second filters block ("Filters B") with the same layout as the first, including More filters.  Quick compare chips fill both blocks in one click and switch the mode on:
- Home vs Away
- Regular season vs Playoffs
- Last 3 seasons vs before
- Wins vs losses
- Favorite vs underdog
- Indoors vs outdoors
- Early vs late season

**Mode 2, two players and the same filters:** a small second-player search next to the player line.  The two players may be different positions; a measure one of them lacks shows a dash.  Because the panel re-renders from the form, the search request includes the form (`hx-include`) so nothing already chosen is lost.

**Engine:** a `run_compare` over the existing menus.  New filters are validated like the old ones (fixed menus; names are matched exactly).  Where two QBs could share a name, the QB filters carry the GSIS id as the value and the name as the label.

## New columns for `player_games` (Stage A)

All come from schedule columns that the join already touches.  The snapshots are rebuilt offline from the stored raw files; the data commit is separate from the code.

| New column | Source (schedule) |
|---|---|
| coach, opp_coach | home_coach, away_coach |
| qb_id, qb, opp_qb_id, opp_qb | home_qb_id, away_qb_id and names |
| referee | referee |
| weekday | weekday |
| temp, wind | temp, wind |
| rest | home_rest, away_rest (own side) |
| div_game | div_game |
| overtime | overtime |

Already present: team, opponent, home_away, game_type, week, season, roof, surface, spread, result.

**Filters this gives:** Team, Head coach, Opponent head coach, Starting QB, Opponent starting QB, Referee, Result (W, L, T), Favorite or underdog (spread below or above 0), Roof, Surface, Weeks (a range), Division game, Day, Temperature (under 40, 40 to 70, over 70), Wind (under 10, 10 to 15, 15+), Rest (short 6 or fewer, normal 7 to 9, long 10+), Overtime.  The coach, QB and referee menus list only names the chosen player actually played with or against.

## Data facts checked (2026-10-13, from the stored files)

- **Schedules carry head coaches for every game 1999 on** (177 distinct coaches), and starting QB ids and names (179 home rows have no QB), referee (208 null, 91 distinct), roof, surface, temp, wind, rest, div_game, overtime, weekday, gametime (from 2000).  193 rows are unplayed games with no score or overtime value.
- **Temp and wind are blank for domes, closed roofs and almost every open roof** (100% null for dome and closed, 99% for open) and 5% null for outdoors.  A temperature filter must exclude blanks, never treat them as a number.
- **Surface values need cleaning:** `grass`, `grass ` (with a trailing space), `dessograss`, `fieldturf`, `astroturf`, `sportturf`, `matrixturf`, `astroplay`, `a_turf` and blank (58).  The builder should offer Grass and Turf buckets and treat blank as unknown.  Roof has 31 blank rows.
- **Rest days:** minimum 4, most are 7 (10,401 of 15,096), then 6 (1,256), 8 (1,012), 14 (832, byes), 4 (614, Thursday after Sunday).
- **Weekday:** Sunday 6,419, Monday 497, Thursday 348, Saturday 259, a handful of others.
- **Division game** is 0 or 1 for every row.

## Coordinators: parked, no clean source

- nflverse has 25 data releases.  None covers coaches or coordinators.  The schedule has head coaches only.
- No open dataset of offensive and defensive coordinators was found.  The only leads are a hand-built Football Perspective Google Doc (by the author's own account not complete), scraping Pro Football Reference coaching pages, or Wikipedia team-season pages.
- Coordinators change mid-season and none of those sources date the change, so a game-level filter would be wrong for those games.  A head coach often calls the plays whatever the coordinator's title.  About 860 team-seasons would need scraping and checking by hand.
- **Rule:** the project does not infer data that does not exist.  If this is ever built it is a curated table limited to recent seasons, marked season-level and unverified.  Decision pending from the user: leave parked, or build that curated table later.

## Stage B: teammates and opposing defenders (game level, not started)

- **Offensive teammate played or sat** (1999 on): derivable from `player_games` itself (same team, same week).  Defenders are not in that table.
- **Opposing defender played or sat** (2016 on): needs a new small committed table, one row per player per game with snaps, built from the play-by-play participation file's defender id lists (GSIS ids, 2016 on).  PFR snap counts are an alternative, but their ids have no crosswalk to GSIS ids in this project, so participation is the cleaner source.
- Raw play-by-play and participation files are stored locally and gitignored, so the table is derived locally and committed small.  Nothing may parse play-by-play on Render.

## Stage C: play level, with phase 2 (not started)

A pass-play table from play-by-play and participation, 2016 on, one row per pass play: passer, receiver, target, catch, yards, air yards, touchdown, defense coverage type (man or zone, Cover 1/2/3/4/6), pass rushers, defenders in the box, route, time to throw, pressure.  This also answers targets per quarterback.

Availability found in the stored participation files:

| Field | Coverage |
|---|---|
| Man or zone, and coverage type (Cover 1, 2, 3, 4, 6 and the like) | 2018 on, on pass plays (about 38% of plays in 2018 to 2022, which is roughly the pass share; man or zone is filled for all plays from 2023).  None for 2016 and 2017. |
| Defenders in box, pass rushers, route | 2016 on (rushers and route are partial before 2023) |
| Defender ids on the field | 2016 on, every play |
| Player names on the play | 2023 on only; ids exist from 2016 |

**Limits:** which defender covered which receiver is not recorded anywhere, only the team's scheme.  Storing every defender on the field for every play would be large, so IDP filters stay game level (Stage B) and only the scheme fields are play level.

## Files (Stage A with the compare feature)

- `fantasy-football-4-fun/webapp/alt_analytics.py`: new filters, `run_compare`, side labels, the better-direction rule, filter option lists.
- `fantasy-football-4-fun/webapp/app.py`: compare and extended filter parameters (extended ones read from the query string so the old signature and its tests stay valid), second-player search.
- `fantasy-football-4-fun/webapp/templates/_alt_builder.html`: Compare line, Filters B, More filters, second-player picker, quick compare chips, comparison table and measure tabs.
- `fantasy-football-4-fun/webapp/static/style.css`: comparison table, tints, tabs, the More filters disclosure.
- `fantasy-football-4-fun/webapp/sources/nflref/player_games.py`: the new columns.
- `fantasy-football-4-fun/tests/test_alt_analytics.py`, `fantasy-football-4-fun/tests/test_nflref.py`.
- `CLAUDE.md` and `docs/alternative-analytics-plan.md`.
- Data, separate commit: rebuilt `data/sources/nflverse/player_games/*.parquet` (about 1 to 2 MB larger).

## Verification to run when built

- Rebuilt snapshots: row counts unchanged; coach, QB and referee spot-checked against the schedule (for example Kelce 2023: Andy Reid, Patrick Mahomes); rest and surface values normalised; blank temp and wind left blank.
- Compare against independent sums from the raw files: a player's Home plus Away must equal his Career, and a result filter must split games exactly.
- In Chromium on port 8000: Kelce home vs away, regular season vs playoffs, wins vs losses; Kelce vs Jefferson with the same filters; a kicker against a receiver (dashes); a grouped compare with its measure tabs; More filters badge counts; a phone width.  The page script is not run by the test suite.
- Full suite.

## Traps to remember

- Missing data is never zero: blanks stay blank through filters, diffs and tints.
- FastAPI `Query(default=[])` parameters leak `Query` objects when a route function is called directly in tests, so tests pass list arguments explicitly (the `_builder()` helper).
- Bash heredocs with nested quotes corrupt files; write patch scripts with the editor tool.
- Jinja autoescapes the literal string in `{{ a if b else "&#9660;" }}`; use `{% if %}` blocks for entities.
- A browser check with Playwright must wait for the htmx swap before reading the page, and a single-match search opens the player without a list.

## Estimates

Compare plus Stage A: about 2.5 hours.  Stage B: about 1 hour.  Stage C with phase 2: 2 to 3 hours.
