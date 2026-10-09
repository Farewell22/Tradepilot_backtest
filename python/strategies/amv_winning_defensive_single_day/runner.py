"""Disable all multi-session primary entries while retaining direct ABC defense."""
from pathlib import Path
import sys

import pandas as pd

from python.run_backtest import RunRequest
from python.strategies.amv_winning import runner as original
from python.strategies.amv_winning_defensive_3d.runner import run_entry_variant


def generate_amv_signals(amv: pd.DataFrame) -> pd.DataFrame:
    signals = original.generate_amv_signals(amv)
    signals["buy_signal"] = (
        (signals["day_return"] >= .04) & (signals["close"] >= signals["ma5"])
    )
    return signals


def run(request: RunRequest) -> Path:
    return run_entry_variant(
        request, signal_generator=generate_amv_signals, variant="single_day",
        multi_day_sessions=None, multi_day_threshold=None,
        title="农行直接防守策略：仅单日涨幅≥4%入场",
        entry_description="取消所有多日涨幅入场分支，仅保留0AMV单日涨幅≥4%且收盘≥MA5的主仓入场。",
        variant_label="新版：仅单日≥4%",
    )


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", "amv_winning_defensive_single_day", *sys.argv[1:]]))
