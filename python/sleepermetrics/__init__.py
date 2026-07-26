"""sleepermetrics (Python): analytical metrics for Sleeper fantasy leagues.

Parallel port of the R package. Same design: compute (metrics) / render (plots)
/ narrate (summaries), fed by season() / seasons() over a league's chain.
"""
from . import (discord_bot, headshots, metrics, playoffs, plots, scoring,
               statnames, summaries, weekly)
from .api import sleeper_api
from .league import league, league_chain, starter_slots
from .players import players
from .playoffs import (Playoff, apply_playoffs, clutch, load_playoffs, playoff,
                       playoff_all_stars, playoff_allplay, playoff_best_games,
                       playoff_busts, playoff_carry, playoff_config,
                       playoff_finals, playoff_margins, playoff_path,
                       playoff_performances, playoff_players, playoff_replay,
                       playoff_seeding, playoff_stats, playoff_summary,
                       game_log, postseason_weeks, reference_scores,
                       scaffold_bracket, scope_frame, seeds,
                       sleeper_bracket, toilet_bowl, validate_config)
from .report import season_report
from .scoring import score_lineup, scoring_chart
from .season import (Season, assemble_season, avatar_url, league_accounts,
                     optimal_points, season, seasons)
from .statnames import scoring_readable, stat_labels
from .summaries import summary_career, summary_season
from .weekly import summary_week

__all__ = [
    "sleeper_api", "league", "league_chain", "starter_slots", "players",
    "Season", "assemble_season", "optimal_points", "season", "seasons",
    "league_accounts", "avatar_url",
    "metrics", "plots", "summaries", "weekly", "discord_bot",
    "summary_season", "summary_career", "summary_week",
    "scoring", "scoring_chart", "score_lineup",
    "statnames", "stat_labels", "scoring_readable",
    "headshots", "season_report",
    "playoffs", "playoff", "playoff_config", "playoff_summary", "Playoff",
    "apply_playoffs", "load_playoffs", "playoff_stats",
    "scope_frame", "seeds", "clutch", "toilet_bowl", "reference_scores", "postseason_weeks",
    "game_log",
    "playoff_performances", "playoff_players", "playoff_all_stars",
    "playoff_best_games", "playoff_busts", "playoff_finals", "playoff_carry",
    "playoff_margins", "playoff_path", "playoff_allplay", "playoff_seeding",
    "playoff_replay", "sleeper_bracket", "scaffold_bracket", "validate_config",
]

__version__ = "0.1.0"
