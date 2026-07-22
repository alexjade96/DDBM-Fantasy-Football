# Single-week metrics and recap text --------------------------------------

#' Per-team stats for one week
#'
#' @param season A [sleeper_season] object.
#' @param week Week number; default = the season's last scored week.
#' @return A tibble (one row per team) with `points`, `opp_points`, `result`,
#'   `margin`, `optimal`, `left_on_bench`, ordered by points.
#' @export
sl_week_stats <- function(season, week = NULL) {
  wk <- week %||% season$last_week
  lu <- season$lineup %>% dplyr::filter(week == wk) %>%
    dplyr::select(user_name, optimal, left_on_bench)
  season$team_wk %>% dplyr::filter(week == wk) %>%
    dplyr::left_join(lu, by = "user_name") %>%
    dplyr::transmute(week = wk, user_name, points, opp_points = pa, result,
                     margin = round(points - pa, 2), optimal,
                     left_on_bench = round(left_on_bench, 1)) %>%
    dplyr::arrange(dplyr::desc(points))
}

#' Markdown recap for one week
#'
#' Names the week's top and low scorer, the biggest blowout, the closest game
#' and the manager who left the most points on their bench.
#'
#' @param season A [sleeper_season] object.
#' @param week Week number; default = last scored week.
#' @return A single markdown string.
#' @export
sl_summary_week <- function(season, week = NULL) {
  wk <- week %||% season$last_week
  d <- sl_week_stats(season, wk)
  top <- d %>% dplyr::slice_max(points, n = 1, with_ties = FALSE)
  low <- d %>% dplyr::slice_min(points, n = 1, with_ties = FALSE)
  # Format to ONE decimal like Python's :.1f. round() drops a trailing
  # zero, so a whole-numbered score renders "78" against Python's
  # "78.0" -- verify.py compares the summary strings EXACTLY.
  fmt1 <- function(x) sprintf("%.1f", round(as.numeric(x), 1))
  bust <- d %>% dplyr::slice_max(left_on_bench, n = 1, with_ties = FALSE)
  played <- d %>% dplyr::filter(!is.na(result), result != "T", margin > 0)
  lines <- c(
    paste0("### ", season$name, " - Week ", wk, " recap"), "",
    paste0("- \U0001F525 **Top score:** ", top$user_name, " (", fmt1(top$points), ")"),
    paste0("- \U0001F9CA **Low score:** ", low$user_name, " (", fmt1(low$points), ")"))
  if (nrow(played)) {
    blow <- played %>% dplyr::slice_max(margin, n = 1, with_ties = FALSE)
    close <- played %>% dplyr::slice_min(margin, n = 1, with_ties = FALSE)
    lines <- c(lines,
      paste0("- \U0001F4A5 **Biggest blowout:** ", blow$user_name, " by ",
             fmt1(blow$margin)),
      paste0("- \U0001F630 **Closest game:** ", close$user_name, " won by ",
             fmt1(close$margin)))
  }
  lines <- c(lines,
    paste0("- \U0001FA91 **Biggest bench blunder:** ", bust$user_name, " left ",
           fmt1(bust$left_on_bench), " pts on the bench"))
  paste(lines, collapse = "\n")
}
