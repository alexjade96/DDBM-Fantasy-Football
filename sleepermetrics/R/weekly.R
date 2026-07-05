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
  bust <- d %>% dplyr::slice_max(left_on_bench, n = 1, with_ties = FALSE)
  played <- d %>% dplyr::filter(!is.na(result), result != "T", margin > 0)
  lines <- c(
    paste0("### ", season$name, " - Week ", wk, " recap"), "",
    paste0("- \U0001F525 **Top score:** ", top$user_name, " (", round(top$points, 1), ")"),
    paste0("- \U0001F9CA **Low score:** ", low$user_name, " (", round(low$points, 1), ")"))
  if (nrow(played)) {
    blow <- played %>% dplyr::slice_max(margin, n = 1, with_ties = FALSE)
    close <- played %>% dplyr::slice_min(margin, n = 1, with_ties = FALSE)
    lines <- c(lines,
      paste0("- \U0001F4A5 **Biggest blowout:** ", blow$user_name, " by ",
             round(blow$margin, 1)),
      paste0("- \U0001F630 **Closest game:** ", close$user_name, " won by ",
             round(close$margin, 1)))
  }
  lines <- c(lines,
    paste0("- \U0001FA91 **Biggest bench blunder:** ", bust$user_name, " left ",
           round(bust$left_on_bench, 1), " pts on the bench"))
  paste(lines, collapse = "\n")
}
