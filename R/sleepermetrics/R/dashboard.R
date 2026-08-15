# Shiny dashboard launcher -------------------------------------------------

#' Launch the interactive dashboard
#'
#' Runs the bundled Shiny app: enter any Sleeper league id to see standings,
#' luck, lineup efficiency, consistency, points-for/against and career metrics
#' with auto-generated insight text.
#'
#' @param league_id Optional league id to pre-load (defaults to the app's
#'   built-in example league).
#' @param playoffs Root directory of season data (playoff bracket configs
#'   under `<playoffs>/<league_id>/`, plus the Python ADP cache under
#'   `<playoffs>/adp/`) to expose in the Playoffs tab. Defaults to `season/`
#'   under the current working directory if it exists. Resolved to an
#'   absolute path *before* the app starts, because [shiny::runApp()] moves
#'   the working directory to the app folder.
#' @param ... Passed to [shiny::runApp()] (e.g. `port`, `launch.browser`).
#' @return Called for its side effect (starts the app; does not return).
#' @examples
#' \dontrun{
#' sl_dashboard()
#' sl_dashboard("1252770181306929152", port = 8100)
#' }
#' @export
sl_dashboard <- function(league_id = NULL, playoffs = "season", ...) {
  for (p in c("shiny", "bslib")) {
    if (!requireNamespace(p, quietly = TRUE))
      stop("Package '", p, "' is required for the dashboard.", call. = FALSE)
  }
  if (!is.null(league_id)) Sys.setenv(SLEEPERMETRICS_LEAGUE = as.character(league_id))
  if (!is.null(playoffs) && dir.exists(playoffs)) {
    Sys.setenv(SLEEPERMETRICS_SEASON_DIR = normalizePath(playoffs))
  }
  app_dir <- system.file("shinyapp", package = "sleepermetrics")
  if (!nzchar(app_dir)) stop("Could not locate the bundled Shiny app.", call. = FALSE)
  shiny::runApp(app_dir, ...)
}
