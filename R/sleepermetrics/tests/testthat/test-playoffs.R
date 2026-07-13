# Playoff engine tests (network-free: stats + player db are mocked).

rules <- list(pass_td = 4, rec = 1, rush_yd = 0.1)

fake_stats <- list(
  `14` = list(`1` = list(pass_td = 3),                  # 12.0
              `2` = list(rec = 5, rush_yd = 20),        #  7.0
              `3` = list(pass_td = 1, rec = 2),         #  6.0
              `4` = list(rush_yd = 100)),               # 10.0
  `15` = list(`1` = list(pass_td = 1),                  #  4.0
              `4` = list(rush_yd = 300)))               # 30.0

fake_players <- tibble::tibble(
  player_id   = c("1", "2", "3", "4"),
  player_name = c("Ace", "Bo", "Cy", "Dee"),
  position    = c("QB", "WR", "QB", "RB"))

test_cfg <- function() list(
  season = "2025", league_id = "0", name = "Test", scoring_settings = rules,
  final = "R2M1",
  rounds = list(
    list(id = "R1", name = "Semi", weeks = list(14), matchups = list(
      list(id = "R1M1", home = list(team = "Al", starters = list("1")),
           away = list(team = "Bo", starters = list("2"))),
      list(id = "R1M2", home = list(team = "Cy", starters = list("3")),
           away = list(team = "Dee", starters = list("4"))))),
    list(id = "R2", name = "Final", weeks = list(15), matchups = list(
      list(id = "R2M1", home = list(team = "W:R1M1", starters = list("1")),
           away = list(team = "W:R1M2", starters = list("4")))))))

with_mocks <- function(code) {
  testthat::local_mocked_bindings(
    sl_players = function(...) fake_players,
    sl_nfl_stats = function(season, week) fake_stats[[as.character(week)]] %||% list())
  force(code)
}

pt <- function(r, m, t) r$points[r$matchup_id == m & r$team == t]

test_that("sl_playoff scores submitted lineups and advances winners", {
  with_mocks({
    p <- sl_playoff(test_cfg(), validate = FALSE)
    r <- p$results
    # Ace: 3 pass_td * 4 = 12 beats Bo: 5 rec + 20 * 0.1 = 7
    expect_equal(pt(r, "R1M1", "Al"), 12)
    expect_equal(pt(r, "R1M1", "Bo"), 7)
    expect_equal(r$result[r$matchup_id == "R1M1" & r$team == "Al"], "W")
    # Both winners flow into the final through the W: references
    expect_setequal(r$team[r$matchup_id == "R2M1"], c("Al", "Dee"))
    expect_equal(pt(r, "R2M1", "Dee"), 30)
    expect_equal(p$champion, "Dee")
  })
})

test_that("a multi-week round sums the weeks", {
  with_mocks({
    cfg <- test_cfg()
    cfg$rounds[[1]]$weeks <- list(14, 15)          # Ace: 12 + 4 = 16
    p <- sl_playoff(cfg, validate = FALSE)
    expect_equal(pt(p$results, "R1M1", "Al"), 16)
  })
})

test_that("a matchup with no submitted lineup stays PENDING", {
  with_mocks({
    cfg <- test_cfg()
    cfg$rounds[[2]]$matchups[[1]]$home$starters <- list()
    p <- sl_playoff(cfg, validate = FALSE)
    expect_true(all(p$results$result[p$results$matchup_id == "R2M1"] == "PENDING"))
    expect_null(p$champion)          # nothing is awarded on an unplayed final
  })
})

test_that("a bye advances unscored", {
  with_mocks({
    cfg <- test_cfg()
    cfg$rounds[[1]]$matchups[[2]] <- list(id = "R1M2", bye = "Dee")
    p <- sl_playoff(cfg, validate = FALSE)
    bye <- p$results[p$results$matchup_id == "R1M2", ]
    expect_equal(bye$result, "BYE")
    expect_true(is.na(bye$points))
    expect_equal(p$champion, "Dee")
  })
})

test_that("starters may be given as player names instead of ids", {
  with_mocks({
    cfg <- test_cfg()
    cfg$rounds[[1]]$matchups[[1]]$home$starters <- list("Ace")
    p <- sl_playoff(cfg, validate = FALSE)
    expect_equal(pt(p$results, "R1M1", "Al"), 12)
  })
})

test_that("sl_check_lineup flags illegal submissions", {
  with_mocks({
    rp <- c("QB", "RB", "WR", "FLEX", "BN")       # 4 starting slots
    short <- sl_check_lineup("1", rp, fake_players)
    expect_true(any(grepl("starters", short)))
    expect_length(sl_check_lineup(c("1", "4", "2", "3"), rp, fake_players), 0)
    expect_true(any(grepl("RB", sl_check_lineup(c("1", "2", "3"), rp, fake_players))))
  })
})

# --- brackets belong to a league, not to a season number --------------------

write_cfg <- function(dir, league_id) {
  cfg <- test_cfg()
  cfg$league_id <- league_id
  cfg$roster_positions <- list("QB")   # stated, so nothing hits the network
  jsonlite::write_json(cfg, file.path(dir, "2025.json"), auto_unbox = TRUE)
  dir
}

test_that("sl_playoff_configs filters by league", {
  d <- withr::local_tempdir()
  write_cfg(d, "111")
  expect_equal(names(sl_playoff_configs(d)), "2025")                 # unfiltered
  expect_equal(names(sl_playoff_configs(d, "111")), "2025")          # its own league
  # Another league's 2025 is NOT this bracket: it must not be handed over.
  expect_length(sl_playoff_configs(d, "222"), 0)
  with_mocks(expect_length(sl_load_playoffs(d, league_ids = "222"), 0))
})

test_that("sl_apply_playoffs does not stamp another league's champion", {
  d <- withr::local_tempdir()
  write_cfg(d, "111")
  mk <- function(lid) list(`2025` = list(
    season = "2025", league_id = lid,
    standings = tibble::tibble(user_name = c("Dee", "Al"),
                               champion = c(FALSE, FALSE))))

  with_mocks({
    same <- sl_apply_playoffs(mk("111"), d)
    expect_equal(same[["2025"]]$standings$champion, c(TRUE, FALSE))

    other <- sl_apply_playoffs(mk("222"), d)   # different league, same season
    expect_equal(other[["2025"]]$standings$champion, c(FALSE, FALSE))
  })
})
