# Hosting & CI/CD Implementation Plan

**Implementation Plan / For Review**

Getting the FastAPI + HTMX webapp onto a host, wiring GitHub Actions to test it,
and scheduling the weekly Discord recap, laid out phase by phase so it can be
approved, trimmed, or redlined before any infra work starts.

**Constraint this revision enforces:** everything here stays on a genuine free
tier that will **not** silently convert to a paid bill.  A platform that
auto-charges past a free allowance with no manual upgrade step (Fly.io for new
accounts, Google Cloud Run) is excluded even where it would fit technically.  The
one always-on paid item (the slash-command bot) is called out as explicitly
opt-in and is not part of the recommended build.

| | |
|---|---|
| **Repo** | DDBM-Fantasy-Football |
| **Scope** | Python webapp only |
| **Status** | Proposal, nothing built |
| **Base** | `main` @ 201976f |
| **Recurring cost of the recommended build** | **$0** |

---

## 1. What is being deployed

Four things live in this repo.  Only one of them runs as a long-lived process in
the recommended build; one is a scheduled job, one is opt-in and paid, and one
never leaves CI.

| Component | What it is | Deploy shape | In the free build? |
|---|---|---|---|
| `webapp.app:app` | FastAPI + HTMX dashboard; charts are server-rendered matplotlib PNGs | Long-running web service, 1 container | **Yes** -- Render free web service |
| Weekly recap (`bot.py weekly`) | One-shot post of a weekly recap to a Discord webhook | Scheduled job (cron) | **Yes** -- GitHub Actions scheduled workflow |
| Discord bot (`bot.py serve`) | discord.py gateway bot answering slash commands (`/standings`, `/luck`, ...) | Always-on worker, persistent gateway connection | **No** -- no free always-on host exists; opt-in at ~$7/mo |
| `sleepermetrics` pkg + `verify.py` | The metrics engine and the R<->Python parity harness | CI only | Never deployed |

### Runtime facts that drive every choice below

- **No database.**  All data is fetched live from the public Sleeper API and
  cached *in-process* (`_cache`, 15-min TTL) plus a few disk caches
  (`sleeperPlayerData_py.pkl` ~8 MB daily; `~/.cache/sleepermetrics/headshots/`).
  Losing the disk caches costs a slower first request, never data.
- **Committed data ships in the image.**  `season/**/*.json` bracket configs and
  `season/adp/*.json` are read from disk; the existing Dockerfile already
  `COPY season ./season`.
- **CPU-bound, single-threaded rendering.**  `plots._render_lock` serialises
  every matplotlib render.  Concurrency comes from more containers, not threads.
  One small instance serves a private league comfortably.
- **The webapp needs zero secrets.**  The Sleeper API is public and
  unauthenticated.  Only the Discord recap needs `DISCORD_WEBHOOK`.
- **The `Dockerfile` already exists and is correct** -- honours `$PORT`, sets
  `MPLBACKEND=Agg`, has a `/health` healthcheck, builds from the repo root.
  Render deploys it directly with no platform-specific config file.

---

## 2. Hosting recommendation

### The free-tier landscape, checked against the no-silent-billing bar

| Platform | Free tier for a new account? | Can it bill without a manual upgrade? | Verdict |
|---|---|---|---|
| **Render** free "Hobby" web service | Yes, forever.  512 MB RAM, 0.1 CPU, 750 instance-hrs/mo, 100 GB bandwidth/mo, 500 build min/mo | **No.**  Over-limit = the service sleeps / throttles.  Card required at signup for verification, never charged on the free tier, no auto-upgrade | **Recommended** |
| **Fly.io** | **No** -- removed for new accounts in 2024.  2-hr / 7-day trial, then pay-as-you-go (~$5/mo floor) | Yes -- pay-as-you-go by design | Excluded |
| **Google Cloud Run** | Always-free quota (2M req, 180k vCPU-sec/mo) that never expires | **Yes** -- past the quota it auto-converts to billable with no hard cap and no upgrade step | Excluded by the constraint |
| **Hugging Face Spaces** | Free CPU tier, no card | No | Viable fallback, but public by default and a shared 2-vCPU box |

