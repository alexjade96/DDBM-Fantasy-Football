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
  # Sleeper marks "no previous season" as either NULL or the string "0"
  # depending on the league; "0" would otherwise issue GET /league/0, which
  # 404s and takes the whole chain walk down with it.
  while (!is.null(id) && !is.na(id) && nzchar(id) && id != "0") {
    lg <- sl_league(id)
    chain[[lg$season]] <- list(
      league_id = lg$league_id,
      season = lg$season,
      name = lg$name,
      last_scored_leg = lg$settings$last_scored_leg %||% 0L,
      # Phase signals from Sleeper: `status` is pre_draft/drafting/in_season/
      # complete, `playoff_week_start` the first postseason week. The latter
      # splits the regular season off from the playoff weeks -- see sl_season().
      status = lg$status %||% NA_character_,
      playoff_week_start = lg$settings$playoff_week_start %||% 0L,
      roster_positions = unlist(lg$roster_positions))
    id <- lg$previous_league_id
  }
  chain[order(as.integer(names(chain)))]
}

#' The origin (oldest) league_id in a league's season chain
#'
#' Stable forever, since a chain only ever extends FORWARD as new seasons are
#' created (the oldest link's own `previous_league_id` is null by
#' definition, and Sleeper never rewrites history). This is the folder key
#' `season/<league_id>/` bracket configs should use (see
#' [sl_playoff_configs()]), NOT any individual season's own, season-specific
#' id -- Sleeper gives every season of a league a DIFFERENT league_id, so
#' keying by a single season's id would scatter one real league's brackets
#' across as many folders as it has seasons.
#'
#' @param league_id Any league id in the chain (usually the current/head one).
#' @return The chain's oldest league_id.
#' @export
sl_root_league_id <- function(league_id) {
  chain <- sl_league_chain(league_id)
  chain[[1]]$league_id
}

# Starter-slot counts from roster_positions (drops bench/IR/taxi). Internal.
sl_starter_slots <- function(roster_positions) {
  rp <- roster_positions[!roster_positions %in% c("BN", "IR", "TAXI")]
  as.list(table(factor(rp)))
}
