"""Actual AMV strategy entry dates × historical ETF corr60 cross-sections."""
from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd
import yaml

from python.factors.amv_correlation import rolling_amv_correlation
from .data import (CACHE, ETF_DIR, ROOT, HISTORY_START, HISTORY_END, aggregate_daily,
                   adjusted_prices, forward_labels, select_representatives, sha256)
from .prepare import validate_metadata, validate_adjustments
from .statistics import HORIZONS, event_statistics, summarize

AMV_PATH = ROOT/'data/backtest_data/0AMV-260612.csv'


def source_events(output_dir: Path) -> pd.DataFrame:
    """Replay the exact strategy on all available history, without publishing it."""
    from python.strategies.amv_winning_defensive.runner import run_research as run_source
    config_path = ROOT/'python/strategies/amv_winning_defensive/config.yaml'
    settings = yaml.safe_load(config_path.read_text())['paths']
    paths = {key:ROOT/value for key,value in settings.items()}
    destination = output_dir/'source_strategy'
    run_source(paths['amv_csv'],paths['primary_csv'],paths['defensive_etf_csv'],
               paths['stock_5m_dir'],destination,start_date=HISTORY_START,end_date=HISTORY_END,
               stock_dividends_path=paths['stock_dividends_csv'])
    frames = []
    for version in ('512890.SH','601288.SH'):
        trades = pd.read_csv(destination/f'trades_{version}.csv',dtype={'date':str,'code':str})
        entries = trades.loc[trades.side.eq('buy') & trades.code.eq('512100.SH'),['date']].copy()
        entries['date'] = pd.to_datetime(entries.date,format='%Y%m%d')
        entries['version'] = version
        frames.append(entries)
    full = pd.concat(frames,ignore_index=True).drop_duplicates(['date','version'])
    events = full.groupby('date',as_index=False).agg(versions=('version',lambda values:','.join(sorted(values))))
    events['version_difference'] = events.versions.str.count(',').eq(0)
    if events.empty:
        raise ValueError('原策略没有进攻仓实际开仓记录')
    (destination/'config.yaml').write_text(config_path.read_text())
    source_manifest = {'task_id':'amv_winning_defensive','status':'complete','start_date':HISTORY_START,'end_date':HISTORY_END,
        'execution':'same_close; original default fees, cash, shared sessions and stops',
        'event_rule':'union of actual 512100.SH buys in both defense variants; unique dates',
        'event_count':len(events), 'variant_difference_dates':events.loc[events.version_difference,'date'].astype(str).tolist(),
        'config_sha256':sha256(config_path),
        'input_paths':{key:str(path) for key,path in paths.items()},
        'small_input_sha256':{key:sha256(path) for key,path in paths.items() if path.is_file()},
        'trade_sha256':{path.name:sha256(path) for path in destination.glob('trades_*.csv')},
        'code_snapshot':'code_snapshot/manifest.json'}
    (destination/'source_manifest.json').write_text(json.dumps(source_manifest,ensure_ascii=False,indent=2)+'\n')
    return events.sort_values('date').reset_index(drop=True)


