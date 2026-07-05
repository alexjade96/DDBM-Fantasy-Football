# Discord integration: webhook posting + slash-command handling -----------

#' Post a message to a Discord webhook
#'
#' Sends `content`/`embeds` and optionally attaches image files (multipart).
#' Also used to deliver slash-command follow-ups (pass a follow-up webhook URL).
#'
#' @param webhook_url A Discord webhook (or interaction follow-up) URL.
#' @param content Optional message text (markdown).
#' @param embeds Optional list of Discord embed objects.
#' @param files Optional character vector of file paths to attach.
#' @param username Optional override for the webhook display name.
#' @return The parsed response (invisibly), or `TRUE` for a 204.
#' @export
sl_discord_send <- function(webhook_url, content = NULL, embeds = NULL,
                            files = NULL, username = NULL) {
  payload <- Filter(Negate(is.null),
                    list(content = content, embeds = embeds, username = username))
  req <- httr2::request(webhook_url)
  if (length(files)) {
    js <- jsonlite::toJSON(payload, auto_unbox = TRUE, null = "null")
    parts <- list(payload_json = js)
    for (i in seq_along(files))
      parts[[paste0("files[", i - 1, "]")]] <- curl::form_file(files[i])
    req <- do.call(function(...) httr2::req_body_multipart(req, ...), parts)
  } else {
    req <- httr2::req_body_json(req, payload)
  }
  resp <- req %>% httr2::req_retry(max_tries = 3) %>% httr2::req_perform()
  if (httr2::resp_status(resp) == 204) invisible(TRUE)
  else invisible(tryCatch(httr2::resp_body_json(resp), error = function(e) TRUE))
}

#' Verify a Discord interaction request signature (Ed25519)
#'
#' Discord signs every interaction POST; the endpoint must reject any request
#' that fails verification (returns 401).
#'
#' @param public_key Your application's public key (hex).
#' @param signature The `X-Signature-Ed25519` header (hex).
#' @param timestamp The `X-Signature-Timestamp` header.
#' @param body The raw request body (string).
#' @return `TRUE` if the signature is valid, else `FALSE`.
#' @export
sl_discord_verify <- function(public_key, signature, timestamp, body) {
  tryCatch(
    sodium::sig_verify(charToRaw(paste0(timestamp, body)),
                       sodium::hex2bin(signature),
                       sodium::hex2bin(public_key)),
    error = function(e) FALSE)
}

#' Slash-command definitions
#'
#' The commands the bot registers and answers.
#' @return A list of Discord application-command objects.
#' @export
sl_discord_commands <- function() {
  list(
    list(name = "standings",  description = "Current season standings", type = 1L),
    list(name = "luck",       description = "Luck: actual vs all-play expected wins", type = 1L),
    list(name = "efficiency", description = "Lineup efficiency (coaching)", type = 1L),
    list(name = "weekly",     description = "Latest week recap", type = 1L,
         options = list(list(name = "week", description = "Week number",
                             type = 4L, required = FALSE))),
    list(name = "career",     description = "All-time career standings", type = 1L),
    list(name = "help",       description = "List available commands", type = 1L))
}

#' Register (bulk-overwrite) the slash commands with Discord
#'
#' @param app_id Discord application id.
#' @param bot_token Bot token (used as `Authorization: Bot <token>`).
#' @param guild_id Optional guild id to register guild-scoped commands (instant);
#'   omit for global commands (can take up to an hour to propagate).
#' @return The parsed API response (invisibly).
#' @export
sl_discord_register_commands <- function(app_id, bot_token, guild_id = NULL) {
  path <- if (is.null(guild_id))
    paste0("/applications/", app_id, "/commands")
  else
    paste0("/applications/", app_id, "/guilds/", guild_id, "/commands")
  resp <- httr2::request(paste0("https://discord.com/api/v10", path)) %>%
    httr2::req_headers(Authorization = paste("Bot", bot_token)) %>%
    httr2::req_method("PUT") %>%
    httr2::req_body_json(sl_discord_commands()) %>%
    httr2::req_perform()
  invisible(httr2::resp_body_json(resp))
}

# Render a command answer from already-assembled data (pure; testable).
# Returns list(content = markdown|NULL, files = character()).
sl_discord_render <- function(name, options = list(), season = NULL,
                              seasons = NULL, out_dir = tempdir()) {
  save_plot <- function(p, f) {
    path <- file.path(out_dir, f)
    dev <- if (requireNamespace("ragg", quietly = TRUE)) ragg::agg_png else grDevices::png
    ggplot2::ggsave(path, p, width = 9, height = 6, dpi = 110, device = dev)
    path
  }
  wk <- options$week
  switch(name,
    help = list(content = paste0("**Commands:** ",
      paste0("`/", vapply(sl_discord_commands(), `[[`, "", "name"), "`", collapse = "  ")),
      files = character()),
    standings  = list(content = paste0("**", season$season, " standings**"),
                      files = save_plot(sl_plot_standings(season), "standings.png")),
    luck       = list(content = "**Luck - actual vs all-play expected wins**",
                      files = save_plot(sl_plot_luck(season), "luck.png")),
    efficiency = list(content = "**Lineup efficiency (coaching)**",
                      files = save_plot(sl_plot_efficiency(season), "efficiency.png")),
    weekly     = list(content = sl_summary_week(season, wk),
                      files = save_plot(sl_plot_standings(season), "weekly.png")),
    career     = list(content = sl_summary_career(seasons),
                      files = save_plot(sl_plot_career(seasons), "career.png")),
    list(content = paste0("Unknown command: `", name, "`"), files = character()))
}

