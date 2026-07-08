# Player metadata (league-independent, cached) ----------------------------

.sl_player_cache <- new.env(parent = emptyenv())

#' Player name / position lookup
#'
#' Downloads Sleeper's full NFL player database (the largest payload it serves)
#' and reduces it to a `player_id -> name/position/gsis_id` table. The dump is
#' league-independent, so it is cached on disk (refetched at most once per day)
#' and memoised for the session.
#'
#' `DEF` "players" are team defenses; their `player_name` is set to the team
#' abbreviation (the Sleeper `player_id`).
#'
#' @param refresh Force a re-download even if today's cache exists.
#' @param cache_path RDS cache location.
#' @return A tibble with `player_id`, `player_name`, `position`, `gsis_id`.
#' @export
sl_players <- function(refresh = FALSE,
                       cache_path = "sleeperPlayerData.rds") {
  key <- "info"
  if (!refresh && !is.null(.sl_player_cache[[key]])) return(.sl_player_cache[[key]])
  fresh <- file.exists(cache_path) &&
    as.Date(file.info(cache_path)$mtime) == Sys.Date()
  raw <- if (fresh) readRDS(cache_path) else {
    r <- sleeper_api("/players/nfl"); saveRDS(r, cache_path); r
  }
  clean <- function(x, empty = NA) {
    if (is.null(x)) return(NA)
    if (is.list(x)) {
      if (!length(x)) return(empty) else return(lapply(x, clean, empty = empty))
    }
    x
  }
  df <- purrr::map_dfr(clean(unname(raw)),
                       ~ tibble::as_tibble(jsonlite::flatten(as.data.frame(.x))))
  info <- df %>%
    dplyr::transmute(
      player_id,
      player_name = dplyr::if_else(position == "DEF",
                                   as.character(player_id), full_name),
      position,
      gsis_id = as.character(gsis_id))
  .sl_player_cache[[key]] <- info
  info
}
