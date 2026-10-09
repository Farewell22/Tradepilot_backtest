"""Immutable experiment artifact output."""
from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pandas as pd


def write_experiment_artifacts(output_dir: Path, observations: pd.DataFrame, summary: pd.DataFrame, metadata: Mapping[str, object]) -> None:
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(f"实验输出目录已存在，拒绝覆盖: {output_dir}")
    output_dir.mkdir(parents=True)
    observations.to_csv(output_dir / "observations.csv", index=False, encoding="utf-8")
    summary.to_csv(output_dir / "factor_summary.csv", index=False, encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(dict(metadata), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    report = "# 0AMV 因子研究报告\n\n本报告检验收盘后可得的 0AMV 特征与未来市场结果的关系，不构成交易建议。\n\n## 数据质量\n\n"
    report += f"逐日观测数：{len(observations)}；汇总行数：{len(summary)}。\n\n## 因子结果\n\n"
    report += summary.to_markdown(index=False) if not summary.empty else "无可评估结果。"
    (output_dir / "report.md").write_text(report + "\n", encoding="utf-8")
