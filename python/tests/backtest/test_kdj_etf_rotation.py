import pandas as pd

from python.research.etf.etf_kdj_rotation.study import choose_relative_strength_candidate


def test_choose_relative_strength_candidate_selects_the_highest_rs20_that_passes_all_filters():
    candidates = pd.DataFrame([
        {"code": "512800.SH", "ma10_above_ma30": True, "rs20": 0.03, "gap10_below_p80": True},
        {"code": "512880.SH", "ma10_above_ma30": True, "rs20": 0.05, "gap10_below_p80": True},
        {"code": "510880.SH", "ma10_above_ma30": True, "rs20": 0.08, "gap10_below_p80": False},
    ])

    result = choose_relative_strength_candidate(candidates)

    assert result.code == "512880.SH"


def test_choose_relative_strength_candidate_returns_none_without_a_qualified_industry():
    candidates = pd.DataFrame([
        {"code": "512800.SH", "ma10_above_ma30": False, "rs20": 0.03, "gap10_below_p80": True},
    ])

    assert choose_relative_strength_candidate(candidates) is None
