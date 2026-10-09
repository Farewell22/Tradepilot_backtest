import unittest

import pandas as pd

from python.research.amv.amv_buy_reentry_filters.study import p40_reset_eligibility


class P40ResetEligibilityTests(unittest.TestCase):
    def test_sell_requires_a_sub_p40_reset_before_later_buys_are_eligible(self):
        dates = pd.date_range("2024-01-02", periods=5, freq="B")
        states = pd.DataFrame({
            "date": dates,
            "gap10_rank": [0.55, 0.88, 0.55, 0.39, 0.62],
            "has_momentum_sell": [False, True, False, False, False],
        })

        eligible = p40_reset_eligibility(states)

        self.assertEqual(eligible.tolist(), [True, False, False, True, True])


if __name__ == "__main__":
    unittest.main()
