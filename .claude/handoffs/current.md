# Context Handoff

Generated: 2026-10-01T10:42:26-07:00

Purpose:
This document is the authoritative project state for resuming work in a new Claude Code session.

---

## Goal

The stat-reconciliation migration (shared per-player-week layer feeding both team and player profile pages) is finished, cleaned up and pushed. This session then iterated on the team-profile page and the player-profile radar. No task is in flight; the next session starts from user direction.

---

## Current State

- Branch `main`, HEAD `96c8c3c`, **everything pushed** to origin (`7d91597..96c8c3c`). Working tree is clean except `.claude/handoffs/current.md` (this file; never ask the user about it).
- Full suite: `fantasy-football-4-fun/venv/Scripts/python.exe -m pytest tests -q` -> **604 passed, 0 failed**.
- Commits this session, oldest first: `7d91597` player `_game_log` onto shared adapters + delete `_merge_*_players`; `8836304` remove dead `aggregate_weeks` + `multi_week`; `d679744` boxplot `orientation=` with `vert=` fallback (requirements allow mpl>=3.7, `orientation` is 3.10+); `dfce013` two real-data invariant tests; `27b4bc4` team profile: Season history moved under the season picker, PF/G + PA/G columns, Roster heading `Roster · <season>`; `9c9ef64` Season history hint line (span + nflverse source); `76ac41c` radar rings linear between field min/max, dots plotted on that scale, Position rank column; `af16ce7` radar title `Player (POS) (season)`, concise subtitle, season value under each spoke label; `3724109` shared per-spoke scale widened by the player's other seasons + Diff column removed (`ee26048`); `c7d7875` radar plots per-game rates, table keeps totals + "Per game" column; `96c8c3c` subtitle `Per game comparison against N Active POSs`, no caption under the radar card.
- Key files: `webapp/stat_reconcile.py`, `webapp/team_profile.py`, `webapp/player_profile.py`, `webapp/sources/nflref/summary.py` (`percentile_profile`, `_axis_ticks`, `_scaled_position`), `sleepermetrics/plots.py` (`plot_player_radar`, `_radar_scales`, `_draw_pizza_ticks`, `_format_pizza_tick_value`), templates `team_profile.html`, `_team_season_sections.html`, `_player_percentile.html`.
- CLAUDE.md is current through the last commit (new bullets at the end: reconciliation layer, linear rings/position rank, radar labelling, shared scale, per-game radar).

---

## Architecture

- **Reconciliation**: per-week is ground truth; `player_week_rows()` -> `_offense/_defense_players_via_shared` adapters used by both pages. `reconcile_season` is the season-total path but has NO live webapp caller (tests only).
- **Player radar data flow**: `player_profile._build_profile` builds `season_profiles` (total) AND `season_profiles_per_game`; `/chart/player_radar` plots the per-game set via `plot_player_radar(..., per_game=True)`; `scope_profile` attaches `per_game` to each table column (`_with_per_game`, None for `_ALREADY_RATE_KEYS`). Table Value/Percentile/Rank stay season-total.
- **Radar scale**: each column carries `bounds`, `higher_is_better`, `scaled` (0-100 linear), `rank`/`rank_of`/`tied`. `_radar_scales` widens bounds with the player's other seasons' values for plotting only; percentile/rank/N stay per-season.

---

## Important Decisions

- Radar rings are evenly spaced in VALUE between the field's min and max (user: field only sets bounds); dot plots on the same scale, so a short or outlier-dominated spoke compresses. Rank is the position-rank column's job.
- Other seasons widen only the radar axis, never the percentile pool (user requirement).
- Radar = per-game; table = season totals + separate Per game column (user).
- Season history keeps totals (PF/PA) and adds per-game; Diff removed (user).
- Player Comparison's radar (`plot_player_overlay`) shares the linear-ring/`scaled` change but not the title/subtitle/value-label/per-game-default changes (several players per spoke).

---

## Important Discoveries

