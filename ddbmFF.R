# DDBM Fantasy Football Stat Tracker
# ddbmFF.R

# The goal of this project is to retrieve Sleeper data and derive fun factoids
# & analytics about the DDBM Redraft League, including trends, patterns,
# and other interesting metrics and (eventually) display them in visualizations

# User Trends & Overall Performances:
# 1) Best & Worst Overall Roster
#      Best & Worst drafted rosters from week 1
#      Total Possible Win/Loss against league (not just weekly opponent)
#      Max Points possible including Bench (possible W/L Rate changes)
#      Best/worst starters/benches week-to-week
#      Unluckiest User (most injuries to roster)
# 2) Transfer Market Performance
#      Waiver churn activity: More or less = win or loss?
#      Waiver/Trade Winners & Losers
#      Most/least Scammy/Scammazed Traders
#      Best F/A Mover (points gained from F/A activity)
#      Player position hoarding preferences
#      Most Activity targeting player positions from F/A
# 3) Strategic Users
#      Lowest point differential in wins, highest in losses(?)
#      Includes bench swap potentials
#      Starting boom players, benching when potentially busting
#      Matchup-predictors
#      Best Boom/Breakout, Worst Hype Predictor Users
# 4) Table Position Movers
#      Most steady/least changing table performances
#      Best/worst Scalers
#      Least consistent (Up-Down-Up-Down)
# 5) Specialist Coaches
#      Best/worst overall holder of QBs/RBs/WRs/TEs/Ks/Ds by points
#      Best/worst Thu/Sun/Mon player performers (players/users)
#      Best/worst weekly position streamer by points (Week 1, Week 2, etc.)
#      Best/worst bench users (more/less points on bench players than starters)
#      Most Players by same NFL teams in one roster

###########################
# Install & Load Packages #
###########################
# # Base Packages:
# install.packages("tidyverse")
# install.packages("ggrepel")
# install.packages("httr2")
# install.packages("jsonlite")
# install.packages("rjson")
# install.packages("ggplot2")
# install.packages("treemapify")
# install.packages("tidytext")
# install.packages("patchwork")
# # nflverse packages:
# install.packages("nflverse")
# install.packages("nflreadr")
# install.packages("nflfastR")
# install.packages("nflplotR")
# install.packages("nfl4th")
# install.packages("nflseedR")
# Modeling Packages:
# install.packages("tidyverse")
# install.packages("corrplot")
# install.packages("olsrr")
# install.packages("rpart.plot")
# install.packages("e1071")

# Load Packages
library(tidyverse)
library(dplyr)
library(purrr)
library(httr2)
library(jsonlite)
library(rjson)
library(ggrepel)
library(tibble)
library(ggplot2)
library(treemapify)
library(tidytext)
library(patchwork)
library(RColorBrewer)
# nflverse specific
library(nflverse)
library(nflreadr)
library(nflfastR)
library(nflplotR)
library(nfl4th)
library(nflseedR)
# Modeling Packages
library(tidyverse)
library(corrplot)
library(olsrr)
library(class)
library(scales)
library(rpart)
library(rpart.plot)
library(e1071)

##########################
# Sleeper API Call setup #
##########################
# Base URL = "https://api.sleeper.app/v1"
callSleeper <- function(objectId, endpoint = NULL) {
  url <- paste0("https://api.sleeper.app/v1",objectId,endpoint)
  cat("\nSleeper API URL:",url,"\n")
  resp <- request(url) %>%
    req_perform()
  respData <- resp |>
    resp_body_json(simplifyDataFrame = TRUE)
    # resp_body_json(simplifyVector = TRUE)
    # resp_body_string()

  # respData <- fromJSON(respData)
  return(respData)
}
#####################################
##### Sample calls useful later #####
# ### Individual User DF ###
# # (LuckyHarm) User ID = 656711573536088064
# objectId = "/user/656711573536088064"
# endpoint = "/leagues/nfl/2025"
# respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
# userDF <- Filter(function(x) !any(is.na(x)), respDF)
# # view(userDF)
# ### Matchups DF ###
# objectId = "/league/1252770181306929152"
# endpoint = "/matchups/1"
# respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
# matchupDF <- Filter(function(x) !any(is.na(x)), respDF)
# # view(matchupDF)
#####################################

#############################
# General Sleeper Stat Data #
#############################
# Initial linking data to be used in conjunction with League-specific data

##### Current NFL State DF #####
# Retrieves the current NFL season progress (current week, year, season, etc.)
objectId = "/state"
endpoint = "/nfl"
respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
currentSeason <- Filter(function(x) !any(is.na(x)), respDF)
# view(currentSeason)

##### Player Fetch DF #####
# Retrieves Player data for all players in the Sleeper Database & stores in RDS
# Largest Data set - To be merged with other DFs for linking purposes
# setwd("~/Data/FantasyFootball")
playerFilename <- "sleeperplayerData.rds"
playerDF <- readRDS(playerFilename)
fileDate <- as.Date(file.info(playerFilename)$mtime)
today = Sys.Date()
if (fileDate == today) {
  print("Player data already retrieved for today, skipping API retrieval.")
} else {
  print("Data not up-to-date, retrieving new data...")
  objectId = "/players"
  endpoint = "/nfl"
  respDF <- callSleeper(objectId,endpoint)
  saveRDS(respDF, file=playerFilename)
  playerDF <- respDF
}
## Replace all NULLs & empty List elements with NAs
cleanList <- function(x, emptyListAs = NA) {
  if (is.null(x)) {
    return(NA)
  } else if (is.list(x)) {
    if (length(x) == 0) {
      return(emptyListAs)
    } else {
      return(lapply(x, cleanList, emptyListAs = emptyListAs))
    }
  } else {
    return(x)
  }
}
players <- unname(playerDF)
cleanPlayers <- cleanList(players)
playerDF <- map_dfr(cleanPlayers, function(x) {
  flat <- flatten(as.data.frame(x))
  as_tibble(flat)
})
# view(playerDF)

## Select relevant columns for initial Player Mapping frame
selectPlayers <- playerDF %>%
  select(c(
    "player_id",player_name = "full_name","age","height","weight",
    "position","years_exp","team","status"))
# view(selectPlayers)

## Remove players not on Teams & add Team names to player_name column
sortPosition <- c("QB","RB","WR","TE","K","DEF")
playerMap <- selectPlayers %>%
  filter(!is.na(team)) %>%
  mutate(player_name = if_else(
    position == "DEF", as.character(player_id), player_name)) %>%
  arrange(match(position, sortPosition), as.numeric(player_id))
# view(playerMap)

########################
# League Specific Data #
########################

##### League Rosters DF #####
# Gets latest rosters for DDBM Redraft League
# League ID = "1252770181306929152"
objectId = "/league/1252770181306929152"
endpoint = "/rosters"

respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
# rosterDF <- Filter(function(x) !any(is.na(x)), respDF)
rosterDF <- respDF %>%
  unnest_wider(settings, names_sep = NULL) %>%
  unnest_wider(metadata, names_sep = NULL) %>%
  select(where(~ !any(is.na(.))))
# view(rosterDF)

##### Users DF #####
# Fix and add user_id & user-name/display_name
objectId = "/league/1252770181306929152"
endpoint = "/users"

respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
userDF <- respDF %>%
  unnest(metadata, names_sep = "_") %>%
  rename(user_name = display_name, team_name = metadata_team_name)
userDF <- userDF %>%
  select(where(~ !any(is.na(.)))) %>%
  select(league_id, user_id, user_name, team_name)
# view(userDF)

##### Map Usernames to User IDs #####
fullRosterDF <- merge(rosterDF, userDF, by.x="owner_id", by.y="user_id") %>%
  rename(user_id = owner_id) %>%
  relocate(league_id.x, roster_id, user_id, user_name, .before = record) %>%
  arrange(roster_id)
userMap <- fullRosterDF %>%
  select(league_id = league_id.x, roster_id, user_id, user_name, team_name)
# view(userMap)

