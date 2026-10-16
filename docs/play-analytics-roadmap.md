# Play-level analytics: what is built and what is next

Written 2026-10-16.  Python webapp only, outside `sleepermetrics`, so `verify.py` is unaffected.  Every number below was measured against the stored raw nflverse files unless it says it was not.

## What exists

- **`pass_plays`** (2016 on): one row per pass attempt and sack, with the defense's scheme (man or zone, coverage, box, rushers, pressure, time to throw), the targeted receiver's route, the offense formation, and the situation (quarter, down, distance, field position, clock).  Backs the Play filters, the "Vs coverage" and "By route" cards, and the profile page splits.
- **`rush_plays`** (2016 on, built 2026-10-16): one row per carry, including quarterback scrambles and kneel-downs (flagged), with the box, offense and defense personnel, formation, run direction and gap, and the situation plus the score differential.  Backs the Run filters and the four run cards (Vs the box, By run direction, By personnel, By formation).
- Both are built offline from the stored raw play-by-play and participation files, committed per season, and never rebuilt on Render.  A query reads the pass table or the rush table, never both.

## Facts found while building the rush table

- **Official carries include kneel-downs and scrambles.**  Counting every rushing play (two-point tries and deleted plays out) reproduces the player stat files exactly: 100% of players match on carries and touchdowns in 2019, 2022 and 2024.  Leaving the kneels out breaks about 3% of players.  Rushing yards differ by 13 to 19 yards a season out of about 65,000.  That is why the flags are stored and the default total includes them.
- **The personnel columns change shape in 2023.**  Through 2022 `offense_personnel` is a clean count ("1 RB, 1 TE, 3 WR").  From 2023 the strings become detailed positions, and the offense string can even list defenders.  The same file carries `offense_positions` and `defense_positions` (one position per player on the field) from 2023, so the groupings are counted from those lists in that era.  After this the "11" package is 42% to 50% of carries in every season, and "Other" is 6% to 11%.
- **A grouping that is not five linemen plus five eligible players is "Other"**, not folded into a standard code.  A sixth lineman would otherwise read as the same package as a standard one.
- **Defenders in the box and the formation are about 100% filled** on runs and passes for 2016 to 2025.  Run direction is about 96% filled and the gap about 70%.  A blank stays blank.
- **2026 has no participation file** until nflverse publishes it after the postseason, so 2026 carries have no box, personnel or formation.  A query that needs those leaves the season out.
- **A "stacked" box matters for backs.**  Derrick Henry, 2016 to 2025: 5.48 yards per carry against 6 or fewer defenders, 4.93 against 7, 4.42 against 8 or more.

## What else the play-by-play can answer

Coverage is the share of 2024 plays with a value.

### 1. Situation filters on data we already store

`pass_plays` and `rush_plays` already hold quarter, down, distance, field position and clock, but the page offers none of them.  Cards would cover down and distance (third and long, third and short), red zone and goal line, the two-minute drill, and the quarter, for passers, receivers and rushers.  Score state (leading or trailing) is stored for runs and needs adding to `pass_plays`.  No download, only a snapshot rebuild and the filters.  Cheapest item.

### 2. More pass fields

- Throw direction (left, middle, right) and depth (short, deep): 92%.
- Shotgun and no-huddle: 100%.  Whether the quarterback was hit: 100%.
- Yards after the catch: 60%, completions only.
- Three model values: EPA per play (100%), completion over expected (88%), expected yards after the catch (82%).  They are estimates, so a card should label them that way and keep them apart from counts.

These are new columns on `pass_plays`, rebuilt offline from raw.

### 3. Personnel and defensive looks for passes

`offense_personnel` and `defense_personnel` are on every play, so the run-side groupings could apply to passes as well.  The same 2023 change applies, so the same position-list rule is needed.

### 4. Kickers by distance

`kick_distance`, `field_goal_result` and `kicker_player_id` exist in play-by-play, which would give "50 or more yards" splits and kicks by roof or wind.  **Not checked:** how well those columns are filled.  `player_games` already has made kicks by distance band per game.

### 5. FTN charting

A separate nflverse release with play action, RPO, screen passes, pre-snap motion and contested catches.  **Not checked:** the first season and the fill rates.  It would be another per-play download joined the way the participation file is.

## What the data cannot do

- Which defender covered a player.  `pass_defense_1_player_id` is filled on only about 11% of passes (it records who broke the pass up), and tackles for loss on about 9% of carries.
- Routes run by receivers who were not targeted.
- Yards over expected for runs.  The Next Gen rushing release is not play level and is missing 2023.
- Anything from PFF.  There is no public release.

## Suggested order

1. Situation filters (item 1): no new data, and they work for runs and passes at once.
2. The extra pass fields (item 2), in the same snapshot rebuild.
3. Personnel for passes (item 3).
4. Check the fill rates for kickers and FTN (items 4 and 5) before committing to either.
