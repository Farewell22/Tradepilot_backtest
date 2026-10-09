"""Top corr60 primary selection with the original defensive execution rules."""
from __future__ import annotations
from dataclasses import dataclass, asdict
import json
import math
import shutil
from pathlib import Path
import numpy as np
import pandas as pd
import yaml
from python.backtest.broker import FeeConfig, calc_buy_cost, calc_sell_proceeds
from python.factors.amv_correlation import rolling_amv_correlation
from python.research.etf.amv_entry_corr60.data import aggregate_daily, select_representatives, sha256
from python.research.etf.amv_entry_corr60.local_screen import screen_prices, name_group
from python.strategies.amv_winning.runner import (
    CONSOLIDATION_DATE, CONSOLIDATION_RATIO, STOCK_BANK_CODES, PRIMARY,
    _normalize_intraday, generate_amv_signals, compute_performance_metrics,
)
from python.strategies.amv_winning_defensive.runner import (
    DEFENSIVE_ETF, DEFENSIVE_STOCK, DEFENSIVE_ETF_SPLIT_DATE,
    _quantity, _bank_take_profit_price, load_stock_bars, load_dividend_events,
    run_defensive_backtest,
)
from python.run_backtest import ROOT, RunRequest

@dataclass
class DynamicResult:
    nav: pd.DataFrame
    trades: pd.DataFrame
    open_positions: dict[str,int]
    selections: pd.DataFrame


class SessionBars:
    """Index available dates cheaply; materialize bars only when a day is used."""
    def __init__(self, frame):
        self.frame = frame
        self.indices = frame.groupby(frame.date.dt.normalize()).indices

    def __iter__(self):
        return iter(self.indices)

    def __contains__(self, date):
        return date in self.indices

    def __getitem__(self, date):
        return self.frame.iloc[self.indices[date]]


def choose_candidate(rankings, date, defensive_code):
    rows=rankings.loc[rankings.date.eq(date) & rankings.code.ne(defensive_code) & np.isfinite(rankings.factor)]
    if rows.empty: return None
    return rows.sort_values(['factor','code'],ascending=[False,True],kind='stable').iloc[0]


def build_rankings(etf_dir, amv, output_dir, *, window=60, jump_threshold=.25, pool_cutoff='20251231'):
    """Pool uses the full cutoff history (lookahead); ranking uses only trailing data."""
    if window!=60 or jump_threshold!=.25 or str(pool_cutoff)!='20251231':
        raise ValueError('本策略固定60日、25%断点规则与20251231股票池截止日')
    rows,audit,bars_by_code=[],[],{}
    for number,path in enumerate(sorted(Path(etf_dir).glob('*.csv')),1):
        record=dict(code=path.stem,raw_path=str(path.resolve()),raw_sha256=sha256(path),status='excluded',reason='')
        try:
            raw=pd.read_csv(path,dtype={'代码':str})
            if '代码' in raw and not raw['代码'].eq(path.stem).all():raise ValueError('文件名与行情代码不一致')
            daily,qa=aggregate_daily(raw)
            daily=daily.loc[daily.date.le(pd.Timestamp(pool_cutoff))].copy()
            clean,jumps=screen_prices(daily,jump_threshold)
            record.update(qa,suspected_breaks=len(jumps))
            if not jumps.empty:
                record['reason']='full_history_suspected_price_break'
            elif not clean.valid.any():record['reason']='no_valid_daily_quotes'
            else:
                factor=rolling_amv_correlation(clean.set_index('date').close,amv,window)
                frame=pd.DataFrame(dict(date=amv.index,factor=factor.values,code=path.stem))
                names=pd.Series(raw['名称'].values,index=pd.to_datetime(raw['时间']).dt.normalize()).groupby(level=0).last().sort_index()
                frame['name']=frame.date.map(names.reindex(names.index.union(amv.index)).ffill())
                frame['index_id']=frame.name.fillna(path.stem).map(name_group)
                frame['first_quote_date']=clean.loc[clean.valid,'date'].min()
                rows.append(frame)
                valid_dates=set(clean.loc[clean.valid,'date'])
                raw=raw.drop_duplicates()
                raw=raw.loc[pd.to_datetime(raw['时间']).dt.normalize().isin(valid_dates)]
                bars=_normalize_intraday(raw)
                bars_by_code[path.stem]=bars.loc[bars.date.dt.normalize().isin(valid_dates)]
                record.update(status='eligible',first_quote_date=str(frame.first_quote_date.iloc[0].date()),name=str(names.iloc[-1]))
        except (ValueError,KeyError,OSError,IndexError) as error:record['reason']=f'{type(error).__name__}: {error}'
        audit.append(record)
        if number%100==0:print(f'Fixed-pool corr60 preparation {number}',flush=True)
    audit=pd.DataFrame(audit)
    audit.to_csv(output_dir/'pool_audit.csv',index=False)
    audit.loc[audit.status.eq('eligible')].to_csv(output_dir/'fixed_etf_pool.csv',index=False)
    if not rows:raise ValueError('无有效固定ETF池')
    selected,dedup=select_representatives(pd.concat(rows,ignore_index=True),date_column='first_quote_date')
    selected.to_parquet(output_dir/'rankings.parquet',index=False)
    dedup.to_parquet(output_dir/'dedup_audit.parquet',index=False)
    return selected,bars_by_code,audit


