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

# --- per-account import: team names + icons ---------------------------------

test_that("sl_avatar_url handles both Sleeper shapes", {
  # An account avatar is a bare id and must be turned into a CDN url...
  expect_equal(sl_avatar_url("abc"), "https://sleepercdn.com/avatars/abc")
  # ...but a custom TEAM avatar is already a url: don't double-prefix it.
  u <- "https://sleepercdn.com/uploads/xyz.jpg"
  expect_equal(sl_avatar_url(u), u)
  expect_true(is.na(sl_avatar_url(NA)))
  expect_true(is.na(sl_avatar_url("")))
})

test_that("sl_league_accounts keys on the persistent user_id", {
  mk <- function(season, name, team, champ) list(
    season = season,
    accounts = tibble::tibble(
      roster_id = 1L, user_id = "u1", user_name = name, team_name = team,
      avatar_url = paste0("pic-", season), team_avatar_url = NA_character_,
      team = team),
    standings = tibble::tibble(user_name = name, champion = champ))

  # Same account, renamed between seasons: one row, not two.
  d <- sl_league_accounts(list(`2024` = mk("2024", "Old", "Old FC", TRUE),
                               `2025` = mk("2025", "New", "New FC", FALSE)))
  expect_equal(nrow(d), 1)
  expect_equal(d$user_name, "New")        # current identity wins
  expect_equal(d$avatar_url, "pic-2025")  # ...including the current picture
  expect_equal(d$seasons, 2L)
  expect_equal(d$titles, 1L)
  expect_equal(d$first_season, "2024")
  expect_equal(d$last_season, "2025")
})

# --- player portraits -------------------------------------------------------

test_that("sl_headshot_url uses the team logo for a team defense", {
  expect_equal(sl_headshot_url("4034"),
               "https://sleepercdn.com/content/nfl/players/4034.jpg")
  # A team defense has no face -- its "player_id" IS its team.
  expect_equal(sl_headshot_url("SF", "DEF"),
               "https://sleepercdn.com/images/team_logos/nfl/sf.png")
  expect_equal(sl_headshot_url("NE"),
               "https://sleepercdn.com/images/team_logos/nfl/ne.png")
})

test_that("portraits degrade to NULL when disabled", {
  withr::local_envvar(SLEEPERMETRICS_NO_IMAGES = "1")
  # Charts must render offline: no image is a NULL, never an error.
  expect_null(sl_headshot("4034"))
  expect_null(sl_headshot_grob("4034"))
})
