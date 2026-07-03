# ddbmMetrics.R - reusable Sleeper fantasy analytics engine
# Pure functions (no Shiny) that fetch a league's data by league_id, compute
# descriptive metrics, and return ggplot objects + markdown insight summaries.
# Sourced by app.R (the Shiny dashboard) and usable standalone.

suppressPackageStartupMessages({
  library(tidyverse); library(httr2); library(jsonlite); library(RColorBrewer)
})

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

## ---------------------------------------------------------------- API + utils
sleeper_get <- function(path) {
  request(paste0("https://api.sleeper.app/v1", path)) |>
    req_timeout(30) |>
    req_retry(max_tries = 4, retry_on_failure = TRUE, backoff = ~ 2 ^ .x) |>
    req_perform() |>
    resp_body_json(simplifyDataFrame = TRUE)
}
ensure_cols <- function(df, cols) {
  miss <- setdiff(cols, names(df)); if (length(miss)) df[miss] <- NA; df
}

sortPosition <- c("QB", "RB", "WR", "TE", "K", "DEF")
posColors <- c(QB = "#d62728", RB = "#2ca02c", WR = "#1f77b4",
               TE = "#ff7f0e", K = "#9467bd", DEF = "#8c564b")

theme_ddbm <- function() theme_minimal(base_size = 13) %+replace% theme(
  plot.title    = element_text(face = "bold", size = 17, hjust = 0, margin = margin(b = 2)),
  plot.subtitle = element_text(color = "grey38", hjust = 0, size = 10, margin = margin(b = 8)),
  plot.caption  = element_text(color = "grey55", size = 8, hjust = 1),
  panel.grid.minor = element_blank(),
  plot.background  = element_rect(fill = "white", color = NA),
  plot.margin = margin(12, 16, 8, 12))

# Cached player name/position/gsis lookup (league-independent). Refetched daily.
player_info <- local({
  cache <- NULL
  function(refresh = FALSE) {
    if (!is.null(cache) && !refresh) return(cache)
    f <- "sleeperPlayerData.rds"
    fresh <- file.exists(f) && as.Date(file.info(f)$mtime) == Sys.Date()
    raw <- if (fresh) readRDS(f) else {
      r <- sleeper_get("/players/nfl"); saveRDS(r, f); r }
    cl <- function(x, e = NA) { if (is.null(x)) return(NA)
      else if (is.list(x)) { if (!length(x)) return(e)
        else return(lapply(x, cl, e = e)) } else return(x) }
    df <- map_dfr(cl(unname(raw)), ~ as_tibble(flatten(as.data.frame(.x))))
    cache <<- df %>% transmute(
      player_id,
      player_name = if_else(position == "DEF", as.character(player_id), full_name),
      position, gsis_id = as.character(gsis_id))
    cache
  }
})

## -------------------------------------------------------- league chain + slots
build_league_chain <- function(head_id) {
  chain <- list(); id <- as.character(head_id)
  while (!is.null(id) && !is.na(id) && nzchar(id)) {
    lg <- sleeper_get(paste0("/league/", id))
    chain[[lg$season]] <- list(
      league_id = lg$league_id, season = lg$season, name = lg$name,
      last_scored_leg = lg$settings$last_scored_leg %||% 0,
      roster_positions = unlist(lg$roster_positions))
    id <- lg$previous_league_id
  }
  chain[order(as.integer(names(chain)))]
}

# Turn roster_positions into starter-slot counts (drops bench/IR/taxi)
starter_slots <- function(rp) {
  rp <- rp[!rp %in% c("BN", "IR", "TAXI")]
  as.list(table(factor(rp)))
}
# Optimal lineup points for one team-week given slot counts
optimal_points <- function(d, slots) {
  d <- d %>% filter(!is.na(position)) %>% arrange(desc(points))
  used <- character(0)
  take <- function(elig, n) { n <- n %||% 0; if (n <= 0) return(0)
    a <- d %>% filter(position %in% elig, !player_id %in% used) %>% slice_head(n = n)
    used <<- c(used, a$player_id); sum(a$points) }
  tot <- 0
  for (p in sortPosition) tot <- tot + take(p, slots[[p]])
  tot <- tot + take(c("WR", "TE"),             slots[["REC_FLEX"]])
  tot <- tot + take(c("RB", "WR", "TE"),        slots[["FLEX"]])
  tot <- tot + take(c("RB", "WR", "TE"),        slots[["WRRB_FLEX"]])
  tot <- tot + take(c("QB", "RB", "WR", "TE"),  slots[["SUPER_FLEX"]])
  tot
}

