import pandas as pd
import unittest

from python.research.etf.amv_buy_etf_cross_section.study import (
    add_flow_trend_features,
    aggregate_intraday_etf,
    attach_forward_returns,
)


class CrossSectionResearchTests(unittest.TestCase):
    def test_aggregate_intraday_etf_sums_volume_and_amount_into_daily_bars(self):
        raw = pd.DataFrame({
            "时间": ["2024-01-02 10:30", "2024-01-02 15:00"],
            "开盘价": [10.0, 10.5], "最高价": [10.8, 11.2], "最低价": [9.9, 10.4],
            "收盘价": [10.5, 11.0], "成交量": [100, 200], "成交额": [1000, 2200],
        })
        daily = aggregate_intraday_etf(raw)
        self.assertEqual(daily.loc[0, ["open", "high", "low", "close", "volume", "amount"]].tolist(), [10.0, 11.2, 9.9, 11.0, 300.0, 3200.0])

    def test_add_flow_trend_features_compares_latest_seven_days_only_to_prior_twenty_days(self):
        daily = pd.DataFrame({
            "date": pd.date_range("2024-01-01", periods=27, freq="B"), "close": [100.0] * 27,
            "amount": [100.0] * 20 + [200.0] * 7, "volume": [10.0] * 20 + [20.0] * 7,
        })
        featured = add_flow_trend_features(daily)
        self.assertAlmostEqual(featured.iloc[-1].amount_ratio_7_20, 2.0)
        self.assertAlmostEqual(featured.iloc[-1].volume_ratio_7_20, 2.0)

    def test_attach_forward_returns_enters_at_next_open_and_exits_at_nth_close(self):
        events = pd.DataFrame({"date": pd.to_datetime(["2024-01-01"])})
        daily = pd.DataFrame({
            "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"]),
            "open": [10.0, 11.0, 12.0, 13.0], "close": [10.5, 11.5, 12.5, 13.5],
        })
        labeled = attach_forward_returns(events, daily, horizons=(1, 3))
        self.assertEqual(labeled.loc[0, "entry_date"], pd.Timestamp("2024-01-02"))
        self.assertAlmostEqual(labeled.loc[0, "forward_return_1_pct"], (11.5 / 11.0 - 1) * 100)
        self.assertAlmostEqual(labeled.loc[0, "forward_return_3_pct"], (13.5 / 11.0 - 1) * 100)
