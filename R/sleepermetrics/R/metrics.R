# Descriptive metric tables (pure compute; no plotting) --------------------

#' Assemble every season of a league
#'
#' Convenience wrapper that walks the chain and assembles each season.
#'
#' @param league_id Head-of-chain league id.
#' @return A named list of [sleeper_season] objects (names = season strings).
#' @export
sl_seasons <- function(league_id) {
  chain <- sl_league_chain(league_id)
  stats::setNames(lapply(names(chain), function(s) sl_assemble_season(chain[[s]])),
                  names(chain))
}

# Bind the standings of a list of sleeper_season objects.
sl_bind_standings <- function(seasons) {
  dplyr::bind_rows(lapply(seasons, function(s) s$standings))
}

#' Season standings
#' @param season A [sleeper_season] object.
#' @return Standings tibble (record, points, all-play, final position, champion).
#' @export
sl_standings <- function(season) season$standings

#' Luck: actual wins vs all-play expected wins
#'
#' All-play expected wins = your win rate had you played the whole league each
#' week, scaled to games played. `luck = wins - expected`; positive is lucky.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble with `user_name`, `wins`, `exp_w`, `luck`.
#' @export
sl_luck <- function(season) {
  season$standings %>%
    dplyr::transmute(user_name, wins,
      exp_w = round(allplay_w / pmax(allplay_w + allplay_l, 1) * (wins + losses), 1),
      luck = round(wins - exp_w, 1)) %>%
    dplyr::arrange(dplyr::desc(luck))
}

#' Lineup efficiency (coaching)
#'
#' Started points as a percentage of the optimal lineup each week, and total
#' points left on the bench.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble with `user_name`, `actual`, `optimal`, `bench`, `eff`.
#' @export
sl_efficiency <- function(season) {
  season$lineup %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(actual = sum(actual), optimal = sum(optimal),
                     bench = sum(left_on_bench), .groups = "drop") %>%
    dplyr::mutate(eff = round(actual / optimal * 100, 1)) %>%
    dplyr::arrange(dplyr::desc(eff))
}

#' Weekly scoring consistency
#' @param season A [sleeper_season] object.
#' @return Tibble with `user_name`, `median`, `sd`, `min`, `max`.
#' @export
sl_consistency <- function(season) {
  season$team_wk %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(median = stats::median(points), sd = round(stats::sd(points), 1),
                     min = min(points), max = max(points), .groups = "drop") %>%
    dplyr::arrange(sd)
}

#' Points for vs points against
#' @param season A [sleeper_season] object.
#' @return Tibble with `user_name`, `points` (for), `pa` (against), `wins`.
#' @export
sl_points_for_against <- function(season) {
  season$standings %>% dplyr::select(user_name, points, pa, wins)
}

#' Weekly high-score counts
#' @param season A [sleeper_season] object.
#' @return Tibble with `user_name`, `highs` (weeks as league top scorer).
#' @export
sl_high_scores <- function(season) {
  season$standings %>% dplyr::select(user_name, highs) %>%
    dplyr::arrange(dplyr::desc(highs))
}

#' Career standings across all seasons
#'
#' Aggregates by persistent `user_id` (the same manager across seasons despite
#' changing display names), then labels with each manager's most recent name.
#'
#' @param seasons A list of [sleeper_season] objects (see [sl_seasons()]).
#' @return Career tibble ranked by win percentage.
#' @export
sl_career <- function(seasons) {
  all <- sl_bind_standings(seasons)
  canon <- all %>% dplyr::group_by(user_id) %>%
    dplyr::arrange(dplyr::desc(as.integer(season))) %>%
    dplyr::summarise(user_name = dplyr::first(user_name), .groups = "drop")
  all %>% dplyr::group_by(user_id) %>%
    dplyr::summarise(seasons = dplyr::n_distinct(season), wins = sum(wins),
                     losses = sum(losses), points = sum(points),
                     titles = sum(champion), best = min(final_position),
                     .groups = "drop") %>%
    dplyr::mutate(win_pct = round(wins / pmax(wins + losses, 1) * 100, 1),
                  record = paste0(wins, "-", losses)) %>%
    dplyr::left_join(canon, by = "user_id") %>%
    dplyr::arrange(dplyr::desc(win_pct))
}

