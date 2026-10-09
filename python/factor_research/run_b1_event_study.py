"""Run a point-in-time 14:45 B1 conditional factor study."""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from python.factors.b1_filter import load_stock_rater_config
from python.factor_research.b1_event_study import (
    aggregate_bars_to_signal_time,
    attach_lagged_amv_features,
    attach_forward_event_returns,
    compute_provisional_indicators,
    score_prefiltered_day,
)
from python.factor_research.data import load_amv_csv
from python.factor_research.evaluators import evaluate_all
from python.factor_research.features import build_0amv_features
from python.factor_research.reporting import write_experiment_artifacts


def _paths(root: Path, start: str, end: str) -> list[Path]:
    return [p for p in sorted(root.glob("*/*.parquet")) if start <= p.stem <= end]


def run(config: dict) -> Path:
    paths, sample, evaluation = config["paths"], config["sample"], config["evaluation"]
    source_root = Path(paths["market_data_root"])
    signal_paths = _paths(source_root, sample["start_date"], sample["end_date"])
    history_paths = _paths(source_root, "00000000", sample["start_date"])[-140:]
    rating_config = load_stock_rater_config()
    weights = rating_config.get("weights")
    history: list[pd.DataFrame] = []
    for path in history_paths:
        raw = pd.read_parquet(path)
        history.append(aggregate_bars_to_signal_time(raw, "15:00:00"))
    daily_bars: list[tuple[pd.DataFrame, pd.DataFrame]] = []
    events: list[pd.DataFrame] = []
    for path in signal_paths:
        raw = pd.read_parquet(path)
        provisional = aggregate_bars_to_signal_time(raw, "14:45:00")
        full = aggregate_bars_to_signal_time(raw, "15:00:00")
        daily_bars.append((provisional, full))
    final_daily = pd.concat(history + [full for _, full in daily_bars], ignore_index=True)
    provisional_daily = pd.concat([provisional for provisional, _ in daily_bars], ignore_index=True)
    provisional_indicators = compute_provisional_indicators(final_daily, provisional_daily)
    passing = provisional_indicators.loc[
        (provisional_indicators["J"] < config["prefilter"]["j_threshold"])
        & (provisional_indicators["close"] > provisional_indicators["zxdkx"])
        & (provisional_indicators["zxdq"] > provisional_indicators["zxdkx"]),
        ["date", "code"],
    ]
    eligible_by_date = {
        date: set(data["code"])
        for date, data in passing.groupby("date", sort=False)
    }
    close_rows: list[pd.DataFrame] = []
    for provisional, full in daily_bars:
        if history and not provisional.empty:
            signal_date = provisional["date"].iloc[0]
            signal_events = score_prefiltered_day(
                pd.concat(history, ignore_index=True),
                provisional,
                eligible_by_date.get(signal_date, set()),
                weights,
                rating_config,
            )
            if not signal_events.empty:
                events.append(signal_events)
        history.append(full)
        history = history[-140:]
        close_rows.append(full.loc[:, ["code", "date", "close"]])
    event_frame = pd.concat(events, ignore_index=True) if events else pd.DataFrame(columns=["signal_date", "code", "entry_price"])
    close_long = pd.concat(close_rows, ignore_index=True)
    panel = close_long.pivot(index="date", columns="code", values="close").reset_index()
    event_frame = attach_forward_event_returns(event_frame, panel, evaluation["horizons"])
    amv = build_0amv_features(load_amv_csv(Path(paths["amv_csv"])), config["factors"]["ma_windows"], config["factors"]["return_windows"])
    event_frame = attach_lagged_amv_features(event_frame, amv)
    factors = [c for c in event_frame if c.startswith("amv_")]
    targets = [f"forward_return_{h}" for h in evaluation["horizons"]]
    summary = evaluate_all(event_frame.rename(columns={"signal_date": "date"}), factors, targets, evaluation["groups"])
    output = Path(paths["output_root"]) / f"b1_1445_{sample['start_date']}_{sample['end_date']}"
    write_experiment_artifacts(output, event_frame, summary, {"config": config, "entry": "T日14:45 close", "amv": "T-1 close"})
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    with args.config.open(encoding="utf-8") as f:
        print(run(yaml.safe_load(f)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
