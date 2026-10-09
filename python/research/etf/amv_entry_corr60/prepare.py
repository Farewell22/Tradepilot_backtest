"""Prepare reference data only: local 60-minute quotes are never downloaded.

Historical index intervals can be imported with --metadata. A current ETF
directory is retained as candidates, never silently backdated to inception.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd
import requests
import yaml

from .data import CACHE, ETF_DIR, ROOT, sha256

METADATA_FIELDS = ['code','name','index_id','list_date','valid_from','valid_to','source_url']
ALIASES = {'399300.SZ':'000300.SH', '000300.CSI':'000300.SH',
           '399905.SZ':'000905.SH', '000905.CSI':'000905.SH',
           '399906.SZ':'000906.SH', '000906.CSI':'000906.SH',
           '399852.SZ':'000852.SH', '000852.CSI':'000852.SH'}


def canonical_index(value: str) -> str:
    value = str(value).strip().upper()
    return ALIASES.get(value, value)


def validate_metadata(frame: pd.DataFrame) -> pd.DataFrame:
    """Require sourced historical intervals; disallow overlaps and guesswork."""
    missing = set(METADATA_FIELDS)-set(frame)
    if missing:
        raise ValueError(f'历史指数资料缺少列: {sorted(missing)}')
    result = frame[METADATA_FIELDS].copy()
    for field in ('code','index_id','source_url'):
        if result[field].isna().any() or result[field].astype(str).str.strip().eq('').any():
            raise ValueError(f'历史指数资料缺少 {field}')
    result['index_id'] = result.index_id.map(canonical_index)
    for field in ('list_date','valid_from','valid_to'):
        result[field] = pd.to_datetime(result[field].astype('string').replace('',pd.NA), format='mixed',errors='raise')
    if result[['list_date','valid_from']].isna().any().any():
        raise ValueError('上市日期和历史映射生效日期不能为空')
    if (result.valid_from < result.list_date).any() or (result.valid_to.notna() & (result.valid_to < result.valid_from)).any():
        raise ValueError('历史映射日期区间无效')
    for code, rows in result.groupby('code'):
        rows = rows.sort_values('valid_from')
        if rows.list_date.nunique()!=1:
            raise ValueError(f'{code}上市日期不一致')
        previous_end = None
        for i, row in enumerate(rows.itertuples()):
            if i and (pd.isna(previous_end) or row.valid_from <= previous_end):
                raise ValueError(f'{code}历史映射区间重叠')
            previous_end = row.valid_to
    return result.sort_values(['code','valid_from']).reset_index(drop=True)


def _api(api_name: str, params: dict, fields: str='') -> pd.DataFrame:
    """Use HTTPS, check errors/empty bodies, never persist credentials."""
    config = yaml.safe_load((ROOT/'python/config/fetch_kline.yaml').read_text())
    token = config.get('tushare',{}).get('token')
    if not token:
        raise ValueError('未配置Tushare凭据')
    last = ''
    for attempt in range(3):
        try:
            response = requests.post('https://api.tushare.pro',
                json={'api_name':api_name,'token':token,'params':params,'fields':fields}, timeout=12)
            response.raise_for_status()
            payload = response.json()
            if payload.get('code') != 0:
                raise ValueError(str(payload.get('msg','接口错误')))
            data = payload.get('data') or {}
            result = pd.DataFrame(data.get('items',[]), columns=data.get('fields',[]))
            if result.empty:
                raise ValueError(f'{api_name}返回空数据')
            return result
        except (requests.RequestException,ValueError) as error:
            last = str(error).replace(token,'[redacted]')
            if attempt < 2:
                time.sleep(.3*(attempt+1))
    raise ValueError(f'{api_name}无法获取有效数据: {last[:250]}')


def validate_adjustments(frame: pd.DataFrame) -> pd.DataFrame:
    required = {'code','date','adj_factor'}
    if not required.issubset(frame):
        raise ValueError(f'复权资料缺少列: {sorted(required-set(frame))}')
    result = frame[list(sorted(required))].copy()
    result['date'] = pd.to_datetime(result.date.astype('string'),format='mixed',errors='raise')
    result['adj_factor'] = pd.to_numeric(result.adj_factor, errors='raise')
    if (result.code.isna().any() or result.date.isna().any() or result.duplicated(['code','date']).any()
            or not np.isfinite(result.adj_factor).all() or result.adj_factor.le(0).any()):
        raise ValueError('复权资料包含重复、空值或非正乘数')
    return result.sort_values(['code','date']).reset_index(drop=True)


def _fetch_adjustments(code: str) -> pd.DataFrame:
    parts = []
    # One calendar year is below the documented 2000-row page limit.
    for year in range(2018,2026):
        try:
            frame = _api('fund_adj',{'ts_code':code,'start_date':f'{year}0101','end_date':f'{year}1231','limit':2000})
        except ValueError as error:
            if '返回空数据' in str(error):
                continue
            raise
        if len(frame)>=2000:
            raise ValueError(f'{code}复权响应可能被截断')
        parts.append(frame.rename(columns={'ts_code':'code','trade_date':'date'}))
    if not parts:
        raise ValueError(f'{code}复权数据为空')
    return validate_adjustments(pd.concat(parts,ignore_index=True))


def prepare_data(cache: Path=CACHE, etf_dir: Path=ETF_DIR, *,
                 metadata_path: Path|None=None, adjustments_path: Path|None=None,
                 workers: int=4) -> dict:
    cache.mkdir(parents=True,exist_ok=True)
    (cache/'adjustments').mkdir(exist_ok=True)
    files = sorted(etf_dir.glob('*.csv'))
    codes = {path.stem for path in files}
    failures = []
    previous = cache/'preparation_manifest.json'
    sources = json.loads(previous.read_text()).get('sources',[]) if previous.is_file() else []
    if metadata_path:
        metadata = validate_metadata(pd.read_csv(metadata_path, dtype={'code':str,'index_id':str}))
        sources.append({'kind':'historical_index_mapping','path':str(metadata_path.resolve()),'sha256':sha256(metadata_path)})
    elif (cache/'metadata.csv').is_file() and len(pd.read_csv(cache/'metadata.csv')):
        metadata = validate_metadata(pd.read_csv(cache/'metadata.csv',dtype={'code':str,'index_id':str}))
    else:
        metadata = pd.DataFrame(columns=METADATA_FIELDS)
        try:
            frames = [_api('etf_basic',{'list_status':status},'ts_code,extname,index_code,index_name,list_date')
                      for status in ('L','D')]
            pd.concat(frames,ignore_index=True).to_csv(cache/'metadata_candidates.csv',index=False)
            failures.append({'code':'*','reason':'current_directory_has_no_verified_historical_index_intervals'})
        except ValueError as error:
            failures.append({'code':'*','reason':str(error)})
    metadata = metadata.loc[metadata.code.isin(codes)].copy()
    metadata.to_csv(cache/'metadata.csv',index=False)
    if adjustments_path:
        raw = pd.read_parquet(adjustments_path) if adjustments_path.suffix=='.parquet' else pd.read_csv(adjustments_path,dtype={'code':str})
        factors = validate_adjustments(raw)
        for code, frame in factors.groupby('code'):
            if code in codes:
                frame.to_parquet(cache/'adjustments'/f'{code}.parquet',index=False)
        sources.append({'kind':'adjustment_factors','path':str(adjustments_path.resolve()),'sha256':sha256(adjustments_path)})
    pending = sorted(code for code in set(metadata.code) if not (cache/'adjustments'/f'{code}.parquet').is_file())
    with ThreadPoolExecutor(max_workers=workers) as executor:
        tasks = {executor.submit(_fetch_adjustments,code):code for code in pending}
        for future in as_completed(tasks):
            code = tasks[future]
            try:
                future.result().to_parquet(cache/'adjustments'/f'{code}.parquet',index=False)
            except (ValueError,OSError) as error:
                failures.append({'code':code,'reason':str(error)})
    audit = []
    for path in files:
        code = path.stem
        reasons = []
        if code not in set(metadata.code):
            reasons.append('missing_historical_index_mapping_or_listing_date')
        factor_path = cache/'adjustments'/f'{code}.parquet'
        if not factor_path.is_file():
            reasons.append('missing_adjustment_factors')
        audit.append({'code':code,'status':'ready' if not reasons else 'excluded','reason':';'.join(reasons)})
    pd.DataFrame(audit).to_csv(cache/'preparation_coverage.csv',index=False)
    manifest = {'version':1,'prepared_at':datetime.now(UTC).isoformat(), 'local_etf_dir':str(etf_dir.resolve()),
        'local_etf_count':len(files),'metadata_codes':int(metadata.code.nunique()),
        'ready_codes':sum(row['status']=='ready' for row in audit),
        'sources':sources,'failures':failures,'metadata_sha256':sha256(cache/'metadata.csv'),
        'adjustment_sha256':{path.stem:sha256(path) for path in sorted((cache/'adjustments').glob('*.parquet'))},
        'quotes':'original local files; no historical quotes downloaded',
        'adjustments':'multiplicative fund_adj factors; Sina ETF f/s/u is not interpreted as stock f'}
    (cache/'preparation_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',type=Path,default=CACHE)
    parser.add_argument('--etf-dir',type=Path,default=ETF_DIR)
    parser.add_argument('--metadata',type=Path,help='已核验历史指数映射CSV，包含有效区间与来源')
    parser.add_argument('--adjustments',type=Path,help='每日复权因子CSV或parquet：code,date,adj_factor')
    parser.add_argument('--workers',type=int,default=4)
    args = parser.parse_args(argv)
    if args.workers<1:
        parser.error('workers必须为正')
    result = prepare_data(args.cache,args.etf_dir,metadata_path=args.metadata,adjustments_path=args.adjustments,workers=args.workers)
    print(json.dumps({key:result[key] for key in ('local_etf_count','metadata_codes','ready_codes','failures')},ensure_ascii=False,indent=2))
    return 0 if result['ready_codes'] else 1


if __name__=='__main__':
    raise SystemExit(main())
