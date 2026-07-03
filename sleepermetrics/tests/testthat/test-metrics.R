# Build a synthetic sleeper_season (no network) --------------------------
make_season <- function(season = "2025", champ_roster = 1L) {
  team_wk <- tibble::tibble(
    week      = rep(1:2, each = 3),
    roster_id = rep(1:3, 2),
    user_id   = as.character(rep(1:3, 2)),
    user_name = rep(c("Al", "Bo", "Cy"), 2),
    points    = c(100, 90, 80, 130, 70, 120),
    pa        = c(90, 100, 80, 70, 130, 120),
    result    = c("W", "L", "T", "W", "L", "T"),
    allplay_w = c(2, 1, 0, 1, 0, 2),
    allplay_l = c(0, 1, 2, 1, 2, 0),
    is_high   = c(FALSE, FALSE, FALSE, TRUE, FALSE, FALSE))
  standings <- team_wk %>%
    dplyr::group_by(roster_id, user_id, user_name) %>%
    dplyr::summarise(wins = sum(result == "W"), losses = sum(result == "L"),
                     points = sum(points), pa = sum(pa),
                     allplay_w = sum(allplay_w), allplay_l = sum(allplay_l),
                     highs = sum(is_high), .groups = "drop") %>%
    dplyr::arrange(dplyr::desc(wins), dplyr::desc(points)) %>%
    dplyr::mutate(final_position = dplyr::row_number(),
                  champion = roster_id == champ_roster, season = season)
  lineup <- tibble::tibble(
    user_name = rep(c("Al", "Bo", "Cy"), each = 2), week = rep(1:2, 3),
    actual = c(100, 100, 90, 90, 80, 80),
    optimal = c(110, 110, 100, 100, 100, 100),
    left_on_bench = c(10, 10, 10, 10, 20, 20))
  structure(list(season = season, name = "Test", league_id = "0", last_week = 2,
                 slots = list(), team_wk = team_wk, pl_wk = tibble::tibble(),
                 lineup = lineup, standings = standings,
                 user_map = tibble::tibble()), class = "sleeper_season")
}

test_that("sl_luck computes expected wins and luck", {
  d <- sl_luck(make_season())
  expect_true(all(c("user_name", "wins", "exp_w", "luck") %in% names(d)))
  expect_equal(nrow(d), 3L)
})

test_that("sl_efficiency computes a percentage and bench points", {
  d <- sl_efficiency(make_season())
  expect_true(all(d$eff <= 100))
  expect_equal(d$eff[d$user_name == "Cy"], round(160 / 200 * 100, 1))
})

test_that("sl_consistency and sl_high_scores return one row per team", {
  s <- make_season()
  expect_equal(nrow(sl_consistency(s)), 3L)
  expect_equal(sum(sl_high_scores(s)$highs), 1L)  # one weekly-high team-week
})

test_that("sl_summary_season is a single markdown string", {
  txt <- sl_summary_season(make_season())
  expect_length(txt, 1L)
  expect_match(txt, "what the numbers say")
})

test_that("sl_summary_career stays length 1 even with tied titles (regression)", {
  # Al champion in 2024, Bo champion in 2025 -> both have 1 title (a tie)
  seasons <- list("2024" = make_season("2024", champ_roster = 1L),
                  "2025" = make_season("2025", champ_roster = 2L))
  txt <- sl_summary_career(seasons)
  expect_length(txt, 1L)                      # not 2 (the with_ties bug)
  expect_match(txt, "Most titles")
  ct <- sl_career(seasons)
  expect_equal(nrow(ct), 3L)                  # 3 managers across 2 seasons
  expect_equal(max(ct$titles), 1L)
})
