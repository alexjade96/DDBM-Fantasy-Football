# Self-contained season report (mirrors python/sleepermetrics/report.py) -----
#
# Bundles a league's whole season -- narrative, headline numbers, a per-manager
# breakdown, and every chart -- into ONE standalone HTML file with the charts
# embedded as base64 PNGs. No external assets, so it can be emailed, dropped in a
# drive, or opened offline. The dashboards are for exploring; the report is the
# thing you keep and share. The CSS/template are byte-identical to the Python
# port so both instances produce a visually matching report.

# A ggplot -> inline base64 PNG data URI. Best-effort: a chart that errors is
# skipped (empty string) so one bad panel never sinks the whole report.
.sl_fig_uri <- function(plot, width = 1100, height = 620, dpi = 112) {
  tmp <- tempfile(fileext = ".png")
  on.exit(unlink(tmp), add = TRUE)
  tryCatch({
    ggplot2::ggsave(tmp, plot, width = width / dpi, height = height / dpi,
                    dpi = dpi, bg = "white",
                    device = if (requireNamespace("ragg", quietly = TRUE))
                      ragg::agg_png else "png")
    base64enc::dataURI(file = tmp, mime = "image/png")
  }, error = function(e) "")
}

# Render a chart-producing call to a <figure>, or "" if it fails/has no data.
.sl_fig <- function(expr, desc = "") {
  plot <- tryCatch(force(expr), error = function(e) NULL)
  if (is.null(plot)) return("")
  uri <- .sl_fig_uri(plot)
  if (!nzchar(uri)) return("")
  cap <- if (nzchar(desc)) sprintf("<figcaption>%s</figcaption>", .sl_esc(desc)) else ""
  sprintf('<figure><img src="%s" alt="%s">%s</figure>', uri, .sl_esc(desc), cap)
}

.sl_esc <- function(x) {
  x <- as.character(x)
  x <- gsub("&", "&amp;", x, fixed = TRUE)
  x <- gsub("<", "&lt;", x, fixed = TRUE)
  gsub(">", "&gt;", x, fixed = TRUE)
}

# The summaries' small markdown subset (- bullets, **bold**) to safe HTML.
.sl_report_md <- function(text) {
  lines <- strsplit(text %||% "", "\n", fixed = TRUE)[[1]]
  out <- character(0); ul <- FALSE
  for (ln in lines) {
    ln <- .sl_esc(ln)
    ln <- gsub("\\*\\*(.+?)\\*\\*", "<strong>\\1</strong>", ln)
    if (startsWith(ln, "### ")) next                      # report supplies its own heading
    if (startsWith(ln, "- ")) {
      if (!ul) { out <- c(out, "<ul>"); ul <- TRUE }
      out <- c(out, sprintf("<li>%s</li>", substring(ln, 3)))
    } else if (nzchar(trimws(ln))) {
      if (ul) { out <- c(out, "</ul>"); ul <- FALSE }
      out <- c(out, sprintf("<p>%s</p>", ln))
    }
  }
  if (ul) out <- c(out, "</ul>")
  paste(out, collapse = "\n")
}

.sl_report_tiles <- function(season) {
  st <- season$standings
  lead <- st[order(st$final_position), ][1, ]
  champ <- st$user_name[st$champion]
  champ_name <- if (length(champ)) champ[1] else lead$user_name
  tw <- season$team_wk
  top <- tw[which.max(tw$points), ]
  ap <- sl_allplay(season)[1, ]
  lk <- sl_luck(season)[1, ]
  eff <- sl_efficiency(season)[1, ]
  most_pts <- st[order(st$points, decreasing = TRUE), ][1, ]
  tiles <- list(
    c("Champion", champ_name, sprintf("%d-%d at the top", lead$wins, lead$losses)),
    c("Most points", sprintf("%.0f", most_pts$points), most_pts$user_name),
    c("Highest week", sprintf("%.1f", top$points),
      sprintf("%s \U00B7 wk %d", top$user_name, top$week)),
    c("Best all-play", sprintf("%.0f%%", ap$allplay_pct * 100),
      sprintf("%s \U00B7 schedule-proof", ap$user_name)),
    c("Luckiest", sprintf("%+.1f", lk$luck), sprintf("%s \U00B7 wins vs merit", lk$user_name)),
    c("Sharpest lineup", sprintf("%.0f%%", eff$eff), sprintf("%s \U00B7 of optimal", eff$user_name)))
  paste(vapply(tiles, function(t) sprintf(
    "<div class='tile'><span class='k'>%s</span><span class='v'>%s</span><span class='s'>%s</span></div>",
    .sl_esc(t[1]), .sl_esc(t[2]), .sl_esc(t[3])), character(1)), collapse = "")
}

