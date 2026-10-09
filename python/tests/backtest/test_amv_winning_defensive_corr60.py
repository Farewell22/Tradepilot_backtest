from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from python.backtest.broker import FeeConfig
from python.strategies.amv_winning_defensive.runner import run_defensive_backtest
from python.strategies.amv_winning_defensive_corr60.runner import run_dynamic_backtest, build_rankings, choose_candidate


def bars(prices):
    dates=pd.bdate_range('2024-01-02',periods=len(prices))
    return pd.DataFrame(dict(date=dates+pd.Timedelta(hours=15),open=prices,high=prices,low=prices,close=prices,volume=1e6))

def signals(n,buys=(),exits=()):
    return pd.DataFrame(dict(date=pd.bdate_range('2024-01-02',periods=n),buy_signal=[i in buys for i in range(n)],exit_ma10=[i in exits for i in range(n)],exit_macd=False))

def rankings(n):
    dates=pd.bdate_range('2024-01-02',periods=n)
    return pd.DataFrame(dict(date=np.repeat(dates,2),code=['A','B']*n,factor=[.9,.8]+[.7,.95]*(n-1),name=['A','B']*n,index_id=['A','B']*n,first_quote_date=pd.Timestamp('2020-01-01')))


def test_choose_ties_and_negative_not_absolute():
    r=rankings(2)
    r.loc[r.date.eq(r.date.min()),'factor']=[-.2,-.8]
    assert choose_candidate(r,r.date.min(),'512890.SH').code=='A'
    r['factor']=.9
    assert choose_candidate(r,r.date.min(),'512890.SH').code=='A'
    assert choose_candidate(r,pd.Timestamp('2000-01-01'),'512890.SH') is None


def test_hold_does_not_rotate_then_reselect():
    b={'512100.SH':bars([10]*4),'A':bars([10]*4),'B':bars([20]*4)}
    result=run_dynamic_backtest(b,bars([5]*4),signals(4,buys=(0,1,3),exits=(2,)), '512890.SH', rankings(4))
    assert result.trades[['code','side']].values.tolist()==[['A','buy'],['A','sell'],['512890.SH','buy'],['512890.SH','sell'],['B','buy']]
    assert result.selections.code.tolist()==['A','B']


def test_no_candidate_keeps_defense():
    b={'512100.SH':bars([10]*3),'A':bars([10]*3),'B':bars([20]*3)}
    result=run_dynamic_backtest(b,bars([5]*3),signals(3,buys=(1,),exits=(0,)), '512890.SH', rankings(3).iloc[:0])
    assert result.trades[['code','side']].values.tolist()==[['512890.SH','buy']]
    assert result.selections.reason.tolist()==['no_eligible_candidate']


@pytest.mark.parametrize('defense',['512890.SH','601288.SH'])
@pytest.mark.parametrize('scenario',['trading','cash','stop','trail','bank_profit'])
def test_fixed_primary_matches_original(defense,scenario):
    p=bars([10.,10.4,10.25,10.1,10.]);d=bars([5.,5.,5.,5.,5.])
    s=signals(5,buys=(0,4),exits=(3,))
    if scenario=='cash':s=signals(5)
    if scenario=='stop':p.loc[1,'low']=9.7
    if scenario=='trail':
        p.loc[1,['open','high','low']]=[10.3,10.6,10.3]
        p.loc[2,['open','high','low']]=[10.4,10.5,10.2]
    if scenario=='bank_profit':
        s=signals(5,buys=(4,),exits=(0,1,2,3));d.loc[1,'high']=5.7
    fees=FeeConfig.etf_legacy();stock=FeeConfig.stock_legacy() if defense=='601288.SH' else fees
    dividends={s.date.iloc[2]:.1} if defense=='601288.SH' else {}
    expected=run_defensive_backtest(p,d,s,defense,primary_fees=fees,defensive_fees=stock,dividends=dividends)
    r=pd.DataFrame(dict(date=s.date,code='512100.SH',factor=.9))
    actual=run_dynamic_backtest({'512100.SH':p},d,s,defense,r,primary_fees=fees,defensive_fees=stock,dividends=dividends)
    pd.testing.assert_frame_equal(expected.nav,actual.nav[expected.nav.columns])
    pd.testing.assert_frame_equal(expected.trades,actual.trades[expected.trades.columns])


def test_held_missing_data_raises_instead_of_dropping_day():
    b={'512100.SH':bars([10]*3),'A':bars([10]*3).iloc[:1],'B':bars([20]*3)}
    with pytest.raises(ValueError,match='持仓行情缺失'):
        run_dynamic_backtest(b,bars([5]*3),signals(3,buys=(0,)), '512890.SH', rankings(3))


def test_unavailable_candidate_is_not_replaced_using_future_data():
    b={'512100.SH':bars([10]*3),'A':bars([10]*3).iloc[1:],'B':bars([20]*3)}
    result=run_dynamic_backtest(b,bars([5]*3),signals(3,buys=(0,)), '512890.SH', rankings(3))
    assert result.trades.code.tolist()==['B']


def quote_csv(path,code,prices,dates):
    stamps=[d+pd.Timedelta(hours=h,minutes=m) for d in dates for h,m in [(10,30),(11,30),(14,0),(15,0)]]
    values=np.repeat(prices,4)
    pd.DataFrame(dict(时间=stamps,代码=code,名称=code,开盘价=values,最高价=values,最低价=values,收盘价=values,成交量=100.,成交额=100.)).to_csv(path,index=False)


