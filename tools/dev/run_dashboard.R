# Launch the sleepermetrics web dashboard.
#
#   Rscript tools/dev/run_dashboard.R [port] [league_id]
#
# Defaults: port 8100, the DDBM league. Exposes data/seasons/ so the Playoffs
# tab finds every season's stored bracket. Run from the repo root.
#
# (A one-liner works too, but PowerShell eats the inner quotes -- hence this file.)

suppressWarnings(suppressMessages(pkgload::load_all("r-analysis/sleepermetrics", quiet = TRUE)))

args   <- commandArgs(trailingOnly = TRUE)
port   <- if (length(args) >= 1) as.integer(args[[1]]) else 8100L
league <- if (length(args) >= 2) args[[2]] else NULL

cat("Starting dashboard on http://127.0.0.1:", port, "\n", sep = "")
cat("Playoff brackets: ", paste(names(sl_playoff_configs(sl_season_dir())), collapse = ", "),
    "\nPress Ctrl+C to stop.\n\n", sep = "")

sl_dashboard(league_id = league, playoffs = sl_season_dir(),
             port = port, host = "127.0.0.1", launch.browser = FALSE)
