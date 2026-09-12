# Hosting & CI/CD -- Direct Action Checklist

Companion to [`hosting-cicd-plan.md`](hosting-cicd-plan.md) (the rationale).  This
doc is the **do-it list**: every file to create with its exact contents, every
command to run, every dashboard click, in order.  Check a box when it is done.

**Target:** the Python webapp on Render's free tier + GitHub Actions for CI and
the weekly Discord recap.  **Recurring cost: $0.**  No step here can move the
project to a paid state without a later, explicit manual choice.

- **Repo:** `alexjade96/DDBM-Fantasy-Football` (private)
- **Base:** `main` @ 201976f
- **League id (DDBM 2025 chain head):** `1252770181306929152`

---

## Pre-flight (once, before Phase 1)

- [ ] Confirm the suite is green:
      `cd python && SLEEPERMETRICS_NO_IMAGES=1 venv/Scripts/python.exe -m pytest -q`
      -> expect `114 passed, 2 warnings`.
- [ ] Confirm you are on `main` with a clean tree (`git status`), or branch first:
      `git switch -c infra/hosting-cicd`.
- [ ] Have a GitHub account with **Actions/Packages spending limit = $0**
      (Settings -> Billing -> Spending limits).  Leave it at $0.  Do not raise it.
- [ ] Decide: **slash-command bot?**  If no (recommended), skip every step tagged
      `[SLASH BOT ONLY]`.  If yes, it is ~$7/mo on a Render background worker and
      is a manual dashboard action, not automated here.

---

## Phase 1 -- Build context hygiene

`.dockerignore` **already exists and is correct** (it excludes `python/venv/`,
`.git`, `.github`, `.claude/`, `R/`, `**/.env`).  Nothing to create.

- [ ] Sanity-check it once:
      `git check-ignore -v --no-index python/venv/x` should print a match; if not,
      open `.dockerignore` and confirm `python/venv/` is listed (it is).
- [ ] Optional tidy: the header comment in `.dockerignore` and the `Dockerfile`
      still say `playoffs/` where the real dir is `season/`.  Cosmetic; fix only
      if you are touching those files anyway.

*Nothing to commit in this phase.*

---

## Phase 2 -- CI workflow

### 2.1  Create `.github/workflows/ci.yml`

- [ ] Create the file with exactly this content:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: python/requirements.txt

      - name: Install deps
        run: pip install -r python/requirements.txt

      - name: pytest (network-free)
        working-directory: python
        env:
          SLEEPERMETRICS_NO_IMAGES: "1"
        run: python -m pytest -q
```

### 2.2  Verify it locally first

- [ ] The workflow only runs what already passes:
      `cd python && SLEEPERMETRICS_NO_IMAGES=1 python -m pytest -q` (using a
      clean `pip install -r requirements.txt` in a throwaway venv if you want to
      catch a missing pin).

### 2.3  Commit + push

- [ ] `git add .github/workflows/ci.yml`
- [ ] `git commit -m "CI: run the network-free pytest suite on push and PR"`
- [ ] `git push`  (or push the branch and open a PR)
- [ ] On GitHub: the **Actions** tab shows the `CI` run green.  If red, read the
      log -- almost always a dependency not pinned in `requirements.txt`.

---

## Phase 3 -- First manual deploy on Render

Do this **before** wiring any deploy automation, so you see the app run once and
catch the 512 MB / cold-start behaviour with your own eyes.

### 3.1  Create the service

- [ ] Sign in at <https://dashboard.render.com> (GitHub sign-in; a card is asked
      for at signup for fraud-check -- the free web service never charges it).
- [ ] **New +  ->  Web Service  ->  Build and deploy from a Git repository.**
- [ ] Connect `alexjade96/DDBM-Fantasy-Football`, grant Render read access.
- [ ] Settings:
  - **Name:** `ddbm-ff` (this sets the URL: `https://ddbm-ff.onrender.com`)
  - **Region:** Oregon (US West) or Ohio (US East) -- closest to you
  - **Branch:** `main`
  - **Runtime / Environment:** `Docker`  (Render auto-detects the `Dockerfile`)
  - **Dockerfile Path:** `./Dockerfile`  **Docker Build Context Directory:** `.`
  - **Instance Type:** **Free**
- [ ] **Environment Variables** (Advanced): add
  - `MPLBACKEND` = `Agg`  (belt-and-suspenders; the Dockerfile already sets it)
  - `SLEEPERMETRICS_LEAGUE` = `1252770181306929152`
  - *(do NOT set `DISCORD_WEBHOOK` here -- the recap runs from GitHub Actions)*
