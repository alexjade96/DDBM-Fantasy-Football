# Context Handoff

Generated: 2026-09-12T13:33:32-07:00

Purpose:
This document is the authoritative project state for resuming work in a new
Claude Code session.

---

## Goal

Two pieces of work this session, both complete:

1. **`sentiment-analysis/`**: a new standalone subproject (repo root) for a
   planned NFL news-sentiment-analysis feature. Currently in a pre-decision
   benchmarking phase -- no model, source, or hosting venue chosen yet.
2. **Full repo-root restructure**: renamed/relocated every top-level
   directory to reflect actual purpose (`python/` -> `webapp/`, `R/` ->
   `r-analysis/`, `season/` -> `data/seasons/`, `results/` ->
   `r-analysis/data/results/`), centralized previously-duplicated
   path-resolution logic, fixed bugs the restructure surfaced (both
   pre-existing and self-introduced), and verified end-to-end.

**Everything described below is implemented and verified.** No pending
uncommitted-but-incomplete work. Nothing has been committed to git yet in
this session -- all changes are staged/working-tree only (commits were not
requested).

---

## Current State

- Branch: `main`. Working tree has extensive staged/unstaged changes from
  the restructure (`git mv` operations show as paired A/D in `git status
  --short`, which is normal -- git's own commit-time diff will detect them
  as renames). Nothing committed yet.
- `sentiment-analysis/` is fully built, tested, and git-tracked as new
  untracked files (never committed either).
- All validation re-run and passing as of the end of this session:
  - Python: 216/216 pytest (`cd webapp && venv/Scripts/python.exe -m
    pytest -q`)
  - `verify.py` (from repo root, with R on PATH): `pytest` PASS, `testthat`
    FAIL (pre-existing, see below), `check_playoffs.py` PASS (4/4 stored
    champions reproduce), `export_py`/`export_r` PASS, parity diff PASS
    (873 metric records + 3 summaries identical R<->Python)
  - Both dashboards (`python launch.py dashboard`, `python launch.py --r
    dashboard`) boot live and load real league data
  - Both origin R scripts (`r-analysis/ddbmFF.R`, `r-analysis/
    leagueAnalytics.R`) run to completion headless from repo root and write
    real output to their new locations
- **Not run**: Docker build validation. Docker Desktop was not running
  during this session and was not started (per standing instruction not to
  manage services/processes myself). Run `docker build -t sleepermetrics .`
  manually before next deploy to confirm the Dockerfile changes are sound.

### New top-level layout

```
DDBM-Fantasy-Football/
  webapp/                    (was python/)
    sleepermetrics/, ffadp/, nflref/, webapp/ (FastAPI app), tests/, venv/
    repo_paths.py             (NEW -- centralized path resolution, see below)
  r-analysis/                (was R/)
    sleepermetrics/ (R package)
    ddbmFF.R, app.R, leagueAnalytics.R, FantasyFootball.Rproj  (moved in)
    data/results/             (was /results at repo root)
    sleeperPlayerData.rds, sleeperPlayers.json, sleeperPlayersSorted.json
    .RData*, .Rhistory*, Rplots.pdf  (moved in; .Rproj.user/ deliberately
      NOT moved, left at repo root to regenerate fresh)
  data/
    seasons/                 (was /season at repo root)
  sentiment-analysis/         (NEW this session, see below)
  parity/                     (unchanged location; gained parity/paths.py)
  tools/                      (unchanged location; getSleeperPlayers.ps1
                                moved in from repo root)
  docs/                       (unchanged location; references.txt moved in
                                from repo root)
  Dockerfile, launch.py, verify.py, README.md, CLAUDE.md,
    .dockerignore, .github/workflows/ci.yml   (repo root, all edited)
```

### Deleted

- `test.json` (repo root) -- confirmed stray, unreferenced anywhere, a raw
  one-off `/rosters` API dump from an unrelated league committed at the
  very first commit. Deleted with explicit user confirmation (destructive
  action, called out beforehand per CLAUDE.md policy).

### Left alone, explicitly out of scope

