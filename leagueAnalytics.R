# DDBM Fantasy Football - Cross-Season (Career) League Analytics
# leagueAnalytics.R
#
# Companion to ddbmFF.R. Where ddbmFF.R analyses ONE season, this script walks
# the league's whole season chain (each season is a separate Sleeper league,
# linked by previous_league_id) and builds CUMULATIVE, career-level analytics
# keyed by the persistent user_id - so the same manager is tracked across
# seasons even though display names, team names, and rosters change year to year.
#
# Output: charts + summary written to results/league/.
# Run headless: Rscript leagueAnalytics.R   (or source in RStudio from repo root)

suppressPackageStartupMessages({
  library(tidyverse)
  library(httr2)
  library(jsonlite)
  library(ggrepel)
  library(RColorBrewer)
})

############
# Helpers  #
############
callSleeper <- function(objectId, endpoint = NULL) {
  url <- paste0("https://api.sleeper.app/v1", objectId, endpoint)
  request(url) %>%
    req_timeout(30) %>%
    req_retry(max_tries = 4, retry_on_failure = TRUE, backoff = ~ 2 ^ .x) %>%
    req_perform() %>%
    resp_body_json(simplifyDataFrame = TRUE)
}
ensure_cols <- function(df, cols) {
  miss <- setdiff(cols, names(df))
  if (length(miss)) df[miss] <- NA
  df
}

# Walk previous_league_id -> season -> {league_id, last_scored_leg}
buildLeagueChain <- function(headId) {
  chain <- list(); id <- headId
  while (!is.null(id) && !is.na(id) && nzchar(id)) {
    lg <- callSleeper(paste0("/league/", id))
    chain[[lg$season]] <- list(league_id = lg$league_id, season = lg$season,
                               last_scored_leg = lg$settings$last_scored_leg)
    id <- lg$previous_league_id
  }
  chain
}

##########
# Config #
##########
currentLeagueId <- "1252770181306929152"
sortPosition <- c("QB", "RB", "WR", "TE", "K", "DEF")
outDir <- file.path("results", "league")
dir.create(outDir, recursive = TRUE, showWarnings = FALSE)
out <- function(f) file.path(outDir, f)

leagueChain <- buildLeagueChain(currentLeagueId)
seasons <- names(leagueChain)[order(as.integer(names(leagueChain)))]
cat("League chain seasons:", paste(seasons, collapse = ", "), "\n")

# Player name/position lookup (team-independent), from the cached dump
playerDF <- readRDS("sleeperPlayerData.rds")
cleanList <- function(x, e = NA) {
  if (is.null(x)) return(NA)
  else if (is.list(x)) { if (length(x) == 0) return(e)
    else return(lapply(x, cleanList, e = e)) } else return(x)
}
playerDF <- map_dfr(cleanList(unname(playerDF)),
                    function(x) as_tibble(flatten(as.data.frame(x))))
playerInfo <- playerDF %>%
  transmute(player_id,
            player_name = if_else(position == "DEF", as.character(player_id),
                                  full_name),
            position)

