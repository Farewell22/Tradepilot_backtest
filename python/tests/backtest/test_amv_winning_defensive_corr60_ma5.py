import numpy as np
import pandas as pd
import pytest
from python.backtest.broker import FeeConfig,calc_sell_proceeds
from python.strategies.amv_winning_defensive_corr60.runner import run_dynamic_backtest
from python.tests.backtest.test_amv_winning_defensive_corr60 import bars,rankings,signals
from python.factors.amv_ma5_entry import generate_signals,weak_exit_parameters,net_exit_price
from python.strategies.amv_winning_defensive_corr60_ma5.runner import run_branch_backtest


def zero():return FeeConfig(commission_rate=0,min_commission=0,stamp_duty_rate=0,transfer_fee_rate=0,slippage_rate=0)


def branch_signals(n,weak=(),high=(),exits=(),rise=.02):
 s=signals(n,buys=tuple(set(weak)|set(high)),exits=exits)
 s['high_signal']=[i in high for i in range(n)];s['weak_signal']=[i in weak for i in range(n)]
 s['entry_branch']=np.where(s.high_signal,'high',np.where(s.weak_signal,'weak',''))
 s['day_return']=rise
 return s


def run_sample(prices,s,**kwargs):
 return run_branch_backtest({'512100.SH':bars([10]*len(prices)),'A':bars(prices),'B':bars([20]*len(prices))},bars([5]*len(prices)),s,'512890.SH',rankings(len(prices)),primary_fees=zero(),defensive_fees=zero(),**kwargs)


def test_cross_is_strict_and_high_unchanged():
 from python.strategies.amv_winning.runner import generate_amv_signals
 dates=pd.bdate_range('2024-01-01',periods=12)
 raw=pd.DataFrame(dict(date=dates,close=[100,100,100,100,100,99,100,101,102,103,108,107]))
 result=generate_signals(raw);original=generate_amv_signals(raw)
 pd.testing.assert_series_equal(result.high_signal,original.buy_signal,check_names=False)
 assert not result.weak_signal.iloc[4]
 assert result.weak_signal.iloc[6]
 assert not result.weak_signal.iloc[7]
 assert result.entry_branch.iloc[10]=='high'


@pytest.mark.parametrize('rise,sl,tp',[(-.01,.01,.015),(.01499,.01,.015),(.015,.0125,.02),(.02999,.0125,.02),(.03,.015,.025)])
def test_tier_boundaries(rise,sl,tp):assert weak_exit_parameters(rise)==(sl,tp)


@pytest.mark.parametrize('quantity',[100,100000])
@pytest.mark.parametrize('target',[-.0125,.02])
def test_fee_inversion(quantity,target):
 fees=FeeConfig.etf_legacy();cost=quantity*10.01+max(5,quantity*10.01*.0003)
 price=net_exit_price(cost,quantity,target,fees)
 assert calc_sell_proceeds(price,quantity,fees)[1]/cost-1==pytest.approx(target,abs=1e-12)


def test_weak_net_stop_and_same_day_strong_blocked():
 s=branch_signals(3,weak=(0,),high=(1,))
 p=bars([10.,10.,10.]);p.loc[1,'low']=9.8
 result=run_branch_backtest({'512100.SH':bars([10]*3),'A':p,'B':bars([20]*3)},bars([5]*3),s,'512890.SH',rankings(3),primary_fees=zero(),defensive_fees=zero())
 assert result.trades.reason.tolist()==['amv_buy_signal','weak_net_stop']
 assert result.trades.iloc[1].pnl_pct==pytest.approx(-1.25)
 assert result.upgrades.empty
 assert result.signal_audit.loc[result.signal_audit.date.eq(s.date.iloc[1]),'action'].iloc[0]=='blocked_exit_today'


def test_weak_profit_and_both_touch_stop_first():
 s=branch_signals(2,weak=(0,))
 result=run_sample([10,10.3],s)
 assert result.trades.iloc[1].reason=='weak_net_take_profit'
 assert result.trades.iloc[1].pnl_pct==pytest.approx(3) # gap at open
 p=bars([10.,10.]);p.loc[1,['high','low']]=[10.5,9.5]
 result=run_branch_backtest({'512100.SH':bars([10]*2),'A':p,'B':bars([20]*2)},bars([5]*2),s,'512890.SH',rankings(2),primary_fees=zero(),defensive_fees=zero())
 assert result.trades.iloc[1].reason=='weak_net_stop'


