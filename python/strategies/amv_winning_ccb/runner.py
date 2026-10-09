"""Independent Construction Bank entry for both existing AMV bank variants."""
from pathlib import Path
import sys

from python.run_backtest import RunRequest


def run(request: RunRequest) -> Path:
    from python.strategies.amv_winning.bank_comparison import run_bank_task
    return run_bank_task(request, bank_code="601939.SH", bank_name="建设银行")


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", "amv_winning_ccb", *sys.argv[1:]]))