##### Aggregates all Matchup results for each week #####
objectId = "/league/1252770181306929152/matchups/"
# currentWeek = currentSeason$week
currentWeek = 18
matchupResults = data.frame()
playerRoster = data.frame()
playerPoints = data.frame()
matchupList = vector("list", length = currentWeek)
playerList = vector("list", length = currentWeek)
pointsList = vector("list", length = currentWeek)
for (i in 1:(currentWeek)) {
  endpoint = i
  respDF <- as_tibble(callSleeper(objectId,endpoint))
  respDF$current_week <- i
  respDF <- respDF %>%
    relocate(current_week, roster_id, matchup_id, .before = points)
  weekDF <- respDF %>%
    left_join(respDF %>%
                select(current_week, matchup_id, roster_id, points) %>%
                rename(opp_id = roster_id, opp_points = points),
              by = c("current_week", "matchup_id")) %>%
    filter(roster_id != opp_id) %>%
    mutate(result = case_when(points > opp_points ~ "W",
                              points < opp_points ~ "L",
                              points == opp_points ~ "T")) %>%
    select(-"opp_id", -"opp_points", -"custom_points",
           -"players_points", -"starters_points") %>%
    relocate(result, .before = points)

  # pointsDF <- respDF %>%
  #   select(c("current_week","players_points"))
  pointsDF <- respDF$players_points
  newPointsDF <- pointsDF %>%
    pivot_longer(
      cols = everything(),
      names_to = "player_id",
      values_to = "player_points"
    )
  newPointsDF$current_week <- i
  newPointsDF <- newPointsDF %>%
    relocate(current_week, .before = player_id) %>%
    arrange(current_week, player_id) %>%
    drop_na()

  playersDF <- weekDF[c("current_week","roster_id")]
  playersDF$players <- Map(c,weekDF$players, weekDF$starters)
  startingPlayers <- Map(function(current_week, roster_id, players, starters) {
    tibble(
      current_week = current_week,
      roster_id = roster_id,
      player_id = players,
      is_starter = players %in% starters
    )
  }, weekDF$current_week, weekDF$roster_id, weekDF$players, weekDF$starters)
  newPlayersDF <- bind_rows(startingPlayers)
  newPlayersDF <- newPlayersDF %>%
    arrange(roster_id, desc(is_starter), as.numeric(player_id))

  matchupList[[i]] <- weekDF
  playerList[[i]] <- newPlayersDF
  pointsList[[i]] <- newPointsDF
}

matchupResults = do.call(rbind, matchupList)
matchupResults <- matchupResults %>%
  group_by(roster_id) %>%
  rename(weekly_points = points) %>%
  mutate(wins = cumsum(result == "W"),
         losses = cumsum(result == "L"),
         current_record = paste0(wins, "-", losses),
         total_points = cumsum(weekly_points),
  ) %>%
  ungroup() %>%
  group_by(current_week) %>%
  arrange(desc(wins), desc(total_points), .by_group = TRUE) %>%
  mutate(table_position = row_number()) %>%
  ungroup() %>%
  relocate(wins, losses, current_record, table_position, .after = result) %>%
  select(-players, -starters) %>%
  left_join(userMap %>% select(roster_id, user_name), by = "roster_id") %>%
  relocate(user_name, .after = roster_id) %>%
  arrange(current_week, table_position)

playerPoints <- do.call(rbind, pointsList)
playerPoints <- playerPoints %>%
  left_join(playerMap %>% select(player_id, position), by = "player_id") %>%
  arrange(current_week, match(position, sortPosition),
          as.numeric(player_id))

playerRoster = do.call(rbind, playerList)
# view(matchupResults)
# view(playerPoints)
# view(playerRoster)


### Full list of weekly rosters for each DDBM User
DDBMRosters <- playerRoster %>%
  full_join(playerPoints, by = c("current_week", "player_id")) %>%
  left_join(playerMap %>% select(player_id, player_name),
            by = "player_id") %>%
  left_join(userMap %>% select(roster_id, user_id, user_name),
            by = c("roster_id"))
DDBMRosters <- DDBMRosters %>%
  select(
    current_week,
    roster_id,
    user_name,
    player_id,
    player_name,
    position,
    player_points,
    is_starter) %>%
  arrange(current_week, roster_id, desc(is_starter),
          match(position, sortPosition), as.numeric(player_id))
# view(DDBMRosters)

### Check if any data is missing
# view(filter(playerMap, if_any(everything(), is.na)))
## Get row number for missing data instances
DDBMRosters %>%
  mutate(row_number = row_number()) %>%
  filter(if_any(everything(), is.na)) %>%
  View()

### Manually add players here
## PlayerIDs:
## 6083 - Matt Gay
## 4666 - Younghoe Koo

# ## Add Joshua Karty (LAR -> released -> LAR) (K)
# ## - Row 826
# DDBMRosters[826, c("position", "player_name")] <- list("K", "Joshua Karty")
#
# ## Add Chris Moore (WAS -> released -> WAS) (WR)
# ## - Rows (1145,1328)
# DDBMRosters[c(1145, 1328),
#             c("position", "player_name")] <- list("WR","Chris Moore")
#
## Add Michael Badgley (IND -> BUF -> released) (K)
## - Row 1872
DDBMRosters[1672, c("position", "player_name")] <- list("K","Michael Badgley")

## Add Younghoe Koo (ATL -> NYG -> released) (K)
## - Row 130
DDBMRosters[130, c("position", "player_name")] <- list("K","Younghoe Koo")
## Add Matt Gay (WAS -> SF -> released) (K)
## - Rows (78,251,425,600,774,951,1127,1972,2148)
DDBMRosters[c(78,251,425,600,774,951,1127,1972,2148),
            c("position", "player_name")] <- list("K","Matt Gay")

##### Transactions DF #####
# objectId = "/league/1252770181306929152"
# endpoint = "/transactions/1"
# respDF <- as_tibble(callSleeper(objectId,endpoint), .name_repair = "unique")
objectId = "/league/1252770181306929152/transactions/"
# currentWeek = currentSeason$week
currentWeek = 18
transactionList = vector("list", length = currentWeek)
for (i in 1:(currentWeek)) {
  endpoint = i
  respDF <- as_tibble(callSleeper(objectId,endpoint))
  weeklyTransactions <- respDF
  weeklyTransactions$current_week <- i
  transactionList[[i]] <- weeklyTransactions
}
transactionsDF = do.call(bind_rows, transactionList)
transactionsDF <- transactionsDF %>% select(-c(
  "created","draft_picks","status_updated","leg","waiver_budget"))
transactionsDF <- merge(transactionsDF, userDF, by.x="creator", by.y="user_id")
transactionsDF <- transactionsDF %>%
  relocate(current_week, transaction_id, roster_ids, consenter_ids,
           creator, user_name, .before = status)
transactionsDF <- transactionsDF[order(transactionsDF$transaction_id),]
# view(transactionsDF)

## Alter columns to transaction types (adds/drops)
## Join player_names from playerMap
## Splice out trades (see below)
## View(filter(allTransactionsDF, type == "trade"))
allTransactionsDF <- transactionsDF %>%
  pivot_longer(cols = c(adds, drops),
               names_to = "transaction",
               values_to = "player_df") %>%
  rowwise() %>%
  mutate(player_df = list({
    df <- player_df
    if (is.null(df) || nrow(df) == 0) {
      tibble(player_id = character(), target_roster = character())
    } else {
      tibble(player_id = names(df), target_roster = unlist(df))
    }})) %>%
  ungroup() %>%
  unnest(player_df) %>%
  filter(!is.na(player_id) & !is.na(target_roster)) %>%
  left_join(playerMap %>% select(player_id, player_name), by = "player_id") %>%
  unnest_wider(metadata, names_sep = ".") %>%
  rename(system_msg = metadata.notes) %>%
  unnest_wider(settings, names_sep = ".") %>%
  rename(order_seq = settings.seq,
       waiver_bid = settings.waiver_bid,
       user_id = creator) %>%
  select(-settings.expires_at, -settings.is_counter, -consenter_ids) %>%
  relocate(target_roster, order_seq, waiver_bid, status, system_msg,
           .after = player_name) %>%
  mutate(
    user_id = recode(as.character(target_roster),
                     !!!setNames(userMap$user_id, userMap$roster_id)),
    user_name = recode(as.character(target_roster),
                       !!!setNames(userMap$user_name, userMap$roster_id))
  ) %>%
  select(-league_id, -team_name) %>%
  arrange(current_week, order_seq, transaction_id,
          target_roster, desc(transaction))
# view(allTransactionsDF)

#####
# Relevant view Tables:
# view(rosterDF)
# view(playerMap)
# view(userMap)
# view(currentSeason)
# view(playerPoints)
# view(matchupResults)
# view(filter(matchupResults, roster_id == 1))
# view(DDBMRosters)
# view(filter(DDBMRosters, current_week == "12")
# view(allTransactionsDF)
# view(filter(allTransactionsDF, type == "trade"))
#####

