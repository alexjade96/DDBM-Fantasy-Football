# Context Handoff

Generated: 2026-09-29T00:00:00-07:00

Purpose:
This document is the authoritative project state for resuming work in a new
Claude Code session.

---

## Goal

Build a shared, cross-source stat-reconciliation layer for the
`fantasy-football-4-fun` webapp so both `team_profile.py` and
`player_profile.py` can consume ONE reconciled per-player-week row instead
of each building its own separate merge/collection logic. Per-week is the
ground truth grain; season totals are `sum(reconciled weekly values)`.

Plan: Phase 1 (extend `stat_reconcile.py` to every metric family) -> Phase 2
(shared `player_week_rows()` assembler) -> Phase 3 (migrate
`team_profile.py`'s LIVE rendering to consume it) -> Phase 4 (migrate
`player_profile.py`, **NOT STARTED**).

A separate, small hover-flyout declip fix (CSS/JS only, no Python) was also
completed and is now committed alongside Phases 1-3.

---

## Current State

**Committed.** All of Phases 1-3 plus the flyout fix landed in one commit
this session (see `git log -1` for the hash/message). Working tree is clean
relative to that commit as of this handoff.

Files in that commit:
- `fantasy-football-4-fun/webapp/stat_reconcile.py` -- Phases 1+2.
- `fantasy-football-4-fun/webapp/team_profile.py` -- Phase 3 adapters live,
  `_full_name`/`_STAT_FULL_NAMES` tooltip feature.
- `fantasy-football-4-fun/webapp/app.py` -- registered `full_name` as a
  Jinja global.
- `fantasy-football-4-fun/webapp/templates/_teamstat_macros.html` --
  `title=` attribute on `position_group_table`'s header cells.
- `fantasy-football-4-fun/webapp/static/style.css` -- `.stat-flyout-declipped`.
- `fantasy-football-4-fun/webapp/static/table-sort.js` -- new
  `window.SMStatFlyouts` shared helper.
- `fantasy-football-4-fun/webapp/templates/index.html` -- wires
  `prepStatFlyouts`.
- `fantasy-football-4-fun/webapp/templates/_team_game_detail.html` -- binds
  `SMStatFlyouts` per game-swap root.
- `fantasy-football-4-fun/webapp/templates/player_profile.html` -- now
  loads `table-sort.js`, binds `SMStatFlyouts` on `document`.
- `fantasy-football-4-fun/tests/test_stat_reconcile.py` -- ~45 new tests.
- `fantasy-football-4-fun/tests/test_team_profile.py` -- ~15 new tests.

**Test suite: 586 passed, 0 failed** (`fantasy-football-4-fun/venv/Scripts/
python.exe -m pytest tests/ -q`).

CI has NOT been run this session (nothing pushed to a remote).

---

## Architecture

### 1. `stat_reconcile.py` -- shared reconciliation layer (Phases 1+2)

`_ALL_METRIC_MAPS = {**_METRIC_MAPS, **_EXTRA_METRIC_MAPS}` covers
passing/rushing/receiving plus defense/defense_team/snaps_offense/
snaps_defense/snaps_special_teams/routes/kicking. `METRIC_LABELS`
deliberately NOT extended (still "Passing"/"Rushing"/"Receiving" only --
its own docstring claims that scope and nothing iterates it in a template).

**`reconcile_season(rows_by_source, metric, season_only_rows=None,
season_only_source="")`** -- sum-then-check: reconciles each week first,
then sums. Different from the pre-existing `aggregate_weeks` (sums each
source's raw weeks first, then votes among sums -- two independent passes;
has NO live caller, kept dormant, do not remove without fresh confirmation).
`_MAX_STATS`/`_OMIT_STATS`/`_RECOMPUTE_STATS` match `team_profile.py`'s
existing season-aggregation precedent (`_kicker_season_totals`,
`_def_season_totals`/`_DEF_SEASON_EXCLUDED_KEYS`). **Not yet consumed by
any live page** -- Phase 4's first real consumer.

