"""Command-line runner for reproducible 0AMV factor experiments."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import yaml

from python.factor_research.data import IndexCache, load_amv_csv, load_market_close_panel
from python.factor_research.evaluators import evaluate_all
from python.factor_research.features import build_0amv_features
from python.factor_research.labels import build_breadth_labels, build_forward_return_labels
from python.factor_research.reporting import write_experiment_artifacts


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def run(config: dict, refresh: bool = False) -> Path:
    paths, sample, factors, evaluation = (config[key] for key in ("paths", "sample", "factors", "evaluation"))
    amv = load_amv_csv(Path(paths["amv_csv"]))
    features = build_0amv_features(amv, factors["ma_windows"], factors["return_windows"])
    cache = IndexCache(Path(paths["index_cache_root"]))
    observations = features
    for code in config["indices"]:
        index = cache.load(code, sample["start_date"], sample["end_date"], refresh)
        observations = observations.merge(build_forward_return_labels(index, evaluation["horizons"], code), on="date", how="left")
    panel = load_market_close_panel(Path(paths["market_data_root"]), sample["start_date"], sample["end_date"]).reset_index()
    observations = observations.merge(build_breadth_labels(panel, evaluation["horizons"]), on="date", how="left")
    start, end = pd.to_datetime(sample["start_date"]), pd.to_datetime(sample["end_date"])
    observations = observations.loc[observations["date"].between(start, end)].reset_index(drop=True)
    factor_columns = [column for column in observations if column.startswith("amv_")]
    target_columns = [column for column in observations if "forward_return_" in column or column.startswith("advance_ratio_")]
    summary = evaluate_all(observations, factor_columns, target_columns, evaluation["groups"])
    config_blob = json.dumps(config, ensure_ascii=False, sort_keys=True)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(config_blob.encode()).hexdigest()[:8]
    output = Path(paths["output_root"]) / run_id
    write_experiment_artifacts(output, observations, summary, {"config": config, "git_commit": _git_commit(), "run_id": run_id, "generated_at": datetime.now(UTC).isoformat()})
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="0AMV 因子研究")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args(argv)
    with args.config.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    output = run(config, args.refresh)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
