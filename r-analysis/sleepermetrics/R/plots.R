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

# Icon-then-name identity axis for a horizontal chart. Each row reads
# [icon] name  |  bar -- the same order as the Career tab's Managers panel.
#
# The names stay real axis text (so ggplot keeps auto-sizing the column) but are
# left-aligned, which lines their left edges up. The icon is then hung at an
# absolute offset from the panel's left edge, stepped back by the width of the
# LONGEST label: grid resolves grobWidth() at draw time, so the icon column lands
# exactly beside the name column without us having to guess how wide the names
# render. plot.margin gains a fixed amount (the icon is a fixed size) to make
# room, since ggplot reserves nothing for annotations outside the panel.
#
# `token(j, x)` returns row j's rasterGrob (already right-justified at `x`), or
# NULL -- so a row with no image simply keeps its plain name.
#
# Add this AFTER theme_sleeper() in the chain: theme_sleeper() is a *complete*
# theme, so adding it later would replace these settings outright. And note
# axis.text.y.left, not axis.text.y: the complete theme defines the .left child,
# which shadows its parent -- setting the parent alone renders byte-identically.
# `fontsize` must match what the axis text ACTUALLY renders at, or the icon
# column lands on top of the names. theme_sleeper()'s %+replace% swaps axis.text
# out wholesale, which drops theme_minimal's size = rel(0.8) -- so the labels
# inherit `text`'s size, i.e. the 13pt base size, not 10.4.
.sl_identity_axis <- function(labels, token, size_mm = 5, gap_pt = 8,
                              fontsize = 13) {
  labels <- as.character(labels)
  longest <- labels[which.max(nchar(labels))]
  maxw <- grid::grobWidth(grid::textGrob(longest, gp = grid::gpar(fontsize = fontsize)))
  x <- grid::unit(0, "npc") - grid::unit(gap_pt, "pt") - maxw - grid::unit(2.6, "mm")
  lays <- list()
  for (j in seq_along(labels)) {
    g <- token(j, x)
    if (is.null(g)) next
    lays[[length(lays) + 1L]] <- ggplot2::annotation_custom(
      g, xmin = -Inf, xmax = Inf, ymin = j, ymax = j)
  }
  if (!length(lays)) return(NULL)
  c(lays, list(
    ggplot2::coord_cartesian(clip = "off"),
    ggplot2::theme(
      axis.text.y.left = ggplot2::element_text(
        hjust = 0, margin = ggplot2::margin(r = gap_pt)),
      plot.margin = ggplot2::margin(14, 18, 10, 14 + size_mm * 3.8))))
}

# Icon-then-name axis for a team chart: token = the manager's account avatar.
.sl_row_avatars <- function(season, levels, size_mm = 5, ...) {
  urls <- .sl_avatar_map(season)
  lv <- as.character(levels)
  .sl_identity_axis(lv, function(j, x) {
    if (!lv[j] %in% names(urls)) return(NULL)
    sl_avatar_grob(urls[[lv[j]]], size_mm, x = x, just = "right")
  }, size_mm = size_mm, ...)
}

# Manager avatars drawn as the markers of a scatter (name already sits to the
# right of the token there, so the icon-then-name order needs nothing extra).
.sl_scatter_avatars <- function(season, d, xcol, ycol, size_mm = 5) {
  av <- .sl_point_avatars(season, d, xcol, ycol, size_mm)
  if (!length(av)) return(NULL)
  c(av, list(ggplot2::coord_cartesian(clip = "off")))
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
    theme_sleeper() +
    .sl_row_avatars(season, levels(d$user_name))
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
    ggplot2::theme(legend.position = "top", legend.justification = "left") +
    .sl_row_avatars(season, levels(d$user_name))
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
    theme_sleeper() +
    .sl_row_avatars(season, levels(d$user_name))
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
    # Avatar as each manager's marker; the dot shows through where none loads.
    .sl_scatter_avatars(season, d, "points", "pa") +
    ggrepel::geom_text_repel(ggplot2::aes(label = paste0(user_name, " (", wins, "W)")),
                             size = 3, colour = "grey25", point.padding = 10) +
    ggplot2::scale_colour_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_size(range = c(3, 9)) +
    ggplot2::labs(title = "Points For vs Points Against",
                  subtitle = "Lower-right beats up the league; upper-left gets snakebit  ·  dot size = wins",
                  x = "Points For", y = "Points Against", caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4))
}