def build_observations(events: pd.DataFrame, amv: pd.Series, etf_dir: Path, cache: Path):
    metadata_path = cache/'metadata.csv'
    metadata = validate_metadata(pd.read_csv(metadata_path,dtype={'code':str,'index_id':str}))
    calendar = pd.DatetimeIndex(amv.index)
    first_position = calendar.get_indexer([events.date.min()])[0]
    if first_position < 0:
        raise ValueError('原策略开仓日不在0AMV日历中')
    calendar = calendar[max(0,first_position-60):]
    amv = amv.reindex(calendar)
    rows, audit = [], []
    meta_codes = set(metadata.code)
    for number,path in enumerate(sorted(etf_dir.glob('*.csv')),1):
        code = path.stem
        factor_path = cache/'adjustments'/f'{code}.parquet'
        record = {'code':code,'raw_path':str(path.resolve()),'raw_bytes':path.stat().st_size,
                  'status':'excluded','reason':''}
        reasons = []
        if code not in meta_codes:
            reasons.append('missing_historical_index_mapping_or_listing_date')
        if not factor_path.is_file():
            reasons.append('missing_adjustment_factors')
        if reasons:
            record['reason'] = ';'.join(reasons)
            audit.append(record)
            continue
        try:
            raw = pd.read_csv(path,dtype={'代码':str})
            if '代码' in raw and not raw['代码'].eq(code).all():
                raise ValueError('文件名与行情代码不一致')
            daily, quote_audit = aggregate_daily(raw)
            record.update(quote_audit,raw_sha256=sha256(path),adjustment_sha256=sha256(factor_path))
            daily = daily.loc[daily.date.between(calendar.min(),calendar.max())].copy()
            if not daily.valid.any():
                raise ValueError('研究区间没有有效日线')
            factors = validate_adjustments(pd.read_parquet(factor_path))
            if not factors.code.eq(code).all():
                raise ValueError('复权代码不一致')
            daily = adjusted_prices(daily,factors)
            record['missing_adjustment_days'] = int(daily.missing_adjustment.sum())
            close = daily.set_index('date').close
            factor = rolling_amv_correlation(close,amv)
            labels = forward_labels(daily,events.date,calendar,HORIZONS)
            labels['factor'] = labels.date.map(factor)
            labels['code'] = code
            labels['name'] = (str(raw['名称'].dropna().iloc[0])
                              if '名称' in raw and raw['名称'].notna().any() else code)
            labels['index_id'] = pd.Series(pd.NA,index=labels.index,dtype='string')
            labels['list_date'] = pd.NaT
            labels['metadata_source'] = ''
            for interval in metadata.loc[metadata.code.eq(code)].itertuples():
                mask = labels.date.ge(interval.valid_from)
                if pd.notna(interval.valid_to):
                    mask &= labels.date.le(interval.valid_to)
                labels.loc[mask,'index_id'] = interval.index_id
                labels.loc[mask,'list_date'] = interval.list_date
                labels.loc[mask,'metadata_source'] = interval.source_url
            rows.append(labels)
            record.update(status='loaded',reason='',valid_factor_events=int(labels.factor.notna().sum()),
                          mapped_events=int(labels.index_id.notna().sum()))
        except (ValueError,OSError,KeyError,IndexError) as error:
            record['reason'] = f'{type(error).__name__}: {error}'
        audit.append(record)
        if number%100==0:
            print(f'ETF local-data audit {number}',flush=True)
    columns = ['date','code','name','index_id','list_date','factor']
    observations = pd.concat(rows,ignore_index=True) if rows else pd.DataFrame(columns=columns)
    return observations,pd.DataFrame(audit),calendar


def coverage_table(events, candidates, selected, audit, date_column='list_date'):
    rows = []
    for date in events.date:
        full = candidates.loc[candidates.date.eq(date)]
        chosen = selected.loc[selected.date.eq(date)]
        row = {'date':date,'local_etf_files':len(audit),'loaded_etfs':int(audit.status.eq('loaded').sum()),
               'metadata_eligible_etfs':int((full.index_id.notna() & full[date_column].le(date)).sum()),
               'factor_valid_etfs':int(full.factor.notna().sum()),
               'eligible_before_dedup':int((full.factor.notna() & full.index_id.notna() & full[date_column].le(date)).sum()),
               'unique_indices':len(chosen)}
        for horizon in HORIZONS:
            row[f'labeled_{horizon}'] = int(chosen.get(f'return_{horizon}',pd.Series(dtype=float)).notna().sum())
            row[f'missing_labels_{horizon}'] = len(chosen)-row[f'labeled_{horizon}']
        rows.append(row)
    return pd.DataFrame(rows)


