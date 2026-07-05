# sleepermetrics

Analytical metrics for **Sleeper** fantasy football leagues. Give it a league
ID; it walks the multi-season chain and computes descriptive analytics with
ready-made `ggplot2` charts, auto-generated markdown insight summaries, and an
interactive Shiny dashboard.

This is the packaged, generalised form of the DDBM league project (the original
one-off script, `ddbmFF.R`, remains at the repo root as the origin source).

## Design

Three separated concerns:

- **compute** — `sl_standings()`, `sl_luck()`, `sl_efficiency()`,
  `sl_consistency()`, `sl_points_for_against()`, `sl_high_scores()`,
  `sl_career()`, `sl_player_loyalty()` return tidy tibbles.
- **render** — `sl_plot_*()` turn those into `ggplot` objects (`theme_sleeper()`).
- **narrate** — `sl_summary_season()`, `sl_summary_career()` return markdown.

Data flow: `sleeper_api()` → `sl_league_chain()` → `sl_season()` /
`sl_seasons()` (each returns a `sleeper_season` holding `team_wk`, `pl_wk`,
`lineup`, `standings`).

The optimal-lineup solver reads each league's `roster_positions`, so it adapts
to any roster (FLEX / SUPER_FLEX / REC_FLEX, varying team counts, etc.). Playoff
teams with `matchup_id = NA` are handled so they never generate phantom
matchups.

## Install & use

```r
# install.packages("pak"); pak::local_install("sleepermetrics")
# or from this repo:
pkgload::load_all("sleepermetrics")   # dev
# devtools::install("sleepermetrics") # installed

library(sleepermetrics)

s <- sl_season("1252770181306929152")   # most recent season
sl_standings(s)
sl_luck(s)
sl_plot_efficiency(s)
cat(sl_summary_season(s))

seasons <- sl_seasons("1252770181306929152")  # every season in the chain
sl_career(seasons)
sl_plot_trajectory(seasons)
cat(sl_summary_career(seasons))
```

## Dashboard

```r
sl_dashboard()                                   # default example league
sl_dashboard("1252770181306929152", port = 8100) # any league id
```

Requires the `shiny`, `bslib`, `DT`, `ragg` suggested packages.

## Discord

Get league analytics into Discord two ways (see
`inst/discordbot/README.md` for full setup):

```r
# 1. Weekly stats poster (webhook; schedulable, no hosting)
sl_post_weekly("<WEBHOOK_URL>", "1252770181306929152")            # post recap
sl_post_weekly("<WEBHOOK_URL>", "1252770181306929152", dry_run = TRUE)

# 2. Interactive slash-command bot (/standings /luck /weekly /career ...)
sl_discord_register_commands(app_id, bot_token, guild_id)  # one-time
sl_discord_serve(port = 8000)                              # interactions endpoint
```

The interactions endpoint verifies Discord's Ed25519 request signatures
(`sl_discord_verify()`), answers the PING handshake, and defers slash commands
so the chart/summary is delivered as a follow-up. Needs `plumber`, `sodium`,
`curl`.
