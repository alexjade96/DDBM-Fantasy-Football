# Register the sleepermetrics slash commands with your Discord application.
#
# Set these first (guild id is optional but registers instantly):
#   DISCORD_APP_ID, DISCORD_BOT_TOKEN, DISCORD_GUILD_ID
# then:  Rscript register.R

library(sleepermetrics)

app   <- Sys.getenv("DISCORD_APP_ID")
token <- Sys.getenv("DISCORD_BOT_TOKEN")
guild <- Sys.getenv("DISCORD_GUILD_ID", "")
if (!nzchar(app) || !nzchar(token))
  stop("Set DISCORD_APP_ID and DISCORD_BOT_TOKEN.")

res <- sl_discord_register_commands(app, token,
                                    guild_id = if (nzchar(guild)) guild else NULL)
cat("Registered", length(res), "commands:",
    paste(vapply(res, function(x) x$name, ""), collapse = ", "), "\n")
