# Auto-generated insight text (narrate layer) ------------------------------

.b <- function(x) paste0("**", x, "**")

#' Markdown insight summary for one season
#'
#' Reads the season's metrics and writes a short bullet list naming the leader,
#' luckiest/unluckiest, best/worst coach, high-score leader and the steadiest
#' vs most volatile scorer.
#'
#' @param season A [sleeper_season] object.
#' @return A single markdown string.
#' @export
sl_summary_season <- function(season) {
  st <- season$standings
  lead <- st %>% dplyr::slice_min(final_position, n = 1, with_ties = FALSE)
  lk <- sl_luck(season)
  lucky <- lk %>% dplyr::slice_max(luck, n = 1, with_ties = FALSE)
  unlucky <- lk %>% dplyr::slice_min(luck, n = 1, with_ties = FALSE)
  eff <- sl_efficiency(season)
  best_c <- eff %>% dplyr::slice_max(eff, n = 1, with_ties = FALSE)
  worst_c <- eff %>% dplyr::slice_min(eff, n = 1, with_ties = FALSE)
  hi <- st %>% dplyr::slice_max(highs, n = 1, with_ties = FALSE)
  cons <- sl_consistency(season)
  steady <- cons %>% dplyr::slice_min(sd, n = 1, with_ties = FALSE)
  swingy <- cons %>% dplyr::slice_max(sd, n = 1, with_ties = FALSE)
  paste0(
    "### ", season$season, " season - what the numbers say\n\n",
    "- ", .b("Top of the table:"), " ", .b(lead$user_name), " (", lead$wins, "-", lead$losses,
      ", ", round(lead$points), " pts", ifelse(lead$champion, ", and the champion \U0001F451", ""), ").\n",
    "- ", .b("Luckiest:"), " ", .b(lucky$user_name), " won ", sprintf("%+.1f", lucky$luck),
      " games above all-play expectation; ", .b("unluckiest:"), " ", .b(unlucky$user_name),
      " (", sprintf("%+.1f", unlucky$luck), ").\n",
    "- ", .b("Best coach:"), " ", .b(best_c$user_name), " started ", sprintf("%.1f%%", best_c$eff),
      " of their optimal lineup; ", .b("most left on the bench:"), " ", .b(worst_c$user_name),
      " (", round(worst_c$bench), " pts wasted).\n",
    "- ", .b("Weekly high-score crowns:"), " ", .b(hi$user_name), " led the league in scoring ",
      hi$highs, " week(s).\n",
    "- ", .b("Steadiest:"), " ", .b(steady$user_name), " (SD ", round(steady$sd), "); ",
      .b("boom-or-bust:"), " ", .b(swingy$user_name), " (SD ", round(swingy$sd), ").")
}

#' Markdown insight summary across all seasons
#'
#' @param seasons A list of [sleeper_season] objects.
#' @return A single markdown string.
#' @export
sl_summary_career <- function(seasons) {
  ct <- sl_career(seasons)
  vets <- ct %>% dplyr::filter(seasons == max(seasons))
  best <- ct %>% dplyr::slice_max(win_pct, n = 1, with_ties = FALSE)
  most_t <- ct %>% dplyr::slice_max(titles, n = 1, with_ties = FALSE)
  worst <- ct %>% dplyr::slice_min(win_pct, n = 1, with_ties = FALSE)
  paste0(
    "### Career - across all seasons\n\n",
    "- ", .b("Managers tracked:"), " ", nrow(ct), " (", sum(ct$seasons > 1), " multi-season).\n",
    "- ", .b("Best win %:"), " ", .b(best$user_name), " (", best$win_pct, "%, ", best$record, ").\n",
    "- ", .b("Most titles:"), " ", .b(most_t$user_name), " with ", most_t$titles, ".\n",
    "- ", .b("Longest-tenured:"), " ", paste(.b(vets$user_name), collapse = ", "),
      " (", max(ct$seasons), " seasons).\n",
    "- ", .b("Still chasing a winning record:"), " ", .b(worst$user_name),
      " (", worst$win_pct, "%).")
}