- [ ] **Create Web Service.**  First build takes ~3-6 min.

### 3.2  Smoke-test the live site

- [ ] `curl -fsS https://ddbm-ff.onrender.com/health` -> `{"ok": true, ...}`
- [ ] Open `https://ddbm-ff.onrender.com/dashboard` in a browser.
- [ ] Click through every phase with real data:
  - **Pre-season:** paste `1313934185055936512` (DDBM 2026) -> Overview shows
    "Pre-season: the draft" + the Drafted Rosters table; Roster / Draft /
    Transactions / Season report show the "fills in once week 1" note; Playoffs
    shows the skeleton bracket only.
  - **Completed:** switch the season picker to 2022 / 2023 / 2024 / 2025 -> every
    tab renders full, charts included.
  - **History tab:** cross-season charts render.
- [ ] Watch the Render **Logs** tab during the first heavy chart render (open the
      Season report tab for 2025 -- it draws ~20 charts).  If you see
      `Out of memory` / the instance restarts:
  - [ ] Add env var `SLEEPERMETRICS_NO_IMAGES` = `1`, **Save, Manual Deploy**.
        This drops player-headshot compositing and cuts peak memory.  Re-test.
  - [ ] If it still OOMs, that is the signal for a **manual** upgrade to Starter
        ($7/mo) -- record it as a decision, do not do it silently.
- [ ] Note the cold-start feel: after 15 min idle the next request takes ~1 min.
      Confirm that is acceptable.  If not -> Starter ($7/mo), manual, later.

### 3.3  (No commit -- this phase is dashboard-only.)

---

## Phase 4 -- Confirm auto-deploy + optional health gate

Render auto-deploys from `main` by default once the service is connected.  No
`deploy.yml`, no deploy token in GitHub.

### 4.1  Prove auto-deploy

- [ ] Make a trivial visible change on `main` (e.g. a comment in
      `python/webapp/app.py`), commit, push.
- [ ] Render **Events** tab shows a new deploy triggered by the push, goes live
      in a few minutes.

### 4.2  Optional -- surface a broken deploy in Actions

Add a health check to `ci.yml` that runs **only on `main`**, a minute after the
push, so a deploy that boots but fails `/health` shows red.

- [ ] Append this job to `.github/workflows/ci.yml`:

```yaml
  deploy-health:
    if: github.ref == 'refs/heads/main'
    needs: python
    runs-on: ubuntu-latest
    steps:
      - name: Wait for Render to redeploy, then check /health
        run: |
          sleep 120
          for i in $(seq 1 10); do
            if curl -fsS https://ddbm-ff.onrender.com/health; then
              echo "healthy"; exit 0
            fi
            echo "retry $i"; sleep 20
          done
          echo "::error::/health did not come back after the deploy"; exit 1
```

- [ ] Commit: `git commit -am "CI: post-deploy /health check on main"`  ; push.
- [ ] Confirm the `deploy-health` job passes on the next `main` push.

> This job is **informational**.  Render deploys regardless of whether it passes;
> it just gives you a red X in the Actions tab if the new revision is unhealthy.

---

## Phase 5 -- Weekly Discord recap

### 5.1  Get a Discord channel webhook URL

- [ ] In Discord: the target channel -> **Edit Channel -> Integrations ->
      Webhooks -> New Webhook -> Copy Webhook URL.**

### 5.2  Store it as a GitHub repo secret

- [ ] `gh secret set DISCORD_WEBHOOK --repo alexjade96/DDBM-Fantasy-Football`
      then paste the URL at the prompt.
      *(Or: repo Settings -> Secrets and variables -> Actions -> New repository
      secret, name `DISCORD_WEBHOOK`.)*

### 5.3  Create `.github/workflows/weekly-recap.yml`

- [ ] Create the file with exactly this content:

```yaml
name: Weekly recap

on:
  schedule:
    - cron: "0 15 * * 2"      # Tuesdays 15:00 UTC -- after Monday-night games settle
  workflow_dispatch:

jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: python/requirements.txt

      - name: Install deps
        run: pip install -r python/requirements.txt

      - name: Post the weekly recap
        working-directory: python
        env:
          DISCORD_WEBHOOK: ${{ secrets.DISCORD_WEBHOOK }}
          SLEEPERMETRICS_LEAGUE: "1252770181306929152"
        run: python bot.py weekly --webhook "$DISCORD_WEBHOOK"
```