#' All-play standings chart
#'
#' Bars = all-play win% (what your record would be if you played everyone every
#' week), ordered by all-play rank. Each bar is annotated with the actual finish
#' and the rank gap, and coloured by whether the real standing beat all-play
#' merit (the schedule helped) or fell short of it (the schedule hurt).
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_allplay <- function(season) {
  d <- sl_allplay(season) %>%
    dplyr::mutate(
      user_name = fct_reorder(user_name, allplay_pct),
      helped = dplyr::case_when(rank_delta > 0 ~ "schedule helped",
                                rank_delta < 0 ~ "schedule hurt",
                                TRUE ~ "as deserved"),
      lbl = sprintf("%.0f%%  ·  finished %d (%s)", allplay_pct * 100,
                    final_position,
                    ifelse(rank_delta == 0, "even",
                           sprintf("%+d", rank_delta))))
  ggplot2::ggplot(d, ggplot2::aes(allplay_pct, user_name)) +
    ggplot2::geom_col(ggplot2::aes(fill = helped), width = 0.72) +
    ggplot2::geom_text(ggplot2::aes(label = lbl), hjust = -0.03, size = 3,
                       colour = "grey20") +
    ggplot2::scale_fill_manual(
      values = c("schedule helped" = "#2ca02c", "schedule hurt" = "#d62728",
                 "as deserved" = "#9aa0a6"), name = NULL) +
    ggplot2::scale_x_continuous(labels = scales::percent,
                                expand = ggplot2::expansion(c(0, 0.38)), limits = c(0, 1)) +
    ggplot2::labs(title = "All-Play Standings",
                  subtitle = "If everyone played everyone every week  ·  colour = did the real schedule flatter or rob them",
                  x = "All-Play Win %", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left") +
    .sl_row_avatars(season, levels(d$user_name))
}

#' Power ranking chart
#'
#' The composite power score as a diverging bar around the league average (0):
#' z-scored blend of scoring, all-play quality, recent form and coaching. Podium
#' medals on the top three.
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_power_rank <- function(season) {
  d <- sl_power_rank(season) %>%
    dplyr::mutate(user_name = fct_reorder(user_name, power))
  x0 <- min(d$power) - diff(range(d$power)) * 0.04
  ggplot2::ggplot(d, ggplot2::aes(power, user_name, fill = power > 0)) +
    ggplot2::geom_col(width = 0.72, show.legend = FALSE) +
    ggplot2::geom_vline(xintercept = 0, colour = "grey70") +
    .sl_medals(d, "power_rank", x0) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%+.2f", power),
                                    hjust = ifelse(power > 0, -0.25, 1.25)),
                       size = 3, colour = "grey25") +
    ggplot2::scale_fill_manual(values = c(`TRUE` = "#2c7fb8", `FALSE` = "#c0563f")) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0.16, 0.14))) +
    ggplot2::labs(title = "Power Rankings",
                  subtitle = "Composite of points, all-play win%, recent form and lineup efficiency  ·  0 = league average",
                  x = "Power Score (standardised)", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    .sl_row_avatars(season, levels(d$user_name))
}

