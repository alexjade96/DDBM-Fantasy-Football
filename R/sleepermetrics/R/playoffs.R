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
#' @param path Path to a playoff JSON config (see `season/<league_id>/` in the repo).
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

# Split a bracket into the championship path and everything else.
#
# Sleeper's winners_bracket stores 3rd-place and placement games alongside the
# real thing, so counting every game as a "playoff win" inflates records. A game
# belongs to the title path only if BOTH teams are still alive going into it;
# once you lose a title-path game you are out, and anything you play afterwards
# is consolation. Rounds are walked in order and eliminations are applied at the
# END of a round, so games within a round cannot affect each other.
.sl_tag_bracket <- function(results, round_order) {
  results$bracket <- NA_character_
  elim <- character(0)
  for (rid in round_order) {
    fresh <- character(0)
    for (m in unique(results$matchup_id[results$round_id == rid])) {
      i <- which(results$matchup_id == m)
      tms <- as.character(stats::na.omit(results$team[i]))
      title <- !any(tms %in% elim)
      results$bracket[i] <- if (title) "title" else "consolation"
      if (title) {
        lost <- results$team[i][results$result[i] == "L"]
        fresh <- c(fresh, as.character(stats::na.omit(lost)))
      }
    }
    elim <- c(elim, fresh)
  }
  results
}

