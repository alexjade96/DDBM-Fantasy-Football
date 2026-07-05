test_that("sl_discord_verify accepts valid and rejects tampered signatures", {
  skip_if_not_installed("sodium")
  key <- sodium::sig_keygen()
  pub <- sodium::sig_pubkey(key)
  ts <- "1700000000"; body <- '{"type":1}'
  sig <- sodium::sig_sign(charToRaw(paste0(ts, body)), key)
  expect_true(sl_discord_verify(sodium::bin2hex(pub), sodium::bin2hex(sig), ts, body))
  # tampered body -> reject
  expect_false(sl_discord_verify(sodium::bin2hex(pub), sodium::bin2hex(sig), ts,
                                 '{"type":2}'))
})

test_that("sl_week_stats returns one row per team for the week", {
  s <- make_season()
  d <- sl_week_stats(s, 2)
  expect_equal(nrow(d), 3L)
  expect_true(all(c("points", "opp_points", "margin", "left_on_bench") %in% names(d)))
  expect_equal(unique(d$week), 2)
})

test_that("sl_summary_week is a single markdown recap", {
  txt <- sl_summary_week(make_season(), 2)
  expect_length(txt, 1L)
  expect_match(txt, "Week 2 recap")
  expect_match(txt, "Top score")
})

test_that("sl_discord_render routes commands and renders charts", {
  dir <- tempfile("shot"); dir.create(dir)
  # text-only command
  h <- sl_discord_render("help", out_dir = dir)
  expect_match(h$content, "Commands")
  expect_length(h$files, 0L)
  # chart command writes a file
  r <- sl_discord_render("standings", season = make_season(), out_dir = dir)
  expect_length(r$files, 1L)
  expect_true(file.exists(r$files))
  # weekly command yields recap text
  w <- sl_discord_render("weekly", season = make_season(), out_dir = dir)
  expect_match(w$content, "recap")
  # unknown command
  u <- sl_discord_render("bogus", out_dir = dir)
  expect_match(u$content, "Unknown command")
})

test_that("sl_discord_commands are well-formed", {
  cmds <- sl_discord_commands()
  nms <- vapply(cmds, `[[`, "", "name")
  expect_true(all(c("standings", "luck", "weekly", "career", "help") %in% nms))
})