#' Answer a slash command for a league (fetch + render)
#'
#' Used by the interactions server: fetches the data a command needs, then
#' renders the reply (markdown + chart file). Career commands assemble the whole
#' chain; others assemble a single season.
#'
#' @param name Command name (e.g. `"standings"`).
#' @param options Named list of command option values (e.g. `list(week = 5)`).
#' @param league_id League id to analyse.
#' @param out_dir Directory for the rendered chart.
#' @return `list(content, files)`.
#' @export
sl_discord_command_reply <- function(name, options = list(), league_id,
                                     out_dir = tempdir()) {
  if (identical(name, "help")) return(sl_discord_render(name, options, out_dir = out_dir))
  if (identical(name, "career"))
    return(sl_discord_render(name, options, seasons = sl_seasons(league_id), out_dir = out_dir))
  sl_discord_render(name, options, season = sl_season(league_id), out_dir = out_dir)
}

#' Build a weekly recap payload for a league
#'
#' Assembles the latest (or given) week's recap: markdown highlights, a text
#' scoreboard, and the standings + luck charts, packaged as a Discord embed plus
#' attachment files.
#'
#' @param league_id League id.
#' @param week Week number; default = last scored week.
#' @param out_dir Directory for the rendered charts.
#' @return `list(season, week, text, embeds, files)`.
#' @export
sl_weekly_recap <- function(league_id, week = NULL, out_dir = tempdir()) {
  s <- sl_season(league_id)
  wk <- week %||% s$last_week
  dev <- if (requireNamespace("ragg", quietly = TRUE)) ragg::agg_png else grDevices::png
  f1 <- file.path(out_dir, "recap_standings.png")
  f2 <- file.path(out_dir, "recap_luck.png")
  ggplot2::ggsave(f1, sl_plot_standings(s), width = 9, height = 6, dpi = 110, device = dev)
  ggplot2::ggsave(f2, sl_plot_luck(s), width = 9, height = 6, dpi = 110, device = dev)
  ws <- sl_week_stats(s, wk)
  board <- paste(sprintf("%-16s %6.1f", substr(ws$user_name, 1, 16), ws$points),
                 collapse = "\n")
  embed <- list(
    title = paste0(s$name, " - Week ", wk, " Recap"),
    description = sl_summary_week(s, wk),
    color = 2915288L,
    fields = list(list(name = "Scoreboard",
                       value = paste0("```\n", board, "\n```"), inline = FALSE)),
    image = list(url = "attachment://recap_standings.png"))
  list(season = s$season, week = wk, text = sl_summary_week(s, wk),
       embeds = list(embed), files = c(f1, f2))
}

#' Post a weekly recap to a Discord webhook
#'
#' @param webhook_url Discord channel webhook URL.
#' @param league_id League id.
#' @param week Week number; default = last scored week.
#' @param dry_run If `TRUE`, build and return the recap without posting.
#' @param out_dir Directory for the rendered charts.
#' @return The recap payload (invisibly).
#' @examples
#' \dontrun{
#' sl_post_weekly(Sys.getenv("DISCORD_WEBHOOK"), "1252770181306929152")
#' }
#' @export
sl_post_weekly <- function(webhook_url, league_id, week = NULL,
                           dry_run = FALSE, out_dir = tempdir()) {
  r <- sl_weekly_recap(league_id, week, out_dir = out_dir)
  if (dry_run) {
    message("[dry run] Week ", r$week, " recap for league ", league_id,
            " (", length(r$files), " charts). Would POST embed:\n", r$text)
    return(invisible(r))
  }
  sl_discord_send(webhook_url, embeds = r$embeds, files = r$files,
                  username = "Sleeper Analytics")
  invisible(r)
}

#' Run the Discord interactions server
#'
#' Serves the bundled plumber endpoint that answers slash commands. Configure
#' `DISCORD_PUBLIC_KEY`, `DISCORD_APP_ID` and `SLEEPERMETRICS_LEAGUE` env vars
#' first, and put HTTPS in front (Discord requires a public HTTPS URL). See
#' `system.file("discordbot", "README.md", package = "sleepermetrics")`.
#'
#' @param port Port to listen on.
#' @param host Host/interface to bind.
#' @return Called for its side effect (runs the server; does not return).
#' @export
sl_discord_serve <- function(port = 8000, host = "0.0.0.0") {
  for (p in c("plumber", "sodium")) {
    if (!requireNamespace(p, quietly = TRUE))
      stop("Package '", p, "' is required for the interactions server.", call. = FALSE)
  }
  f <- system.file("discordbot", "plumber.R", package = "sleepermetrics")
  if (!nzchar(f)) stop("Could not locate the bundled bot script.", call. = FALSE)
  plumber::pr_run(plumber::pr(f), host = host, port = port)
}
