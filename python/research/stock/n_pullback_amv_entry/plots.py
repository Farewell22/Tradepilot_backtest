"""Standalone research charts with visible as-of structure annotations."""
from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def render_figures(output_dir: Path, daily, observations, summary):
    plt.rcParams["font.sans-serif"] = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    directory = output_dir / "figures"
    directory.mkdir(exist_ok=True)
    groups = ["universe", "broken", "intact", "Q1", "Q2", "Q3", "Q4", "Q5"]
    selected = summary[summary.stage.eq("all") & summary.threshold.eq(.05)]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5), sharey=True)
    for ax, h in zip(axes, (5, 10, 20)):
        table = selected[selected.horizon.eq(h)].set_index("group").reindex(groups)
        ax.bar(np.arange(len(groups)), table.mean_excess * 100,
               color=["#94a3b8", "#ef4444", "#16a34a"] + ["#3b82f6"] * 5)
        ax.set_xticks(np.arange(len(groups)), groups, rotation=40)
        ax.axhline(0, color="#64748b", linewidth=.8)
        ax.set_title(f"{h}日：日期等权平均超额收益")
        ax.grid(axis="y", alpha=.2)
    axes[0].set_ylabel("相对同日全A股等权收益（百分点）")
    fig.suptitle("三轮N型守前低因子 · 51个AMV主仓开仓日 · 5%波段")
    # Identical zero excess returns plus axhline can leave roundoff-sized limits;
    # shared-axis tight_layout then produces NaN geometry in matplotlib.
    finite = selected.mean_excess.to_numpy(dtype=float) * 100
    finite = finite[np.isfinite(finite)]
    if not len(finite) or np.max(np.abs(finite)) < 1e-8:
        axes[0].set_ylim(-.1, .1)
    fig.tight_layout()
    fig.savefig(directory / "group_excess_returns.png", dpi=160)
    plt.close(fig)

    sample = observations[observations.threshold.eq(.05) & observations.status.eq("valid")].copy()
    categories = {"high": sample[sample.factor >= 0].sort_values("factor", ascending=False),
                  "slight_break": sample[(sample.factor < 0) & (sample.factor > -.05)].sort_values("factor", ascending=False),
                  "deep_break": sample[sample.factor <= -.05].sort_values("factor")}
    chosen = []
    used = set()
    for category, candidates in categories.items():
        candidates = candidates.drop_duplicates("date")
        if len(candidates):
            indices = np.linspace(0, min(15, len(candidates) - 1), min(4, len(candidates))).astype(int)
            for _, row in candidates.iloc[indices].iterrows():
                key = (row.code, row.date)
                if key not in used:
                    chosen.append((category, row))
                    used.add(key)
    if len(chosen) < 12:
        for _, row in sample.sort_values(["date", "code"]).iterrows():
            if len(chosen) == 12:
                break
            if (row.code, row.date) not in used:
                chosen.append(("additional", row))
                used.add((row.code, row.date))
    export = []
    frames = {code: frame[frame.valid].sort_values("date").reset_index(drop=True)
              for code, frame in daily[daily.code.isin([row.code for _, row in chosen])].groupby("code", observed=True)}
    for number, (category, row) in enumerate(chosen, 1):
        frame = frames[row.code]
        end = int(frame.date.searchsorted(row.date, side="right"))
        start = max(0, int(row.L0_index) - 10)
        visible = frame.iloc[start:end]
        anchor = row.L0_price
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(visible.date, visible.close / anchor, color="#334155", label="复权收盘 / L0")
        ax.fill_between(visible.date, visible.low / anchor, visible.high / anchor, color="#94a3b8", alpha=.2)
        names = ("L0", "H1", "L1", "H2", "L2", "H3", "L3")
        dates = pd.to_datetime([row[f"{name}_date"] for name in names])
        prices = [row[f"{name}_price"] / anchor for name in names]
        ax.plot(dates, prices, "o--", color="#f97316", label="截至观察日可见结构")
        for name, date, price in zip(names, dates, prices):
            ax.annotate(name, (date, price), xytext=(0, 10), textcoords="offset points", ha="center")
        ax.axvline(row.date, color="#dc2626", linestyle=":", label="观察日，右侧数据未展示")
        ax.set_title(f"{row.code} · {row.date:%Y-%m-%d} · F={row.factor * 100:.2f}% · {category}")
        ax.set_ylabel("相对L0价格")
        ax.legend(fontsize=9)
        ax.grid(alpha=.2)
        fig.autofmt_xdate()
        fig.tight_layout()
        filename = f"structure_{number:02d}_{row.code}_{row.date:%Y%m%d}.png"
        fig.savefig(directory / filename, dpi=140)
        plt.close(fig)
        export.append({"file": filename, "code": row.code, "date": row.date, "factor": row.factor,
                       "category": category, "return_5": row.return_5, "return_10": row.return_10, "return_20": row.return_20})
    pd.DataFrame(export).to_csv(directory / "structure_examples.csv", index=False)
