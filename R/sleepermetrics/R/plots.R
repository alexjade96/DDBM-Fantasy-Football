# Charts (render layer) ----------------------------------------------------

#' A clean ggplot theme for sleepermetrics charts
#' @return A ggplot2 theme.
#' @export
theme_sleeper <- function() {
  ggplot2::theme_minimal(base_size = 13) %+replace% ggplot2::theme(
    plot.title    = ggplot2::element_text(face = "bold", size = 17, hjust = 0,
                                          margin = ggplot2::margin(b = 2)),
    plot.subtitle = ggplot2::element_text(color = "grey38", hjust = 0, size = 10,
                                          margin = ggplot2::margin(b = 8)),
    plot.caption  = ggplot2::element_text(color = "grey55", size = 8, hjust = 1),
    panel.grid.minor = ggplot2::element_blank(),
    plot.background  = ggplot2::element_rect(fill = "white", color = NA),
    plot.margin = ggplot2::margin(12, 16, 8, 12))
}

.sl_cap <- function(season) paste0("Data: Sleeper API  -  ", season$name, " ", season$season)

#' Season standings bar chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_standings <- function(season) {
  d <- season$standings %>%
    dplyr::mutate(record = paste0(wins, "-", losses),
                  lbl = paste0(record, ifelse(champion, "  \U0001F451", "")),
                  user_name = fct_reorder(user_name, points))
  ggplot2::ggplot(d, ggplot2::aes(points, user_name, fill = user_name)) +
    ggplot2::geom_col(width = 0.72, show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(label = lbl), hjust = -0.03, size = 3.4,
                       family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.18))) +
    ggplot2::labs(title = paste(season$season, "Standings"),
                  subtitle = "Total points; record labeled, crown = champion",
                  x = "Season Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Luck (actual vs all-play expected wins) dumbbell
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_luck <- function(season) {
  d <- sl_luck(season) %>% dplyr::mutate(user_name = fct_reorder(user_name, luck))
  ggplot2::ggplot(d, ggplot2::aes(y = user_name)) +
    ggplot2::geom_segment(ggplot2::aes(x = exp_w, xend = wins, yend = user_name),
                          color = "grey75", linewidth = 1) +
    ggplot2::geom_point(ggplot2::aes(x = exp_w), color = "grey55", size = 3.5) +
    ggplot2::geom_point(ggplot2::aes(x = wins, color = luck > 0), size = 4.5,
                        show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(x = wins, label = sprintf("%+.1f", luck),
                                    hjust = ifelse(luck > 0, -0.4, 1.4)),
                       size = 3, fontface = "bold") +
    ggplot2::scale_color_manual(values = c(`TRUE` = "#2ca02c", `FALSE` = "#d62728")) +
    ggplot2::labs(title = "Luck: Actual vs All-Play Expected Wins",
                  subtitle = "Grey = expected wins vs whole league each week; colored = actual",
                  x = "Wins", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Lineup efficiency chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_efficiency <- function(season) {
  d <- sl_efficiency(season) %>% dplyr::mutate(user_name = fct_reorder(user_name, eff))
  ggplot2::ggplot(d, ggplot2::aes(eff, user_name)) +
    ggplot2::geom_col(ggplot2::aes(fill = eff), width = 0.72, show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%  (%.0f pts benched)", eff, bench)),
                       hjust = -0.03, size = 3) +
    ggplot2::scale_fill_gradient(low = "#f0a58f", high = "#2ca02c") +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.55)), limits = c(0, 100)) +
    ggplot2::labs(title = "Lineup Efficiency (Coaching)",
                  subtitle = "Started points as % of the optimal lineup each week",
                  x = "Efficiency %", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Weekly score distribution (consistency) chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_consistency <- function(season) {
  ord <- sl_consistency(season) %>% dplyr::arrange(dplyr::desc(median)) %>% dplyr::pull(user_name)
  d <- season$team_wk %>% dplyr::mutate(user_name = factor(user_name, levels = ord))
  ggplot2::ggplot(d, ggplot2::aes(points, user_name, fill = user_name)) +
    ggplot2::geom_boxplot(width = 0.55, alpha = 0.55, outlier.shape = NA, show.legend = FALSE) +
    ggplot2::geom_jitter(ggplot2::aes(color = user_name), height = 0.15, alpha = 0.6,
                         size = 1.5, show.legend = FALSE) +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_color_manual(values = sl_palette(d$user_name)) +
    ggplot2::labs(title = "Consistency: Weekly Score Distributions",
                  subtitle = "Tight box = steady; wide = boom-or-bust",
                  x = "Weekly Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Points-for vs points-against quadrant chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_pf_pa <- function(season) {
  d <- sl_points_for_against(season)
  ggplot2::ggplot(d, ggplot2::aes(points, pa)) +
    ggplot2::geom_vline(xintercept = stats::median(d$points), linetype = "dashed", color = "grey60") +
    ggplot2::geom_hline(yintercept = stats::median(d$pa), linetype = "dashed", color = "grey60") +
    ggplot2::geom_point(ggplot2::aes(color = user_name, size = wins), show.legend = FALSE) +
    ggrepel::geom_text_repel(ggplot2::aes(label = paste0(user_name, " (", wins, "W)")), size = 3) +
    ggplot2::scale_color_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_size(range = c(3, 9)) +
    ggplot2::labs(title = "Points For vs Points Against",
                  subtitle = "Right = scored a lot; low = fewer points allowed; size = wins",
                  x = "Points For", y = "Points Against", caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Career standings chart
#' @param seasons A list of [sleeper_season] objects.
#' @return A ggplot.
#' @export
sl_plot_career <- function(seasons) {
  d <- sl_career(seasons) %>% dplyr::mutate(user_name = fct_reorder(user_name, win_pct))
  ggplot2::ggplot(d, ggplot2::aes(win_pct, user_name, fill = user_name)) +
    ggplot2::geom_col(width = 0.72, show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%s  %.1f%%  %s", record, win_pct,
                                    ifelse(titles > 0, strrep("\U0001F451", titles), ""))),
                       hjust = -0.03, size = 3.2, family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.35)), limits = c(0, 100)) +
    ggplot2::labs(title = "Career Standings (All Seasons)", subtitle = "Ranked by win %",
                  x = "Career Win %", y = NULL) +
    theme_sleeper()
}

#' Finish-trajectory-by-season chart
#' @param seasons A list of [sleeper_season] objects.
#' @return A ggplot.
#' @export
sl_plot_trajectory <- function(seasons) {
  all <- sl_bind_standings(seasons)
  canon <- all %>% dplyr::group_by(user_id) %>%
    dplyr::arrange(dplyr::desc(as.integer(season))) %>%
    dplyr::summarise(nm = dplyr::first(user_name), .groups = "drop")
  d <- all %>% dplyr::left_join(canon, by = "user_id") %>%
    dplyr::mutate(season = as.integer(season))
  mp <- max(all$final_position)
  ggplot2::ggplot(d, ggplot2::aes(season, final_position, color = nm, group = nm)) +
    ggplot2::geom_line(linewidth = 1.1, alpha = 0.85) +
    ggplot2::geom_point(ggplot2::aes(shape = champion), size = 3) +
    ggrepel::geom_text_repel(
      data = d %>% dplyr::group_by(nm) %>% dplyr::filter(season == max(season)),
      ggplot2::aes(label = nm), nudge_x = 0.12, hjust = 0, size = 3,
      direction = "y", show.legend = FALSE) +
    ggplot2::scale_y_reverse(breaks = 1:mp) +
    ggplot2::scale_x_continuous(breaks = sort(unique(d$season)),
                                expand = ggplot2::expansion(c(0.02, 0.16))) +
    ggplot2::scale_shape_manual(values = c(`FALSE` = 16, `TRUE` = 8), guide = "none") +
    ggplot2::scale_color_manual(values = sl_palette(d$nm), guide = "none") +
    ggplot2::labs(title = "Finish Trajectory by Season", subtitle = "1 = top; star = champion",
                  x = "Season", y = "Final Position") +
    theme_sleeper()
}
