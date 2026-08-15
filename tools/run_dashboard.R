# Launch the sleepermetrics web dashboard.
#
#   Rscript tools/run_dashboard.R [port] [league_id]
#
# Defaults: port 8100, the DDBM league. Exposes season/ so the Playoffs tab
# finds every season's stored bracket. Run from the repo root.
#
# (A one-liner works too, but PowerShell eats the inner quotes -- hence this file.)

suppressWarnings(suppressMessages(pkgload::load_all("R/sleepermetrics", quiet = TRUE)))

args   <- commandArgs(trailingOnly = TRUE)
port   <- if (length(args) >= 1) as.integer(args[[1]]) else 8100L
league <- if (length(args) >= 2) args[[2]] else NULL

cat("Starting dashboard on http://127.0.0.1:", port, "\n", sep = "")
cat("Playoff brackets: ", paste(names(sl_playoff_configs("season")), collapse = ", "),
    "\nPress Ctrl+C to stop.\n\n", sep = "")

sl_dashboard(league_id = league, playoffs = "season",
             port = port, host = "127.0.0.1", launch.browser = FALSE)
