# Bundled Shiny dashboard for the sleepermetrics package.
# Launch via sleepermetrics::sl_dashboard().

library(shiny)
library(bslib)
options(shiny.useragg = TRUE)   # crisp plots + color-emoji rendering
sm <- asNamespace("sleepermetrics")  # package must be loaded/installed

DEFAULT_LEAGUE <- Sys.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152")

# Playoff bracket configs (see sl_dashboard(playoffs = ...)).
PLAYOFF_DIR <- Sys.getenv("SLEEPERMETRICS_PLAYOFFS", "")
playoff_cfgs <- if (nzchar(PLAYOFF_DIR) && dir.exists(PLAYOFF_DIR)) {
  stats::setNames(list.files(PLAYOFF_DIR, "\\.json$", full.names = TRUE),
                  basename(list.files(PLAYOFF_DIR, "\\.json$")))
} else character(0)

ui <- page_sidebar(
  title = "Sleeper League Analytics",
  theme = bs_theme(version = 5, bootswatch = "litera", primary = "#2c7fb8"),
  sidebar = sidebar(
    width = 300,
    markdown("Enter a **Sleeper league ID** and load it. Works for any league; historical seasons are found automatically."),
    textInput("league_id", "Sleeper league ID", value = DEFAULT_LEAGUE),
    actionButton("load", "Load league", icon = icon("download"), class = "btn-primary"),
    hr(),
    selectInput("season", "Season", choices = NULL),
    uiOutput("league_info"),
    hr(),
    markdown("<small>Data: public Sleeper API. Metrics computed live.</small>")
  ),
  navset_card_tab(
    nav_panel("Season overview", icon = icon("table-list"),
      card(card_header("What the numbers say"), uiOutput("season_summary")),
      layout_columns(card(full_screen = TRUE, plotOutput("p_standings", height = 430)),
                     card(full_screen = TRUE, plotOutput("p_luck", height = 430)))),
    nav_panel("Weekly trends", icon = icon("chart-line"),
      card(full_screen = TRUE, plotOutput("p_tablepos", height = 470)),
      card(full_screen = TRUE, plotOutput("p_teampts", height = 470))),
    nav_panel("Coaching & scoring", icon = icon("chart-simple"),
      layout_columns(card(full_screen = TRUE, plotOutput("p_eff", height = 430)),
                     card(full_screen = TRUE, plotOutput("p_cons", height = 430))),
      card(full_screen = TRUE, plotOutput("p_pfpa", height = 470))),
    nav_panel("Roster & positions", icon = icon("users"),
      layout_columns(card(full_screen = TRUE, plotOutput("p_posscore", height = 430)),
                     card(full_screen = TRUE, plotOutput("p_rostercount", height = 430))),
      card(full_screen = TRUE, plotOutput("p_heatmap", height = 470)),
      card(full_screen = TRUE, plotOutput("p_starter", height = 400)),
      card(full_screen = TRUE, plotOutput("p_posbox", height = 470))),
    nav_panel("Transactions", icon = icon("right-left"),
      markdown("Value **while rostered**, read from weekly roster membership. Trades show every team that held the player; waivers/FA show the acquiring team."),
      card(full_screen = TRUE, plotOutput("p_trade", height = 520)),
      card(full_screen = TRUE, plotOutput("p_waiver", height = 560))),
    nav_panel("Playoffs", icon = icon("sitemap"),
      layout_columns(
        col_widths = c(3, 3, 3, 3),
        value_box("Champion", textOutput("pl_champ"), showcase = icon("crown"),
                  theme = "warning"),
        value_box("Playoff games", textOutput("pl_games"), showcase = icon("sitemap"),
                  theme = "primary"),
        value_box("Highest playoff score", textOutput("pl_top"),
                  showcase = icon("fire"), theme = "success"),
        value_box("Biggest blowout", textOutput("pl_blow"),
                  showcase = icon("bomb"), theme = "secondary")),
      layout_columns(
        col_widths = c(8, 4),
        card(full_screen = TRUE, card_header("Bracket"),
             plotOutput("p_bracket", height = 520)),
        card(card_header("Run the bracket"),
          if (length(playoff_cfgs))
            selectInput("pl_cfg", "Bracket config", choices = playoff_cfgs)
          else markdown("No bracket configs found. Launch with `sl_dashboard(playoffs = \"playoffs\")`."),
          radioButtons("pl_scope", "Count which games?",
                       choices = c("Championship path only" = "title",
                                   "Include consolation" = "all",
                                   "Consolation only" = "consolation"),
                       selected = "title"),
          actionButton("pl_refresh", "Score / refresh", icon = icon("rotate"),
                       class = "btn-primary"),
          markdown("<small>Only **roster inputs** are needed: each side's submitted starters. Scores are recomputed live from current NFL stats under the league's own scoring chart.</small>"),
          tableOutput("pl_summary"))),
      card(full_screen = TRUE, card_header("Matchup detail"),
           selectInput("pl_matchup", "Matchup", choices = NULL),
           plotOutput("p_matchup", height = 470)),
      layout_columns(
        col_widths = c(6, 6),
        card(full_screen = TRUE, card_header("Best playoff players (all time)"),
             plotOutput("p_plplayers", height = 460)),
        card(full_screen = TRUE, card_header("Clutch: playoff vs regular season"),
             plotOutput("p_clutch", height = 460))),
      layout_columns(
        col_widths = c(7, 5),
        card(full_screen = TRUE, card_header("Career playoff record (all seasons)"),
             plotOutput("p_plstats", height = 420)),
        card(full_screen = TRUE, card_header("Postseason résumé"),
             markdown("<small>Playoff-only metrics: appearances, playoff W-L, titles, finals reached, and points per playoff game.</small>"),
             tableOutput("pl_career"))),
      card(card_header("League point-calculation chart (stored with the bracket)"),
           tableOutput("pl_scoring"))),
    nav_panel("Career (all seasons)", icon = icon("trophy"),
      card(card_header("Career insights"), uiOutput("career_summary")),
      layout_columns(card(full_screen = TRUE, plotOutput("p_career", height = 470)),
                     card(full_screen = TRUE, plotOutput("p_traj", height = 470))))
  )
)

