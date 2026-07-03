test_that("ensure_cols backfills missing columns as NA", {
  df <- tibble::tibble(a = 1:2)
  out <- sleepermetrics:::ensure_cols(df, c("a", "b"))
  expect_true(all(c("a", "b") %in% names(out)))
  expect_true(all(is.na(out$b)))
})

test_that("sl_starter_slots parses roster_positions and drops bench", {
  rp <- c("QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN")
  s <- sleepermetrics:::sl_starter_slots(rp)
  expect_equal(as.integer(s[["QB"]]), 1L)
  expect_equal(as.integer(s[["RB"]]), 2L)
  expect_equal(as.integer(s[["FLEX"]]), 1L)
  expect_null(s[["BN"]])
})

test_that("sl_optimal_points builds the best legal lineup including flex", {
  d <- tibble::tibble(
    player_id = as.character(1:8),
    position  = c("QB", "RB", "RB", "RB", "WR", "WR", "TE", "K"),
    points    = c(20, 15, 12, 30, 10, 8, 5, 7))
  slots <- list(QB = 1, RB = 2, WR = 2, TE = 1, K = 1, FLEX = 1)
  # QB20 + RB(30,15) + WR(10,8) + TE5 + K7 + FLEX(best leftover RB/WR/TE = 12)
  expect_equal(sleepermetrics:::sl_optimal_points(d, slots), 107)
})

test_that("sl_palette returns one colour per manager", {
  p <- sl_palette(c("Bo", "Al", "Al"))
  expect_equal(length(p), 2L)
  expect_equal(sort(names(p)), c("Al", "Bo"))
})
