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

SL_AVATAR_CDN <- "https://sleepercdn.com/avatars"

#' CDN url for a Sleeper account avatar id
#'
#' Note the two avatar fields have different shapes and are easy to confuse: a
#' user's `avatar` is a bare id that has to be turned into a url, while a
#' league-specific `metadata.avatar` (the custom team picture) is already a full
#' url. This handles both, so either can be passed to it.
#'
#' @param avatar Avatar id, a full url, or `NA`.
#' @return Character url, or `NA` where there is no avatar. Vectorised.
#' @export
sl_avatar_url <- function(avatar) {
  a <- as.character(avatar)
  ifelse(is.na(a) | !nzchar(a), NA_character_,
         ifelse(grepl("^http", a), a, paste0(SL_AVATAR_CDN, "/", a)))
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
    ensure_cols(c("metadata_team_name", "metadata_avatar", "avatar")) %>%
    dplyr::transmute(
      user_id, user_name,
      team_name = dplyr::na_if(trimws(as.character(metadata_team_name)), ""),
      avatar_url      = sl_avatar_url(avatar),           # the account's picture
      team_avatar_url = sl_avatar_url(metadata_avatar),  # a custom team picture
      # What to actually show: a manager who named their team gets that name.
      team = dplyr::coalesce(team_name, user_name))
  rosters <- as_tibble(sleeper_api(paste0("/league/", lid, "/rosters")),
                       .name_repair = "unique") %>%
    dplyr::select(roster_id, owner_id)
  # Identity is kept OUT of user_map on purpose: user_map is joined into team_wk,
  # and every column added there would ride along into the metrics.
  user_map <- rosters %>%
    dplyr::left_join(users, by = c("owner_id" = "user_id")) %>%
    dplyr::transmute(roster_id, user_id = owner_id, user_name)
  accounts <- rosters %>%
    dplyr::left_join(users, by = c("owner_id" = "user_id")) %>%
    dplyr::transmute(roster_id, user_id = owner_id, user_name, team_name,
                     avatar_url, team_avatar_url, team)

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

  # SPLIT THE SEASON HERE -- mirrors python/sleepermetrics/season.py. Everything
  # downstream (standings, luck, efficiency, all-play, power rank) is a
  # REGULAR-season metric and must not count postseason weeks: where a league
  # runs its playoff outside Sleeper those weeks are phantom matchups nobody
  # played, and even where it doesn't, a playoff game is not a regular-season
  # result. Filtering once, identically, in both languages is what keeps every
  # derived metric in parity without either side special-casing anything.
  # team_wk_all / pl_wk_all keep every scored week for postseason features.
  pws <- as.integer(link$playoff_week_start %||% 0L)
  team_wk_all <- team_wk
  pl_wk_all <- pl_wk
  lw_all <- lw
  if (!is.na(pws) && pws > 0) {
    team_wk <- team_wk[team_wk$week < pws, , drop = FALSE]
    pl_wk <- pl_wk[pl_wk$week < pws, , drop = FALSE]
    # last_week must name a week that EXISTS in the scoped frames -- it is the
    # default for "the latest week" throughout, and leaving it at the last
    # scored leg indexes an empty frame once the postseason is split off.
    lw <- min(lw, pws - 1L)
  }

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
         transactions = transactions, accounts = accounts,
         status = link$status %||% NA_character_,
         playoff_week_start = if (!is.na(pws) && pws > 0) pws else NA_integer_,
         team_wk_all = team_wk_all, pl_wk_all = pl_wk_all,
         last_week_all = lw_all),
    class = "sleeper_season")
}

#' Every manager in the league's history
#'
#' Who they are *now*, and their record. Keyed on `user_id`, which persists
#' across seasons even as display names and team names change -- so a manager who
#' renamed themselves is one row, not two, and the name/icon shown is the one
#' from their most recent season.
#'
#' @param seasons Named list of `sleeper_season` objects ([sl_seasons()]).
#' @return Tibble: `user_id`, `user_name`, `team_name`, `team`, `avatar_url`,
#'   `team_avatar_url`, `seasons`, `first_season`, `last_season`, `titles`.
#' @export
sl_league_accounts <- function(seasons) {
  rows <- dplyr::bind_rows(lapply(seasons, function(s) {
    if (is.null(s$accounts) || !nrow(s$accounts)) return(NULL)
    champs <- s$standings$user_name[s$standings$champion]
    s$accounts %>%
      dplyr::mutate(season = s$season, title = .data$user_name %in% champs)
  }))
  if (!nrow(rows)) {
    return(tibble(user_id = character(), user_name = character(),
                  team_name = character(), team = character(),
                  avatar_url = character(), team_avatar_url = character(),
                  seasons = integer(), first_season = character(),
                  last_season = character(), titles = integer()))
  }
  rows %>%
    dplyr::filter(!is.na(.data$user_id)) %>%
    dplyr::group_by(.data$user_id) %>%
    dplyr::summarise(
      # dplyr::last() = most recent season in the chain = the current identity.
      user_name = dplyr::last(.data$user_name),
      team_name = dplyr::last(.data$team_name),
      team = dplyr::last(.data$team),
      avatar_url = dplyr::last(.data$avatar_url),
      team_avatar_url = dplyr::last(.data$team_avatar_url),
      seasons = dplyr::n_distinct(.data$season),
      first_season = min(.data$season), last_season = max(.data$season),
      titles = sum(.data$title), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(.data$titles), dplyr::desc(.data$seasons),
                   .data$user_name)
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