server <- function(input, output, session) {
  store <- reactiveVal(NULL)
  busy <- reactiveVal(FALSE)

  load_league <- function() {
    id <- trimws(input$league_id %||% "")
    if (!nzchar(id) || isTRUE(busy())) return()
    busy(TRUE); on.exit(busy(FALSE))
    withProgress(message = "Loading league from Sleeper...", value = 0, {
      chain <- tryCatch(sm$sl_league_chain(id), error = function(e) NULL)
      if (is.null(chain) || !length(chain)) {
        showNotification("Could not load that league ID.", type = "error"); return() }
      incProgress(0.1, detail = "player database"); sm$sl_players()
      seasons <- list(); n <- length(chain)
      for (nm in names(chain)) {
        incProgress(0.85 / n, detail = paste("season", nm))
        seasons[[nm]] <- tryCatch(sm$sl_assemble_season(chain[[nm]]), error = function(e) NULL)
      }
      seasons <- seasons[!vapply(seasons, is.null, logical(1))]
      if (!length(seasons)) { showNotification("No scored seasons found.", type = "error"); return() }
      # A season's playoff bracket, where one is stored, decides its champion --
      # Sleeper's own bracket is not reliable (see playoffs/README.md). This is
      # what makes career titles correct.
      if (nzchar(PLAYOFF_DIR)) {
        seasons <- tryCatch(sm$sl_apply_playoffs(seasons, PLAYOFF_DIR),
                            error = function(e) seasons)
      }
      store(list(seasons = seasons, name = chain[[length(chain)]]$name,
                 season_names = names(seasons)))
      updateSelectInput(session, "season", choices = rev(names(seasons)),
                        selected = names(seasons)[length(seasons)])
    })
  }
  observeEvent(input$load, load_league(), ignoreInit = TRUE)
  autoload <- observe({ isolate(load_league()); autoload$destroy() })

  cur <- reactive({ req(store(), input$season); store()$seasons[[input$season]] })
  seasons <- reactive({ req(store()); store()$seasons })

  output$league_info <- renderUI({
    d <- store(); if (is.null(d)) return(HTML("<em>Loading&hellip;</em>"))
    HTML(paste0("<b>", d$name, "</b><br><small>Seasons: ",
                paste(d$season_names, collapse = ", "), "</small>"))
  })
  output$season_summary <- renderUI({ req(cur()); markdown(sm$sl_summary_season(cur())) })
  output$career_summary <- renderUI({ req(seasons()); markdown(sm$sl_summary_career(seasons())) })
  output$p_standings <- renderPlot({ req(cur()); sm$sl_plot_standings(cur()) }, res = 96)
  output$p_luck      <- renderPlot({ req(cur()); sm$sl_plot_luck(cur()) }, res = 96)
  output$p_eff       <- renderPlot({ req(cur()); sm$sl_plot_efficiency(cur()) }, res = 96)
  output$p_cons      <- renderPlot({ req(cur()); sm$sl_plot_consistency(cur()) }, res = 96)
  output$p_pfpa      <- renderPlot({ req(cur()); sm$sl_plot_pf_pa(cur()) }, res = 96)
  output$p_career    <- renderPlot({ req(seasons()); sm$sl_plot_career(seasons()) }, res = 96)
  output$p_traj      <- renderPlot({ req(seasons()); sm$sl_plot_trajectory(seasons()) }, res = 96)

  # Ported roster/position + weekly-trend charts.
  output$p_tablepos    <- renderPlot({ req(cur()); sm$sl_plot_table_position(cur()) }, res = 96)
  output$p_teampts     <- renderPlot({ req(cur()); sm$sl_plot_team_points(cur()) }, res = 96)
  output$p_posscore    <- renderPlot({ req(cur()); sm$sl_plot_position_scoring(cur()) }, res = 96)
  output$p_rostercount <- renderPlot({ req(cur()); sm$sl_plot_roster_counts(cur()) }, res = 96)
  output$p_heatmap     <- renderPlot({ req(cur()); sm$sl_plot_roster_heatmap(cur()) }, res = 96)
  output$p_starter     <- renderPlot({ req(cur()); sm$sl_plot_starter_bench(cur()) }, res = 96)
  output$p_posbox      <- renderPlot({ req(cur()); sm$sl_plot_position_box(cur()) }, res = 96)

  # --- Playoffs: config-driven custom bracket, scored live -----------------
  playoff <- reactiveVal(NULL)

  run_bracket <- function() {
    cfg <- input$pl_cfg
    if (is.null(cfg) || !nzchar(cfg)) return()
    withProgress(message = "Scoring bracket from submitted lineups...", value = 0.3, {
      sm$sl_clear_stats_cache()   # live week: never serve stale stat lines
      p <- tryCatch(sm$sl_playoff(cfg), error = function(e) {
        showNotification(paste("Bracket error:", conditionMessage(e)), type = "error")
        NULL
      })
      if (is.null(p)) return()
      playoff(p)
      played <- unique(p$results$matchup_id[p$results$result %in% c("W", "L", "T")])
      updateSelectInput(session, "pl_matchup", choices = played,
                        selected = if (length(played)) played[length(played)] else NULL)
    })
  }
  observeEvent(input$pl_refresh, run_bracket(), ignoreInit = TRUE)
  observeEvent(input$pl_cfg, run_bracket(), ignoreInit = FALSE)

  # Follow the season picker: show that season's stored bracket automatically.
  observeEvent(input$season, {
    req(input$season, length(playoff_cfgs) > 0)
    hit <- playoff_cfgs[startsWith(names(playoff_cfgs), input$season)]
    if (length(hit)) updateSelectInput(session, "pl_cfg", selected = hit[[1]])
  }, ignoreInit = FALSE)

  output$p_bracket <- renderPlot({
    validate(need(playoff(), "Pick a bracket config and hit Score / refresh."))
    sm$sl_plot_playoff_bracket(playoff())
  }, res = 96)

  output$pl_summary <- renderTable({
    req(playoff()); sm$sl_playoff_summary(playoff())
  }, digits = 1, spacing = "xs")

  scope <- reactive(input$pl_scope %||% "title")

  # Stat indicators for the selected season's bracket.
  pl_played <- reactive({
    p <- playoff(); req(p)
    p$results[p$results$result %in% c("W", "L", "T"), ]
  })
  output$pl_champ <- renderText({ playoff()$champion %||% "undecided" })
  output$pl_games <- renderText({
    d <- pl_played(); paste0(length(unique(d$matchup_id)), " games")
  })
  output$pl_top <- renderText({
    d <- pl_played(); req(nrow(d))
    i <- which.max(d$points)
    sprintf("%.1f  %s", d$points[i], d$team[i])
  })
  output$pl_blow <- renderText({
    d <- pl_played(); req(nrow(d))
    i <- which.max(d$margin)
    sprintf("%+.1f  %s", d$margin[i], d$team[i])
  })

  # Playoff-only analytics across every stored bracket.
  all_playoffs <- reactive({
    req(nzchar(PLAYOFF_DIR))
    withProgress(message = "Scoring every stored bracket...", value = 0.3,
                 sm$sl_load_playoffs(PLAYOFF_DIR))
  })
  output$p_plstats <- renderPlot({
    validate(need(length(all_playoffs()) > 0, "No bracket configs found."))
    sm$sl_plot_playoff_stats(all_playoffs(), scope = scope())
  }, res = 96)
  output$p_plplayers <- renderPlot({
    req(all_playoffs()); sm$sl_plot_playoff_players(all_playoffs(), scope = scope())
  }, res = 96)
  output$p_clutch <- renderPlot({
    req(all_playoffs(), seasons())
    sm$sl_plot_clutch(seasons(), all_playoffs(), scope = scope())
  }, res = 96)
  output$pl_career <- renderTable({
    req(all_playoffs())
    d <- sm$sl_playoff_stats(all_playoffs(), scope = scope())
    d[, c("user_name", "appearances", "games", "wins", "losses", "win_pct",
          "titles", "finals", "ppg")]
  }, digits = 1, spacing = "xs")

  output$p_matchup <- renderPlot({
    req(playoff())
    validate(need(isTruthy(input$pl_matchup), "No matchup has been played yet."))
    sm$sl_plot_playoff_matchup(playoff(), input$pl_matchup)
  }, res = 96)

  output$pl_scoring <- renderTable({
    p <- playoff(); req(p)
    sc <- p$config$scoring_settings
    validate(need(length(sc), "This bracket has no stored scoring chart."))
    d <- data.frame(stat = names(sc), weight = as.numeric(unlist(sc)))
    d <- d[order(d$stat), ]
    # Wide, compact layout: the chart is ~48 rules.
    n <- ceiling(nrow(d) / 4)
    cols <- lapply(seq_len(4), function(i) {
      idx <- ((i - 1) * n + 1):min(i * n, nrow(d))
      r <- d[idx, ]; r[is.na(r$stat), ] <- ""
      setNames(r, paste0(c("stat", "weight"), i))
    })
    do.call(cbind, lapply(cols, function(x) { x[seq_len(n), ] }))
  }, digits = 2, spacing = "xs", na = "")

  # Transaction charts: guard seasons with no trades / pickups.
  output$p_trade <- renderPlot({
    req(cur())
    validate(need(nrow(sm$sl_trade_performance(cur())) > 0,
                  "No trades recorded this season."))
    sm$sl_plot_trade_performance(cur())
  }, res = 96)
  output$p_waiver <- renderPlot({
    req(cur())
    validate(need(nrow(sm$sl_waiver_performance(cur())) > 0,
                  "No waiver / free-agent pickups recorded this season."))
    sm$sl_plot_waiver_performance(cur())
  }, res = 96)
}

shinyApp(ui, server)
