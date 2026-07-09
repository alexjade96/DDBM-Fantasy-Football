# Charts (render layer) ----------------------------------------------------

#' A clean, recessive ggplot theme for sleepermetrics charts
#'
#' Bold title, muted subtitle/caption, ink-token axis text, and light gridlines
#' only on the value axis (horizontal-bar friendly). Line/scatter charts re-add
#' the y grid themselves.
#' @return A ggplot2 theme.
#' @export
theme_sleeper <- function() {
  ggplot2::theme_minimal(base_size = 13) %+replace% ggplot2::theme(
    plot.title    = ggplot2::element_text(face = "bold", size = 18, hjust = 0,
                                          colour = "grey15", margin = ggplot2::margin(b = 2)),
    plot.subtitle = ggplot2::element_text(colour = "grey40", hjust = 0, size = 10.5,
                                          margin = ggplot2::margin(b = 10)),
    plot.caption  = ggplot2::element_text(colour = "grey60", size = 8, hjust = 1,
                                          margin = ggplot2::margin(t = 8)),
    axis.title    = ggplot2::element_text(colour = "grey40", size = 10),
    axis.text     = ggplot2::element_text(colour = "grey30"),
    panel.grid.minor   = ggplot2::element_blank(),
    panel.grid.major.y = ggplot2::element_blank(),
    panel.grid.major.x = ggplot2::element_line(colour = "grey92", linewidth = 0.4),
    plot.background = ggplot2::element_rect(fill = "white", colour = NA),
    plot.title.position = "plot",
    plot.margin = ggplot2::margin(14, 18, 10, 14))
}

.sl_cap <- function(season) paste0("Data: Sleeper API  ·  ", season$name, " ", season$season)
.sl_medal_cols <- c("#f1c40f", "#c8cdd0", "#cd7f32")  # gold, silver, bronze

# Podium badges: a medal-coloured disc with the rank number, for the top-3 rows
# (rank carried by shape+number so identity is never colour-alone). Returns a
# list of ggplot layers to add. `x0` places the badge near the bar origin.
.sl_medals <- function(d, rank_col, x0) {
  top <- d[d[[rank_col]] <= 3, , drop = FALSE]
  if (!nrow(top)) return(NULL)
  top$.mcol <- .sl_medal_cols[top[[rank_col]]]
  top$.x0 <- x0
  list(
    ggplot2::geom_point(data = top, ggplot2::aes(x = .x0, y = user_name),
                        fill = top$.mcol, colour = "white", shape = 21,
                        size = 6.4, stroke = 1.1, inherit.aes = FALSE),
    ggplot2::geom_text(data = top, ggplot2::aes(x = .x0, y = user_name, label = .data[[rank_col]]),
                       inherit.aes = FALSE, size = 3, fontface = "bold", colour = "grey20"))
}

