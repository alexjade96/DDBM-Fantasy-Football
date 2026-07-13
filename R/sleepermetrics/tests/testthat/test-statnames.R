# Stat-code -> human language. Network-free: the dictionary is static.

test_that("yardage weights read as a rate", {
  # 0.04/yd is how Sleeper spells "1 point per 25 yards" -- say it that way.
  expect_equal(.sl_rule_text("pass_yd", 0.04), "1 point per 25 yards")
  expect_equal(.sl_rule_text("rush_yd", 0.1), "1 point per 10 yards")
})

test_that("non-yardage fractions stay per-event", {
  # A half point for taking a sack is -0.5, NOT "-1 point per 2".
  expect_equal(.sl_rule_text("pass_sack", -0.5), "-0.5 points")
  expect_equal(.sl_rule_text("bonus_rec_te", 0.25), "+0.25 points")
})

test_that("whole weights and zero", {
  expect_equal(.sl_rule_text("rec_td", 6), "+6 points")
  expect_equal(.sl_rule_text("rec", 1), "+1 point")        # singular
  expect_equal(.sl_rule_text("fum_lost", -2), "-2 points")
  expect_equal(.sl_rule_text("fum", 0), "no points")
})

test_that("every rule is translated and grouped", {
  d <- sl_scoring_readable(list(pass_yd = 0.04, bonus_rec_te = 0.25, pts_allow_0 = 10))
  expect_equal(names(d), c("group", "stat", "label", "weight", "rule"))
  expect_setequal(d$label, c("Passing yards", "Reception by a tight end (bonus)",
                             "Shutout - 0 points allowed"))
  expect_false("Other" %in% d$group)
})

test_that("unknown keys surface rather than vanish", {
  d <- sl_scoring_readable(list(pass_td = 4, brand_new_stat = 3))
  expect_equal(nrow(d), 2)                                  # nothing dropped
  row <- d[d$stat == "brand_new_stat", ]
  expect_equal(row$group, "Other")
  expect_equal(row$label, "brand_new_stat")
})

test_that("reading order is the dictionary's, not alphabetical", {
  # Points allowed must descend by bracket; alphabetising labels would file
  # "35+ points allowed" before "7-13 points allowed".
  d <- sl_scoring_readable(list(pts_allow_35p = -4, pts_allow_7_13 = 4,
                                pts_allow_0 = 10, pts_allow_14_20 = 1))
  expect_equal(d$stat, c("pts_allow_0", "pts_allow_7_13",
                         "pts_allow_14_20", "pts_allow_35p"))
})

test_that("an empty chart is an empty frame, not an error", {
  expect_equal(nrow(sl_scoring_readable(list())), 0)
})

test_that("the dictionary has no duplicate labels within a group", {
  d <- sl_stat_labels()
  expect_false(any(duplicated(d[, c("group", "label")])))
  expect_false(any(duplicated(d$stat)))
})
