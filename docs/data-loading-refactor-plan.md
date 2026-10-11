# Data loading refactor: store raw and complete first

Status: planned, not started.  Written 2026-10-10.  Nothing in this plan has been implemented.

## Problem

Most sources are trimmed before they are first written to disk, so the full payload is thrown away after each download.  Adding a column later, or asking a question the trim did not anticipate, means downloading the source again.

Audit of the 2024 releases (columns raw versus kept):

| Source | Raw cols | Kept | Raw size | Note |
|---|---|---|---|---|
| `player_stats` | 53 | 27 | 0.3 MB | |
| `schedules` | 46 | 22 | 0.5 MB | all seasons in one file |
| `ngs_passing` | 29 | 22 | 0.7 MB | all seasons in one file |
| `ngs_receiving` | 23 | 19 | 1.1 MB | all seasons in one file |
| `ngs_rushing` | 22 | 18 | 0.4 MB | all seasons in one file |
| `pfr_pass` | 24 | 15 | under 0.1 MB | |
| `pfr_rec` | 17 | 13 | 0.1 MB | |
| `pfr_rush` | 16 | 14 | under 0.1 MB | |
| `pfr_def` | 29 | 27 | 0.2 MB | |
| `injuries` | 16 | 14 | 0.1 MB | |
| `snap_counts` | 16 | 15 | 0.2 MB | |
| `pbp` | 372 | about 12 | 20 MB per season | only a derived 70KB table is stored |
| `pbp_participation` | 26 | about 8 | 4.6 MB per season | same |

