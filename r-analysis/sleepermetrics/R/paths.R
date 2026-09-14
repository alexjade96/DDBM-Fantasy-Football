# Single source of truth for this instance's season-data directory --------

#' Resolve the season-data directory
#'
#' Every caller that needs the durable `data/seasons/` tree (custom playoff
#' bracket configs, `<root_league_id>/<season>_season.json`) used to hardcode
#' its own `"season"` default, relative to the current working directory.
#' That meant a repo restructure (or even just running from a different
#' directory) could silently point at a directory that no longer exists.
#' This function is the one place that default is computed; every other
#' caller in this package should use it instead of hardcoding a literal.
#'
#' `data/seasons/` holds ONLY league-scoped bracket configs. The Python side
#' additionally has a sibling `data/sources/` tree (the ADP cache, weekly
#' stat caches, nflverse snapshots, default scoring chart) which this R
#' package has no equivalent of -- see `data/sources/README.md`.
#'
#' Resolution order: the `SLEEPERMETRICS_SEASON_DIR` environment variable if
#' set (mirrors the Python side's own override, so both instances can be
#' pointed at the same directory); otherwise the literal `"data/seasons"`,
#' relative to the current working directory -- which is the repo root when
#' run the standard way (`launch.py --r ...`, `Rscript` from repo root, or
#' `verify.py`'s `testthat::test_local()` call), since `data/seasons/` is a
#' sibling of `r-analysis/` at the repo root, not nested inside it.
#'
#' Opening `r-analysis/FantasyFootball.Rproj` directly in RStudio instead
#' sets the working directory to `r-analysis/`, one level below repo root;
#' in that case pass an explicit path (e.g. `sl_dashboard(playoffs =
#' "../data/seasons")`) or `setwd()` to the repo root first.
#'
#' @return A (possibly non-existent) path string. Callers that need it to
#'   exist should check `dir.exists()` themselves, same as before.
#' @export
sl_season_dir <- function() {
  env <- Sys.getenv("SLEEPERMETRICS_SEASON_DIR", "")
  if (nzchar(env)) return(env)
  "data/seasons"
}