#' Scope a playoff frame to part of the bracket
#'
#' `"title"` (default) keeps only the championship path; `"consolation"` keeps
#' the placement games a team plays after being knocked out; `"all"` keeps both.
#'
#' @param d A frame with a `bracket` column.
#' @param scope One of `"title"`, `"all"`, `"consolation"`.
#' @return The filtered frame.
#' @export
sl_scope <- function(d, scope = c("title", "all", "consolation")) {
  scope <- match.arg(scope)
  if (scope == "all") d else dplyr::filter(d, bracket == scope)
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

  results <- .sl_tag_bracket(dplyr::bind_rows(res),
                             vapply(config$rounds, function(r) r$id, character(1)))
  players <- dplyr::bind_rows(det)
  if (nrow(players)) {
    players <- players %>%
      dplyr::left_join(dplyr::distinct(results, matchup_id, bracket), by = "matchup_id")
  }
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

#' Stored season brackets
#'
#' Configs live one level down, under `<playoff_dir>/<league_id>/<season>.json`
#' -- Sleeper gives each season its own league id (see `league_ids` below), so a
#' bracket is keyed by BOTH, not by season number alone. Only numeric-named
#' subfolders are treated as league folders (a Sleeper league_id is always a
#' numeric string); `<playoff_dir>/adp/` and `<playoff_dir>/fixtures/` are
#' siblings holding unrelated data (the Python ADP cache, a manually-referenced
#' ground-truth bracket) and are skipped by that same rule.
#'
#' `league_ids` restricts the result to brackets belonging to those leagues. A
#' bracket is keyed by season, but a season number is not unique across leagues
#' -- without this filter, loading some *other* league into the dashboard would
#' silently hand it DDBM's brackets and DDBM's champions. Sleeper gives each
#' season its own league id, so pass the whole chain.
#'
#' @param playoff_dir Root directory of bracket configs (default `"season"`).
#' @param league_ids Optional character vector of league ids to keep.
#' @return Named character vector: `season -> config path`.
#' @export
sl_playoff_configs <- function(playoff_dir = "season", league_ids = NULL) {
  subs <- list.dirs(playoff_dir, full.names = FALSE, recursive = FALSE)
  subs <- subs[grepl("^[0-9]+$", subs)]
  fs <- unlist(lapply(subs, function(sub) {
    list.files(file.path(playoff_dir, sub), "\\.json$", full.names = TRUE)
  }))
  ids <- if (is.null(league_ids)) NULL else as.character(league_ids)
  out <- character(0)
  for (f in fs) {
    cfg <- tryCatch(sl_playoff_config(f), error = function(e) NULL)
    if (is.null(cfg) || is.null(cfg$rounds) || is.null(cfg$season)) next
    if (!is.null(ids) && !(as.character(cfg$league_id %||% "") %in% ids)) next
    out[[as.character(cfg$season)]] <- f
  }
  out
}

#' The champion a bracket produces
#'
#' Configs persist the engine-derived `champion` so a season load stays cheap;
#' pass `recompute = TRUE` to re-run the bracket from the stored lineups rather
#' than trust the stored value (`verify.py` does exactly this).
#'
#' @param config A config, or a path to one.
#' @param recompute Re-run the bracket instead of reading the stored champion.
#' @return The champion's manager name, or `NULL`.
#' @export
sl_playoff_champion <- function(config, recompute = FALSE) {
  if (is.character(config)) config <- sl_playoff_config(config)
  if (!recompute && !is.null(config$champion)) return(config$champion)
  sl_playoff(config, validate = FALSE)$champion
}

#' Let each season's playoff bracket decide that season's champion
#'
#' Sleeper's `winners_bracket` is the default source of the champion flag, but it
#' is only right for playoffs Sleeper actually ran -- for DDBM 2025 it is
#' demonstrably incoherent. Where a bracket config exists it is authoritative,
#' and the corrected flag flows straight into career titles.
#'
#' @param seasons A list of [sleeper_season] objects.
#' @param playoff_dir Directory of bracket configs.
#' @param recompute Re-run each bracket rather than reading its stored champion.
#' @return The seasons, with `standings$champion` corrected where a bracket exists.
#' @export
sl_apply_playoffs <- function(seasons, playoff_dir = "season", recompute = FALSE) {
  # Only this league's brackets: pointing the dashboard at another league must
  # not stamp this league's champions onto it.
  paths <- sl_playoff_configs(
    playoff_dir, league_ids = vapply(seasons, function(s) s$league_id, character(1)))
  for (k in names(seasons)) {
    s <- seasons[[k]]
    # Note `[[` on a plain character vector ERRORS on a missing name rather than
    # returning NULL, so check membership -- a league with no stored brackets at
    # all is entirely normal and must not blow up the season load.
    key <- as.character(s$season)
    if (!key %in% names(paths)) next
    p <- paths[[key]]
    champ <- sl_playoff_champion(p, recompute = recompute)
    if (!is.null(champ)) {
      seasons[[k]]$standings$champion <- seasons[[k]]$standings$user_name == champ
    }
  }
  seasons
}

#' Score every stored bracket
#' @param playoff_dir Directory of bracket configs.
#' @param league_ids Optional league-id chain; load only that league's brackets
#'   (see [sl_playoff_configs()]).
#' @return Named list of `sleeper_playoff` objects (names = seasons).
#' @export
sl_load_playoffs <- function(playoff_dir = "season", league_ids = NULL) {
  paths <- sl_playoff_configs(playoff_dir, league_ids)
  stats::setNames(lapply(paths, function(p) sl_playoff(p, validate = FALSE)),
                  names(paths))
}

#' Career playoff record per manager
#'
#' Regular-season metrics say nothing about January. This is the postseason
#' resume: how often you got there, how you did once you did, and how deep.
#'
#' @param playoffs A named list of `sleeper_playoff` objects (see
#'   [sl_load_playoffs()]).
#' @param scope See [sl_scope()]. Defaults to `"title"`, so 3rd-place and
#'   placement games do not get counted as playoff wins.
#' @return Tibble: `user_name`, `appearances`, `games`, `wins`, `losses`,
#'   `points`, `titles`, `finals`, `win_pct`, `ppg`.
#' @export
sl_playoff_stats <- function(playoffs, scope = "title") {
  rows <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    p <- playoffs[[s]]
    final_id <- p$config$final
    played <- sl_scope(p$results, scope) %>%
      dplyr::filter(result %in% c("W", "L", "T"))
    p$results %>% dplyr::group_by(team) %>%
      dplyr::summarise(in_final = if (is.null(final_id)) FALSE
                                  else any(matchup_id == final_id), .groups = "drop") %>%
      dplyr::left_join(
        played %>% dplyr::group_by(team) %>%
          dplyr::summarise(games = dplyr::n(), wins = sum(result == "W"),
                           losses = sum(result == "L"),
                           points = sum(points, na.rm = TRUE), .groups = "drop"),
        by = "team") %>%
      dplyr::mutate(season = s, title = team == (p$champion %||% ""),
                    games = dplyr::coalesce(games, 0L),
                    wins = dplyr::coalesce(wins, 0L),
                    losses = dplyr::coalesce(losses, 0L),
                    points = dplyr::coalesce(points, 0))
  }))
  if (!nrow(rows)) return(rows)
  rows %>%
    dplyr::group_by(user_name = team) %>%
    dplyr::summarise(appearances = dplyr::n_distinct(season), games = sum(games),
                     wins = sum(wins), losses = sum(losses),
                     points = sum(points), titles = sum(title),
                     finals = sum(in_final), .groups = "drop") %>%
    dplyr::mutate(win_pct = wins / pmax(games, 1) * 100,
                  ppg = points / pmax(games, 1)) %>%
    dplyr::arrange(dplyr::desc(titles), dplyr::desc(win_pct), dplyr::desc(ppg))
}