.sl_report_team_table <- function(season) {
  d <- season$standings %>%
    dplyr::select(user_name, wins, losses, points, pa, final_position) %>%
    dplyr::left_join(dplyr::select(sl_allplay(season), user_name, allplay_pct, rank_delta),
                     by = "user_name") %>%
    dplyr::left_join(dplyr::select(sl_power_rank(season), user_name, power_rank),
                     by = "user_name") %>%
    dplyr::left_join(dplyr::select(sl_manager_profile(season), user_name, moves,
                                   trades, lineup_iq), by = "user_name") %>%
    dplyr::arrange(final_position)
  rows <- vapply(seq_len(nrow(d)), function(i) {
    r <- d[i, ]
    sprintf(paste0(
      "<tr><td class='rank'>%d</td><td class='name'>%s</td><td>%d-%d</td>",
      "<td class='n'>%.0f</td><td class='n'>%.0f</td><td class='n'>%.0f%%</td>",
      "<td class='n'>#%d</td><td class='n'>%.0f%%</td><td class='n'>%d/%d</td></tr>"),
      r$final_position, .sl_esc(r$user_name), r$wins, r$losses, r$points, r$pa,
      r$allplay_pct * 100, r$power_rank, r$lineup_iq, r$moves, r$trades)
  }, character(1))
  paste0(
    "<table class='teams'><thead><tr>",
    "<th>#</th><th>Manager</th><th>Record</th><th class='n'>PF</th>",
    "<th class='n'>PA</th><th class='n'>All-play</th><th class='n'>Power</th>",
    "<th class='n'>Lineup IQ</th><th class='n'>Moves/Trades</th>",
    "</tr></thead><tbody>", paste(rows, collapse = ""), "</tbody></table>")
}

.sl_report_section <- function(title, blurb, figs) {
  body <- paste(figs[nzchar(figs)], collapse = "")
  if (!nzchar(body)) return("")
  sub <- if (nzchar(blurb)) sprintf("<p class='blurb'>%s</p>", .sl_esc(blurb)) else ""
  sprintf("<section><h2>%s</h2>%s<div class='grid'>%s</div></section>",
          .sl_esc(title), sub, body)
}

