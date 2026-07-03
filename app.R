# app.R - Sleeper Fantasy Analytics dashboard (Shiny)
# Enter any Sleeper league ID; the app walks the season chain and renders
# descriptive metrics (standings, luck, lineup efficiency, consistency,
# points-for/against, career trajectory) plus auto-generated insight text.
#
# Run:  shiny::runApp(".")   or   Rscript -e 'shiny::runApp(".", port=8100)'

library(shiny)
library(bslib)
options(shiny.useragg = TRUE)  # crisp plots + color-emoji (crowns) rendering
source("R/ddbmMetrics.R")

DEFAULT_LEAGUE <- "1252770181306929152"  # DDBM

ui <- page_sidebar(
  title = "Sleeper Fantasy Analytics",
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
    id = "tabs",
    nav_panel(
      "Season overview", icon = icon("table-list"),
      card(card_header("What the numbers say"), uiOutput("season_summary")),
      layout_columns(
        card(full_screen = TRUE, plotOutput("p_standings", height = 430)),
        card(full_screen = TRUE, plotOutput("p_luck", height = 430)))
    ),
    nav_panel(
      "Coaching & scoring", icon = icon("chart-simple"),
      layout_columns(
        card(full_screen = TRUE, plotOutput("p_eff", height = 430)),
        card(full_screen = TRUE, plotOutput("p_cons", height = 430))),
      card(full_screen = TRUE, plotOutput("p_pfpa", height = 470))
    ),
    nav_panel(
      "Career (all seasons)", icon = icon("trophy"),
      card(card_header("Career insights"), uiOutput("career_summary")),
      layout_columns(
        card(full_screen = TRUE, plotOutput("p_career", height = 470)),
        card(full_screen = TRUE, plotOutput("p_traj", height = 470)))
    )
  )
)

server <- function(input, output, session) {
  store <- reactiveVal(NULL)
  busy  <- reactiveVal(FALSE)

  load_league <- function() {
    id <- trimws(input$league_id %||% "")
    if (!nzchar(id) || isTRUE(busy())) return()
    busy(TRUE); on.exit(busy(FALSE))
    withProgress(message = "Loading league from Sleeper...", value = 0, {
      chain <- tryCatch(build_league_chain(id), error = function(e) NULL)
      if (is.null(chain) || length(chain) == 0) {
        showNotification("Could not load that league ID.", type = "error"); return() }
      incProgress(0.1, detail = "player database")
      player_info()
      seasons <- list(); n <- length(chain)
      for (nm in names(chain)) {
        incProgress(0.85 / n, detail = paste("season", nm))
        seasons[[nm]] <- tryCatch(get_season(chain[[nm]]), error = function(e) NULL)
      }
      seasons <- seasons[!vapply(seasons, is.null, logical(1))]
      if (!length(seasons)) { showNotification("No scored seasons found.", type = "error"); return() }
      store(list(seasons = seasons,
                 all = dplyr::bind_rows(lapply(seasons, `[[`, "standings")),
                 name = chain[[length(chain)]]$name,
                 season_names = names(seasons)))
      updateSelectInput(session, "season", choices = rev(names(seasons)),
                        selected = names(seasons)[length(seasons)])
    })
  }
  observeEvent(input$load, load_league(), ignoreInit = TRUE)   # reload on button click
  autoload <- observe({ isolate(load_league()); autoload$destroy() })  # auto-load default once at startup

  cur <- reactive({ req(store(), input$season); store()$seasons[[input$season]] })

  output$league_info <- renderUI({
    d <- store()
    if (is.null(d)) return(HTML("<em>Loading…</em>"))
    HTML(paste0("<b>", d$name, "</b><br><small>Seasons: ",
                paste(d$season_names, collapse = ", "), "</small>"))
  })
  output$season_summary <- renderUI({ req(cur()); markdown(summarize_season(cur())) })
  output$career_summary <- renderUI({ req(store()); markdown(summarize_career(store()$all)) })

  output$p_standings <- renderPlot({ req(cur()); plot_standings(cur()) }, res = 96)
  output$p_luck      <- renderPlot({ req(cur()); plot_luck(cur()) }, res = 96)
  output$p_eff       <- renderPlot({ req(cur()); plot_efficiency(cur()) }, res = 96)
  output$p_cons      <- renderPlot({ req(cur()); plot_consistency(cur()) }, res = 96)
  output$p_pfpa      <- renderPlot({ req(cur()); plot_pf_pa(cur()) }, res = 96)
  output$p_career    <- renderPlot({ req(store()); plot_career(store()$all) }, res = 96)
  output$p_traj      <- renderPlot({ req(store()); plot_trajectory(store()$all) }, res = 96)
}

shinyApp(ui, server)