#' Manager tendencies chart
#'
#' The manager-identity quadrant: activity (roster moves per week) against lineup
#' IQ (how close to the optimal lineup they set), with bubble size = trades.
#' Splits the league into active/passive and sharp/loose managers.
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_manager_profile <- function(season) {
  d <- sl_manager_profile(season)
  mx <- stats::median(d$moves_per_wk); my <- stats::median(d$lineup_iq)
  ggplot2::ggplot(d, ggplot2::aes(moves_per_wk, lineup_iq)) +
    ggplot2::geom_vline(xintercept = mx, linetype = "dashed", colour = "grey78") +
    ggplot2::geom_hline(yintercept = my, linetype = "dashed", colour = "grey78") +
    ggplot2::geom_point(ggplot2::aes(colour = user_name, size = trades),
                        alpha = 0.85, show.legend = FALSE) +
    # Avatar as each manager's marker; the dot shows through where none loads.
    .sl_scatter_avatars(season, d, "moves_per_wk", "lineup_iq") +
    ggrepel::geom_text_repel(ggplot2::aes(label = user_name), size = 3,
                             colour = "grey25", point.padding = 6) +
    ggplot2::scale_colour_manual(values = sl_palette(d$user_name)) +
    ggplot2::scale_size(range = c(3, 10)) +
    ggplot2::labs(title = "Manager Tendencies",
                  subtitle = "Right = works the wire  ·  up = sets a sharp lineup  ·  bubble = trades made",
                  x = "Roster Moves per Week", y = "Lineup IQ (% of optimal)",
                  caption = .sl_cap(season)) +
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

# --- Weekly-standings & transaction charts (ported from ddbmFF.R) ----------

#' Weekly table-position bump chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_table_position <- function(season) {
  d <- sl_table_position(season)
  last <- d %>% dplyr::filter(week == max(week))
  ord <- last %>% dplyr::arrange(table_position) %>% dplyr::pull(user_name)
  d <- d %>% dplyr::mutate(user_name = factor(user_name, levels = ord))
  end_lab <- last %>% dplyr::mutate(user_name = factor(user_name, levels = ord),
                                    lbl = paste0(user_name, " (", wins, "-", losses, ")"))
  nteams <- nrow(last)
  playoff <- if (nteams >= 8) nteams / 2 else NA_real_
  p <- ggplot2::ggplot(d, ggplot2::aes(week, table_position, colour = user_name,
                                       group = user_name))
  if (!is.na(playoff)) p <- p +
    ggplot2::annotate("rect", xmin = -Inf, xmax = Inf, ymin = 0.5, ymax = playoff + 0.5,
                      fill = "#2f9e44", alpha = 0.06)
  p +
    ggplot2::geom_line(linewidth = 1.2, alpha = 0.85) +
    ggplot2::geom_point(size = 2.6) +
    ggrepel::geom_text_repel(data = end_lab, ggplot2::aes(label = lbl),
                             nudge_x = 0.35, hjust = 0, direction = "y", size = 3,
                             segment.colour = "grey80", show.legend = FALSE) +
    ggplot2::scale_y_reverse(breaks = seq_len(max(d$table_position))) +
    ggplot2::scale_x_continuous(breaks = sort(unique(d$week)),
                                expand = ggplot2::expansion(c(0.03, 0.28))) +
    ggplot2::scale_colour_manual(values = sl_palette(as.character(d$user_name)), guide = "none") +
    ggplot2::labs(title = "Table-Position Trajectory",
                  subtitle = if (!is.na(playoff))
                    "Standing after each week  ·  1 = top  ·  green band = playoff spots"
                    else "Standing after each week  ·  1 = top",
                  x = "Week", y = "Table Position", caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4))
}

