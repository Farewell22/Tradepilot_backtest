"""Export standalone research figures without a dashboard dependency."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def write_figures(summary, effects, output_dir: Path):
    titles = {"1000": "CSI 1000 ETF (512100)", "50": "SSE 50 ETF (510050)", "spread": "CSI 1000 minus SSE 50"}
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6), constrained_layout=True)
    for ax, (target, title) in zip(axes, titles.items()):
        sample = summary.loc[summary.stage.eq("all") & summary.target.eq(target)]
        for horizon, group in sample.groupby("horizon"):
            ax.plot(group.percentile_bin, group.mean_pct, marker="o", label=f"{horizon} sessions")
        ax.axhline(0, color="gray", linewidth=.8)
        ax.set(title=title, xlabel="Rolling percentile decile (low to high)", ylabel="Mean forward return (%)")
        ax.set_xticks(range(1, 11))
        ax.legend(fontsize=8)
        ax.grid(alpha=.2)
    fig.savefig(output_dir / "quantile_returns.png", dpi=180)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), constrained_layout=True)
    for ax, (target, title) in zip(axes, titles.items()):
        sample = effects.loc[effects.stage.str.fullmatch(r"\d{4}") & effects.target.eq(target)]
        matrix = sample.pivot(index="stage", columns="horizon", values="spearman_ic")
        data = matrix.to_numpy(dtype=float)
        im = ax.imshow(data, vmin=-.5, vmax=.5, cmap="RdBu", aspect="auto")
        ax.set(title=title, xlabel="Forward sessions", ylabel="Observation year")
        ax.set_xticks(range(len(matrix.columns)), matrix.columns)
        ax.set_yticks(range(len(matrix.index)), matrix.index)
        for y, x in np.ndindex(data.shape):
            if np.isfinite(data[y, x]):
                ax.text(x, y, f"{data[y, x]:+.2f}", ha="center", va="center", fontsize=9)
        fig.colorbar(im, ax=ax, label="Spearman correlation")
    fig.savefig(output_dir / "annual_stability.png", dpi=180)
    plt.close(fig)
