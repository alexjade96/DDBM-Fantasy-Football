# Context Handoff

Generated: 2026-09-18T10:48:00-07:00

Purpose:
This document is the authoritative project state for resuming work in a new
Claude Code session.

---

## Goal

Built a new **Player Comparison** feature (renamed from "Position
Comparison" this session -- see below): a league-free landing-page tab
(alongside ADP Comparison / NFL Stats) that compares same-position real-NFL
players against the field and against each other, week by week -- built for
in-season lineup decisions. Shipped, tested against real data end to end,
and iterated through several rounds of user-reported bugs, each fixed and
re-verified with a real browser (Playwright), not just unit tests.

**This session's follow-up work (still uncommitted, same working tree):**
renamed the whole feature from "Position Comparison" to "Player Comparison"
per explicit user request ("this function is meant to be a player
comparison tool... rb1 on team a vs rb2 on team b is essentially a player
comparison in the same position"), and changed the dashboard header's
league/user lookup button from "Load" to "Search" to match the landing
page's already-"Search" equivalent. Verified via `git diff` before starting
that every renamed line was newly added this feature's own build (zero
matching removed lines in the modified files, and the 6 renamed files were
untracked with no prior git history) -- nothing pre-existing was touched.

---

## Current State

- Branch: `main`. **Nothing from this session (or the prior session) is
  committed** -- all work is uncommitted in the working tree on top of
  `99c8376`.
- **Files (new, this feature -- renamed a second time this session, see
  below)**:
  - `fantasy-football-4-fun/webapp/player_compare.py` (was
    `position_compare.py`) -- league-free data layer:
    `player_field_compare()` (was `position_field_compare`), `player_trend()`
    (was `position_trend`).
  - `fantasy-football-4-fun/webapp/templates/_playercompare_compare.html`
    (was `_poscompare_compare.html`) -- tab shell (controls + leaderboard
    container + chart container + JS).
  - `fantasy-football-4-fun/webapp/templates/_playercompare_table.html`
    (was `_poscompare_table.html`) -- leaderboard fragment with per-row
    checkboxes (`data-playercompare-pick`, was `data-poscompare-pick`).
  - `fantasy-football-4-fun/webapp/templates/_playercompare_charts.html`
    (was `_poscompare_charts.html`) -- the two comparison-chart `<img>`
    panels fragment.
  - `fantasy-football-4-fun/tests/test_player_compare.py` (was
    `test_position_compare.py`) -- data-layer + chart-function tests (31
    tests, all renamed, all passing).
  - `fantasy-football-4-fun/tests/test_playercompare_landing.py` (was
    `test_poscompare_landing.py`) -- route tests (13 tests, all renamed, all
    passing).
- **Files (modified, this feature)**:
  - `fantasy-football-4-fun/webapp/app.py` -- `/playercompare` (was
    `/poscompare`), `/playercompare/data`, `/playercompare/compare` routes;
    `player_overlay` (was `position_overlay`) branch in the league-free part
    of `/chart/{name}` (before `pick()`). Three comments describing the
    historical route-collision bug still literally say `/chart/poscompare`
    on purpose -- that's the name the bug actually had; left as accurate
    history, same convention as the ddbmFF.R row-index comments.
  - `fantasy-football-4-fun/sleepermetrics/plots.py` -- `plot_player_
    overlay()` (was `plot_position_overlay`; shared snapshot/trend chart),
    `_place_radar_labels()`, `_format_stat_value()`,
    `_radar_label_radius`-related constants (docstrings/comments updated to
    the new function name, logic untouched).
  - `fantasy-football-4-fun/webapp/static/style.css` -- `#playercompare-
    picks`/`#playercompare-count`/`#playercompare-compare-btn` selectors
    (were `#poscompare-*`).
  - `fantasy-football-4-fun/webapp/templates/home.html` -- nav button
    "Player Comparison" (was "Position Comparison"), `hx-get="/playercompare"`
    (was `/poscompare`); also carries this session's unrelated prior-session
    "Look up a league" label removal and "Find" -> "Search" (already done
    before this session started).
  - `fantasy-football-4-fun/webapp/templates/index.html` -- header lookup
    button `#lookup-go` changed **"Load" -> "Search"** (this session, user
    request) to match the landing page's already-"Search" equivalent; brand
    tooltip text updated to say "Player Comparison".
- **Scope of the rename, verified before starting**: grepped the whole
  `fantasy-football-4-fun/` tree for `poscompare`/`position_compare`/
  `position_overlay`/"Position Comparison" (11 files matched) and confirmed
  via `git diff` that every match was a newly-ADDED line in this feature's
  own uncommitted build (zero matching REMOVED lines in any modified file;
  the 6 renamed files were untracked with no prior commit history). Nothing
  pre-existing was touched. Explicitly left alone as genuinely generic /
  not-this-feature: `nflref/summary.py`'s `percentile_profile()` (shared
  with the existing player-profile radar chart) and `plots.py`'s
  `plot_player_radar()`/`_radar_axes()`/`_place_radar_labels()`/
  `_format_stat_value()` (generic radar-drawing helpers used by more than
  just this feature) and `player_compare.py`'s own `_DEFAULT_TREND_KEYS`
  (genuinely per-position defaults, not the feature name).