Other trimmed sources: `sleeper_stats` (about a dozen of roughly 85 keys per player, raw size not measured), all ADP providers (`ffadp/*._trim`, ESPN's feed is about 20MB raw).  The only source stored raw is the Sleeper player dump (`sleeperPlayerData_py.pkl`).

Redundant loading found:

- `schedules` and the three `ngs_*` files are one file for all seasons, but each season is fetched separately, so the same file is downloaded once per season (about 18 times for schedules during backfill).
- `route_participation` re-downloads about 25MB per season on every build, and an empty result is not cached.
- `scoring.nfl_stats` and `nflstats.raw_week` pull the same Sleeper weekly feed; only the trimmed copy persists.

## Target rule

1. **Raw layer.**  The download function writes the complete payload, byte for byte, to `data/sources/<source_name>/raw/` before any parsing.
2. **Derived layer.**  Today's `data/sources/...` files become derived tables built from the raw files.  A change to the trim rules is a rebuild with no network.
3. **Network only on schedule.**  Downloads happen in the refresher (daily or in-season weekly) or on an explicit reload.  Interactive requests never download.  Comprehensive datasets are loaded at most once per refresh cycle.

## Plan

Each step is its own task and commit, in this order.

0. **Build a data-load measurement function first** (see "Measurement" below), and record a baseline.
1. **Fix the folder layout and git policy** (location is decided; the `pbp` git call is deferred).
2. **`nflref` loader.**  In `api.read_release_parquet`, save the raw bytes before parsing; add `nflref.raw` (path helper, load, save).  Change `NflDataset.fetch` to: raw file present and fresh, rebuild derived from it; otherwise download, store raw, derive.  Tests monkeypatch the raw directory as well as the snapshot directory (the 2024 `player_stats` overwrite bug is the precedent).
3. **All-seasons files** (`schedules`, `ngs_*`): one raw file, sliced per season locally.  Backfill becomes one download per file.
4. **Backfill raw** for the small datasets from the current upstream files (one pass; keep a manifest of source URL and fetch date).
5. **`pbp` and `pbp_participation`.**  Store raw locally, gitignored (about 25MB per season).  Rebuild `route_participation` and the new `pass_plays` from the raw files.  Render never reads them.  Cache the empty result for an in-progress season so it is not retried every build.
6. **Sleeper weekly feed.**  Persist the full week once (check size first), derive the usage subset and the scoring subset from it, and share it between `scoring` and `nflstats`.
7. **ADP providers.**  Measure raw sizes; store raw where small (Sleeper, FFC, Yahoo, CBS), decide separately for ESPN and RotoWire (large, no usable validators).
8. **Refresher.**  Teach `refresh_policy` and `refresher` that the raw file is the thing that goes stale; derived tables rebuild from it.  Keep the existing conditional-request logic.
9. **Docs.**  Update `data/sources/README.md` and add a `CLAUDE.md` bullet.

## Constraints

- Render is 512MB, `DISABLE_REFRESH=1` stays set, and the image is built from git.  Anything the app needs at request time must be a committed derived file; raw files are for the build and refresh path.
- `verify.py` parity is unaffected (Python webapp only), but the full `pytest` suite must stay green after each step, and any test that passes `reload=True` must redirect the raw and snapshot directories to `tmp_path`.
- Atomic writes (temp file plus `os.replace`) for raw files too.
- Stage named files only.

## Decisions (2026-10-10)

- **Location (decided):** raw lives at `data/sources/<source_name>/raw/`, for example `data/sources/nflverse/raw/`, `data/sources/sleeper_stats/raw/`, and one `raw/` per ADP provider.  Derived files stay where they are.  Check in step 1 that no dataset or season folder is already named `raw` (nflverse datasets sit directly under `data/sources/nflverse/`).
- **Git:** commit the raw files.  The exception still to decide is `pbp` and `pbp_participation` (about 25MB per season, 200MB or more for ten seasons), which would bloat the repo and the Render image; either keep those two out of git or commit only a reduced raw copy.  The call is deferred (2026-10-10); step 5 does not start until it is made.
- **Retention:** keep every season raw, no pruning.
- **`route_participation`:** needs a rebuild from stored raw.  It also stays blocked in season while nflverse freezes `pbp_participation`; the rebuild changes where the data comes from, not that limit.
- **Scope widened:** other functions that make ad-hoc pulls where they could filter stored raw data are in scope too.  Inventory below.

## Inventory of ad-hoc pulls (code read, not executed)

Sleeper league data is fetched live through `sleeper_api` and kept only in memory (or in a trimmed form), with no raw copy on disk:

| Where | What it pulls | Issue |
|---|---|---|
| `sleepermetrics/season.py` (matchups, rosters, users, winners bracket) | the whole league chain per season | in-memory only; rebuilt from the network after every cache expiry |
| `sleepermetrics/league.py` | league, user, state, rosters | same |
| `sleepermetrics/draft.py` | `/drafts`, `/draft/{id}/picks` | memoised in process only |
| `sleepermetrics/playoffs.py` | league, rosters, users, matchups, both brackets | repeats season.py's calls |
| `webapp/app.py` (`_waiver_bids`, matchups at ~5973, user-leagues sweep) | transactions per week, matchups | extra live pulls beside the season build; transactions were already fetched once for the season |
| `sleepermetrics/report.py` ~1213 | user leagues | ad hoc |
| `sleepermetrics/scoring.py` `nfl_stats` | `/stats/nfl/regular/{season}/{week}` | in-memory only; the full ~85-key line is dropped |
| Callers of `scoring.nfl_stats` directly: `metrics.py` (2 sites), `team_profile.py` (2 sites), `ffadp/finish.py` | the same weekly feed | bypass the `nflstats.raw_week` snapshots, so each repeats the download |
| `ffadp/identity.py` and `sleepermetrics/players.py` | `/players/nfl` | two separate callers of one daily dump (check they share the raw `.pkl`) |

Already fine: the player dump itself (stored raw), headshots (image files cached on disk), the assets cache.

Proposed handling:

- **Sleeper weekly feed:** one raw store, one reader.  `nflstats.raw_week` and `scoring.nfl_stats` both read it; direct callers move to the shared reader.  Highest value, because it is the most repeated pull.
- **Sleeper league data:** raw JSON per `(endpoint, league, season/week)`.  Completed seasons never change, so they are fetched once and reused (this extends the `reuse=` logic already in `season.seasons`); only an in-progress season re-fetches.  This also removes the repeated calls in `app.py` and `playoffs.py`.
- **Live-state calls** (`/state/nfl`, the forward league lookup, user search): stay live and short-lived.  They are lookups, not datasets.
- A function that must stay live (for example the in-progress week via `fetch_live_week`) is marked as such in the code, so the rule has visible exceptions.

New steps (after step 8 above, before docs):

- **8a.** Route the direct `scoring.nfl_stats` callers through the shared reader.
- **8b.** Raw store for Sleeper league endpoints, completed seasons first.
- **8c.** Confirm `ffadp/identity.py` and `players.py` share one `/players/nfl` download.

## Measurement

Added 2026-10-10.  We need numbers on what the ad-hoc pulls cost before and after the refactor, not guesses.

A small instrumentation module (proposed home: `fantasy-football-4-fun/webapp/loadmeter.py`, or `sleepermetrics/` if the Sleeper code needs it directly) that records every outbound data call:

- Hook points: `requests.get` in `nflref/api.py` and `ffadp/api.py`, and `sleeper_api` / `sleeper_api_many` (the one place all Sleeper calls pass through), plus `scoring.nfl_stats` cache hits and misses.
- Per call: timestamp, source, URL or endpoint, bytes received, seconds, whether it was a network hit, a memory-cache hit, or a disk hit, and the calling function (from the stack).
- A context manager, `with loadmeter.session("label"):`, that collects calls for one action, and a report that groups by caller and endpoint: call count, total bytes, total seconds, repeats of the same URL.
- Off by default.  Enabled by an environment variable or the context manager, so it adds nothing in production.  It records metadata only, never payloads, and never logs secrets or full query strings that could hold them.

Use:

1. **Baseline** before any refactor step: run representative actions with the meter on (cold league load, a cold player profile, a team profile, the ADP tab with Load, a season report, Player Comparison).  Save each report under `docs/` or `.claude-logs/`.
2. **After each step**, re-run the same actions and compare.  A step is only done when the repeat count and bytes for its targets go down, or the report shows it is already zero.
3. A test fixture that asserts no network call happens on a warm path (this is the check that the "interactive requests never download" rule holds).

Network-free tests cover the module itself; real-network baselines are run by hand and labelled as measured, not inferred.

## Still open (updated)

- Whether `pbp` and `pbp_participation` raw go to git: deferred by the user.
- Raw size of the Sleeper weekly feed, the league endpoints for the full chain, and each ADP provider: the meter in step 0 will measure these.


## Baseline (measured 2026-10-10, local machine, step 0 meter)

Raw results: `.claude-logs/loadmeter-baseline-2026-10-10.json`.  Run with `tools/dev/loadmeter_baseline.py`, real network, refresher off.  Each action ran cold, then warm straight after.  Network calls only; memory and disk cache hits are invisible to the meter.

| Action | Cold | Warm |
|---|---|---|
| `league_load` (default league, 5 seasons) | 230 calls, 22.5 MB, 10.4 s | 0 calls |
| `player_profile` (id 4034, no league) | 42 calls, 279.6 MB, 34.9 s | 0 calls |
| `player_profile_with_league` | 104 calls, 311.8 MB, 46.4 s | 0 calls |
| `team_profile` (DET 2025) | 2 calls, 0 MB | 0 calls |
| `adp_board` (2025) | 1 call, 22.7 MB | **1 call, 22.7 MB** |
| `player_compare` (RB, 2025) | 0 calls | 0 calls |

What the numbers show:

1. **`route_participation` dominates a cold player profile.**  A career-length player triggers a build for every season with no committed snapshot, and each build downloads `pbp` (about 19 to 20 MB) and `pbp_participation`.  The run made 13 such file downloads, about 140 MB in total, to produce roughly 70 KB of stored data per season.  The meter's headline of 279.6 MB double counts them: each download is a redirect from github.com to release-assets.githubusercontent.com and the meter logs both hops with the final size (confirmed by the two host rows matching at 139.78 MB).  Until the meter is fixed, halve any redirected-download total.  This is step 5 of the plan, and the largest single cost measured.
2. **The ESPN ADP board re-downloads 22.7 MB on every load, warm or cold.**  2025 has no ESPN snapshot (the feed comes back all-sentinel), so there is nothing to find on disk and nothing is stored to say "checked, empty".  Cheap fix once raw storage exists: store the raw response (or a "checked on" marker) so an empty season is not re-pulled.
3. **League load: 230 calls in about 10 s, 35 repeated URLs.**  Per-week `matchups` (75) and `transactions` (75) calls dominate, plus 29 `/league/N` lookups from `league_chain` and 13 stat-week pulls from `scoring.nfl_stats`.  Completed seasons never change, so these are step 8b candidates.  The repeated URLs include `/league/N` and `rosters`/`users` fetched both by `season.py` and by `playoffs._bracket_context`; I have not traced every one of the 35.
4. **The player dump (14.7 MB) was re-downloaded on this cold league load.**  That is the daily cache expiring, not a bug, but it is the biggest single item in a league load.
5. **Already clean:** `team_profile`, `player_compare`, and every warm path except the ADP board.  Warm paths making zero calls confirms the in-process caches work; it does not say what happens after a restart.

Limits of this baseline: one machine and one player/team; the player id was a long-career RB, so the profile numbers are near the worst case; Render skips `route_participation` entirely, so item 1 is a local-build and refresh cost, not a Render request cost.

To do for the meter: collapse a redirect chain into one logical download so bytes are not double-counted; optionally add cache-hit counters (needs edits in `scoring.py`, `nflstats.py` and `nflref/cache.py`).

Update 2026-10-10: the meter now counts a redirect chain as one call (original URL, final size, total time), with a test.  The baseline JSON above was recorded BEFORE this fix, so its byte totals for nflverse downloads are about double; re-run it for corrected figures.

## Step 1: proposed layout (2026-10-10, for confirmation; nothing moved yet)

Rule: `data/sources/<source_name>/raw/`, holding the payload exactly as received, named after the upstream asset.  Checked against the current tree: no folder or file is called `raw` today, so there is no name collision.

| Source | Raw location | Notes |
|---|---|---|
| nflverse | `data/sources/nflverse/raw/<release>/<asset>` e.g. `raw/pbp/play_by_play_2024.parquet`, `raw/nextgen_stats/ngs_passing.parquet` | mirrors the upstream release path; the all-seasons files (schedules, NGS) are stored once |
| Sleeper weekly feed | `data/sources/sleeper_stats/raw/<season>/week_<week>.json` | full lines; the existing trimmed files stay as the derived layer |
| Sleeper league endpoints | `data/sources/sleeper_api/raw/<endpoint path>.json` (new source) | completed seasons only at first |
| ADP | `data/sources/adp/<provider>/raw/...` and `data/sources/adp/raw/` for Sleeper's own | |

Tooling that walks these folders and must tolerate `raw/` (found by reading, not yet changed):

- `tools/dev/refresh_data.py` finds seasons from file stems of four digits (`_seasons_in`) and scans every subfolder of an ADP provider (it treats each as a scoring-format variant).  Raw files named after the upstream asset (`play_by_play_2024.parquet`) are not read as a season, but a raw ADP file named `2025.json` WOULD be.  So: name raw ADP files with a prefix (for example `raw_2025.json`) or make the scan skip a `raw` folder.
- `nflverse/` is iterated as a list of dataset folders in places; `raw` must be skipped there.  I have not located every such loop.
- The Docker image copies `data/sources`, so committed raw files ship to Render.  That is why the size of what gets committed matters (the `pbp` decision is deferred).

Decisions still needed from the user: confirm this layout, and whether Sleeper league raw lives in a new `sleeper_api/` source folder.

## Baseline 2 (measured 2026-10-10, after the redirect fix and the ESPN empty-season marker)

Raw results: `.claude-logs/loadmeter-baseline-2026-10-10b.json`.  Same actions, same machine, real network.  Supersedes the byte totals in the first baseline.

| Action | Cold | Warm | Change from baseline 1 |
|---|---|---|---|
| `league_load` | 229 calls, 7.8 MB, 9.6 s | 0 | 22.5 MB before; the 14.7 MB player dump was not re-downloaded this time (its once-a-day cache was fresh), so the drop is not a code change |
| `player_profile` | 29 calls, 139.8 MB, 36.9 s | 0 | 279.6 MB before, which was the redirect double count; calls 42 to 29 for the same reason |
| `player_profile_with_league` | 91 calls, 172.0 MB, 43.7 s | 0 | 311.8 MB before, same cause; 32.2 MB of it is the Sleeper weekly feed (77 calls) |
| `team_profile` | 2 calls, 0 MB | 0 | unchanged |
| `adp_board` | 0 calls | 0 | was 22.7 MB on every load; the ESPN marker file from the earlier run made even the cold pass free |
| `player_compare` | 0 calls | 0 | unchanged |

So the true cold player-profile cost is about 140 MB of `pbp` and `pbp_participation` downloads, confirming step 5.  Of the 172 MB for a profile with a league, 32 MB is the Sleeper weekly feed, which `nflstats` and `scoring` fetch separately (steps 6 and 8a).  The `adp_board` row reflects a snapshot written by the earlier run, so it does not show a clean cold start; a fresh checkout would pay the 22.7 MB once.

## Progress (2026-10-10)

- **Step 0 done:** meter (session and per-request modes), baseline script, journey tool.
- **Steps 2 to 4 done for the nflverse tabular datasets:** `api.read_release_parquet` stores the raw file as it arrives; `api.fetch_release_parquet` reads raw first; `NflDataset.fetch`, `Schedules.fetch` and `_NgsRole.fetch` use it; an all-seasons file is one download per process window.  83 raw files (14.4 MB) backfilled with `tools/dev/backfill_raw.py`, manifest at `data/sources/nflverse/raw/manifest.json`.  Checked: rebuilding all 140 derived snapshots from raw with the network blocked reproduced 138 exactly; the other two (schedules 2025, 2026) differ where upstream changed after the derived copy was written (2026 scores and lines; 2025 temperature and wind; the 2025 cause is inferred, not confirmed).
- **Not done:** `pbp` and `pbp_participation` (decision deferred), Sleeper weekly feed (steps 6, 8a), Sleeper league endpoints (8b), ADP providers (7), refresher awareness of raw files (8), `route_participation` rebuild from raw (5).
- `tools/dev/refresh_data.py` needed no edit: it iterates dataset names, never folder names, so `raw/` is ignored, and its per-season reloads now share one download of an all-seasons file.

## Progress: Sleeper weekly feed (2026-10-10)

- **Steps 6 and 8a done.**  `scoring.nfl_stats(season, week, reload=False)` is raw-first: memory, then `data/sources/sleeper_stats/raw/<season>/week_<week>.json.gz`, then Sleeper (storing the complete answer).  `nflstats.raw_week` passes `reload` through and derives its trimmed usage file from it.  The five direct callers (`metrics.py` x2, `team_profile.py` x2, `ffadp/finish.py`) needed no edit.
- Stored gzip, not plain JSON: 180 weeks are 10.4 MB (about 0.06 MB each), far below the 120 MB I first estimated for plain JSON.
- Backfill: `tools/dev/backfill_sleeper_raw.py`, 152 downloads plus 28 already stored, none failed.
- Checked: with the network blocked, rebuilding the 180 trimmed files from raw reproduced 179 exactly.  The one difference (2026 week 4) is probably a later upstream correction, not confirmed.
- Measured (baseline 3, `.claude-logs/loadmeter-baseline-2026-10-10c.json`, cold passes only):

| Action | Before | After |
|---|---|---|
| `league_load` | 229 calls, 7.8 MB | 217 calls, 1.1 MB |
| `player_profile_with_league`, Sleeper host | 77 calls, 32.2 MB | 30 calls, 0.3 MB |

  The nflverse `pbp` downloads in the profile (about 140 MB) are unchanged, as expected.
- Still open: Sleeper league endpoints (8b: the 75 + 75 per-week matchups and transactions calls), ADP providers (7), `pbp` raw (decision deferred), refresher awareness of raw (8), `route_participation` from raw (5), and a `verify.py` run (not done this session; `scoring.py` is in the parity-covered package, values unchanged).

## Rule: committed raw data is league- and user-agnostic (decided 2026-10-10)

Raw files that get committed may hold NFL player, team and game information only.  Nothing keyed to a specific Sleeper league id or user id is stored, committed or not.  A call that names a league or user id (`/league/<id>/...`, `/user/<id>/...`) always goes back to Sleeper.

Consequences:

- **Step 8b (raw store for Sleeper league endpoints) is dropped.**  The 75 + 75 per-week `matchups` and `transactions` calls in a league load stay live.  Reducing them has to come from calling less often (for example not re-fetching a completed season within one process, which `season.seasons(..., reuse=)` already does between cache refreshes), not from storing responses.
- **Allowed raw, agnostic:** nflverse release files (done), Sleeper's weekly NFL stat feed `/stats/nfl/regular/<season>/<week>` (done; keyed by NFL player id), the ADP providers (step 7: public NFL player rankings), the Sleeper player dump `/players/nfl` (NFL players; today stored as a git-ignored `.pkl`, and a committed copy would go stale daily, so it stays as is).
- **Measurement output is covered too (done).**  The meter reports where each call went through an ALLOW LIST (`loadmeter.classify`), not a redaction rule: a Sleeper path is shown only as a fixed template (`/v1/league/{league}/matchups/{week}`), a path on a public NFL-data host (nflverse, ESPN, Yahoo, CBS, FFC, RotoWire) only when it fits that host's pattern, and any other host as a placeholder.  No call keeps its real path; repeats are counted from a one-way fingerprint.  A new Sleeper endpoint reads "(unrecognised)" until a template is added, and a test that scans the source for Sleeper paths fails until it is.  A second test scans all report output for any run of 15 or more digits.  The three baseline JSON files in `.claude-logs/` were re-labelled through the same function and contain no ids.
- Already in the repo before this work and unchanged: `data/seasons/<league_id>/` folder names, the default league id in `app.py`, and ids in older `.claude-logs` entries.  Say if those should be cleaned up too.

## Progress: ADP providers (2026-10-10)

- **Step 7 done for storing raw.**  Every provider's API function keeps the complete response (gzip, `adp/<provider>/raw/`) on a successful live fetch; same storage type for all, committed, per the decision.  ESPN is included for every season (about 4 MB each from 2018, so 21 seasons are roughly 40 MB of the 44.0 MB total).  Backfilled 92 responses with `tools/dev/backfill_adp_raw.py`, none failed.  New helper `sleepermetrics/rawfile.py` (atomic gzip write and read) is shared by the ADP layer.
- Checked: re-trimming 84 stored responses reproduced 79 snapshots; the 5 differences are upstream drift (details in `data/sources/README.md`).
- **Not done:** rebuilding the ADP snapshots FROM raw when a snapshot is missing (the providers still fetch live); the trimmed snapshots are unchanged.  Sleeper's own ADP and CBS were not part of the re-trim check.
- Still open: refresher awareness of raw (step 8), the `pbp` raw decision, `route_participation` from raw (step 5).

## Step 8 (refresher and raw): no code change needed (checked 2026-10-10)

`webapp/refresher.py` refreshes every source through the same `reload=True` paths that now keep the raw copy, so raw stays current with the derived files:

- nflverse: `dataset.fetch(season, reload=True)` -> `api.fetch_release_parquet(reload=True)` -> `read_release_parquet`, which replaces the raw file.  For an all-seasons file the first season downloads it and the rest of that run reuse it (10 minute window).
- Sleeper weekly feed: `nflstats.raw_week(..., reload=True)` -> `scoring.nfl_stats(..., reload=True)` replaces the raw week (test added).
- ADP: `provider.fetch(..., reload=True)` -> the API functions, which store the response.  Sleeper's own ADP goes through `draft._fetch_adp_raw` -> `sleeper_adp`, which also stores it.

What a refresh now costs on disk: current-season ESPN raw is about 8 MB and is rewritten on each ESPN refresh (weekly by the existing policy), so a local dev server leaves those files modified in `git status`.  That is a decision for whoever commits, as with the ADP snapshots.  Render sets `DISABLE_REFRESH=1` and does not write raw files.

Not changed: the refresher's change detection still looks at the derived files' timestamps, which is correct because raw and derived are written in the same call.

## Progress: play-by-play raw and `route_participation` (2026-10-10)

- **Decision:** store `pbp` and `pbp_participation` raw (the earlier deferral is closed).  `cache.NO_RAW_PREFIXES` is now empty.
- **Step 5 done.**  `route_participation._build` reads the stored raw files (only the columns it needs, locally and on Render alike), downloading and storing them when absent or on a reload.  `api.store_release` stores a large file without parsing it.  Backfilled 21 of 22 files (252.1 MB: `pbp` 194 MB, `pbp_participation` 34 MB, plus the earlier 14 MB); the one failure is the 2026 participation file, which nflverse does not publish while the season runs.
- **Checked:** rebuilding 2023, 2024 and 2025 from raw with the network blocked reproduced the committed tables exactly (6008, 5921 and 5908 rows), in 0.3 s each instead of several downloads.
- **Finding (not fixed yet):** seasons 2016 to 2022 build to ZERO rows.  Their participation files have 20 columns and no `offense_names` or `offense_positions` (those arrive in 2023), so the build cannot tell which on-field players are receivers.  The module's `EARLIEST = 2016` ("verified live") is therefore wrong for routes; usable data starts in 2023.  This is the source of the waste in the first baseline: every cold profile for a long-career player tried seven seasons, downloaded about 140 MB, got nothing and cached nothing, so it repeated.  With raw stored the retry is local and takes 0.1 s, but a fresh checkout or Render would still download first.  Proposed: set `EARLIEST = 2023`.
- **Still to decide:** the Docker image.  `COPY data/sources` would ship the 228 MB of play-by-play raw to Render, which never reads it (it skips route builds).  Proposed: exclude `data/sources/nflverse/raw/pbp/` and `pbp_participation/` in `.dockerignore`.

## Progress: downstream data comes from raw (2026-10-10)

- `route_participation.EARLIEST` is now 2023 (see the finding above), and `.dockerignore` keeps the two play-by-play raw folders out of the Render image.
- **Empty answers are remembered.**  `scoring.nfl_stats` stores an empty week as a marker: final for a past season, trusted for 6 hours for the current one.  The route build remembers, in memory, that a season came back empty (the in-progress season) and does not retry for 6 hours.
- **ADP snapshots rebuild from raw** with no network, for every provider and for Sleeper's own ADP; a past season's Sleeper ADP no longer asks Sleeper each process.
- **`tools/dev/offline_check.py`** (network switched off) verifies it.  Raw-only state, derived snapshots deleted: leaderboards, schedule, all nflverse datasets, route participation (5921 rows for 2024), Player Comparison, the ADP board (1888 rows) and finish ranks (631), and a player profile (636 stored rows) all came back from raw.  The only attempts left: Sleeper `/state/nfl` (a lookup of the current season and week, live by design), and `pbp_participation_2026` (404 until nflverse publishes it).
- Measured with the meter, a cold player profile for a long-career player: 42 calls and 279.6 MB at the start of the day (the redirect double count included), then 15 calls and 0 MB with raw stored, then 3 calls and 0 MB once empty weeks were remembered (3.2 s instead of 35 s).
- Left as designed: league and user endpoints (always live), `/state/nfl`, the daily player dump.