#' Weekly points stacked-by-week bar chart
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_team_points <- function(season) {
  tot <- season$team_wk %>% dplyr::group_by(user_name) %>%
    dplyr::summarise(total = sum(points), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(total))
  d <- season$team_wk %>%
    dplyr::mutate(user_name = factor(user_name, levels = tot$user_name),
                  week = factor(week, levels = sort(unique(week))))
  ramp <- grDevices::colorRampPalette(c("#1f6f8b", "#8ecae6"))(nlevels(d$week))
  ggplot2::ggplot(d, ggplot2::aes(points, user_name, fill = week)) +
    ggplot2::geom_col(width = 0.7, colour = "white", linewidth = 0.3) +
    ggplot2::geom_text(data = tot, ggplot2::aes(x = total, y = user_name,
                       label = round(total)), inherit.aes = FALSE,
                       hjust = -0.15, size = 3.2, fontface = "bold", colour = "grey25") +
    ggplot2::scale_fill_manual(values = ramp, name = "Week", guide =
                                 ggplot2::guide_legend(reverse = TRUE, ncol = 2)) +
    ggplot2::scale_y_discrete(limits = rev(tot$user_name)) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.12))) +
    ggplot2::labs(title = "Total Points by Team",
                  subtitle = "Season points, stacked by week  ·  bold = season total",
                  x = "Points", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper()
}

#' Average weekly position-points distribution (box + jitter)
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_position_box <- function(season) {
  d <- sl_roster(season)
  ggplot2::ggplot(d, ggplot2::aes(position, avg)) +
    ggplot2::geom_boxplot(width = 0.55, fill = "grey92", colour = "grey55",
                          outlier.shape = NA) +
    ggplot2::geom_jitter(ggplot2::aes(colour = user_name), width = 0.16, alpha = 0.8,
                         size = 2.4, show.legend = TRUE) +
    ggplot2::scale_colour_manual(values = sl_palette(d$user_name), name = "Team") +
    ggplot2::labs(title = "Average Weekly Position Points",
                  subtitle = "Each dot is a team's per-week average at a position  ·  spread = positional inequality",
                  x = NULL, y = "Average Points", caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4))
}

#' Average roster composition (starters vs bench slots by position)
#' @param season A [sleeper_season] object.
#' @return A ggplot.
#' @export
sl_plot_roster_counts <- function(season) {
  d <- sl_roster_counts(season) %>%
    dplyr::mutate(status = factor(status, levels = c("Bench", "Starters")))
  ggplot2::ggplot(d, ggplot2::aes(position, avg_count, fill = status)) +
    ggplot2::geom_col(width = 0.7) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f", avg_count)),
                       position = ggplot2::position_stack(vjust = 0.5),
                       size = 3, colour = "white", fontface = "bold") +
    ggplot2::scale_fill_manual(values = c(Starters = "#2f9e44", Bench = "#c3c9d0"),
                               name = NULL) +
    ggplot2::labs(title = "Average Roster Composition",
                  subtitle = "Mean roster slots per team each week, by position",
                  x = NULL, y = "Slots per Team-Week", caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(panel.grid.major.y = ggplot2::element_line(colour = "grey92", linewidth = 0.4),
                   panel.grid.major.x = ggplot2::element_blank(),
                   legend.position = "top", legend.justification = "left")
}

# Shared renderer for the trade/waiver performance charts: stacked player points
# by manager (each segment = one manager's stint), ranked by total, with the
# season total called out at the end of each bar.
.sl_plot_acq <- function(d, season, title, subtitle) {
  d <- d %>% dplyr::mutate(player_name = fct_reorder(player_name, total))
  totals <- d %>% dplyr::distinct(player_name, total)
  span <- max(totals$total)
  # One portrait per player row (a traded player appears under several managers,
  # so take the first -- it is the same player either way).
  faces <- d %>% dplyr::distinct(player_name, .keep_all = TRUE)
  lv <- levels(d$player_name)
  idx <- match(lv, as.character(faces$player_name))
  ggplot2::ggplot(d, ggplot2::aes(points, player_name, fill = user_name)) +
    ggplot2::geom_col(width = 0.72, colour = "white", linewidth = 0.3) +
    ggplot2::geom_text(ggplot2::aes(label = ifelse(points >= span * 0.06,
                                    paste0(round(points), " (", weeks, "w)"), "")),
                       position = ggplot2::position_stack(vjust = 0.5), size = 2.5,
                       colour = "grey15") +
    ggplot2::geom_text(data = totals, ggplot2::aes(x = total, y = player_name,
                       label = paste0(round(total))), inherit.aes = FALSE,
                       hjust = -0.2, size = 3, fontface = "bold", colour = "grey30") +
    ggplot2::scale_fill_manual(values = sl_palette(d$user_name), name = "Team") +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0.07, 0.12))) +
    ggplot2::labs(title = title, subtitle = subtitle,
                  x = "Points While Rostered", y = NULL, caption = .sl_cap(season)) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left",
                   legend.key.size = ggplot2::unit(0.9, "lines")) +
    .sl_identity_axis(lv, function(j, x) {
      if (is.na(idx[j])) return(NULL)
      sl_headshot_grob(faces$player_id[idx[j]], as.character(faces$position[idx[j]]),
                       size_mm = 5, x = x, just = "right")
    })
}

