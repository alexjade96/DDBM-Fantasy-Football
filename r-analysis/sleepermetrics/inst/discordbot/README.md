# sleepermetrics Discord bot

Two ways to get league analytics into Discord. Both reuse the package's
metrics/charts, so they stay in sync with the dashboard.

## 1. Weekly stats poster (webhook, simplest, no hosting)

A one-way poster: computes the latest week's recap (highlights + scoreboard +
standings/luck charts) and posts it to a channel via an **Incoming Webhook**.

Setup:
1. In Discord: *Channel → Edit → Integrations → Webhooks → New Webhook*, copy
   the **Webhook URL**.
2. Post a recap:

   ```r
   library(sleepermetrics)
   sl_post_weekly("<WEBHOOK_URL>", "1252770181306929152")          # post it
   sl_post_weekly("<WEBHOOK_URL>", "1252770181306929152", dry_run = TRUE)  # preview
   ```

3. Schedule it (Windows Task Scheduler / cron) each Tuesday, e.g.:

   ```
   Rscript -e 'sleepermetrics::sl_post_weekly(Sys.getenv("DISCORD_WEBHOOK"), Sys.getenv("SLEEPERMETRICS_LEAGUE"))'
   ```

## 2. Interactive slash-command bot (interactions endpoint)

Users type `/standings`, `/luck`, `/efficiency`, `/weekly [week]`, `/career`,
`/help`; the bot replies with the chart + insight text.

Setup:
1. Create an application at <https://discord.com/developers/applications>. Note
   the **Application ID**, **Public Key**, and add a **Bot** (copy its **Token**).
2. Register the commands (guild id = instant; global can take ~1h):

   ```
   DISCORD_APP_ID=... DISCORD_BOT_TOKEN=... DISCORD_GUILD_ID=... \
     Rscript inst/discordbot/register.R
   ```

3. Run the endpoint (needs a public **HTTPS** URL; put a reverse proxy,
   Cloudflare Tunnel, or ngrok in front):

   ```r
   Sys.setenv(DISCORD_PUBLIC_KEY = "...", DISCORD_APP_ID = "...",
              SLEEPERMETRICS_LEAGUE = "1252770181306929152")
   sleepermetrics::sl_discord_serve(port = 8000)
   ```

4. In the Developer Portal set **Interactions Endpoint URL** to
   `https://<your-host>/interactions`. Discord sends a signed PING to validate
   it; the server verifies the Ed25519 signature (`sl_discord_verify()`) and
   replies to the handshake automatically.

Each command **defers** (Discord's 3s limit) and delivers the answer as a
follow-up once the data fetch + chart render finish.