def test_fixed_pool_excludes_future_break_but_rankings_are_trailing(tmp_path):
    dates=pd.bdate_range('2020-01-01',periods=130)
    market=pd.Series(100*np.cumprod(1+.005*np.sin(np.arange(130))),index=dates)
    etfs=tmp_path/'etfs';etfs.mkdir();out=tmp_path/'out';out.mkdir()
    a=market.values.copy();b=100*np.cumprod(1+.004*np.sin(np.arange(130))+.003*np.cos(np.arange(130)))
    bad=a.copy();bad[100:]*=3
    for code,values in [('A',a),('B',b),('BAD',bad)]:quote_csv(etfs/f'{code}.csv',code,values,dates)
    ranked,_,audit=build_rankings(etfs,market,out)
    assert set(audit.loc[audit.status.eq('eligible'),'code'])=={'A','B'}
    assert set(ranked.code)=={'A','B'}
    assert not ranked.date.lt(dates[60]).any()
    old=ranked.loc[ranked.date.le(dates[80])].reset_index(drop=True)
    a[90:]*=1.1
    quote_csv(etfs/'A.csv','A',a,dates)
    updated,_,_=build_rankings(etfs,market,out)
    pd.testing.assert_frame_equal(old,updated.loc[updated.date.le(dates[80])].reset_index(drop=True))


def test_registration():
    from python.task_registry import TASKS
    spec=TASKS['strategy','amv_winning_defensive_corr60']
    assert spec.default_start_date=='20190118'
    assert spec.execution_mode=='legacy_same_close_idealized'
    assert spec.default_config.is_file()


def test_runner_outputs_all_versions_and_requested_dates(tmp_path,monkeypatch):
    import yaml,json
    from python.run_backtest import RunRequest
    from python.strategies.amv_winning_defensive_corr60 import runner
    dates=pd.bdate_range('2020-01-01',periods=130)
    market=100*np.cumprod(1+.012*np.sin(np.arange(130)))
    market[65:]*=1.06;market[100:]*=1.06
    etfs=tmp_path/'etfs';etfs.mkdir()
    for code in ['512100.SH','512890.SH','A']:
        prices=market if code!='512890.SH' else np.full(len(dates),5.)
        quote_csv(etfs/f'{code}.csv',code,prices,dates)
    amv=tmp_path/'amv.csv';pd.DataFrame(dict(date=dates,close=market)).to_csv(amv,index=False)
    div=tmp_path/'div.csv';pd.DataFrame(columns=['ex_date','cash_per_share','source']).to_csv(div,index=False)
    paths=dict(amv_csv=str(amv),etf_dir=str(etfs),primary_csv=str(etfs/'512100.SH.csv'),defensive_etf_csv=str(etfs/'512890.SH.csv'),stock_5m_dir=str(tmp_path),stock_dividends_csv=str(div))
    config=tmp_path/'config.yaml';config.write_text(yaml.safe_dump(dict(paths=paths)))
    bank=pd.DataFrame(dict(date=dates+pd.Timedelta(hours=15),open=5.,high=5.,low=5.,close=5.,volume=1e6))
    monkeypatch.setattr(runner,'load_stock_bars',lambda *_:bank)
    request=RunRequest('amv_winning_defensive_corr60','strategy',dates[60].strftime('%Y%m%d'),dates[-1].strftime('%Y%m%d'),tmp_path/'run',FeeConfig.etf_legacy(),'legacy_same_close_idealized',config)
    runner.run(request)
    metadata=json.loads((request.output_dir/'metrics.json').read_text())
    assert len(metadata['variants'])==4
    for variant in metadata['variants']:
        nav=pd.read_csv(request.output_dir/variant/'nav.csv')
        observed=pd.to_datetime(nav.date)
        assert observed.between(dates[60],dates[-1]).all()
        assert len(nav)==70
    assert (request.output_dir/'report.md').is_file()
    assert (request.output_dir/'code_snapshot/manifest.json').is_file()


def test_public_type_hints_and_execution_mode():
    from typing import get_type_hints
    from python.strategies.amv_winning_defensive_corr60.runner import DynamicResult
    assert get_type_hints(run_dynamic_backtest)['return'] is DynamicResult
    with pytest.raises(ValueError,match='仅支持 same_close'):
        run_dynamic_backtest({'512100.SH':bars([10]*2)},bars([5]*2),signals(2), '512890.SH',rankings(2),execution_timing='next_open')


def test_session_view_lazy_day_lookup():
    from python.strategies.amv_winning_defensive_corr60.runner import SessionBars
    frame=bars([10,20,30])
    sessions=SessionBars(frame)
    dates=frame.date.dt.normalize()
    assert set(sessions)==set(dates)
    assert dates.iloc[1] in sessions
    pd.testing.assert_frame_equal(sessions[dates.iloc[1]],frame.iloc[[1]])


def test_invalid_raw_day_does_not_exclude_other_clean_history(tmp_path):
    dates=pd.bdate_range('2020-01-01',periods=130)
    market=pd.Series(100*np.cumprod(1+.005*np.sin(np.arange(130))),index=dates)
    etfs=tmp_path/'etfs';etfs.mkdir();out=tmp_path/'out';out.mkdir()
    path=etfs/'A.csv';quote_csv(path,'A',market.values,dates)
    raw=pd.read_csv(path);raw.loc[0,['开盘价','收盘价','最高价','最低价']]=0
    raw.to_csv(path,index=False)
    ranked,_,audit=build_rankings(etfs,market,out)
    assert audit.status.tolist()==['eligible']
    assert not ranked.empty