**`player_week_rows(role_rows, position_of=None)`** -- merges every metric
family's per-week reconciled rows into one dict per (player, week).
Returns `(player_rows, team_rows)`. Key internals: `_ROLE_ROWS_KEY`
(explicit table, source key-naming genuinely differs per source, not one
formula), `_ROLE_POSITION_KEY`, two-pass position resolution (fills every
role's real position source across ALL roles before any `position_of`
fallback is consulted -- fixes a real two-way-player ordering bug),
`_attach_pfr_extra` (PFR's non-overlapping extra columns joined directly by
name, mirroring `team_profile._attach_pfr_extra`'s per-game logic).

### 2. `team_profile.py` -- Phase 3, LIVE switch, BOTH paths still exist

`_offense_players_via_shared`/`_defense_players_via_shared` -- adapters
translating `player_week_rows`'s generic shape into the exact shape
`_build_position_groups` expects. **`_offense_position_groups`/
`_defense_position_groups` call these adapters** (this is what's live on
`/team/{abbr}`, confirmed correct by the user in a live browser check).

**`_merge_offense_players`/`_merge_defense_players` are NOT dormant and
NOT deleted -- they are STILL LIVE**, called directly by
`player_profile.py`'s `_game_log` (see Important Discoveries below; this
was found mid-session and is the reason Phase 4 exists as separate,
required work before any deletion). Do not delete either function without
a fresh, explicit go-ahead, and only once `player_profile.py` no longer
calls them.

### 3. Tooltip feature (`_full_name`)

`team_profile._STAT_FULL_NAMES` (~70 entries) + `_full_name(key)` --
hover-tooltip text for every abbreviated column header in
`position_group_table` (the only live consumer of abbreviated `(key,
label)` headers). Keyed by real stat KEY (not label text -- several labels
are genuinely ambiguous, e.g. "TD" means different things in different
tables). Registered as Jinja global `full_name`; wired into
`_teamstat_macros.html`'s `<th title="{{ full_name(key) }}">`.

### 4. Hover-flyout declip fix (this session, CSS/JS only)

`.stat-cell`/`.stat-flyout` (the per-source breakdown that appears on
hovering a reconciled stat cell) is `position: absolute`, and its
containing tables (`.tablewrap`/`.dt-detail`) use `overflow-x: auto`,
which per the CSS spec also clips `overflow-y` -- a flyout near a table
edge could render visibly cut off. This was a documented "known, accepted
limitation" before this session.

Fixed with `window.SMStatFlyouts.bind(root)` in `table-sort.js` (shared,
since all three consuming pages need it): on hover/focus it measures the
flyout at its normal position; only if an edge would be clipped by a
scroll ancestor or the viewport does it switch the flyout to
`.stat-flyout-declipped` (`position: fixed`, JS-computed/clamped
top/left, flips below the cell if no room above). CSS still owns
show/hide entirely -- the JS never controls whether a flyout appears,
only where it lands when it would otherwise be cut off.

Wired into:
- `index.html` -- `prepStatFlyouts()` calls `SMStatFlyouts.bind(document)`,
  hooked to `htmx:afterSwap` plus an initial call.
- `_team_game_detail.html` -- binds per `#gs-panels-{{ game_key }}` root,
  matching that file's existing per-swap script convention (no reliable
  `document.currentScript` under htmx's script re-execution).
- `player_profile.html` -- did NOT load `table-sort.js` before this
  session; now does, and binds on `document` via the script's own
  `onload` handler (delegation means lazily-loaded Game log rows need no
  re-bind).

Verified via direct Jinja template renders (not just syntax checks) that
the new markup and script calls actually appear in real output. **No
browser was used** (none available in this environment) -- the clamping
math itself was not visually confirmed.

---

## Important Decisions

