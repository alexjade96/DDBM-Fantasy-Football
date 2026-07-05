# Build a synthetic sleeper_season (no network) for tests.
make_season <- function(season = "2025", champ_roster = 1L) {
  team_wk <- tibble::tibble(
    week      = rep(1:2, each = 3),
    roster_id = rep(1:3, 2),
    user_id   = as.character(rep(1:3, 2)),
    user_name = rep(c("Al", "Bo", "Cy"), 2),
    matchup_id = rep(c(1, 1, NA), 2),
    points    = c(100, 90, 80, 130, 70, 120),
    pa        = c(90, 100, 80, 70, 130, 120),
    result    = c("W", "L", "T", "W", "L", "T"),
    allplay_w = c(2, 1, 0, 1, 0, 2),
    allplay_l = c(0, 1, 2, 1, 2, 0),
    is_high   = c(FALSE, FALSE, FALSE, TRUE, FALSE, FALSE))
  standings <- team_wk |>
    dplyr::group_by(roster_id, user_id, user_name) |>
    dplyr::summarise(wins = sum(result == "W"), losses = sum(result == "L"),
                     points = sum(points), pa = sum(pa),
                     allplay_w = sum(allplay_w), allplay_l = sum(allplay_l),
                     highs = sum(is_high), .groups = "drop") |>
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points)) |>
    dplyr::mutate(final_position = dplyr::row_number(),
                  champion = roster_id == champ_roster, season = season)
  lineup <- tibble::tibble(
    user_name = rep(c("Al", "Bo", "Cy"), each = 2), week = rep(1:2, 3),
    actual = c(100, 100, 90, 90, 80, 80),
    optimal = c(110, 110, 100, 100, 100, 100),
    left_on_bench = c(10, 10, 10, 10, 20, 20))
  structure(list(season = season, name = "Test League", league_id = "0",
                 last_week = 2, slots = list(), team_wk = team_wk,
                 pl_wk = tibble::tibble(), lineup = lineup,
                 standings = standings, user_map = tibble::tibble()),
            class = "sleeper_season")
}