#' Traded-player performance chart
#' @param season A [sleeper_season] object.
#' @param top_n Keep the `top_n` highest-scoring traded players.
#' @return A ggplot.
#' @export
sl_plot_trade_performance <- function(season, top_n = 12) {
  d <- sl_trade_performance(season)
  keep <- d %>% dplyr::distinct(player_name, total) %>%
    dplyr::slice_max(total, n = top_n, with_ties = FALSE) %>% dplyr::pull(player_name)
  .sl_plot_acq(dplyr::filter(d, player_name %in% keep), season,
               "Traded Players: Value While Rostered",
               "Points each team got from players it acquired in trades  ·  segment = one manager's stint")
}

#' Waiver / free-agent pickup performance chart
#' @param season A [sleeper_season] object.
#' @param top_n Keep the `top_n` highest-scoring pickups.
#' @return A ggplot.
#' @export
sl_plot_waiver_performance <- function(season, top_n = 15) {
  d <- sl_waiver_performance(season)
  keep <- d %>% dplyr::distinct(player_name, total) %>%
    dplyr::slice_max(total, n = top_n, with_ties = FALSE) %>% dplyr::pull(player_name)
  .sl_plot_acq(dplyr::filter(d, player_name %in% keep), season,
               "Best Waiver & Free-Agent Pickups",
               "Points managers got from players added off waivers / FA")
}

# --- Playoff charts --------------------------------------------------------