- **"Sum-then-check" (Option A) over "vote twice"** -- season total is
  always exactly `sum(reconciled weekly values)`.
- **All metric families reconciled, not just the original 3** -- a future
  second source for any single-source family needs zero new plumbing.
- **Promote `stat_reconcile.py` to the shared layer**, not a new module.
- **Compute on-demand, no new persistence/caching layer** -- reuses the
  existing per-request TTL cache pattern (`_PROFILE_CACHE`).
- **`METRIC_LABELS` NOT extended** to the new families (Jinja global,
  docstring scope preserved).
- **Phase 3 adapter approach over renaming Phase 2's role keys** -- keeps
  the shared assembler page-agnostic.
- **Snap-count and PFR-def cells gaining a hover-flyout** (real, visible
  behavior change) -- explicitly accepted by the user, twice.
- **A punter's real position (e.g. "P") now shown instead of "Other"**
  (real, visible behavior change) -- explicitly accepted.
- **`_merge_offense_players`/`_merge_defense_players` are kept, not
  deleted** -- explicit user decision this session, after discovering
  `player_profile.py` still depends on them directly. Revisit only once
  Phase 4 migrates `player_profile.py` off them.
- **Tooltips keyed by real stat KEY**, not a simpler global label
  glossary -- per-column accuracy over simplicity.
- **Flyout declip fix implemented as a shared `table-sort.js` helper**
  (`SMStatFlyouts`), not duplicated per page -- matches this codebase's
  own established precedent (`SMTableSort`) for logic three different
  pages (`index.html`, `team_profile.html`, `player_profile.html`) all
  need, one `#panel`-based and two `#panel`-less.

---

## Important Discoveries

- **The current NFL season is 2026** (`sleepermetrics.league.nfl_state()`).
  All real-data verification for Phases 1-3 used 2026, not a prior season.
- **`team_profile.py` already had more sophisticated season-aggregation
  precedent** than the first `reconcile_season` design accounted for
  (`_kicker_season_totals`, `_def_season_totals`/
  `_DEF_SEASON_EXCLUDED_KEYS`) -- `reconcile_season`'s special-case sets
  were built to match this, not invent a new convention.
- **`role_rows`'s real key-naming convention genuinely differs per
  source** -- fixed with the explicit `_ROLE_ROWS_KEY` table rather than a
  formula.
- **CRITICAL, found this session: `player_profile.py`'s `_game_log`
  function calls `tp._merge_offense_players`/`tp._merge_defense_players`
  DIRECTLY** (`webapp/player_profile.py` lines ~833/838), not the
  `_via_shared` adapters. This was NOT known when the prior handoff
  described these two functions as "dormant" -- they are not. Deleting
  them without first migrating `player_profile.py` would break the
  player-profile page's game log entirely. This is now the concrete,
  required shape of Phase 4: `player_profile._game_log` must be switched
  to `_offense_players_via_shared`/`_defense_players_via_shared` (or a
  shared `player_week_rows()`-based path) before
  `_merge_offense_players`/`_merge_defense_players` can ever be deleted.
- **`reconciled_table` (a macro in `_teamstat_macros.html`) is dead code**
  -- confirmed via grep, no template calls it.
- **`METRIC_LABELS` is a registered Jinja global but nothing currently
  iterates it in any template** -- confirmed before deciding not to extend
  it.

---

## Constraints

- Always use `fantasy-football-4-fun/venv/Scripts/python.exe` for any
  ad-hoc verification script or pytest invocation.
- Never manage the dev server directly (standing memory rule) -- verify
  via direct Python function/route/template calls.
- Confirm the exact file list with the user before ANY commit (global
  CLAUDE.md rule) -- done for this session's commit.
- No AI/Claude/Anthropic attribution in commits (global CLAUDE.md rule).
- Real-data verification must use the CURRENT season (2026), not a prior
  one -- standing practice for this project.
- Every real behavior change found via comparison must be surfaced and
  explicitly confirmed with the user before being accepted -- do not
  silently absorb a discovered behavior difference as "probably fine."