#' Season standings bar chart
#'
#' Bars in standing order (1st on top), podium medals on the top three, and a
#' crown on the playoff champion.
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_standings <- function(season) {
  d <- season$standings %>%
    dplyr::mutate(record = paste0(wins, "-", losses),
                  lbl = paste0(record, ifelse(champion, "  \U0001F451", "")),
                  user_name = fct_reorder(user_name, final_position, .desc = TRUE))
  x0 <- max(d$points) * 0.035
  ggplot2::ggplot(d, ggplot2::aes(points, user_name, fill = user_name)) +
    ggplot2::geom_col(width = 0.72, show.legend = FALSE) +
    .sl_medals(d, "final_position", x0) +
    ggplot2::geom_text(ggplot2::aes(label = lbl), hjust = -0.03, size = 3.4,
                       colour = "grey20", family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.16))) +
    ggplot2::labs(title = paste(season$season, "Standings"),
                  subtitle = "Bars = total points, in standing order  ·  \U0001F947\U0001F948\U0001F949 podium  ·  \U0001F451 champion",
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
    ggplot2::geom_segment(ggplot2::aes(x = exp_w, xend = wins, yend = user_name,
                                       colour = luck > 0), linewidth = 1.3, alpha = 0.5) +
    ggplot2::geom_point(ggplot2::aes(x = exp_w), colour = "grey65", size = 3.6) +
    ggplot2::geom_point(ggplot2::aes(x = wins, colour = luck > 0), size = 4.8) +
    ggplot2::geom_text(ggplot2::aes(x = wins, label = sprintf("%+.1f", luck),
                                    colour = luck > 0, hjust = ifelse(luck > 0, -0.4, 1.4)),
                       size = 3, fontface = "bold", show.legend = FALSE) +
    ggplot2::scale_colour_manual(values = c(`TRUE` = "#2ca02c", `FALSE` = "#d62728"),
                                 labels = c(`TRUE` = "lucky (won more than earned)",
                                            `FALSE` = "unlucky"), name = NULL) +
    ggplot2::labs(title = "Luck: Actual vs All-Play Expected Wins",
                  subtitle = "Grey dot = expected wins vs the whole league each week; coloured = actual",
                  x = "Wins", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left")
}

#' Lineup efficiency chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_efficiency <- function(season) {
  d <- sl_efficiency(season) %>% dplyr::mutate(user_name = fct_reorder(user_name, eff))
  ggplot2::ggplot(d, ggplot2::aes(eff, user_name)) +
    ggplot2::geom_col(ggplot2::aes(fill = eff), width = 0.72, show.legend = FALSE) +
    ggplot2::geom_vline(xintercept = 100, linetype = "dashed", colour = "grey70") +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f%%  (%.0f pts benched)", eff, bench)),
                       hjust = -0.03, size = 3, colour = "grey20") +
    ggplot2::scale_fill_gradient(low = "#c8e6c9", high = "#1b5e20", limits = c(70, 100),
                                 oob = scales::squish) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.5)), limits = c(0, 100)) +
    ggplot2::labs(title = "Lineup Efficiency (Coaching)",
                  subtitle = "Started points as % of the optimal lineup each week  ·  100% = optimal  ·  darker = better",
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
    ggplot2::geom_boxplot(width = 0.55, alpha = 0.5, outlier.shape = NA,
                          colour = "grey55", show.legend = FALSE) +
    ggplot2::geom_jitter(ggplot2::aes(colour = user_name), height = 0.15, alpha = 0.65,
                         size = 1.6, show.legend = FALSE) +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_colour_manual(values = sl_palette(d$user_name)) +
    ggplot2::labs(title = "Consistency: Weekly Score Distributions",
                  subtitle = "Tight box = steady  ·  wide = boom-or-bust",
                  x = "Weekly Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Points-for vs points-against quadrant chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_pf_pa <- function(season) {
  d <- sl_points_for_against(season)
  mx <- stats::median(d$points); my <- stats::median(d$pa)
  xr <- range(d$points); yr <- range(d$pa)
  quad <- data.frame(
    x = c(xr[2], xr[1], xr[2], xr[1]), y = c(yr[1], yr[2], yr[2], yr[1]),
    h = c(1, 0, 1, 0), v = c(0, 1, 1, 0),
    lab = c("Dominant", "Snakebit", "Shootouts", "Low-event"))
  ggplot2::ggplot(d, ggplot2::aes(points, pa)) +
    ggplot2::geom_vline(xintercept = mx, linetype = "dashed", colour = "grey75") +
    ggplot2::geom_hline(yintercept = my, linetype = "dashed", colour = "grey75") +
    ggplot2::geom_text(data = quad, ggplot2::aes(x = x, y = y, label = lab, hjust = h, vjust = v),
                       inherit.aes = FALSE, size = 3.2, fontface = "italic", colour = "grey78") +
    ggplot2::geom_point(ggplot2::aes(colour = user_name, size = wins), show.legend = FALSE) +
    ggrepel::geom_text_repel(ggplot2::aes(label = paste0(user_name, " (", wins, "W)")),
                             size = 3, colour = "grey25", point.padding = 6) +
    ggplot2::scale_colour_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_size(range = c(3, 9)) +
    ggplot2::labs(title = "Points For vs Points Against",
                  subtitle = "Lower-right beats up the league; upper-left gets snakebit  ·  dot size = wins",
                  x = "Points For", y = "Points Against", caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4))
}

