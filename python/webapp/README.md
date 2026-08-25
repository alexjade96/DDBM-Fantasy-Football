# Python web dashboard (FastAPI + HTMX)

The Python instance's web app, mirroring the R Shiny dashboard tab for tab.

```bash
python launch.py dashboard                     # -> http://127.0.0.1:8000
python launch.py dashboard --port 8080
```

## Why FastAPI + HTMX

The charts are **already** matplotlib figures in `sleepermetrics/plots.py`. This
app streams those exact figures as PNG, so it adds **no plotting code at all**,
which means the R↔Python chart mirror and the `verify.py` parity harness keep
protecting them for free. A Plotly/Dash port would have meant re-implementing all
22 charts and breaking that mirror.

HTMX supplies the interactivity (tab switching, season switching, live playoff
re-scoring) with ~14kb of JS, no build step, and no client-side state.

## Routes

| Route | What it does |
|---|---|
| `GET /` | the shell: league + season pickers, tab nav |
| `GET /tab/{name}` | an HTML fragment, swapped into `#panel` by HTMX |
| `GET /chart/{name}` | a chart, rendered from `plots.py` and streamed as PNG |
| `GET /health` | liveness probe (used by the Docker healthcheck) |

Tabs: `overview`, `weekly`, `coaching`, `roster`, `transactions`, `playoffs`,
`career`, the same seven the Shiny app has.

## Notes

- **Caching.** Assembling a league is many API calls, so `league_data()` holds it
  for `SLEEPERMETRICS_TTL` seconds (default 900). Charts redraw cheaply from the
  cached frames, so tab switches stay fast.
- **Live playoffs.** `/tab/playoffs?refresh=1` clears the weekly stat-line cache
  before re-scoring, so a week still in progress is never served stale points.
  It also cache-busts the chart URLs.
- **Champions** come from the stored brackets in `season/<league_id>/` (via
  `apply_playoffs`), not Sleeper's `winners_bracket`; see `season/README.md`.
- **ADP cache.** The Draft tab's redraft-by-ADP simulation reads/writes
  `season/adp/<season>.json`, a fallback snapshot of Sleeper's undocumented
  ADP endpoint; see `season/README.md`.

## Environment

| Var | Default |
|---|---|
| `SLEEPERMETRICS_LEAGUE` | the DDBM league id |
| `SLEEPERMETRICS_SEASON_DIR` | `<repo>/season` |
| `SLEEPERMETRICS_TTL` | `900` (seconds) |
| `PORT` | `8000` (hosts inject this) |

## Free hosting

`Dockerfile` (repo root) builds this app and works unchanged on any host that
injects `$PORT`:

| Host | Free tier | Notes |
|---|---|---|
| **Render** | free web service | easiest; sleeps when idle, cold start ~30–60s |
| **Fly.io** | small free allowance | keeps a machine warm; `fly launch` reads the Dockerfile |
| **Google Cloud Run** | generous free tier | scale-to-zero, pay nothing when idle |
| **Hugging Face Spaces** | free (Docker SDK) | simplest public link |

The app is read-only over the public Sleeper API and holds no secrets (the
Discord token lives in `.env`, which this app never reads), so a public
deployment exposes nothing that isn't already public.
