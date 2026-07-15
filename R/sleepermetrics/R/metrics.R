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

#' Weekly table-position trajectory
#'
#' Rebuilds the league table after each week from cumulative record then points,
#' giving every manager's standing position week by week. Ported/generalised
#' from `ddbmFF.R`'s table-position line graph. Cumulative wins use
#' `coalesce(result == "W", FALSE)` so bye/eliminated weeks (no opponent) never
#' poison the running record.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `week`, `user_name`, `wins`, `losses`, `points` (all
#'   cumulative through that week) and `table_position`.
#' @export
sl_table_position <- function(season) {
  season$team_wk %>%
    dplyr::arrange(user_name, week) %>%
    dplyr::group_by(user_name) %>%
    dplyr::mutate(wins = cumsum(dplyr::coalesce(result == "W", FALSE)),
                  losses = cumsum(dplyr::coalesce(result == "L", FALSE)),
                  points = cumsum(points)) %>%
    dplyr::ungroup() %>%
    dplyr::group_by(week) %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points), user_name, .by_group = TRUE) %>%
    dplyr::mutate(table_position = dplyr::row_number()) %>%
    dplyr::ungroup() %>%
    dplyr::transmute(week, user_name, wins, losses, points, table_position) %>%
    dplyr::arrange(week, table_position)
}

#' Average roster composition (slots used per position, starters vs bench)
#'
#' Mean number of roster spots each team devotes to a position per week, split
#' by starter/bench. Ported from `ddbmFF.R`'s roster-count breakdown.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `position`, `status`, `avg_count` (slots per team per week).
#' @export
sl_roster_counts <- function(season) {
  denom <- nrow(season$standings) * season$last_week
  season$pl_wk %>%
    dplyr::filter(position %in% .sl_positions) %>%
    dplyr::mutate(status = ifelse(is_starter, "Starters", "Bench")) %>%
    dplyr::group_by(position, status) %>%
    dplyr::summarise(avg_count = dplyr::n() / denom, .groups = "drop") %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(position, status)
}

# --- Transaction analytics (ported from ddbmFF.R) -------------------------

#' League transactions (adds/drops, one row per player movement)
#'
#' The season's `transactions` frame, already unnested to one row per player
#' add/drop. Ported from `ddbmFF.R`'s `allTransactionsDF`.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `week`, `transaction_id`, `type`, `transaction` (add/drop),
#'   `player_id`, `roster_id`, `user_name`, `player_name`, `position`, `status`.
#' @export
sl_transactions <- function(season) season$transactions

# Points a set of players scored while rostered by each manager, from pl_wk
# (roster membership week by week) rather than reconstructing transaction
# stints -- pl_wk already knows exactly which weeks a player was on a roster.
# `by` selects the join grain: player_id alone (trades -> every team that held
# the player) or player_id+roster_id (waivers -> only the acquiring team).
.sl_rostered_perf <- function(season, keep, by) {
  season$pl_wk %>%
    dplyr::semi_join(keep, by = by) %>%
    dplyr::left_join(dplyr::select(season$user_map, roster_id, user_name), by = "roster_id") %>%
    dplyr::filter(position %in% .sl_positions, !is.na(player_name)) %>%
    # player_id rides along: it is the only safe key for a portrait (names are
    # neither unique nor stable).
    dplyr::group_by(player_id, player_name, position, user_name) %>%
    dplyr::summarise(weeks = dplyr::n_distinct(week), points = sum(points),
                     avg = sum(points) / dplyr::n_distinct(week), .groups = "drop") %>%
    dplyr::group_by(player_name) %>%
    dplyr::mutate(total = sum(points)) %>%
    dplyr::ungroup()
}

#' Traded-player performance while rostered
#'
#' For every player who changed hands in a trade, the points they scored on each
#' team that rostered them (kept to players who actually moved between managers).
#' Ported/improved from `ddbmFF.R`'s trade-performance chart -- membership comes
#' from `pl_wk`, so "while rostered" needs no stint reconstruction, and both
#' sides of the trade are captured by matching the player across every roster.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `player_name`, `position`, `user_name`, `weeks`, `points`,
#'   `avg`, `total` (player's points across all teams).
#' @export
sl_trade_performance <- function(season) {
  keep <- season$transactions %>%
    dplyr::filter(type == "trade", transaction == "add", status != "failed") %>%
    dplyr::distinct(player_id)
  .sl_rostered_perf(season, keep, by = "player_id") %>%
    dplyr::group_by(player_name) %>%
    dplyr::filter(dplyr::n_distinct(user_name) > 1) %>%
    dplyr::ungroup() %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(dplyr::desc(total), player_name, user_name)
}

#' Waiver / free-agent pickup performance
#'
#' Points scored by players a manager acquired off waivers or free agency, while
#' they were on that manager's roster. Ported/improved from `ddbmFF.R`'s waiver
#' performance chart.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `player_name`, `position`, `user_name`, `weeks`, `points`,
#'   `avg`, `total`.
#' @export
sl_waiver_performance <- function(season) {
  keep <- season$transactions %>%
    dplyr::filter(type %in% c("waiver", "free_agent"), transaction == "add",
                  status != "failed") %>%
    dplyr::distinct(player_id, roster_id)
  .sl_rostered_perf(season, keep, by = c("player_id", "roster_id")) %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(dplyr::desc(total), player_name, user_name)
}
