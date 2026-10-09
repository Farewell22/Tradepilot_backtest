import unittest

import pandas as pd

from python.research.amv.amv_quantile_window_impact.study import (
    minimum_history,
    rolling_gap_rank,
    stage_correlations,
    spearman_correlation,
)


class QuantileWindowImpactTests(unittest.TestCase):
    def test_minimum_history_scales_to_one_third_of_the_window(self):
        self.assertEqual(minimum_history(100), 34)
        self.assertEqual(minimum_history(200), 67)
        self.assertEqual(minimum_history(750), 250)

    def test_rank_uses_only_prior_gap_observations(self):
        ranks = rolling_gap_rank(pd.Series([1.0, 2.0, 3.0, 2.0]), window=3, min_history=2)

        self.assertTrue(pd.isna(ranks.iloc[1]))
        self.assertEqual(ranks.iloc[2], 1.0)
        self.assertEqual(ranks.iloc[3], 0.5)

    def test_spearman_correlation_does_not_require_scipy(self):
        self.assertEqual(spearman_correlation(pd.Series([1.0, 2.0, 3.0]), pd.Series([3.0, 2.0, 1.0])), -1.0)

    def test_stage_correlations_excludes_other_periods(self):
        states = pd.DataFrame({
            "date": pd.to_datetime(["2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "gap10_rank": [0.1, 0.1, 0.2, 0.3],
            "forward_return_5_pct": [-1.0, 1.0, 2.0, 3.0],
            "forward_return_10_pct": [-1.0, 1.0, 2.0, 3.0],
        })

        result = stage_correlations(states, "2024-01-01", "2024-12-31")

        self.assertEqual(result[5], 1.0)
        self.assertEqual(result[10], 1.0)


if __name__ == "__main__":
    unittest.main()
