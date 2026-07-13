# Sleeper stat keys -> human language --------------------------------------
#
# `scoring_settings` is keyed by Sleeper's internal stat codes (`pass_yd`,
# `bonus_rec_te`, `pts_allow_7_13`). Those are fine for arithmetic and useless
# to a human reading the point-calculation chart, so everywhere we *show* a
# chart we translate it. Kept in one table, mirrored 1:1 in Python
# (python/sleepermetrics/statnames.py) and diffed by the parity harness so the
# two vocabularies cannot drift.

# stat key, group, label. Order within a group is the order it reads best in.
.sl_stat_dict <- tibble::tribble(
  ~stat,             ~group,        ~label,
  # -- Passing
  "pass_yd",         "Passing",     "Passing yards",
  "pass_td",         "Passing",     "Passing touchdown",
  "pass_int",        "Passing",     "Interception thrown",
  "pass_int_td",     "Passing",     "Pick-six thrown",
  "pass_2pt",        "Passing",     "Two-point conversion pass",
  "pass_sack",       "Passing",     "Sack taken",
  # -- Rushing
  "rush_yd",         "Rushing",     "Rushing yards",
  "rush_td",         "Rushing",     "Rushing touchdown",
  "rush_fd",         "Rushing",     "Rushing first down",
  "rush_2pt",        "Rushing",     "Two-point conversion run",
  # -- Receiving
  "rec",             "Receiving",   "Reception",
  "rec_yd",          "Receiving",   "Receiving yards",
  "rec_td",          "Receiving",   "Receiving touchdown",
  "rec_2pt",         "Receiving",   "Two-point conversion catch",
  "bonus_rec_te",    "Receiving",   "Reception by a tight end (bonus)",
  # -- Turnovers a player commits or recovers
  "fum",             "Fumbles",     "Fumble",
  "fum_lost",        "Fumbles",     "Fumble lost",
  "fum_rec",         "Fumbles",     "Fumble recovered",
  "fum_rec_td",      "Fumbles",     "Fumble returned for a touchdown",
  # -- Kicking
  "fgm_0_19",        "Kicking",     "Field goal made, 0-19 yards",
  "fgm_20_29",       "Kicking",     "Field goal made, 20-29 yards",
  "fgm_30_39",       "Kicking",     "Field goal made, 30-39 yards",
  "fgm_40_49",       "Kicking",     "Field goal made, 40-49 yards",
  "fgm_50p",         "Kicking",     "Field goal made, 50+ yards",
  "fgmiss",          "Kicking",     "Field goal missed",
  "fgmiss_0_19",     "Kicking",     "Field goal missed, 0-19 yards",
  "fgmiss_20_29",    "Kicking",     "Field goal missed, 20-29 yards",
  "xpm",             "Kicking",     "Extra point made",
  "xpmiss",          "Kicking",     "Extra point missed",
  # -- Individual defensive players
  "sack",            "Defense",     "Sack",
  "int",             "Defense",     "Interception caught",
  "ff",              "Defense",     "Forced fumble",
  "blk_kick",        "Defense",     "Blocked kick",
  "safe",            "Defense",     "Safety",
  "def_td",          "Defense",     "Defensive touchdown",
  # -- Team defense / special teams unit
  "def_st_td",       "Team D/ST",   "Defensive or special-teams touchdown",
  "def_st_ff",       "Team D/ST",   "Forced fumble by the defense",
  "def_st_fum_rec",  "Team D/ST",   "Fumble recovered by the defense",
  "st_td",           "Team D/ST",   "Special-teams touchdown (return)",
  "st_ff",           "Team D/ST",   "Forced fumble on special teams",
  "st_fum_rec",      "Team D/ST",   "Fumble recovered on special teams",
  "pts_allow_0",     "Points allowed", "Shutout - 0 points allowed",
  "pts_allow_1_6",   "Points allowed", "1-6 points allowed",
  "pts_allow_7_13",  "Points allowed", "7-13 points allowed",
  "pts_allow_14_20", "Points allowed", "14-20 points allowed",
  "pts_allow_21_27", "Points allowed", "21-27 points allowed",
  "pts_allow_28_34", "Points allowed", "28-34 points allowed",
  "pts_allow_35p",   "Points allowed", "35+ points allowed"
)

