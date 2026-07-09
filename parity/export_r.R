# Export a canonical JSON of metrics for a league (R implementation).
# Run from repo base:
#   Rscript parity/export_r.R <league_id> parity/out_r.json
# Emits the identical structure to parity/export_py.py so verify.py can assert
# the two implementations mirror each other.

suppressWarnings(suppressMessages({
  pkgload::load_all("R/sleepermetrics", quiet = TRUE)
  library(dplyr); library(jsonlite)
}))

args <- commandArgs(trailingOnly = TRUE)
league <- if (length(args) >= 1) args[[1]] else "1252770181306929152"
out_path <- if (length(args) >= 2) args[[2]] else "parity/out_r.json"

# Round numeric columns to 2dp and select/sort deterministically.
recs <- function(df, cols, sortcol) {
  df %>%
    dplyr::select(dplyr::all_of(cols)) %>%
    dplyr::arrange(.data[[sortcol]]) %>%
    dplyr::mutate(dplyr::across(dplyr::where(is.numeric), ~ round(.x, 2)))
}

ss <- sl_seasons(league)
latest <- ss[[length(ss)]]

out <- list(
  impl = "r",
  league = league,
  season = latest$season,
  standings = recs(sl_standings(latest),
                   c("user_name", "wins", "losses", "points", "final_position", "champion"),
                   "final_position"),
  luck = recs(sl_luck(latest), c("user_name", "wins", "exp_w", "luck"), "user_name"),
  efficiency = recs(sl_efficiency(latest), c("user_name", "eff", "bench"), "user_name"),
  consistency = recs(sl_consistency(latest), c("user_name", "sd"), "user_name"),
  high_scores = recs(sl_high_scores(latest), c("user_name", "highs"), "user_name"),
  week_stats = recs(sl_week_stats(latest), c("user_name", "points", "margin"), "user_name"),
  career = recs(sl_career(ss),
                c("user_name", "seasons", "wins", "losses", "win_pct", "titles"), "user_name"),
  position_scoring = recs(sl_position_scoring(latest), c("position", "points", "share"), "position"),
  roster = recs(sl_roster(latest),
                c("user_name", "position", "spots", "points", "avg"), "user_name"),
  starter_bench = recs(sl_starter_bench(latest),
                       c("user_name", "position", "status", "avg"), "user_name"),
  table_position = recs(sl_table_position(latest),
                        c("week", "user_name", "table_position", "wins"), "week"),
  roster_counts = recs(sl_roster_counts(latest),
                       c("position", "status", "avg_count"), "position"),
  trade_performance = recs(sl_trade_performance(latest),
                           c("player_name", "user_name", "weeks", "points", "avg", "total"),
                           "player_name"),
  waiver_performance = recs(sl_waiver_performance(latest),
                            c("player_name", "user_name", "weeks", "points", "avg", "total"),
                            "player_name"),
  summary_season = sl_summary_season(latest),
  summary_career = sl_summary_career(ss),
  summary_week = sl_summary_week(latest)
)

writeLines(toJSON(out, auto_unbox = TRUE, pretty = TRUE, digits = 2, na = "null"),
           out_path)
cat(sprintf("wrote %s (season %s, %d teams)\n",
            out_path, latest$season, nrow(out$standings)))
