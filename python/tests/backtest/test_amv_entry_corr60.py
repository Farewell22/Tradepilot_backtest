import numpy as np
import pandas as pd
import pytest

from python.factors.amv_correlation import rolling_amv_correlation
from python.research.etf.amv_entry_corr60.data import aggregate_daily, adjusted_prices, forward_labels, select_representatives
from python.research.etf.amv_entry_corr60.statistics import event_statistics, overlap_clusters
from python.research.etf.amv_entry_corr60.prepare import validate_metadata, validate_adjustments, prepare_data
from python.research.etf.amv_entry_corr60.local_screen import name_group, screen_prices, clean_forward_labels


def test_correlation_requires_61_closes_and_no_calendar_compression():
    dates = pd.bdate_range('2020-01-01', periods=90)
    price = pd.Series(100 * np.cumprod(1 + np.sin(np.arange(90)) / 100), index=dates)
    factor = rolling_amv_correlation(price, price)
    assert factor.iloc[:60].isna().all()
    assert factor.iloc[60] == pytest.approx(1)
    changed = price.copy()
    changed.iloc[75:] *= 3
    pd.testing.assert_series_equal(factor.iloc[:75], rolling_amv_correlation(changed, price).iloc[:75])
    changed.iloc[40] = np.nan
    assert rolling_amv_correlation(changed, price).iloc[60:].isna().all()
    assert rolling_amv_correlation(pd.Series(1., index=dates), price).isna().all()


def test_daily_exact_duplicates_not_double_counted_conflicts_invalidate_day():
    times = pd.to_datetime(['2020-01-02 10:30','2020-01-02 11:30','2020-01-02 14:00','2020-01-02 15:00'])
    raw = pd.DataFrame(dict(timestamp=times, open=1., high=1., low=1., close=1., volume=10., amount=10.))
    daily, audit = aggregate_daily(pd.concat([raw, raw.iloc[[0]]]))
    assert daily.volume.iloc[0] == 40
    assert daily.valid.iloc[0]
    assert audit['exact_duplicates'] == 1
    conflict = raw.iloc[[0]].copy(); conflict['close'] = 2.
    assert not aggregate_daily(pd.concat([raw, conflict]))[0].valid.iloc[0]


def test_adjustment_and_exact_market_forward_endpoints():
    dates = pd.bdate_range('2020-01-01', periods=7)
    raw = pd.DataFrame(dict(date=dates, open=[10,10,5,5,5,5,5], close=[10,10,5,5,5,5,5], valid=True))
    adj = pd.DataFrame(dict(date=dates, adj_factor=[1,1,2,2,2,2,2]))
    prices = adjusted_prices(raw, adj)
    assert prices.close.nunique() == 1
    labels = forward_labels(prices, [dates[0]], dates, horizons=(5,10))
    assert labels.iloc[0].return_5 == 0
    assert labels.iloc[0].exit_date_5 == dates[5]
    assert pd.isna(labels.iloc[0].return_10)
    prices.loc[prices.date.eq(dates[1]), 'valid'] = False
    assert pd.isna(forward_labels(prices, [dates[0]], dates, horizons=(5,)).iloc[0].return_5)


def test_oldest_eligible_representative_never_uses_future_labels():
    frame = pd.DataFrame(dict(date=pd.Timestamp('2020-01-01'), code=['B','A','C'], index_id=['X']*3,
                              list_date=pd.to_datetime(['2010-01-01','2010-01-01','2009-01-01']),
                              factor=[.4,.3,np.nan], return_5=[.1,np.nan,.2]))
    chosen, audit = select_representatives(frame)
    assert chosen.code.tolist() == ['A']
    assert pd.isna(chosen.return_5.iloc[0])
    assert len(audit) == 3


