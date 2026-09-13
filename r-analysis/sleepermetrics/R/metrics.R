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

#' Regular-season all-play standings
#'
#' What the standings would be if every team played every other team every week.
#' All-play win% is schedule-independent, so comparing all-play rank with the
#' actual finish shows who the schedule flattered and who it robbed.
#'
#' `rank_delta = allplay_rank - final_position`: positive means the real standing
#' is better than all-play merit (a friendly schedule / good timing), negative
#' means the team was better than its record.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `user_name`, `allplay_w`, `allplay_l`, `allplay_pct`,
#'   `final_position`, `allplay_rank`, `rank_delta`.
#' @export
sl_allplay <- function(season) {
  season$standings %>%
    dplyr::transmute(user_name, allplay_w, allplay_l,
                     allplay_pct = allplay_w / pmax(allplay_w + allplay_l, 1),
                     final_position) %>%
    dplyr::arrange(dplyr::desc(allplay_pct), dplyr::desc(allplay_w)) %>%
    dplyr::mutate(allplay_rank = dplyr::row_number(),
                  rank_delta = allplay_rank - final_position)
}

#' Power ranking (composite)
#'
#' A transparent blend of four z-scored components: points for (scoring power),
#' all-play win% (schedule-independent quality), recent form (mean points over
#' the last `recent` weeks), and lineup efficiency (coaching). Each is
#' standardised across the league then weighted, so the number answers "how
#' strong is this team, all things considered" rather than just "what is its
#' record". Weights are explicit and tunable.
#'
#' The composite is deliberately left unrounded (z-scores are mean/sd derived);
#' round only when displaying, per the project's parity discipline.
#'
#' @param season A [sleeper_season] object.
#' @param weights Named numeric with `points`, `allplay`, `form`, `eff`.
#' @param recent Number of most recent weeks that count as "form".
#' @return Tibble: `user_name`, `points`, `allplay_pct`, `form`, `eff`, `power`,
#'   `power_rank`.
#' @export
sl_power_rank <- function(season,
                          weights = c(points = 0.35, allplay = 0.30,
                                      form = 0.20, eff = 0.15),
                          recent = 3) {
  # z across the league; a league where everyone is equal (sd 0) contributes 0.
  z <- function(x) {
    s <- stats::sd(x)
    if (is.na(s) || s == 0) rep(0, length(x)) else (x - mean(x)) / s
  }
  maxwk <- max(season$team_wk$week)
  form <- season$team_wk %>%
    dplyr::filter(week > maxwk - recent) %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(form = mean(points), .groups = "drop")
  eff <- sl_efficiency(season) %>% dplyr::select(user_name, eff)
  season$standings %>%
    dplyr::transmute(user_name, points,
                     allplay_pct = allplay_w / pmax(allplay_w + allplay_l, 1)) %>%
    dplyr::left_join(form, by = "user_name") %>%
    dplyr::left_join(eff, by = "user_name") %>%
    dplyr::mutate(power = weights[["points"]]  * z(points) +
                          weights[["allplay"]] * z(allplay_pct) +
                          weights[["form"]]    * z(form) +
                          weights[["eff"]]     * z(eff)) %>%
    dplyr::arrange(dplyr::desc(power)) %>%
    dplyr::mutate(power_rank = dplyr::row_number())
}

#' Manager tendencies
#'
#' A behavioural profile from the season's transactions and lineups: roster churn
#' (waiver / free-agent adds), trade activity, drops, and how well each manager
#' actually set their lineup (mean weekly start/sit efficiency). Answers "what
#' kind of manager is this" rather than "how good is the team".
#'
#' `lineup_iq` is mean-derived, so it is returned unrounded; round on display.
#'
#' @param season A [sleeper_season] object.
#' @return Tibble: `user_name`, `moves` (waiver+FA adds), `trades` (players
#'   acquired via trade), `drops`, `moves_per_wk`, `lineup_iq`.
#' @export
sl_manager_profile <- function(season) {
  tx <- season$transactions
  weeks <- max(season$team_wk$week)
  managers <- season$standings %>% dplyr::distinct(user_name)

  tally <- function(pred) {
    if (!nrow(tx)) return(tibble(user_name = character(), n = integer()))
    dplyr::count(dplyr::filter(tx, pred & status != "failed"), user_name, name = "n")
  }
  moves  <- dplyr::rename(tally(tx$type %in% c("waiver", "free_agent") &
                                  tx$transaction == "add"), moves = n)
  trades <- dplyr::rename(tally(tx$type == "trade" & tx$transaction == "add"),
                          trades = n)
  drops  <- dplyr::rename(tally(tx$transaction == "drop"), drops = n)
  iq <- season$lineup %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(lineup_iq = mean(actual / pmax(optimal, 1e-9)) * 100,
                     .groups = "drop")

  managers %>%
    dplyr::left_join(moves, by = "user_name") %>%
    dplyr::left_join(trades, by = "user_name") %>%
    dplyr::left_join(drops, by = "user_name") %>%
    dplyr::left_join(iq, by = "user_name") %>%
    dplyr::mutate(dplyr::across(c(moves, trades, drops),
                                ~ tidyr::replace_na(.x, 0L)),
                  moves_per_wk = moves / weeks) %>%
    dplyr::arrange(dplyr::desc(moves), dplyr::desc(lineup_iq))
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