# User Trends & Overall Performances:
# 1) Best & Worst Overall Roster
#      Best & Worst drafted rosters from week 1
#      Total Possible Win/Loss against league (not just weekly opponent)
#      Max Points possible including Bench (possible W/L Rate changes)
#      Best/worst starters/benches week-to-week
#      Unluckiest User (most injuries to roster)
# 2) Transfer Market Performance
#      Waiver churn activity: More or less = win or loss?
#      Waiver/Trade Winners & Losers
#      Most/least Scammy/Scammazed Traders
#      Best F/A Mover (points gained from F/A activity)
#      Player position hoarding preferences
#      Most Activity targeting player positions from F/A
# 3) Strategic Users
#      Lowest point differential in wins, highest in losses(?)
#      Includes bench swap potentials
#      Starting boom players, benching when potentially busting
#      Matchup-predictors
#      Best Boom/Breakout, Worst Hype Predictor Users
# 4) Table Position Movers
#      Most steady/least changing table performances
#      Best/worst Scalers
#      Least consistent (Up-Down-Up-Down)
# 5) Specialist Coaches
#      Best/worst overall holder of QBs/RBs/WRs/TEs/Ks/Ds by points
#      Best/worst Thu/Sun/Mon player performers (players/users)
#      Best/worst weekly position streamer by points (Week 1, Week 2, etc.)
#      Best/worst bench users (more/less points on bench players than starters)
#      Most Players by same NFL teams in one roster

#####
# 1) Plot out current season matchups by week
#       -matchupResults
#       -current_week, roster_id, record, points
#   a) Line chart of league table position changes
#       -matchupResults
#       -current_week, roster_id, table_position
#   b) Bar chart of Team weekly points
#       -DDBMRosters, matchupResults
#       -current_week, roster_id, points
#   c) Roster breakdown of players by points/position/starter, league averages
#       -playerPoints, DDBMRosters
#       -current_week, roster_id, player_points, weekly_points, position
#   d) Best Teams of the Week by players
#   e) Individual weekly roster breakdowns
#   f) Playoff team differentials
#   g) Closest matchup performances (pf vs pa)
#####

# Manually remove current week if Matchup set is incomplete & Sort Positions
# prePlayoffWeeks = 15
# endOfSeasonWeek = 18
# latestWeek = currentSeason$week
latestWeek = 18
FilterMatchupResults <- matchupResults %>%
  filter(current_week != latestWeek)
FilterPlayerPoints <- playerPoints %>%
  filter(current_week != latestWeek) %>%
  mutate(position = factor(position, levels = sortPosition))
FilterDDBMRosters <- DDBMRosters %>%
  filter(current_week != latestWeek) %>%
  mutate(position = factor(position, levels = sortPosition))
FilterAllTransactions <- allTransactionsDF %>%
  filter(current_week != latestWeek)
# view(FilterMatchupResults)
# view(FilterPlayerPoints)
# view(FilterDDBMRosters)
# view(FilterAllTransactions)
# view(filter(FilterDDBMRosters, if_any(everything(), is.na)))

### Get all Players of the Week & determine who rosters had the most of these
benchOfTheWeek <- {
  base <- FilterDDBMRosters %>%
    filter(is_starter == FALSE) %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(n_per_position = case_when(position == "QB"  ~ 1L,
                                      position == "RB"  ~ 2L,
                                      position == "WR"  ~ 2L,
                                      position == "TE"  ~ 1L,
                                      position == "K"   ~ 1L,
                                      position == "DEF" ~ 1L,
                                      TRUE              ~ 0L),
           pos_rank = row_number()) %>%
    filter(pos_rank <= n_per_position) %>%
    ungroup()
  flex_candidates <- FilterDDBMRosters %>%
    filter(is_starter == FALSE & position %in% c("RB", "WR", "TE")) %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(pos_rank = row_number()) %>%
    ungroup() %>%
    anti_join(base, by = c("current_week", "player_id"))
  flex <- flex_candidates %>%
    group_by(current_week) %>%
    slice_max(order_by = player_points, n = 1, with_ties = FALSE) %>%
    mutate(position = "FLEX") %>%
    ungroup()
  bind_rows(base, flex) %>%
    arrange(current_week,
            match(position, c("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")),
            desc(player_points)) %>%
    select(current_week, position, player_name, player_points, user_name)
}
# view(benchOfTheWeek)

startersOfTheWeek <- {
  base <- FilterDDBMRosters %>%
    filter(is_starter == TRUE) %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(n_per_position = case_when(position == "QB"  ~ 1L,
                                      position == "RB"  ~ 2L,
                                      position == "WR"  ~ 2L,
                                      position == "TE"  ~ 1L,
                                      position == "K"   ~ 1L,
                                      position == "DEF" ~ 1L,
                                      TRUE              ~ 0L),
           pos_rank = row_number()) %>%
    filter(pos_rank <= n_per_position) %>%
    ungroup()
  flex_candidates <- FilterDDBMRosters %>%
    filter(is_starter == TRUE & position %in% c("RB", "WR", "TE")) %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(pos_rank = row_number()) %>%
    ungroup() %>%
    anti_join(base, by = c("current_week", "player_id"))
  flex <- flex_candidates %>%
    group_by(current_week) %>%
    slice_max(order_by = player_points, n = 1, with_ties = FALSE) %>%
    mutate(position = "FLEX") %>%
    ungroup()
  bind_rows(base, flex) %>%
    arrange(current_week,
            match(position, c("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")),
            desc(player_points)) %>%
    select(current_week, position, player_name, player_points, user_name)
}
# view(startersOfTheWeek)

playersOfTheWeek <- {
  base <- FilterDDBMRosters %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(n_per_position = case_when(position == "QB"  ~ 1L,
                                      position == "RB"  ~ 2L,
                                      position == "WR"  ~ 2L,
                                      position == "TE"  ~ 1L,
                                      position == "K"   ~ 1L,
                                      position == "DEF" ~ 1L,
                                      TRUE              ~ 0L),
           pos_rank = row_number()) %>%
    filter(pos_rank <= n_per_position) %>%
    ungroup()
  flex_candidates <- FilterDDBMRosters %>%
    filter(position %in% c("RB", "WR", "TE")) %>%
    group_by(current_week, position) %>%
    arrange(desc(player_points), .by_group = TRUE) %>%
    mutate(pos_rank = row_number()) %>%
    ungroup() %>%
    anti_join(base, by = c("current_week", "player_id"))
  flex <- flex_candidates %>%
    group_by(current_week) %>%
    slice_max(order_by = player_points, n = 1, with_ties = FALSE) %>%
    mutate(position = "FLEX") %>%
    ungroup()
  bind_rows(base, flex) %>%
    arrange(current_week,
            match(position, c("QB", "RB", "WR", "TE", "FLEX", "K", "DEF")),
            desc(player_points)) %>%
    select(current_week, position, player_name, player_points, user_name)
}
# view(playersOfTheWeek)


bestOfTheWeekStats <- {
  benchSummary <- benchOfTheWeek %>%
    group_by(current_week) %>%
    summarise(
      bench_total_points = sum(player_points, na.rm = TRUE),
      bench_qb_points  = sum(player_points[position == "QB"],  na.rm = TRUE),
      bench_rb_points  = sum(player_points[position == "RB"],  na.rm = TRUE),
      bench_wr_points  = sum(player_points[position == "WR"],  na.rm = TRUE),
      bench_te_points  = sum(player_points[position == "TE"],  na.rm = TRUE),
      bench_k_points   = sum(player_points[position == "K"],   na.rm = TRUE),
      bench_def_points = sum(player_points[position == "DEF"], na.rm = TRUE),
      bench_flex_points = sum(player_points[position == "FLEX"], na.rm = TRUE),
      bench_top_team = names(sort(table(user_name), decreasing = TRUE))[1],
      bench_top_team_points = sum(player_points[user_name ==
                                                  names(sort(table(user_name), decreasing = TRUE))[1]], na.rm = TRUE)
    )
  starterSummary <- startersOfTheWeek %>%
    group_by(current_week) %>%
    summarise(
      starter_total_points = sum(player_points, na.rm = TRUE),
      starter_qb_points  = sum(player_points[position == "QB"],  na.rm = TRUE),
      starter_rb_points  = sum(player_points[position == "RB"],  na.rm = TRUE),
      starter_wr_points  = sum(player_points[position == "WR"],  na.rm = TRUE),
      starter_te_points  = sum(player_points[position == "TE"],  na.rm = TRUE),
      starter_k_points   = sum(player_points[position == "K"],   na.rm = TRUE),
      starter_def_points = sum(player_points[position == "DEF"], na.rm = TRUE),
      starter_flex_points = sum(player_points[position == "FLEX"], na.rm = TRUE),
      starter_top_team = names(sort(table(user_name), decreasing = TRUE))[1],
      starter_top_team_points = sum(player_points[user_name ==
                                                    names(sort(table(user_name), decreasing = TRUE))[1]], na.rm = TRUE)
    )
  playerSummary <- playersOfTheWeek %>%
    group_by(current_week) %>%
    summarise(
      potw_total_points = sum(player_points, na.rm = TRUE),
      potw_qb_points  = sum(player_points[position == "QB"],  na.rm = TRUE),
      potw_rb_points  = sum(player_points[position == "RB"],  na.rm = TRUE),
      potw_wr_points  = sum(player_points[position == "WR"],  na.rm = TRUE),
      potw_te_points  = sum(player_points[position == "TE"],  na.rm = TRUE),
      potw_k_points   = sum(player_points[position == "K"],   na.rm = TRUE),
      potw_def_points = sum(player_points[position == "DEF"], na.rm = TRUE),
      potw_flex_points = sum(player_points[position == "FLEX"], na.rm = TRUE),
      potw_top_team = names(sort(table(user_name), decreasing = TRUE))[1],
      potw_top_team_points = sum(player_points[user_name ==
                                                 names(sort(table(user_name), decreasing = TRUE))[1]], na.rm = TRUE)
    )
  benchSummary %>%
    full_join(starterSummary, by = "current_week") %>%
    full_join(playerSummary, by = "current_week")
}
# view(bestOfTheWeekStats)


