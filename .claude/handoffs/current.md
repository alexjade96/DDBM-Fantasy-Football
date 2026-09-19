# Context Handoff

Generated: 2026-09-18T12:57:35-07:00

Purpose:
This document is the authoritative project state for resuming work in a new
Claude Code session.

---

## Goal

Redesigned Player Comparison's snapshot radar chart (and, by shared code, the
player-profile page's own season-overlay radar) from a shared-0-100-percentile
axis with floating value badges into a classic Statsbomb/Ted Knutson "pizza
chart" -- each spoke prints its OWN stat's real values at 5 rings, rotated to
align with the spoke's own angle -- matching a reference image the user
supplied (`screenshots/sample_radar.png`). Also added a Total/Per-game toggle
to both Player Comparison charts, defaulted both to "Per game," fixed several
real layout/rotation/formatting bugs along the way (each caught only by a
direct visual comparison against the reference image, not by automated tests
alone), and iterated through multiple rounds of user-reported visual polish.

---

## Current State

- Branch: `main`. **Nothing from this session is committed** -- all work is
  uncommitted in the working tree on top of `2cdb8fc` (which itself already
  contains the earlier Player Comparison feature + rename, all pushed).
- Modified files, all uncommitted:
  - `CLAUDE.md` -- 6 new dense bullets documenting: DEF/percentile-profile +
    unified search (prerequisite work, not this session's), Player
    Comparison itself, the Total/Per-game toggle, the pizza-chart redesign,
    the rotation/layout follow-up fixes, the spoke-name rotation fix, and
    the share-stat percentage fix. (Some of these bullets predate this
    exact session but are still uncommitted from a prior turn.)
  - `fantasy-football-4-fun/sleepermetrics/plots.py` -- the actual chart
    code; see Architecture below for the specific functions touched.
  - `fantasy-football-4-fun/webapp/sources/nflref/summary.py` --
    `percentile_profile()` gained `stat_mode` (total/per_game) and
    `axis_ticks` per column; new `_axis_ticks()` helper.
  - `fantasy-football-4-fun/webapp/player_compare.py` --
    `player_field_compare()` gained `stat_mode` passthrough.
  - `fantasy-football-4-fun/webapp/app.py` -- `/chart/player_overlay` route
    reads/validates `stat_mode` query param.
  - `fantasy-football-4-fun/webapp/templates/_playercompare_charts.html` --
    both charts' Total/Per-game toggle UI + JS; both default to "Per game".
  - `fantasy-football-4-fun/tests/test_nflref.py`,
    `test_player_compare.py`, `test_playercompare_landing.py`,
    `test_player_profile.py` -- extensive new/updated coverage, see
    Reference Documents.
- Full pytest (`fantasy-football-4-fun/`): **405 passed**, 2 pre-existing
  failures unrelated to this session (`test_ffadp.py::test_export_xlsx_route`
  -- missing `openpyxl`; `test_nflref.py::test_snapshot_serves_when_
  network_gone` -- pre-existing `KeyError`). Re-confirmed identical after
  every change this session via full-suite reruns.
- `verify.py` (R<->Python parity) NOT re-run -- nothing touched is in the
  parity-diffed contract (`plots.py`'s radar functions are webapp-only chart
  code, same precedent as `plot_player_radar`/`plot_player_overlay`
  already established; `nflref`/`player_compare`/`app.py` are all outside
  `sleepermetrics`'s diffed surface).
- Verified end-to-end repeatedly via a scoped, throwaway `uvicorn.Server` +
  `threading.Thread` in the scratchpad dir + a real Playwright browser
  click-through (leaderboard load -> player selection -> Compare selected
  -> both charts render -> toggle both independently) after EVERY visual
  change in this session, not just after tests passed. Scratchpad scripts
  (`run_server.py`, `click_flow_pizza.py`) may not survive to a new
  session -- rebuild the pattern described in Constraints if needed.

---

## Architecture

### 1. Two radar functions share `_radar_axes`/`_draw_pizza_ticks` (`plots.py`)

- `plot_player_overlay(players, stat_keys, mode, title, position, stat_mode)`
  -- Player Comparison's own chart. `mode="snapshot"` = the radar;
  `mode="trend"` = the week-by-week line (unaffected by any of this
  session's radar work, aside from its own pre-existing `stat_mode`
  cumulative-sum toggle from an earlier session).
- `plot_player_radar(season_profiles, focus_season, player_name)` -- the
  player-profile page's own season-over-season radar (a DIFFERENT,
  pre-existing feature). Both call `_radar_axes(fig, labels, pizza=True)`
  and `_draw_pizza_ticks(ax, angles, keys, players)` -- the SAME two shared
  helpers, so a change to either helper affects both charts. Confirmed this
  is intentional per an explicit user answer earlier in the redesign ("both
  radars get the pizza-chart style").
- The single-spoke or single-player codepaths (`plot_player_radar` with one
  season, or a chart with players missing `axis_ticks`) still degrade
  gracefully -- verified by dedicated tests, not just visually.

### 2. Pizza-chart mechanics (`_radar_axes`, `_draw_pizza_ticks`, `plots.py`)

- Point RADIUS is still 0-100 percentile (unchanged from the old design) --
  this is what lets differently-scaled stats share one polar frame. Only
  the PRINTED ring numbers changed: `_axis_ticks()` (in
  `nflref/summary.py`) computes 5 real-value reference points (at the
  20/40/60/80/100th percentile of the FIELD's own distribution for that
  stat) per leaderboard column, attached to `percentile_profile()`'s
  `columns` as `axis_ticks`.
- **Spoke-NAME labels are NOT drawn via `set_xticklabels`** in pizza mode.
  Real discovery: matplotlib's `PolarAxes` silently resets a THETA tick
  label's `set_rotation()` back to 0 on every draw, so there is no way to
  rotate a real polar tick label. Fix: `set_xticklabels([])` (hides them,
  keeps tick POSITIONS registered) + manual `ax.text()` per label at radius
  112 (just past the rim, same 0-100 data scale), with the SAME rotation
  formula as the ring ticks (see below).
- **Rotation formula** (used identically for both spoke names and ring
  ticks): `rot = -math.degrees(ang)`; then `if 90 < rot % 360 < 270: rot +=
  180` to flip upside-down text (left/bottom half of the chart) right-side
  up. This axes uses `set_theta_offset(pi/2)` + `set_theta_direction(-1)`.
  **A previous, WRONG version of this formula was `degrees(pi/2 - theta)`**
  -- it conflated the theta OFFSET (which repositions where spoke 0 sits on
  the page) with a ROTATION that text drawn there would need; this made
  EVERY label rotate a full 90 degrees off from the reference chart's own
  convention. Only caught by direct visual comparison against the
  reference image -- automated checks (non-overlap, right-side-up-ness)
  were satisfied by the wrong formula too.
- **Ring-tick text formatting**: new `_format_pizza_tick_value(key, value)`
  in `plots.py` -- falls through to the existing `_format_stat_value()` for
  everything except a narrow `_PERCENT_TICK_KEYS = {"tgt_share",
  "snap_share"}`, which render as a whole-number percent ("34%") instead of
  a 3-decimal fraction ("0.340"). Deliberately NOT the broader
  `_SHARE_STAT_KEYS` (which also has `wopr`/`racr`/`pacr` -- ratios that can
  exceed 1.0, where "%" misreads); those never reach Player Comparison's
  radar in practice anyway (nflverse-only leaderboard columns, this feature
  forces `source="sleeper"`). The leaderboard TABLE's own formatting
  (`_format_stat_value`) is completely untouched.
- **Ring-band shading**: `_radar_axes(pizza=True)` fills every OTHER ring
  band (0-20, 40-60, 80-100 -- starting at the innermost) with
  `T["neutral"]` at `alpha=0.30`, `zorder=0`. Deliberately `T["neutral"]`
  (a saturated, visible token), not `T["grid"]` (near-white, was tried
  first and was nearly invisible).
- **Layout**: both radar functions' legends moved from `bbox_to_anchor`
  positioning them OFF TO THE SIDE (pushed the whole polar axes off-center
  to the left) to centered BELOW the axes
  (`loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=<count>`); titles
  re-centered to match (`x=0.5, ha="center"`). This surfaced a SEPARATE
  latent bug in `plot_player_radar` (narrower 7x7in figure): its long
  subtitle, now centered instead of left-aligned, ran off the canvas edge
  -- fixed with `textwrap.fill` (same technique `_finish()` uses) plus a
  title/subtitle y-position adjustment for the wrapped 2-line case.

### 3. Total/Per-game toggle (from an earlier turn this session, still uncommitted)

- `percentile_profile(..., stat_mode="total"|"per_game")`: `"per_game"`
  divides every counting-total column by that row's own `games` (computed
  fresh, not a stored column) and ranks percentile against the FIELD's own
  per-game rate -- a genuinely different ranking, not a relabeled total.
  `games` itself is excluded from per-game mode. Already-rate columns
  (`snap_share`, `tgt_share`, `adot`, `ppg_ppr`) are left alone in both
  modes. **Spoke labels do NOT get a "/G" suffix in per-game mode** (user
  explicitly asked this removed after an earlier pass added it) -- the
  toggle itself states which reading is active; only the chart SUBTITLE
  says "(per-game rates)"/"(season totals)".
  `plot_player_overlay`'s trend-mode `stat_mode` is a SEPARATE, older
  concern (cumulative sum vs. weekly value) -- unrelated to the radar's own
  `stat_mode` (total vs. per-game percentile ranking), same param name,
  different meaning per mode.
- UI: `_playercompare_charts.html`'s two `<nav class="rail">` pill pairs,
  wired by an inline `<script>` INSIDE the htmx-swapped fragment itself
  (relies on htmx's `allowScriptTags` default re-executing a swapped
  fragment's own `<script>` on every load). Clicking a pill rewrites just
  that `<img>`'s `stat_mode` query param via regex replace -- no server
  round trip for the surrounding fragment, and the two charts' toggles are
  fully independent.

---

## Important Decisions

- **Both radars (Player Comparison + player-profile page) get the pizza
  style, not just Player Comparison.** Explicit user answer when asked to
  scope this -- since they share `_radar_axes`/`_draw_pizza_ticks`,
  building a separate renderer for just one would have meant real
  duplication.
- **No "/G" suffix on spoke labels in per-game mode; no percentile
  restated in the subtitle either past what's needed.** User explicitly
  asked for label text to stay minimal and let the toggle/subtitle carry
  the mode information instead of every spoke restating it.
- **Ring-tick collision fixes favored INSET RADIUS + shorter text
  (percentage) over an angular stagger.** An angular stagger
  (`_TICK_NUDGE`) was tried first for a different collision (rim
  spoke-name vs. outer ring label) and later explicitly REMOVED by user
  request once it was clear it broke "labels sit exactly on their own
  spoke's line" -- see Rejected Approaches. The share-percentage fix this
  session is the SAME kind of fix applied to a DIFFERENT collision (two
  adjacent share spokes' own rings), chosen deliberately as "shorten the
  text" rather than "add more spacing," per the user's own suggestion in
  their request.
- **`_PERCENT_TICK_KEYS` is narrower than `_SHARE_STAT_KEYS`.** Considered
  reusing the existing set wholesale; rejected because `wopr`/`racr`/`pacr`
  are ratios, not proportions, and "%" would misrepresent a value >1.0. Kept
  narrow even though the wider set is unreachable in practice today, so a
  future nflverse-sourced radar caller doesn't inherit a silent bug.

---

## Important Discoveries

- **Matplotlib's `PolarAxes` silently resets a THETA tick label's rotation
  to 0 on every draw**, regardless of `set_rotation()` calls on the `Text`
  objects `set_xticklabels()` returns. Confirmed directly with an isolated
  script (rotation read back as 0 immediately after `fig.canvas.draw()`).
  This does NOT apply to plain `ax.text()` calls (used for the ring ticks
  and, after this fix, the spoke names too) -- only to the axes' own
  managed tick-label `Text` objects. No workaround exists other than hiding
  the real tick labels and drawing your own text.
- **The correct screen-space rotation formula for THIS axes' settings
  (`theta_offset=pi/2`, `theta_direction=-1`) is `-degrees(theta)`, NOT
  `degrees(pi/2 - theta)`.** The offset term does not also enter the
  rotation formula -- conflating "where a spoke is drawn" with "how text at
  that spoke should be rotated" produced every label rotated a full 90
  degrees off from the reference chart's convention. This shipped once and
  was only caught by a direct side-by-side visual comparison against the
  reference image -- neither the earlier empirical single-spoke check nor
  the automated non-overlap/right-side-up tests could distinguish the wrong
  formula from the right one, since both properties held under either
  rotation.
- **A near-white color at low alpha (`T["grid"]`) is visually
  indistinguishable from no fill at all** for ring-band shading; the
  reference chart's bands are a real, visible grey. `T["neutral"]` (an
  already-existing, more saturated theme token) was the fix.
- **A subtitle centered on a narrow (7x7in) figure can run off the canvas
  edge even though the SAME subtitle text fit fine on a wider (9.5x9.5in)
  figure.** Left-aligned text doesn't have this failure mode (it just runs
  off the RIGHT edge, less noticeable in casual review); centering exposed
  it immediately. `textwrap.fill` at a width calibrated to the actual
  figure size fixes it; a one-size-fits-all wrap width across differently
  sized figures would be wrong for at least one of them.
- **`ax.text()` on a polar axes accepts a radius beyond the axes' own
  `set_ylim(0, 100)`** (e.g. radius 112) and renders it visibly outside the
  rim without needing to change the axes limits or disable clipping --
  verified empirically, not assumed.

---

## Constraints

- Never manage/start dev servers directly (standing preference). All
  real-server verification this session used a scoped, throwaway
  `uvicorn.Server` + `threading.Thread` in the scratchpad dir, torn down
  (or left as an orphaned background process killed via its saved PID)
  after each check -- never a persistent dev server.
- **Verify against real rendered output, not just "tests pass."**
  Established hard-won discipline for this feature specifically: at least
  three real bugs this session (the legend/off-center layout, the 90-degree
  rotation error, the spoke-name-can't-rotate matplotlib quirk) were
  invisible to automated tests and caught ONLY by rendering a real chart
  and looking at it (or, for the rotation error, comparing it side-by-side
  against the reference image). Do not skip this step for any future
  change to `_radar_axes`/`_draw_pizza_ticks`/either radar function.
- Before modifying files, list them and wait for confirmation (user's
  global CLAUDE.md rule) -- followed throughout via the file-list-before-
  edit convention already established in this repo's own sessions.
- Nothing gets committed without an explicit user request to commit --
  followed; all of this session's work remains uncommitted by design,
  pending the user's own commit/push instruction.

---

## Rejected Approaches

- **Angular stagger (`_TICK_NUDGE`) for ring-tick labels** -- built once to
  fight a rim/ring-label collision, explicitly REMOVED by user request in
  a later turn once it was clear it broke "every ring value sits exactly
  on its own spoke's radial line" (the reference chart's own convention).
  Superseded by inset radius (`_TICK_R_SCALE`) alone. Do not reintroduce an
  angular offset for ring-tick placement without a new explicit request.
- **`degrees(pi/2 - theta)` as the rotation formula** -- shipped, visually
  compared against the reference image, found wrong by a full 90 degrees,
  replaced with `-degrees(theta)`. Do not resurrect the `+pi/2` term; see
  Important Discoveries for why it's wrong, not just stylistically
  different.
- **Calling `.set_rotation()` on `set_xticklabels()`'s returned `Text`
  objects to rotate spoke names** -- tried first (the "obvious" approach),
  found to have NO EFFECT on a real render (matplotlib resets it). Do not
  retry this on a `PolarAxes` -- draw spoke names as plain `ax.text()`
  instead, as the current code does.
- **`T["grid"]` for ring-band shading color** -- tried first, nearly
  invisible against a light background at any reasonable alpha, replaced
  with `T["neutral"]`.
- **Reusing the full `_SHARE_STAT_KEYS` set for the radar's percent-tick
  conversion** -- rejected because it also contains `wopr`/`racr`/`pacr`
  (ratios, not 0-1 proportions); a narrower `_PERCENT_TICK_KEYS` was
  introduced instead. See Important Decisions.

---

## Remaining Work

1. [ ] **Nothing is committed.** If the user asks to commit, propose a
   sensible split (e.g.: the pizza-chart redesign itself; the
   rotation/layout bug fixes; the spoke-name-rotation fix; the
   share-percentage fix; CLAUDE.md updates alongside whichever commit they
   most directly document) rather than one giant commit, per this
   project's own established precedent from earlier sessions (see git log
   -- `6e1781f`/`47e4996` were themselves a deliberate split). Confirm the
   working tree is otherwise clean (`git status`) before staging anything.
