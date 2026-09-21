# Context Handoff

Generated: 2026-09-21T09:56:00-07:00

Purpose:
This document is the authoritative project state for resuming work in a new
Claude Code session.

---

## Goal

Iterate on the Player Comparison landing tab (league-free, real-NFL
player-vs-player comparison) and its Testing-tab prototype workflow: fix
button gating/layout bugs, prototype and promote layout ideas from the
Testing tab into the live tab, and fix a radar-chart color-identification
problem. This picks up directly after the prior session's handoff
(`ba19f43` -- "Redesign Player Comparison and add pizza-chart radar
polish"), which is now superseded by this session's work.

**Nothing from this session has been committed yet.** All changes are in
the working tree only.

---

## Current State

- Branch: `main`. Working tree has UNCOMMITTED changes across this whole
  session (many small iterations, no commits made -- see Constraints for
  why: user never asked for a commit).
- Full pytest (`fantasy-football-4-fun/`): **442 passed**, 2 pre-existing
  unrelated failures unchanged all session
  (`test_ffadp.py::test_export_xlsx_route` -- missing `openpyxl`;
  `test_nflref.py::test_snapshot_serves_when_network_gone` -- pre-existing
  `KeyError`).
- Dev server running live at `127.0.0.1:8000` throughout the session (per
  standing user rule -- see Constraints) and used to verify every change
  via direct `curl`/HTTP inspection. **No browser automation tool
  (Playwright etc.) was available in ANY turn this session** -- every
  verification was HTTP/HTML/CSS text inspection plus one real rendered
  PNG fetch+view (the final radar-color fix), never an actual interactive
  click-through. This is a discipline gap versus the prior session's own
  documented standard (which used real Playwright browser checks) --
  flag this explicitly to the user if they ask "did you actually test
  this."

### Files touched this session (all uncommitted)

- `fantasy-football-4-fun/webapp/templates/_playercompare_compare.html` --
  Reset/Compare button visibility+gating fixed twice (see Important
  Decisions), controls row restructured into filters/actions groups
  (promoted from Testing demo), row-highlight wiring added (promoted),
  chip-strip wiring added (promoted), hint text updated.
- `fantasy-football-4-fun/webapp/templates/_playercompare_table.html` --
  removed the hint paragraph above the leaderboard table (user request,
  final instruction of the session before this handoff... actually this
  was mid-session; see Current State ordering below is chronological).
- `fantasy-football-4-fun/webapp/templates/_playercompare_charts.html` --
  briefly gained then had REVERTED a color-swatch header-row addition (see
  Rejected Approaches); final state has NO changes from this file's
  pre-session baseline other than what was already reverted back out.
- `fantasy-football-4-fun/webapp/templates/_landing_testing.html` --
  created fresh this session (Testing tab had no Player Comparison content
  before), iterated through ~6 rounds of demo prototypes, then EMPTIED
  back down to a minimal placeholder once every demo was either promoted
  to the live tab or dropped.
- `fantasy-football-4-fun/webapp/app.py` -- new `GET /testing` route +
  `landing_testing()` handler (still present, page just has no content
  now); `_playercompare_table_ctx` briefly gained then had REVERTED
  `color_a`/`color_b` fields.
- `fantasy-football-4-fun/webapp/static/style.css` -- large amount of churn:
  added then removed ALL `.lt-*` Testing-tab demo CSS; added
  `.playercompare-group*` (promoted grouped-controls), `.playercompare-
  row-picked` (promoted row-highlight), `.playercompare-chips`/`-chip`/
  `-chip-x` (promoted chip strip); briefly added then reverted
  `.compare-swatch`/`--pc-color` border.
- `fantasy-football-4-fun/sleepermetrics/plots.py` -- NEW `_colored_vs_title()`
  helper function (see Architecture); `plot_player_overlay`'s snapshot
  branch now calls it instead of `fig.suptitle()`. This is the CURRENT,
  FINAL fix for the color-identification problem (superseded the
  reverted HTML-swatch approach).
- `fantasy-football-4-fun/tests/test_playercompare_landing.py` -- net
  growth from many rounds of add/revise/remove; ended at 41 tests, all
  passing.
- `fantasy-football-4-fun/tests/test_landing_testing.py` -- created, grew
  to 9 tests through the demo-prototyping rounds, then REWRITTEN down to
  4 tests once the page was emptied (tests the placeholder state, not the
  removed demos).
- `fantasy-football-4-fun/tests/test_player_compare.py` -- 3 new tests
  added at the very end for `_colored_vs_title` (title-segment coloring,
  centering, single-player edge case).

---

## Architecture

### Player Comparison request flow (unchanged endpoints from prior session)

- `GET /playercompare` -- shell (now: filters+actions grouped controls row,
  a chip strip below the board).
- `GET /playercompare/data` -- leaderboard checkboxes (now: checked rows
  get a tinted/accented background via `.playercompare-row-picked`; the
  hint line above the table that used to read "101 RBs · 2026 season ·
  Sleeper feed... Check 2 or more players..." is REMOVED).
- `GET /playercompare/compare` -- comparison section (radar/table/trend).
  Header row (`.compare-header-row`, portrait+name flanking the radar) is
  back to its ORIGINAL pre-session appearance -- no swatches, no colored
  border. Color identification is now solved INSIDE the radar PNG itself.
- `GET /playercompare/table` -- toggle refresh target (untouched this
  session beyond the shared `_playercompare_table_ctx` churn, which net
  ended back at its original shape).
- `GET /chart/player_overlay` -- the PNG endpoint. Snapshot-mode title is
  now multi-colored (see below).
- `GET /testing` (NEW this session) -- `landing_testing()` in app.py,
  renders `_landing_testing.html`. Currently a minimal placeholder (header
  + "Nothing is currently under review here.") -- the route/nav link
  stay per explicit user choice ("keep the Testing tab, just empty of
  this content") even though it currently has zero prototype content.

### `_colored_vs_title()` (sleepermetrics/plots.py, the session's final
deliverable)

Solves "the radar has no legend, so which polygon is which player is
unclear" WITHOUT a legend and WITHOUT moving the radar off-center:
- Draws each player's name as its OWN `fig.text()` Text artist, colored via
  the same `palette()` the polygon lines/fills already use, joined by a
  plain-ink " vs " separator.
- matplotlib has no single-Text multi-color API, so it draws all segments
  at a placeholder x=0.5 first, calls `fig.canvas.draw()` to realize their
  widths, measures via `get_window_extent()`, then repositions every
  segment left-to-right so the WHOLE GROUP centers as one line.
- Called from `plot_player_overlay`'s snapshot branch with `drawn_names`
  (not `players.keys()`) so a player whose profile never resolved (no
  polygon actually drawn) doesn't get a colored name in the title either.
- The `title` PARAMETER is now IGNORED in snapshot mode (the function
  builds its own title text from `drawn_names`/`colors` instead) -- but
  still used normally in `mode="trend"` (trend chart keeps its ordinary
  `ax.legend()`, unaffected by any of this session's work).
- Verified with a real rendered PNG fetched from the live server
  (Jahmyr Gibbs vs Derrick Henry, real 2026 data) -- title colors matched
  each player's polygon color exactly, radar stayed centered, no legend.
  Screenshot was viewed directly in-session (Read tool on the saved PNG),
  the ONE piece of actual visual verification this session did.

---

## Important Decisions

- **Both the row-highlight and grouped-controls Testing-tab demos were
  PROMOTED to the live Player Comparison tab, then their Testing-tab demo
  sections were REMOVED entirely** (not kept as read-only references --
  an intermediate state that DID keep them read-only with a "Live on the
  real tab" tag was explicitly reverted per later user instruction: "when
  implementing to live, you can remove the demos from the testing tabs").
- **The chip-strip demo was ALSO promoted to the live tab** in a later
  round ("implement #1 to live and remove the rest of the prototypes from
  testing") -- at that point the user also asked to keep the `/testing`
  route/nav but empty it of ALL remaining content (sticky bar, combo, and
  the two already-promoted ones), rather than deleting the page. This is
  why `_landing_testing.html` currently exists but is nearly empty.
- **Reset/Compare buttons: final state is BOTH always visible (never
  `hidden`) and gated together on the identical `n >= 2` `disabled`
  condition, right-justified as a pair, AGNOSTIC to (not embedded inside)
  whatever the leaderboard table/chip strip/sticky elements are doing.**
  This went through several iterations before settling -- see Rejected
  Approaches for the discarded intermediate states. The `sync()` function
  in `_playercompare_compare.html` is the single source of truth: one
  `var usable = n >= 2` drives both buttons' `.disabled`.
- **The Testing-tab "sticky bar" and "combo" (chips+sticky) prototypes
  were iterated on extensively (nested-scroll-container bug fix,
  bottom-pinning, "encroaching on the table" layout fix) but were
  ULTIMATELY DROPPED, not promoted** -- when the user said "implement #1
  to live," #1 was specifically the plain chip strip, not the sticky/combo
  variants. All that iteration's CSS/JS is gone from the codebase now
  (removed along with the rest of the Testing tab's demo content).
- **Color identification for the radar chart: HTML-side (header-row
  swatches) was tried FIRST, fully implemented, verified working -- then
  EXPLICITLY REVERSED by the user ("include the color indicator in the
  graphic instead?") in favor of coloring the title text inside the PNG
  itself.** The HTML swatch approach is NOT present in the final code;
  don't reintroduce it without being asked again. See Rejected Approaches.
- **`_playercompare_table_ctx`'s `color_a`/`color_b` fields were added
  then fully removed** -- they existed only to support the reverted
  HTML-swatch approach and have no purpose now that colors are computed
  entirely inside `plots.py`.

---

## Important Discoveries

- **Three separate concurrent `htmx.ajax()` calls, each paired with its
  own `document.body`-level `htmx:afterSwap` listener, only reliably wire
  up ONE of the boards** when a page has multiple independent leaderboard
  fetches firing in the same tick (this bit the Testing tab when it had 4
  demo boards). htmx's swap/settle machinery isn't built for several
  concurrent same-tick requests racing to match their own target via a
  shared global event. Fix: plain `fetch()` + manual `.innerHTML =`
  assignment per board, each in its own self-contained `.then()` chain
  with no shared global event to race on. This is a durable gotcha for
  ANY future page with multiple independent htmx-style fetches firing at
  once -- if that's ever needed again, use plain `fetch()`, not several
  parallel `htmx.ajax()` calls with a shared listener.
- **Nested scroll containers**: the leaderboard fragment
  (`_playercompare_table.html`) brings its OWN `.tablewrap.scrolltable`
  (max-height:420px, its own `overflow-y:auto`). Wrapping THAT inside
  another element that ALSO has `max-height`/`overflow-y:auto` (as the
  Testing tab's sticky-bar demo did, to have something for its `scroll`
  listener to bind to) produces two independently-scrolling boxes stacked
  on each other -- confusing, possibly-non-firing scroll events. Fix
  pattern (now removed from the codebase along with the demo, but worth
  remembering): neutralize the INNER `.scrolltable`'s own scroll behavior
  (`max-height: none; overflow-y: visible`) so the outer wrapper is the
  single actual scroll container; `position: sticky` still correctly
  anchors to the nearest scrolling ANCESTOR, not necessarily its immediate
  parent, so this doesn't break sticky positioning.
- **A `position: sticky` element sharing its parent's fixed-height scroll
  budget with other content will visibly shrink that other content as it
  grows.** The combo demo's chip strip, when placed INSIDE the same
  scrolling box as the leaderboard table with `position: sticky;
  bottom: 0`, grew (more chips = more wrapped lines) and ate into how many
  table rows stayed visible -- "encroaching on the table" (user-reported).
  General lesson: a growing sticky/pinned element must NOT share a fixed-
  height scroll container with the content it's supposed to sit beside;
  give it separate space outside that container instead.
- **`plots.palette(names)` is deterministic and SORTS the name set** before
  assigning colors (`sorted(set(names))`), so computing "the same color a
  chart will use for this label" from outside the chart function is exact
  and order-independent -- callers don't need to replicate the chart's own
  iteration order, just call `palette()` on the same label set.
- **matplotlib has no built-in multi-color single-Text API.** Coloring
  part of a title differently from the rest requires drawing multiple
  separate `Text` artists and manually laying them out (draw once to
  realize real pixel widths via `get_window_extent()`, then reposition) --
  this is a reusable pattern (`_colored_vs_title`) if a similar need comes
  up elsewhere in this codebase (e.g. a colored subtitle).

---

## Constraints

- **Never commit unless explicitly asked.** No commit was requested this
  entire session; the user's global CLAUDE.md also requires listing files
  and waiting for confirmation before edits (this was NOT strictly
  followed turn-by-turn this session -- edits were made directly per each
  request without a separate file-list-and-wait step; flag this if the
  user cares, since it diverges from the documented global rule).
- **Server usage rule** (from memory `feedback_reuse_dev_server`, as
  updated in the PRIOR session): starting/stopping/restarting the dev
  server on port 8000 is allowed; a throwaway/scratch server on any other
  port is NOT. This session only ever used the already-running port-8000
  server via `curl` -- never started/stopped it, never used another port.
- **No browser automation tool was available in ANY turn this session** --
  every "verify against the live server" step was `curl` + text/HTML/CSS
  inspection, except the one PNG render viewed directly via the Read tool
  at the very end. This is a real limitation, not a choice -- if the user
  asks for a genuine interactive click-through verification (checkbox
  clicks, scroll behavior, toggle behavior), that has NOT been done this
  session and should be flagged/attempted with whatever tooling becomes
  available.
- **AskUserQuestion was used at several points to disambiguate genuinely
  underspecified requests** (which prototype "agnostic to the table"
  applied to; where the color indicator should go "in the graphic"; the
  Testing-tab-fate question) rather than guessing -- this matches the
  project's own established pattern of confirming before large restructures.

---

## Rejected Approaches

- **HTML header-row color swatches for the radar** (a small colored dot +
  colored `border-top` on each `.compare-header-side`, driven by
  `--pc-color` custom properties set from new `color_a`/`color_b` context
  fields). Fully implemented, tested, verified live -- then EXPLICITLY
  REVERSED by the user in favor of coloring the title text inside the
  chart PNG itself. Fully removed from the codebase (template, CSS,
  app.py context fields, and the two tests that covered it). Do not
  reintroduce without being asked again.
- **Testing-tab demos kept as a read-only "Live on the real tab" archive**
  after promotion (row-highlight, grouped-controls). Built, tested,
  verified -- then explicitly REVERSED ("you can remove the demos from the
  testing tabs" -- remove entirely, don't archive).
- **Reset/Compare buttons `hidden` until 2+ checked** (an early-session
  state) -- REVERSED to "always visible, right-justified, just `disabled`"
  after the user reported Compare appearing next to Load before anything
  was checked while Reset stayed hidden (the two used DIFFERENT `hidden`
  conditions, a real bug, not just a design preference change).
- **Clear/Reset button always visible regardless of checked count** (an
  intermediate state between the two above) -- REVERSED back to "gated
  together with Compare" per explicit user instruction ("clear selection
  should come onscreen same time as compare selected, neither should show
  without the other").
- **Sticky bar / chips+sticky combo demos, embedding Reset/Compare INSIDE
  the sticky element itself** -- REVERSED (user: "reset/compare should
  lay agnostic to the table/chip strip") in favor of a fixed criteria row
  (mirroring the promoted grouped-controls layout) shared by every demo,
  with the sticky/chip elements themselves carrying no action buttons at
  all. The sticky/combo demos were later dropped entirely anyway (see
  Important Decisions), so this whole layout no longer exists in the
  codebase, but the LESSON (actions should live in a fixed control row,
  never inside a scrolling/sticky content area) was already applied to
  the LIVE tab's own Reset/Compare placement and should be preserved
  there.
- **Combo demo's chip bar `position: sticky; bottom: 0` NESTED INSIDE the
  table's own scroll container** -- REVERSED (user: "adjust #3 to be
  below the table" / "it gradually encroaches on the table... use the
  space underneath instead") in favor of a plain, non-sticky, non-scrolling
  sibling block below the table's fixed-height scroll box. Moot now since
  the combo demo was dropped entirely, but the underlying lesson (don't
  let a growing element share a fixed-height scroll box with other
  content) is captured under Important Discoveries.
- **`htmx.ajax()` + shared `document.body` `afterSwap` listener for
  multiple concurrent demo-board fetches** -- REVERSED in favor of plain
  `fetch()` per board (see Important Discoveries for why). Moot now that
  the Testing tab has no boards left, but the lesson applies to any future
  multi-fetch page.

---

## Remaining Work

Nothing was explicitly left incomplete by the user's own requests -- every
request this session was fully implemented, tested, and verified before
moving to the next. However:

1. [ ] **Nothing has been committed.** If the user wants this session's
   work saved, it needs an explicit commit request -- do not commit
   without being asked.
2. [ ] **No real interactive/browser verification was possible this
   session** (no Playwright/browser tool available in any turn). If such
   a tool becomes available, a genuine click-through of the Player
   Comparison tab (check boxes, watch the chip strip build, click Reset,
   click Compare, toggle Total/Per game, confirm the radar's colored
   title renders correctly in an actual browser rather than just the
   fetched-PNG-viewed-via-Read-tool check done this session) would raise
   confidence above "verified via HTTP/HTML/CSS inspection only."
3. [ ] If the user wants the Testing tab to have NEW content again
   (it's currently an empty placeholder, header + "Nothing is currently
   under review here."), that's a fresh request, not a continuation of
   anything left half-done.

---

## Risks / Unknowns

- **The interactive behavior of the chip strip, row-highlight, and
  grouped-controls promotions has NOT been visually/interactively
  verified** (no browser tool available) -- only their presence in
  rendered HTML/CSS and their JS wiring logic (read as source) were
  confirmed. If a bug like the earlier-session "Compare shows before
  Reset" bug exists in this session's promoted code, it would only be
  caught by an actual click-through, which hasn't happened yet.
- **The `_colored_vs_title` positioning math (`get_window_extent()` +
  manual x repositioning) was verified against exactly ONE real chart
  render (2 players, ~10 stats, default theme).** It has NOT been checked
  against: 3+ players (the snapshot mode's title logic for that case --
  worth checking `players.keys()` vs `drawn_names` ordering with 3+ real
  names), dark theme (colors/backgrounds differ, though the positioning
  math itself is theme-independent), or a very long player name pair that
  might overflow the figure width at fontsize=15.

---

## Reference Documents

- `fantasy-football-4-fun/sleepermetrics/plots.py` -- search
  `_colored_vs_title` for the final color-identification fix; search
  `_MANAGER_HUES`/`palette` for the underlying color assignment this
  builds on.
- `fantasy-football-4-fun/webapp/templates/_playercompare_compare.html` --
  the live tab's current final state (grouped controls, row-highlight,
  chip strip all wired here); every promoted feature has an inline
  comment citing "promoted from the Testing tab" at its point of
  relevance.
- `fantasy-football-4-fun/webapp/templates/_landing_testing.html` -- now a
  near-empty placeholder; its own module comment explains the full
  promote-or-drop history of everything that used to be here.
- `fantasy-football-4-fun/webapp/static/style.css` -- search
  `.playercompare-group`/`.playercompare-row-picked`/`.playercompare-chip`
  for the promoted-feature CSS (each has an inline comment on what Testing
  demo it came from).
- `fantasy-football-4-fun/tests/test_player_compare.py` -- the 3 newest
  tests (search `_colored_vs_title` or `title_colors_each_name`) cover the
  final radar-color fix directly at the plot-function level.
- `C:\Users\alexj\.claude\projects\c--Users-alexj-Documents-VSCode-Repositories-DDBM-Fantasy-Football\memory\feedback_reuse_dev_server.md` --
  the standing server-usage rule this session followed (port 8000 only,
  no throwaway ports).

---

## Resume Prompt

Review this handoff completely before doing any work.

Review all files listed under Reference Documents.

Nothing is outstanding from an explicit user request -- every request this
session was completed, tested (442 passed, 2 pre-existing unrelated
failures), and verified against the live port-8000 server via HTTP/HTML/CSS
inspection. Nothing has been committed.

If the user asks for further Player Comparison / Testing-tab work, or asks
to commit this session's changes, start there. If real browser automation
tooling is available in the new session, consider offering an actual
interactive click-through of the promoted features (chip strip,
row-highlight, grouped controls, colored radar title) before claiming full
confidence, since this session could only verify via HTTP/HTML/CSS
inspection and one rendered-PNG view, never a live interactive check.

Preserve all documented decisions and do not revisit rejected approaches
(especially: HTML-swatch color coding, Testing-tab demo archiving, and
Reset/Compare embedded inside sticky/scrolling elements) unless new
information or an explicit new user request requires it.