def test_time_exit_and_upgrade_priority():
 s=branch_signals(5,weak=(0,))
 result=run_sample([10]*5,s)
 assert result.trades.iloc[1].date==s.date.iloc[3].strftime('%Y%m%d')
 assert result.trades.iloc[1].reason=='weak_time_exit'
 s=branch_signals(5,weak=(0,),high=(3,))
 result=run_sample([10]*5,s)
 assert len(result.trades)==1
 assert len(result.upgrades)==1
 assert result.upgrades.iloc[0].code=='A' # B now ranks higher; do not rotate
 assert result.upgrades.iloc[0].reference_price==10
 assert result.upgrades.iloc[0].buy_cost==200000
 assert result.nav.iloc[-1].primary_quantity==20000


def test_amv_exit_precedes_upgrade_and_time_exit():
 s=branch_signals(5,weak=(0,),high=(3,),exits=(3,))
 result=run_sample([10]*5,s)
 assert result.upgrades.empty
 assert result.trades.reason.tolist()==['amv_buy_signal','amv_close_below_ma10','amv_close_below_ma10']


def test_disable_weak_matches_existing():
 p={'512100.SH':bars([10]*5),'A':bars([10]*5),'B':bars([20]*5)};d=bars([5]*5)
 s=branch_signals(5,weak=(1,),high=(0,4),exits=(3,))
 old=s.copy();old.buy_signal=old.high_signal;old=old.drop(columns=['entry_branch'])
 expected=run_dynamic_backtest(p,d,old,'512890.SH',rankings(5))
 actual=run_branch_backtest(p,d,s,'512890.SH',rankings(5),weak_enabled=False)
 pd.testing.assert_frame_equal(expected.nav,actual.nav[expected.nav.columns])
 pd.testing.assert_frame_equal(expected.trades,actual.trades[expected.trades.columns])


def test_control_matches_original_exits_even_when_upgraded():
 p=bars([10.,10.4,10.25,10.1,10.]);p.loc[1,['open','high','low']]=[10.3,10.6,10.3]
 p.loc[2,['open','high','low']]=[10.4,10.5,10.2]
 all_bars={'512100.SH':bars([10]*5),'A':p,'B':bars([20]*5)};d=bars([5]*5)
 s=branch_signals(5,weak=(0,),high=(1,4))
 expected=run_dynamic_backtest(all_bars,d,s,'512890.SH',rankings(5))
 actual=run_branch_backtest(all_bars,d,s,'512890.SH',rankings(5),tight_weak=False)
 pd.testing.assert_frame_equal(expected.nav,actual.nav[expected.nav.columns])
 pd.testing.assert_frame_equal(expected.trades,actual.trades[expected.trades.columns])


def test_registration():
 from python.task_registry import TASKS
 spec=TASKS['strategy','amv_winning_defensive_corr60_ma5']
 assert spec.execution_mode=='legacy_same_close_idealized'
 assert spec.default_config.is_file()


def test_future_signal_invariance():
 dates=pd.bdate_range('2024-01-01',periods=100)
 raw=pd.DataFrame(dict(date=dates,close=100*np.cumprod(1+.01*np.sin(np.arange(100)))))
 a=generate_signals(raw);raw.loc[80:,'close']*=1.1;b=generate_signals(raw)
 pd.testing.assert_frame_equal(a.iloc[:80],b.iloc[:80])


def test_time_exit_cannot_reopen_and_negative_cross_uses_floor():
 s=branch_signals(5,weak=(0,3),rise=-.001)
 result=run_sample([10]*5,s)
 assert len(result.trades)==2
 assert result.trades.iloc[0].weak_stop==.01
 assert result.signal_audit.iloc[-1].action=='blocked_exit_today'