def test_missing_future_adjustment_never_erases_historical_factor_or_representative():
    dates = pd.bdate_range('2020-01-01',periods=100)
    close = 100*np.cumprod(1+.01*np.sin(np.arange(100)))
    daily = pd.DataFrame(dict(date=dates,open=close,close=close,valid=True))
    factors = pd.DataFrame(dict(date=dates,adj_factor=1.))
    event = dates[65]
    complete = adjusted_prices(daily,factors)
    incomplete = adjusted_prices(daily,factors.loc[~factors.date.eq(dates[70])])
    market = pd.Series(close,index=dates)
    complete_factor = rolling_amv_correlation(complete.set_index('date').close,market).loc[event]
    incomplete_factor = rolling_amv_correlation(incomplete.set_index('date').close,market).loc[event]
    assert complete_factor == pytest.approx(incomplete_factor)
    assert not incomplete.loc[incomplete.date.eq(dates[70]),'valid'].iloc[0]
    assert pd.isna(forward_labels(incomplete,[event],dates,horizons=(5,)).return_5.iloc[0])
    frame = pd.DataFrame(dict(date=event,code=['old','new'],index_id='X',
        list_date=pd.to_datetime(['2010-01-01','2011-01-01']),factor=[incomplete_factor,.8],return_5=[np.nan,.2]))
    assert select_representatives(frame)[0].code.tolist()==['old']


def test_quintiles_precede_labels_and_dates_are_observation_units():
    rows = pd.DataFrame(dict(date=pd.Timestamp('2020-01-01'), code=[str(i) for i in range(10)],
                             factor=np.arange(10), return_5=np.arange(10)/100))
    out = event_statistics(rows, horizons=(5,))
    assert out.loc[out.group.eq('Q5-Q1'),'mean_return'].iloc[0] == pytest.approx(.08)
    assert out.loc[out.group.eq('IC'),'mean_return'].iloc[0] == pytest.approx(1.)
    rows.loc[rows.factor.eq(9),'return_5'] = np.nan
    out = event_statistics(rows, horizons=(5,))
    assert out.loc[out.group.eq('Q5'),'mean_return'].iloc[0] == pytest.approx(.08)


def test_overlap_clusters_count_time_not_etfs():
    calendar = pd.bdate_range('2020-01-01', periods=30)
    assert overlap_clusters(calendar[[0,3,10]], calendar, 5).tolist() == [0,0,1]


def test_metadata_requires_intervals_aliases_and_numeric_dates():
    rows = pd.DataFrame(dict(code=['A','A'], name=['A','A'],index_id=['399300.SZ','000300.SH'],
        list_date=[20100101]*2,valid_from=[20100101,20200101],valid_to=['2019-12-31',''],source_url=['https://example.org']*2))
    result = validate_metadata(rows)
    assert result.index_id.tolist()==['000300.SH']*2
    assert result.list_date.iloc[0]==pd.Timestamp('2010-01-01')
    rows.loc[0,'valid_to']='2020-01-01'
    with pytest.raises(ValueError,match='重叠'):
        validate_metadata(rows)
    assert validate_adjustments(pd.DataFrame(dict(code=['A'],date=[20200101],adj_factor=[1.]))).date.iloc[0]==pd.Timestamp('2020-01-01')


def test_full_research_pipeline_on_local_fixture(tmp_path,monkeypatch):
    import python.research.etf.amv_entry_corr60.study as study
    dates = pd.bdate_range('2020-01-01',periods=130)
    returns = .003*np.sin(np.arange(130))+.001*np.cos(np.arange(130)/5)
    amv = 100*np.cumprod(1+returns)
    amv_path = tmp_path/'amv.csv'
    pd.DataFrame(dict(date=dates,close=amv)).to_csv(amv_path,index=False)
    etfs = tmp_path/'etfs'; etfs.mkdir()
    metadata,adjustments = [],[]
    for i in range(12):
        code = f'{i:06}.SH'
        prices = np.cumprod(1+returns*(i+1)/12+.001*np.cos(np.arange(130)*(i+2)/4))
        times = [date+pd.Timedelta(hours=hour,minutes=minute) for date in dates
                 for hour,minute in [(10,30),(11,30),(14,0),(15,0)]]
        quote = np.repeat(prices,4)
        pd.DataFrame(dict(时间=times,代码=code,名称=code,开盘价=quote,收盘价=quote,最高价=quote,最低价=quote,
                          成交量=100.,成交额=100.)).to_csv(etfs/f'{code}.csv',index=False)
        metadata.append(dict(code=code,name=code,index_id=f'IDX{i}',list_date='2018-01-01',
                             valid_from='2018-01-01',valid_to='',source_url='https://example.org/fixture'))
        adjustments.append(pd.DataFrame(dict(code=code,date=dates,adj_factor=1.)))
    meta_path=tmp_path/'meta.csv';pd.DataFrame(metadata).to_csv(meta_path,index=False)
    adj_path=tmp_path/'adj.parquet';pd.concat(adjustments).to_parquet(adj_path,index=False)
    cache=tmp_path/'cache'
    prepared=prepare_data(cache,etfs,metadata_path=meta_path,adjustments_path=adj_path)
    assert prepared['ready_codes']==12
    monkeypatch.setattr(study,'source_events',lambda _:pd.DataFrame(dict(date=dates[[65,80,100]],versions='fixture',version_difference=False)))
    output=tmp_path/'run'
    study.run_research(output,etf_dir=etfs,cache=cache,amv_path=amv_path)
    rows=pd.read_parquet(output/'observations.parquet')
    assert len(rows)==36
    assert not rows.duplicated(['date','index_id']).any()
    assert rows.return_20.notna().all()
    assert (output/'report.md').is_file()
    local=tmp_path/'local_run'
    study.run_research(local,etf_dir=etfs,cache=tmp_path/'absent_cache',amv_path=amv_path,price_mode='local_screen')
    local_rows=pd.read_parquet(local/'observations.parquet')
    assert len(local_rows)==36
    assert not local_rows.duplicated(['date','index_id']).any()
    assert local_rows.return_20.notna().all()
    assert '未复权清洁价格收益' in (local/'report.md').read_text()
    summary=pd.read_csv(output/'summary.csv')
    assert summary.loc[summary.group.eq('IC') & summary.stage.eq('all'),'event_count'].eq(3).all()
    # A date filter retains pre-window prices; it must not restart the strategy.
    smaller=tmp_path/'filtered'
    study.run_research(smaller,start_date=dates[80].strftime('%Y%m%d'),end_date=dates[80].strftime('%Y%m%d'),
                       etf_dir=etfs,cache=cache,amv_path=amv_path)
    filtered=pd.read_parquet(smaller/'observations.parquet')
    pd.testing.assert_series_equal(rows.loc[rows.date.eq(dates[80]),'factor'].reset_index(drop=True),filtered.factor,check_names=False)


