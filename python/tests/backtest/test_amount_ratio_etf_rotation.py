import unittest

import pandas as pd

from python.research.etf.etf_amount_ratio_rotation.study import (
    attach_selection_metadata,
    build_selection_schedule,
    choose_low_flow_candidate,
)


class AmountRatioSelectionTests(unittest.TestCase):
    def test_selection_metadata_replaces_legacy_selection_type_without_suffix_columns(self):
        trades = pd.DataFrame({"buy_date": ["20240103"], "selection_type": ["legacy"], "code": ["512800.SH"]})
        selections = pd.DataFrame({
            "execution_date": ["2024-01-03"], "selection_type": ["low_amount_ratio"],
            "amount_ratio_7_20": [0.8], "volume_ratio_7_20": [0.9],
            "amount_quintile": ["Q1"], "volume_quintile": ["Q2"],
            "candidate_count": [10], "trend_candidate_count": [7],
        })

        enriched = attach_selection_metadata(trades, selections)

        self.assertEqual(enriched.loc[0, "selection_type"], "low_amount_ratio")
        self.assertNotIn("selection_type_x", enriched.columns)
        self.assertNotIn("selection_type_y", enriched.columns)

    def test_returns_none_for_an_empty_dynamic_candidate_snapshot(self):
        self.assertIsNone(choose_low_flow_candidate(pd.DataFrame()))

    def test_selection_schedule_includes_existing_execution_metadata_fields(self):
        signal_date = pd.Timestamp("2024-01-02")
        codes = ["510880.SH", "512800.SH", "512880.SH", "512200.SH", "159928.SZ"]
        factor_daily = {
            code: pd.DataFrame([{
                "date": signal_date, "ma10_above_ma30": True,
                "amount_ratio_7_20": 0.5 + index * 0.1,
                "volume_ratio_7_20": 1.0 + index * 0.1,
            }])
            for index, code in enumerate(codes)
        }
        schedule, _ = build_selection_schedule(
            pd.DataFrame({"date": [signal_date], "signal_type": ["class_2"]}),
            factor_daily,
            pd.Series([signal_date, pd.Timestamp("2024-01-03")]),
            common_only=False,
        )

        self.assertIn("rs20", schedule[pd.Timestamp("2024-01-03")])
        self.assertIn("gap10", schedule[pd.Timestamp("2024-01-03")])

    def test_chooses_next_lowest_amount_group_when_q1_is_volume_q5(self):
        candidates = pd.DataFrame([
            {"code": "A", "name": "A", "ma10_above_ma30": True, "amount_ratio_7_20": 0.60, "volume_ratio_7_20": 5.0},
            {"code": "B", "name": "B", "ma10_above_ma30": True, "amount_ratio_7_20": 0.70, "volume_ratio_7_20": 1.0},
            {"code": "C", "name": "C", "ma10_above_ma30": True, "amount_ratio_7_20": 0.80, "volume_ratio_7_20": 2.0},
            {"code": "D", "name": "D", "ma10_above_ma30": True, "amount_ratio_7_20": 0.90, "volume_ratio_7_20": 3.0},
            {"code": "E", "name": "E", "ma10_above_ma30": True, "amount_ratio_7_20": 1.00, "volume_ratio_7_20": 4.0},
        ])

        selected = choose_low_flow_candidate(candidates)

        self.assertEqual(selected.code, "B")
        self.assertEqual(selected.amount_quintile, "Q2")
        self.assertEqual(selected.volume_quintile, "Q1")

    def test_returns_none_when_fewer_than_five_trend_candidates_exist(self):
        candidates = pd.DataFrame([
            {"code": code, "name": code, "ma10_above_ma30": True, "amount_ratio_7_20": value, "volume_ratio_7_20": value}
            for code, value in zip(["A", "B", "C", "D"], [0.5, 0.6, 0.7, 0.8])
        ])

        self.assertIsNone(choose_low_flow_candidate(candidates))

    def test_excludes_lowest_amount_etf_when_its_ma10_is_not_above_ma30(self):
        candidates = pd.DataFrame([
            {"code": "A", "name": "A", "ma10_above_ma30": False, "amount_ratio_7_20": 0.10, "volume_ratio_7_20": 1.0},
            {"code": "B", "name": "B", "ma10_above_ma30": True, "amount_ratio_7_20": 0.60, "volume_ratio_7_20": 1.0},
            {"code": "C", "name": "C", "ma10_above_ma30": True, "amount_ratio_7_20": 0.70, "volume_ratio_7_20": 2.0},
            {"code": "D", "name": "D", "ma10_above_ma30": True, "amount_ratio_7_20": 0.80, "volume_ratio_7_20": 3.0},
            {"code": "E", "name": "E", "ma10_above_ma30": True, "amount_ratio_7_20": 0.90, "volume_ratio_7_20": 4.0},
            {"code": "F", "name": "F", "ma10_above_ma30": True, "amount_ratio_7_20": 1.00, "volume_ratio_7_20": 5.0},
        ])

        selected = choose_low_flow_candidate(candidates)

        self.assertEqual(selected.code, "B")


if __name__ == "__main__":
    unittest.main()
