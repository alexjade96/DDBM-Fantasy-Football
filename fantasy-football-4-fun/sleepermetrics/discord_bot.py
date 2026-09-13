"""Discord integration: webhook poster + slash-command bot (mirrors R discord.R).

The bot uses discord.py (gateway + native slash commands), so unlike the R
plumber endpoint it needs no signature verification or public HTTPS host - just
a bot token.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile

import requests

from . import metrics, plots
from .season import season, seasons
from .summaries import summary_career
from .weekly import summary_week


# --- Webhook posting ------------------------------------------------------
def post_webhook(url, content=None, embeds=None, files=None, username=None):
    """POST content/embeds and optional image files to a Discord webhook."""
    payload = {k: v for k, v in
               {"content": content, "embeds": embeds, "username": username}.items()
               if v is not None}
    if files:
        data = {"payload_json": json.dumps(payload)}
        handles = [open(p, "rb") for p in files]
        try:
            multi = {f"files[{i}]": (os.path.basename(files[i]), handles[i], "image/png")
                     for i in range(len(files))}
            resp = requests.post(url, data=data, files=multi, timeout=30)
        finally:
            for h in handles:
                h.close()
    else:
        resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return True


def weekly_recap(league_id, week=None, out_dir=None) -> dict:
    """Assemble a week's recap: highlights + scoreboard + standings/luck charts."""
    out_dir = out_dir or tempfile.gettempdir()
    s = season(league_id)
    wk = week if week is not None else s.last_week
    f1 = plots.save(plots.plot_standings(s), os.path.join(out_dir, "recap_standings.png"))
    f2 = plots.save(plots.plot_luck(s), os.path.join(out_dir, "recap_luck.png"))
    ws = metrics.week_stats(s, wk)
    board = "\n".join(f"{str(n)[:16]:<16} {p:6.1f}"
                      for n, p in zip(ws["user_name"], ws["points"]))
    text = summary_week(s, wk)
    embed = {
        "title": f"{s.name} - Week {wk} Recap",
        "description": text,
        "color": 2915288,
        "fields": [{"name": "Scoreboard", "value": f"```\n{board}\n```", "inline": False}],
        "image": {"url": "attachment://recap_standings.png"},
    }
    return {"season": s.season, "week": wk, "text": text, "embeds": [embed], "files": [f1, f2]}


def post_weekly(webhook_url, league_id, week=None, dry_run=False, out_dir=None) -> dict:
    """Build a weekly recap and post it to a channel webhook (or dry-run)."""
    r = weekly_recap(league_id, week, out_dir)
    if dry_run:
        msg = f"[dry run] Week {r['week']} recap ({len(r['files'])} charts):\n{r['text']}"
        try:
            print(msg)
        except UnicodeEncodeError:  # non-UTF-8 console (e.g. Windows cp1252)
            print(msg.encode("ascii", "replace").decode("ascii"))
        return r
    post_webhook(webhook_url, embeds=r["embeds"], files=r["files"],
                 username="Sleeper Analytics")
    return r


# --- Interactive slash-command bot (discord.py) ---------------------------
def _render_command(name: str, league_id: str, week=None, out_dir=None):
    """Blocking: fetch + render a command answer. Returns (content, file_path)."""
    out_dir = out_dir or tempfile.gettempdir()
    if name == "help":
        return ("**Commands:** `/standings`  `/luck`  `/efficiency`  "
                "`/weekly`  `/career`  `/help`", None)
    if name == "career":
        ss = seasons(league_id)
        path = plots.save(plots.plot_career(ss), os.path.join(out_dir, "career.png"))
        return (summary_career(ss), path)
    s = season(league_id)
    if name == "standings":
        return (f"**{s.season} standings**",
                plots.save(plots.plot_standings(s), os.path.join(out_dir, "standings.png")))
    if name == "luck":
        return ("**Luck - actual vs all-play expected wins**",
                plots.save(plots.plot_luck(s), os.path.join(out_dir, "luck.png")))
    if name == "efficiency":
        return ("**Lineup efficiency (coaching)**",
                plots.save(plots.plot_efficiency(s), os.path.join(out_dir, "efficiency.png")))
    if name == "weekly":
        return (summary_week(s, week),
                plots.save(plots.plot_standings(s), os.path.join(out_dir, "weekly.png")))
    return (f"Unknown command: `{name}`", None)


def build_client(league_id: str):
    """Build a discord.py client with the slash commands registered."""
    import discord
    from discord import app_commands

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    tree = app_commands.CommandTree(client)

    @client.event
    async def on_ready():  # noqa: D401
        await tree.sync()
        print(f"Logged in as {client.user}; slash commands synced.")

    async def answer(interaction, name, week=None):
        await interaction.response.defer(thinking=True)
        content, path = await asyncio.to_thread(_render_command, name, league_id, week)
        import discord
        file = discord.File(path) if path else None
        await interaction.followup.send(content=content,
                                        file=file if file else discord.utils.MISSING)

    @tree.command(name="standings", description="Current season standings")
    async def _standings(interaction):
        await answer(interaction, "standings")

    @tree.command(name="luck", description="Luck: actual vs all-play expected wins")
    async def _luck(interaction):
        await answer(interaction, "luck")

    @tree.command(name="efficiency", description="Lineup efficiency (coaching)")
    async def _efficiency(interaction):
        await answer(interaction, "efficiency")

    @tree.command(name="weekly", description="Weekly recap")
    @app_commands.describe(week="Week number (default: latest)")
    async def _weekly(interaction, week: int | None = None):
        await answer(interaction, "weekly", week)

    @tree.command(name="career", description="All-time career standings")
    async def _career(interaction):
        await answer(interaction, "career")

    @tree.command(name="help", description="List available commands")
    async def _help(interaction):
        await interaction.response.send_message(_render_command("help", league_id)[0])

    return client


def run_bot(token: str, league_id: str):
    """Connect and run the slash-command bot (blocks)."""
    build_client(league_id).run(token)