# --- Playoff analytics ----------------------------------------------------

#' Every playoff player-week, across all stored brackets
#'
#' The raw grain the player metrics are built from: one row per started player
#' per week, tagged with season, round and `bracket` (title / consolation).
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `season`, `round`, `bracket`, `matchup_id`, `team`,
#'   `player_name`, `position`, `week`, `points`.
#' @export
sl_playoff_performances <- function(playoffs, scope = "title") {
  d <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    p <- playoffs[[s]]
    if (!nrow(p$players)) return(NULL)
    p$players %>%
      dplyr::left_join(dplyr::distinct(p$results, matchup_id, round), by = "matchup_id") %>%
      dplyr::mutate(season = s, champion = team == (p$champion %||% ""))
  }))
  if (!nrow(d)) return(d)
  # player_id rides along: it is the only safe key for a portrait (names are
  # neither unique nor stable).
  sl_scope(d, scope) %>%
    dplyr::select(season, round, bracket, matchup_id, team, player_id, player_name,
                  position, week, points, champion) %>%
    dplyr::arrange(dplyr::desc(points))
}

#' Career playoff scoring leaders (players)
#'
#' Who actually produces in January. Aggregates every started player-week across
#' all stored brackets.
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `player_name`, `position`, `seasons`, `games`, `points`,
#'   `ppg`, `best`, `rings` (games played on a roster that won the title).
#' @export
sl_playoff_players <- function(playoffs, scope = "title") {
  d <- sl_playoff_performances(playoffs, scope)
  if (!nrow(d)) return(d)
  d %>%
    dplyr::group_by(player_id, player_name, position) %>%
    # NOTE: dplyr evaluates summarise() expressions in order, so `best` and `ppg`
    # must be computed BEFORE `points` is redefined -- otherwise they read the
    # summed column and `best` silently becomes the season total.
    dplyr::summarise(seasons = dplyr::n_distinct(season), games = dplyr::n(),
                     best = max(points),
                     ppg = sum(points) / dplyr::n(),
                     points = sum(points),
                     # rings = SEASONS won while on the title roster, not champion
                     # player-weeks (weeks gave players more rings than seasons).
                     rings = dplyr::n_distinct(season[champion]),
                     .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(points))
}

