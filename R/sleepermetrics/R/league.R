# League metadata and the multi-season chain ------------------------------

#' Fetch a single league object
#'
#' @param league_id Sleeper league id (string or number).
#' @return The parsed league object (a list).
#' @export
sl_league <- function(league_id) {
  sleeper_api(paste0("/league/", league_id))
}

#' Walk a league's season chain
#'
#' Sleeper stores each season as a separate league object linked backwards by
#' `previous_league_id`. This walks that chain from the supplied (head) id and
#' returns one entry per season, oldest first.
#'
#' `last_scored_leg` is that season's last fully scored week - the correct cap
#' for week loops (live-safe, and unlike `state.week` it does not reset to 0 in
#' the offseason). `roster_positions` drives the optimal-lineup solver.
#'
#' @param league_id Head-of-chain (usually current season) league id.
#' @return A named list (names = season strings) of link lists, each with
#'   `league_id`, `season`, `name`, `last_scored_leg`, `roster_positions`.
#' @export
sl_league_chain <- function(league_id) {
  chain <- list()
  id <- as.character(league_id)
  while (!is.null(id) && !is.na(id) && nzchar(id)) {
    lg <- sl_league(id)
    chain[[lg$season]] <- list(
      league_id = lg$league_id,
      season = lg$season,
      name = lg$name,
      last_scored_leg = lg$settings$last_scored_leg %||% 0L,
      roster_positions = unlist(lg$roster_positions))
    id <- lg$previous_league_id
  }
  chain[order(as.integer(names(chain)))]
}

# Starter-slot counts from roster_positions (drops bench/IR/taxi). Internal.
sl_starter_slots <- function(roster_positions) {
  rp <- roster_positions[!roster_positions %in% c("BN", "IR", "TAXI")]
  as.list(table(factor(rp)))
}
