"""sleepermetrics (Python): analytical metrics for Sleeper fantasy leagues.

Parallel port of the R package. Same design: compute (metrics) / render (plots)
/ narrate (summaries), fed by season() / seasons() over a league's chain.
"""
from . import discord_bot, metrics, plots, summaries, weekly
from .api import sleeper_api
from .league import league, league_chain, starter_slots
from .players import players
from .season import Season, assemble_season, optimal_points, season, seasons
from .summaries import summary_career, summary_season
from .weekly import summary_week

__all__ = [
    "sleeper_api", "league", "league_chain", "starter_slots", "players",
    "Season", "assemble_season", "optimal_points", "season", "seasons",
    "metrics", "plots", "summaries", "weekly", "discord_bot",
    "summary_season", "summary_career", "summary_week",
]

__version__ = "0.1.0"