#####################################
# Collect per-season, per-user data #
#####################################
# Returns: $standings (one row per roster), $rostered (distinct players per user)
collectSeason <- function(s) {
  lid <- leagueChain[[s]]$league_id
  lw  <- leagueChain[[s]]$last_scored_leg
  cat("  season", s, "league", lid, "weeks 1:", lw, "\n")

  users <- as_tibble(callSleeper(paste0("/league/", lid), "/users"),
                     .name_repair = "unique") %>%
    unnest(metadata, names_sep = "_") %>%
    rename(user_name = display_name) %>%
    ensure_cols("metadata_team_name") %>%
    transmute(user_id, user_name, team_name = metadata_team_name)
  rosters <- as_tibble(callSleeper(paste0("/league/", lid), "/rosters"),
                       .name_repair = "unique") %>%
    select(roster_id, owner_id)
  userMap <- rosters %>%
    left_join(users, by = c("owner_id" = "user_id")) %>%
    transmute(roster_id, user_id = owner_id, user_name, team_name)

  # Fetch each week's matchups once; derive both results and rostered players
  raw <- map(1:lw, function(i) {
    m <- as_tibble(callSleeper(paste0("/league/", lid, "/matchups/"), i))
    m$current_week <- i
    m
  })
  wk <- map_dfr(raw, ~ .x %>%
                  select(current_week, roster_id, matchup_id, points))
  # Head-to-head result per team-week (na_matches="never": teams with NA
  # matchup_id are eliminated/bye and get no result - no phantom matchups)
  wres <- wk %>%
    left_join(wk %>% select(current_week, matchup_id,
                            opp = roster_id, opp_points = points),
              by = c("current_week", "matchup_id"), na_matches = "never") %>%
    filter(is.na(opp) | roster_id != opp) %>%
    mutate(result = case_when(points > opp_points ~ "W",
                              points < opp_points ~ "L",
                              points == opp_points ~ "T",
                              TRUE ~ NA_character_))
  standings <- wres %>%
    group_by(roster_id) %>%
    summarise(games  = sum(!is.na(result)),
              wins   = sum(result == "W", na.rm = TRUE),
              losses = sum(result == "L", na.rm = TRUE),
              ties   = sum(result == "T", na.rm = TRUE),
              points = sum(points, na.rm = TRUE),
              .groups = "drop") %>%
    arrange(desc(wins), desc(points)) %>%
    mutate(final_position = row_number())

  # Champion from the playoff winners bracket (placement match p == 1)
  champ_rid <- tryCatch({
    wb <- as_tibble(callSleeper(paste0("/league/", lid), "/winners_bracket"))
    if ("p" %in% names(wb)) {
      fin <- wb %>% filter(p == 1)
      if (nrow(fin) > 0) as.integer(fin$w[[1]]) else NA_integer_
    } else NA_integer_
  }, error = function(e) NA_integer_)

  standings <- standings %>%
    mutate(champion = !is.na(champ_rid) & roster_id == champ_rid) %>%
    left_join(userMap, by = "roster_id") %>%
    mutate(season = s)

  # Distinct players each user rostered this season (any week)
  rostered <- map_dfr(raw, ~ tibble(roster_id = .x$roster_id,
                                     players = .x$players)) %>%
    unnest(players) %>%
    rename(player_id = players) %>%
    distinct(roster_id, player_id) %>%
    left_join(userMap %>% select(roster_id, user_id, user_name), by = "roster_id") %>%
    mutate(season = s)

  list(standings = standings, rostered = rostered)
}

cat("Collecting season data...\n")
collected   <- map(seasons, collectSeason)
allStandings <- map_dfr(collected, "standings")
allRostered  <- map_dfr(collected, "rostered")

# Canonical display name per user = their most recent season's name
canonName <- allStandings %>%
  group_by(user_id) %>%
  arrange(desc(as.integer(season))) %>%
  summarise(user_name = first(user_name), .groups = "drop")

###############################
# Career (cumulative) summary #
###############################
career <- allStandings %>%
  group_by(user_id) %>%
  summarise(seasons      = n_distinct(season),
            first_season = min(as.integer(season)),
            last_season  = max(as.integer(season)),
            wins         = sum(wins),
            losses       = sum(losses),
            ties         = sum(ties),
            points       = sum(points),
            titles       = sum(champion, na.rm = TRUE),
            best_finish  = min(final_position),
            avg_finish   = round(mean(final_position), 2),
            .groups = "drop") %>%
  mutate(win_pct      = round(wins / pmax(wins + losses + ties, 1) * 100, 1),
         avg_points   = round(points / seasons, 1),
         record       = paste0(wins, "-", losses,
                               ifelse(ties > 0, paste0("-", ties), ""))) %>%
  left_join(canonName, by = "user_id") %>%
  arrange(desc(win_pct), desc(wins)) %>%
  relocate(user_name, .before = seasons)