@pytest.mark.parametrize('filtered',[False,True])
def test_runner_six_variants(tmp_path,monkeypatch,filtered):
 import yaml,json
 from python.run_backtest import RunRequest
 from python.tests.backtest.test_amv_winning_defensive_corr60 import quote_csv
 from python.strategies.amv_winning_defensive_corr60_ma5 import runner
 dates=pd.bdate_range('2020-01-01',periods=130)
 market=100*np.cumprod(1+.015*np.sin(np.arange(130)));market[65:]*=1.06
 etfs=tmp_path/'etfs';etfs.mkdir()
 for code in ['512100.SH','512890.SH','A']:
  quote_csv(etfs/f'{code}.csv',code,market if code!='512890.SH' else np.full(130,5.),dates)
 amv=tmp_path/'amv.csv';pd.DataFrame(dict(date=dates,close=market)).to_csv(amv,index=False)
 div=tmp_path/'div.csv';pd.DataFrame(columns=['ex_date','cash_per_share','source']).to_csv(div,index=False)
 paths=dict(amv_csv=str(amv),etf_dir=str(etfs),primary_csv=str(etfs/'512100.SH.csv'),defensive_etf_csv=str(etfs/'512890.SH.csv'),stock_5m_dir=str(tmp_path),stock_dividends_csv=str(div))
 config=tmp_path/'config.yaml';config.write_text(yaml.safe_dump(dict(paths=paths,weak_entry=dict(minimum_day_return=.015))))
 bank=pd.DataFrame(dict(date=dates+pd.Timedelta(hours=15),open=5.,high=5.,low=5.,close=5.,volume=1e6))
 monkeypatch.setattr(runner,'load_stock_bars',lambda *_:bank)
 request=RunRequest('amv_winning_defensive_corr60_ma5','strategy',dates[60].strftime('%Y%m%d'),dates[-1].strftime('%Y%m%d'),tmp_path/'run',FeeConfig.etf_legacy(),'legacy_same_close_idealized',config)
 if filtered:
  from python.strategies.amv_winning_defensive_corr60_ma5_15.runner import run
  run(request)
 else:
  runner.run(request)
 m=json.loads((request.output_dir/'metrics.json').read_text())
 assert len(m['variants'])==6
 if filtered:
  assert 'filtered_601288.SH' in m['variants'] and 'control_601288.SH' not in m['variants']
  assert m['minimum_weak_return']==.015
  f=pd.read_csv(request.output_dir/'filtered_amv_signals.csv')
  assert f.loc[f.weak_signal,'day_return'].ge(.015).all()
  assert (request.output_dir/'code_snapshot/python/strategies/amv_winning_defensive_corr60_ma5_15/runner.py').is_file()
 for name in m['variants']:
  nav=pd.read_csv(request.output_dir/name/'nav.csv')
  assert len(nav)==70
  assert pd.to_datetime(nav.date).between(dates[60],dates[-1]).all()
 assert (request.output_dir/'branch_statistics.csv').is_file()
 assert (request.output_dir/'ma5_601288.SH/upgrades.csv').is_file()


@pytest.mark.parametrize('upgrade_close,expected_trail',[(10.4,False),(10.6,True)])
def test_upgrade_arms_profit_only_from_close(upgrade_close,expected_trail):
 p=bars([10.,upgrade_close,10.3]);p.loc[1,['open','high','low']]=[10.5,10.8,10.4]
 p.loc[2,['open','high','low']]=[10.5,10.5,10.3]
 s=branch_signals(3,weak=(0,),high=(1,))
 result=run_branch_backtest({'512100.SH':bars([10]*3),'A':p,'B':bars([20]*3)},bars([5]*3),s,'512890.SH',rankings(3),primary_fees=zero(),defensive_fees=zero(),tiers=((float('inf'),.2,.2),))
 assert len(result.upgrades)==1
 assert result.trades.reason.str.startswith('profit_trail').any()==expected_trail


def test_minimum_weak_return_filters_only_weak_and_keeps_boundary():
 from python.factors.amv_ma5_entry import filter_weak_signals
 s=branch_signals(4,weak=(0,1,2),high=(3,))
 s['day_return']=[.014999,.015,.03,.005]
 f=filter_weak_signals(s,.015)
 assert f.weak_signal.tolist()==[False,True,True,False]
 assert f.high_signal.tolist()==s.high_signal.tolist()
 assert f.buy_signal.tolist()==[False,True,True,True]
 assert f.entry_branch.tolist()==['','weak','weak','high']
 pd.testing.assert_frame_equal(filter_weak_signals(s,None),s)


def test_filtered_weak_does_not_buy_later_without_new_cross():
 from python.factors.amv_ma5_entry import filter_weak_signals
 s=branch_signals(4,weak=(0,2));s['day_return']=[.01,.02,.015,.02]
 result=run_sample([10]*4,filter_weak_signals(s,.015))
 assert result.trades.iloc[0].date==s.date.iloc[2].strftime('%Y%m%d')


def test_minimum_task_registered():
 from python.task_registry import TASKS
 spec=TASKS['strategy','amv_winning_defensive_corr60_ma5_15']
 assert spec.default_config.is_file()
