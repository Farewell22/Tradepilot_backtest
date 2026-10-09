"""MA5-cross entry with weak net exits and cost-preserving strong upgrades."""
from dataclasses import dataclass
import json
import math
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from python.factors.amv_ma5_entry import DEFAULT_TIERS,generate_signals,weak_exit_parameters,net_exit_price,filter_weak_signals
from python.strategies.amv_winning_defensive_corr60.runner import (
    DynamicResult,SessionBars,choose_candidate,PRIMARY,STOCK_BANK_CODES,DEFENSIVE_ETF,
    DEFENSIVE_STOCK,DEFENSIVE_ETF_SPLIT_DATE,CONSOLIDATION_DATE,CONSOLIDATION_RATIO,
    FeeConfig,calc_buy_cost,calc_sell_proceeds,_normalize_intraday,_quantity,_bank_take_profit_price,
    build_rankings,load_stock_bars,load_dividend_events,paired_trades,compute_performance_metrics,
    run_dynamic_backtest,ROOT,RunRequest,sha256,asdict,
)

@dataclass
class BranchResult(DynamicResult):
    upgrades: pd.DataFrame
    signal_audit: pd.DataFrame


def run_branch_backtest(
    primary_bars: dict[str, pd.DataFrame],
    defensive_bars: pd.DataFrame,
    amv_signals: pd.DataFrame,
    defensive_code: str,
    rankings: pd.DataFrame,
    initial_cash: float = 200_000.0,
    primary_fees: FeeConfig | None = None,
    defensive_fees: FeeConfig | None = None,
    dividends: dict[pd.Timestamp, float] | None = None,
    *, execution_timing: str = "same_close", primary_code: str = PRIMARY,
    weak_enabled: bool = True, tight_weak: bool = True, max_hold_sessions: int = 3,
    tiers=DEFAULT_TIERS,
) -> BranchResult:
    """Use the original same-close execution with dynamic primary selection.

    A primary intraday stop is sold at the stop bar and leaves cash. Only
    an AMV close exit buys defense. Dividend amounts are per share on ex date.
    """
    if not primary_code or primary_code == defensive_code:
        raise ValueError("主仓代码必须非空且与防守标的不同")
    if defensive_code not in STOCK_BANK_CODES | {DEFENSIVE_ETF}:
        raise ValueError(f"不支持的防守标的: {defensive_code}")
    if initial_cash <= 0:
        raise ValueError("初始资金必须大于 0")
    if execution_timing != "same_close":
        raise ValueError("本策略仅支持 same_close")
    primary_fees = primary_fees or FeeConfig.etf_legacy()
    defensive_fees = defensive_fees or (
        FeeConfig.stock_legacy() if defensive_code in STOCK_BANK_CODES else FeeConfig.etf_legacy()
    )
    primary = {code: _normalize_intraday(frame) for code,frame in primary_bars.items()}
    if primary_code not in primary:
        raise ValueError("缺少基准主仓行情")
    selection_rows = []
    upgrade_rows = []
    signal_rows = []
    if not isinstance(max_hold_sessions,int) or max_hold_sessions<1:
        raise ValueError("弱仓持有期限必须为正整数")
    weak_exit_parameters(0.,tiers)
    defensive = _normalize_intraday(defensive_bars)
    signals = amv_signals.copy()
    if 'high_signal' not in signals:
        signals['high_signal'] = signals.buy_signal
    if 'weak_signal' not in signals:
        signals['weak_signal'] = False
    signals['buy_signal'] = signals.high_signal | (signals.weak_signal & weak_enabled)
    signals['entry_branch'] = np.where(signals.high_signal,'high',np.where(signals.weak_signal & weak_enabled,'weak',''))
    required = {"date", "buy_signal", "exit_ma10", "exit_macd"}
    if not required.issubset(signals.columns):
        raise ValueError(f"0AMV 信号缺少列: {sorted(required - set(signals.columns))}")
    signals["date"] = pd.to_datetime(signals["date"]).dt.normalize()
    if signals["date"].duplicated().any():
        raise ValueError("0AMV 信号存在重复日期")
    signal_map = signals.set_index("date")
    sessions = {code: SessionBars(bars) for code,bars in {**primary, defensive_code:defensive}.items()}
    dates = sorted(set(signal_map.index) & set(sessions[primary_code]) & set(sessions[defensive_code]))
    if not dates:
        raise ValueError("0AMV、主仓和防守标的没有共同交易日")

    cash = float(initial_cash)
    positions: dict[str, dict] = {}
    trade_rows: list[dict] = []
    nav_rows: list[dict] = []
    previous_body_low: float | None = None
    dividend_total = 0.0
    bank_take_profit_locked = False
    dividend_map = {pd.Timestamp(date).normalize(): float(amount)
                    for date, amount in (dividends or {}).items()}

    def sell(code: str, date: pd.Timestamp, price: float, reason: str,
             time: str = "15:00", signal_date: pd.Timestamp | None = None) -> None:
        nonlocal cash
        held = positions.pop(code)
        fees = primary_fees if code == primary_code else defensive_fees
        exec_price, proceeds = calc_sell_proceeds(price, held["quantity"], fees)
        cash += proceeds
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "sell", "quantity": held["quantity"], "signal_price": price,
            "exec_price": exec_price, "cash_flow": proceeds, "reason": reason,
            "dividend_income": held["dividend_income"],
            "pnl": proceeds + held["dividend_income"] - held["buy_cost"],
            "pnl_pct": (proceeds + held["dividend_income"]) / held["buy_cost"] * 100 - 100,
            "hold_sessions": session_index - held["entry_session_index"],
        })
        trade_rows[-1].update(entry_branch=held.get('entry_branch','defense'),
            exit_mode=held.get('mode','defense'),upgrade_date=held.get('upgrade_date',''))
        if "entry_signal_date" in held:
            trade_rows[-1].update(
                signal_date=(signal_date if signal_date is not None else date).strftime("%Y%m%d"),
                entry_signal_date=held["entry_signal_date"], entry_branch=held["entry_branch"],
            )

    def buy(code: str, date: pd.Timestamp, price: float, reason: str,
            time: str = "15:00", signal_date: pd.Timestamp | None = None,
            entry_branch: str = "") -> None:
        nonlocal cash
        fees = primary_fees if code == primary_code else defensive_fees
        quantity = _quantity(price, cash, fees)
        if quantity == 0:
            return
        exec_price, cost = calc_buy_cost(price, quantity, fees)
        cash -= cost
        positions[code] = {
            "quantity": quantity, "buy_cost": cost, "entry_date": date,
            "entry_session_index": session_index, "reference_price": exec_price,
            "profit_armed": False, "dividend_income": 0.0,
            "consolidation_applied": date >= CONSOLIDATION_DATE,
            "defensive_split_applied": date >= DEFENSIVE_ETF_SPLIT_DATE,
        }
        if code == primary_code:
            held = positions[code]
            held['mode'] = 'weak' if entry_branch=='weak' else 'strong'
            held['entry_branch'] = entry_branch
            if held['mode']=='weak':
                rise = float(signal_map.loc[date,'day_return'])
                stop,profit = weak_exit_parameters(rise,tiers)
                held.update(amv_entry_return=rise,weak_stop=stop,weak_profit=profit,
                    weak_stop_price=net_exit_price(cost,quantity,-stop,primary_fees),
                    weak_profit_price=net_exit_price(cost,quantity,profit,primary_fees))
        if code in STOCK_BANK_CODES:
            positions[code]["take_profit_price"] = _bank_take_profit_price(quantity, cost, fees)
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": exec_price, "cash_flow": -cost, "reason": reason,
        })
        if code == primary_code:
            trade_rows[-1].update(entry_branch=entry_branch,
                amv_entry_return=positions[code].get('amv_entry_return',float('nan')),
                weak_stop=positions[code].get('weak_stop',float('nan')),
                weak_profit=positions[code].get('weak_profit',float('nan')))
        if signal_date is not None:
            positions[code].update(entry_signal_date=signal_date.strftime("%Y%m%d"),
                                   entry_branch=entry_branch)
            trade_rows[-1].update(signal_date=signal_date.strftime("%Y%m%d"),
                                 entry_signal_date=signal_date.strftime("%Y%m%d"),
                                 entry_branch=entry_branch)

    def execute_signal(signal: pd.Series, date: pd.Timestamp,
                       primary_price: float, defensive_price: float, time: str) -> None:
        nonlocal bank_take_profit_locked, primary_code, previous_body_low
        exit_ma10, exit_macd = bool(signal["exit_ma10"]), bool(signal["exit_macd"])
        annotated = "entry_branch" in signal.index
        source_date = signal.name if annotated else None
        if exit_ma10 or exit_macd:
            reason = (
                "amv_close_below_ma10_and_macd_dead_cross" if exit_ma10 and exit_macd
                else "amv_close_below_ma10" if exit_ma10 else "amv_macd_dead_cross"
            )
            if primary_code in positions:
                sell(primary_code, date, primary_price, reason, time, source_date)
            if defensive_code not in positions and not bank_take_profit_locked:
                buy(defensive_code, date, defensive_price, reason, time, source_date)
        elif (bool(signal['high_signal']) and primary_code in positions
              and positions[primary_code].get('mode')=='weak'):
            held=positions[primary_code]
            held['mode']='strong'
            held['upgrade_date']=date.strftime('%Y%m%d')
            held['profit_armed']=held['profit_armed'] or primary_price>held['reference_price']*1.05
            upgrade_rows.append(dict(date=date,code=primary_code,entry_date=held['entry_date'],
                reference_price=held['reference_price'],buy_cost=held['buy_cost'],quantity=held['quantity']))
        elif bool(signal["buy_signal"]) and primary_code not in positions:
            available = rankings.loc[rankings.date.eq(date)].copy()
            available = available.loc[available.code.map(lambda code: date in sessions.get(code, {}))]
            selected = choose_candidate(available, date, defensive_code)
            if selected is None:
                selection_rows.append(dict(date=date,code='',factor=float('nan'),candidate_count=len(available),reason='no_eligible_candidate'))
                return
            primary_code = str(selected.code)
            selected_day = sessions[primary_code][date].sort_values('date')
            primary_price = float(selected_day.iloc[-1].close)
            previous_body_low = min(float(selected_day.iloc[0].open),primary_price)
            selection_rows.append(dict(date=date,code=primary_code,factor=float(selected.factor),candidate_count=int(available.loc[available.code.ne(defensive_code)].shape[0]),reason='selected'))
            if defensive_code in positions:
                sell(defensive_code, date, defensive_price,
                     "amv_buy_signal_rotate_back", time, source_date)
            if primary_code not in positions:
                buy(primary_code, date, primary_price, "amv_buy_signal", time,
                    source_date, str(signal.get("entry_branch", "")))
            if primary_code in positions:
                bank_take_profit_locked = False

    for session_index, date in enumerate(dates):
        if primary_code in positions and date not in sessions[primary_code]:
            raise ValueError(f'持仓行情缺失: {primary_code} {date.date()}')
        if primary_code not in positions:
            primary_code = PRIMARY
        day_primary = sessions[primary_code][date].sort_values("date")
        day_defensive = sessions[defensive_code][date].sort_values("date")
        primary_close = float(day_primary.iloc[-1]["close"])
        defensive_close = float(day_defensive.iloc[-1]["close"])
        daily_open = float(day_primary.iloc[0]["open"])
        daily_high = float(day_primary["high"].max())
        if (defensive_code == DEFENSIVE_ETF and defensive_code in positions
                and not positions[defensive_code]["defensive_split_applied"]
                and date >= DEFENSIVE_ETF_SPLIT_DATE):
            positions[defensive_code]["quantity"] *= 2
            positions[defensive_code]["defensive_split_applied"] = True
        if defensive_code in positions and date in dividend_map:
            amount = positions[defensive_code]["quantity"] * dividend_map[date]
            cash += amount
            dividend_total += amount
            positions[defensive_code]["dividend_income"] += amount

        if primary_code in positions:
            held = positions[primary_code]
            if (primary_code == PRIMARY and not held["consolidation_applied"] and held["entry_date"] < CONSOLIDATION_DATE
                    and date >= CONSOLIDATION_DATE):
                held["quantity"] = math.ceil(held["quantity"] * CONSOLIDATION_RATIO)
                held["reference_price"] /= CONSOLIDATION_RATIO
                held["consolidation_applied"] = True
                if previous_body_low is not None:
                    previous_body_low /= CONSOLIDATION_RATIO

        intraday_exit = ""
        if primary_code in positions and positions[primary_code]["entry_date"] < date:
            held = positions[primary_code]
            is_weak = tight_weak and held.get('mode')=='weak'
            stop_level = held['weak_stop_price'] if is_weak else held['reference_price']*.975
            profit_level = held['weak_profit_price'] if is_weak else None
            trail_level = previous_body_low if (not is_weak and held['profit_armed']) else None
            for bar in day_primary.to_dict('records'):
                op,low,high = float(bar['open']),float(bar['low']),float(bar['high'])
                price = None
                if is_weak:
                    if op<=stop_level: price,intraday_exit=op,'weak_net_stop'
                    elif op>=profit_level: price,intraday_exit=op,'weak_net_take_profit'
                    elif low<=stop_level: price,intraday_exit=stop_level,'weak_net_stop'
                    elif high>=profit_level: price,intraday_exit=profit_level,'weak_net_take_profit'
                else:
                    if op<stop_level: price,intraday_exit=op,'hard_stop_2.5pct'
                    elif trail_level is not None and op<trail_level: price,intraday_exit=op,'profit_trail_body_break_5pct'
                    elif trail_level is not None and low<trail_level: price,intraday_exit=trail_level,'profit_trail_body_break_5pct'
                    elif low<stop_level: price,intraday_exit=stop_level,'hard_stop_2.5pct'
                if price is not None:
                    sell(primary_code,date,price,intraday_exit,pd.Timestamp(bar['date']).strftime('%H:%M'))
                    break

        if (defensive_code in STOCK_BANK_CODES and defensive_code in positions
                and positions[defensive_code]["entry_date"] < date):
            take_profit_price = positions[defensive_code]["take_profit_price"]
            for bar in day_defensive.to_dict("records"):
                open_price, high_price = float(bar["open"]), float(bar["high"])
                if open_price >= take_profit_price or high_price >= take_profit_price:
                    fill_price = open_price if open_price >= take_profit_price else take_profit_price
                    sell(defensive_code, date, fill_price, "bank_take_profit_8pct",
                         pd.Timestamp(bar["date"]).strftime("%H:%M"))
                    bank_take_profit_locked = True
                    break

        signal = signal_map.loc[date]
        if intraday_exit:
            signal = signal.copy()
            signal["buy_signal"] = False
        before_buys=len(selection_rows)
        before_upgrades=len(upgrade_rows)
        execute_signal(signal,date,primary_close,defensive_close,'15:00')
        timed_exit=False
        if (tight_weak and primary_code in positions and positions[primary_code].get('mode')=='weak'
                and session_index-positions[primary_code]['entry_session_index']>=max_hold_sessions):
            sell(primary_code,date,primary_close,'weak_time_exit')
            timed_exit=True
        if bool(signal.high_signal) or (weak_enabled and bool(signal.weak_signal)):
            action=('amv_exit_priority' if bool(signal.exit_ma10) or bool(signal.exit_macd)
                else 'blocked_exit_today' if intraday_exit or timed_exit
                else 'upgraded' if len(upgrade_rows)>before_upgrades
                else 'opened' if len(selection_rows)>before_buys and selection_rows[-1]['reason']=='selected'
                else 'no_candidate' if len(selection_rows)>before_buys
                else 'already_holding')
            signal_rows.append(dict(date=date,high_signal=bool(signal.high_signal),
                weak_signal=bool(signal.weak_signal),action=action))

        if (primary_code in positions and positions[primary_code]["entry_date"] < date
                and (not tight_weak or positions[primary_code].get('mode')=='strong')
                and (not tight_weak or positions[primary_code].get('upgrade_date')!=date.strftime('%Y%m%d'))):
            if daily_high > positions[primary_code]["reference_price"] * 1.05:
                positions[primary_code]["profit_armed"] = True
        if primary_code in positions:
            selected_day = sessions[primary_code][date].sort_values('date')
            primary_close = float(selected_day.iloc[-1].close)
            daily_open = float(selected_day.iloc[0].open)
        nav_rows.append({
            "date": date, "nav": cash + sum(
                held["quantity"] * (primary_close if code == primary_code else defensive_close)
                for code, held in positions.items()),
            "cash": cash, "dividend_income": dividend_total,
            "primary_quantity": positions.get(primary_code, {}).get("quantity", 0),
            "defensive_quantity": positions.get(defensive_code, {}).get("quantity", 0),
            "invested": bool(positions),
            "primary_code": primary_code if primary_code in positions else "",
            "position_mode": positions.get(primary_code,{}).get('mode','defense' if defensive_code in positions else 'cash'),
        })
        previous_body_low = min(daily_open, primary_close)

    return BranchResult(pd.DataFrame(nav_rows), pd.DataFrame(trade_rows),
                         {code: held["quantity"] for code, held in positions.items()},
                         pd.DataFrame(selection_rows,columns=['date','code','factor','candidate_count','reason']),
                         pd.DataFrame(upgrade_rows,columns=['date','code','entry_date','reference_price','buy_cost','quantity']),
                         pd.DataFrame(signal_rows,columns=['date','high_signal','weak_signal','action']))