def run_dynamic_backtest(
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
) -> DynamicResult:
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
    defensive = _normalize_intraday(defensive_bars)
    signals = amv_signals.copy()
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
        if code in STOCK_BANK_CODES:
            positions[code]["take_profit_price"] = _bank_take_profit_price(quantity, cost, fees)
        trade_rows.append({
            "date": date.strftime("%Y%m%d"), "time": time, "code": code,
            "side": "buy", "quantity": quantity, "signal_price": price,
            "exec_price": exec_price, "cash_flow": -cost, "reason": reason,
        })
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
            stop_level = held["reference_price"] * 0.975
            trail_level = previous_body_low if held["profit_armed"] else None
            for bar in day_primary.to_dict("records"):
                open_price, low_price = float(bar["open"]), float(bar["low"])
                price: float | None = None
                if open_price < stop_level:
                    price, intraday_exit = open_price, "hard_stop_2.5pct"
                elif trail_level is not None and open_price < trail_level:
                    price, intraday_exit = open_price, "profit_trail_body_break_5pct"
                elif trail_level is not None and low_price < trail_level:
                    price, intraday_exit = trail_level, "profit_trail_body_break_5pct"
                elif low_price < stop_level:
                    price, intraday_exit = stop_level, "hard_stop_2.5pct"
                if price is not None:
                    sell(primary_code, date, price, intraday_exit,
                         pd.Timestamp(bar["date"]).strftime("%H:%M"))
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
        execute_signal(signal, date, primary_close, defensive_close, "15:00")

        if primary_code in positions and positions[primary_code]["entry_date"] < date:
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
        })
        previous_body_low = min(daily_open, primary_close)

    return DynamicResult(pd.DataFrame(nav_rows), pd.DataFrame(trade_rows),
                         {code: held["quantity"] for code, held in positions.items()},
                         pd.DataFrame(selection_rows, columns=["date","code","factor","candidate_count","reason"]))