#' Manager-player loyalty across seasons
#'
#' Players a single manager re-rostered in multiple seasons.
#'
#' @param seasons A list of [sleeper_season] objects.
#' @param min_seasons Keep players rostered by the same manager in at least this
#'   many seasons.
#' @return Tibble with `user_name`, `player_name`, `position`, `seasons_kept`,
#'   `season_list`.
#' @export
sl_player_loyalty <- function(seasons, min_seasons = 3) {
  pinfo <- sl_players()
  rostered <- dplyr::bind_rows(lapply(seasons, function(s) {
    s$pl_wk %>% dplyr::left_join(s$user_map, by = "roster_id") %>%
      dplyr::distinct(user_id, player_id) %>% dplyr::mutate(season = s$season)
  }))
  canon <- sl_bind_standings(seasons) %>% dplyr::group_by(user_id) %>%
    dplyr::arrange(dplyr::desc(as.integer(season))) %>%
    dplyr::summarise(user_name = dplyr::first(user_name), .groups = "drop")
  rostered %>% dplyr::group_by(user_id, player_id) %>%
    dplyr::summarise(seasons_kept = dplyr::n_distinct(season),
                     season_list = paste(sort(unique(season)), collapse = ", "),
                     .groups = "drop") %>%
    dplyr::filter(seasons_kept >= min_seasons) %>%
    dplyr::left_join(pinfo %>% dplyr::select(player_id, player_name, position),
                     by = "player_id") %>%
    dplyr::left_join(canon, by = "user_id") %>%
    dplyr::filter(!is.na(player_name)) %>%
    dplyr::arrange(dplyr::desc(seasons_kept), user_name, player_name)
}

# --- Roster & position analytics (ported from ddbmFF.R) -------------------

#' League scoring by position
#'
#' Total *started* points by position and each position's share of league
#' scoring. Ported/generalised from `ddbmFF.R`'s position pie/treemap.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `position`, `points` (starter total), `share` (%).
#' @export
sl_position_scoring <- function(season) {
  season$pl_wk %>%
    dplyr::filter(is_starter, position %in% .sl_positions) %>%
    dplyr::group_by(position) %>%
    dplyr::summarise(points = sum(points), .groups = "drop") %>%
    dplyr::mutate(share = round(points / sum(points) * 100, 1),
                  position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(position)
}

#' Roster construction by team and position
#'
#' Player-weeks rostered ("spots"), total and average points per manager per
#' position. Ported from `ddbmFF.R`'s roster-spot heatmap.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `user_name`, `position`, `spots`, `points`, `avg`.
#' @export
sl_roster <- function(season) {
  season$pl_wk %>%
    dplyr::left_join(dplyr::select(season$user_map, roster_id, user_name), by = "roster_id") %>%
    dplyr::filter(position %in% .sl_positions) %>%
    dplyr::group_by(user_name, position) %>%
    dplyr::summarise(spots = dplyr::n(), points = sum(points),
                     avg = sum(points) / dplyr::n(), .groups = "drop") %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(user_name, position)
}

#' Average points, starters vs bench, per team and position
#'
#' Ported from `ddbmFF.R`'s starters-vs-bench roster-performance chart: are the
#' right players in the lineup?
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `user_name`, `position`, `status`, `avg`.
#' @export
sl_starter_bench <- function(season) {
  season$pl_wk %>%
    dplyr::left_join(dplyr::select(season$user_map, roster_id, user_name), by = "roster_id") %>%
    dplyr::filter(position %in% .sl_positions) %>%
    dplyr::mutate(status = ifelse(is_starter, "Starters", "Bench")) %>%
    dplyr::group_by(user_name, position, status) %>%
    dplyr::summarise(avg = mean(points), .groups = "drop") %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(user_name, position, status)
}