### Recommended -- Render free web service

- Deploys the existing `Dockerfile` directly (`Environment: Docker`), no
  `render.yaml` needed, no CLI.  Connect the GitHub repo once in the Render
  dashboard; it redeploys on every push to `main` automatically.
- **Card required at signup** (fraud check) but the free web service **never
  incurs a charge** and **does not auto-upgrade** -- if you blow past 750 hrs or
  100 GB it sleeps, it does not invoice.
- Cold start: the free service **spins down after 15 min idle** and takes
  **~1 min to wake** on the next request.  For a private league dashboard checked
  a few times a week, acceptable.  This is the price of $0.  An external HTTP
  pinger (cron-job.org) can hold it warm during a chosen daily window if the
  cold start proves annoying -- but that spends the same 750 instance-hrs/mo it
  protects, so it has to be *windowed*, not 24/7.  Full trade-off and setup in
  the action doc's **Phase 5b**.

> **Decision -- platform**
>
> **Render free "Hobby" web service.**  It is the only option that is free
> forever, needs no manual step to stay free, and cannot silently start billing.
> The cold start is the trade-off and is judged acceptable for this audience.
> **Hugging Face Spaces** is the fallback if Render's free tier is ever cut
> further -- same Dockerfile, no card, but the Space is public.

> **Gotcha -- 512 MB RAM ceiling**
>
> pandas + matplotlib + a loaded league can run close to 512 MB.  Mitigations,
> in order: (1) the app already renders one chart at a time under
> `_render_lock`, so peak is one figure not many; (2) set
> `SLEEPERMETRICS_NO_IMAGES=1` to drop player-headshot fetching/compositing
> entirely if memory is tight; (3) the 15-min `_cache` TTL bounds how many
> `Season` objects are resident.  If it still OOMs, that is the signal to move
> to a paid 1 GB instance ($7/mo) -- a deliberate, manual decision, not an
> automatic one.

> **Gotcha -- no persistent disk on the free tier**
>
> Free Render web services **cannot attach a persistent disk**, so
> `sleeperPlayerData_py.pkl` and the headshot cache are rebuilt after every cold
> start / redeploy.  The player dump is one ~8 MB Sleeper fetch on the first
> request after a wake; `players()` already refetches daily anyway, so the only
> effect is that first request being a few seconds slower.  No code change
> needed.  (The `[mounts]` volume and the `SLEEPERMETRICS_CACHE` env var from
> the earlier Fly-based draft are dropped.)