def test_registration_exposes_full_history_and_zero_research_fees():
    from python.task_registry import TASKS
    spec=TASKS['research','amv_entry_corr60']
    assert spec.default_start_date=='20190118'
    assert spec.default_end_date=='20251231'
    assert spec.default_fees.commission_rate==0
    assert not spec.supports_fee_override


def test_local_names_conservative_groups_and_history_proxy():
    assert name_group('沪深300ETF华泰柏瑞')==name_group('沪深300ETF嘉实')
    assert name_group('300ETF')==name_group('沪深300ETF')
    assert name_group('沪深300ESGETF')!=name_group('沪深300ETF')
    assert name_group('中证500ETF')!=name_group('中证500增强ETF')
    assert name_group('芯片ETF')!=name_group('半导体ETF')
    frame=pd.DataFrame(dict(date=pd.Timestamp('2020-01-01'),code=['old','new'],index_id='G',
        first_quote_date=pd.to_datetime(['2010-01-01','2012-01-01']),factor=[.4,.6]))
    assert select_representatives(frame,date_column='first_quote_date')[0].code.tolist()==['old']


def test_local_jumps_mask_windows_without_removing_past_samples():
    dates=pd.bdate_range('2020-01-01',periods=140)
    prices=100*np.cumprod(1+.005*np.sin(np.arange(140)))
    prices[80:]*=3
    daily=pd.DataFrame(dict(date=dates,open=prices,close=prices,high=prices,low=prices,valid=True))
    clean,jumps=screen_prices(daily,jump_threshold=.25)
    market=pd.Series(100*np.cumprod(1+.005*np.sin(np.arange(140))),index=dates)
    assert jumps.date.tolist()==[dates[80]]
    f=rolling_amv_correlation(clean.set_index('date').close,market)
    assert pd.notna(f.loc[dates[65]])
    assert pd.isna(f.loc[dates[85]])
    # The split was not known at t=74: retain the ETF, mark polluted labels missing.
    labels=clean_forward_labels(clean,jumps,[dates[65],dates[74]],dates,horizons=(5,20))
    assert pd.notna(labels.loc[labels.date.eq(dates[74]),'return_5'].iloc[0])
    assert pd.isna(labels.loc[labels.date.eq(dates[74]),'return_20'].iloc[0])
    assert labels.loc[labels.date.eq(dates[74]),'missing_reason_20'].iloc[0]=='suspected_price_break_in_window'
    # A price jump after the label endpoint must not remove an earlier label.
    assert pd.notna(labels.loc[labels.date.eq(dates[65]),'return_5'].iloc[0])