### Get cummulative player performances
playerRosterPerformances <- FilterDDBMRosters %>%
  group_by(position, player_name) %>%
  summarise(
    teams_rostered = n_distinct(roster_id),
    total_weeks_rostered = n(),
    total_weeks_started  = sum(is_starter, na.rm = TRUE),
    total_points = sum(player_points, na.rm = TRUE),
    total_average_points = round(total_points / total_weeks_rostered, 2),
    total_starter_points = sum(player_points[is_starter == TRUE], na.rm = TRUE),
    total_bench_points = sum(player_points[is_starter == FALSE], na.rm = TRUE),
    .groups = "drop") %>%
  left_join(
    FilterDDBMRosters %>%
      group_by(position, player_name, user_name) %>%
      summarise(
        team_weeks_rostered = n_distinct(current_week),
        team_weeks_started = sum(is_starter, na.rm = TRUE),
        team_roster_points = sum(player_points, na.rm = TRUE),
        team_average_points = round(team_roster_points / team_weeks_rostered, 2),
        team_starter_points = sum(player_points[is_starter == TRUE],
                                   na.rm = TRUE),
        team_bench_points = sum(player_points[is_starter == FALSE],
                                   na.rm = TRUE),
        .groups = "drop"),
    by = c("position", "player_name")) %>%
  relocate(user_name, .after = teams_rostered) %>%
  mutate(
    total_roster_share = round((team_weeks_rostered / total_weeks_rostered) * 100, 2),
    team_points_share = round((team_roster_points / total_points) * 100, 2),
    point_pct_diff = round(team_points_share - total_roster_share, 2),
    team_starter_share = ifelse(total_starter_points > 0,
                                round((team_starter_points / total_starter_points) * 100, 2), 0),
    actual_diff = ifelse(total_starter_points > 0, round(team_starter_share - total_roster_share, 2), 0)) %>%
  relocate(total_roster_share, team_points_share, point_pct_diff,
           team_starter_share, actual_diff, .after = user_name) %>%
  arrange(position, player_name, desc(total_weeks_rostered),
          desc(teams_rostered), desc(total_points),
          desc(total_roster_share),desc(team_points_share))
# view(playerRosterPerformances)


## Diverging plot of differences in shared player points between 2 teams
# view(filter(playerRosterPerformances, teams_rostered == 2))
playerPerformance2Actual <- ggplot(playerRosterPerformances %>%
         filter(teams_rostered == 2 &
                  player_name %in% (playerRosterPerformances %>%
                                      filter(teams_rostered == 2) %>%
                                      arrange(desc(total_points)) %>%
                                      distinct(player_name, total_points) %>%
                                      slice_head(n = 20) %>%
                                      pull(player_name))) %>%
         mutate(diff_sign = ifelse(actual_diff < 0, "negative", "positive"),
                diff_sign = fct_relevel(diff_sign, "negative", "positive")),
       aes(x = actual_diff,
           y = fct_reorder(player_name, total_points, .desc = TRUE),
           fill = user_name,
           group = diff_sign)) +
  geom_bar(stat = "identity", position = "dodge") +
  geom_vline(xintercept = 0, color = "black", linetype = "dashed") +
  geom_text(aes(
    x = ifelse(actual_diff > 0, actual_diff + 0.05, actual_diff - 0.05),
    y = ifelse(diff_sign == "positive",
               as.numeric(fct_reorder(player_name, total_points,
                                      .desc = TRUE)) + 0.25,
               as.numeric(fct_reorder(player_name, total_points,
                                      .desc = TRUE)) - 0.25),
    label = paste0(round(actual_diff, 1), "% (",
                               round(team_starter_points, 1), " pts)"),
    hjust = ifelse(actual_diff > 0, 0, 1)),
    size = 3,
    color = "black") +
  scale_fill_manual(values = brewer.pal(10, "Paired")) +
  scale_x_continuous(expand = expansion(mult = c(0.5, 0.5))) +
  labs(title = "Player Performances Across Multiple Teams (2)",
       x = "Actual Point % Diff (Starter Pts)",
       y = "Player") +
  theme_minimal()

playerPerformance2Potential <- ggplot(playerRosterPerformances %>%
         filter(teams_rostered == 2 &
                  player_name %in% (
                    playerRosterPerformances %>%
                      filter(teams_rostered == 2) %>%
                      arrange(desc(total_points)) %>%
                      distinct(player_name, total_points) %>%
                      slice_head(n = 20) %>%
                      pull(player_name))) %>%
         mutate(diff_sign = ifelse(point_pct_diff < 0, "negative", "positive"),
                diff_sign = fct_relevel(diff_sign, "negative", "positive")),
       aes(x = point_pct_diff,
           y = fct_reorder(player_name, total_points, .desc = TRUE),
           fill = user_name,
           group = diff_sign)) +
  geom_bar(stat = "identity", position = "dodge") +
  geom_vline(xintercept = 0, color = "black", linetype = "dashed") +
  geom_text(aes(
    x = ifelse(point_pct_diff > 0, point_pct_diff + 0.05, point_pct_diff - 0.05),
    y = ifelse(diff_sign == "positive",
               as.numeric(fct_reorder(player_name, total_points,
                                      .desc = TRUE)) + 0.25,
               as.numeric(fct_reorder(player_name, total_points,
                                      .desc = TRUE)) - 0.25),
    label = paste0(round(point_pct_diff, 1), "% (",
                   round(team_roster_points, 1), " pts)"),
    hjust = ifelse(point_pct_diff > 0, 0, 1)),
    size = 3,
    color = "black") +
  scale_fill_manual(values = brewer.pal(10, "Paired")) +
  scale_x_continuous(expand = expansion(mult = c(0.5, 0.5))) +
  labs(title = "Player Performances Across Multiple Teams (2)",
       x = "Potential Point % Share (Total Pts)",
       y = "Player") +
  theme_minimal()
playerPerformance2Chart <- (playerPerformance2Actual | playerPerformance2Potential) + plot_layout(guides = "collect")
playerPerformance2Chart
ggsave("DDBMPlayerPerformance2Chart.png", playerPerformance2Chart,
       width = 24, height = 8, dpi = 300)

## Diverging plot of differences in shared player points earned per team (3+)
# view(filter(playerRosterPerformances, teams_rostered > 2))
playerPerformance3Actual <- ggplot(playerRosterPerformances %>%
         filter(teams_rostered > 2) %>%
         mutate(diff_sign = ifelse(actual_diff < 0, "negative", "positive"),
                diff_sign = fct_relevel(diff_sign, "negative", "positive")),
       aes(x = actual_diff,
           y = fct_reorder(player_name, total_points, .desc = TRUE),
           fill = user_name)) +
  geom_bar(stat = "identity", position = position_dodge(width = 0.9)) +
  geom_vline(xintercept = 0, color = "black", linetype = "dashed") +
  geom_text(aes(label = paste0(round(actual_diff, 1), "% (",
                               round(team_starter_points, 1), " pts)"),
                hjust = ifelse(actual_diff > 0, -0.15, 1.15)),
            position = position_dodge(width = 0.9),
            color = "black",
            size = 3) +
  scale_fill_manual(values = brewer.pal(10, "Paired"), name = "Team") +
  scale_x_continuous(expand = expansion(mult = c(0.5, 0.5))) +
  labs(title = "Player Performances Across Multiple Teams (3+)",
       x = "Actual Point % Diff (Starter Pts)",
       y = "Player") +
  theme_minimal()

