"""Research MA10 gap filters for the 510300.SH + 0AMV trend signals."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pandas as pd

from python.research.date_scope import date_window, scoped_ranges
from python.backtest.broker import FeeConfig
from python.strategies.etf_amv.runner import load_settings, run_stage


SCENARIOS = {
    "A_baseline": {},
    "B_gap10_above_p50": {"min_amv_gap10_quantile": 0.50},
    "C_gap10_p50_with_p95_veto": {
        "min_amv_gap10_quantile": 0.50,
        "veto_amv_gap10_quantile": 0.95,
    },
}
SIGNAL_SETS = {
    "best-only": ["best"],
    "secondary-only": ["secondary"],
    "secondary-best": ["secondary", "best"],
}


def format_report(summary: pd.DataFrame) -> str:
    return (
        "# 0AMV MA10 乖离度筛选研究\n\n"
        "按场景、信号组合及训练/样本外阶段比较回测结果。各组合的逐笔交易、净值和原始报告保存在本次运行目录的对应子目录。\n\n"
        "## 组合汇总\n\n"
        + summary.to_markdown(index=False) + "\n"
    )


def run_research(
    config_path: Path, output_root: Path,
    start_date: str | None = None, end_date: str | None = None,
    fees: FeeConfig | None = None,
) -> pd.DataFrame:
    base = load_settings(config_path)
    stages = ("train", "oos")
    if start_date is not None and end_date is not None:
        with date_window(start_date, end_date):
            bounded = scoped_ranges({name: (sample["start_date"], sample["end_date"]) for name, sample in base["sample"].items()})
        if not bounded:
            raise ValueError("所选日期与研究样本没有交集")
        stages = tuple(bounded)
        for stage, (start, end) in bounded.items():
            base["sample"][stage] = {**base["sample"][stage], "start_date": start.replace("-", ""), "end_date": end.replace("-", "")}
    rows: list[dict] = []
    for scenario, filters in SCENARIOS.items():
        for signal_set, enabled in SIGNAL_SETS.items():
            settings = deepcopy(base)
            settings["strategy"]["enabled_signals"] = enabled
            settings["strategy"]["momentum_window_days"] = 5
            settings["strategy"].update(filters)
            settings["strategy"]["best_weight"] = 1.0
            settings["strategy"]["secondary_weight"] = 1.0
            settings["strategy"]["worst_weight"] = 1.0
            settings["paths"]["output_root"] = str(output_root / scenario / signal_set)
            for stage in stages:
                output_dir = run_stage(stage, settings, fees=fees)
                report = (output_dir / "report.txt").read_text(encoding="utf-8")
                metrics = {}
                for line in report.splitlines():
                    line = line.strip()
                    for key in ("期末净值:", "总收益率", "年化收益率", "最大回撤:", "夏普比率:", "已平仓次数:", "胜率:"):
                        if line.startswith(key):
                            metrics[key] = line.split(":", 1)[1].strip()
                trades = pd.read_csv(output_dir / "trades.csv")
                rows.append({
                    "scenario": scenario,
                    "signal_set": signal_set,
                    "stage": stage,
                    **metrics,
                    "止损次数": int(trades["sell_reason"].str.startswith("stop_loss").sum()),
                    "output": str(output_dir),
                })
    result = pd.DataFrame(rows)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "report.md").write_text(format_report(result), encoding="utf-8")
    return result


def main() -> None:
    root = Path("data/backtest_runs/etf_510300_0amv_ma10_gap_research")
    result = run_research(Path("python/config/etf_0amv.yaml"), root)
    result.to_csv(root / "summary.csv", index=False, encoding="utf-8-sig")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