- **Do not delete `_merge_offense_players`/`_merge_defense_players`**
  until `player_profile.py`'s `_game_log` no longer calls them AND the
  user gives a fresh, explicit go-ahead.
- Don't remove `aggregate_weeks` without a fresh, explicit go-ahead.

---

## Rejected Approaches

- **Renaming Phase 2's `player_week_rows` role keys to match
  `team_profile.html`'s existing template vocabulary** -- rejected in
  favor of a thin adapter in `team_profile.py`.
- **A single global label-keyed tooltip glossary** -- rejected once shown
  the real ambiguity (TD/INT/Snaps mean different things in different
  tables).
- **Full upfront implementation plan before any code** -- user chose a
  smaller proof-of-concept first.
- **Matching OLD behavior exactly for the punter-position edge case** --
  declined in favor of the more-accurate "P" resolution.
- **Keeping pfr_def cells display-identical (suppressing the new hover
  flyout)** -- declined, same acceptance already given to snap cells.
- **Deleting `_merge_offense_players`/`_merge_defense_players` this
  session** -- offered, then blocked once the `player_profile.py`
  dependency was found; user confirmed to keep both functions rather than
  expand scope to migrate `player_profile.py` in the same pass.

---

## Remaining Work

1. [ ] **Phase 4: migrate `player_profile.py`** to consume the shared
   reconciliation layer. Concretely: switch `_game_log`'s two call sites
   (`tp._merge_defense_players(stats, [], abbr="")` and
   `tp._merge_offense_players(stats, [...])`) to
   `tp._defense_players_via_shared`/`tp._offense_players_via_shared` (or a
   more direct `player_week_rows()` call, if that turns out cleaner once
   in the code) -- NOT STARTED. Budget for finding and fixing real bugs
   via exhaustive real-league comparison, same discipline Phase 3 required
   (two real bugs were found there purely by comparison, not design
   review alone).
   - This is a genuine behavior change (player-profile gains real
     `agreed`/`sources` disagreement data it doesn't have today) --
     confirm with the user before it lands.
   - `scope_profile()`'s season-total path currently filters raw rows by
     season with zero reconciliation -- `reconcile_season()`'s first real
     consumer, if that becomes part of this phase too.
   - Existing tests keyed to `_game_log`'s current shape
     (`test_player_profile.py`, `test_player_page.py`) will need
     rewriting, verified against real running code first.
2. [ ] **Only after Phase 4 lands and `player_profile.py` no longer calls
   them, with fresh explicit confirmation**: delete
   `_merge_offense_players`/`_merge_defense_players` from
   `team_profile.py`.
3. [ ] **Housekeeping, only after Phase 4 lands and only with fresh
   confirmation**: `aggregate_weeks()` becomes fully superseded by
   `reconcile_season()` -- still don't remove it without asking. Revisit
   whether `team_profile.py`'s role-split helpers
   (`_split_snap_counts`/`_split_player_stats`/`_split_sleeper_stats`)
   should move into `stat_reconcile.py` if `player_profile.py` ends up
   needing to duplicate them.
4. [ ] **CLAUDE.md was not updated** despite the scope of Phases 1-3 (a
   new shared reconciliation layer, a live rendering path switch, real
   accepted behavior changes) -- consider updating it with a dense summary,
   following this codebase's own established documentation density
   convention, once Phase 4 is far enough along that the summary can
   describe the whole migration rather than a half-finished one.

---

## Risks / Unknowns

- **No browser confirmation of the flyout declip fix's actual visual
  behavior** -- the user separately confirmed the LIVE team-profile page's
  Phase 3 data (the reconciliation switch) looks correct, but the flyout
  declip JS itself (added after that confirmation, in the same session)
  has only been verified via direct template renders showing the right
  markup/script calls are present, not an actual hover-and-watch-it-move
  browser check.
- **The real-data comparison scripts used to verify Phase 3 were ad-hoc,
  not committed as permanent test fixtures** -- the FINDINGS are captured
  as regression tests, but the exhaustive "sweep all 32 teams x 3 weeks"
  comparison itself is not a re-runnable artifact.
- **Phase 4 (player_profile.py) is completely unstarted** -- no adapter
  switch, no comparison script, no real-data verification has begun.
  Treat any claim about how it should be migrated as a plan, not a
  verified fact, until that work actually happens.
- **`_merge_offense_players`/`_merge_defense_players` being genuinely live
  (not dormant) was discovered only this session, mid-deletion-attempt**
  -- worth double-checking there are no OTHER call sites of these two
  functions (or of `_build_position_groups`, `_sleeper_position_map`, etc.)
  outside `team_profile.py`/`player_profile.py` that haven't been swept
  for yet, before assuming the dependency map is fully known.

---

## Reference Documents

- `fantasy-football-4-fun/webapp/stat_reconcile.py` -- read the module's
  own header comment and the header comments on `_EXTRA_METRIC_MAPS`,
  `_MAX_STATS`/`_OMIT_STATS`/`_RECOMPUTE_STATS`, `_ROLE_ROWS_KEY`, and
  `player_week_rows` itself before touching Phase 1/2's code again.
- `fantasy-football-4-fun/webapp/team_profile.py` -- read
  `_offense_players_via_shared`/`_defense_players_via_shared`'s docstrings
  AND `_merge_offense_players`/`_merge_defense_players`'s own docstrings
  (both now explicitly say "STILL LIVE... not safe to delete until
  `player_profile.py` is migrated too") before touching any of this again.
- `fantasy-football-4-fun/webapp/player_profile.py` -- read `_game_log`'s
  own docstring and its two `tp._merge_*` call sites (~line 830-840)
  before starting Phase 4.
- `fantasy-football-4-fun/webapp/static/table-sort.js` -- read
  `SMStatFlyouts`'s own header comment before touching the flyout declip
  fix again.
- `fantasy-football-4-fun/tests/test_stat_reconcile.py` /
  `fantasy-football-4-fun/tests/test_team_profile.py` -- Phase 1-3
  regression tests, including the two real-bug regression tests and the
  self-updating `test_full_name_covers_every_real_key_in_every_live_
  column_spec` guard.
- `CLAUDE.md` -- not yet updated for any of this work; see Remaining Work
  item 4.

---

## Resume Prompt

Review this handoff completely before doing any work.

Review all files listed under Reference Documents, especially
`player_profile.py`'s `_game_log` function and its two `tp._merge_*` call
sites -- this is the concrete starting point for Phase 4.

Confirm starting state with `git log --oneline -3` and
`fantasy-football-4-fun/venv/Scripts/python.exe -m pytest tests/ -q`
(should show 586 passed, 0 failed) before assuming anything.

The immediate next action is Phase 4: migrate `player_profile.py`'s
`_game_log` off `_merge_offense_players`/`_merge_defense_players` onto
`_offense_players_via_shared`/`_defense_players_via_shared` (or a more
direct `player_week_rows()` call). Budget for finding and fixing real bugs
via exhaustive real-league comparison, the same discipline Phase 3
required. This is a genuine behavior change (player-profile gains real
`agreed`/`sources` disagreement data) -- confirm with the user before it
lands.

Only once Phase 4 is confirmed correct in practice AND the user gives a
fresh, explicit go-ahead should `_merge_offense_players`/
`_merge_defense_players` be deleted from `team_profile.py`. Do not delete
`aggregate_weeks` without a fresh, explicit go-ahead either.

Always use `fantasy-football-4-fun/venv/Scripts/python.exe` for any
ad-hoc verification, and never manage the dev server directly. Any new
real-data verification must use the CURRENT NFL season (check via
`sleepermetrics.league.nfl_state()`), not a prior one.
