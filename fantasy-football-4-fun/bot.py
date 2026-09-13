#!/usr/bin/env python
"""CLI for the Python sleepermetrics Discord bot.

  python bot.py weekly --dry-run              # preview a weekly recap
  python bot.py weekly --webhook <URL>        # post a weekly recap
  python bot.py serve                         # run the slash-command bot

Config falls back to env vars / a .env file: SLEEPERMETRICS_LEAGUE,
DISCORD_WEBHOOK, DISCORD_BOT_TOKEN.
"""
from __future__ import annotations

import argparse
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from sleepermetrics import discord_bot


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bot.py",
                                 description="Sleeper analytics Discord bot (Python)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("weekly", help="Post a weekly recap to a webhook")
    w.add_argument("--league", default=os.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152"))
    w.add_argument("--webhook", default=os.getenv("DISCORD_WEBHOOK"))
    w.add_argument("--week", type=int, default=None)
    w.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("serve", help="Run the interactive slash-command bot")
    s.add_argument("--league", default=os.getenv("SLEEPERMETRICS_LEAGUE", "1252770181306929152"))
    s.add_argument("--token", default=os.getenv("DISCORD_BOT_TOKEN"))

    args = ap.parse_args(argv)
    if args.cmd == "weekly":
        if not args.league:
            ap.error("set --league or SLEEPERMETRICS_LEAGUE")
        if not args.dry_run and not args.webhook:
            ap.error("set --webhook or DISCORD_WEBHOOK (or use --dry-run)")
        discord_bot.post_weekly(args.webhook, args.league, args.week, dry_run=args.dry_run)
    elif args.cmd == "serve":
        if not args.token:
            ap.error("set --token or DISCORD_BOT_TOKEN")
        if not args.league:
            ap.error("set --league or SLEEPERMETRICS_LEAGUE")
        discord_bot.run_bot(args.token, args.league)


if __name__ == "__main__":
    main()