**Secrets** (Render dashboard -> the service -> Environment): `DISCORD_WEBHOOK`
only, and only if you also want the recap posted from a Render cron instead of
GitHub Actions (you don't -- see 3c).  The webapp itself needs no secrets.

---

## 3. CI/CD with GitHub Actions

Two workflows under `.github/workflows/`.  Deploy is **not** a workflow -- Render
auto-deploys from `main` on its own, so there is no `deploy.yml`, no
`FLY_API_TOKEN`, no third-party deploy action.

> **Billing safety note -- GitHub Actions**
>
> Private-repo Actions include **2,000 Linux minutes/month** free.  The default
> **spending limit for Actions/Packages on a personal account is $0**, which
> means once the free minutes are gone, jobs are **blocked, not billed**.  The
> Dec 2025 "cloud platform charge" that would have changed this was **postponed
> indefinitely** after backlash; the Jan 2026 change that shipped was a price
> *cut*.  **Action item: leave the Actions/Packages spending limit at $0.**  Do
> not raise it (raising it for Codespaces or Packages would also expose Actions
> overage to billing).  This plan's usage is ~5 min per PR + ~4 min per weekly
> recap = well under 100 min/month.

### 3a. `ci.yml` -- test on every push and PR

The pytest suite is **network-free** (`conftest.py` fixtures +
`SLEEPERMETRICS_NO_IMAGES=1`): 114 tests, ~8 s, no secrets, no flakiness.

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request:
jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r python/requirements.txt
      - name: pytest (network-free)
        env: { SLEEPERMETRICS_NO_IMAGES: "1" }
        working-directory: python
        run: python -m pytest -q
```

- **Optional lint**: add a `ruff check python/` step.  Not used in the repo
  today, so introduce it `continue-on-error: true` first -- don't wall off a
  green repo on day one.
- **R parity (`verify.py`)** needs R, `Rscript` and the `sleepermetrics` R
  package.  Put it in a *separate, optional* job (`r-lib/actions/setup-r@v2` +
  `setup-r-dependencies`) gated with a `paths:` filter on `R/**`, `parity/**`,
  plus `workflow_dispatch`.  The R toolchain install is ~5-10 min -- don't pay it
  in minutes on a Python-only PR.

### 3b. Deploy -- Render auto-deploy, no workflow

- In the Render dashboard: **New -> Web Service -> connect the GitHub repo ->
  Environment: Docker -> Instance Type: Free**.  Save.
- Render builds the `Dockerfile` and redeploys on every push to `main`
  automatically.  No `deploy.yml`, no deploy token in GitHub, no
  `superfly/flyctl-actions`.
- Optional health gate: add a one-line step to `ci.yml`'s end (only on
  `push` to `main`, `if: github.ref == 'refs/heads/main'`) that
  `curl -fsS https://<service>.onrender.com/health` a minute after the push, so a
  broken deploy shows red in Actions.  Purely informational -- Render deploys
  regardless.

> **Decision -- no automated deploy pipeline**
>
> A private league dashboard with no DB and no migrations does not need
> blue-green or a gated deploy.  Render's built-in auto-deploy plus the optional
> `/health` curl is enough, and it keeps the GitHub side free of deploy
> credentials.

### 3c. `weekly-recap.yml` -- scheduled Discord post

```yaml
name: Weekly recap
on:
  schedule:
    - cron: "0 15 * * 2"        # Tue 15:00 UTC, after MNF settles
  workflow_dispatch:
jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12", cache: pip }
      - run: pip install -r python/requirements.txt
      - working-directory: python
        env:
          DISCORD_WEBHOOK: ${{ secrets.DISCORD_WEBHOOK }}
          SLEEPERMETRICS_LEAGUE: "1252770181306929152"
        run: python bot.py weekly --webhook "$DISCORD_WEBHOOK"
```

- This is the **free way to run the recap** -- GitHub runs it, no always-on host,
  no Render cron (Render cron jobs are **paid-only**, min $1/mo).  It hits the
  live Sleeper API and posts to the webhook.  `workflow_dispatch` fires it
  manually to test.
- `DISCORD_WEBHOOK` is a **GitHub repo secret**
  (`gh secret set DISCORD_WEBHOOK`), never committed.
- The **slash-command bot cannot be a cron job** -- it is a persistent gateway
  connection.  There is **no free always-on host** for it (Fly, Render workers,
  Cloud Run always-on are all paid or billing-capable).  If you want slash
  commands, that is an explicit ~$7/mo decision for a Render background worker,
  outside this plan.  The scheduled webhook recap covers "post to Discord"
  without it.
- **Timing caveat**: Actions `cron` is best-effort and can lag 5-15 min under
  load.  Fine for a recap; set the day/hour to your league's real schedule.

> **Do not build**
>
> - **A `deploy.yml` / Fly / Cloud Run deploy job** -- Render auto-deploys itself;
>   adding one just puts a deploy credential in GitHub for no gain.
> - **A container-registry push step** -- Render builds the Dockerfile on its own
>   infra.
> - **A staging environment** -- no DB, no migrations, one reader.
> - **Secrets in the webapp CI or in the web service** -- both are
>   public-API-only.
> - **Raising the GitHub Actions/Packages spending limit above $0.**

---

## 4. Rollout order

Ordered because each step de-risks the next: prove the pieces in isolation before
automating them together.

### 01 -- `.dockerignore` (new)

Exclude `python/venv/` (259 MB), `**/__pycache__`, `.git`, `samples/`,
`.claude*`, `R/`, `*.rds`.  The venv must never enter the build context (it would
also blow past Render's build limits).

*Zero risk, no runtime change.*

### 02 -- `ci.yml`

Get the green check on pull requests first.  It runs the existing suite unchanged
and adds no dependencies to the repo.

*Zero risk, CI only.*

### 03 -- Deploy manually once on Render

Dashboard: New Web Service -> connect repo -> Docker -> **Free** instance.  Then
eyeball the live site across phases -- DDBM 2026 is genuinely pre-season right
now, and 2022-2025 are finished, so every phase branch is reachable with real
data.  Watch the Render logs for an OOM on the first heavy chart render (the
512 MB ceiling); if it appears, set `SLEEPERMETRICS_NO_IMAGES=1` in the
service's env and redeploy.

*Low risk, free tier, reversible (delete the service).*

### 04 -- Confirm auto-deploy + optional `/health` gate

Push a trivial change to `main`, confirm Render redeploys.  Optionally add the
`if: github.ref == 'refs/heads/main'` `/health` curl step to `ci.yml`.

*Low risk, no new credentials.*

### 05 -- `weekly-recap.yml`

Add the workflow, set the `DISCORD_WEBHOOK` repo secret, test immediately with
`workflow_dispatch` rather than waiting a week for the cron.

*Low risk, posts to one channel.*

### 06 -- Optional follow-ups

- The R-parity CI job, `paths:`-gated to `R/**` and `parity/**`.
- A non-blocking `ruff` lint step.
- The two cosmetic gaps from the last review (`plot_clutch` empty guard,
  `_liveband.html` pre-season copy) -- unrelated to hosting, tracked in
  CLAUDE.md.
- **If, and only if, cold starts prove too annoying:** either a windowed
  cron-job.org pinger (`$0`, action doc Phase 5b -- must stay under the 750
  instance-hr/mo cap), or a manual upgrade to Render's $7/mo Starter instance
  (always-on, 512 MB) or $25/mo Standard (always-on, 2 GB).  Both are
  deliberate, never automatic.

*Deferred, quality / comfort, not blocking.*

---

## 5. Cost

| Line item | Configuration | Monthly | Can it auto-bill? |
|---|---|---|---|
| Render -- webapp | Free "Hobby" web service, Docker, 512 MB, spins down at 15 min idle | **$0** | No -- over-limit sleeps, card never charged on free tier |
| GitHub Actions -- CI | ~5 min per PR, ~4 min per weekly recap; 2,000 free min/mo | **$0** | No -- default $0 spending limit blocks over-quota jobs |
| **Recommended build total** | | **$0** | |
| *Opt-in later:* always-on slash bot | Render background worker, 512 MB | ~$7 | Only after you manually change the instance type |
| *Opt-in later:* always-on webapp (no cold start) | Render Starter web service | ~$7 | Only after you manually change the instance type |

Every paid line requires a **manual instance-type change in the Render
dashboard**.  Nothing in the recommended build can move to a paid state on its
own.

---

## Open questions for the reviewer

- **Is the ~1-minute cold start acceptable?**  It is the entire cost of running
  this at $0.  If not, the honest answer is Render Starter at $7/mo -- there is
  no free always-on option that can't also silently bill.
- **Slash commands, or is the weekly webhook recap enough?**  Slash commands need
  a paid always-on worker (~$7/mo).  The recap does not.
- **Custom domain?**  Not in this plan -- Render gives a free
  `*.onrender.com` URL; a domain is a 10-minute add later (free on Render, you
  just pay the registrar).
- **Access control?**  The dashboard is currently open to anyone with the URL.
  If that matters, a single basic-auth middleware in `webapp/app.py` is the
  lightest fix -- it becomes a new Phase 3b and needs one secret
  (`DASHBOARD_PASSWORD`) in the Render service env.

---

*Prepared for review against `main` @ 201976f.  No files created yet -- this
document is the proposal.  On approval, Phases 1-2 land as one PR, Phase 3 is a
manual Render setup, Phases 4-5 as a second PR.*