- **NOT this session's work -- pre-existing/concurrent, still present,
  untouched by this session** (see Risks/Unknowns -- flag before any commit):
  modified: `_shell_sync.html`, `_user_leagues.html`, `_landing_start.html`,
  `tab_testing.html`; untracked: `test_lookup.py`, `test_season_history.py`,
  `test_user_leagues.py`, `webapp/templates/tab_season_history.html`.
  `data/sources/adp/2026.json` modified -- benign live-ADP-refetch drift,
  same as prior sessions; `git checkout` it before a commit unless wanted.
- Full pytest (`fantasy-football-4-fun/`), re-run AFTER this session's
  rename: **377 passed**, same 2 pre-existing failures as before the rename
  (`test_ffadp.py::test_export_xlsx_route` -- missing `openpyxl`;
  `test_nflref.py::test_snapshot_serves_when_network_gone` -- pre-existing
  `KeyError`). Identical pass count to the prior session's own run,
  confirming the rename introduced no regressions.
- `verify.py` (R<->Python parity) NOT re-run -- nothing touched is in the
  parity-diffed contract (`player_compare.py`/`app.py`/webapp templates are
  all outside `sleepermetrics`' diffed surface; `plots.py` additions are
  webapp-only chart functions, same precedent as `plot_player_radar`).

---

## Architecture

**Naming note:** this feature was called "Position Comparison" through its
entire build (dashboard-tab pivot, landing-tab rebuild, radar-label solver)
and was renamed to **"Player Comparison"** only in this session's own
follow-up work, per explicit user request. Every name below (routes,
functions, files, CSS ids) is given in its CURRENT (post-rename) form;
where the history below refers to a bug or decision by the name it had AT
THE TIME (e.g. "`/chart/poscompare` registered after `/chart/{name}`"),
that historical name is preserved on purpose -- see Important Discoveries.

### 1. Player Comparison is genuinely league-free (major pivot mid-build)