#' Playoff bracket chart
#'
#' The whole bracket at a glance: rounds left to right, each matchup a pair of
#' rows with its score, the winner filled and the loser greyed. Pending matchups
#' (lineups not in yet) are drawn hollow.
#'
#' @param playoff A `sleeper_playoff` object (see [sl_playoff()]).
#' @return A ggplot.
#' @export
sl_plot_playoff_bracket <- function(playoff, seeds = NULL) {
  d <- playoff$results
  rounds <- unique(d$round_id)
  if (is.null(seeds)) seeds <- playoff$config$`_seeds`
  seed_of <- if (length(seeds))
    stats::setNames(names(seeds), unlist(seeds)) else character(0)

  # Lay each round out as evenly spaced matchup slots on a shared vertical span.
  mu <- d %>% dplyr::distinct(round_id, matchup_id) %>%
    dplyr::group_by(round_id) %>%
    dplyr::mutate(j = dplyr::row_number(), n = dplyr::n()) %>%
    dplyr::ungroup()
  span <- max(mu$n)
  mu <- mu %>% dplyr::mutate(rx = match(round_id, rounds),
                             cy = (j - 0.5) * span / n)

  d <- d %>%
    dplyr::left_join(dplyr::select(mu, matchup_id, rx, cy), by = "matchup_id") %>%
    dplyr::group_by(matchup_id) %>%
    dplyr::mutate(side = dplyr::row_number(), sides = dplyr::n()) %>%
    dplyr::ungroup() %>%
    dplyr::mutate(
      y = dplyr::if_else(sides == 1, cy, cy + dplyr::if_else(side == 1, -0.19, 0.19)),
      sd = unname(seed_of[team]),
      lbl = paste0(ifelse(is.na(sd), "", paste0(sd, "  ")), team,
                   ifelse(is.na(points), "   \U2013", paste0("   ", sprintf("%.1f", points)))),
      fill = dplyr::case_when(result == "W" ~ "win", result == "BYE" ~ "bye",
                              result == "PENDING" ~ "pending", TRUE ~ "loss"))

  # Connectors: a winner (or a bye team) flows into the next matchup that holds
  # it, so trace each advancing team forward and elbow the line across.
  adv <- d %>% dplyr::filter(result %in% c("W", "BYE"), !is.na(team))
  seg <- purrr::map_dfr(seq_len(nrow(adv)), function(i) {
    a <- adv[i, ]
    nxt <- d %>% dplyr::filter(team == a$team, rx > a$rx) %>%
      dplyr::slice_min(rx, n = 1, with_ties = FALSE)
    if (!nrow(nxt)) return(NULL)
    tibble(x = a$rx + 0.44, y = a$cy, xend = nxt$rx - 0.44, yend = nxt$y)
  })

  champ <- playoff$champion
  p <- ggplot2::ggplot(d, ggplot2::aes(rx, y))
  if (nrow(seg)) p <- p +
    ggplot2::geom_curve(data = seg,
      ggplot2::aes(x = x, y = y, xend = xend, yend = yend), inherit.aes = FALSE,
      curvature = 0, colour = "grey82", linewidth = 0.5)
  p +
    ggplot2::geom_tile(ggplot2::aes(fill = fill), width = 0.86, height = 0.3,
                       colour = "white", linewidth = 0.9) +
    ggplot2::geom_text(ggplot2::aes(label = lbl,
                       fontface = ifelse(result == "W", "bold", "plain")),
                       size = 3, colour = "grey15") +
    ggplot2::scale_fill_manual(
      values = c(win = "#a5d6a7", loss = "#e6e8ea", bye = "#ffe0a3",
                 pending = "#f4f6f8"),
      breaks = c("win", "loss", "bye", "pending"),
      labels = c(win = "won", loss = "lost", bye = "bye (seeded)",
                 pending = "not yet played"), name = NULL) +
    ggplot2::scale_x_continuous(breaks = seq_along(rounds),
                                labels = unique(d$round), position = "top",
                                expand = ggplot2::expansion(c(0.05, 0.05))) +
    ggplot2::scale_y_reverse(expand = ggplot2::expansion(c(0.06, 0.06))) +
    ggplot2::labs(
      title = paste0(playoff$name, " \U00B7 ", playoff$season, " Bracket"),
      subtitle = if (!is.null(champ))
        paste0("Champion: ", champ, " \U0001F451   \U00B7   every score computed from the submitted lineups under the league's own scoring chart")
        else "Every score computed from the submitted lineups under the league's own scoring chart",
      x = NULL, y = NULL) +
    theme_sleeper() +
    ggplot2::theme(
      panel.grid = ggplot2::element_blank(),
      axis.text.y = ggplot2::element_blank(),
      axis.text.x = ggplot2::element_text(face = "bold", colour = "grey30", size = 11),
      legend.position = "bottom", legend.justification = "left",
      plot.subtitle = ggplot2::element_text(family = "Segoe UI Emoji", colour = "grey40"))
}

