# Generate a standalone HTML season report (R instance).
#
#   Rscript R/make_report.R [league_id] [--season 2024] [--out file.html] [--all]
#
# Invoked by launch.py ("r report"); loads the package via pkgload and writes the
# report(s) to the repo root. Mirrors python/make_report.py.

suppressWarnings(suppressMessages(pkgload::load_all("R/sleepermetrics", quiet = TRUE)))

args <- commandArgs(trailingOnly = TRUE)
get_opt <- function(flag) {
  i <- match(flag, args)
  if (is.na(i) || i == length(args)) NULL else args[[i + 1]]
}
positional <- args[!grepl("^--", args) &
                     !(seq_along(args) %in% (match(c("--season", "--out"), args) + 1))]
league <- if (length(positional)) positional[[1]] else
  Sys.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152")
season_arg <- get_opt("--season")
out_arg <- get_opt("--out")
all_seasons <- "--all" %in% args
playoff_dir <- Sys.getenv("SLEEPERMETRICS_PLAYOFFS", "playoffs")

ss <- sl_apply_playoffs(sl_seasons(league), playoff_dir)
if (!length(ss)) stop("No scored seasons found for league ", league)
ids <- vapply(ss, function(s) s$league_id, character(1))
pos <- sl_load_playoffs(playoff_dir, league_ids = ids)

targets <- if (all_seasons) names(ss) else {
  if (!is.null(season_arg) && season_arg %in% names(ss)) season_arg else names(ss)[length(ss)]
}
for (key in targets) {
  out <- if (!is.null(out_arg) && !all_seasons) out_arg else
    sprintf("report_%s_%s.html", league, key)
  sl_season_report(ss[[key]], out, seasons = ss, playoffs = pos)
  cat(sprintf("wrote %s  (%s %s)\n", out, ss[[key]]$name, key))
}