# Persisted summary (markdown - tracked; PNGs are gitignored artifacts)
summ <- c(
  "# DDBM League - Career Analytics",
  paste0("_Generated ", Sys.Date(), " across seasons ",
         paste(seasons, collapse = ", "), "_"), "",
  paste0("Managers (distinct user_id): ", nrow(career),
         " | Multi-season managers: ", sum(career$seasons > 1)), "",
  "## Career standings (by win %)", "",
  "| Manager | Seasons | Record | Win% | Pts | Pts/Seas | Titles | Best | Avg Finish |",
  "|---|--:|--:|--:|--:|--:|--:|--:|--:|",
  career %>%
    mutate(row = sprintf("| %s | %d (%d-%d) | %s | %.1f | %s | %.1f | %d | %d | %.2f |",
                         user_name, seasons, first_season, last_season, record,
                         win_pct, format(round(points), big.mark = ","),
                         avg_points, titles, best_finish, avg_finish)) %>%
    pull(row))
writeLines(summ, out("league-career-summary.md"))
write_csv(career, out("league-career-standings.csv"))
cat("Wrote career summary for", nrow(career), "managers\n")

# Palette big enough for all managers
managerColors <- colorRampPalette(brewer.pal(12, "Paired"))(nrow(career))
names(managerColors) <- career$user_name

#####################
# Chart 1: Career   #
#####################
careerStandings <- ggplot(
  career %>% mutate(user_name = fct_reorder(user_name, win_pct)),
  aes(x = win_pct, y = user_name, fill = user_name)) +
  geom_col(show.legend = FALSE) +
  geom_text(aes(label = sprintf("%s  |  %.1f%%  |  %s seas  |  %s pts%s",
                                record, win_pct, seasons,
                                format(round(points), big.mark = ","),
                                ifelse(titles > 0,
                                       paste0("  |  ", titles, "x champ"), ""))),
            hjust = -0.02, size = 3) +
  scale_fill_manual(values = managerColors) +
  scale_x_continuous(expand = expansion(mult = c(0, 0.45)),
                     limits = c(0, 100)) +
  labs(title = "DDBM Career Standings (All Seasons)",
       subtitle = paste0("Cumulative across ", paste(seasons, collapse = ", "),
                         " - ranked by win %"),
       x = "Career Win %", y = NULL) +
  theme_minimal()
ggsave(out("DDBMLeagueCareerStandings.png"), careerStandings,
       width = 13, height = 7, dpi = 300)

#########################################
# Chart 2: Finish trajectory by season  #
#########################################
maxPos <- max(allStandings$final_position)
trajectory <- allStandings %>%
  left_join(canonName, by = "user_id") %>%
  mutate(season = as.integer(season),
         user_name = user_name.y)
finishTrajectory <- ggplot(
  trajectory,
  aes(x = season, y = final_position, color = user_name, group = user_name)) +
  geom_line(linewidth = 1.1, alpha = 0.85) +
  geom_point(aes(shape = champion), size = 3) +
  geom_text_repel(data = trajectory %>%
                    group_by(user_name) %>% filter(season == max(season)),
                  aes(label = user_name), nudge_x = 0.15, hjust = 0,
                  size = 3, direction = "y", segment.alpha = 0.4,
                  show.legend = FALSE) +
  scale_y_reverse(breaks = 1:maxPos) +
  scale_x_continuous(breaks = sort(unique(trajectory$season)),
                     expand = expansion(mult = c(0.02, 0.18))) +
  scale_shape_manual(values = c(`FALSE` = 16, `TRUE` = 8),
                     labels = c("FALSE" = "-", "TRUE" = "Champion"),
                     name = NULL) +
  scale_color_manual(values = managerColors, guide = "none") +
  labs(title = "DDBM Finish Trajectory by Season",
       subtitle = "Final table position each season (1 = top). Stars = league champion (playoff bracket winner).",
       x = "Season", y = "Final Table Position") +
  theme_minimal()
