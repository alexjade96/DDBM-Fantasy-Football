# League scoring rules -> player points ------------------------------------
#
# Sleeper stores each league's "point calculation chart" as `scoring_settings`
# (stat key -> weight). Applying it to the raw weekly stat lines reproduces
# Sleeper's own player points exactly, which lets us score ANY lineup --
# including one a commissioner collected by hand that Sleeper never had on a
# roster (see sl_playoff()).

# Weekly stat lines are a large payload; cache them per season+week.
.sl_stats_cache <- new.env(parent = emptyenv())

#' League point-calculation chart
#'
#' The league's `scoring_settings` as a tidy table: one row per stat rule. This
#' is the chart that turns a stat line into fantasy points; snapshot it
#' alongside playoff results so they stay reproducible if settings later change.
#'
#' @param league_id Sleeper league id.
#' @return Tibble with `stat` and `weight`.
#' @seealso [sl_score_lineup()], [sl_playoff()]
#' @export
sl_scoring_chart <- function(league_id) {
  sc <- sleeper_api(paste0("/league/", league_id))$scoring_settings
  tibble(stat = names(sc), weight = as.numeric(unlist(sc))) %>%
    dplyr::arrange(stat)
}

#' League scoring rules as a named list
#' @param league_id Sleeper league id.
#' @return Named list of `stat -> weight`.
#' @export
sl_scoring_rules <- function(league_id) {
  ch <- sl_scoring_chart(league_id)
  stats::setNames(as.list(ch$weight), ch$stat)
}

#' Raw NFL stat lines for one week
#'
#' Note: distinct from [sl_week_stats()], which summarises a league's team-week
#' results. This returns raw per-player NFL stat lines straight from Sleeper.
#'
#' @param season Season string, e.g. `"2025"`.
#' @param week Week number.
#' @return A named list: `player_id -> list(stat = value)`. Cached per session.
#' @export
sl_nfl_stats <- function(season, week) {
  key <- paste0(season, "-", week)
  if (is.null(.sl_stats_cache[[key]])) {
    st <- sleeper_api(paste0("/stats/nfl/regular/", season, "/", week),
                      simplify = FALSE)
    .sl_stats_cache[[key]] <- if (is.null(st)) list() else st
  }
  .sl_stats_cache[[key]]
}

#' Drop the cached weekly stat lines
#'
#' Stat lines are cached per session. Call this before re-scoring a week that is
#' still in progress, otherwise a live playoff would keep showing stale points.
#'
#' @return `TRUE`, invisibly.
#' @export
sl_clear_stats_cache <- function() {
  rm(list = ls(envir = .sl_stats_cache), envir = .sl_stats_cache)
  invisible(TRUE)
}

#' Fantasy points for one player in one week
#' @param player_id Sleeper player id.
#' @param season Season string.
#' @param week Week number.
#' @param rules Named list of scoring rules (see [sl_scoring_rules()]).
#' @return A single numeric (points, 2dp).
#' @export
sl_score_player <- function(player_id, season, week, rules) {
  line <- sl_nfl_stats(season, week)[[as.character(player_id)]]
  if (is.null(line) || !length(line)) return(0)
  keys <- intersect(names(line), names(rules))
  if (!length(keys)) return(0)
  round(sum(vapply(keys, function(k) as.numeric(line[[k]]) * rules[[k]],
                   numeric(1))), 2)
}

#' Score a submitted lineup across one or more weeks
#'
#' The core of the manual playoff engine: give it the starters a manager handed
#' the commissioner and it prices them under the league's own rules, whatever
#' Sleeper's rosters happened to say.
#'
#' @param player_ids Character vector of Sleeper player ids (the starters).
#' @param season Season string.
#' @param weeks One or more week numbers (a multi-week round sums across them).
#' @param rules Named list of scoring rules.
#' @return Tibble with one row per `player_id` x `week` and its `points`.
#' @export
sl_score_lineup <- function(player_ids, season, weeks, rules) {
  grid <- expand.grid(player_id = as.character(player_ids), week = as.integer(weeks),
                      stringsAsFactors = FALSE)
  if (!nrow(grid)) {
    return(tibble(player_id = character(), week = integer(), points = numeric()))
  }
  tibble(player_id = grid$player_id, week = grid$week,
         points = vapply(seq_len(nrow(grid)),
                         function(i) sl_score_player(grid$player_id[i], season,
                                                     grid$week[i], rules),
                         numeric(1)))
}