- Originally built as a **dashboard tab** (within-team depth chart +
  fantasy-roster comparison, needing a loaded league's `roster_detail()`).
  **Fully reverted** after the user clarified a league only ever added a
  scoring-format distinction, and that's a separate future feature -- see
  Rejected Approaches.
- Rebuilt as a **landing-page tab**, same family as ADP Comparison / NFL
  Stats: `GET /playercompare` (shell), `GET /playercompare/data`
  (leaderboard fragment), `GET /playercompare/compare` (the two-chart HTML
  fragment), `GET /chart/player_overlay` (the actual PNG, dispatched in
  `app.py`'s `chart()` BEFORE `pick()`, exactly like the existing
  `PLAYER_CHARTS` branch -- see Important Discoveries for why this route
  naming matters).
- `webapp/player_compare.py`'s functions are already league-free
  (`player_field_compare`/`player_trend` never took a `Season`); the
  removed `roster_position_group()` was the only league-scoped piece.
- No Scoring (std/half/ppr) control yet -- deliberately deferred (see
  Rejected Approaches). `player_leaderboard()`/`percentile_profile()` are
  PPR-only today; the control would be decorative until a per-format
  leaderboard aggregation exists.

### 2. Leaderboard -> checkbox -> "Compare selected" -> two charts

- `_playercompare_table.html`: Sleeper-sourced leaderboard (`source="sleeper"`
  forced, not a toggle -- the checked `player_id`s feed straight into
  `player_field_compare`/`player_trend`, both keyed on the real Sleeper
  id), one checkbox per row (`data-playercompare-pick`, `value=player_id`,
  `data-label=player name`).
- `_playercompare_compare.html`'s inline JS: `wireCheckboxes()` re-binds on
  every htmx leaderboard swap; "Compare selected" button (bare `<button>`,
  NOT `.nfl-apply` -- see Important Discoveries) collects checked ids/labels
  comma-joined and fires `window.htmx.ajax('GET', '/playercompare/compare', ...)`.
- `/playercompare/compare` (HTML fragment, in `app.py`) renders
  `_playercompare_charts.html`: two `<img src="/chart/player_overlay?...">`
  tags (snapshot radar + trend line), each with `mode=`/`player_ids=`/
  `player_labels=` query params.
- `/chart/player_overlay` (PNG route) calls `plots.plot_player_overlay`.

### 3. `plots.plot_player_overlay(players, stat_keys, mode, title, position)`

- `players` = `{label: data}`. `mode="snapshot"`: `data` is a
  `percentile_profile()`-shaped dict, drawn as a radar (`_radar_axes`,
  shared with `plot_player_radar`). `mode="trend"`: `data` is a
  `player_trend()`-shaped list, drawn as a Cartesian line (one stat,
  `stat_keys[0]`, per player).
- Colors via the existing `palette()` (stable per label).
- **Radar shows actual numbers per spoke**: `"{value} ({percentile})"` per
  player per stat, via `_place_radar_labels()` -- a real polar-coordinate
  collision solver, the polar counterpart to the existing Cartesian
  `_place_labels`. See Important Discoveries for why a naive radial-push
  formula was structurally insufficient and had to be replaced.

---

## Important Decisions

- **Scope pivot: dropped the fantasy-roster/within-team dashboard-tab
  design entirely, rebuilt as league-free.** User's own words: "the only
  league-type purpose is more of a scoring distinguishment... but players
  themselves can be compared already at the baseline." This was a full
  revert-and-rebuild mid-session, not an incremental adjustment -- see
  Rejected Approaches for exactly what was removed.
- **No Scoring control shipped, despite being partially built once.**
  Removed after confirming `player_leaderboard()`/`percentile_profile()`
  have no per-format variant -- a control that changes nothing is worse
  than no control. The user confirmed the INTENT (compare a player's value
  across std/half/ppr) is real future work, just not built yet. The seam is
  commented in `app.py` above the `/playercompare` routes.
- **Renamed "Position Comparison" -> "Player Comparison" (this session,
  after the feature was otherwise complete).** User's own words: "this
  function is meant to be a player comparison tool; any downstream
  functions or files that supplement it are meant to follow it, the
  exceptions being position comparison functions (e.g. rb vs wr) / rb1 on
  team a vs rb2 on team b is essentially a player comparison in the same
  position." Scope was verified via `git diff` before starting (see Current
  State) then executed as a full rename across the module, its two
  functions, all three routes, the chart function + its dispatch key, all
  three templates, CSS ids, the nav label, and both test files -- 11 files
  total. Deliberately left alone: `nflref.summary.percentile_profile`
  (generic, shared with `plot_player_radar`), `plot_player_radar`/
  `_radar_axes`/`_place_radar_labels`/`_format_stat_value` (generic
  radar-drawing helpers, not named after this feature), and
  `player_compare.py`'s own `_DEFAULT_TREND_KEYS` (genuinely per-position
  stat defaults). Three comments in `app.py` describing the historical
  route-collision bug still literally read `/chart/poscompare` -- that is
  the name the bug actually had, kept as accurate history rather than
  rewritten, same convention as the ddbmFF.R row-index comments.
- **Radar labels show BOTH raw value and percentile** (user's explicit
  choice among value-only / percentile-only / both), and **all 14 stats
  stay labeled** rather than trimming to a smaller set (user's explicit
  choice: "label all and pad/distinguish labels to make readable") --
  this is what forced building the real polar collision solver rather than
  a simpler fixed-offset or a reduced stat set.
- **"Compare selected" sits beside "Load", not below the leaderboard** --
  moved per user request, required removing `.nfl-apply` from the new
  button (that class's `margin-left:auto` would have split the two buttons
  apart with a gap instead of sitting flush).

---

## Important Discoveries