## --------------------------------------------------- per-season data + metrics
get_season <- function(link) {
  lid <- link$league_id; lw <- link$last_scored_leg
  slots <- starter_slots(link$roster_positions)
  pinfo <- player_info()

  users <- as_tibble(sleeper_get(paste0("/league/", lid, "/users")),
                     .name_repair = "unique") %>%
    unnest(metadata, names_sep = "_") %>% rename(user_name = display_name) %>%
    ensure_cols("metadata_team_name") %>%
    transmute(user_id, user_name, team_name = metadata_team_name)
  userMap <- as_tibble(sleeper_get(paste0("/league/", lid, "/rosters")),
                       .name_repair = "unique") %>%
    select(roster_id, owner_id) %>%
    left_join(users, by = c("owner_id" = "user_id")) %>%
    transmute(roster_id, user_id = owner_id, user_name)

  raw <- map(seq_len(max(lw, 1)), function(i) {
    m <- as_tibble(sleeper_get(paste0("/league/", lid, "/matchups/", i))); m$week <- i; m })

  teamWk <- map_dfr(raw, ~ .x %>% select(week, roster_id, matchup_id, points)) %>%
    left_join(map_dfr(raw, ~ .x %>% select(week, roster_id, matchup_id, points)) %>%
                select(week, matchup_id, opp = roster_id, pa = points),
              by = c("week", "matchup_id"), na_matches = "never",
              relationship = "many-to-many") %>%
    filter(is.na(opp) | roster_id != opp) %>%
    mutate(result = case_when(points > pa ~ "W", points < pa ~ "L",
                              points == pa ~ "T", TRUE ~ NA_character_)) %>%
    group_by(week) %>%
    mutate(allplay_w = map_dbl(points, ~ sum(.x > points)),
           allplay_l = map_dbl(points, ~ sum(.x < points)),
           is_high = points == max(points)) %>%
    ungroup() %>% left_join(userMap, by = "roster_id")

  plWk <- map_dfr(raw, function(m) {
    pp <- m$players_points
    map_dfr(seq_len(nrow(m)), function(i) {
      ids <- unlist(m$players[[i]]); st <- unlist(m$starters[[i]])
      pts <- vapply(ids, function(id) { v <- if (!is.null(pp) && id %in% names(pp)) pp[[id]][i] else NA_real_
        if (length(v) == 0 || is.na(v)) 0 else as.numeric(v) }, numeric(1))
      tibble(week = m$week[i], roster_id = m$roster_id[i], player_id = ids,
             points = pts, is_starter = ids %in% st)
    })
  }) %>% left_join(pinfo %>% select(player_id, player_name, position), by = "player_id")

  lineup <- plWk %>% left_join(userMap, by = "roster_id") %>%
    group_by(user_name, week) %>%
    summarise(actual = sum(points[is_starter]),
              optimal = optimal_points(pick(everything()), slots),
              .groups = "drop") %>%
    mutate(left_on_bench = pmax(optimal - actual, 0))

  standings <- teamWk %>% group_by(roster_id, user_id, user_name) %>%
    summarise(wins = sum(result == "W", na.rm = TRUE),
              losses = sum(result == "L", na.rm = TRUE),
              points = sum(points), pa = sum(pa, na.rm = TRUE),
              allplay_w = sum(allplay_w), allplay_l = sum(allplay_l),
              highs = sum(is_high), .groups = "drop") %>%
    arrange(desc(wins), desc(points)) %>% mutate(final_position = row_number())

  champ <- tryCatch({ wb <- as_tibble(sleeper_get(paste0("/league/", lid, "/winners_bracket")))
    if ("p" %in% names(wb)) { f <- wb %>% filter(p == 1); if (nrow(f)) as.integer(f$w[[1]]) else NA } else NA },
    error = function(e) NA)
  standings <- standings %>% mutate(champion = !is.na(champ) & roster_id == champ,
                                    season = link$season)

  list(season = link$season, teamWk = teamWk, plWk = plWk, lineup = lineup,
       standings = standings, userMap = userMap)
}