playerPerformance3Potential <- ggplot(playerRosterPerformances %>%
         filter(teams_rostered > 2) %>%
         mutate(diff_sign = ifelse(point_pct_diff < 0, "negative", "positive"),
                diff_sign = fct_relevel(diff_sign, "negative", "positive")),
       aes(x = point_pct_diff,
           y = fct_reorder(player_name, total_points, .desc = TRUE),
           fill = user_name)) +
  geom_bar(stat = "identity", position = position_dodge(width = 0.9)) +
  geom_vline(xintercept = 0, color = "black", linetype = "dashed") +
  geom_text(aes(label = paste0(round(point_pct_diff, 1), "% (",
                               round(team_roster_points, 1), " pts)"),
                hjust = ifelse(point_pct_diff > 0, -0.15, 1.15)),
            position = position_dodge(width = 0.9),
            color = "black",
            size = 3) +
  scale_fill_manual(values = brewer.pal(10, "Paired"), name = "Team") +
  scale_x_continuous(expand = expansion(mult = c(0.5, 0.5))) +
  labs(title = "Player Performances Across Multiple Teams (3+)",
       x = "Potential Point % Share (Total Pts)",
       y = "Player") +
  theme_minimal()
playerPerformance3Chart <- (playerPerformance3Actual | playerPerformance3Potential) + plot_layout(guides = "collect")
playerPerformance3Chart
ggsave("DDBMPlayerPerformance3Chart.png", playerPerformance3Chart,
       width = 24, height = 8, dpi = 300)


### Compare performances for players in trades, or waiver/free agency
playerTradePerformances <- FilterDDBMRosters %>%
  semi_join(FilterAllTransactions %>%
              filter(type == "trade") %>%
              distinct(player_name, user_name, current_week,
                       transaction, transaction_id),
            by = c("player_name", "user_name")) %>%
  group_by(player_name, position, user_name) %>%
  summarise(weeks_rostered  = n_distinct(current_week),
            roster_points   = sum(player_points, na.rm = TRUE),
            average_points  = round(roster_points / weeks_rostered, 2),
            .groups = "drop") %>%
  group_by(player_name, position) %>%
  mutate(total_points = sum(roster_points, na.rm = TRUE)) %>%
  left_join(FilterAllTransactions %>%
              filter(type == "trade") %>%
              distinct(player_name, user_name, current_week,
                       transaction, transaction_id),
            by = c("player_name", "user_name")) %>%
  filter(n_distinct(user_name) > 1) %>%
  rename(week_traded = current_week) %>%
  mutate(transaction = factor(transaction, levels = c("drops", "adds"))) %>%
  arrange(transaction_id, player_name, transaction, user_name) %>%
  ungroup() %>%
  mutate(trade_no = dense_rank(transaction_id)) %>%
  relocate(trade_no, .before = player_name) %>%
  relocate(week_traded, .after = weeks_rostered) %>%
  select(-transaction, -transaction_id)
# view(playerTradePerformances)

playerTradePerformancePlot <- ggplot(playerTradePerformances,
                                     aes(x = average_points,
                                         y = fct_reorder(paste0(player_name, "\n(", total_points, " pts total)"),
                                           total_points, .desc = TRUE),
                                         fill = user_name)) +
  geom_bar(stat = "identity", position = position_dodge(width = 0.9), width = 0.8) +
  geom_text(aes(label = paste0(round(average_points, 2)," pts / ",
                               weeks_rostered," week(s)")),
            position = position_dodge(width = 0.9),
            hjust = -0.05, size = 3) +
  geom_vline(xintercept = 0, color = "black", linetype = "dashed") +
  scale_fill_manual(values = brewer.pal(10, "Paired"), name = "Team") +
  scale_x_continuous(expand = expansion(mult = c(0.05, 0.5))) +
  labs(title = "Traded Player Performances While Rostered",
       x = "Average Player Points",
       y = "Player") +
  facet_wrap(~ trade_no, scales = "free_y",
             labeller = labeller(
               trade_no = function(trade_vals) {
                 sapply(trade_vals, function(tn) {
                   players <- playerTradePerformances |>
                     filter(trade_no == tn) |>
                     pull(user_name) |>
                     unique() |>
                     paste(collapse = " | ")
                   wk <- playerTradePerformances |>
                     filter(trade_no == tn) |>
                     pull(week_traded) |>
                     unique()
                   paste0("Trade #", tn, " Week ", wk, ": ", players)})})) +
  theme_minimal() +
  theme(strip.text = element_text(face = "bold", size = 10),
        strip.background = element_rect(fill = "grey90", color = NA))
playerTradePerformancePlot
ggsave("DDBMplayerTradePerformancePlot.png", playerTradePerformancePlot,
       width = 24, height = 8, dpi = 300)

playerWaiverPerformances <- {
  tx <- FilterAllTransactions %>%
    filter(type %in% c("waiver", "free_agent"), status != "failed") %>%
    arrange(player_name, user_name, current_week)

  stints <- tx %>%
    group_by(player_name, user_name) %>%
    summarise(add_weeks  = list(current_week[transaction == "adds"]),
              drop_weeks = list(current_week[transaction == "drops"]),
              .groups = "drop") %>%
    filter(length(add_weeks) > 0) %>%
    unnest_longer(add_weeks, indices_include = TRUE) %>%
    rename(stint_id = add_weeks_id, week_added = add_weeks) %>%
    left_join(FilterDDBMRosters %>%
                group_by(player_name, user_name) %>%
                summarise(roster_min_week = min(current_week, na.rm = TRUE),
                          roster_max_week = max(current_week, na.rm = TRUE),
                          .groups = "drop"),
              by = c("player_name", "user_name")) %>%
    arrange(player_name, user_name, week_added) %>%
    group_by(player_name, user_name) %>%
    mutate(next_add = lead(week_added)) %>%
    ungroup() %>%
    rowwise() %>%
    mutate(week_dropped_tx = {
      dw <- drop_weeks
      dw <- dw[dw >= week_added]
      if (length(dw) > 0) min(dw) else NA_integer_
      },
      stint_end = if (!is.na(week_dropped_tx)) {
        week_dropped_tx
        } else if (!is.na(next_add)) {
          max(min(next_add - 1L, roster_max_week), week_added)
          } else {
            max(roster_max_week, week_added)},
      week_dropped = stint_end) %>%
    ungroup() %>%
    select(player_name, user_name, stint_id, week_added, week_dropped)

  perf <- pmap_dfr(
    stints %>% select(player_name, user_name, stint_id,
                      week_added, week_dropped),
    function(player_name, user_name, stint_id, week_added, week_dropped) {
      slice <- FilterDDBMRosters %>%
        filter(player_name == !!player_name,
               user_name   == !!user_name,
               current_week >= !!week_added,
               current_week <= !!week_dropped)
      if (nrow(slice) == 0) return(NULL)
      weeks_rostered <- n_distinct(slice$current_week)
      roster_points  <- sum(slice$player_points, na.rm = TRUE)
      average_points <- round(roster_points / pmax(weeks_rostered, 1L), 2)
      pos <- slice %>%
        filter(!is.na(position)) %>%
        count(position, sort = TRUE) %>%
        slice(1) %>%
        pull(position)
      if (length(pos) == 0) pos <- NA_character_
      tibble(player_name    = player_name,
             position       = pos,
             user_name      = user_name,
             week_added     = week_added,
             weeks_rostered = weeks_rostered,
             week_dropped   = week_dropped,
             roster_points  = roster_points,
             average_points = average_points)}) %>%
    filter(weeks_rostered > 0) %>%
    group_by(player_name, position) %>%
    mutate(total_points = sum(roster_points, na.rm = TRUE)) %>%
    ungroup() %>%
    arrange(player_name, position, week_added, user_name)

  perf
} %>%
  left_join(FilterAllTransactions %>%
              filter(transaction == "drops",
                     current_week == max(FilterDDBMRosters$current_week,
                                         na.rm = TRUE)) %>%
              distinct(player_name, user_name) %>%
              mutate(dropped_latest = TRUE),
            by = c("player_name", "user_name")) %>%
  mutate(week_dropped = if_else(
    !is.na(week_dropped) &
      week_dropped == max(FilterDDBMRosters$current_week, na.rm = TRUE) &
      is.na(dropped_latest),
    NA_integer_,
    week_dropped)) %>%
  select(-dropped_latest) %>%
  arrange(player_name, position,
          week_added, user_name) -> playerWaiverPerformances
# view(playerWaiverPerformances)