- **A route registered under `/chart/{name}` (a path-param catch-all) will
  silently swallow ANY later route registered as a more specific literal
  path under the same prefix**, e.g. `/chart/poscompare` (the route's name
  AT THE TIME this bug shipped, before this session's rename) registered
  AFTER `/chart/{name}` never received a request -- FastAPI/Starlette
  matches in REGISTRATION ORDER, and the catch-all matched first every
  time, returning a 404 from inside `chart()`'s own fallback logic. This was
  a real, shipped bug (user reported "no response" when clicking Compare
  selected). Fixed by renaming the HTML-fragment route to
  `/playercompare/compare` (outside the `/chart/` prefix entirely, itself
  since renamed from `/poscompare/compare`) rather than relying on
  registration order staying correct forever. The PNG route (now
  `/chart/player_overlay`, was `/chart/position_overlay`) is fine because
  it's a literal `if name == "player_overlay"` branch INSIDE the existing
  `/chart/{name}` function, not a second route registration.
- **`.card.chart img` starts at `opacity: 0` (style.css) and is only made
  visible by `prepCharts()`, JS that lives in `index.html` (the dashboard
  shell).** Any standalone page rendering chart PNGs (no dashboard shell)
  needs its OWN copy of that fade-in logic or images load correctly but
  stay permanently invisible forever. This bit twice in this project now:
  `player_profile.html` needed it first (documented in CLAUDE.md), and this
  feature's `_playercompare_compare.html` (was `_poscompare_compare.html`)
  needed the identical fix (`fadeInCharts()`, mirrored from
  `player_profile.html`, wired to `htmx:afterSwap` on the charts
  container). **Check for this class of bug on any FUTURE standalone page
  that renders `.card.chart` images.**
- **A bare `input { width: 210px; ... }` rule in style.css (meant for the
  header's league-ID text field) silently styles EVERY `<input>` on the
  page, including a plain checkbox**, unless overridden. `.adp-check input`
  already guarded against this for the ADP tab's own checkboxes; this
  feature's leaderboard checkboxes needed the identical guard
  (`#playercompare-picks input[type="checkbox"] { width: 14px; ... }`, was
  `#poscompare-picks`). A `width: 1%`/`width: 1px` hint on the surrounding
  `<td>` does NOT fix this -- the checkbox's OWN inflated width is what was
  dragging the column wide, not the cell's table-layout sizing.
- **A polar radar spoke pointing straight at its own tick label (e.g. 12
  o'clock) cannot escape a collision by pushing the value label further out
  along that spoke alone** -- the tick label and any purely-radial-pushed
  point stay on the exact same angular ray however far out it goes.
  Verified with an isolated single-spoke debug render before believing it.
  Fix: `_place_radar_labels` tries a 2D grid (radius x small angular
  nudge), not radius alone.
- **`.controls span` (11px, uppercase -- styled for field-label captions
  like "Position"/"Season") bleeds into ANY `<span>` nested inside a
  `.controls` form**, including a button's own inner count span. Fixed by
  removing an unnecessary wrapper `<span>` and targeting the count span by
  id (`#playercompare-count`, was `#poscompare-count`, specificity (1,0,0))
  since a bare class selector (0,1,0) loses to `.controls span`'s (0,1,1).
- **`window.htmx` is only `window.htmx` if `home.html`/`index.html` actually
  loaded it via `<script src="/static/htmx-...js">`** -- navigating
  directly to a fragment-only route (e.g. `/playercompare`) in a test
  bypasses that entirely and produces a native (non-htmx) form submit with
  no error, which looks deceptively like "nothing happened" rather than a
  clear failure. Any future browser-driven verification of an htmx page
  MUST start from the real entry point (`/` or `/dashboard`), not the
  fragment route directly.
- **Screenshot timing is not proof of a bug** -- an early full-page
  `page.screenshot()` showed blank chart panels even though `img.
  naturalWidth`/`img.complete` both reported success; that particular case
  WAS just Playwright screenshot timing (confirmed by re-screenshotting
  after a longer wait). But the SAME "blank panel" symptom reappeared later
  and was a REAL bug (the opacity:0 issue above) -- the two look identical
  from a screenshot alone. Always check `getComputedStyle(img).opacity`
  directly, not just `naturalWidth`/`complete`, when a chart "looks" blank.

---

## Constraints

- Never manage/start dev servers directly (standing preference, carried
  forward). Real-server verification in this session used a scoped,
  throwaway `uvicorn.Server` + `threading.Thread` inside a disposable
  Python script in the scratchpad dir, torn down at the end of each run --
  not a persistent dev server left running. This was necessary because
  static template inspection alone MISSED two real, user-reported bugs
  (the route collision, the opacity:0 issue) that only manifest via an
  actual HTTP request/response cycle.
- **Verify against real rendered output, not just "the code ran without
  error" or "tests pass."** This session's own pattern, established the
  hard way: built a scratchpad Playwright harness
  (`click_flow_real.py` and siblings, in the session's scratchpad dir --
  see Reference Documents) that drives a REAL browser through the REAL
  click flow against a REAL throwaway server with REAL (unmocked) Sleeper
  data. Re-run this same harness pattern for any future verification of
  this feature.
- Before modifying files, present the complete list and wait for
  confirmation (user's global CLAUDE.md rule) -- followed throughout.
- When the user corrects scope mid-task, revert cleanly rather than
  layering on top -- done for the dashboard-tab -> landing-tab pivot (full
  removal of `roster_position_group()`, the 4 old dashboard templates, the
  `tab()`/`@tab_part` wiring, before rebuilding fresh).

---

## Rejected Approaches

- **Dashboard-tab design (within-team depth chart via `roster_position_
  group()`, fantasy-roster-vs-roster comparison)** -- fully built (4
  templates, `TABS` entry, `tab()` branch, 3 `@tab_part` handlers,
  `roster_position_group()` + its tests), then FULLY REVERTED same session
  once the user clarified the feature should be league-free. Do not rebuild
  this without an explicit new request -- if a within-league roster
  comparison is wanted again, it should probably be a SEPARATE feature from
  Player Comparison, not a re-merge, per the user's own framing ("players
  themselves can be compared already at the baseline").
- **A Scoring (std/half/ppr) control on the landing tab** -- built once,
  found to be decorative (no per-format leaderboard/percentile exists to
  select between), removed. Don't re-add without first building the
  underlying per-format aggregation.
- **Fixed-offset / naive-stacking radar label placement** (`_radar_label_
  radius`, a simple formula: base + player_index * step) -- built, rendered
  against real 14-stat data, found genuinely unreadable (labels overlapping
  tick text and each other), replaced with the real collision solver
  (`_place_radar_labels`). The formula-only function name/constant
  (`_radar_label_radius`) may still appear in old diffs/history but is
  GONE from the current code -- don't resurrect it.
- **Pure radial-push-only collision avoidance for radar labels** (tried as
  the first version of the REAL solver, before adding angular nudges) --
  structurally cannot fix a spoke-pointing-at-its-own-tick-label collision;
  see Important Discoveries. Superseded by the 2D (radius x angle) search.
- **Wrapping the "Compare selected" button's count in a `<span>`, and
  giving the button the `.nfl-apply` class** -- both tried first, both
  reverted for the specificity/auto-margin reasons in Important
  Discoveries.

---

## Remaining Work

1. [ ] **Not yet committed.** Propose a commit split (data layer + chart
   function; landing route/templates; the Player Comparison rename; the
   Load->Search button fix; maybe the radar-label-solver fix as its own
   commit given its size) rather than one combined commit, per this
   project's own established precedent. `git checkout --
   data/sources/adp/2026.json` first unless the drift is wanted.
2. [ ] **Flag the non-this-session files to the user before any commit** --
   `_shell_sync.html`, `_user_leagues.html`, `_landing_start.html`,
   `tab_testing.html` (modified) and `test_lookup.py`,
   `test_season_history.py`, `test_user_leagues.py`,
   `tab_season_history.html` (untracked) are NOT this session's work and
   should not be swept into a commit for this feature without the user's
   explicit say-so.
3. [ ] CLAUDE.md has NOT been updated with a bullet documenting Player
   Comparison yet -- this codebase's own established convention (dense
   bullet per shipped feature). Worth doing before/alongside a commit. Use
   the FINAL (post-rename) names throughout: `player_compare.py`,
   `player_field_compare`/`player_trend`, `/playercompare*` routes,
   `plot_player_overlay`.
4. [ ] Consider whether the Scoring (std/half/ppr) control is wanted as a
   follow-up now that the seam is documented -- would need a new per-format
   leaderboard aggregation in `nflstats.py`/`nflref/summary.py` first.
5. [ ] The trend chart's `weeks=` narrowing (a range picker scoping the
   snapshot views to recent weeks) was part of the ORIGINAL plan
   (documented in an earlier planning-phase conversation) but never built
   -- `player_field_compare`'s `weeks=` param is still a documented no-op.
   Not requested again; only pick up if asked.

---

## Risks / Unknowns

- **The concurrent/other-session files flagged throughout this document are
  still sitting in the working tree, unexamined by this session beyond
  noting they exist and are not this session's work.** Do not assume they
  are safe to discard or safe to commit -- ask the user or investigate
  their origin before touching them.
- **The radar label solver's collision-avoidance was verified against
  exactly one real case (2 players x 14 RB stats)** -- not stress-tested
  with 3-4+ overlapping players, which the chart's own design nominally
  supports (colors come from a palette with more than 2 entries). The
  `_RADAR_LABEL_PUSHES`/`_RADAR_LABEL_NUDGES` search space may need wider
  bounds if a future real render with more players still shows collisions.
- **No Scoring/format control means every part of this feature (leaderboard
  ranking, percentile field comparison, trend fantasy-points line) is
  implicitly PPR-only.** This is documented in code comments but not
  surfaced to the end user anywhere on the page itself (no "PPR" label
  visible in the UI) -- worth a small UI note if this becomes confusing in
  practice.

---

## Reference Documents

- `CLAUDE.md` (repo root) -- has NOT been updated yet (see Remaining Work
  #3). Read its existing dense-bullet entries (especially the
  player-profile and dark-mode-chart ones) as the convention to follow.
- `fantasy-football-4-fun/webapp/player_compare.py` (was
  `position_compare.py`) -- read the module docstring first; explains
  exactly why this stays league-free.
- `fantasy-football-4-fun/webapp/templates/_playercompare_compare.html`
  (was `_poscompare_compare.html`) -- read the inline JS comments before
  touching the button/checkbox wiring again; several non-obvious
  CSS-specificity traps are documented inline.
- `fantasy-football-4-fun/sleepermetrics/plots.py` -- read
  `_place_radar_labels`'s docstring (and the module comments right above
  `_RADAR_LABEL_PUSHES`/`_RADAR_LABEL_NUDGES`) before touching radar label
  placement again; it documents the exact collision case that broke the
  simpler version.
- `fantasy-football-4-fun/tests/test_player_compare.py` (was
  `test_position_compare.py`) and `test_playercompare_landing.py` (was
  `test_poscompare_landing.py`) -- read before extending; several tests are
  regression tests for specific bugs (the tick-collision fix, the fade-in
  fix, the route-naming fix) with detailed docstrings explaining what real
  failure they guard against.
- Scratchpad Playwright harness scripts (session-specific temp dir, may not
  survive to a new session -- see the Constraints section for the pattern
  to rebuild if needed): `click_flow_real.py` was the most useful one
  (real server + real browser + real data, full click-through). These
  predate the rename and reference the OLD route/id names
  (`/poscompare`, `data-poscompare-pick`) -- update them to the new names
  before reusing.

---

## Resume Prompt

Review this handoff completely before doing any work. Review all files
listed under Reference Documents, especially `CLAUDE.md` and
`player_compare.py`'s module docstring.

Player Comparison (the league-free landing-page tab, renamed from "Position
Comparison" late in its own build -- see Important Decisions) is
functionally complete and verified against real data via a real browser,
through multiple rounds of user-reported bugs, PLUS a full rename pass
verified via `git diff` (every touched line was newly added by this
feature's own build; nothing pre-existing was touched) and confirmed with a
full pytest run (377 passed, same 2 pre-existing unrelated failures as
before) -- do not assume "tests pass" means "the feature works end-to-end"
for any future change here; re-verify with a real browser click-through
(rebuild the Playwright scratchpad harness pattern described in
Constraints if the original scripts are gone, updating route/id names to
the current `/playercompare`/`data-playercompare-pick` forms).

If the user wants to commit, propose splitting into logical commits and
explicitly flag the non-this-session files (see Current State and Risks)
before staging anything -- do not assume those files are safe to include.

Do not rebuild the dashboard-tab (within-league roster) version of Player
Comparison, and do not re-add a Scoring control, without an explicit new
request -- both were deliberately built once and reverted/removed; see
Rejected Approaches for why.

Preserve all documented decisions and do not revisit rejected approaches
unless new information requires it.
