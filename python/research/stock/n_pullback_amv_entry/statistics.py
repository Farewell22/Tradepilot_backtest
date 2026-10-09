"""Date-equal cross-sectional statistics and overlap-cluster uncertainty."""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5, 10, 20)


def quintiles(values: pd.Series) -> pd.Series:
    result = pd.Series(pd.NA, index=values.index, dtype="Int64")
    valid = values.dropna()
    if len(valid) >= 50 and valid.nunique() >= 5:
        result.loc[valid.index] = np.ceil(valid.rank(method="average", pct=True) * 5).astype(int)
    return result


def overlap_clusters(dates, calendar: pd.DatetimeIndex, horizon: int) -> np.ndarray:
    positions = calendar.get_indexer(pd.DatetimeIndex(dates))
    if (positions < 0).any():
        raise ValueError("事件日期不在市场日历内")
    output = np.empty(len(positions), dtype=int)
    end, cluster = -1, -1
    for index in np.argsort(positions, kind="stable"):
        if positions[index] + 1 > end:
            cluster += 1
        end = max(end, positions[index] + horizon)
        output[index] = cluster
    return output


def event_statistics(observations: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    rows = []
    for (threshold, date), full in observations.groupby(["threshold", "date"], sort=True):
        full = full.loc[full.status != "insufficient_history"].copy()
        structure = full.status.eq("valid")
        full["quintile"] = quintiles(full.factor.where(structure))
        groups = {"universe": pd.Series(True, index=full.index), "all_n": structure,
                  "intact": structure & full.factor.ge(0), "broken": structure & full.factor.lt(0),
                  "non_n": ~structure}
        groups.update({f"Q{i}": full.quintile.eq(i).fillna(False) for i in range(1, 6)})
        for h in horizons:
            column = f"return_{h}"
            benchmark = full[column].mean()
            for name, mask in groups.items():
                group = full.loc[mask]
                labeled = group.dropna(subset=[column])
                returns = labeled[column]
                rows.append({"date": date, "threshold": threshold, "horizon": h, "group": name,
                             "n_input": len(group), "n_labeled": len(labeled),
                             "mean_return": returns.mean(), "mean_excess": returns.mean() - benchmark,
                             "win_rate": returns.gt(0).mean() if len(returns) else np.nan,
                             "median_return": returns.median(), "p10": returns.quantile(.1),
                             "mean_mae": labeled[f"mae_{h}"].mean()})
            valid = full.loc[structure].dropna(subset=[column, "factor"])
            ic = (valid.factor.rank().corr(valid[column].rank())
                  if len(valid) >= 30 and valid.factor.nunique() > 1 and valid[column].nunique() > 1 else np.nan)
            rows.append({"date": date, "threshold": threshold, "horizon": h, "group": "IC",
                         "n_input": int(structure.sum()), "n_labeled": len(valid),
                         "mean_return": ic, "mean_excess": np.nan, "win_rate": np.nan,
                         "median_return": np.nan, "p10": np.nan, "mean_mae": np.nan})
    result = pd.DataFrame(rows)
    contrasts = []
    for (threshold, h), sample in result.groupby(["threshold", "horizon"]):
        for name, high, low in (("Q5-Q1", "Q5", "Q1"), ("intact-broken", "intact", "broken")):
            left = sample.loc[sample.group.eq(high)].set_index("date")
            right = sample.loc[sample.group.eq(low)].set_index("date")
            paired = left.join(right, lsuffix="_a", rsuffix="_b", how="inner")
            for date, pair in paired.iterrows():
                contrasts.append({"date": date, "threshold": threshold, "horizon": h, "group": name,
                                  "n_input": pair.n_input_a + pair.n_input_b,
                                  "n_labeled": pair.n_labeled_a + pair.n_labeled_b,
                                  "mean_return": pair.mean_return_a - pair.mean_return_b,
                                  "mean_excess": pair.mean_excess_a - pair.mean_excess_b,
                                  "win_rate": np.nan, "median_return": np.nan, "p10": np.nan, "mean_mae": np.nan})
    return pd.concat([result, pd.DataFrame(contrasts)], ignore_index=True)


def cluster_interval(values: pd.Series, calendar, horizon, repeats=2000, seed=42):
    values = values.dropna().sort_index()
    clusters = overlap_clusters(values.index, calendar, horizon)
    count = len(np.unique(clusters))
    if count < 10 or not repeats:
        return np.nan, np.nan, count
    sums = np.bincount(clusters, weights=values.to_numpy())
    sizes = np.bincount(clusters)
    draws = np.random.default_rng(seed).integers(0, count, size=(repeats, count))
    samples = sums[draws].sum(axis=1) / sizes[draws].sum(axis=1)
    lower, upper = np.quantile(samples, [.025, .975])
    return float(lower), float(upper), count


def summarize(event_rows: pd.DataFrame, calendar, repeats=2000) -> pd.DataFrame:
    stages = {"all": event_rows, "2020_2023": event_rows[event_rows.date.dt.year <= 2023],
              "2024_2025": event_rows[event_rows.date.dt.year >= 2024]}
    stages.update({str(year): sample for year, sample in event_rows.groupby(event_rows.date.dt.year)})
    rows = []
    for stage, sample in stages.items():
        for (threshold, h, group), values in sample.groupby(["threshold", "horizon", "group"], sort=True):
            valid = values.dropna(subset=["mean_return"])
            lo, hi, clusters = cluster_interval(valid.set_index("date").mean_return,
                                                calendar, h, repeats if stage in {"all", "2020_2023", "2024_2025"} else 0)
            rows.append({"stage": stage, "threshold": threshold, "horizon": h, "group": group,
                         "event_count": len(valid), "stock_observations": int(valid.n_labeled.sum()),
                         "input_observations": int(values.n_input.sum()),
                         "missing_labels": int((values.n_input - values.n_labeled).sum()),
                         **{col: valid[col].mean() for col in ("mean_return", "mean_excess", "win_rate",
                                                              "median_return", "p10", "mean_mae")},
                         "ci_low": lo, "ci_high": hi, "clusters": clusters})
    return pd.DataFrame(rows)