playerWaiverPerformancePlot <- ggplot(playerWaiverPerformances %>%
                                        semi_join(playerWaiverPerformances %>%
                                                    distinct(player_name, .keep_all = TRUE) %>%
                                                    filter(total_points >= 60),
                                                  by = "player_name") %>%
                                        mutate(user_name = fct_reorder(user_name, roster_points, .fun = sum)) %>%
                                        ungroup(),
                                      aes(x = roster_points,
                                          y = fct_reorder(paste0(player_name), total_points, .desc = FALSE),
                                          fill = user_name)) +
  geom_bar(stat = "identity", position = "stack") +
  geom_text(aes(label = paste0(round(roster_points, 2)," pts")),
            position = position_stack(vjust = 0.35), hjust = 0, size = 3) +
  geom_text(aes(x = total_points + 0.5, label = paste0(total_points, " pts Total")),
            hjust = 0, size = 3) +
  scale_fill_manual(values = brewer.pal(10, "Paired"), name = "Team") +
  scale_x_continuous(expand = expansion(mult = c(0, 0.1))) +
  labs(title = "Waiver Player Performances",
       x = "Total Player Points",
       y = "Player") +
  theme_minimal()
playerWaiverPerformancePlot
ggsave("DDBMplayerWaiverPerformancePlot.png", playerWaiverPerformancePlot,
       width = 24, height = 8, dpi = 300)


### Roster breakdown of flex position & individual points per week
plots <- list()
for (team in unique(FilterDDBMRosters$user_name)) {
  weeklyRosterPoints <- FilterDDBMRosters %>%
    filter(user_name == team) %>%
    group_by(current_week, is_starter, position, player_name) %>%
    summarise(player_points = sum(player_points), .groups = "drop") %>%
    complete(current_week, is_starter, position, player_name,
             fill = list(player_points = 0)) %>%
    mutate(position = fct_relevel(as.factor(position), sortPosition),
           week_x = as.numeric(factor(current_week))) %>%
    droplevels()
  # view(weeklyRosterPoints)

  weeklyRosterTotal <- weeklyRosterPoints %>%
    group_by(current_week, is_starter) %>%
    summarise(weekly_points = sum(player_points), .groups = "drop") %>%
    mutate(week_x = as.numeric(factor(current_week)))
  # view(weeklyRosterTotal)

  offset <- 0.2
  bar_width <- 0.4

  weeklyRosterChart <- ggplot(weeklyRosterPoints,
                               aes(y = player_points, fill = position)) +
    geom_col(data = filter(weeklyRosterPoints, is_starter == TRUE),
             aes(x = week_x - offset),
             position = position_stack(reverse = FALSE),
             width = bar_width, color = "white") +
    geom_col(data = filter(weeklyRosterPoints, is_starter == FALSE),
             aes(x = week_x + offset),
             position = position_stack(reverse = FALSE),
             width = bar_width, color = "white") +
    geom_text(data = filter(weeklyRosterTotal, is_starter == TRUE),
              aes(x = week_x - offset, y = weekly_points, label = weekly_points),
              vjust = -0.3, fontface = "bold", inherit.aes = FALSE) +
    geom_text(data = filter(weeklyRosterTotal, is_starter == FALSE),
              aes(x = week_x + offset, y = weekly_points, label = weekly_points),
              vjust = -0.3, fontface = "bold", inherit.aes = FALSE) +
    scale_x_continuous(breaks = unique(weeklyRosterPoints$week_x),
                       labels = unique(weeklyRosterPoints$current_week)) +
    scale_y_continuous(expand = expansion(mult = c(0, 0.1))) +
    scale_fill_manual(values = c("QB"  = "#d62728",
                                 "RB"  = "#2ca02c",
                                 "WR"  = "#1f77b4",
                                 "TE"  = "#ff7f0e",
                                 "K"   = "#9467bd",
                                 "DEF" = "#8c564b"),
                      breaks = sortPosition,
                      drop = FALSE) +
    labs(title = paste("Weekly Starter vs Bench Points for ", team),
         x = "Week", y = "Total Points", fill = "Position") +
    theme_minimal()
  # print(weeklyRosterChart)
  plots[[team]] <- weeklyRosterChart
  ggsave(paste0("DDBMWeeklyRosterChart_", team, ".png"),
         plot = weeklyRosterChart,
         width = 12,
         height = 6,
         dpi = 300)
}
allPlots <- wrap_plots(plots, ncol = 2)   # adjust ncol/nrow as needed
# allPlots
ggsave("DDBMWeeklyRosterChart_AllTeams.png", allPlots,
       width = 24, height = 16, dpi = 300)


### Roster breakdown by player position/points, average across league
# Show roster breakdown over the season by position count
teamRosterStats <- FilterDDBMRosters %>%
  group_by(position, is_starter, user_name) %>%
  summarise(count = n(),
            total_points = sum(player_points, na.rm = TRUE),
            average_points = total_points / count,
            .groups = "drop") %>%
  complete(user_name, position, is_starter = c(TRUE, FALSE),
           fill = list(count = 0, total_points = 0, average_points = 0)) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(user_name, match(position, sortPosition), desc(is_starter),
          desc(average_points))
# view(teamRosterStats)

starter_order <- FilterDDBMRosters %>%
  filter(is_starter) %>%
  group_by(position, user_name) %>%
  summarise(starter_avg = mean(player_points, na.rm = TRUE), .groups = "drop")

rosterPositionPerformance <- ggplot(teamRosterStats,
                  aes(x = reorder_within(user_name,
                     -starter_order$starter_avg[match(
                       paste(position, user_name),
                       paste(starter_order$position, starter_order$user_name))],
                     position),
                     y = average_points,
                     fill = factor(is_starter,
                                   levels = c(TRUE, FALSE),
                                   labels = c("Starters", "Bench")))) +
  geom_col(position = position_dodge(width = 0.9)) +
  geom_text(aes(label = round(average_points, 2)),
            position = position_dodge(width = 0.9),
            vjust = -0.3, size = 2) +
  facet_wrap(~ position, scales = "free_x") +
  scale_x_reordered() +
  labs(title = "Average Starters vs Bench Points",
       x = "Teams",
       y = "Average Points",
       fill = "Status") +
  theme_minimal() +
  theme(axis.text.x = element_text(angle = 45, hjust = 1))
rosterPositionPerformance
ggsave("DDBMRosterPerformance.png", plot = rosterPositionPerformance,
       width = 12, height = 6, dpi = 300)

weeklyPositionPoints <- FilterDDBMRosters %>%
  # filter(is_starter == TRUE) %>%
  group_by(current_week, user_name, position, is_starter) %>%
  summarise(count = n(),
            total_points = sum(player_points, na.rm = TRUE),
            average_points = total_points / count) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(current_week, user_name,
          match(position, sortPosition), desc(is_starter))
# view(weeklyPositionPoints)

### Roster breakdown of starters vs bench (flex spots)
averageWeeklyFlex <- weeklyPositionPoints %>%
  filter(is_starter == TRUE, position %in% c("RB", "WR", "TE")) %>%
  group_by(current_week, position) %>%
  summarise(total_count = sum(count, na.rm = TRUE),
            average_points = mean(average_points),
            total_points = sum(total_points))
# view(averageWeeklyFlex)

position_totals <- averageWeeklyFlex %>%
  group_by(position) %>%
  summarise(total_points_sum = mean(total_points, na.rm = TRUE),
            .groups = "drop")

weeklyHeatmap <- ggplot(
  averageWeeklyFlex,
  aes(x = factor(current_week),
      y = position,
      fill = case_when(position == "TE" ~ pmax(total_count - 10, 0),
                       position %in% c("WR", "RB") ~ pmax(total_count - 20, 0),
                       TRUE ~ total_count))) +
  geom_tile(color = "white") +
  geom_text(aes(label = paste0(total_count,"\n(", round(average_points, 2), " pts)"),
                color = case_when(
                  position == "TE" & total_count > 10 ~ "light",
                  position %in% c("WR","RB") & total_count > 20 ~ "light",
                  TRUE ~ "dark")),
            size = 3) +
  scale_fill_gradient(low = "lightblue", high = "darkblue",
                      name = "Position Flex Counts") +
  scale_color_manual(values = c("light" = "white", "dark" = "black"),
                     guide = "none") +
  scale_y_discrete(
    labels = function(pos) {
      sapply(pos, function(p) {
        pts <- position_totals$total_points_sum[position_totals$position == p]
        paste0(p, "\n(", round(pts, 2), " pts)")})}) +
  labs(title = "Weekly Position Flex Counts",
       x = "Week",
       y = "Position") +
  theme_minimal()
# weeklyHeatmap
ggsave("DDBMWeeklyHeatmap.png", plot = weeklyHeatmap,
       width = 12, height = 6, dpi = 300)