- `webapp/.refactor-backup-2026-08-27/` -- untracked, pre-existing, has its
  own `RESTORE.md` saying "delete after manual review." Not touched.
- `.Rproj.user/` at repo root -- left at the OLD location rather than moved
  alongside the relocated `.Rproj`; it holds session/cursor state tied to
  the old project path and regenerates cleanly next to
  `r-analysis/FantasyFootball.Rproj` on first open there.
- `.claude/`, `.claude-logs/` -- session-management artifacts, never in
  scope for the restructure.

---

## Architecture

### sentiment-analysis/ (new subproject)

Standalone, pre-decision benchmarking harness for a planned news-sentiment
feature (news tab split by team/player, ranking source material by
positive/negative fantasy impact, building a historical source-reliability
record). Deliberately isolated from `webapp/sleepermetrics` -- no wiring
into the live site yet.

```
sentiment-analysis/
  README.md               -- full architecture notes, model/source research summary
  requirements.txt         -- transformers, torch, vaderSentiment, datasets, scikit-learn
  benchmark/                -- code only, owns no data
    models.py               -- common interface: VADER, cardiffnlp RoBERTa, ProsusAI/finbert
    loader.py                -- loads james-kramer/football_news (HF) + Data/hand-labeled/
    run.py                    -- CLI: scores every dataset x every model, prints accuracy/confusion matrix
  Data/                    -- ALL data lives here (benchmark/ reads from it, owns none itself)
    hand-labeled/hand_labeled.csv   -- 16 real NFL injury/beat-writer examples, tracked in git
    beat-writers/, news-feeds/       -- empty placeholders for future scraped sources (gitkeep only)
  Models/                  -- empty placeholder for downloaded model weights (gitkeep only;
                               models currently download fresh from HF Hub each run)
```

Verified working: ran `python -m benchmark.run --models vader --dataset
hand_labeled` end-to-end (VADER scored 43.8% accuracy on the 16-example
starter set; the two transformer models correctly degrade with a clear
"missing dependency" message when `transformers`/`torch` aren't installed,
rather than crashing).

**No model/source/hosting decision made yet** -- this is intentionally the
next phase of work, not something to resolve automatically. See the
README's "Architecture notes" section for full research summary (GitHub
Actions cron vs other hosting options, source candidates researched: RSS
feeds, ESPN undocumented API, nflverse structured data; Reddit and
Twitter/X ruled out).

### Repo-root restructure: centralized path resolution

**The core fragility this fixed**: 8+ independent places computed "find
`data/seasons/` (formerly `season/`) relative to this file" via hardcoded
`Path(__file__).resolve().parents[N]` hop-counts or bare relative-path
literals. A directory rename/renest broke ALL of them independently unless
each was found and fixed by hand -- exactly the failure mode that bit twice
during this session (see Important Discoveries).

**New centralizing modules**:
- **`webapp/repo_paths.py`** -- Python. `REPO_ROOT = Path(__file__).resolve
  ().parent.parent` (one level up from `webapp/`, since this file sits at
  `webapp/repo_paths.py` and the repo root is one level above `webapp/`).
  `SEASON_DIR` = `SLEEPERMETRICS_SEASON_DIR` env var if set, else
  `REPO_ROOT / "data" / "seasons"`. Every one of `webapp/{sleepermetrics,
  ffadp,nflref}/*.py` and `webapp/webapp/app.py` now imports `SEASON_DIR`
  from here instead of recomputing it. Docstring explains why the
  Dockerfile's flattened `/app/` layout does NOT reuse this same
  computation (env var override always wins there instead -- see below).
- **`r-analysis/sleepermetrics/R/paths.R`** -- new file, exports
  `sl_season_dir()`. Resolution order: `SLEEPERMETRICS_SEASON_DIR` env var,
  else the bare literal `"data/seasons"` (correct when cwd = repo root,
  which is how `launch.py`/`verify.py`/`testthat`/`parity/export_r.R`/
  `tools/run_dashboard.R` all invoke R). **Deliberately does NOT get a
  `this.path`-style self-locating fix** the way the origin scripts did --
  see Important Decisions for why (the package is meant to be
  `library()`-loaded after install, with no fixed source location).
  `playoffs.R`'s three function defaults (`sl_playoff_configs`,
  `sl_apply_playoffs`, `sl_load_playoffs`) all now default to
  `sl_season_dir()` instead of the literal `"season"`.
