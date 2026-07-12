# Manual / custom playoff engine -------------------------------------------
#
# Sleeper can only express its own bracket shape (fixed playoff_week_start,
# team count, and lineups locked to what the app had). When a league runs its
# playoff by hand -- a different week range, a custom bracket, and starters
# collected by the commissioner -- none of that fits.
#
# This engine takes a bracket config (rounds -> matchups -> each side's
# submitted starters) and prices every lineup under the league's own scoring
# chart (see scoring.R), so the ONLY input needed per elimination matchup is the
# rosters. Winners advance automatically via "W:<matchup_id>" references.

.sl_bye <- "BYE"

# Resolve starters given as player ids OR player names into player ids.
.sl_resolve_players <- function(x, pinfo = NULL) {
  x <- as.character(x)
  # Sleeper ids are numeric strings; team defenses are codes like "SEA".
  is_id <- grepl("^[0-9]+$", x) | grepl("^[A-Z]{2,3}$", x)
  if (all(is_id)) return(x)
  if (is.null(pinfo)) pinfo <- sl_players()
  out <- x
  for (i in which(!is_id)) {
    hit <- pinfo$player_id[match(tolower(x[i]), tolower(pinfo$player_name))]
    if (is.na(hit)) stop("Unknown player in lineup: '", x[i], "'", call. = FALSE)
    out[i] <- hit
  }
  out
}

#' Read a playoff bracket config
#'
#' @param path Path to a playoff JSON config (see `playoffs/` in the repo).
#' @return The parsed config as a list.
#' @export
sl_playoff_config <- function(path) {
  jsonlite::fromJSON(path, simplifyVector = FALSE)
}

#' Check a submitted lineup against the league's starting slots
#'
#' Manually collected lineups are the one thing nobody validates, so validate
#' them: counts each position against `roster_positions` and reports any slot
#' that is over- or under-filled (FLEX absorbs spare RB/WR/TE).
#'
#' @param player_ids The submitted starters.
#' @param roster_positions The league's `roster_positions` vector.
#' @param pinfo Optional player table (see [sl_players()]).
#' @return A character vector of problems; empty if the lineup is legal.
#' @export
sl_check_lineup <- function(player_ids, roster_positions, pinfo = NULL) {
  if (is.null(pinfo)) pinfo <- sl_players()
  slots <- sl_starter_slots(roster_positions)
  pos <- pinfo$position[match(as.character(player_ids), pinfo$player_id)]
  pos <- pos[!is.na(pos)]
  probs <- character(0)
  n_need <- sum(unlist(slots))
  if (length(player_ids) != n_need) {
    probs <- c(probs, sprintf("lineup has %d starters, league starts %d",
                              length(player_ids), n_need))
  }
  # Fixed slots first, then let the flex slots soak up the remainder.
  left <- table(factor(pos, levels = .sl_positions))
  for (p in .sl_positions) {
    need <- slots[[p]] %||% 0
    if (need > 0) {
      have <- min(left[[p]], need)
      if (have < need)
        probs <- c(probs, sprintf("%d %s short", need - have, p))
      left[[p]] <- left[[p]] - have
    }
  }
  flex <- (slots[["FLEX"]] %||% 0) + (slots[["WRRB_FLEX"]] %||% 0) +
    (slots[["REC_FLEX"]] %||% 0) + (slots[["SUPER_FLEX"]] %||% 0)
  spare <- sum(left)
  if (spare != flex)
    probs <- c(probs, sprintf("%d players for %d flex slot(s)", spare, flex))
  probs
}

# Score one side of a matchup: total points + the per-player breakdown.
.sl_score_side <- function(side, season, weeks, rules, pinfo, ctx) {
  starters <- .sl_resolve_players(side$starters, pinfo)
  det <- sl_score_lineup(starters, season, weeks, rules) %>%
    dplyr::left_join(dplyr::select(pinfo, player_id, player_name, position),
                     by = "player_id")
  det$team <- ctx$team
  det$matchup_id <- ctx$matchup_id
  det$round_id <- ctx$round_id
  list(points = round(sum(det$points), 2), n = length(starters), detail = det)
}