#' Career standings chart
#' @param seasons A list of [sleeper_season] objects.
#' @return A ggplot.
#' @export
sl_plot_career <- function(seasons) {
  d <- sl_career(seasons) %>%
    dplyr::mutate(rank = rank(-win_pct, ties.method = "first"),
                  user_name = fct_reorder(user_name, win_pct))
  ggplot2::ggplot(d, ggplot2::aes(win_pct, user_name, fill = user_name)) +
    ggplot2::geom_col(width = 0.72, show.legend = FALSE) +
    .sl_medals(d, "rank", 3.5) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%s  %.1f%%  %s", record, win_pct,
                                    ifelse(titles > 0, strrep("\U0001F451", titles), ""))),
                       hjust = -0.03, size = 3.2, colour = "grey20", family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.32)), limits = c(0, 100)) +
    ggplot2::labs(title = "Career Standings (All Seasons)",
                  subtitle = "Ranked by win %  ·  \U0001F947\U0001F948\U0001F949 podium  ·  \U0001F451 per title",
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
  ggplot2::ggplot(d, ggplot2::aes(season, final_position, colour = nm, group = nm)) +
    ggplot2::annotate("rect", xmin = -Inf, xmax = Inf, ymin = 0.5, ymax = 3.5,
                      fill = "#f1c40f", alpha = 0.08) +
    ggplot2::annotate("text", x = min(d$season), y = 1, label = "podium",
                      hjust = -0.1, vjust = 0.5, size = 3, colour = "grey60") +
    ggplot2::geom_line(linewidth = 1.2, alpha = 0.85) +
    ggplot2::geom_point(ggplot2::aes(shape = champion), size = 3.2) +
    ggrepel::geom_text_repel(
      data = d %>% dplyr::group_by(nm) %>% dplyr::filter(season == max(season)),
      ggplot2::aes(label = nm), nudge_x = 0.12, hjust = 0, size = 3,
      direction = "y", show.legend = FALSE) +
    ggplot2::scale_y_reverse(breaks = 1:mp) +
    ggplot2::scale_x_continuous(breaks = sort(unique(d$season)),
                                expand = ggplot2::expansion(c(0.04, 0.16))) +
    ggplot2::scale_shape_manual(values = c(`FALSE` = 16, `TRUE` = 8), guide = "none") +
    ggplot2::scale_colour_manual(values = sl_palette(d$nm), guide = "none") +
    ggplot2::labs(title = "Finish Trajectory by Season",
                  subtitle = "1 = top  ·  gold band = podium  ·  ✳ = champion",
                  x = "Season", y = "Final Position") +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4))
}

# --- Roster & position charts (ported from ddbmFF.R) ----------------------

#' League scoring-by-position chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_position_scoring <- function(season) {
  d <- sl_position_scoring(season)
  ggplot2::ggplot(d, ggplot2::aes(points, position, fill = position)) +
    ggplot2::geom_col(width = 0.7, show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%s pts  ·  %.0f%%", round(points), share)),
                       hjust = -0.04, size = 3.4, colour = "grey20") +
    ggplot2::scale_fill_manual(values = .sl_pos_colors) +
    ggplot2::scale_y_discrete(limits = rev(.sl_positions)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.2))) +
    ggplot2::labs(title = "Where the Points Come From",
                  subtitle = "Total started points by position  ·  share of league scoring",
                  x = "Starter Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Roster-construction heatmap (team \U00D7 position)
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_roster_heatmap <- function(season) {
  d <- sl_roster(season)
  ggplot2::ggplot(d, ggplot2::aes(position, user_name, fill = avg)) +
    ggplot2::geom_tile(colour = "white", linewidth = 1.4) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%d wk\n%.1f", spots, avg)),
                       size = 2.7, lineheight = 0.9, colour = "grey15") +
    ggplot2::scale_fill_gradient(low = "#eaf2f8", high = "#1f6f8b", name = "Avg pts") +
    ggplot2::scale_x_discrete(position = "top") +
    ggplot2::labs(title = "Roster Construction",
                  subtitle = "Player-weeks rostered and average points, by team and position",
                  x = NULL, y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.x = ggplot2::element_blank(),
                   legend.position = "right")
}

#' Starters-vs-bench average points chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_starter_bench <- function(season) {
  d <- sl_starter_bench(season) %>%
    dplyr::mutate(status = factor(status, levels = c("Starters", "Bench")))
  ggplot2::ggplot(d, ggplot2::aes(avg, user_name, fill = status)) +
    ggplot2::geom_col(position = ggplot2::position_dodge(width = 0.7), width = 0.66) +
    ggplot2::facet_wrap(~ position, nrow = 1) +
    ggplot2::scale_fill_manual(values = c(Starters = "#2f9e44", Bench = "#c3c9d0"), name = NULL) +
    ggplot2::labs(title = "Starters vs Bench",
                  subtitle = "Average points by position  ·  are the right players in the lineup?",
                  x = "Average Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left",
                   panel.spacing = ggplot2::unit(0.8, "lines"),
                   strip.text = ggplot2::element_text(face = "bold", colour = "grey30"))
}
