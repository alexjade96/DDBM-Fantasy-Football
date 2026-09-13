#' sleepermetrics: analytical metrics for Sleeper fantasy leagues
#'
#' Fetch a Sleeper league by id, walk its multi-season chain, and compute
#' descriptive analytics with ready-made charts, markdown insight summaries,
#' and an interactive dashboard.
#'
#' The design separates three concerns:
#' * **compute** ([sl_standings()], [sl_luck()], [sl_efficiency()], ...) return
#'   tidy tibbles,
#' * **render** ([sl_plot_standings()], [sl_plot_luck()], ...) turn those into
#'   `ggplot` objects,
#' * **narrate** ([sl_summary_season()], [sl_summary_career()]) turn them into
#'   markdown.
#'
#' Start with [sl_season()] for one season or [sl_league_chain()] +
#' [sl_career()] for all-time, or just launch [sl_dashboard()].
#'
#' @keywords internal
#' @import dplyr
#' @import ggplot2
#' @importFrom magrittr %>%
#' @importFrom tibble tibble as_tibble
#' @importFrom tidyr unnest unnest_wider pivot_longer
#' @importFrom purrr map map_dfr map_dbl
#' @importFrom forcats fct_reorder
#' @importFrom rlang %||% .data
#' @importFrom httr2 request req_timeout req_retry req_perform resp_body_json
#' @importFrom jsonlite flatten
#' @importFrom RColorBrewer brewer.pal
#' @importFrom grDevices colorRampPalette
#' @importFrom stats median sd
"_PACKAGE"

# Silence R CMD check notes for tidy-eval column names used across the package.
utils::globalVariables(c(
  ".", "player_id", "full_name", "position", "gsis_id", "team", "player_name",
  "roster_id", "owner_id", "user_id", "user_name", "team_name", "metadata",
  "display_name", "week", "matchup_id", "points", "pa", "opp", "opp_points",
  "result", "allplay_w", "allplay_l", "is_high", "is_starter", "starters",
  "players", "wins", "losses", "ties", "highs", "final_position", "champion",
  "season", "actual", "optimal", "left_on_bench", "eff", "bench", "luck",
  "exp_w", "win_pct", "record", "titles", "best", "seasons", "seasons_kept",
  "n", "value", "name"
))