- **`parity/paths.py`** -- new file. `PY_PACKAGE_DIR = "webapp"`,
  `SEASON_DIR = "data/seasons"` (plain strings, repo-root-relative).
  `parity/export_py.py` and `parity/check_playoffs.py` both import from
  here instead of hardcoding `sys.path.insert(0, "python")` +
  `"season"`/`"playoffs"` literals. `parity/export_r.R` has NO R
  equivalent import mechanism (R has no `Path(__file__)` primitive to
  centralize this the same way) -- it calls `sl_season_dir()` directly and
  a comment cross-references `parity/paths.py` for whoever touches either
  side, telling them to keep the two in sync by hand.

**Docker is a genuinely different case, not just a deeper nesting**: the
Dockerfile's `COPY` steps flatten `webapp/{sleepermetrics,ffadp,nflref,
webapp}` into `/app/{sleepermetrics,ffadp,nflref,webapp}` as direct
siblings, while `data/seasons/` is copied to `/app/data/seasons` -- a
different relative shape than the real repo, not a uniformly-deeper
version of it. Rather than trying to make one formula cover both, the
Dockerfile just sets `SLEEPERMETRICS_SEASON_DIR=/app/data/seasons`
explicitly, so `repo_paths.py`'s env-var-override path always wins there
and the REPO_ROOT-relative fallback (correct only for the real repo layout)
never actually executes in Docker.

### Origin-script self-location (`this.path`)

`r-analysis/ddbmFF.R` and `r-analysis/leagueAnalytics.R` gained:
```r
SCRIPT_DIR <- dirname(this.path::this.path())
```
placed after the `library()` calls. Every bare-filename I/O call
(`sleeperPlayerData.rds`, the `out()` helper building `data/results/
<season>/` or `data/results/league/`) now builds off `SCRIPT_DIR` instead
of a literal relative path. This makes both scripts genuinely
cwd-independent: they produce identical output whether run as `Rscript
r-analysis/ddbmFF.R` from repo root, `Rscript ddbmFF.R` from inside
`r-analysis/`, or sourced in RStudio via `r-analysis/FantasyFootball.Rproj`
(which sets cwd to `r-analysis/`). New dependency: `this.path` (CRAN),
documented in CLAUDE.md's and README.md's install-package lists.

`app.R` also got its stale `source("R/ddbmMetrics.R")` fixed to
`source("ddbmMetrics.R")` (now a sibling file, not needing the old `R/`
prefix) and its header comment's `shiny::runApp(".")` usage note expanded
to cover both invocation directories.

---

## Important Decisions

- **Decision**: Rename-in-place is the default-safe restructure move
  (same nesting depth under repo root); allowing deeper nesting (e.g.
  `data/seasons/` instead of `season/` at repo root) is explicitly
  user-approved and requires fixing every hop-count reference as part of
  the same change. **Reasoning**: `parents[N]`-style hop counts are
  correct only for a specific, fixed nesting depth; changing depth without
  updating every computation silently breaks path resolution (found and
  fixed this exact bug live in `data/seasons/scaffold.py` -- see
  Important Discoveries).
- **Decision**: Centralize path-resolution logic into one module per
  language (`repo_paths.py`, `paths.R`, `parity/paths.py`) rather than
  just fixing each of the 8+ existing hardcoded occurrences in place.
  **Reasoning**: explicit user request ("verify as few as possible/0
  hard-coded items as possible") -- fixes the root cause (duplicated
  computation) so a FUTURE rename only touches one file per language, not
  8+.
- **Decision**: `r-analysis/sleepermetrics/` (the R *package*) does NOT
  get a `this.path`-based self-locating fix, unlike the origin scripts.
  **Reasoning**: `this.path` finds where a SOURCE FILE lives on disk,
  which is meaningless once a package is `library()`-loaded after
  installation (no fixed source location at all). The package's
  `sl_season_dir()` instead relies on cwd = repo root, which is correct
  for every actual invocation path in this repo (`launch.py`, `verify.py`,
  `testthat`, `parity/export_r.R`, `tools/run_dashboard.R`) but NOT if you
  open `r-analysis/FantasyFootball.Rproj` directly in RStudio and then
  call a package function needing `data/seasons/` -- documented as a
  known asymmetry in CLAUDE.md's "Working directory" bullet, with the
  explicit-path workaround spelled out (`sl_dashboard(playoffs =
  "../data/seasons")`).
- **Decision**: `this.path` added as a real new R dependency (not a
  narrower `commandArgs()`-based fix). **Reasoning**: presented both
  options with full tradeoffs (this.path = works in all 3 invocation
  styles including RStudio, small new dependency; commandArgs = no new
  dependency but does NOT cover the RStudio-sourced case, so doesn't
  actually solve the problem fully) -- user explicitly chose this.path
  after seeing neither option cleanly dominated.
- **Decision**: `data/seasons/scaffold.py`'s bugged `sys.path.insert`
  (see Important Discoveries) was fixed to `parents[2] / "webapp"` rather
  than importing from a shared helper. **Reasoning**: this file lives
  OUTSIDE both `webapp/` and any package tree (it's a standalone CLI at
  `data/seasons/scaffold.py`), so there's no existing shared-helper
  location it could cleanly import from without adding a new cross-tree
  dependency; a corrected inline hop-count was the smallest fix.
- **Decision**: Two genuinely pre-existing bugs (parity exporters calling
  `apply_playoffs(ss, "playoffs")` -- a directory that never existed;
  `check_playoffs.py`'s stale `sys.path.insert(0, "python")`) were FIXED
  as part of this restructure rather than left alone. **Reasoning**: both
  were sitting on the exact lines already being edited for the rename, and
  the user explicitly approved fixing them in that same pass rather than
  treating the restructure as strictly rename-only.
- **Decision**: `sentiment-analysis/Data/` and `sentiment-analysis/
  benchmark/` are a strict data/code split -- `benchmark/` owns no data of
  its own, `loader.py` reads from `../Data/`. **Reasoning**: explicit user
  request when reviewing the initial structure ("benchmark should be
  standalone/able to link to the data at a later time").

---

## Important Discoveries

- **`Path(__file__).resolve().parents[N]` hop-counts are fragile to ANY
  nesting-depth change, and this bit twice during THIS session, not just
  as a theoretical risk**:
  1. `data/seasons/scaffold.py` hardcoded `parent.parent / "python"` to
     find the sibling `sleepermetrics` package. Before the restructure,
     `season/scaffold.py`'s `parent.parent` was the repo root (correct).
     After nesting `season/` one level deeper under `data/`, the SAME
     `parent.parent` computation from `data/seasons/scaffold.py` resolves
     to `data/`'s parent context wrong -- it needed `parents[2]`, not
     `parent.parent` (=`parents[1]`). Found via a broad final `grep`
     sweep across ALL file types repo-wide (not just the `webapp/*.py`
     files the initial "8 occurrences" audit covered) -- confirms a
     narrow initial audit scope can miss real breakage. Fixed and
     verified live (`python data/seasons/scaffold.py --help` now
     imports and runs correctly).
  2. The Docker image's COPY-flattened layout (`/app/{sleepermetrics,
     ffadp,...}` as direct siblings, NOT preserving the `webapp/` prefix)
     is NOT simply "one level shallower" than the real repo in a way one
     shared formula could cover -- it's a genuinely different relative
     shape (`data/seasons/` lands as a CHILD of `/app`, not a sibling of
     the package dirs the way it is in the real repo). Solved by having
     Docker set `SLEEPERMETRICS_SEASON_DIR` explicitly rather than trying
     to unify the two computations.
- **A broad, repo-wide, all-file-type sweep is necessary after a
  restructure like this -- a narrower sweep scoped to "the obvious code
  directories" WILL miss things.** The initial audit (8 `parents[2]`
  occurrences in `webapp/*.py`) was thorough for that scope but missed:
  `data/seasons/scaffold.py` (outside `webapp/`), and ~15 stale prose
  comment/docstring references scattered across R package files
  (`headshots.R`, `report.R`, `season.R`, `statnames.R`, `league.R`,
  `playoffs.R`), Python package files (`ffadp/base.py`, `ffadp/cbs.py`,
  `ffadp/espn.py`, `ffadp/fantasypros.py`, `ffadp/rotowire.py`,
  `ffadp/sleeper.py`, `ffadp/yahoo.py`, `ffadp/ffc.py`, `ffadp/__init__.py`,
  `ffadp/finish.py`, `nflref/base.py`, `nflref/schedules.py`,
  `nflref/__init__.py`, `sleepermetrics/{scoring,nflstats,draft,league,
  plots,playoffs}.py`), `webapp/webapp/app.py`, `parity/README.md`,
  `sentiment-analysis/README.md`, `docs/hosting-cicd-{plan,actions}.md`,
  and `README.md`/`CLAUDE.md` themselves. None of these were
  functionally broken (comments don't execute), but they'd mislead anyone
  reading them post-restructure. The check that actually found these:
  `grep -rn "\bpython/|\bseason/|R/sleepermetrics" --include={py,R,md,yml}
  .` repo-wide, filtering out `.claude*`/`.refactor-backup` as
  out-of-scope, then manually reviewing each hit for false positives
  (prose like "Pre-season/draft slot", "--python/--r flag", "per
  season/league" are NOT paths).
- **`docs/hosting-cicd-actions.md` had its own STALE self-referential
  note** claiming ".dockerignore and Dockerfile still say `playoffs/`
  where the real dir is `season/`" -- but neither file actually contained
  `playoffs/` by the time this session touched them (already-resolved
  drift, predating this session). Rewritten to state the actual current
  fixed state rather than leave a misleading unchecked action item.
- **`git status --short` after `git mv` + follow-up edits shows paired
  A/D lines, not `R` (rename) lines, when files were ALSO edited after
  the move** (37 files showed as `AM`). This is normal git behavior, not
  a sign anything is broken -- `git diff -M`/`git log --follow` at
  commit time will still detect the underlying renames via content
  similarity. Don't be alarmed by `git status --short` not showing `R`
  lines directly after `git mv` + edits.
- **`treemapify` 2.5.6 is broken against `ggplot2` 4.0.1`** (a `geom_
  treemap()` internal API mismatch, `argument of length 0` in
  `tile_f()`). This crashed `ddbmFF.R`'s `DDBMPositionPointsTree.png`
  chart during live verification -- confirmed as a pre-existing
  dependency-version-drift issue, NOT caused by this session's changes
  (13+ other charts rendered successfully before this one failed,
  including charts written to the new `r-analysis/data/results/2025/`
  location, proving the path-resolution fix itself works). Not fixed;
  flagged for whoever next touches `ddbmFF.R`'s R environment.
- **dplyr `left_join` many-to-many warnings in `leagueAnalytics.R`** --
  pre-existing dplyr-version-drift noise, script still completed
  successfully and wrote all 6 expected output files. Not a path/
  restructure issue.

---

## Constraints

- User's writing-style rules (global CLAUDE.md): no em dashes, two spaces
  after periods -- but this project's OWN established convention (per
  "preserve existing project conventions") is `--` for the em-dash
  equivalent and single spaces after periods; this handoff and all
  restructure edits followed the PROJECT convention, not the raw global
  default, consistent with prior sessions' documented practice.
- CLAUDE.md's "Code Modifications" protocol (list every file, wait for
  confirmation before editing) was followed for the restructure: the
  full file list was presented and explicitly confirmed before any
  `git mv` or edit began.
- CLAUDE.md's "Destructive Operations" protocol: `test.json`'s deletion
  was explicitly flagged as destructive and confirmed separately before
  being carried out; the dev-server-stop blocker (see Rejected
  Approaches / discoveries) was handed back to the user rather than
  self-resolved by killing processes.
- Never manage the dev server myself (existing standing feedback memory,
  `feedback_reuse_dev_server.md`) -- when `git mv python webapp` failed
  with a Windows file-lock (the dev server was running from
  `python/venv`), the correct response was to ask the user to stop it
  manually, NOT kill the process myself. User did stop it; work resumed
  cleanly.
- `sentiment-analysis/` must not import from or modify
  `webapp/sleepermetrics`/`webapp/webapp` -- confirmed clean via a
  dedicated verification pass (grep for cross-references, live import
  test) at the user's explicit request in the final turn of this session.

---

## Rejected Approaches

- **Rejected**: Manually fixing each of the 8 `parents[2]` occurrences
  in place without a shared helper module. **Why**: user explicitly
  wanted "0 hard-coded items as possible" -- centralizing was chosen
  over item-by-item patching specifically to remove the duplicated-
  computation root cause, not just its current symptom.
- **Rejected**: Giving the R *package* (`sleepermetrics`) the same
  `this.path`-based self-location fix as the origin scripts. **Why**:
  doesn't make sense for an installable package with no fixed source
  location; see Important Decisions above for the full reasoning. This
  asymmetry between origin-scripts and package is intentional, not an
  oversight -- don't "fix" it by adding this.path to the package later
  without re-deriving why it was excluded here.
- **Rejected**: A `commandArgs()`-based self-location fix for the origin
  scripts (no new R dependency). **Why**: doesn't work when a script is
  sourced interactively inside RStudio (no `--file=` arg present in that
  case), so it doesn't actually solve the cwd-ambiguity problem in the
  one case (RStudio, "the author's way" per CLAUDE.md) that matters
  most. Presented to the user as a real option with this caveat; they
  chose `this.path` instead once it was clear commandArgs was not a full
  fix.
- **Rejected**: Trying to make ONE path-resolution formula cover both the
  real repo layout AND the Dockerfile's flattened `/app/` layout.
  **Why**: they are genuinely different relative shapes (see Important
  Discoveries), not the same computation at different depths -- forcing
  one formula to cover both would have made the (already correct, already
  working) Docker `ENV SLEEPERMETRICS_SEASON_DIR=` override redundant or
  wrong. Kept them as two intentionally separate mechanisms instead.
  Documented explicitly in `repo_paths.py`'s own docstring so a future
  editor doesn't try to "simplify" this into one formula.
- **Rejected**: Deleting `sleeperPlayers.json`/`sleeperPlayersSorted.json`
  (confirmed orphaned -- nothing in the repo reads them, gitignored).
  **Why**: user chose to move them into `r-analysis/` for consistency
  with the R-scoped grouping instead of deleting, even though nothing
  currently reads them there either. A deliberate, low-risk organizational
  choice, not an oversight -- don't "clean these up" by deleting them
  without asking again.
- **Rejected**: Moving `.Rproj.user/` alongside the relocated `.Rproj`
  file. **Why**: it holds session/cursor-position state keyed to the OLD
  project path; carrying it forward risked stale/mismatched project
  metadata. Left at the old (repo root) location to regenerate cleanly
  next to `r-analysis/FantasyFootball.Rproj` on first RStudio open there.

---

## Remaining Work

Nothing blocking. Optional follow-ups, none requested/required:

1. **(Recommended before next deploy)** Run `docker build -t
   sleepermetrics .` manually to validate the Dockerfile changes --
   Docker Desktop was not running during this session and was
   deliberately not started. This is the one validation step from the
   original plan that could not be completed.
2. **(Optional)** The pre-existing `testthat` failure in `test-playoffs.R`
   (`write_cfg()`'s test helper writes `<dir>/2025.json` directly instead
   of the `<dir>/<league_id>/2025.json` shape `sl_playoff_configs()`
   requires) was confirmed identical against the pre-restructure code via
   `git stash` and left as out of scope. Fix only if asked.
2b. **(Optional)** `treemapify` 2.5.6 vs `ggplot2` 4.0.1 incompatibility
   breaks `ddbmFF.R`'s treemap chart. Pre-existing environment issue, not
   caused by this session. Fix (upgrade/downgrade one of the two
   packages) only if `ddbmFF.R`'s full chart set is needed again.
3. **(Optional)** `sentiment-analysis/` has no model/source/hosting
   decision yet -- next step per its own README is either growing
   `Data/hand-labeled/hand_labeled.csv` with more real examples, or
   installing the full `requirements.txt` and running the full
   VADER/cardiffnlp/FinBERT comparison. Not started; genuinely the next
   phase, not a forgotten task.
4. **(Not yet committed)** Nothing in this session's work has been
   committed to git. If/when the user asks for a commit, note the scale
   (300+ file moves via `git mv`, plus edits) -- consider whether they
   want one large restructure commit or split by concern
   (sentiment-analysis addition vs. the repo-root restructure are
   logically separate and could be two commits).

---

## Risks / Unknowns

- **Docker build unverified** (see Remaining Work #1). The Dockerfile
  edits were carefully reasoned through (COPY paths, ENV var, the
  flattened-layout path-resolution mismatch) but never build-tested this
  session. Low risk given the reasoning was thorough and cross-checked
  against `repo_paths.py`'s own documented Docker-case handling, but
  it's the one unverified piece.
- **If a FOURTH hardcoded path-hop-count or stale-literal turns up later**
  (beyond the two already found and fixed:
  `data/seasons/scaffold.py`, and the original 8 in `webapp/*.py`), the
  fastest way to find it is the same broad repo-wide grep already proven
  to work this session: `grep -rn "\bpython/|\bseason/|R/sleepermetrics"
  --include={py,R,md,yml} .` (excluding `.claude*`/`.refactor-backup`),
  then manually filter false positives (prose uses of these words are
  common and NOT paths -- "Pre-season/draft", "--python/--r flag",
  "season/league" as an "or", "field1/field2/season/field4" lists).

---

## Reference Documents

- `CLAUDE.md` (repo root) -- read the "2026-09 repo-root restructure"
  bullet (search for that exact phrase) and the rewritten "Working
  directory" bullet immediately before it, before touching path
  resolution, `ddbmFF.R`/`leagueAnalytics.R`, or the R package's
  `sl_season_dir()` again.
- `README.md` (repo root) -- "What's in here" table and Setup section
  reflect the new layout.
- `sentiment-analysis/README.md` -- full architecture/research notes for
  the sentiment feature; read before resuming that work.
- `data/seasons/README.md` -- updated for the new path; describes the
  playoff-bracket-config directory contract in detail.
- `webapp/webapp/README.md` -- updated for the new path.
- `parity/README.md` -- updated for the new paths.
- No other design docs specific to either piece of work exist.

---

## Resume Prompt

Review this handoff completely before making changes.

Review CLAUDE.md's "2026-09 repo-root restructure" bullet and the
"Working directory" bullet before touching path resolution
(`webapp/repo_paths.py`, `r-analysis/sleepermetrics/R/paths.R`,
`parity/paths.py`, `ddbmFF.R`/`leagueAnalytics.R`'s `SCRIPT_DIR`, or
`sl_season_dir()`) again.

All work described above is implemented and verified -- there is nothing
to continue unless the user gives a new task. If the user reports a
"file not found" / "wrong directory" style bug anywhere in `webapp/`,
`r-analysis/`, `data/seasons/`, `parity/`, or `tools/`, suspect a missed
hardcoded path reference first and use the repo-wide grep sweep documented
under Risks / Unknowns before writing new code.

If asked to continue the sentiment-analysis work, start from
`sentiment-analysis/README.md`'s "Architecture notes" and "Datasets used"
sections -- the next real step is either growing the hand-labeled dataset
or running the full model benchmark comparison.

Preserve documented decisions and do not revisit rejected approaches
unless new information requires it.
