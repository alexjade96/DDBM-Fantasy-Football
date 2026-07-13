"""Sleeper stat keys -> human language (mirrors R statnames.R).

`scoring_settings` is keyed by Sleeper's internal stat codes (`pass_yd`,
`bonus_rec_te`, `pts_allow_7_13`). Those are fine for arithmetic and useless to
a human reading the point-calculation chart, so everywhere we *show* a chart we
translate it. Kept in one table, mirrored 1:1 in R (R/sleepermetrics/R/statnames.R)
and diffed by the parity harness so the two vocabularies cannot drift.
"""
from __future__ import annotations

import pandas as pd

# stat key -> (group, label). Order within a group is the order it reads best in.
STAT_DICT: dict[str, tuple[str, str]] = {
    # -- Passing
    "pass_yd":         ("Passing", "Passing yards"),
    "pass_td":         ("Passing", "Passing touchdown"),
    "pass_int":        ("Passing", "Interception thrown"),
    "pass_int_td":     ("Passing", "Pick-six thrown"),
    "pass_2pt":        ("Passing", "Two-point conversion pass"),
    "pass_sack":       ("Passing", "Sack taken"),
    # -- Rushing
    "rush_yd":         ("Rushing", "Rushing yards"),
    "rush_td":         ("Rushing", "Rushing touchdown"),
    "rush_fd":         ("Rushing", "Rushing first down"),
    "rush_2pt":        ("Rushing", "Two-point conversion run"),
    # -- Receiving
    "rec":             ("Receiving", "Reception"),
    "rec_yd":          ("Receiving", "Receiving yards"),
    "rec_td":          ("Receiving", "Receiving touchdown"),
    "rec_2pt":         ("Receiving", "Two-point conversion catch"),
    "bonus_rec_te":    ("Receiving", "Reception by a tight end (bonus)"),
    # -- Turnovers a player commits or recovers
    "fum":             ("Fumbles", "Fumble"),
    "fum_lost":        ("Fumbles", "Fumble lost"),
    "fum_rec":         ("Fumbles", "Fumble recovered"),
    "fum_rec_td":      ("Fumbles", "Fumble returned for a touchdown"),
    # -- Kicking
    "fgm_0_19":        ("Kicking", "Field goal made, 0-19 yards"),
    "fgm_20_29":       ("Kicking", "Field goal made, 20-29 yards"),
    "fgm_30_39":       ("Kicking", "Field goal made, 30-39 yards"),
    "fgm_40_49":       ("Kicking", "Field goal made, 40-49 yards"),
    "fgm_50p":         ("Kicking", "Field goal made, 50+ yards"),
    "fgmiss":          ("Kicking", "Field goal missed"),
    "fgmiss_0_19":     ("Kicking", "Field goal missed, 0-19 yards"),
    "fgmiss_20_29":    ("Kicking", "Field goal missed, 20-29 yards"),
    "xpm":             ("Kicking", "Extra point made"),
    "xpmiss":          ("Kicking", "Extra point missed"),
    # -- Individual defensive players
    "sack":            ("Defense", "Sack"),
    "int":             ("Defense", "Interception caught"),
    "ff":              ("Defense", "Forced fumble"),
    "blk_kick":        ("Defense", "Blocked kick"),
    "safe":            ("Defense", "Safety"),
    "def_td":          ("Defense", "Defensive touchdown"),
    # -- Team defense / special teams unit
    "def_st_td":       ("Team D/ST", "Defensive or special-teams touchdown"),
    "def_st_ff":       ("Team D/ST", "Forced fumble by the defense"),
    "def_st_fum_rec":  ("Team D/ST", "Fumble recovered by the defense"),
    "st_td":           ("Team D/ST", "Special-teams touchdown (return)"),
    "st_ff":           ("Team D/ST", "Forced fumble on special teams"),
    "st_fum_rec":      ("Team D/ST", "Fumble recovered on special teams"),
    "pts_allow_0":     ("Points allowed", "Shutout - 0 points allowed"),
    "pts_allow_1_6":   ("Points allowed", "1-6 points allowed"),
    "pts_allow_7_13":  ("Points allowed", "7-13 points allowed"),
    "pts_allow_14_20": ("Points allowed", "14-20 points allowed"),
    "pts_allow_21_27": ("Points allowed", "21-27 points allowed"),
    "pts_allow_28_34": ("Points allowed", "28-34 points allowed"),
    "pts_allow_35p":   ("Points allowed", "35+ points allowed"),
}

GROUPS = ["Passing", "Rushing", "Receiving", "Fumbles", "Kicking", "Defense",
          "Team D/ST", "Points allowed", "Other"]


# Dict insertion order is the reading order within a group (field goals by
# distance, points allowed by bracket) -- alphabetising the labels would file
# "35+ points allowed" before "7-13".
_RANK = {stat: i for i, stat in enumerate(STAT_DICT)}


def stat_labels() -> pd.DataFrame:
    """Sleeper stat keys in plain English: `stat`, `group`, `label`."""
    return pd.DataFrame(
        [{"stat": k, "group": g, "label": lab} for k, (g, lab) in STAT_DICT.items()]
    )


def _num(x: float) -> str:
    """Trim trailing zeros: 4 not 4.00, 0.5 not 0.50."""
    return f"{x:g}"


def rule_text(stat: str, weight: float) -> str:
    """Phrase one weight as a sentence.

    A fractional *yardage* weight is really a rate: 0.04/passing yard is how
    Sleeper spells "1 point per 25 yards", so say it the way the league rules
    say it. Everything else stays a per-event value -- a half point for a sack
    taken is "-0.5 points", not "-1 point per 2".
    """
    if weight != weight:                       # NaN
        return ""
    if weight == 0:
        return "no points"
    per = 1 / abs(weight)
    if (stat.endswith("_yd") and abs(weight) < 1
            and abs(per - round(per)) < 1e-6 and round(per) > 1):
        sign = "-1 point per " if weight < 0 else "1 point per "
        return f"{sign}{round(per)} yards"
    pts = "point" if abs(weight) == 1 else "points"
    sign = "+" if weight > 0 else ""
    return f"{sign}{_num(weight)} {pts}"


def scoring_readable(rules: dict) -> pd.DataFrame:
    """A league's point-calculation chart, in human-readable language.

    Translates `scoring_settings` (or a bracket's stored snapshot of it) from
    Sleeper's stat codes into labelled, grouped, plain-English rules -- so the
    chart the playoff scores are computed from can actually be read by the humans
    whose season it decided.

    Unknown keys are never dropped: they fall into the "Other" group with their
    raw code as the label, so a new Sleeper stat shows up rather than vanishing.

    Returns `group`, `stat` (raw key), `label`, `weight`, `rule`.
    """
    cols = ["group", "stat", "label", "weight", "rule"]
    if not rules:
        return pd.DataFrame(columns=cols)
    rows = []
    for stat, weight in rules.items():
        group, label = STAT_DICT.get(stat, ("Other", stat))
        w = float(weight)
        rows.append({"group": group, "stat": stat, "label": label,
                     "weight": w, "rule": rule_text(stat, w),
                     "_rank": _RANK.get(stat, len(_RANK)), "_lab": label})
    d = pd.DataFrame(rows)
    d["group"] = pd.Categorical(d["group"], categories=GROUPS, ordered=True)
    d = d.sort_values(["group", "_rank", "_lab"]).reset_index(drop=True)
    d["group"] = d["group"].astype(str)
    return d[cols]