#' The playoff All-Star team
#'
#' Top career playoff scorer at each position.
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble, one row per position.
#' @export
sl_playoff_all_stars <- function(playoffs, scope = "title") {
  d <- sl_playoff_players(playoffs, scope)
  if (!nrow(d)) return(d)
  d %>% dplyr::filter(position %in% .sl_positions) %>%
    dplyr::group_by(position) %>%
    dplyr::slice_max(points, n = 1, with_ties = FALSE) %>%
    dplyr::ungroup() %>%
    dplyr::mutate(position = factor(position, levels = .sl_positions)) %>%
    dplyr::arrange(position)
}

#' Best single playoff performances
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param n How many to return.
#' @param scope See [sl_scope()].
#' @return Tibble of the biggest individual player-weeks.
#' @export
sl_playoff_best_games <- function(playoffs, n = 15, scope = "title") {
  d <- sl_playoff_performances(playoffs, scope)
  if (!nrow(d)) return(d)
  d %>% dplyr::slice_max(points, n = n, with_ties = FALSE)
}

#' Worst playoff performances by a started player
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param n How many to return.
#' @param scope See [sl_scope()].
#' @return Tibble of the biggest playoff busts (started, and did nothing).
#' @export
sl_playoff_busts <- function(playoffs, n = 15, scope = "title") {
  d <- sl_playoff_performances(playoffs, scope)
  if (!nrow(d)) return(d)
  d %>% dplyr::slice_min(points, n = n, with_ties = FALSE)
}

#' Title-game performers
#'
#' Who shows up when the trophy is on the line: every player-week in a final.
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @return Tibble of finals performances, best first.
#' @export
sl_playoff_finals <- function(playoffs) {
  d <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    p <- playoffs[[s]]
    fid <- p$config$final
    if (is.null(fid) || !nrow(p$players)) return(NULL)
    p$players %>% dplyr::filter(matchup_id == fid) %>%
      dplyr::mutate(season = s, won = team == (p$champion %||% ""))
  }))
  if (!nrow(d)) return(d)
  d %>% dplyr::select(season, team, won, player_name, position, week, points) %>%
    dplyr::arrange(dplyr::desc(points))
}

#' Carry factor: how much of a playoff run one player accounted for
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `season`, `team`, `points`, `top_player`, `top_points`,
#'   `share` (% of the team's playoff points from its best player).
#' @export
sl_playoff_carry <- function(playoffs, scope = "title") {
  d <- sl_playoff_performances(playoffs, scope)
  if (!nrow(d)) return(d)
  by_player <- d %>% dplyr::group_by(season, team, player_name) %>%
    dplyr::summarise(pp = sum(points), .groups = "drop")
  tot <- by_player %>% dplyr::group_by(season, team) %>%
    dplyr::summarise(points = sum(pp), .groups = "drop")
  by_player %>% dplyr::group_by(season, team) %>%
    dplyr::slice_max(pp, n = 1, with_ties = FALSE) %>% dplyr::ungroup() %>%
    dplyr::left_join(tot, by = c("season", "team")) %>%
    dplyr::transmute(season, team, points = points,
                     top_player = player_name, top_points = pp,
                     share = pp / points * 100) %>%
    dplyr::arrange(dplyr::desc(share))
}

#' Clutch index: playoff scoring vs regular-season scoring
#'
#' Regular-season averages say nothing about January. Positive = raises their
#' game when it matters.
#'
#' @param seasons Named list of [sleeper_season] objects.
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `user_name`, `reg_ppg`, `po_ppg`, `clutch`, `games`.
#' @export
sl_clutch <- function(seasons, playoffs, scope = "title") {
  po <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    r <- sl_scope(playoffs[[s]]$results, scope)
    r %>% dplyr::filter(result %in% c("W", "L", "T")) %>% dplyr::mutate(season = s)
  }))
  if (!nrow(po)) return(po)
  reg <- dplyr::bind_rows(lapply(seasons, function(s) s$team_wk)) %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(reg_ppg = mean(points), .groups = "drop")
  po %>% dplyr::group_by(user_name = team) %>%
    dplyr::summarise(games = dplyr::n(), po_ppg = mean(points),
                     .groups = "drop") %>%
    dplyr::left_join(reg, by = "user_name") %>%
    dplyr::mutate(clutch = po_ppg - reg_ppg) %>%
    dplyr::select(user_name, reg_ppg, po_ppg, clutch, games) %>%
    dplyr::arrange(dplyr::desc(clutch))
}

