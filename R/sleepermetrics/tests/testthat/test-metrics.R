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

test_that("sl_table_position ranks by cumulative record then points", {
  d <- sl_table_position(make_season())
  expect_equal(nrow(d), 6L)                          # 3 teams x 2 weeks
  wk2 <- d[d$week == 2, ]
  expect_equal(wk2$user_name[wk2$table_position == 1], "Al")   # 2-0, top
  expect_equal(wk2$user_name[wk2$table_position == 3], "Bo")   # 0-2, bottom
  expect_true(all(wk2$table_position == 1:3))
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