def paired_trades(events, etf_fees, stock_fees):
    held,rows={},[]
    for row in events.to_dict('records'):
        if row['side']=='buy':
            held[row['code']]=row
            continue
        buy=held.pop(row['code'])
        fees=stock_fees if row['code']==DEFENSIVE_STOCK else etf_fees
        rows.append(dict(code=row['code'],buy_date=buy['date'],buy_time=buy['time'],
            sell_date=row['date'],sell_time=row['time'],buy_quantity=buy['quantity'],sell_quantity=row['quantity'],
            buy_exec_price=buy['exec_price'],sell_exec_price=row['exec_price'],
            buy_cost=-buy['cash_flow'],sell_proceeds=row['cash_flow'],
            buy_commission=max(fees.min_commission,buy['exec_price']*buy['quantity']*fees.commission_rate),
            sell_commission=max(fees.min_commission,row['exec_price']*row['quantity']*fees.commission_rate),
            sell_stamp_duty=row['exec_price']*row['quantity']*fees.stamp_duty_rate,
            sell_transfer_fee=row['exec_price']*row['quantity']*fees.transfer_fee_rate,
            buy_reason=buy['reason'],sell_reason=row['reason'],pnl=row['pnl'],pnl_pct=row['pnl_pct'],
            dividend_income=row['dividend_income'],hold_sessions=row['hold_sessions']))
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['code','buy_date','sell_date','pnl','pnl_pct','hold_sessions'])


