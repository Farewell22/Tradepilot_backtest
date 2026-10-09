"""Audited daily prices, exact calendar labels and point-in-time index dedup."""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
ETF_DIR = ROOT / 'data/backtest_data/ETF_60min_2005_2025'
CACHE = ROOT / 'data/factor_research_data/amv_entry_corr60'
HISTORY_START = '20190118'
HISTORY_END = '20251231'
SLOTS = {'10:30', '11:30', '14:00', '15:00'}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def aggregate_daily(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    aliases = {'时间':'timestamp', '日期':'timestamp', 'date':'timestamp', '开盘价':'open',
               '收盘价':'close', '最高价':'high', '最低价':'low', '成交量':'volume', '成交额':'amount'}
    frame = raw.rename(columns=aliases).copy()
    fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'amount']
    if not set(fields).issubset(frame):
        raise ValueError(f'行情缺少列: {set(fields) - set(frame)}')
    frame = frame[fields]
    frame['timestamp'] = pd.to_datetime(frame.timestamp, errors='raise')
    if frame.timestamp.isna().any():
        raise ValueError('行情日期为空')
    for field in fields[1:]:
        frame[field] = pd.to_numeric(frame[field], errors='raise')
    duplicates = int(frame.duplicated().sum())
    frame = frame.drop_duplicates().sort_values('timestamp')
    frame['date'] = frame.timestamp.dt.normalize()
    frame['conflict'] = frame.timestamp.duplicated(keep=False)
    quotes = frame[['open','high','low','close']]
    frame['price_ok'] = (np.isfinite(frame[fields[1:]]).all(axis=1) & quotes.gt(0).all(axis=1)
                         & frame.volume.ge(0) & frame.amount.ge(0)
                         & frame.high.ge(quotes.max(axis=1)) & frame.low.le(quotes.min(axis=1)))
    frame['slot'] = frame.timestamp.dt.strftime('%H:%M')
    grouped = frame.groupby('date', sort=True)
    daily = grouped.agg(open=('open','first'), close=('close','last'), high=('high','max'),
                        low=('low','min'), volume=('volume','sum'), amount=('amount','sum'),
                        bars=('timestamp','size'), price_ok=('price_ok','all'), conflict=('conflict','any'))
    slots = grouped.slot.agg(set)
    daily['valid'] = daily.bars.eq(4) & slots.map(lambda value: value == SLOTS) & daily.price_ok & ~daily.conflict & daily.volume.gt(0)
    return daily.reset_index(), {'exact_duplicates':duplicates, 'conflicting_days':int(daily.conflict.sum()),
                                 'invalid_days':int((~daily.valid).sum()), 'total_days':len(daily)}


def adjusted_prices(daily: pd.DataFrame, factors: pd.DataFrame) -> pd.DataFrame:
    """Daily multiplicative factors only; no carry of unknown adjustment values."""
    factors = factors.copy()
    factors['date'] = pd.to_datetime(factors.date).dt.normalize()
    if factors.date.duplicated().any():
        raise ValueError('复权日期重复')
    result = daily.merge(factors[['date','adj_factor']], on='date', how='left', validate='one_to_one')
    result['adj_factor'] = pd.to_numeric(result.adj_factor, errors='coerce')
    good = np.isfinite(result.adj_factor) & result.adj_factor.gt(0)
    # A future missing factor must not remove an ETF from earlier cross-sections.
    result['missing_adjustment'] = result.valid & ~good
    result['valid'] = result.valid & good
    anchor = result.loc[result.valid, 'adj_factor'].iloc[-1] if result.valid.any() else 1.
    for field in ('open','close','high','low'):
        if field in result:
            result[field] = (result[field] * result.adj_factor / anchor).where(result.valid)
    return result


def forward_labels(prices: pd.DataFrame, events, calendar: pd.DatetimeIndex,
                   horizons=(5,10,20)) -> pd.DataFrame:
    calendar = pd.DatetimeIndex(calendar)
    indexed = prices.loc[prices.valid].set_index('date')
    if indexed.index.has_duplicates:
        raise ValueError('日线日期重复')
    aligned = indexed.reindex(calendar)
    records = []
    for date in pd.DatetimeIndex(events):
        position = calendar.get_indexer([date])[0]
        if position < 0:
            raise ValueError('事件不在市场交易日历中')
        entry = position + 1
        row = {'date':date, 'entry_date':calendar[entry] if entry < len(calendar) else pd.NaT,
               'entry_open':aligned.open.iloc[entry] if entry < len(calendar) else np.nan}
        for horizon in horizons:
            end = position + horizon
            row[f'exit_date_{horizon}'] = calendar[end] if end < len(calendar) else pd.NaT
            end_price = aligned.close.iloc[end] if end < len(calendar) else np.nan
            row[f'return_{horizon}'] = end_price / row['entry_open'] - 1
            row[f'missing_reason_{horizon}'] = ('immature_window' if end >= len(calendar)
                else 'missing_entry' if pd.isna(row['entry_open'])
                else 'missing_exit' if pd.isna(end_price) else '')
        records.append(row)
    return pd.DataFrame(records)


def select_representatives(rows: pd.DataFrame, date_column: str='list_date') -> tuple[pd.DataFrame, pd.DataFrame]:
    """Oldest eligible listed ETF, code breaks ties; labels never enter selection."""
    audit = rows.copy().reset_index(drop=True)
    eligible = audit.factor.notna() & audit[date_column].le(audit.date) & audit.index_id.notna()
    candidates = audit.loc[eligible].sort_values(['date','index_id',date_column,'code'], kind='stable')
    chosen = candidates.drop_duplicates(['date','index_id'], keep='first')
    audit['selected'] = audit.index.isin(chosen.index)
    audit['dedup_reason'] = np.where(audit.selected, 'selected',
        np.where(eligible, 'same_index_later_listing', 'ineligible_factor_or_metadata'))
    return chosen.reset_index(drop=True), audit.reset_index(drop=True)