### Roster Flex & Points per Team
averageRosterFlex <- FilterDDBMRosters %>%
  filter(is_starter == TRUE, position %in% c("RB", "WR", "TE")) %>%
  group_by(user_name, position) %>%
  summarise(count = n(),
            total_points = sum(player_points, na.rm = TRUE),
            average_points = total_points / count) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(user_name, match(position, sortPosition))
# view(averageRosterFlex)

rosterFlexPlot <- ggplot(
  averageRosterFlex %>%
    group_by(user_name) %>%
    mutate(rb_total = sum(count[position == "RB"], na.rm = TRUE),
           wr_total = sum(count[position == "WR"], na.rm = TRUE),
           team_total_points = sum(total_points, na.rm = TRUE)) %>%
    ungroup(),
  aes(x = reorder(paste0(user_name, "\n(", round(team_total_points, 1), " pts)"),
                  -rb_total*1000 + wr_total),
      y = average_points,
      fill = position)) +
  geom_bar(stat = "identity", position = position_dodge(width = 0.9)) +
  geom_text(aes(label = count),
            position = position_dodge(width = 0.9),
            vjust = 1.5,
            color = "white",
            size = 3) +
  geom_text(aes(label = round(average_points, 1)),
            position = position_dodge(width = 0.9),
            vjust = -0.3,
            size = 3,
            color = "black") +
  labs(title = "Average Points Per Flex Position Per Team",
       x = "Team (Total Points)",
       y = "Average Points",
       fill = "Position") +
  theme_minimal()
# rosterFlexPlot
ggsave("DDBMRosterFlexPlot.png", plot = rosterFlexPlot,
       width = 12, height = 6, dpi = 300)

rosterFlexHeatmap <- ggplot(
  averageRosterFlex %>%
    group_by(user_name) %>%
    mutate(rb_total  = sum(count[position == "RB"],  na.rm = TRUE),
           wr_total  = sum(count[position == "WR"],  na.rm = TRUE),
           te_total  = sum(count[position == "TE"],  na.rm = TRUE),
           ordering_score = rb_total*1e3 + wr_total*1e2 + te_total,
           team_total_points = sum(total_points, na.rm = TRUE)) %>%
    ungroup(),
  aes(x = reorder(user_name, -ordering_score), y = position, fill = count)) +
  geom_tile(color = "white") +
  geom_text(aes(label = paste0(count,
                               "\n (Avg: ", round(average_points, 1), " pts)",
                               "\n (Total: ", round(total_points, 1), " pts)"),
                color = ifelse(count > max(count)/2, "light", "dark")),
            size = 3) +
  scale_fill_gradient(low = "lightblue", high = "darkblue") +
  scale_color_manual(values = c("light" = "white", "dark" = "black"),
                     guide = "none") +
  labs(title = "Roster Flex Starters Heatmap (RB Heavy vs WR Heavy)",
       x = "Team (Position Points)",
       y = "Position",
       fill = "Count") +
  theme_minimal()
rosterFlexHeatmap
ggsave("DDBMRosterFlexHeatmap.png", plot = rosterFlexHeatmap,
       width = 12, height = 6, dpi = 300)


### Total Roster spots per Team over the Season
averageRosterSpot <- FilterDDBMRosters %>%
  group_by(user_name, position) %>%
  summarise(count = n(),
            total_points = sum(player_points, na.rm = TRUE),
            average_points = total_points / count) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(user_name, match(position, sortPosition))
# view(averageRosterSpot)

rosterSpotPlot <- ggplot(
  averageRosterSpot %>%
    group_by(user_name) %>%
    mutate(qb_total  = sum(count[position == "QB"],  na.rm = TRUE),
           rb_total  = sum(count[position == "RB"],  na.rm = TRUE),
           wr_total  = sum(count[position == "WR"],  na.rm = TRUE),
           te_total  = sum(count[position == "TE"],  na.rm = TRUE),
           k_total   = sum(count[position == "K"],   na.rm = TRUE),
           def_total = sum(count[position == "DEF"], na.rm = TRUE),
           ordering_score = qb_total*1e6 + rb_total*1e5 + wr_total*1e4 +
             te_total*1e3 + k_total*1e2 + def_total,
           team_total_points = sum(total_points, na.rm = TRUE)) %>%
    ungroup(),
  aes(x = reorder(user_name, -ordering_score), y = position, fill = count)) +
  geom_tile(color = "white") +
  geom_text(aes(label = paste0(count,
                               "\n (Avg: ", round(average_points, 1), " pts)",
                               "\n (Total: ", round(total_points, 1), " pts)"),
                color = ifelse(count > max(count)/2, "light", "dark")),
            size = 3) +
  scale_fill_gradient(low = "lightblue", high = "darkblue") +
  scale_color_manual(values = c("light" = "white", "dark" = "black"),
                     guide = "none") +
  labs(title = "Total Roster Heatmap Over 18 Weeks",
       x = "Team",
       y = "Position",
       fill = "Count") +
  theme_minimal()
rosterSpotPlot
ggsave("DDBMRosterSpotPlot.png", plot = rosterSpotPlot,
       width = 12, height = 6, dpi = 300)

### Total Seasonal Roster Count Averages
averagePositionCounts <- weeklyPositionPoints %>%
  group_by(position, is_starter) %>%
  summarise(avg_count = mean(count), .groups = "drop")
# view(averagePositionCounts)

rosterCountBar <- ggplot(averagePositionCounts,
                         aes(x = position,
                             y = avg_count,
                             fill = factor(is_starter,
                                           levels = c(FALSE, TRUE),
                                           labels = c("Bench", "Starters")))) +
  geom_col(position = "stack") +
  geom_text(aes(label = round(avg_count, 2)),
            position = position_stack(vjust = 0.5),
            color = "white",
            size = 4) +
  labs(title = "Average Roster Breakdown During the Season",
       x = "Position",
       y = "Roster Slots Used",
       fill = "Starter") +
  theme_minimal()
# rosterCountBar
ggsave("DDBMRosterCount.png", plot = rosterCountBar,
       width = 12, height = 6, dpi = 300)


### Seasonal Roster breakdown by player position/points across league Box Plot
seasonPositionPoints <- FilterDDBMRosters %>%
  group_by(user_name, position) %>%
  summarise(position_counts = n(),
            total_points = sum(player_points, na.rm = TRUE),
            average_points = total_points / position_counts) %>%
  mutate(position = factor(position, levels = sortPosition)) %>%
  arrange(user_name, match(position, sortPosition))
# view(seasonPositionPoints)

positionDiffLabel <- seasonPositionPoints %>%
  group_by(position) %>%
  summarise(max_points = max(average_points),
            min_points = min(average_points),
            point_diff = max(average_points) - min(average_points),
            avg_points = mean(average_points))

seasonPointsBox <- ggplot(seasonPositionPoints,
                          aes(x = position, y = average_points,)) +
  geom_boxplot(fill = "lightgray", alpha = 0.6) +
  geom_jitter(aes(color = user_name), width = 0.2, alpha = 0.7) +
  # geom_text(aes(label = total_points, color = user_name),
            # vjust = -0.8, size = 3, show.legend = FALSE) +
  geom_text_repel(aes(label = round(average_points, 2), color = user_name),
                  size = 4, max.overlaps = Inf, show.legend = FALSE) +
  geom_text(data = positionDiffLabel,
            aes(x = position,
                y = max_points + 10,
                label = paste0("Avg: ", round(avg_points, 2),
                               " | Max Diff: ", round(point_diff, 2))),
            inherit.aes = FALSE, color = "black", size = 4, fontface = "bold") +
  scale_y_continuous(expand = expansion(mult = c(0, 0.1)), limits = c(0, NA)) +
  labs(title = "Average Weekly Position Points",
       x = "Position",
       y = "Points",
       color = "Teams") +
  theme_minimal()
# seasonPointsBox
ggsave("DDBMSeasonPoints.png", plot = seasonPointsBox,
       width = 12, height = 6, dpi = 300)


### Treemap of points by position over the season with user split
# Convert data to TreeMap format
treemapData <- FilterDDBMRosters %>%
  filter(is_starter == TRUE) %>%
  group_by(position, user_name) %>%
  summarise(total_points = sum(player_points, na.rm = TRUE), .groups = "drop")
# view(treemapData)

seasonPoints <- FilterDDBMRosters %>%
  filter(is_starter == TRUE) %>%
  group_by(position) %>%
  summarise(total_points = sum(player_points, na.rm = TRUE)) %>%
  arrange(match(position, sortPosition))
# view(seasonPoints)