#' Write a standalone HTML season report
#'
#' Bundles the season's narrative, headline numbers, a per-manager table and
#' every chart into one self-contained HTML file (charts embedded as base64
#' PNGs -- no external assets). The shareable counterpart to the dashboard.
#'
#' @param season A [sleeper_season] object (the season to report on).
#' @param file Output path (`.html`).
#' @param seasons Optional full league chain ([sl_seasons()]) for career context.
#' @param playoffs Optional stored brackets ([sl_load_playoffs()]) for the
#'   postseason section.
#' @return The output path, invisibly.
#' @seealso [sl_dashboard()], [sl_summary_season()]
#' @export
sl_season_report <- function(season, file, seasons = NULL, playoffs = NULL) {
  if (!requireNamespace("base64enc", quietly = TRUE)) {
    stop("sl_season_report needs the 'base64enc' package.")
  }
  sections <- c(
    .sl_report_section("The standings", "Where the season finished, and how deserved it was.", c(
      .sl_fig(sl_plot_standings(season), "Final standings"),
      .sl_fig(sl_plot_power_rank(season), "Composite power ranking"),
      .sl_fig(sl_plot_allplay(season), "All-play: standings independent of schedule"),
      .sl_fig(sl_plot_luck(season), "Luck: actual vs all-play expected wins"))),
    .sl_report_section("Coaching & scoring", "Who set the best lineups and who ran hot or cold.", c(
      .sl_fig(sl_plot_efficiency(season), "Lineup efficiency"),
      .sl_fig(sl_plot_consistency(season), "Weekly score distributions"),
      .sl_fig(sl_plot_pf_pa(season), "Points for vs against"))),
    .sl_report_section("The weekly story", "How the table and the scoring moved week to week.", c(
      .sl_fig(sl_plot_table_position(season), "Weekly table position"),
      .sl_fig(sl_plot_team_points(season), "Weekly team points"))),
    .sl_report_section("Rosters & positions", "Where each team's points came from.", c(
      .sl_fig(sl_plot_position_scoring(season), "Scoring by position"),
      .sl_fig(sl_plot_roster_heatmap(season), "Roster points heatmap"),
      .sl_fig(sl_plot_starter_bench(season), "Starters vs bench"))),
    .sl_report_section("Managers & transactions", "Roster-building style, and what the moves returned.", c(
      .sl_fig(sl_plot_manager_profile(season), "Manager tendencies"),
      if (nrow(sl_trade_performance(season)))
        .sl_fig(sl_plot_trade_performance(season), "Traded-player value") else "",
      if (nrow(sl_waiver_performance(season)))
        .sl_fig(sl_plot_waiver_performance(season), "Waiver / FA value") else "")))

  if (!is.null(playoffs) && !is.null(playoffs[[season$season]])) {
    p <- playoffs[[season$season]]
    sections <- c(sections, .sl_report_section(
      "The postseason", "How the bracket actually played out.", c(
        .sl_fig(sl_plot_playoff_bracket(p), "Playoff bracket"),
        .sl_fig(sl_plot_playoff_players(playoffs), "Best playoff players (all time)"))))
  }
  if (!is.null(seasons) && length(seasons) > 1) {
    sections <- c(sections, .sl_report_section(
      "Career context", "This season against the league's whole history.", c(
        .sl_fig(sl_plot_career(seasons), "Career standings"),
        .sl_fig(sl_plot_trajectory(seasons), "Finish trajectory by season"))))
  }

  doc <- sprintf(.sl_report_template,
    sprintf("%s \U00B7 %s Season Report", .sl_esc(season$name), season$season),
    .SL_REPORT_CSS, .sl_esc(season$name), season$season, as.character(Sys.Date()),
    .sl_report_tiles(season), .sl_report_md(sl_summary_season(season)),
    .sl_report_team_table(season), paste(sections[nzchar(sections)], collapse = ""))
  writeLines(doc, file, useBytes = TRUE)
  invisible(file)
}

