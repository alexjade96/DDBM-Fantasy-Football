# DDBM Fantasy Football

Analytics for [Sleeper](https://sleeper.com) fantasy football leagues, grown from
the "DDBM" redraft league into a reusable package that works for **any** league id.

Two parallel implementations (**R** and **Python**) compute byte-identical metrics,
enforced by a cross-language test harness. Each ships a **web dashboard**, a
**Discord bot**, and a **custom playoff engine** for leagues whose postseason
Sleeper can't express.

---

## Quick start

Everything runs through one entry point, `launch.py`. The instance defaults to
Python; pass `--r` for the R instance (`--python` is the explicit default). The
flag may sit before or after the mode.

### Web dashboards

```bash
python launch.py dashboard                     # FastAPI + HTMX  -> http://127.0.0.1:8000
python launch.py --r dashboard                 # Shiny           -> http://127.0.0.1:8100

python launch.py dashboard --port 8080         # pick a port
python launch.py --r dashboard --port 8200

python launch.py dashboard --no-reload         # serving for real, not editing
```

The Python dashboard hot-reloads on save (code *and* templates together; see
`--no-reload` above to turn that off). The Shiny app does not: `runApp` reads the
source once at startup, so after editing it you must stop and relaunch.

Both serve the same seven tabs (season overview, weekly trends, coaching &
scoring, roster & positions, transactions, playoffs, career) and the same 22
charts. Type any Sleeper league id to switch leagues; historical seasons are
found automatically.

> On Windows, R is often not on `PATH`. `launch.py --r dashboard` locates
> `Rscript.exe` for you. There is also a direct launcher:
> `.\tools\dev\run_dashboard.ps1 [-Port 8100]`.

### Discord bot

```bash
python launch.py serve                         # slash-command bot (discord.py gateway)
python launch.py weekly --dry-run              # preview a weekly recap
python launch.py --r serve                     # R interactions endpoint (plumber)
python launch.py --r weekly --dry-run
```

Config lives in each instance's `.env` (`fantasy-football-4-fun/.env`,
`r-analysis/.env`); copy the `*.env.example` templates and fill in your
Discord token / webhook.

### Verify everything

```bash
python verify.py                               # both test suites + R<->Python parity
```

Runs `pytest`, `testthat`, re-derives every playoff champion from the stored
lineups, then exports both implementations' metrics and diffs them field by
field. Exit 0 only if all pass. **Run this after changing either implementation.**

### Regenerate charts

```bash
Rscript tools/dev/render_examples.R                                         # 22 charts -> r-analysis/data/results/examples/r/
fantasy-football-4-fun/venv/Scripts/python tools/dev/render_examples.py     # 22 charts -> r-analysis/data/results/examples/py/
```

---

## Setup

```bash
# Python instance
python -m venv fantasy-football-4-fun/venv
fantasy-football-4-fun/venv/Scripts/pip install -r fantasy-football-4-fun/requirements.txt   # Windows
# fantasy-football-4-fun/venv/bin/pip install -r fantasy-football-4-fun/requirements.txt     # macOS/Linux

# R instance: install the deps once, then load the package
# install.packages(c("tidyverse","httr2","ggplot2","ggrepel","shiny","bslib","DT","ragg","pkgload","this.path"))
```

---

## What's in here

| Path | What it is |
|---|---|
| `r-analysis/sleepermetrics/` | the R package: metrics, plots, summaries, Shiny app, Discord bot |
| `r-analysis/ddbmFF.R`, `app.R`, `leagueAnalytics.R` | the **origin scripts**, historical basis, left largely untouched |
| `r-analysis/FantasyFootball.Rproj` | the RStudio project for the R instance |
| `fantasy-football-4-fun/sleepermetrics/` | the Python port: same modules, `pandas` + `matplotlib` |
| `fantasy-football-4-fun/webapp/` | the Python web dashboard (FastAPI + HTMX) |
| `data/seasons/` | custom playoff engine configs (one bracket per league+season) and the Python Draft tab's ADP cache |
| `tools/parity/` + `verify.py` | the cross-language harness that keeps R and Python identical |
| `tools/dev/` | launchers and chart regeneration |
| `Dockerfile` | builds the Python dashboard for free hosting |

### The playoff engine

Sleeper can only express *its own* bracket. DDBM 2025 ran a **choose-your-opponent**
playoff by hand (weeks 15–18, seeds 1–2 double-byed, lineups submitted to the
commissioner), and Sleeper's stored bracket for it is genuinely incoherent.

So brackets come from config, and points are recomputed from first principles:
every submitted starter is priced from raw weekly stat lines × the league's own
**scoring chart** (`scoring_settings`). Only **roster inputs** are needed per
matchup; winners advance automatically.

This is verified exact: it reproduces Sleeper's own player points (175/175 in
wk15) and, replaying Sleeper's own bracket, all 12 matchup winners with zero
mismatches. Season champions come from these brackets, not Sleeper's
`winners_bracket`. See [`data/seasons/README.md`](data/seasons/README.md).

### Free hosting

The `Dockerfile` honours `$PORT`, so the Python dashboard deploys unchanged to a
**Render free web service**: connect the repo once in the Render dashboard and it
builds the `Dockerfile` and redeploys on every push to `main`. The webapp is
read-only over the public Sleeper API and reads no secrets. The free tier spins
down after 15 minutes idle (about a 1 minute cold start) and has no persistent
disk, so the player and headshot caches rebuild on wake; the player dump is one
Sleeper fetch and `players()` refetches daily anyway.

The weekly Discord recap runs on a GitHub Actions scheduled workflow rather than
a Render cron (Render crons are paid). Hugging Face Spaces is a fallback (same
`Dockerfile`, no card) but the Space is public.

See also [`fantasy-football-4-fun/webapp/README.md`](fantasy-football-4-fun/webapp/README.md).

---

## Notes

- Chart PNGs are gitignored build artifacts; regenerate them with the commands above.
- `CLAUDE.md` holds the architecture notes and the gotchas worth knowing before
  changing anything (week caps, NA playoff matchups, season-shape tolerance).