positionTotalsCaption <- seasonPoints %>%
  mutate(txt = paste0(position, ": ", total_points, " points")) %>%
  pull(txt) %>%
  paste(collapse = " | ")
# view(positionTotalsCaption)

positionPointsTree <- ggplot(treemapData,
                             aes(area = total_points,
                                 fill = user_name,
                                 label = paste(user_name, "\n", total_points),
                                 subgroup = position)) +
  geom_treemap() +
  geom_treemap_subgroup_border(color = "white", size = 2) +
  geom_treemap_subgroup_text(place = "centre", grow = TRUE, alpha = 0.5) +
  geom_treemap_text(colour = "grey20",
                    place = "centre",
                    grow = FALSE, # TRUE
                    reflow = TRUE) +
  scale_fill_brewer(palette = "Set3") +
  labs(title = "Most Points by Position",
       caption = paste("Position Totals: ", positionTotalsCaption),
       fill = "Team") +
  theme_minimal()
# positionPointsTree
ggsave("DDBMPositionPointsTree.png", plot = positionPointsTree,
       width = 12, height = 6, dpi = 300)


### Total Points Bar Chart
# Custom Labels (weekly max points, total team points)
weekly_max <- FilterMatchupResults %>%
  group_by(current_week) %>%
  summarise(max_points = max(weekly_points, na.rm = TRUE)) %>%
  ungroup()
maxPointsLabel <- setNames(
  paste0(weekly_max$current_week," (Max: ", weekly_max$max_points, ")"),
  weekly_max$current_week)

season_total <- FilterMatchupResults %>%
  filter(current_week == max(current_week)) %>%
  arrange(desc(total_points)) %>%
  pull(user_name)
totalPointsLabel <- FilterMatchupResults %>%
  filter(current_week == max(current_week)) %>%
  select(user_name, total_points)

teamLabel <- with(
  FilterMatchupResults[FilterMatchupResults$current_week == latestWeek-1,],
  setNames(paste0(user_name, "\n(", current_record, ")"),user_name))


tablePointsChart <- ggplot(FilterMatchupResults,
                           aes(x = factor(user_name),
                               y = weekly_points,
                               fill = factor(current_week,
                                             levels = rev(
                                               sort(unique(current_week)))))) +
  geom_bar(stat = "identity") +
  geom_text(aes(label = weekly_points),
            position = position_stack(vjust = 0.5), color = "black", size = 3) +
  geom_text(data = totalPointsLabel,
            aes(x = user_name, y = total_points, label = total_points),
            vjust = -0.5, fontface = "bold", size = 4, inherit.aes = FALSE) +
  # scale_fill_hue(name = "Week", labels = maxPointsLabel) +
  scale_fill_manual(values = c(
    "#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00","#ffff33",
    "#a65628", "#f781bf", "#999999", "#66c2a5", "#fc8d62", "#8da0cb",
    "#e78ac3", "#a6d854", "#ffd92f", "#e5c494", "#b3b3b3", "#1b9e77"),
    name = "Week",
    labels = maxPointsLabel) +
  scale_x_discrete(limits = season_total, labels = teamLabel) +
  labs(title = "Total Points by Team",
       x = "Team",
       y = "Points") +
  theme_minimal()
# tablePointsChart
ggsave("DDBMTablePoints.png", plot = tablePointsChart,
       width = 12, height = 6, dpi = 300)


### Pie chart of points by position over the season
positionPoints <- FilterDDBMRosters %>%
  filter(is_starter == TRUE) %>%
  group_by(position) %>%
  summarise(total_points = sum(player_points, na.rm = TRUE)) %>%
  arrange(match(position, sortPosition)) %>%
  mutate(pct = total_points / sum(total_points) * 100)
# view(positionPoints)
# view(FilterDDBMRosters)

positionPointsChart <- ggplot(positionPoints,
                              aes(x = "", y = total_points, fill = position)) +
  geom_bar(stat = "identity", width = 1) +
  coord_polar("y", start = 0) +
  geom_label_repel(aes(label = paste0(total_points, " (", round(pct, 1), "%)")),
                   position = position_stack(vjust = 0.5),
                   size = 4, color = "black", show.legend = FALSE) +
  scale_fill_brewer(breaks = sortPosition, palette = "Set3") +
  labs(title = "Total Points by Position",
       fill = "Position") +
  theme_void()
# positionPointsChart
ggsave("DDBMPositionPoints.png", plot = positionPointsChart,
       width = 12, height = 6, dpi = 300)


### Weekly Table Position Line Graph
latest_week <- max(FilterMatchupResults$current_week)
tablePositionGraph <- ggplot(FilterMatchupResults,
                             aes(x = current_week,
                                 y = table_position,
                                 color = factor(
                                   user_name,
                                   levels = FilterMatchupResults %>%
                                     filter(current_week == latest_week) %>%
                                     arrange(table_position) %>%
                                     pull(user_name)),
                                 group = user_name)) +
  geom_line(size = 1.2) +
  geom_point(size = 3) +
  scale_y_reverse(
    breaks = seq(0, max(FilterMatchupResults$table_position), by = 1),
    sec.axis = dup_axis(name = "Position")) +
  scale_x_continuous(breaks = seq(0, latest_week, by = 1)) +
  scale_color_viridis_d(name = "Team",
                        option = "turbo",
                        labels = function(x) {
                          df <- FilterMatchupResults %>%
                            filter(current_week == latest_week, user_name %in% x)
                          paste0(df$user_name, " (", df$current_record, ")")}) +
  geom_hline(yintercept = 8.5, linetype = "dashed", color = "black", size = 1) +
  geom_vline(xintercept = 14.5, linetype = "dashed", color = "black", size = 1) +
  annotate("text",
           x = latest_week - 1,
           y = 8.5,
           label = "Playoff Line",
           hjust = 3,
           vjust = -0.5,
           fontface = "bold",
           color = "black") +
  labs(title = "Table Position Shifts", x = "Week", y = "Position") +
  theme_minimal()
# tablePositionGraph
ggsave("DDBMTablePosition.png", plot = tablePositionGraph,
       width = 10, height = 6, dpi = 300)

# allTransactionsDF <- allTransactionsDF %>%
#   ungroup() %>%
#   mutate(adds = ifelse(adds == "", NA, adds),
#          drops = ifelse(drops == "", NA, drops)) %>%
#   unnest_wider(metadata, names_sep = ".") %>%
#   rename(system_msg = metadata.notes) %>%
#   unnest_wider(settings, names_sep = ".") %>%
#   rename(order_seq = settings.seq,
#          waiver_bid = settings.waiver_bid,
#          user_id = creator) %>%
#   separate_rows(adds, drops, sep = ",") %>%
#   mutate(adds = ifelse(!is.na(drops) & adds == drops, NA, adds)) %>%
#   pivot_longer(cols = c(adds, drops),
#                names_to = "transaction", values_to = "player_id") %>%
#   filter(!is.na(player_id)) %>%
#   left_join(playerMap %>% select(player_id, player_name), by = "player_id") %>%
  # mutate(transaction = case_when(
  #   transaction == "adds" ~ "added",
  #   transaction == "drops" ~ "dropped",
  #   TRUE ~ transaction)) %>%
  # separate_rows(adds, drops, sep = ",") %>%
  # mutate(adds = ifelse(!is.na(drops) & adds == drops, NA, adds)) %>%
  # left_join(playerMap %>% select(player_id, player_added = player_name),
  #  by = c("adds" = "player_id")) %>%
  # left_join(playerMap %>% select(player_id, player_dropped = player_name),
  #  by = c("drops" = "player_id")) %>%
  # unnest_wider(metadata, names_sep = ".") %>%
  # rename(system_msg = metadata.notes) %>%
  # unnest_wider(settings, names_sep = ".") %>%
  # rename(order_seq = settings.seq,
  #        waiver_bid = settings.waiver_bid,
  #        user_id = creator) %>%
  # select(-transaction_id) %>% #, -consenter_ids) %>%
  # relocate(order_seq, waiver_bid, status, system_msg,
  #          .after = player_name) %>%
  # arrange(current_week, order_seq, desc(waiver_bid), roster_ids)
# view(allTransactionsDF)
# View(filter(allTransactionsDF, type == "trade"))


############
# nflfastR #
############
# options(scipen = 9999)
#
# data <- load_pbp(2025)
#
# dim(data)
# str(data[1:10])
# glimpse(data[1:10])
# data |>
#   select(home_team, away_team, posteam, desc) |>
#   View()
# data |>
#   select(posteam, defteam, desc, rush, pass) |>
#   head()
# data |> select(posteam, defteam, desc, rush, pass) |> head()