mgr_palette <- function(names_vec) {
  nm <- sort(unique(names_vec))
  setNames(colorRampPalette(brewer.pal(12, "Paired"))(length(nm)), nm)
}

## --------------------------------------------------------- SEASON metric plots
plot_standings <- function(s) {
  d <- s$standings %>% mutate(
    record = paste0(wins, "-", losses),
    lbl = paste0(record, ifelse(champion, "  \U0001F451", "")),
    user_name = fct_reorder(user_name, points))
  ggplot(d, aes(points, user_name, fill = user_name)) +
    geom_col(width = 0.72, show.legend = FALSE) +
    geom_text(aes(label = lbl), hjust = -0.03, size = 3.4, family = "Segoe UI Emoji") +
    scale_fill_manual(values = mgr_palette(d$user_name)) +
    scale_x_continuous(expand = expansion(c(0, 0.18))) +
    labs(title = paste0(s$season, " Standings"),
         subtitle = "Total points; record labeled, crown = champion",
         x = "Season Points", y = NULL) + theme_ddbm()
}
plot_luck <- function(s) {
  d <- s$standings %>% mutate(g = wins + losses,
      exp_w = round(allplay_w / pmax(allplay_w + allplay_l, 1) * g, 1),
      luck = round(wins - exp_w, 1), user_name = fct_reorder(user_name, luck))
  ggplot(d, aes(y = user_name)) +
    geom_segment(aes(x = exp_w, xend = wins, yend = user_name), color = "grey75", linewidth = 1) +
    geom_point(aes(x = exp_w), color = "grey55", size = 3.5) +
    geom_point(aes(x = wins, color = luck > 0), size = 4.5, show.legend = FALSE) +
    geom_text(aes(x = wins, label = sprintf("%+.1f", luck),
                  hjust = ifelse(luck > 0, -0.4, 1.4)), size = 3, fontface = "bold") +
    scale_color_manual(values = c(`TRUE` = "#2ca02c", `FALSE` = "#d62728")) +
    labs(title = "Luck: Actual vs All-Play Expected Wins",
         subtitle = "Grey dot = expected wins vs whole league each week; colored = actual",
         x = "Wins", y = NULL) + theme_ddbm()
}
plot_efficiency <- function(s) {
  d <- s$lineup %>% group_by(user_name) %>%
    summarise(actual = sum(actual), optimal = sum(optimal), bench = sum(left_on_bench),
              .groups = "drop") %>%
    mutate(eff = actual / optimal * 100, user_name = fct_reorder(user_name, eff))
  ggplot(d, aes(eff, user_name)) +
    geom_col(aes(fill = eff), width = 0.72, show.legend = FALSE) +
    geom_text(aes(label = sprintf("%.1f%%  (%.0f pts benched)", eff, bench)),
              hjust = -0.03, size = 3) +
    scale_fill_gradient(low = "#f0a58f", high = "#2ca02c") +
    scale_x_continuous(expand = expansion(c(0, 0.55)), limits = c(0, 100)) +
    labs(title = "Lineup Efficiency (Coaching)",
         subtitle = "Started points as % of the optimal lineup each week",
         x = "Efficiency %", y = NULL) + theme_ddbm()
}
plot_consistency <- function(s) {
  med <- s$teamWk %>% group_by(user_name) %>% summarise(m = median(points), .groups = "drop")
  s$teamWk %>% mutate(user_name = factor(user_name, levels = med$user_name[order(med$m)])) %>%
    ggplot(aes(points, user_name, fill = user_name)) +
    geom_boxplot(width = 0.55, alpha = 0.55, outlier.shape = NA, show.legend = FALSE) +
    geom_jitter(aes(color = user_name), height = 0.15, alpha = 0.6, size = 1.5, show.legend = FALSE) +
    scale_fill_manual(values = mgr_palette(s$teamWk$user_name)) +
    scale_color_manual(values = mgr_palette(s$teamWk$user_name)) +
    labs(title = "Consistency: Weekly Score Distributions",
         subtitle = "Tight box = steady; wide = boom-or-bust", x = "Weekly Points", y = NULL) +
    theme_ddbm()
}
plot_pf_pa <- function(s) {
  d <- s$standings %>% mutate(w = wins)
  ggplot(d, aes(points, pa)) +
    geom_vline(xintercept = median(d$points), linetype = "dashed", color = "grey60") +
    geom_hline(yintercept = median(d$pa), linetype = "dashed", color = "grey60") +
    geom_point(aes(color = user_name, size = w), show.legend = FALSE) +
    ggrepel::geom_text_repel(aes(label = paste0(user_name, " (", w, "W)")), size = 3) +
    scale_color_manual(values = mgr_palette(d$user_name)) + scale_size(range = c(3, 9)) +
    labs(title = "Points For vs Points Against",
         subtitle = "Right = scored a lot; low = fewer points allowed; size = wins",
         x = "Points For", y = "Points Against") + theme_ddbm()
}

