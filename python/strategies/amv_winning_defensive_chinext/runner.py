"""Replace the attack ETF with E Fund ChiNext ETF 159915.SZ."""
from pathlib import Path
import sys

from python.run_backtest import RunRequest
from python.strategies.amv_winning_defensive_csi2000.runner import run_primary_variant


def run(request: RunRequest) -> Path:
    return run_primary_variant(
        request, primary_code="159915.SZ", primary_label="创业板指", variant="chinext",
        calendar_policy_path=Path(__file__).with_name("calendar_policy.json"),
    )


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", "amv_winning_defensive_chinext", *sys.argv[1:]]))
