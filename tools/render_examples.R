# Regenerate every analytics graphic + summary from the R package.
#
#   Rscript tools/render_examples.R [league_id]
#
# Champions come from the stored playoff brackets (see playoffs/README.md), not
# Sleeper's winners_bracket -- so crowns, titles and champion stars are correct.
# Output: results/examples/r/ (gitignored build artifacts).

suppressWarnings(suppressMessages({
  pkgload::load_all("R/sleepermetrics", quiet = TRUE)
  library(ggplot2)
}))

args <- commandArgs(trailingOnly = TRUE)
league <- if (length(args)) args[[1]] else "1252770181306929152"
OUT <- "results/examples/r"
dir.create(OUT, recursive = TRUE, showWarnings = FALSE)

save_plot <- function(name, p, w = 10, h = 6.2) {
  ggsave(file.path(OUT, paste0(name, ".png")), p, width = w, height = h,
         dpi = 130, bg = "white")
  cat("  ", name, "\n", sep = "")
}

cat("Loading league...\n")
ss <- sl_apply_playoffs(sl_seasons(league), "playoffs")
latest <- ss[[length(ss)]]
pos <- sl_load_playoffs("playoffs")

cat("Season charts (", latest$season, ")\n", sep = "")
save_plot("standings",          sl_plot_standings(latest))
save_plot("luck",               sl_plot_luck(latest))
save_plot("efficiency",         sl_plot_efficiency(latest))
save_plot("consistency",        sl_plot_consistency(latest))
save_plot("pf_pa",              sl_plot_pf_pa(latest))
save_plot("table_position",     sl_plot_table_position(latest))
save_plot("team_points",        sl_plot_team_points(latest), w = 11)
save_plot("position_scoring",   sl_plot_position_scoring(latest))
save_plot("roster_heatmap",     sl_plot_roster_heatmap(latest))
save_plot("starter_bench",      sl_plot_starter_bench(latest), w = 14)
save_plot("position_box",       sl_plot_position_box(latest))
save_plot("roster_counts",      sl_plot_roster_counts(latest))
save_plot("trade_performance",  sl_plot_trade_performance(latest), w = 11)
save_plot("waiver_performance", sl_plot_waiver_performance(latest), w = 11, h = 7)

cat("Career charts\n")
save_plot("career",     sl_plot_career(ss))
save_plot("trajectory", sl_plot_trajectory(ss))

cat("Playoff charts\n")
for (s in names(pos)) {
  n <- dplyr::n_distinct(pos[[s]]$results$matchup_id)
  save_plot(paste0("bracket_", s), sl_plot_playoff_bracket(pos[[s]]),
            w = 12.5, h = max(5.5, 1.1 * n))
}
save_plot("playoff_stats", sl_plot_playoff_stats(pos))
fin <- pos[[length(pos)]]
save_plot("playoff_final", sl_plot_playoff_matchup(fin, fin$config$final), h = 6.4)

cat("Summaries + metric tables\n")
writeLines(c(sl_summary_season(latest), "", sl_summary_career(ss)),
           file.path(OUT, "summaries.md"))
write.csv(sl_playoff_stats(pos), file.path(OUT, "playoff_stats.csv"), row.names = FALSE)
write.csv(sl_career(ss), file.path(OUT, "career.csv"), row.names = FALSE)
cat("  summaries.md, playoff_stats.csv, career.csv\n")

cat("\nchampions (from the brackets):\n")
for (s in names(pos)) cat("  ", s, ": ", pos[[s]]$champion, "\n", sep = "")
cat("\nDone -> ", OUT, "\n", sep = "")
