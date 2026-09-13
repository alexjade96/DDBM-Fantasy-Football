# Discord slash-command interactions endpoint for sleepermetrics.
#
# Discord POSTs every interaction here; this verifies the Ed25519 signature,
# answers the PING handshake, and for slash commands defers immediately then
# delivers the (slower) chart/summary as a follow-up message.
#
# Config via env vars:
#   DISCORD_PUBLIC_KEY   your app's public key (Developer Portal)
#   DISCORD_APP_ID       your application id
#   SLEEPERMETRICS_LEAGUE  the league id to analyse
#
# Run: sleepermetrics::sl_discord_serve(port = 8000)  (put HTTPS in front)

library(sleepermetrics)

.PUBLIC_KEY <- Sys.getenv("DISCORD_PUBLIC_KEY")
.APP_ID     <- Sys.getenv("DISCORD_APP_ID")
.LEAGUE_ID  <- Sys.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152")

.parse_options <- function(options) {
  if (is.null(options) || !length(options)) return(list())
  stats::setNames(lapply(options, function(o) o$value),
                  vapply(options, function(o) o$name, ""))
}

#* Health check
#* @get /health
#* @serializer unboxedJSON
function() list(status = "ok", league = .LEAGUE_ID)

#* Discord interactions endpoint
#* @post /interactions
#* @serializer unboxedJSON
function(req, res) {
  sig  <- req$HTTP_X_SIGNATURE_ED25519
  ts   <- req$HTTP_X_SIGNATURE_TIMESTAMP
  body <- req$postBody
  if (is.null(sig) || is.null(ts) ||
      !sl_discord_verify(.PUBLIC_KEY, sig, ts, body)) {
    res$status <- 401
    return("invalid request signature")
  }
  ix <- jsonlite::fromJSON(body, simplifyVector = FALSE)

  if (ix$type == 1) return(list(type = 1L))          # PING -> PONG

  if (ix$type == 2) {                                # APPLICATION_COMMAND
    name  <- ix$data$name
    opts  <- .parse_options(ix$data$options)
    token <- ix$token
    # Answer asynchronously: Discord requires a response within 3s, but a data
    # fetch + chart render takes longer, so defer now and follow up.
    later::later(function() {
      reply <- tryCatch(
        sl_discord_command_reply(name, opts, .LEAGUE_ID),
        error = function(e) list(content = paste("Error:", conditionMessage(e)),
                                 files = character()))
      followup <- paste0("https://discord.com/api/v10/webhooks/", .APP_ID, "/", token)
      sl_discord_send(followup, content = reply$content, files = reply$files)
    })
    return(list(type = 5L))                          # DEFERRED_CHANNEL_MESSAGE
  }

  list(type = 4L, data = list(content = "Unsupported interaction"))
}