2. [ ] No further visual polish has been requested as of this handoff. If
   the user asks for another round, re-render via the scratchpad
   throwaway-server + Playwright pattern (Constraints) before and after any
   change -- do not rely on "tests pass" alone, per this feature's own
   established discipline.
3. [ ] Nothing else outstanding. The trend chart's `weeks=` narrowing
   (a range-picker seam noted in `player_field_compare`'s own docstring as
   a documented no-op) remains unbuilt from a much earlier planning
   conversation -- only pick up if explicitly asked again.

---

## Risks / Unknowns

- **The rotation/layout fixes were verified on real 2024/2026 Sleeper data
  with 3 players and up to 16 spokes (RB), and separately on an 8-spoke
  synthetic test fixture spanning the full circle.** Not stress-tested with
  a position carrying a very different spoke count (e.g. QB's smaller
  column set, or DEF's own disjoint column set) -- the rotation formula and
  upside-down normalization are generic to spoke COUNT, so this is a low
  risk, but hasn't been visually re-confirmed for those positions
  specifically this session.
- **The share-percentage fix (`_PERCENT_TICK_KEYS`) is scoped to exactly
  two keys** (`tgt_share`, `snap_share`) based on what Player Comparison's
  `source="sleeper"`-only leaderboard actually carries today. If a future
  change lets Player Comparison read nflverse-sourced columns (adding
  `wopr`/`racr`/`pacr`/`air_yards_share` to what reaches the radar), this
  set will need deliberate reconsideration, not just widening to match
  `_SHARE_STAT_KEYS` (see Important Decisions for why those are different
  in kind, not just historically narrower).

---

## Reference Documents

- `CLAUDE.md` (repo root) -- has 6 new dense bullets from this and the
  immediately preceding turns (search for "pizza chart" / "Player
  Comparison" / "radar"). Read these in order; several explicitly
  reference and correct claims made in the bullet immediately before them
  (e.g. the rotation-formula bullet documents its own predecessor's bug).
- `fantasy-football-4-fun/sleepermetrics/plots.py` -- read
  `_radar_axes`, `_draw_pizza_ticks`, `_format_pizza_tick_value`,
  `plot_player_radar`, and `plot_player_overlay`'s snapshot branch in that
  order; each docstring documents a specific real bug/fix in detail and
  should be treated as load-bearing, not decorative.
- `fantasy-football-4-fun/webapp/sources/nflref/summary.py` -- read
  `_axis_ticks()` and `percentile_profile()`'s own docstring for the
  `stat_mode`/`axis_ticks` contract this whole feature is built on.
- `fantasy-football-4-fun/tests/test_player_compare.py` -- the largest
  concentration of regression tests for this session's fixes; several have
  detailed docstrings explaining the exact real bug they guard against
  (search for "regression test" in that file).
- `screenshots/sample_radar.png` -- the reference image every visual
  decision this session was checked against. Look at it again before
  making any further radar styling change.
- Scratchpad Playwright/server harness scripts (session-specific temp dir,
  may not survive to a new session): `run_server.py` (throwaway uvicorn
  server) and `click_flow_pizza.py` (full click-through + screenshot) were
  the two reused repeatedly this session -- rebuild this exact pattern
  (see Constraints) for any future verification here.

---

## Resume Prompt

Review this handoff completely before doing any work. Review all files
listed under Reference Documents, especially `CLAUDE.md`'s newest bullets
and `screenshots/sample_radar.png`.

The pizza-chart radar redesign (both Player Comparison's snapshot chart and
the player-profile page's season radar) is functionally complete and visually
verified against the reference image and a real browser click-through,
through multiple rounds of user-reported visual bugs -- do not assume "tests
pass" means "the chart looks right" for any future change here; re-verify
with a real render (and, for anything involving rotation/angle/position,
compare it directly against `screenshots/sample_radar.png` again) before
calling a change done.

If the user wants to commit, propose splitting into logical commits (see
Remaining Work #1) and confirm the working tree is otherwise clean before
staging anything -- nothing in this session has been committed yet.

Do not reintroduce the angular tick-label stagger (`_TICK_NUDGE`), the
`degrees(pi/2 - theta)` rotation formula, `set_xticklabels().set_rotation()`
for spoke names, `T["grid"]` for ring-band shading, or the wide
`_SHARE_STAT_KEYS` set for percent-tick conversion -- all were tried and
explicitly rejected/fixed this session; see Rejected Approaches for why each
one specifically doesn't work.

Preserve all documented decisions and do not revisit rejected approaches
unless new information requires it.