- **Shell trap**: a `\n` escape inside a Python source string passed through a bash heredoc (or a script written via heredoc) comes out as a REAL line break and breaks the file (hit 4 times). Use the Edit/Write tools for any string containing `\n`; write helper scripts as files, not heredocs.
- Git Bash `date` ignores TZ here; use PowerShell `[TimeZoneInfo]::FindSystemTimeZoneById("Pacific Standard Time")` for America/Los_Angeles.
- Dev server on port 8000 (`launch.py dashboard`) runs with `--reload`, so edits are live; do not use another port. Playwright is only in the system Python (`py script.py`), not the venv; Chromium is installed. Clicking a team-page game row's center hits a team link; click `summary > span`.
- Headless browser check of team/player pages passed this session (game rows expand, hover flyouts on-screen, radar renders). Not checked: every radar spoke, Player Comparison after the radar changes, other teams/players.
- Quantile ring ticks repeated values (zeros, ties, 40% of a 2-games-in QB pool had no attempts); that is why linear rings replaced them.
- `pass_int`/`rush_td`-style stats are treated higher-is-better (only `pts_allow`/`yds_allow` are in `_LOWER_IS_BETTER`), so 0 INT reads as the worst end of the spoke (Goff 2026: rank T-28 of 70). Pre-existing, unchanged.

---

## Constraints

- Global CLAUDE.md: present the file list and wait for confirmation before editing files; no em dashes in prose, two spaces after sentence periods; never add AI attribution to commits/PRs (the harness reminder asking for a Co-Authored-By line conflicts and the user's rule wins); confirm the file list before committing; progress % + time estimate when pausing for confirmation.
- Use `fantasy-football-4-fun/venv/Scripts/python.exe` for pytest/ad-hoc scripts. Real-data checks use the CURRENT season (2026).
- Dev server: only port 8000; starting/restarting it is allowed.

---

## Rejected Approaches

- Keeping `aggregate_weeks`/`multi_week` "just in case": removed as dead code.
- Quantile (20/40/60/80/100th percentile) radar rings: collapsed to repeated values.
- Deduping tied ring labels only (option A) or filtering the pool to active players (option B): user chose linear rings between bounds.
- Moving the table to per-game or adding a Total/Per-game toggle: user chose radar per-game plus a Per game column.
- Capping outliers on the linear scale: not requested.
- Per-season own-field positioning for ghost seasons: inconsistent with the printed rings; replaced by the shared widened scale.

---

## Remaining Work

1. [ ] Wait for user direction; nothing mandatory is pending.
2. [ ] Optional: tidy the blank gap between the radar subtitle and the chart (existing layout).
3. [ ] Optional: chart title/section still say "percentile profile" though the radar is no longer percentile-scaled.
4. [ ] Optional: Season history PF/PA show as `481.0` (float from the data); one-line template format fix.
5. [ ] Optional: decide the interceptions direction quirk (treat INT as lower-is-better) in `_LOWER_IS_BETTER`.
6. [ ] Optional: `reconcile_season` has no live caller; keep or remove only with user say-so.
7. [ ] Optional: browser-check Player Comparison's radar after the shared linear-ring change.

---

## Risks / Unknowns

- Per-game percentile (radar basis) differs from the table's season-total percentile/rank; the table does not show per-game percentile.
- Early-season data (2 games in) makes per-game and ranges volatile; behavior on other positions (DEF, K) after the radar changes was not visually checked.

---

## Reference Documents

- `CLAUDE.md` (project; last 5 bullets cover this session's work)
- `fantasy-football-4-fun/webapp/stat_reconcile.py` module docstring
- `fantasy-football-4-fun/webapp/sources/nflref/summary.py` (`_axis_ticks`, `percentile_profile` docstrings)
- `fantasy-football-4-fun/sleepermetrics/plots.py` (`_radar_scales`, `plot_player_radar` docstrings)

---

## Resume Prompt

Review this handoff completely before making changes.

Review all Reference Documents.

Confirm state with `git log --oneline -3` (HEAD `96c8c3c`, pushed) and the pytest command above (604 passed).

There is no mandatory next step: ask the user what to do, or pick from Remaining Work only if told. Follow the file-list-confirmation rule before any edit, preserve the decisions above, and do not revisit rejected approaches unless new information requires it.