def run(request: RunRequest) -> Path:
    settings=yaml.safe_load(request.config_path.read_text())
    paths={k:Path(v) if Path(v).is_absolute() else ROOT/v for k,v in settings['paths'].items()}
    initial_cash=float(settings.get('initial_cash',200000))
    if not math.isfinite(initial_cash) or initial_cash<=0:raise ValueError('初始资金必须有限且大于0')
    start,end=pd.Timestamp(request.start_date),pd.Timestamp(request.end_date)
    cutoff=str(settings.get('pool_cutoff','20251231'))
    if start>end or end>pd.Timestamp(cutoff):raise ValueError('请求日期无效或超过固定股票池截止日')
    output=request.output_dir;output.mkdir(parents=True,exist_ok=True)
    raw_amv=pd.read_csv(paths['amv_csv'])
    signals=generate_amv_signals(raw_amv)
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
    primary=primary.loc[primary.date.dt.normalize().isin(shared)].reset_index(drop=True)
    defense=defense.loc[defense.date.dt.normalize().isin(shared)].reset_index(drop=True)
    bank=bank.loc[bank.date.dt.normalize().isin(shared)].reset_index(drop=True)
    dividends=load_dividend_events(paths['stock_dividends_csv'])
    etf_fees=request.fees
    stock_fees=FeeConfig.stock_legacy().with_overrides(commission_rate=etf_fees.commission_rate,
                    min_commission=etf_fees.min_commission,slippage_rate=etf_fees.slippage_rate)
    # Save baseline before preparing any candidate data.
    results={}
    for code,dbars,dfees,div in [(DEFENSIVE_ETF,defense,etf_fees,{}),(DEFENSIVE_STOCK,bank,stock_fees,dividends)]:
        results[f'baseline_{code}']=run_defensive_backtest(primary,dbars,scoped_signals,code,initial_cash,etf_fees,dfees,div)
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
        results[f'corr60_{code}']=run_dynamic_backtest(all_bars,dbars,scoped_signals,code,ranked,
                                                     initial_cash,etf_fees,dfees,div)
    metrics=dict(start_date=min(shared).strftime('%Y%m%d'),end_date=max(shared).strftime('%Y%m%d'),
        shared_sessions=len(shared),initial_cash=initial_cash,fixed_pool_count=int(audit.status.eq('eligible').sum()),
        local_etf_files=len(audit),excluded_etf_sessions=[str(d.date()) for d in missing_etf],
        excluded_stock_sessions=[str(d.date()) for d in missing_bank],
        fees=dict(etf=asdict(etf_fees),stock=asdict(stock_fees)),execution_mode='legacy_same_close_idealized',
        pool_lookahead=True,pool_cutoff=cutoff,jump_threshold=.25,window=60,variants={})
    combined=pd.DataFrame(dict(date=scoped_signals.date))
    annual_rows=[]
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
        pairs.to_csv(target/'paired_trades.csv',index=False)
        m=compute_performance_metrics(nav,pairs,initial_cash,bool(result.open_positions))
        m.update(buy_count=int(result.trades.side.eq('buy').sum()) if not result.trades.empty else 0,
                 primary_buy_count=int((result.trades.side.eq('buy') & result.trades.code.ne(defense_code)).sum()) if not result.trades.empty else 0,
                 open_positions=result.open_positions)
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
    scoped_signals.to_csv(output/'amv_signals.csv',index=False)
    (output/'metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2)+'\n')
    snapshot=output/'inputs';snapshot.mkdir(exist_ok=True)
    for name,frame in [('primary',primary),('defensive_etf',defense),('bank',bank)]:frame.to_csv(snapshot/f'{name}_bars.csv',index=False)
    for key in ['amv_csv','stock_dividends_csv']:shutil.copy2(paths[key],snapshot/paths[key].name)
    small_hashes={k:sha256(v) for k,v in paths.items() if v.is_file()}
    code_sources=[Path(__file__),ROOT/'python/factors/amv_correlation.py',
        ROOT/'python/research/etf/amv_entry_corr60/data.py',ROOT/'python/research/etf/amv_entry_corr60/local_screen.py',
        ROOT/'python/strategies/amv_winning_defensive/runner.py',ROOT/'python/strategies/amv_winning/runner.py',
        ROOT/'python/backtest/broker.py',ROOT/'python/task_registry.py',ROOT/'python/run_backtest.py']
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
    report=['# 0AMV防守策略：进攻仓60日相关性第一名','',
        f'区间：{metrics["start_date"]}—{metrics["end_date"]}；共同交易日{len(shared)}；固定候选池{metrics["fixed_pool_count"]}/{len(audit)}只。','',
        '**探索性回测：固定ETF池按截至2025-12-31完整历史剔除25%疑似断点，使用了未来信息，存在前视偏差。**',
        '**同日收盘信号、相关性和成交属于legacy_same_close_idealized理想化口径。**','',
        '## 同期对照','',table.round(3).to_markdown(index=False),'',
        '## 年度收益','',annual.pivot(index="year",columns="variant",values="return_pct").round(3).to_markdown(),'',
        '## 规则与限制','',
        '- 仅实际开进攻仓时选择截至当日的最高corr60，不取绝对值；持仓不因排名变化换仓。重新开仓时重新排序。',
        '- 原策略入场、MA10/MACD退出、2.5%硬止损、超过5%后的跟踪止盈、满仓和防守规则保留。新开仓日可因ETF止损不同而变化。',
        '- 因子要求60对完整市场日收益；名称代理去重、最早有效行情选代表，非官方指数映射及上市日。',
        '- 没有有效候选则保持当前防守或现金。持仓行情缺失报错，不能删交易日或按未来行情换标的。',
        '- ETF未取得完整复权与现金分红；原始价格收益可能残留25%以下除权变化。已知基准512100合并、512890拆分及农行分红保留原记账。',
        '- 保留原费用和同日收盘理想化成交，买入日不做盘中卖出。未模拟盘口容量、涨跌停和停牌成交约束。',
        '- 候选池事后筛选与同日收盘成交均可能夸大可实现表现；本结果不属于严格无前视实盘验证。','',
        '逐版本目录保存NAV、逐笔/配对交易、绩效和选股记录；固定池和排除原因见fixed_etf_pool.csv、pool_audit.csv。','']
    for code in [DEFENSIVE_ETF,DEFENSIVE_STOCK]:
        old=metrics['variants'][f'baseline_{code}'];new=metrics['variants'][f'corr60_{code}']
        report.append(f'{code}：总收益变化{new["total_return_pct"]-old["total_return_pct"]:+.3f}个百分点；最大回撤绝对值变化{abs(new["max_drawdown_pct"])-abs(old["max_drawdown_pct"]):+.3f}个百分点。')
    (output/'report.md').write_text('\n'.join(report)+'\n')
    return output