#' Career playoff record chart
#'
#' Postseason résumé per manager: playoff win %, sized by games played, with
#' titles marked. Managers who never made a bracket are omitted.
#'
#' @param playoffs A named list of `sleeper_playoff` objects ([sl_load_playoffs()]).
#' @param scope See [sl_scope()].
#' @return A ggplot.
#' @export
sl_plot_playoff_stats <- function(playoffs, scope = "title") {
  d <- sl_playoff_stats(playoffs, scope) %>%
    dplyr::filter(games > 0) %>%
    dplyr::mutate(user_name = fct_reorder(user_name, win_pct),
                  lbl = paste0(wins, "-", losses, "  ", sprintf("%.0f%%", win_pct),
                               ifelse(titles > 0, paste0("  ", strrep("\U0001F451", titles)), "")))
  ggplot2::ggplot(d, ggplot2::aes(win_pct, user_name)) +
    ggplot2::geom_col(ggplot2::aes(fill = titles > 0), width = 0.72, show.legend = FALSE) +
    ggplot2::geom_text(ggplot2::aes(label = lbl), hjust = -0.03, size = 3.2,
                       colour = "grey20", family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = c(`TRUE` = "#f1c40f", `FALSE` = "#9fb8c8")) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0, 0.34)), limits = c(0, 100)) +
    ggplot2::labs(title = "Career Playoff Record",
                  subtitle = paste0("Win % across ", length(playoffs),
                                    " postseasons  \U00B7  ",
                                    if (scope == "title") "championship path only"
                                    else paste0("scope: ", scope),
                                    "  \U00B7  gold = has won a title  \U00B7  \U0001F451 per title"),
                  x = "Playoff Win %", y = NULL) +
    theme_sleeper() +
    ggplot2::theme(plot.subtitle = ggplot2::element_text(family = "Segoe UI Emoji",
                                                         colour = "grey40"))
}

#' Career playoff scoring leaders chart
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param n How many players to show.
#' @param scope See [sl_scope()].
#' @return A ggplot.
#' @export
sl_plot_playoff_players <- function(playoffs, n = 15, scope = "title") {
  d <- sl_playoff_players(playoffs, scope) %>%
    dplyr::slice_max(points, n = n, with_ties = FALSE) %>%
    dplyr::mutate(label = paste0(player_name, "  \U00B7  ", position),
                  label = fct_reorder(label, points))
  lv <- levels(d$label)
  idx <- match(lv, as.character(d$label))
  ggplot2::ggplot(d, ggplot2::aes(points, label, fill = position)) +
    ggplot2::geom_col(width = 0.72) +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.0f  (%.1f ppg)%s", points, ppg,
                       ifelse(rings > 0, paste0("  ", strrep("\U0001F48D", rings)), ""))),
                       hjust = -0.03, size = 3, colour = "grey20",
                       family = "Segoe UI Emoji") +
    ggplot2::scale_fill_manual(values = .sl_pos_colors, name = NULL) +
    ggplot2::scale_x_continuous(expand = ggplot2::expansion(c(0.06, 0.34))) +
    ggplot2::labs(title = "Best Playoff Players (All Time)",
                  subtitle = paste0("Total points scored in the postseason  \U00B7  ",
                                    if (scope == "title") "championship path only"
                                    else paste0("scope: ", scope),
                                    "  \U00B7  \U0001F48D per title"),
                  x = "Playoff Points", y = NULL) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left",
                   plot.subtitle = ggplot2::element_text(family = "Segoe UI Emoji",
                                                         colour = "grey40")) +
    .sl_identity_axis(lv, function(j, x) {
      sl_headshot_grob(d$player_id[idx[j]], as.character(d$position[idx[j]]),
                       size_mm = 5, x = x, just = "right")
    })
}

