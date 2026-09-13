"""Stat-code -> human language. Network-free: the dictionary is static."""
from sleepermetrics.statnames import STAT_DICT, rule_text, scoring_readable


def test_yardage_weights_read_as_a_rate():
    # 0.04/yd is how Sleeper spells "1 point per 25 yards" -- say it that way.
    assert rule_text("pass_yd", 0.04) == "1 point per 25 yards"
    assert rule_text("rush_yd", 0.1) == "1 point per 10 yards"


def test_non_yardage_fractions_stay_per_event():
    # A half point for taking a sack is -0.5, NOT "-1 point per 2".
    assert rule_text("pass_sack", -0.5) == "-0.5 points"
    assert rule_text("bonus_rec_te", 0.25) == "+0.25 points"


def test_whole_weights_and_zero():
    assert rule_text("rec_td", 6.0) == "+6 points"
    assert rule_text("rec", 1.0) == "+1 point"          # singular
    assert rule_text("fum_lost", -2.0) == "-2 points"
    assert rule_text("fum", 0.0) == "no points"


def test_every_rule_is_translated_and_grouped():
    d = scoring_readable({"pass_yd": 0.04, "bonus_rec_te": 0.25, "pts_allow_0": 10})
    assert list(d.columns) == ["group", "stat", "label", "weight", "rule"]
    assert set(d["label"]) == {"Passing yards", "Reception by a tight end (bonus)",
                               "Shutout - 0 points allowed"}
    assert "Other" not in set(d["group"])


def test_unknown_keys_surface_rather_than_vanish():
    d = scoring_readable({"pass_td": 4, "brand_new_stat": 3})
    assert len(d) == 2                       # nothing dropped
    row = d[d["stat"] == "brand_new_stat"].iloc[0]
    assert row["group"] == "Other" and row["label"] == "brand_new_stat"


def test_reading_order_is_the_dictionarys_not_alphabetical():
    # Points allowed must descend by bracket; alphabetising labels would file
    # "35+ points allowed" before "7-13 points allowed".
    d = scoring_readable({"pts_allow_35p": -4, "pts_allow_7_13": 4,
                          "pts_allow_0": 10, "pts_allow_14_20": 1})
    assert list(d["stat"]) == ["pts_allow_0", "pts_allow_7_13",
                               "pts_allow_14_20", "pts_allow_35p"]


def test_empty_chart_is_an_empty_frame_not_an_error():
    assert scoring_readable({}).empty


def test_dictionary_has_no_duplicate_labels_within_a_group():
    seen = set()
    for stat, (group, label) in STAT_DICT.items():
        assert (group, label) not in seen, f"{stat} duplicates {group}/{label}"
        seen.add((group, label))