ggsave(out("DDBMLeagueFinishTrajectory.png"), finishTrajectory,
       width = 12, height = 7, dpi = 300)

############################################
# Chart 3: Points per season per manager   #
############################################
pointsPerSeason <- allStandings %>%
  left_join(canonName, by = "user_id") %>%
  mutate(user_name = user_name.y)
ptsChart <- ggplot(pointsPerSeason,
                   aes(x = factor(season), y = points, fill = user_name)) +
  geom_col(position = position_dodge2(preserve = "single"), width = 0.85) +
  geom_text(aes(label = round(points)),
            position = position_dodge2(width = 0.85, preserve = "single"),
            vjust = -0.3, size = 2.4) +
  scale_fill_manual(values = managerColors, name = "Manager") +
  scale_y_continuous(expand = expansion(mult = c(0, 0.08))) +
  labs(title = "DDBM Points Scored per Season",
       subtitle = "Each manager's total points by season",
       x = "Season", y = "Total Points") +
  theme_minimal()
ggsave(out("DDBMLeaguePointsPerSeason.png"), ptsChart,
       width = 14, height = 7, dpi = 300)

##################################################
# Chart 4: Manager-player loyalty across seasons #
##################################################
# Players the SAME user rostered across multiple seasons (year-over-year keeps)
loyalty <- allRostered %>%
  group_by(user_id, player_id) %>%
  summarise(seasons_kept = n_distinct(season),
            season_list  = paste(sort(unique(season)), collapse = ", "),
            .groups = "drop") %>%
  filter(seasons_kept >= 2) %>%
  left_join(playerInfo, by = "player_id") %>%
  left_join(canonName, by = "user_id") %>%
  filter(!is.na(player_name)) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(desc(seasons_kept), user_name, player_name)

# Genuine multi-year keeps (>= 3 seasons); 2-season keeps are too many to be
# meaningful. Fall back to the top 20 by tenure if very few reach 3 seasons.
loyaltyTop <- loyalty %>% filter(seasons_kept >= 3)
if (nrow(loyaltyTop) < 8) {
  loyaltyTop <- loyalty %>%
    slice_max(order_by = seasons_kept, n = 20, with_ties = FALSE)
}
loyaltyChart <- ggplot(
  loyaltyTop %>%
    mutate(lbl = paste0(player_name, "  (", user_name, ")"),
           lbl = fct_reorder(lbl, seasons_kept)),
  aes(x = seasons_kept, y = lbl, fill = user_name)) +
  geom_col() +
  geom_text(aes(label = season_list), hjust = -0.04, size = 3) +
  scale_fill_manual(values = managerColors, name = "Manager") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.5)),
                     breaks = seq_len(length(seasons)), limits = c(0, NA)) +
  labs(title = "Manager-Player Loyalty Across Seasons",
       subtitle = paste0("Players a manager re-rostered in 3+ seasons (",
                         nrow(loyaltyTop), " keeps)"),
       x = "Seasons Rostered by Same Manager", y = NULL) +
  theme_minimal()
ggsave(out("DDBMLeaguePlayerLoyalty.png"), loyaltyChart,
       width = 12, height = max(5, 0.32 * nrow(loyaltyTop) + 1.5), dpi = 300)

cat("\nLeague analytics written to ", normalizePath(outDir), ":\n", sep = "")
cat(" - DDBMLeagueCareerStandings.png\n - DDBMLeagueFinishTrajectory.png\n",
    "- DDBMLeaguePointsPerSeason.png\n - DDBMLeaguePlayerLoyalty.png\n",
    "- league-career-summary.md\n - league-career-standings.csv\n", sep = "")
