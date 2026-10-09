"""Time-series descriptive statistics and dependence-aware uncertainty."""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20, 60)
TARGETS = {"1000": "return_1000", "50": "return_50", "spread": "spread"}
BLOCK_LENGTH = 120
BOOTSTRAP_REPEATS = 2000
SEED = 42


def effect_values(frame: pd.DataFrame, target: str) -> tuple[float, float]:
    paired = frame[["rs20_percentile", "percentile_bin", target]].dropna()
    ic = np.nan
    if len(paired) >= 3 and paired.rs20_percentile.nunique() > 1 and paired[target].nunique() > 1:
        ic = paired.rs20_percentile.rank().corr(paired[target].rank())
    high = paired.loc[paired.percentile_bin.eq(10), target]
    low = paired.loc[paired.percentile_bin.eq(1), target]
    return float(ic), float((high.mean() - low.mean()) * 100)


def bootstrap_effects(frame: pd.DataFrame, target: str, *, repeats: int = BOOTSTRAP_REPEATS,
                      block_length: int = BLOCK_LENGTH, seed: int = SEED) -> dict[str, float]:
    """Resample chronological blocks BEFORE removing missing outcome labels."""
    result = dict.fromkeys(("ic_ci_low", "ic_ci_high", "spread_ci_low_pct", "spread_ci_high_pct"), np.nan)
    if repeats <= 0 or block_length <= 0:
        raise ValueError("bootstrap重复次数及块长必须为正")
    if frame[target].notna().sum() < 2 * block_length:
        return result
    ic, spread = effect_values(frame, target)
    if not np.isfinite(ic) and not np.isfinite(spread):
        return result
    # Include unlabeled calendar rows in blocks: dropna first would bridge holes.
    rng = np.random.default_rng(seed)
    n = len(frame)
    offsets = np.arange(block_length)
    blocks = int(np.ceil(n / block_length))
    values = np.full((repeats, 2), np.nan)
    for iteration in range(repeats):
        starts = rng.integers(0, n - block_length + 1, blocks)
        indices = (starts[:, None] + offsets).ravel()[:n]
        values[iteration] = effect_values(frame.iloc[indices], target)
    for index, keys in enumerate((("ic_ci_low", "ic_ci_high"), ("spread_ci_low_pct", "spread_ci_high_pct"))):
        valid = values[:, index][np.isfinite(values[:, index])]
        # An absent extreme group must not yield a confident interval.
        if len(valid) >= .95 * repeats:
            result[keys[0]], result[keys[1]] = map(float, np.quantile(valid, [.025, .975]))
    return result


def stage_frames(rows: pd.DataFrame):
    dates = pd.to_datetime(rows.date)
    yield "all", rows
    yield "2020_2023", rows.loc[dates.between("2020-01-01", "2023-12-31")]
    yield "2024_2025", rows.loc[dates.between("2024-01-01", "2025-12-31")]
    for year in sorted(dates.dt.year.unique()):
        yield str(year), rows.loc[dates.dt.year.eq(year)]


def analyze(rows: pd.DataFrame, *, horizons=HORIZONS, bootstrap_repeats=BOOTSTRAP_REPEATS):
    summaries, effects, phases = [], [], []
    for stage, sample in stage_frames(rows):
        if sample.empty:
            continue
        for horizon in horizons:
            for target, prefix in TARGETS.items():
                column = f"{prefix}_{horizon}d"
                baseline = sample[column].mean()
                for group in range(1, 11):
                    selected = sample.loc[sample.percentile_bin.eq(group), column]
                    values = selected.dropna()
                    summaries.append({"stage": stage, "target": target, "horizon": horizon,
                                      "percentile_bin": group, "observations": len(selected),
                                      "labeled": len(values), "missing_labels": len(selected) - len(values),
                                      "mean_pct": values.mean() * 100, "median_pct": values.median() * 100,
                                      "positive_rate_pct": (values > 0).mean() * 100 if len(values) else np.nan,
                                      "p10_pct": values.quantile(.1) * 100, "p90_pct": values.quantile(.9) * 100,
                                      "baseline_mean_pct": baseline * 100,
                                      "mean_minus_baseline_pct": (values.mean() - baseline) * 100})
                ic, spread = effect_values(sample, column)
                intervals = dict.fromkeys(("ic_ci_low", "ic_ci_high", "spread_ci_low_pct", "spread_ci_high_pct"), np.nan)
                # Annual panels are descriptive; uncertainty is pooled or period-level.
                if stage in {"all", "2020_2023", "2024_2025"}:
                    intervals = bootstrap_effects(sample, column, repeats=bootstrap_repeats)
                phase_values = []
                for phase in range(horizon):
                    phase_sample = sample.loc[(sample.session_index % horizon).eq(phase)]
                    phase_ic, phase_spread = effect_values(phase_sample, column)
                    count = int(phase_sample[column].notna().sum())
                    phases.append({"stage": stage, "target": target, "horizon": horizon, "phase": phase,
                                   "labeled": count, "spearman_ic": phase_ic, "high_minus_low_pct": phase_spread})
                    phase_values.append((phase_ic, phase_spread))
                phase_array = np.asarray(phase_values)
                def bounds(index):
                    valid = phase_array[:, index][np.isfinite(phase_array[:, index])]
                    return (float(valid.min()), float(valid.max())) if len(valid) else (np.nan, np.nan)
                ic_min, ic_max = bounds(0)
                spread_min, spread_max = bounds(1)
                effects.append({"stage": stage, "target": target, "horizon": horizon,
                                "observations": len(sample), "labeled": int(sample[column].notna().sum()),
                                "baseline_mean_pct": baseline * 100, "spearman_ic": ic,
                                "high_minus_low_pct": spread, **intervals,
                                "nonoverlap_ic_min": ic_min, "nonoverlap_ic_max": ic_max,
                                "nonoverlap_spread_min_pct": spread_min, "nonoverlap_spread_max_pct": spread_max})
    return pd.DataFrame(summaries), pd.DataFrame(effects), pd.DataFrame(phases)