def _snapshot(output_dir: Path, cache: Path, audit: pd.DataFrame):
    snapshot = output_dir/'inputs'
    snapshot.mkdir(exist_ok=True)
    inputs = {}
    for name in ('metadata.csv','preparation_manifest.json','preparation_coverage.csv'):
        path = cache/name
        if path.is_file():
            shutil.copy2(path,snapshot/name)
            inputs[str(path.resolve())] = sha256(path)
    for code in audit.loc[audit.status.eq('loaded'),'code']:
        path = cache/'adjustments'/f'{code}.parquet'
        if not path.is_file():
            continue
        target = snapshot/'adjustments'/path.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path,target)
        inputs[str(path.resolve())] = sha256(path)
    code_hashes = {}
    sources = [Path(__file__).with_name(name) for name in ('study.py','data.py','statistics.py','prepare.py','local_screen.py')]
    sources += [ROOT/'python/factors/amv_correlation.py',ROOT/'python/task_registry.py',ROOT/'python/run_backtest.py']
    for path in sources:
        target = output_dir/'code_snapshot'/path.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)
        code_hashes[str(path.relative_to(ROOT))] = sha256(path)
    manifest = {'references':inputs,'code_sha256':code_hashes,
                'quotes':audit.astype(object).where(pd.notna(audit),None).to_dict('records')}
    (output_dir/'input_audit.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,default=str)+'\n')


def write_report(output_dir, events, coverage, summary, audit, price_mode='verified', jump_threshold=.25):
    table = summary.loc[summary.stage.eq('all')].copy()
    for field in ('mean_return','median_return','positive_rate','mean_excess','ci_low','ci_high'):
        table[field] = table[field]*np.where(table.group.eq('IC'),1.,100.)
    selected_columns = ['horizon','group','event_count','etf_observations','mean_return','mean_excess','positive_rate','clusters','ci_low','ci_high']
    yearly = summary.loc[~summary.stage.eq('all') & summary.group.isin(['IC','Q5-Q1']),
                         ['stage','horizon','group','event_count','mean_return','clusters']].copy()
    yearly['mean_return'] *= np.where(yearly.group.eq('IC'),1.,100.)
    reasons = audit.loc[audit.status.eq('excluded')].groupby('reason').size().rename('ETFs').reset_index()
    lines = ['# 0AMV 60日相关性：进攻仓开仓日ETF截面研究','',
        f'观察区间：{events.date.min().date()}—{events.date.max().date()}；实际开仓日去重后共 {len(events)} 个。',
        f'本地目录共 {len(audit)} 只ETF；资料与行情校验后加载 {int(audit.status.eq("loaded").sum())} 只。',
        f'逐日去重后指数数量范围：{coverage.unique_indices.min()}—{coverage.unique_indices.max()}。','',
        '## 定义与时间对齐','',
        '- F=corr(ETF日收益率,0AMV日变化率)，截至开仓日收盘取60个市场交易日，要求完整60对收益、61个连续日历收盘。',
        '- 收益为下一市场交易日开盘至第5/10/20个后续市场交易日收盘的前复权价格收益；缺失端点不顺延，未成熟标签不填零。',
        '- 前复权使用逐日乘数，现金分红不重复相加；价格收益不计交易费用。',
        '- 原策略从2019-01-18开始重跑，两个防守版本进攻仓实际开仓日取并集去重。原策略同日收盘成交仅决定观察日期。',
        '- 每个日期同指数选择已上市且因子有效的最早上市ETF，同日上市按代码排序；选择不参考未来标签。',
        '- 指数映射按已核验有效区间匹配。缺失参考资料、行情和因子均有覆盖审计。','',
        '## 全区间统计','',
        '收益和区间均以百分数显示，IC行为相关系数；上涨比例是ETF上涨比例的日期平均，不是策略交易胜率。',
        table[selected_columns].round(4).to_markdown(index=False),'',
        '## 年度与分阶段稳定性','',yearly.round(4).to_markdown(index=False),'',
        '## 覆盖与限制','',reasons.to_markdown(index=False),'',
        '- 每日先分组，再过滤未来标签；每个日期先统计，再日期等权汇总。每个窗口的等权基准是同截面代表中标签有效的ETF。',
        '- 至少10只有效代表、5个不同因子值才划五组；同分按平均秩，不强行拆分。IC要求至少10对有效值且双方有变化。',
        '- Q5-Q1与IC的95%区间按远期窗口重叠关系连接为时间簇，簇bootstrap 2000次、种子42，少于10簇不报区间。',
        '- 日期去重不意味着远期窗口独立；ETF观察数量不等于独立时间样本。',
        '- 2019—2023与2024—2025是描述性时期比较，不宣称严格未知样本外；不按结果挑选最佳窗口。',
        '- 本地文件目录可能遗漏已经退市基金；参考资料缺失带来选择偏差，不能把覆盖子集解释为全市场ETF。',
        '- 相关性衡量同步程度，不能直接解释为0AMV领先ETF或因果关系。','',
        '逐日数量见coverage.csv；逐只排除原因见etf_audit.csv；代表选择见dedup_audit.parquet；来源与代码哈希见input_audit.json。','']
    report='\n'.join(lines)
    if price_mode=='local_screen':
        report=report.replace('前复权价格收益','未复权清洁价格收益').replace('前复权使用逐日乘数，现金分红不重复相加；价格收益不计交易费用。','原始价格不含现金分红收益；未取得完整复权资料，价格收益不计费用。').replace('每个日期同指数选择已上市且因子有效的最早上市ETF，同日上市按代码排序；选择不参考未来标签。','按名称保守归一化分组，每日选择因子有效且最早出现有效行情的ETF，同日按代码排序；名称和首条行情仅为指数与上市日的代理。').replace('指数映射按已核验有效区间匹配。缺失参考资料、行情和因子均有覆盖审计。',f'相邻有效行情收盘或隔夜开盘跳变超过{jump_threshold:.0%}标为疑似价格断点；断点污染的因子和远期收益窗口设为缺失，不因未来异常删掉历史样本。名称代理可能误合并或漏合并；断点也可能是真实行情，无法等同于已确认份额合并。')
    (output_dir/'report.md').write_text(report)


def run_research(output_dir: Path, *, start_date: str=HISTORY_START,end_date: str=HISTORY_END,
                 etf_dir: Path=ETF_DIR,cache: Path=CACHE,amv_path: Path=AMV_PATH, price_mode: str='verified', jump_threshold: float=.25) -> Path:
    output_dir.mkdir(parents=True,exist_ok=True)
    events = source_events(output_dir)
    events = events.loc[events.date.between(pd.Timestamp(start_date),pd.Timestamp(end_date))].copy()
    if events.empty:
        raise ValueError('请求区间没有原策略实际进攻仓开仓日')
    events.to_csv(output_dir/'events.csv',index=False)
    raw_amv = pd.read_csv(amv_path)
    raw_amv['date'] = pd.to_datetime(raw_amv.date)
    if raw_amv.date.duplicated().any():
        raise ValueError('0AMV日期重复')
    amv = raw_amv.loc[raw_amv.date.le(pd.Timestamp(HISTORY_END))].sort_values('date').set_index('date').close
    if price_mode=='local_screen':
        from .local_screen import build_local_observations
        candidates,audit,calendar,jumps=build_local_observations(events,amv,etf_dir,jump_threshold)
        jumps.to_csv(output_dir/'suspected_price_breaks.csv',index=False)
        date_column='first_quote_date'
    elif price_mode=='verified':
        candidates,audit,calendar = build_observations(events,amv,etf_dir,cache)
        date_column='list_date'
    else: raise ValueError('unknown price_mode')
    selected,dedup = select_representatives(candidates,date_column=date_column)
    audit.to_csv(output_dir/'etf_audit.csv',index=False)
    dedup.to_parquet(output_dir/'dedup_audit.parquet',index=False)
    coverage = coverage_table(events,candidates,selected,audit,date_column)
    coverage.to_csv(output_dir/'coverage.csv',index=False)
    _snapshot(output_dir,cache,audit)
    selected.to_parquet(output_dir/'observations.parquet',index=False)
    if selected.empty:
        (output_dir/'data_status.md').write_text('# 数据覆盖审计\n\n当前没有同时具备历史指数映射、上市日期、完整复权和60日因子的ETF截面。\n'
            '未生成正式因子收益结论；本地行情未重新下载。查看etf_audit.csv、coverage.csv及inputs/preparation_manifest.json。\n')
        raise ValueError('没有合格ETF截面；数据审计已保存，不以未复权或猜测指数降级')
    # Freeze groups before any future-label filtering, and expose them in observations.
    selected['quintile'] = selected.groupby('date').factor.transform(
        lambda values: np.ceil(values.rank(method='average',pct=True)*5)
        if len(values)>=10 and values.nunique()>=5 else np.nan)
    for horizon in HORIZONS:
        selected[f'baseline_{horizon}'] = selected.groupby('date')[f'return_{horizon}'].transform('mean')
        selected[f'excess_{horizon}'] = selected[f'return_{horizon}']-selected[f'baseline_{horizon}']
    selected.to_parquet(output_dir/'observations.parquet',index=False)
    per_event = event_statistics(selected)
    per_event.to_csv(output_dir/'event_statistics.csv',index=False)
    summary = summarize(per_event,calendar)
    summary.to_csv(output_dir/'summary.csv',index=False)
    if not summary.group.eq('IC').any() or summary.loc[summary.group.eq('IC'),'event_count'].max()==0:
        raise ValueError('代表数量或标签不足以计算截面IC；观察表及统计已保存，不能发布正式因子结论')
    _meta = {'price_mode':price_mode,'jump_threshold':jump_threshold,'factor':'corr60 daily ETF return vs AMV change','horizons':list(HORIZONS),
        'entry':'next market session open','exit':'close on Hth market session after event','gross_returns':True,
        'event_count':len(events),'source_replay_start':HISTORY_START,'source_replay_end':HISTORY_END,
        'requested_start':start_date,'requested_end':end_date,'amv_sha256':sha256(amv_path),
        'dedup':('name proxy; earliest valid quote then code' if price_mode=='local_screen' else 'oldest listed eligible ETF by historical index, then code'),'weighting':'date equal',
        'bootstrap_repeats':2000,'bootstrap_seed':42,'minimum_bootstrap_clusters':10}
    (output_dir/'research_metadata.json').write_text(json.dumps(_meta,ensure_ascii=False,indent=2)+'\n')
    write_report(output_dir,events,coverage,summary,audit,price_mode,jump_threshold)
    return output_dir