#' Playoff margins per manager
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `user_name`, `avg_margin`, `best_win`, `worst_loss`, `games`.
#' @export
sl_playoff_margins <- function(playoffs, scope = "title") {
  d <- dplyr::bind_rows(lapply(playoffs, function(p) sl_scope(p$results, scope))) %>%
    dplyr::filter(result %in% c("W", "L", "T"))
  if (!nrow(d)) return(d)
  d %>% dplyr::group_by(user_name = team) %>%
    dplyr::summarise(games = dplyr::n(), avg_margin = mean(margin), best_win = max(margin),
                     worst_loss = min(margin), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(avg_margin))
}

#' Path difficulty: how hard were the teams you had to beat
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `user_name`, `games`, `opp_ppg` (mean points the opponents
#'   scored against them), `opp_total`.
#' @export
sl_playoff_path <- function(playoffs, scope = "title") {
  d <- dplyr::bind_rows(lapply(playoffs, function(p) sl_scope(p$results, scope))) %>%
    dplyr::filter(result %in% c("W", "L", "T"))
  if (!nrow(d)) return(d)
  d %>% dplyr::group_by(user_name = team) %>%
    dplyr::summarise(games = dplyr::n(), opp_ppg = mean(opp_points),
                     opp_total = sum(opp_points), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(opp_ppg))
}

#' Playoff all-play: win rate against the whole playoff field each week
#'
#' Separates genuinely dominant runs from soft brackets -- your record if you had
#' played every other playoff team that week instead of just your opponent.
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return Tibble: `user_name`, `games`, `allplay_w`, `allplay_l`, `allplay_pct`.
#' @export
sl_playoff_allplay <- function(playoffs, scope = "title") {
  d <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    sl_scope(playoffs[[s]]$results, scope) %>%
      dplyr::filter(result %in% c("W", "L", "T")) %>% dplyr::mutate(season = s)
  }))
  if (!nrow(d)) return(d)
  d %>% dplyr::group_by(season, weeks) %>%
    dplyr::mutate(allplay_w = map_dbl(points, ~ sum(.x > points, na.rm = TRUE)),
                  allplay_l = map_dbl(points, ~ sum(.x < points, na.rm = TRUE))) %>%
    dplyr::ungroup() %>%
    dplyr::group_by(user_name = team) %>%
    dplyr::summarise(games = dplyr::n(), allplay_w = sum(allplay_w),
                     allplay_l = sum(allplay_l),
                     allplay_pct = sum(allplay_w) /
                       pmax(sum(allplay_w) + sum(allplay_l), 1) * 100,
                     .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(allplay_pct))
}

#' Regular-season playoff seeding
#'
#' Seeds are set by the REGULAR season, not the final standings -- the final
#' table includes the playoff weeks themselves, which reorders the middle of the
#' bracket and quietly breaks every seed-based metric.
#'
#' @param season A [sleeper_season] object.
#' @param through_week Last regular-season week (default: the week before the
#'   playoff starts, if `playoff` is supplied).
#' @param playoff Optional `sleeper_playoff` used to infer `through_week`.
#' @return Tibble: `seed`, `user_name`, `wins`, `losses`, `points`.
#' @export
sl_seeds <- function(season, through_week = NULL, playoff = NULL) {
  if (is.null(through_week)) {
    if (is.null(playoff)) stop("Give through_week or a playoff to infer it from.",
                               call. = FALSE)
    wk1 <- min(as.integer(unlist(lapply(playoff$config$rounds, function(r) r$weeks))))
    through_week <- wk1 - 1L
  }
  season$team_wk %>%
    dplyr::filter(week <= through_week) %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(wins = sum(dplyr::coalesce(result == "W", FALSE)),
                     losses = sum(dplyr::coalesce(result == "L", FALSE)),
                     points = round(sum(points), 2), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points)) %>%
    dplyr::mutate(seed = dplyr::row_number()) %>%
    dplyr::select(seed, user_name, wins, losses, points)
}