## --------------------------------------------------------- CAREER metric plots
career_table <- function(all_standings) {
  canon <- all_standings %>% group_by(user_id) %>% arrange(desc(as.integer(season))) %>%
    summarise(user_name = first(user_name), .groups = "drop")
  all_standings %>% group_by(user_id) %>%
    summarise(seasons = n_distinct(season), wins = sum(wins), losses = sum(losses),
              points = sum(points), titles = sum(champion), best = min(final_position),
              .groups = "drop") %>%
    mutate(win_pct = round(wins / pmax(wins + losses, 1) * 100, 1),
           record = paste0(wins, "-", losses)) %>%
    left_join(canon, by = "user_id") %>% arrange(desc(win_pct))
}
plot_career <- function(all_standings) {
  d <- career_table(all_standings) %>% mutate(user_name = fct_reorder(user_name, win_pct))
  ggplot(d, aes(win_pct, user_name, fill = user_name)) +
    geom_col(width = 0.72, show.legend = FALSE) +
    geom_text(aes(label = sprintf("%s  %.1f%%  %s", record, win_pct,
                  ifelse(titles > 0, strrep("\U0001F451", titles), ""))),
              hjust = -0.03, size = 3.2, family = "Segoe UI Emoji") +
    scale_fill_manual(values = mgr_palette(d$user_name)) +
    scale_x_continuous(expand = expansion(c(0, 0.35)), limits = c(0, 100)) +
    labs(title = "Career Standings (All Seasons)", subtitle = "Ranked by win %",
         x = "Career Win %", y = NULL) + theme_ddbm()
}
plot_trajectory <- function(all_standings) {
  canon <- all_standings %>% group_by(user_id) %>% arrange(desc(as.integer(season))) %>%
    summarise(nm = first(user_name), .groups = "drop")
  d <- all_standings %>% left_join(canon, by = "user_id") %>%
    mutate(season = as.integer(season))
  mp <- max(all_standings$final_position)
  ggplot(d, aes(season, final_position, color = nm, group = nm)) +
    geom_line(linewidth = 1.1, alpha = 0.85) +
    geom_point(aes(shape = champion), size = 3) +
    ggrepel::geom_text_repel(data = d %>% group_by(nm) %>% filter(season == max(season)),
      aes(label = nm), nudge_x = 0.12, hjust = 0, size = 3, direction = "y", show.legend = FALSE) +
    scale_y_reverse(breaks = 1:mp) +
    scale_x_continuous(breaks = sort(unique(d$season)), expand = expansion(c(0.02, 0.16))) +
    scale_shape_manual(values = c(`FALSE` = 16, `TRUE` = 8), guide = "none") +
    scale_color_manual(values = mgr_palette(d$nm), guide = "none") +
    labs(title = "Finish Trajectory by Season", subtitle = "1 = top; star = champion",
         x = "Season", y = "Final Position") + theme_ddbm()
}