#' Run a manual / custom playoff bracket
#'
#' Resolves a bracket config round by round: each matchup's two sides are scored
#' from the starters submitted to the commissioner, priced under the league's own
#' scoring chart, and the winner advances into any `"W:<matchup_id>"` reference in
#' a later round. Byes pass a team through unscored.
#'
#' Because lineups are an input rather than read from Sleeper, this reproduces a
#' playoff Sleeper itself could not run (custom week range, custom bracket,
#' lineups the app had locked).
#'
#' @param config A parsed config (see [sl_playoff_config()]) or a path to one.
#' @param rules Optional scoring rules; defaults to the config's snapshotted
#'   `scoring_settings`, else fetched live from the league.
#' @param validate Check each submitted lineup against the league's starting
#'   slots and warn on problems.
#' @return A `sleeper_playoff` object: `$results` (one row per team per matchup),
#'   `$players` (per-player breakdown), `$champion`, `$config`.
#' @seealso [sl_scoring_chart()], [sl_plot_playoff_bracket()]
#' @export
sl_playoff <- function(config, rules = NULL, validate = TRUE) {
  if (is.character(config)) config <- sl_playoff_config(config)
  season <- as.character(config$season)
  lid <- config$league_id
  if (is.null(rules)) {
    rules <- if (!is.null(config$scoring_settings)) config$scoring_settings
             else sl_scoring_rules(lid)
  }
  pinfo <- sl_players()
  rposi <- if (!is.null(config$roster_positions)) unlist(config$roster_positions)
           else tryCatch(unlist(sleeper_api(paste0("/league/", lid))$roster_positions),
                         error = function(e) NULL)

  winners <- list(); losers <- list()
  res <- list(); det <- list()

  # Resolve a team or a W:/L: reference; NA if it is not decided yet.
  resolve_team <- function(nm) {
    nm <- as.character(nm)
    if (grepl("^W:", nm)) return(winners[[sub("^W:", "", nm)]] %||% NA_character_)
    if (grepl("^L:", nm)) return(losers[[sub("^L:", "", nm)]] %||% NA_character_)
    nm
  }

  for (rd in config$rounds) {
    weeks <- as.integer(unlist(rd$weeks))
    for (mu in rd$matchups) {
      mid <- mu$id
      if (!is.null(mu$bye)) {
        team <- resolve_team(mu$bye)
        if (!is.na(team)) winners[[mid]] <- team
        res[[length(res) + 1]] <- tibble(
          round_id = rd$id, round = rd$name, weeks = paste(weeks, collapse = "+"),
          matchup_id = mid, team = team, starters = NA_integer_, points = NA_real_,
          opponent = .sl_bye, opp_points = NA_real_,
          result = if (is.na(team)) "PENDING" else "BYE", margin = NA_real_)
        next
      }
      sides <- list(mu$home, mu$away)
      nms <- vapply(sides, function(s) resolve_team(s$team), character(1))
      nstart <- vapply(sides, function(s) length(s$starters %||% list()), integer(1))
      # A round only becomes playable once both teams are known AND both lineups
      # have been submitted -- otherwise it is simply not yet run.
      if (anyNA(nms) || any(nstart == 0)) {
        for (i in 1:2) {
          res[[length(res) + 1]] <- tibble(
            round_id = rd$id, round = rd$name, weeks = paste(weeks, collapse = "+"),
            matchup_id = mid,
            team = if (is.na(nms[i])) as.character(sides[[i]]$team) else nms[i],
            starters = nstart[i], points = NA_real_,
            opponent = if (is.na(nms[3 - i])) as.character(sides[[3 - i]]$team) else nms[3 - i],
            opp_points = NA_real_, result = "PENDING", margin = NA_real_)
        }
        next
      }
      scored <- lapply(seq_along(sides), function(i) {
        if (validate && !is.null(rposi)) {
          probs <- sl_check_lineup(.sl_resolve_players(sides[[i]]$starters, pinfo),
                                   rposi, pinfo)
          if (length(probs))
            warning("[", mid, "] ", nms[i], ": ", paste(probs, collapse = "; "),
                    call. = FALSE)
        }
        .sl_score_side(sides[[i]], season, weeks, rules, pinfo,
                       list(team = nms[i], matchup_id = mid, round_id = rd$id))
      })
      pts <- vapply(scored, function(s) s$points, numeric(1))
      wi <- if (pts[1] == pts[2]) NA_integer_ else which.max(pts)
      if (is.na(wi)) {
        warning("[", mid, "] tie at ", pts[1], " -- no winner advanced.", call. = FALSE)
      } else {
        winners[[mid]] <- nms[wi]; losers[[mid]] <- nms[3 - wi]
      }
      for (i in 1:2) {
        res[[length(res) + 1]] <- tibble(
          round_id = rd$id, round = rd$name, weeks = paste(weeks, collapse = "+"),
          matchup_id = mid, team = nms[i], starters = scored[[i]]$n,
          points = pts[i], opponent = nms[3 - i], opp_points = pts[3 - i],
          result = if (is.na(wi)) "T" else if (i == wi) "W" else "L",
          margin = round(pts[i] - pts[3 - i], 2))
        det[[length(det) + 1]] <- scored[[i]]$detail
      }
    }
  }

  results <- dplyr::bind_rows(res)
  players <- dplyr::bind_rows(det)
  # The championship must be named: a final round can also hold consolation and
  # placement games, so "last matchup" is not the title game.
  final_id <- config$final
  if (is.null(final_id)) {
    last <- config$rounds[[length(config$rounds)]]
    final_id <- last$matchups[[length(last$matchups)]]$id
  }
  champion <- winners[[final_id]]

  structure(list(results = results, players = players, champion = champion,
                 season = season, name = config$name %||% "Playoffs",
                 config = config),
            class = "sleeper_playoff")
}

#' @export
print.sleeper_playoff <- function(x, ...) {
  cat("<sleeper_playoff>", x$name, x$season, "| rounds:",
      dplyr::n_distinct(x$results$round_id), "| champion:",
      x$champion %||% "(undecided)", "\n")
  invisible(x)
}

#' Playoff standings (per-team run through the bracket)
#' @param playoff A `sleeper_playoff` object.
#' @return Tibble: `team`, `games`, `wins`, `losses`, `points`, `eliminated_in`.
#' @export
sl_playoff_summary <- function(playoff) {
  playoff$results %>%
    dplyr::group_by(team) %>%
    dplyr::summarise(
      games = sum(result %in% c("W", "L", "T")),
      wins = sum(result == "W"), losses = sum(result == "L"),
      points = round(sum(points, na.rm = TRUE), 2),
      eliminated_in = {
        l <- round[result == "L"]
        if (length(l)) l[length(l)] else NA_character_
      }, .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points))
}
