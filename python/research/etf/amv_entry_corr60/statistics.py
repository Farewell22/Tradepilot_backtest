"""Date-equal quintiles and rank IC, with overlapping-window cluster bootstrap."""
from __future__ import annotations

import numpy as np
import pandas as pd

HORIZONS = (5,10,20)


def overlap_clusters(dates, calendar: pd.DatetimeIndex, horizon: int) -> np.ndarray:
    positions = calendar.get_indexer(pd.DatetimeIndex(dates))
    if (positions < 0).any():
        raise ValueError('事件不在市场交易日历中')
    result = np.empty(len(positions), dtype=int)
    end, cluster = -1, -1
    for i in np.argsort(positions, kind='stable'):
        if positions[i] + 1 > end:
            cluster += 1
        end = max(end, positions[i] + horizon)
        result[i] = cluster
    return result


def event_statistics(observations: pd.DataFrame, horizons=HORIZONS) -> pd.DataFrame:
    records = []
    for date, original in observations.groupby('date', sort=True):
        frame = original.loc[original.factor.notna()].copy()
        frame['quintile'] = pd.Series(pd.NA, index=frame.index, dtype='Int64')
        if len(frame) >= 10 and frame.factor.nunique() >= 5:
            frame['quintile'] = np.ceil(frame.factor.rank(method='average', pct=True) * 5).astype('Int64')
        for horizon in horizons:
            label = f'return_{horizon}'
            valid = frame.dropna(subset=[label])
            baseline = valid[label].mean()
            groups = {'universe':valid, **{f'Q{q}':valid.loc[valid.quintile.eq(q)] for q in range(1,6)}}
            metrics = {}
            for name, subset in groups.items():
                values = subset[label]
                metrics[name] = values.mean()
                records.append({'date':date, 'horizon':horizon, 'group':name, 'observations':len(values),
                    'eligible_observations':len(frame) if name=='universe' else int(frame.quintile.eq(int(name[1:])).sum()),
                    'mean_return':values.mean(), 'median_return':values.median(),
                    'positive_rate':values.gt(0).mean() if len(values) else np.nan,
                    'mean_excess':values.mean()-baseline})
            records.append({'date':date, 'horizon':horizon, 'group':'Q5-Q1',
                'observations':min(len(groups['Q1']),len(groups['Q5'])),
                'mean_return':metrics['Q5']-metrics['Q1'], 'mean_excess':metrics['Q5']-metrics['Q1']})
            ic = (valid.factor.rank().corr(valid[label].rank())
                  if len(valid)>=10 and valid.factor.nunique()>1 and valid[label].nunique()>1 else np.nan)
            records.append({'date':date, 'horizon':horizon, 'group':'IC', 'observations':len(valid), 'mean_return':ic})
    return pd.DataFrame(records)


def summarize(events: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    stages = {'all':pd.Series(True,index=events.index),
              '2019_2023':events.date.lt('2024-01-01'), '2024_2025':events.date.ge('2024-01-01')}
    stages.update({str(year):events.date.dt.year.eq(year) for year in sorted(events.date.dt.year.unique())})
    records = []
    for stage, mask in stages.items():
        for (horizon, group), full in events.loc[mask].groupby(['horizon','group']):
            frame = full.dropna(subset=['mean_return'])
            row = {'stage':stage, 'horizon':int(horizon), 'group':group, 'event_count':len(frame),
                   'missing_events':len(full)-len(frame), 'etf_observations':int(frame.observations.sum()),
                   'mean_return':frame.mean_return.mean(), 'ci_low':np.nan, 'ci_high':np.nan, 'clusters':0}
            for field in ('median_return','positive_rate','mean_excess'):
                row[field] = frame[field].mean()
            if len(frame):
                clusters = overlap_clusters(frame.date, calendar, int(horizon))
                row['clusters'] = int(clusters.max()+1)
                if group in ('IC','Q5-Q1') and row['clusters'] >= 10:
                    clustered = frame.assign(cluster=clusters).groupby('cluster').mean_return.agg(['sum','count'])
                    rng = np.random.default_rng(42)
                    draws = rng.integers(0, len(clustered), size=(2000,len(clustered)))
                    means = clustered['sum'].to_numpy()[draws].sum(axis=1)/clustered['count'].to_numpy()[draws].sum(axis=1)
                    row['ci_low'],row['ci_high'] = np.quantile(means,[.025,.975])
            records.append(row)
    return pd.DataFrame(records)