#' Seed-based playoff metrics: upsets, Cinderellas and chokes
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param seasons Named list of [sleeper_season] objects.
#' @return Tibble: `user_name`, `runs`, `avg_seed`, `best_seed`, `upsets` (wins
#'   over a better seed), `upset_losses`, `cinderella` (best seed-vs-finish
#'   overachievement), `chokes` (top-2 seed that missed the final).
#' @export
sl_playoff_seeding <- function(playoffs, seasons) {
  rows <- dplyr::bind_rows(lapply(names(playoffs), function(s) {
    p <- playoffs[[s]]
    if (is.null(seasons[[s]])) return(NULL)
    sd <- sl_seeds(seasons[[s]], playoff = p)
    seed_of <- stats::setNames(sd$seed, sd$user_name)
    r <- sl_scope(p$results, "title") %>% dplyr::filter(result %in% c("W", "L", "T"))
    fid <- p$config$final
    reached_final <- unique(p$results$team[p$results$matchup_id == fid])
    r %>% dplyr::mutate(
      season = s,
      seed = unname(seed_of[team]),
      opp_seed = unname(seed_of[opponent]),
      upset = result == "W" & !is.na(opp_seed) & !is.na(seed) & seed > opp_seed,
      upset_loss = result == "L" & !is.na(opp_seed) & !is.na(seed) & seed < opp_seed,
      in_final = team %in% reached_final,
      champ = team == (p$champion %||% ""))
  }))
  if (!nrow(rows)) return(rows)
  rows %>% dplyr::group_by(user_name = team, season) %>%
    dplyr::summarise(seed = dplyr::first(seed), upsets = sum(upset),
                     upset_losses = sum(upset_loss),
                     in_final = any(in_final), champ = any(champ),
                     .groups = "drop") %>%
    dplyr::group_by(user_name) %>%
    dplyr::summarise(runs = dplyr::n(), avg_seed = mean(seed, na.rm = TRUE),
                     best_seed = suppressWarnings(min(seed, na.rm = TRUE)),
                     upsets = sum(upsets), upset_losses = sum(upset_losses),
                     # Cinderella: the deepest run relative to seed (a low seed
                     # reaching a final scores highest).
                     cinderella = suppressWarnings(max(
                       ifelse(in_final, seed, 0L), na.rm = TRUE)),
                     chokes = sum(seed <= 2 & !in_final, na.rm = TRUE),
                     .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(upsets), avg_seed)
}

