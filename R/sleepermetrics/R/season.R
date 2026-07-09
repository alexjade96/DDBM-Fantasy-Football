# Assemble one season into a tidy object ----------------------------------

# Optimal-lineup points for one team-week given starter-slot counts. Greedy
# fill: fixed positions first, then flex slots by increasing eligibility.
sl_optimal_points <- function(d, slots) {
  d <- d %>% dplyr::filter(!is.na(position)) %>% dplyr::arrange(dplyr::desc(points))
  used <- character(0)
  take <- function(elig, n) {
    n <- n %||% 0
    if (n <= 0) return(0)
    a <- d %>% dplyr::filter(position %in% elig, !player_id %in% used) %>%
      dplyr::slice_head(n = n)
    used <<- c(used, a$player_id)
    sum(a$points)
  }
  tot <- 0
  for (p in .sl_positions) tot <- tot + take(p, slots[[p]])
  tot <- tot + take(c("WR", "TE"),            slots[["REC_FLEX"]])
  tot <- tot + take(c("RB", "WR", "TE"),       slots[["FLEX"]])
  tot <- tot + take(c("RB", "WR", "TE"),       slots[["WRRB_FLEX"]])
  tot <- tot + take(c("QB", "RB", "WR", "TE"), slots[["SUPER_FLEX"]])
  tot
}

# Core assembler used by sl_season(); takes a chain link.
sl_assemble_season <- function(link) {
  lid <- link$league_id
  lw <- max(link$last_scored_leg, 1L)
  slots <- sl_starter_slots(link$roster_positions)
  pinfo <- sl_players()

  users <- as_tibble(sleeper_api(paste0("/league/", lid, "/users")),
                     .name_repair = "unique") %>%
    unnest(metadata, names_sep = "_") %>%
    dplyr::rename(user_name = display_name) %>%
    ensure_cols("metadata_team_name") %>%
    dplyr::transmute(user_id, user_name, team_name = metadata_team_name)
  user_map <- as_tibble(sleeper_api(paste0("/league/", lid, "/rosters")),
                        .name_repair = "unique") %>%
    dplyr::select(roster_id, owner_id) %>%
    dplyr::left_join(users, by = c("owner_id" = "user_id")) %>%
    dplyr::transmute(roster_id, user_id = owner_id, user_name)

  raw <- map(seq_len(lw), function(i) {
    m <- as_tibble(sleeper_api(paste0("/league/", lid, "/matchups/", i)))
    m$week <- i
    m
  })

  base <- map_dfr(raw, ~ .x %>% dplyr::select(week, roster_id, matchup_id, points))
  team_wk <- base %>%
    dplyr::left_join(
      base %>% dplyr::select(week, matchup_id, opp = roster_id, pa = points),
      by = c("week", "matchup_id"), na_matches = "never",
      relationship = "many-to-many") %>%
    dplyr::filter(is.na(opp) | roster_id != opp) %>%
    dplyr::mutate(result = dplyr::case_when(
      points > pa ~ "W", points < pa ~ "L", points == pa ~ "T",
      TRUE ~ NA_character_)) %>%
    dplyr::group_by(week) %>%
    dplyr::mutate(allplay_w = map_dbl(points, ~ sum(.x > points)),
                  allplay_l = map_dbl(points, ~ sum(.x < points)),
                  is_high = points == max(points)) %>%
    dplyr::ungroup() %>%
    dplyr::left_join(user_map, by = "roster_id")

  pl_wk <- map_dfr(raw, function(m) {
    pp <- m$players_points  # data frame: cols = player_ids, rows = rosters
    map_dfr(seq_len(nrow(m)), function(i) {
      ids <- unlist(m$players[[i]]); st <- unlist(m$starters[[i]])
      pts <- vapply(ids, function(id) {
        v <- if (!is.null(pp) && id %in% names(pp)) pp[[id]][i] else NA_real_
        if (length(v) == 0 || is.na(v)) 0 else as.numeric(v)
      }, numeric(1))
      tibble(week = m$week[i], roster_id = m$roster_id[i], player_id = ids,
             points = pts, is_starter = ids %in% st)
    })
  }) %>% dplyr::left_join(pinfo %>% dplyr::select(player_id, player_name, position),
                          by = "player_id")

  tx_raw <- map_dfr(seq_len(lw), function(i) {
    t <- sleeper_api(paste0("/league/", lid, "/transactions/", i))
    t <- as_tibble(t)
    if (nrow(t) == 0) return(tibble())
    t$week <- i
    t
  })
  transactions <- sl_unnest_transactions(tx_raw, user_map, pinfo)

  lineup <- pl_wk %>% dplyr::left_join(user_map, by = "roster_id") %>%
    dplyr::group_by(user_name, week) %>%
    dplyr::summarise(actual = sum(points[is_starter]),
                     optimal = sl_optimal_points(dplyr::pick(dplyr::everything()), slots),
                     .groups = "drop") %>%
    dplyr::mutate(left_on_bench = pmax(optimal - actual, 0))

  standings <- team_wk %>%
    dplyr::group_by(roster_id, user_id, user_name) %>%
    dplyr::summarise(wins = sum(result == "W", na.rm = TRUE),
                     losses = sum(result == "L", na.rm = TRUE),
                     points = sum(points), pa = sum(pa, na.rm = TRUE),
                     allplay_w = sum(allplay_w), allplay_l = sum(allplay_l),
                     highs = sum(is_high), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points)) %>%
    dplyr::mutate(final_position = dplyr::row_number())

  champ <- tryCatch({
    wb <- as_tibble(sleeper_api(paste0("/league/", lid, "/winners_bracket")))
    if ("p" %in% names(wb)) {
      f <- wb %>% dplyr::filter(p == 1)
      if (nrow(f)) as.integer(f$w[[1]]) else NA_integer_
    } else NA_integer_
  }, error = function(e) NA_integer_)
  standings <- standings %>%
    dplyr::mutate(champion = !is.na(champ) & roster_id == champ,
                  season = link$season)

  structure(
    list(season = link$season, name = link$name, league_id = lid,
         last_week = lw, slots = slots, team_wk = team_wk, pl_wk = pl_wk,
         lineup = lineup, standings = standings, user_map = user_map,
         transactions = transactions),
    class = "sleeper_season")
}