## ------------------------------------------------------------ insight summaries
.fmt_mgr <- function(x) paste0("**", x, "**")
summarize_season <- function(s) {
  st <- s$standings
  lead <- st %>% slice_min(final_position, n = 1, with_ties = FALSE)
  luck <- st %>% mutate(g = wins + losses,
      exp_w = allplay_w / pmax(allplay_w + allplay_l, 1) * g, luck = wins - exp_w)
  lucky <- luck %>% slice_max(luck, n = 1, with_ties = FALSE); unlucky <- luck %>% slice_min(luck, n = 1, with_ties = FALSE)
  eff <- s$lineup %>% group_by(user_name) %>%
    summarise(a = sum(actual), o = sum(optimal), b = sum(left_on_bench), .groups = "drop") %>%
    mutate(e = a / o * 100)
  best_c <- eff %>% slice_max(e, n = 1, with_ties = FALSE); worst_c <- eff %>% slice_min(e, n = 1, with_ties = FALSE)
  hi <- st %>% slice_max(highs, n = 1, with_ties = FALSE)
  cons <- s$teamWk %>% group_by(user_name) %>% summarise(sd = sd(points), .groups = "drop")
  steady <- cons %>% slice_min(sd, n = 1, with_ties = FALSE); swingy <- cons %>% slice_max(sd, n = 1, with_ties = FALSE)
  paste0(
    "### ", s$season, " season - what the numbers say\n\n",
    "- **Top of the table:** ", .fmt_mgr(lead$user_name), " (", lead$wins, "-", lead$losses,
      ", ", round(lead$points), " pts", ifelse(lead$champion, ", and the champion \U0001F451", ""), ").\n",
    "- **Luckiest:** ", .fmt_mgr(lucky$user_name), " won ", sprintf("%+.1f", lucky$luck),
      " games above all-play expectation; **unluckiest:** ", .fmt_mgr(unlucky$user_name),
      " (", sprintf("%+.1f", unlucky$luck), ").\n",
    "- **Best coach:** ", .fmt_mgr(best_c$user_name), " started ", sprintf("%.1f%%", best_c$e),
      " of their optimal lineup; **most left on the bench:** ", .fmt_mgr(worst_c$user_name),
      " (", round(worst_c$b), " pts wasted).\n",
    "- **Weekly high-score crowns:** ", .fmt_mgr(hi$user_name), " led the league in scoring ",
      hi$highs, " week(s).\n",
    "- **Steadiest:** ", .fmt_mgr(steady$user_name), " (SD ", round(steady$sd), "); ",
      "**boom-or-bust:** ", .fmt_mgr(swingy$user_name), " (SD ", round(swingy$sd), ").")
}
summarize_career <- function(all_standings) {
  ct <- career_table(all_standings)
  vets <- ct %>% filter(seasons == max(seasons))
  best <- ct %>% slice_max(win_pct, n = 1, with_ties = FALSE); most_t <- ct %>% slice_max(titles, n = 1, with_ties = FALSE)
  worst <- ct %>% slice_min(win_pct, n = 1, with_ties = FALSE)
  paste0(
    "### Career - across all seasons\n\n",
    "- **Managers tracked:** ", nrow(ct), " (", sum(ct$seasons > 1), " multi-season).\n",
    "- **Best win %:** ", .fmt_mgr(best$user_name), " (", best$win_pct, "%, ", best$record, ").\n",
    "- **Most titles:** ", .fmt_mgr(most_t$user_name), " with ", most_t$titles, ".\n",
    "- **Longest-tenured:** ", paste(.fmt_mgr(vets$user_name), collapse = ", "),
      " (", max(ct$seasons), " seasons).\n",
    "- **Still chasing a winning record:** ", .fmt_mgr(worst$user_name),
      " (", worst$win_pct, "%).")
}
