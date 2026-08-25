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
> `.\tools\run_dashboard.ps1 [-Port 8100]`.

### Discord bot

```bash
python launch.py serve                         # slash-command bot (discord.py gateway)
python launch.py weekly --dry-run              # preview a weekly recap
python launch.py --r serve                     # R interactions endpoint (plumber)
python launch.py --r weekly --dry-run
```

Config lives in each instance's `.env` (`python/.env`, `R/.env`); copy the
`*.env.example` templates and fill in your Discord token / webhook.

### Verify everything

```bash
python verify.py                               # both test suites + R<->Python parity
```

Runs `pytest`, `testthat`, re-derives every playoff champion from the stored
lineups, then exports both implementations' metrics and diffs them field by
field. Exit 0 only if all pass. **Run this after changing either implementation.**

### Regenerate charts

```bash
Rscript tools/render_examples.R                          # 22 charts -> results/examples/r/
python/venv/Scripts/python tools/render_examples.py      # 22 charts -> results/examples/py/
```

---

## Setup

```bash
# Python instance
python -m venv python/venv
python/venv/Scripts/pip install -r python/requirements.txt   # Windows
# python/venv/bin/pip install -r python/requirements.txt     # macOS/Linux

# R instance: install the deps once, then load the package
# install.packages(c("tidyverse","httr2","ggplot2","ggrepel","shiny","bslib","DT","ragg","pkgload"))
```

---

## What's in here

| Path | What it is |
|---|---|
| `R/sleepermetrics/` | the R package: metrics, plots, summaries, Shiny app, Discord bot |
| `python/sleepermetrics/` | the Python port: same modules, `pandas` + `matplotlib` |
| `python/webapp/` | the Python web dashboard (FastAPI + HTMX) |
| `season/` | custom playoff engine configs (one bracket per league+season) and the Python Draft tab's ADP cache |
| `parity/` + `verify.py` | the cross-language harness that keeps R and Python identical |
| `tools/` | launchers and chart regeneration |
| `ddbmFF.R` | the **origin script**, historical basis, left untouched |
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
`winners_bracket`. See [`season/README.md`](season/README.md).

### Free hosting

The `Dockerfile` honours `$PORT`, so the Python dashboard deploys unchanged to
Render, Fly.io, Google Cloud Run or Hugging Face Spaces free tiers. It is
read-only over the public Sleeper API and reads no secrets. See
[`python/webapp/README.md`](python/webapp/README.md).

---

## Notes

- Chart PNGs are gitignored build artifacts; regenerate them with the commands above.
- `CLAUDE.md` holds the architecture notes and the gotchas worth knowing before
  changing anything (week caps, NA playoff matchups, season-shape tolerance).