#' Did the wrong team win? Replay each matchup with optimal lineups
#'
#' Re-scores both sides of every playoff game using the best legal lineup their
#' roster could have started, and reports where the result would have flipped.
#'
#' Only works where the season object actually holds that week's rosters. DDBM
#' 2025's final is week 18, past `last_scored_leg` (17), so it cannot be
#' replayed -- those rows come back `NA` rather than being quietly dropped.
#'
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param seasons Named list of [sleeper_season] objects.
#' @param scope See [sl_scope()].
#' @return Tibble: one row per matchup with actual and optimal points for both
#'   sides, and `flipped`.
#' @export
sl_playoff_replay <- function(playoffs, seasons, scope = "title") {
  dplyr::bind_rows(lapply(names(playoffs), function(s) {
    p <- playoffs[[s]]; se <- seasons[[s]]
    if (is.null(se)) return(NULL)
    r <- sl_scope(p$results, scope) %>% dplyr::filter(result %in% c("W", "L"))
    if (!nrow(r)) return(NULL)
    dplyr::bind_rows(lapply(unique(r$matchup_id), function(m) {
      g <- r[r$matchup_id == m, ]
      wks <- as.integer(strsplit(g$weeks[1], "\\+")[[1]])
      opt <- vapply(g$team, function(tm) {
        rid <- se$user_map$roster_id[match(tm, se$user_map$user_name)]
        # Playoff weeks sit OUTSIDE the regular season, so read the unscoped
        # frame -- se$pl_wk stops at playoff_week_start - 1 and would find
        # nothing here (mirrors pl_wk_all in python/sleepermetrics/playoffs.py).
        pw <- se$pl_wk_all %||% se$pl_wk
        d <- pw %>% dplyr::filter(roster_id == rid, week %in% wks)
        if (!nrow(d) || !all(wks %in% unique(d$week))) return(NA_real_)
        sum(vapply(wks, function(w) sl_optimal_points(
          d %>% dplyr::filter(week == w), se$slots), numeric(1)))
      }, numeric(1))
      opt_win <- if (anyNA(opt)) NA_character_ else g$team[which.max(opt)]
      act_win <- g$team[g$result == "W"][1]
      tibble(season = s, matchup_id = m, round = g$round[1],
             team_a = g$team[1], team_b = g$team[2],
             actual_a = g$points[1], actual_b = g$points[2],
             optimal_a = round(opt[[1]], 2), optimal_b = round(opt[[2]], 2),
             actual_winner = act_win, optimal_winner = opt_win,
             flipped = if (is.na(opt_win)) NA else opt_win != act_win)
    }))
  }))
}

#' Playoff standings (per-team run through the bracket)
#'
#' `outcome` narrates how each run ended and is never `NA`: the champion and the
#' runner-up are named outright, and elimination is the last loss in the **title**
#' bracket, not the last loss overall -- consolation games are played after a team
#' is already out, so ranking by them overstates the run.
#' @param playoff A `sleeper_playoff` object.
#' @return Tibble: `team`, `games`, `wins`, `losses`, `points`, `outcome`.
#' @export
sl_playoff_summary <- function(playoff) {
  champ <- playoff$champion
  rounds <- playoff$config$rounds
  final_id <- playoff$config$final
  if (is.null(final_id) && length(rounds)) {
    last <- rounds[[length(rounds)]]$matchups
    if (length(last)) final_id <- last[[length(last)]]$id
  }
  playoff$results %>%
    dplyr::group_by(team) %>%
    dplyr::summarise(
      games = sum(result %in% c("W", "L", "T")),
      wins = sum(result == "W"), losses = sum(result == "L"),
      points = round(sum(points, na.rm = TRUE), 2),
      # Rate stats live here so one table can carry the whole run; a team with
      # only byes has no played game, so guard the divide.
      win_pct = if (sum(result %in% c("W", "L", "T"))) {
        sum(result == "W") / sum(result %in% c("W", "L", "T")) * 100
      } else 0,
      ppg = if (sum(result %in% c("W", "L", "T"))) {
        sum(points, na.rm = TRUE) / sum(result %in% c("W", "L", "T"))
      } else 0,
      outcome = {
        lost <- result == "L"
        is_title <- if (!is.null(playoff$results$bracket)) bracket == "title" else lost
        out_in <- round[lost & is_title]
        if (!length(out_in)) out_in <- round[lost]
        if (!is.null(champ) && length(champ) && team[1] == champ) {
          "Champion"
        } else if (!is.null(final_id) && any(lost & matchup_id == final_id)) {
          "Runner-up"
        } else if (length(out_in)) {
          paste("Lost in", out_in[length(out_in)])
        } else if (is.null(champ) || !length(champ)) {
          "Still alive"
        } else {
          "—"
        }
      }, .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points))
}
