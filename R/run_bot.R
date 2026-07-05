# R instance launcher for the sleepermetrics Discord bot.
# Invoked by ../launch.py (with cwd = repo base):
#   Rscript R/run_bot.R serve                 # interactions endpoint (plumber)
#   Rscript R/run_bot.R weekly [--dry-run]    # weekly recap poster
# Config: R/.env (auto-loaded if present) or the environment.

args <- commandArgs(trailingOnly = TRUE)
mode <- if (length(args) >= 1) args[[1]] else "serve"
dry  <- any(args == "--dry-run")

if (file.exists("R/.env")) readRenviron("R/.env")

if (requireNamespace("sleepermetrics", quietly = TRUE)) {
  suppressMessages(library(sleepermetrics))
} else {
  suppressMessages(pkgload::load_all("sleepermetrics", quiet = TRUE))
}

league <- Sys.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152")

if (mode == "weekly") {
  webhook <- Sys.getenv("DISCORD_WEBHOOK")
  if (!dry && !nzchar(webhook))
    stop("Set DISCORD_WEBHOOK in r/.env (or pass --dry-run).")
  sl_post_weekly(webhook, league, dry_run = dry)
} else if (mode == "serve") {
  port <- as.integer(Sys.getenv("PORT", "8000"))
  message("Starting R interactions endpoint on port ", port,
          " (needs DISCORD_PUBLIC_KEY, DISCORD_APP_ID; put HTTPS in front).")
  sl_discord_serve(port = port)
} else {
  stop("Unknown mode: ", mode, " (use 'serve' or 'weekly').")
}