def run(request: RunRequest, *, minimum_weak_return: float | None = None, extra_code_sources=()) -> Path:
    settings=yaml.safe_load(request.config_path.read_text())
    paths={k:Path(v) if Path(v).is_absolute() else ROOT/v for k,v in settings['paths'].items()}
    initial_cash=float(settings.get('initial_cash',200000))
    if not math.isfinite(initial_cash) or initial_cash<=0:raise ValueError('初始资金必须有限且大于0')
    start,end=pd.Timestamp(request.start_date),pd.Timestamp(request.end_date)
    cutoff=str(settings.get('pool_cutoff','20251231'))
    if start>end or end>pd.Timestamp(cutoff):raise ValueError('请求日期无效或超过固定股票池截止日')
    output=request.output_dir;output.mkdir(parents=True,exist_ok=True)
    raw_amv=pd.read_csv(paths['amv_csv'])
    signals=generate_signals(raw_amv)
    primary=_normalize_intraday(pd.read_csv(paths['primary_csv']))
    defense=_normalize_intraday(pd.read_csv(paths['defensive_etf_csv']))
    shared=set(signals.date) & set(primary.date.dt.normalize())
    shared={d for d in shared if start<=d<=end}
    missing_etf=sorted(shared-set(defense.date.dt.normalize()))
    shared &= set(defense.date.dt.normalize())
    bank=load_stock_bars(paths['stock_5m_dir'],shared)
    missing_bank=sorted(shared-set(bank.date.dt.normalize()))
    shared &= set(bank.date.dt.normalize())
    if not shared:raise ValueError('没有基准共同交易日')
    scoped_signals=signals.loc[signals.date.isin(shared)].reset_index(drop=True)
    filtered_signals=filter_weak_signals(scoped_signals,minimum_weak_return)
    primary=primary.loc[primary.date.dt.normalize().isin(shared)].reset_index(drop=True)
    defense=defense.loc[defense.date.dt.normalize().isin(shared)].reset_index(drop=True)
    bank=bank.loc[bank.date.dt.normalize().isin(shared)].reset_index(drop=True)
    dividends=load_dividend_events(paths['stock_dividends_csv'])
    etf_fees=request.fees
    stock_fees=FeeConfig.stock_legacy().with_overrides(commission_rate=etf_fees.commission_rate,
                    min_commission=etf_fees.min_commission,slippage_rate=etf_fees.slippage_rate)
    results={}
    baseline_signals=scoped_signals.copy()
    baseline_signals['buy_signal']=baseline_signals.high_signal
    baseline_signals=baseline_signals.drop(columns=['entry_branch'])
    weak_settings=settings.get('weak_exit',{})
    max_hold=int(weak_settings.get('max_hold_sessions',3))
    tier_settings=weak_settings.get('tiers')
    tiers=(tuple((math.inf if t['upper'] is None else float(t['upper']),float(t['stop']),float(t['profit']))
                 for t in tier_settings) if tier_settings is not None else DEFAULT_TIERS)
    weak_exit_parameters(0.,tiers)
    amv=signals.loc[signals.date.le(pd.Timestamp(cutoff))].set_index('date').close
    ranked,all_bars,audit=build_rankings(paths['etf_dir'],amv,output,
        window=int(settings.get('window',60)),jump_threshold=float(settings.get('jump_threshold',.25)),pool_cutoff=cutoff)
    ranked=ranked.loc[ranked.date.isin(shared)].reset_index(drop=True)
    ranked.to_parquet(output/'rankings.parquet',index=False)
    # Baseline instrument is available for the calendar and fixed-primary regression,
    # but an excluded 512100 is never added back to the candidate rankings.
    all_bars={code:frame.loc[frame.date.dt.normalize().isin(shared)].reset_index(drop=True)
              for code,frame in all_bars.items()}
    all_bars[PRIMARY]=primary
    for code,dbars,dfees,div in [(DEFENSIVE_ETF,defense,etf_fees,{}),(DEFENSIVE_STOCK,bank,stock_fees,dividends)]:
        print(f'Running three entry/exit variants with defense {code}',flush=True)
        results[f'baseline_{code}']=run_dynamic_backtest(all_bars,dbars,baseline_signals,code,ranked,
                                                       initial_cash,etf_fees,dfees,div)
        if minimum_weak_return is None:
            results[f'control_{code}']=run_branch_backtest(all_bars,dbars,scoped_signals,code,ranked,
                initial_cash,etf_fees,dfees,div,tight_weak=False,max_hold_sessions=max_hold,tiers=tiers)
        else:
            results[f'filtered_{code}']=run_branch_backtest(all_bars,dbars,filtered_signals,code,ranked,
                initial_cash,etf_fees,dfees,div,tight_weak=True,max_hold_sessions=max_hold,tiers=tiers)
        results[f'ma5_{code}']=run_branch_backtest(all_bars,dbars,scoped_signals,code,ranked,
            initial_cash,etf_fees,dfees,div,tight_weak=True,max_hold_sessions=max_hold,tiers=tiers)
    metrics=dict(start_date=min(shared).strftime('%Y%m%d'),end_date=max(shared).strftime('%Y%m%d'),
        shared_sessions=len(shared),initial_cash=initial_cash,fixed_pool_count=int(audit.status.eq('eligible').sum()),
        local_etf_files=len(audit),excluded_etf_sessions=[str(d.date()) for d in missing_etf],
        excluded_stock_sessions=[str(d.date()) for d in missing_bank],
        fees=dict(etf=asdict(etf_fees),stock=asdict(stock_fees)),execution_mode='legacy_same_close_idealized',
        pool_lookahead=True,pool_cutoff=cutoff,jump_threshold=.25,window=60,variants={})
    metrics['minimum_weak_return']=minimum_weak_return
    combined=pd.DataFrame(dict(date=scoped_signals.date))
    annual_rows=[]
    branch_rows=[]
    exit_rows=[]
    for name,result in results.items():
        target=output/name;target.mkdir(exist_ok=True)
        nav=result.nav.copy()
        nav['return_pct']=(nav.nav/initial_cash-1)*100
        nav['drawdown_pct']=(nav.nav/nav.nav.cummax().clip(lower=initial_cash)-1)*100
        if 'primary_code' not in nav:nav['primary_code']=np.where(nav.primary_quantity.gt(0),PRIMARY,'')
        defense_code=name.split('_',1)[1]
        nav['position_code']=np.where(nav.primary_quantity.gt(0),nav.primary_code,np.where(nav.defensive_quantity.gt(0),defense_code,'cash'))
        nav.to_csv(target/'nav.csv',index=False)
        result.trades.to_csv(target/'trades.csv',index=False)
        pairs=paired_trades(result.trades,etf_fees,stock_fees)
        sells=result.trades.loc[result.trades.side.eq('sell')] if not result.trades.empty else result.trades
        pairs['entry_branch']=(sells.entry_branch.values if 'entry_branch' in sells else
                               np.where(pairs.code.eq(defense_code),'defense','high'))
        pairs['entry_branch']=pairs.entry_branch.replace('','defense').fillna('defense')
        pairs['exit_mode']=(sells.exit_mode.values if 'exit_mode' in sells else
                            np.where(pairs.code.eq(defense_code),'defense','strong'))
        pairs['upgrade_date']=sells.upgrade_date.values if 'upgrade_date' in sells else ''
        pairs.to_csv(target/'paired_trades.csv',index=False)
        for branch,frame in pairs.groupby('entry_branch'):
            branch_rows.append(dict(variant=name,entry_branch=branch,trades=len(frame),pnl=frame.pnl.sum(),
                mean_pnl_pct=frame.pnl_pct.mean(),win_rate_pct=frame.pnl.gt(0).mean()*100))
        for reason,frame in pairs.groupby('sell_reason') if 'sell_reason' in pairs else []:
            exit_rows.append(dict(variant=name,exit_reason=reason,trades=len(frame),pnl=frame.pnl.sum(),mean_pnl_pct=frame.pnl_pct.mean()))
        m=compute_performance_metrics(nav,pairs,initial_cash,bool(result.open_positions))
        m.update(buy_count=int(result.trades.side.eq('buy').sum()) if not result.trades.empty else 0,
                 primary_buy_count=int((result.trades.side.eq('buy') & result.trades.code.ne(defense_code)).sum()) if not result.trades.empty else 0,
                 open_positions=result.open_positions)
        commissions=taxes=slippage=notional=0.
        for trade in result.trades.to_dict('records'):
            fees=stock_fees if trade['code']==DEFENSIVE_STOCK else etf_fees
            gross=trade['quantity']*trade['exec_price']
            commissions+=max(fees.min_commission,gross*fees.commission_rate)
            taxes+=gross*(fees.transfer_fee_rate+(fees.stamp_duty_rate if trade['side']=='sell' else 0))
            slippage+=abs(trade['exec_price']-trade['signal_price'])*trade['quantity']
            notional+=gross
        m.update(commission_cash=commissions,tax_cash=taxes,slippage_estimate=slippage,
                 traded_notional_initial_cash_multiple=notional/initial_cash)
        if isinstance(result,BranchResult):
            result.upgrades.to_csv(target/'upgrades.csv',index=False)
            result.signal_audit.to_csv(target/'signal_audit.csv',index=False)
            m['upgrade_count']=len(result.upgrades)
            m['high_signal_blocked_exit_today']=int((result.signal_audit.high_signal & result.signal_audit.action.eq('blocked_exit_today')).sum())
            buys=result.trades.loc[result.trades.side.eq('buy')] if not result.trades.empty else result.trades
            m['weak_buy_count']=int(buys.entry_branch.eq('weak').sum()) if 'entry_branch' in buys else 0
            m['high_buy_count']=int(buys.entry_branch.eq('high').sum()) if 'entry_branch' in buys else 0
        metrics['variants'][name]=m
        (target/'metrics.json').write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n')
        if isinstance(result,DynamicResult):result.selections.to_csv(target/'selections.csv',index=False)
        combined[f'{name}_nav']=nav.nav.values
        previous=initial_cash
        for year,year_nav in nav.groupby(nav.date.dt.year,sort=True):
            final=float(year_nav.nav.iloc[-1])
            annual_rows.append(dict(variant=name,year=int(year),return_pct=(final/previous-1)*100))
            previous=final
    combined.to_csv(output/'nav.csv',index=False)
    annual=pd.DataFrame(annual_rows);annual.to_csv(output/'annual_returns.csv',index=False)
    pd.DataFrame(branch_rows).to_csv(output/'branch_statistics.csv',index=False)
    pd.DataFrame(exit_rows).to_csv(output/'exit_statistics.csv',index=False)
    scoped_signals.to_csv(output/'amv_signals.csv',index=False)
    if minimum_weak_return is not None:
        filtered_signals.to_csv(output/'filtered_amv_signals.csv',index=False)
    (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    snapshot=output/'inputs';snapshot.mkdir(exist_ok=True)
    for name,frame in [('primary',primary),('defensive_etf',defense),('bank',bank)]:frame.to_csv(snapshot/f'{name}_bars.csv',index=False)
    for key in ['amv_csv','stock_dividends_csv']:shutil.copy2(paths[key],snapshot/paths[key].name)
    small_hashes={k:sha256(v) for k,v in paths.items() if v.is_file()}
    code_sources=[Path(__file__),ROOT/'python/factors/amv_ma5_entry.py',
        ROOT/'python/strategies/amv_winning_defensive_corr60/runner.py',ROOT/'python/factors/amv_correlation.py',
        ROOT/'python/research/etf/amv_entry_corr60/data.py',ROOT/'python/research/etf/amv_entry_corr60/local_screen.py',
        ROOT/'python/strategies/amv_winning_defensive/runner.py',ROOT/'python/strategies/amv_winning/runner.py',
        ROOT/'python/backtest/broker.py',ROOT/'python/task_registry.py',ROOT/'python/run_backtest.py']
    code_sources.extend(extra_code_sources)
    hashes={}
    for path in code_sources:
        target=output/'code_snapshot'/path.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target);hashes[str(path.relative_to(ROOT))]=sha256(path)
    (output/'code_snapshot/manifest.json').write_text(json.dumps(dict(sha256=hashes),indent=2)+'\n')
    (output/'input_audit.json').write_text(json.dumps(dict(source_hashes=small_hashes,
        snapshots={f.name:sha256(f) for f in snapshot.iterdir()},pool_audit='pool_audit.csv',
        pool_cutoff=cutoff,pool_lookahead=True,config_sha256=sha256(request.config_path)),ensure_ascii=False,indent=2)+'\n')
    comparison=[]
    for name,m in metrics['variants'].items():
        comparison.append(dict(variant=name,total_return_pct=m['total_return_pct'],annualized_return_pct=m['annualized_return_pct'],
            max_drawdown_pct=m['max_drawdown_pct'],primary_buy_count=m['primary_buy_count'],
            closed_trade_count=m['closed_trade_count'],win_rate_pct=m['win_rate_pct']))
    table=pd.DataFrame(comparison);table.to_csv(output/'comparison.csv',index=False)
    report=['# 0AMV动态进攻：MA5上穿与分档净收益退出','',
        f'区间：{metrics["start_date"]}—{metrics["end_date"]}；共同交易日{len(shared)}；固定候选池{metrics["fixed_pool_count"]}/{len(audit)}只。','',
        '**探索性回测：固定ETF池按截至2025-12-31完整历史剔除25%疑似断点，使用了未来信息，存在前视偏差。**',
        '**同日收盘信号、相关性和成交属于legacy_same_close_idealized理想化口径。**','',
        '## 同期对照','',table.round(3).to_markdown(index=False),'',
        '## 年度收益','',annual.pivot(index="year",columns="variant",values="return_pct").round(3).to_markdown(),'',
        '## 规则与限制','',
        '- 仅实际开进攻仓时选择截至当日的最高corr60，不取绝对值；持仓不因排名变化换仓。重新开仓时重新排序。',
        ('- baseline只开原高质量信号；control增加MA5严格上穿，但均用原退出；ma5对弱仓增加分档净止盈止损和时间退出。高质量原条件保留。' if minimum_weak_return is None else f'- baseline只开原高质量信号；ma5为无涨幅门槛现版；filtered仅增加弱入场当日涨幅≥{minimum_weak_return:.1%}门槛，使用与ma5相同退出。均满仓。'),
        '- 弱仓原ETF升级强仓不产生交易，不重置真实成本。盘中退出优先于收盘升级，AMV退出优先于升级，升级优先于时间退出。',
        f'- 弱仓持有上限为买入后第{max_hold}个共同交易日；分档为{tiers}，分别是涨幅上限、净止损比例、净止盈比例。分档按开仓日冻结。',
        '- 同根60分钟K线先处理跳空开盘；未跳空且同时触及止盈止损时止损优先。弱仓退出当日禁止重开。',
        '- 因子要求60对完整市场日收益；名称代理去重、最早有效行情选代表，非官方指数映射及上市日。',
        '- 没有有效候选则保持当前防守或现金。持仓行情缺失报错，不能删交易日或按未来行情换标的。',
        '- ETF未取得完整复权与现金分红；原始价格收益可能残留25%以下除权变化。已知基准512100合并、512890拆分及农行分红保留原记账。',
        '- 保留原费用和同日收盘理想化成交，买入日不做盘中卖出。未模拟盘口容量、涨跌停和停牌成交约束。',
        '- 候选池事后筛选与同日收盘成交均可能夸大可实现表现；本结果不属于严格无前视实盘验证。','',
        '逐版本目录保存NAV、逐笔/配对交易、绩效和选股记录；固定池和排除原因见fixed_etf_pool.csv、pool_audit.csv。','']
    if minimum_weak_return is not None:
        report += ['',f'本次baseline为原高质量信号；ma5为无涨幅门槛现版；filtered为弱信号当日涨幅≥{minimum_weak_return:.1%}的满仓新版。filtered与ma5使用相同紧退出，未延迟补买被过滤的上穿信号。','']
    report += ['', '## 入场分支平仓贡献', '',pd.DataFrame(branch_rows).round(3).to_markdown(index=False),'']
    for code in [DEFENSIVE_ETF,DEFENSIVE_STOCK]:
        old=metrics['variants'][f'baseline_{code}'];new=metrics['variants'][f'ma5_{code}' if minimum_weak_return is None else f'filtered_{code}']
        report.append(f'{code}：总收益变化{new["total_return_pct"]-old["total_return_pct"]:+.3f}个百分点；最大回撤绝对值变化{abs(new["max_drawdown_pct"])-abs(old["max_drawdown_pct"]):+.3f}个百分点。')
    (output/'report.md').write_text('\n'.join(report)+'\n')
    return output
