import pandas as pd
import unittest
from unittest.mock import patch

from python.backtest_dashboard import service


class AmountRatioRotationDashboardTests(unittest.TestCase):
    def test_load_amount_ratio_rotation_reads_dynamic_stage_artifacts(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "amount_ratio_rotation"
            run_dir.mkdir()
            pd.DataFrame([{
                "universe": "dynamic_universe", "stage": "oos", "stage_start": "2024-01-01",
                "entry_signal_count": 12, "fallback_510300_count": 1, "final_value": 261000.0,
                "total_return_pct": 30.5, "annualized_return_pct": 14.0, "max_drawdown_pct": -4.7,
                "closed_trade_count": 7, "win_rate_pct": 85.7, "ignored_buy_signals": 5,
            }]).to_csv(run_dir / "summary.csv", index=False)
            pd.DataFrame({
                "date": ["2024-01-02", "2024-01-03"], "nav": [200000.0, 202000.0],
                "return_pct": [0.0, 1.0], "drawdown_pct": [0.0, 0.0],
            }).to_csv(run_dir / "nav_dynamic_universe_oos.csv", index=False)
            pd.DataFrame({"year": [2024], "return_pct": [5.0], "max_drawdown_pct": [-2.0], "end_nav": [210000.0]}).to_csv(
                run_dir / "annual_dynamic_universe_oos.csv", index=False
            )
            pd.DataFrame([{
                "code": "512800.SH", "name": "银行", "buy_date": "20240102", "sell_date": "20240103",
                "buy_signal_type": "class_2", "selection_type": "low_amount_ratio",
                "amount_quintile": "Q1", "volume_quintile": "Q2", "amount_ratio_7_20": 0.8,
                "volume_ratio_7_20": 0.9, "pnl_pct": 2.0, "hold_days": 1, "sell_reason": "trend_exit_ma10_le_ma30",
            }]).to_csv(run_dir / "trades_dynamic_universe_oos.csv", index=False)
            with patch.object(service, "AMOUNT_RATIO_ROTATION_RUN_DIR", run_dir):
                result = service.load_amount_ratio_rotation("oos")

        self.assertEqual(result.universe, "dynamic_universe")
        self.assertEqual(result.summary.total_return_pct, 30.5)
        self.assertEqual(result.nav[-1].nav, 202000.0)
        self.assertEqual(result.annual[0].year, 2024)
        self.assertEqual(result.trades[0].code, "512800.SH")
        self.assertEqual(result.trades[0].amount_quintile, "Q1")