### 5.4  Test it before trusting the schedule

- [ ] Dry-run locally first (no post):
      `cd python && venv/Scripts/python.exe bot.py weekly --league 1252770181306929152 --dry-run`
- [ ] Commit + push the workflow:
      `git add .github/workflows/weekly-recap.yml && git commit -m "CI: scheduled weekly Discord recap" && git push`
- [ ] On GitHub: **Actions -> Weekly recap -> Run workflow** (the
      `workflow_dispatch` button).  Confirm it posts to the channel.
- [ ] Adjust the `cron` day/hour to your league's real weekly cadence if Tuesday
      15:00 UTC is wrong.  (Actions cron can lag 5-15 min -- fine for a recap.)

---

## Phase 5b -- Optional: cut the cold start with an external pinger

**Status:** optional, `$0` if done carefully, easy to get wrong.  Skip it if the
~1-minute wake on the first visit of the day is acceptable (it was judged
acceptable in the plan).  This section exists because
[cron-job.org](https://cron-job.org/en/) is the obvious free tool for it and the
trade-off needs to be written down before anyone wires it up.

### What it does

An external service sends a small HTTP request to `/health` on a schedule.  Each
request resets Render's 15-minute idle timer, so the service does not spin down
and the next real visitor gets a warm response instead of a ~1-minute wake.  The
ping **must** come from outside Render -- a cron job inside the app is asleep
when the app is asleep and cannot wake it.

### The catch -- it spends the 750-hour budget it protects

Render's free web service gets **750 instance-hours per workspace per calendar
month** (does not roll over).  A service only burns hours while it is *running*;
a spun-down service burns nothing.  Keeping it awake therefore trades cold starts
for instance-hours:

| Ping cadence | Awake time | Instance-hrs/mo | Under the 750 cap? |
|---|---|---|---|
| None (default) | only while serving real traffic | a few hrs | Yes, huge margin |
| Every 10 min, 24/7 | ~always | **~730** | Barely -- one other free service, or a long month, blows it |
| Every 10 min, 13:00-05:00 UTC only (~16 h/day) | draft/game-day hours | ~495 | Yes |
| Every 10 min, 2-hr pre-check window before you look | ~4 h/day | ~125 | Yes, wide margin |

**When the 750 hours run out, Render suspends *all* of your free web services
for the rest of the month** -- not just this one.  There is no `$0`-limit
safety net for instance-hours the way there is for GitHub Actions minutes; the
protection is that it *suspends* rather than *bills*, but the site does go dark.
Outbound bandwidth is a separate 100 GB/mo workspace cap; a `/health` ping is a
few hundred bytes so the pinger's bandwidth cost is nil, but note that **bandwidth
overage on a workspace with a saved card *does* bill** (instance-hours never
bill, they suspend).

### If you decide to do it

- [ ] Create a free account at <https://cron-job.org/en/>.
- [ ] **Create cronjob**:
  - **URL:** `https://ddbm-fantasy-football.onrender.com/health`
        (the real service URL -- not `ddbm-ff`, see the note in Phase 3;
        `/health` returns `{"ok": true, ...}`, touches no Sleeper API, no
        chart render)
  - **Schedule:** **not** every 5-10 min 24/7.  Restrict it to the hours the
    league actually uses the site and leave it spun down the rest of the day --
    there is no point warming the service through the night when nobody looks.
    cron-job.org supports per-hour and per-weekday selection on the free plan,
    so set it directly:
    - **Hours:** tick only the active block, e.g. `17`-`23` local plus maybe
      `12` on a weekend.  Convert to **UTC** for cron-job.org (it schedules in
      UTC unless you set a timezone in the job).  A 6-7 hour evening window is
      ~200 instance-hrs/mo, a wide margin under 750.
    - **Days:** if the league only checks in around game days, tick just those
      weekdays (e.g. Sun/Mon/Tue in season) and drop the rest.
    - Off-hours (overnight, dead midweek): **no ping** -> the service spins
      down -> the first visitor then pays the ~1-min wake, which is the
      accepted default behaviour anyway.
  - Keep it to **>= 10-minute** intervals within the active window (Render
    idles at 15 min, so 10 gives margin without waste).  cron-job.org's free
    plan allows 1-minute resolution; do not use it here.
  - Enable "save responses" / failure notification so a `502` (deploy in
    progress) or a suspended service is visible.
- [ ] After a week, check the Render dashboard -> the service -> **Metrics ->
      Instance Hours** and confirm the month's projection stays well under 750.
- [ ] Note this in the project log as a deliberate decision (it changes the
      "cold start is the price of `$0`" trade-off recorded in the plan).

### Alternatives considered

- **GitHub Actions `schedule` as the pinger** -- works (a `curl` step on a cron),
  but Actions cron is best-effort and frequently lags 5-15 min, which is exactly
  the resolution that matters here; and it spends Actions minutes.  cron-job.org
  is the better free tool for a fixed-interval HTTP ping.
- **UptimeRobot / other free monitors** -- equivalent; 5-minute floor on the
  free plan.  Same instance-hour trade-off applies identically.  cron-job.org
  chosen only because the user named it; any of them works.
- **Just paying for Starter ($7/mo)** -- removes the spin-down entirely and the
  750-hour cap does not apply to paid instances.  This is the honest fix if the
  cold start is genuinely a problem; the pinger is the `$0` workaround with the
  budget caveat above.

---

## Phase 6 -- Optional follow-ups (not blocking)

Pick up any of these later; none is required for a working $0 deployment.

- [ ] **`ruff` lint in CI**, non-blocking at first.  Add to the `python` job:

```yaml
      - name: ruff (advisory)
        continue-on-error: true
        run: |
          pip install ruff
          ruff check python/
```

- [ ] **R-parity job**, `paths:`-gated so it only runs when R code changes.
      New file `.github/workflows/parity.yml`:

```yaml
name: R parity
on:
  pull_request:
    paths: ["R/**", "parity/**", "python/sleepermetrics/**"]
  workflow_dispatch:
jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - uses: r-lib/actions/setup-r@v2
      - uses: r-lib/actions/setup-r-dependencies@v2
        with: { working-directory: R/sleepermetrics }
      - run: pip install -r python/requirements.txt
      - run: python verify.py
```

- [ ] **Fix the two cosmetic review gaps** (unrelated to hosting, tracked in
      CLAUDE.md): `plots.plot_clutch` empty-frame guard; `_liveband.html` should
      also require `scored` before showing the "in progress" banner.
- [ ] **Kill cold starts** -- only if they prove annoying: Render dashboard ->
      the service -> Settings -> Instance Type -> **Starter ($7/mo)**.  Manual,
      deliberate, reversible.
- [ ] `[SLASH BOT ONLY]` **Always-on slash-command bot** -- Render dashboard ->
      **New + -> Background Worker**, same repo, Docker, start command
      `python -m bot serve`, env `DISCORD_BOT_TOKEN` + `SLEEPERMETRICS_LEAGUE`.
      This is a paid instance type (~$7/mo); there is no free always-on option.
- [ ] **Basic-auth on the dashboard** -- if "anyone with the URL" is a problem.
      Add a tiny middleware to `python/webapp/app.py` reading
      `os.environ["DASHBOARD_PASSWORD"]`, set that var in the Render service env.
- [ ] **Update `README.md`** "Free hosting" section: it currently lists Fly.io /
      Cloud Run as options.  Narrow it to "Render free web service" and link
      `docs/hosting-cicd-plan.md`.

---

## Rollback

| To undo | Do |
|---|---|
| The whole deployment | Render dashboard -> the service -> Settings -> **Delete Web Service**.  Removes the site; the repo is untouched. |
| CI / recap workflows | `git rm .github/workflows/*.yml && git commit && git push`.  Render is unaffected (it deploys on push, not via Actions). |
| A bad revision | Render **Events** tab -> pick the last good deploy -> **Rollback to this deploy**. |
| The `DISCORD_WEBHOOK` secret | `gh secret delete DISCORD_WEBHOOK --repo alexjade96/DDBM-Fantasy-Football`.  Delete the webhook in Discord too. |

---

## Done-state

- [ ] `ci.yml` green on every PR and push to `main`.
- [ ] `https://ddbm-ff.onrender.com/dashboard` serves all phases; `/health` is 200.
- [ ] Push to `main` -> Render redeploys automatically within minutes.
- [ ] `weekly-recap.yml` posts to the Discord channel on schedule and on demand.
- [ ] GitHub Actions/Packages spending limit still **$0**.
- [ ] Monthly spend: **$0**.

---

*Every command assumes repo root as CWD unless a `working-directory` /
`cd python` is shown.  Windows shell: the repo's venv Python is
`python/venv/Scripts/python.exe`.  On approval this is roughly two PRs: Phase 2
alone, then Phases 4-6 together, with Phases 1/3/5-dashboard done outside git.*
