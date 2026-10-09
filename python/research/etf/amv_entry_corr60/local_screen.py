"""Local raw-price screening; name groups are proxies, not official index IDs."""
import unicodedata
import numpy as np
import pandas as pd
from .data import forward_labels, aggregate_daily, sha256
from python.factors.amv_correlation import rolling_amv_correlation

ISSUERS = '华泰柏瑞 申万菱信 方正富邦 国投瑞银 西部利得 前海开源 民生加银 中银证券 汇添富 国联安 海富通 华安 易方达 华夏 富国 广发 国泰 南方 嘉实 博时 招商 鹏华 工银 华宝 银华 平安 天弘 万家 大成 建信 景顺 永赢 东财 摩根 浦银 泰康 兴业 融通 鹏扬 国寿 中银 国联 兴银 中金 交银 新华 汇安 银河 长城 弘毅远方 南华'.split()

def name_group(name):
    value=''.join(unicodedata.normalize('NFKC',str(name)).split())
    for issuer in sorted(ISSUERS,key=len,reverse=True):
        if value.startswith(issuer): value=value[len(issuer):]
        if value.endswith(issuer): value=value[:-len(issuer)]
    value=value.replace('ETF','')
    value={'300':'沪深300','500':'中证500','1000':'中证1000','科创板50':'科创50'}.get(value,value)
    return 'name:'+value

def screen_prices(daily,jump_threshold=.25):
    if not 0<jump_threshold<1: raise ValueError('jump_threshold must be between 0 and 1')
    clean=daily.sort_values('date').copy()
    quoted=clean.close.where(clean.valid & clean.close.gt(0))
    change=quoted/quoted.ffill().shift(1)-1
    overnight=clean.open.where(clean.valid)/quoted.ffill().shift(1)-1
    suspicious=change.abs().gt(jump_threshold) | overnight.abs().gt(jump_threshold)
    jumps=clean.loc[suspicious,['date']].copy()
    jumps['close_return']=change.loc[suspicious]
    jumps['overnight_return']=overnight.loc[suspicious]
    clean.loc[suspicious,'valid']=False
    clean.loc[~clean.valid,['open','close','high','low']]=np.nan
    return clean,jumps

def clean_forward_labels(clean,jumps,events,calendar,horizons=(5,10,20)):
    labels=forward_labels(clean,events,calendar,horizons)
    for row in labels.itertuples():
        position=calendar.get_indexer([row.date])[0]
        for h in horizons:
            if position>=0 and position+h<len(calendar):
                if jumps.date.between(calendar[position+1],calendar[position+h]).any():
                    labels.loc[labels.date.eq(row.date),f'return_{h}']=np.nan
                    labels.loc[labels.date.eq(row.date),f'missing_reason_{h}']='suspected_price_break_in_window'
    return labels

def build_local_observations(events,amv,etf_dir,jump_threshold=.25):
    calendar=pd.DatetimeIndex(amv.index)
    first=calendar.get_indexer([events.date.min()])[0]
    if first<0: raise ValueError('开仓日不在AMV日历')
    calendar=calendar[max(0,first-60):]
    amv=amv.reindex(calendar)
    rows,audit,all_jumps=[],[],[]
    for number,path in enumerate(sorted(etf_dir.glob('*.csv')),1):
        code=path.stem
        record=dict(code=code,raw_path=str(path.resolve()),raw_bytes=path.stat().st_size,status='excluded',reason='')
        try:
            raw=pd.read_csv(path,dtype={'代码':str})
            if '代码' in raw and not raw['代码'].eq(code).all(): raise ValueError('行情代码不一致')
            daily,qa=aggregate_daily(raw)
            record.update(qa,raw_sha256=sha256(path))
            valid=daily.loc[daily.valid]
            if valid.empty: raise ValueError('无有效日线')
            first_quote=valid.date.min()
            clean,jumps=screen_prices(daily,jump_threshold)
            jumps['code']=code
            all_jumps.append(jumps)
            factor=rolling_amv_correlation(clean.set_index('date').close,amv)
            labels=clean_forward_labels(clean,jumps,events.date,calendar)
            labels['factor']=labels.date.map(factor)
            labels['code']=code
            if '名称' in raw:
                names=pd.Series(raw['名称'].values,index=pd.to_datetime(raw['时间']).dt.normalize())
                names=names.groupby(level=0).last().sort_index()
                labels['name']=labels.date.map(names.reindex(names.index.union(pd.DatetimeIndex(events.date))).ffill())
            else: labels['name']=code
            labels['index_id']=labels.name.fillna(code).map(name_group)
            labels['first_quote_date']=first_quote
            rows.append(labels)
            record.update(status='loaded',first_quote_date=str(first_quote.date()),suspected_breaks=len(jumps),valid_factor_events=int(labels.factor.notna().sum()))
        except (ValueError,KeyError,OSError,IndexError) as error: record['reason']=f'{type(error).__name__}: {error}'
        audit.append(record)
        if number%100==0: print(f'Local clean-price audit {number}',flush=True)
    return pd.concat(rows,ignore_index=True),pd.DataFrame(audit),calendar,pd.concat(all_jumps,ignore_index=True)