# CSS + template: byte-identical to python/sleepermetrics/report.py so the two
# instances emit a visually matching report. %s order in the template:
# title, css, league, season, generated, tiles, narrative, team_table, sections.
.SL_REPORT_CSS <- "
:root{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#5b616e;--faint:#9aa0a6;
 --line:#e6e8eb;--accent:#2c7fb8;--gold:#e6b400;--radius:14px}
@media (prefers-color-scheme:dark){:root{--bg:#111316;--card:#1a1d21;--ink:#e9ebee;
 --muted:#a7adb8;--faint:#6b7280;--line:#2a2e35;--accent:#5aa9de;--gold:#f1c40f}}
:root[data-theme=dark]{--bg:#111316;--card:#1a1d21;--ink:#e9ebee;--muted:#a7adb8;
 --faint:#6b7280;--line:#2a2e35;--accent:#5aa9de;--gold:#f1c40f}
:root[data-theme=light]{--bg:#f6f7f9;--card:#fff;--ink:#1a1d21;--muted:#5b616e;
 --faint:#9aa0a6;--line:#e6e8eb;--accent:#2c7fb8;--gold:#e6b400}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:16px/1.55 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:clamp(20px,4vw,48px)}
header.top{display:flex;justify-content:space-between;align-items:flex-end;
 gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:18px}
header.top .eyebrow{text-transform:uppercase;letter-spacing:.14em;font-size:12px;
 color:var(--accent);font-weight:700}
header.top h1{margin:.1em 0 0;font-size:clamp(30px,5vw,46px);line-height:1.02;
 letter-spacing:-.02em;text-wrap:balance}
header.top .gen{color:var(--faint);font-size:13px;text-align:right}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));
 gap:14px;margin:26px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 padding:16px 18px;display:flex;flex-direction:column;gap:2px}
.tile .k{text-transform:uppercase;letter-spacing:.06em;font-size:11px;
 color:var(--faint);font-weight:700}
.tile .v{font-size:30px;font-weight:750;letter-spacing:-.02em;
 font-variant-numeric:tabular-nums;line-height:1.1}
.tile:first-child .v{color:var(--gold)}
.tile .s{font-size:12.5px;color:var(--muted)}
.lead{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);
 border-radius:var(--radius);padding:6px 22px;margin:24px 0}
.lead ul{margin:12px 0;padding-left:20px}.lead li{margin:5px 0}
.lead strong{color:var(--ink)}
h2{font-size:22px;letter-spacing:-.01em;margin:40px 0 2px;
 padding-top:22px;border-top:1px solid var(--line)}
.blurb{color:var(--muted);margin:.2em 0 14px;font-size:14.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(430px,1fr));gap:20px}
figure{margin:0;background:var(--card);border:1px solid var(--line);
 border-radius:var(--radius);padding:12px;overflow:hidden}
figure img{width:100%;height:auto;display:block;border-radius:8px}
figcaption{color:var(--faint);font-size:12px;margin-top:8px;padding:0 4px}
.teamsec{overflow-x:auto}
table.teams{width:100%;border-collapse:collapse;font-size:14px;
 background:var(--card);border:1px solid var(--line);border-radius:var(--radius);
 overflow:hidden}
table.teams th,table.teams td{padding:10px 12px;text-align:left;
 border-bottom:1px solid var(--line);white-space:nowrap}
table.teams th{font-size:11px;text-transform:uppercase;letter-spacing:.05em;
 color:var(--faint);font-weight:700;background:color-mix(in srgb,var(--ink) 4%,transparent)}
table.teams td.n,table.teams th.n{text-align:right;font-variant-numeric:tabular-nums}
table.teams td.rank{color:var(--faint);font-variant-numeric:tabular-nums}
table.teams td.name{font-weight:650}
table.teams tbody tr:last-child td{border-bottom:0}
table.teams tbody tr:first-child td{background:color-mix(in srgb,var(--gold) 10%,transparent)}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
 color:var(--faint);font-size:12.5px;display:flex;justify-content:space-between;
 gap:12px;flex-wrap:wrap}
@media(max-width:520px){.grid{grid-template-columns:1fr}}
"

.sl_report_template <- paste0(
  "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">\n",
  "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\n",
  "<title>%s</title><style>%s</style></head>\n<body><div class=\"wrap\">\n",
  "<header class=\"top\">\n",
  "  <div><div class=\"eyebrow\">Season Report</div><h1>%s<br>%s</h1></div>\n",
  "  <div class=\"gen\">Generated %s<br>Data: public Sleeper API</div>\n</header>\n",
  "<div class=\"tiles\">%s</div>\n",
  "<div class=\"lead\"><h2 style=\"border:0;padding:0;margin:14px 0 0\">What the numbers say</h2>\n%s</div>\n",
  "<section><h2>Team by team</h2>\n",
  "<p class=\"blurb\">The whole season on one line each &mdash; record, points for and\n",
  "against, all-play win %%, power rank, lineup efficiency, and waiver moves / trades.</p>\n",
  "<div class=\"teamsec\">%s</div></section>\n%s\n",
  "<footer><span>Champions come from the stored playoff brackets, not Sleeper&rsquo;s\n",
  "winners_bracket.</span><span>sleepermetrics</span></footer>\n</div></body></html>")