# Empty transactions frame with the canonical column set.
.sl_empty_transactions <- function() {
  tibble(week = integer(), transaction_id = character(), type = character(),
         transaction = character(), player_id = character(),
         roster_id = integer(), user_name = character(),
         player_name = character(), position = character(), status = character())
}

# Unnest a raw weekly-transactions frame (list-columns `adds`/`drops`, each a
# named list player_id -> roster_id) into one row per player movement. Mirrors
# the Python season._unnest_transactions build.
sl_unnest_transactions <- function(tx_raw, user_map, pinfo) {
  if (!nrow(tx_raw) || !all(c("adds", "drops") %in% names(tx_raw))) {
    return(.sl_empty_transactions())
  }
  tx_raw %>%
    ensure_cols(c("transaction_id", "type", "status")) %>%
    dplyr::select(week, transaction_id, type, status, adds, drops) %>%
    tidyr::pivot_longer(c(adds, drops), names_to = "transaction",
                        values_to = "pd") %>%
    dplyr::mutate(transaction = dplyr::recode(transaction, adds = "add", drops = "drop")) %>%
    dplyr::rowwise() %>%
    dplyr::mutate(pd = list(
      if (is.null(pd) || length(pd) == 0) {
        tibble(player_id = character(), roster_id = integer())
      } else {
        tibble(player_id = names(pd), roster_id = as.integer(unlist(pd)))
      })) %>%
    dplyr::ungroup() %>%
    tidyr::unnest(pd) %>%
    dplyr::filter(!is.na(player_id), !is.na(roster_id)) %>%
    dplyr::left_join(dplyr::select(user_map, roster_id, user_name), by = "roster_id") %>%
    dplyr::left_join(dplyr::select(pinfo, player_id, player_name, position),
                     by = "player_id") %>%
    dplyr::transmute(week, transaction_id = as.character(transaction_id),
                     type, transaction, player_id, roster_id, user_name,
                     player_name, position, status) %>%
    dplyr::arrange(week, transaction_id, transaction, roster_id)
}

#' Assemble one season of a league
#'
#' Fetches and reshapes a single season into a `sleeper_season` object holding
#' the frames every metric builds on: `team_wk` (one row per team-week with
#' points, opponent points, result, all-play tallies), `pl_wk` (player-week
#' points + starter flag + position), `lineup` (actual vs optimal each week)
#' and `standings`.
#'
#' Playoff teams with `matchup_id = NA` (eliminated/bye) are handled correctly:
#' the self-join uses `na_matches = "never"`, so they are not paired against
#' each other and receive no phantom win/loss.
#'
#' @param league_id Head-of-chain league id.
#' @param season Optional season string (e.g. `"2024"`); default = most recent.
#' @return A `sleeper_season` object.
#' @seealso [sl_standings()], [sl_luck()], [sl_summary_season()]
#' @export
sl_season <- function(league_id, season = NULL) {
  chain <- sl_league_chain(league_id)
  link <- if (is.null(season)) chain[[length(chain)]] else chain[[as.character(season)]]
  if (is.null(link)) stop("Season not found in league chain: ", season)
  sl_assemble_season(link)
}

#' @export
print.sleeper_season <- function(x, ...) {
  cat("<sleeper_season>", x$name, x$season,
      "| teams:", nrow(x$standings), "| weeks 1:", x$last_week, "\n")
  invisible(x)
}