#' Clutch chart: playoff scoring vs regular-season scoring
#' @param seasons Named list of [sleeper_season] objects.
#' @param playoffs Named list of `sleeper_playoff` objects.
#' @param scope See [sl_scope()].
#' @return A ggplot.
#' @export
sl_plot_clutch <- function(seasons, playoffs, scope = "title") {
  d <- sl_clutch(seasons, playoffs, scope) %>%
    dplyr::mutate(user_name = fct_reorder(user_name, clutch))
  ggplot2::ggplot(d, ggplot2::aes(y = user_name)) +
    ggplot2::geom_vline(xintercept = 0, colour = "grey75", linetype = "dashed") +
    ggplot2::geom_segment(ggplot2::aes(x = reg_ppg, xend = po_ppg, yend = user_name,
                                       colour = clutch > 0), linewidth = 1.3, alpha = 0.5) +
    ggplot2::geom_point(ggplot2::aes(x = reg_ppg), colour = "grey65", size = 3.4) +
    ggplot2::geom_point(ggplot2::aes(x = po_ppg, colour = clutch > 0), size = 4.6) +
    ggplot2::geom_text(ggplot2::aes(x = po_ppg, label = sprintf("%+.1f", clutch),
                       colour = clutch > 0, hjust = ifelse(clutch > 0, -0.35, 1.35)),
                       size = 3, fontface = "bold", show.legend = FALSE) +
    ggplot2::scale_colour_manual(values = c(`TRUE` = "#2ca02c", `FALSE` = "#d62728"),
                                 labels = c(`TRUE` = "raises their game",
                                            `FALSE` = "shrinks"), name = NULL) +
    ggplot2::labs(title = "Clutch: Playoff vs Regular-Season Scoring",
                  subtitle = "Grey dot = regular-season PPG; coloured = playoff PPG",
                  x = "Points per Game", y = NULL) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left")
}

#' Player-by-player breakdown of one playoff matchup
#'
#' The receipts for a result: both submitted lineups side by side, each starter's
#' points under the league's scoring chart.
#'
#' @param playoff A `sleeper_playoff` object.
#' @param matchup_id Which matchup to show (e.g. `"R1M1"`).
#' @return A ggplot.
#' @export
sl_plot_playoff_matchup <- function(playoff, matchup_id) {
  d <- playoff$players %>% dplyr::filter(matchup_id == !!matchup_id)
  if (!nrow(d)) stop("No scored players for matchup '", matchup_id,
                     "' (is it still pending?)", call. = FALSE)
  d <- d %>% dplyr::group_by(team, player_id, player_name, position) %>%
    dplyr::summarise(points = sum(points), .groups = "drop")
  tm <- unique(d$team)
  tot <- d %>% dplyr::group_by(team) %>%
    dplyr::summarise(total = sum(points), .groups = "drop")
  # Mirror the left-hand team so the two lineups face each other.
  d <- d %>% dplyr::mutate(
    signed = ifelse(team == tm[1], -points, points),
    lbl = paste0(player_name, " (", position, ")"),
    yfac = stats::reorder(lbl, abs(signed)))
  hdr <- paste0(tot$team, ": ", sprintf("%.1f", tot$total), collapse = "   vs   ")
  lv <- levels(d$yfac)
  idx <- match(lv, as.character(d$yfac))
  ggplot2::ggplot(d, ggplot2::aes(signed, yfac, fill = team)) +
    ggplot2::geom_col(width = 0.72) +
    ggplot2::geom_vline(xintercept = 0, colour = "grey70") +
    ggplot2::geom_text(ggplot2::aes(label = sprintf("%.1f", points),
                       hjust = ifelse(signed < 0, 1.15, -0.15)),
                       size = 2.9, colour = "grey25") +
    ggplot2::scale_fill_manual(values = sl_palette(d$team), name = NULL) +
    ggplot2::scale_x_continuous(labels = function(x) abs(x),
                                expand = ggplot2::expansion(c(0.27, 0.16))) +
    ggplot2::labs(title = paste0("Matchup ", matchup_id),
                  subtitle = hdr, x = "Points", y = NULL) +
    theme_sleeper() +
    ggplot2::theme(legend.position = "top", legend.justification = "left") +
    .sl_identity_axis(lv, function(j, x) {
      sl_headshot_grob(d$player_id[idx[j]], as.character(d$position[idx[j]]),
                       size_mm = 5, x = x, just = "right")
    })
}