.sl_stat_groups <- c("Passing", "Rushing", "Receiving", "Fumbles", "Kicking",
                     "Defense", "Team D/ST", "Points allowed", "Other")

# Row order in the dictionary is the reading order within a group (field goals by
# distance, points allowed by bracket) -- alphabetising the labels would file
# "35+ points allowed" before "7-13".
.sl_stat_dict$rank <- seq_len(nrow(.sl_stat_dict))

#' Sleeper stat keys in plain English
#'
#' The lookup behind every point-calculation chart we display: Sleeper's stat
#' codes mapped to a readable label and a category.
#'
#' @return Tibble with `stat`, `group`, `label`.
#' @seealso [sl_scoring_readable()]
#' @export
sl_stat_labels <- function() .sl_stat_dict[, c("stat", "group", "label")]

# A fractional *yardage* weight is really a rate: 0.04/passing yard is how
# Sleeper spells "1 point per 25 yards", so say it the way the league rules say
# it. Everything else stays a per-event value -- a half point for a sack taken is
# "-0.5 points", not "-1 point per 2".
.sl_rule_text <- function(stat, weight) {
  if (is.na(weight)) return("")
  if (weight == 0) return("no points")
  per <- 1 / abs(weight)
  if (grepl("_yd$", stat) && abs(weight) < 1 &&
      abs(per - round(per)) < 1e-6 && round(per) > 1) {
    sign <- if (weight < 0) "-1 point per " else "1 point per "
    return(paste0(sign, round(per), " yards"))
  }
  pts <- if (abs(weight) == 1) "point" else "points"
  paste0(if (weight > 0) "+" else "", .sl_num(weight), " ", pts)
}

# Trim trailing zeros: 4 not 4.00, 0.5 not 0.50.
.sl_num <- function(x) format(x, trim = TRUE, drop0trailing = TRUE, scientific = FALSE)

#' A league's point-calculation chart, in human-readable language
#'
#' Translates `scoring_settings` (or a bracket's stored snapshot of it) from
#' Sleeper's stat codes into labelled, grouped, plain-English rules -- so the
#' chart the playoff scores are computed from can actually be read by the humans
#' whose season it decided.
#'
#' Unknown keys are never dropped: they fall into the "Other" group with their
#' raw code as the label, so a new Sleeper stat shows up rather than vanishing.
#'
#' @param rules Named list / vector of `stat -> weight` (e.g.
#'   `sl_scoring_rules()`, or `playoff$config$scoring_settings`).
#' @return Tibble with `group`, `stat` (raw key), `label`, `weight`, `rule`
#'   (the weight phrased as a sentence), ordered by group.
#' @examples
#' \dontrun{
#' sl_scoring_readable(sl_scoring_rules(league_id))
#' }
#' @seealso [sl_scoring_chart()], [sl_stat_labels()]
#' @export
sl_scoring_readable <- function(rules) {
  if (!length(rules)) {
    return(tibble(group = character(), stat = character(), label = character(),
                  weight = numeric(), rule = character()))
  }
  d <- tibble(stat = names(rules), weight = as.numeric(unlist(rules))) %>%
    dplyr::left_join(.sl_stat_dict, by = "stat") %>%
    dplyr::mutate(
      group = dplyr::coalesce(.data$group, "Other"),
      label = dplyr::coalesce(.data$label, .data$stat),
      rank  = dplyr::coalesce(.data$rank, nrow(.sl_stat_dict) + 1L),
      rule  = vapply(seq_len(dplyr::n()),
                     function(i) .sl_rule_text(.data$stat[i], .data$weight[i]),
                     character(1)),
      group = factor(.data$group, levels = .sl_stat_groups)
    ) %>%
    dplyr::arrange(.data$group, .data$rank, .data$label) %>%
    dplyr::mutate(group = as.character(.data$group))
  d[, c("group", "stat", "label", "weight", "rule")]
}
