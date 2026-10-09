"""Run the two existing AMV bank variants on one bank and primary calendar."""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.factors.z_indicators import compute_dynamic_weekly_kdj
from python.run_backtest import ROOT, RunRequest
from python.strategies.amv_winning import runner as weekly
from python.strategies.amv_winning.bank_stock import (
    AUDITED_END, HISTORY_START, load_stock_dividends, load_stock_history, snapshot_stock_inputs,
)
from python.strategies.amv_winning_defensive.runner import run_defensive_backtest


VARIANT_LABELS = {"direct": "0AMV 收盘离场直接买入", "weekly_j": "主仓卖出后周线 J<10 买入"}
RULES = {
    "direct": {
        "entry": "amv_close_exit", "weekly_j_threshold": None,
        "intraday_primary_exit": "cash_until_amv_close_exit",
        "primary_same_day_reentry_after_stop": False,
        "take_profit_basis": "8pct_net_price_pnl_excluding_dividends",
        "post_take_profit": "cash_until_effective_primary_entry",
    },
    "weekly_j": {
        "entry": "after_actual_primary_sale_and_dynamic_weekly_j_lt_10", "weekly_j_threshold": 10,
        "intraday_primary_exit": "enable_bank_observation",
        "primary_same_day_reentry_after_stop": True,
        "take_profit_basis": "execution_buy_price_times_1.08_rounded_up_to_cent",
        "post_take_profit": "bank_observation_from_next_session",
    },
}


def _write_json(path: Path, content: dict) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _paired_events(events: pd.DataFrame, primary_fees: FeeConfig, stock_fees: FeeConfig,
                   *, primary_code: str = weekly.PRIMARY) -> pd.DataFrame:
    """Expose closed trades for common metrics, keeping the original event ledger."""
    held = {}
    rows = []
    for row in events.to_dict("records"):
        if row["side"] == "buy":
            held[row["code"]] = row
            continue
        buy = held.pop(row["code"])
        fees = primary_fees if row["code"] == primary_code else stock_fees
        buy_gross, sell_gross = buy["exec_price"] * buy["quantity"], row["exec_price"] * row["quantity"]
        rows.append({
            "code": row["code"], "buy_date": buy["date"], "buy_time": buy["time"],
            "buy_signal_price": buy["signal_price"], "buy_exec_price": buy["exec_price"],
            "buy_quantity": buy["quantity"], "buy_cost": -buy["cash_flow"], "buy_reason": buy["reason"],
            "buy_commission": max(fees.min_commission, buy_gross * fees.commission_rate),
            "buy_transfer_fee": buy_gross * fees.transfer_fee_rate,
            "sell_date": row["date"], "sell_time": row["time"],
            "sell_signal_price": row["signal_price"], "sell_exec_price": row["exec_price"],
            "sell_quantity": row["quantity"], "sell_proceeds": row["cash_flow"],
            "sell_commission": max(fees.min_commission, sell_gross * fees.commission_rate),
            "sell_transfer_fee": sell_gross * fees.transfer_fee_rate,
            "sell_stamp_duty": sell_gross * fees.stamp_duty_rate,
            "sell_reason": row["reason"], "dividend_income": row["dividend_income"],
            "pnl": row["pnl"], "pnl_pct": row["pnl_pct"], "hold_sessions": row["hold_sessions"],
        })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
        "code", "buy_date", "sell_date", "buy_quantity", "sell_quantity", "buy_cost",
        "sell_proceeds", "sell_reason", "dividend_income", "pnl", "pnl_pct", "hold_sessions",
    ])


def _decorate_nav(nav: pd.DataFrame, initial_cash: float) -> pd.DataFrame:
    result = nav.copy()
    result["position_code"] = result.position_code.replace("", "cash").fillna("cash")
    result["return_pct"] = (result.nav / initial_cash - 1) * 100
    result["drawdown_pct"] = (result.nav / result.nav.cummax().clip(lower=initial_cash) - 1) * 100
    return result


def _metrics(nav, trades, initial_cash, open_position, bank_code, parameters):
    metrics = weekly.compute_performance_metrics(nav, trades, initial_cash, bool(open_position))
    metrics.update(
        bank_code=bank_code, sessions=len(nav), actual_start=nav.date.iloc[0].strftime("%Y%m%d"),
        actual_end=nav.date.iloc[-1].strftime("%Y%m%d"), open_position=open_position,
        dividend_income=float(nav.dividend_income.iloc[-1]), parameters=parameters,
    )
    return metrics


def _report(bank_name: str, bank_code: str, metrics: dict, annual: pd.DataFrame, fees: dict) -> str:
    lines = [
        f"# 0AMV 主仓与{bank_name}（{bank_code}）回测", "",
        f"实际区间 {metrics['actual_start']}—{metrics['actual_end']}，{metrics['sessions']} 个交易日；"
        f"初始 {metrics['initial_cash']:,.0f} 元。", "",
        "| 版本 | 期末资金（元） | 总收益 | 年化收益 | 最大回撤 | 夏普 | 已平仓交易 | 税前分红（元） |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, m in metrics["variants"].items():
        lines.append(f"| {VARIANT_LABELS[key]} | {m['final_nav']:,.2f} | {m['total_return_pct']:.2f}% | "
                     f"{m['annualized_return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | "
                     f"{m['sharpe_ratio']:.3f} | {m['closed_trade_count']} | {m['dividend_income']:,.2f} |")
    lines += ["", "## 年度收益（相对上年末净值；首年相对初始资金）", "",
              "| 年份 | 直接买入 | 周线 J<10 | 原主仓离场持现金 |", "|---|---:|---:|---:|"]
    for row in annual.to_dict("records"):
        lines.append(f"| {row['year']} | {row['direct_return_pct']:.2f}% | {row['weekly_j_return_pct']:.2f}% | "
                     f"{row['cash_return_pct']:.2f}% |")
    lines += ["", "## 规则与可比范围", "",
        "主仓 512100.SH：0AMV 单日/两日增长至少 4% 且不低于 MA5 进场；低于 MA10 或 MACD 死叉离场；"
        "盘中 2.5% 硬止损、上涨超过 5% 后次日起按前一日实体低点退出。银行无止损，"
        "有效主仓进场信号卖出全部银行并按原主仓规则买入，冲突日离场信号优先。", "",
        "直接版完全沿用 amv_winning_defensive：0AMV 收盘离场即买银行；主仓仅盘中止损后先持现金。"
        "银行扣交易费用后净价差达到 8% 止盈（分红不计入阈值），止盈后持现金至主仓实际进场。"
        "主仓盘中退出当日不重新进场。", "",
        "J 版完全沿用 amv_winning：实际卖出主仓才开启银行观察，现金且当日可见的动态周线 J 严格小于 10 才买；"
        "使用本股 2019 年以来的预热行情和截至当日的分红连续指标。银行成交买价上涨 8% 止盈，"
        "目标向上取整至分；止盈当日不能再买银行，次日可继续观察，主仓可盘中止损后当日按有效信号再进场。", "",
        "两版的差异沿用此前农行对照，因此差别并非只有 J 过滤。银行买卖使用未复权价格，"
        "分红按上一交易日持仓于除息日入账；2020—2025 两股 A 股派息日均为除息日。"
        "每次买入按可用现金买整手 100 股，剩余零头及股息现金不自动增持，银行当日买入次日才能卖出。", "",
        f"费用：主仓 `{json.dumps(fees['primary'], ensure_ascii=False)}`；"
        f"银行 `{json.dumps(fees['stock'], ensure_ascii=False)}`。", "",
        "成交口径为 legacy_same_close_idealized：收盘才能确认的信号按同日收盘成交；盘中用 OHLC 触价成交。"
        "保留旧固定印花税/过户费与税前股息，未模拟个人股息税、历史税率变更、停牌涨跌停成交及盘口容量。"
        "这是同口径比较结果，不能直接视为可实盘复制的收益。", "",
        "年化按实际起止日间隔和 365 天复利，夏普以日收益、无风险利率 0、243 个交易日计算；"
        "期末持仓按收盘价估值，不强制平仓。完整主仓交易日全部保留，数据缺口直接报错。", "",
        "## 输出与复现", "",
        "direct/ 与 weekly_j/ 各含 nav.csv、trades.csv、metrics.json、report.md；直接版另外保留 events.csv。"
        "根目录 nav.csv、trades.csv、metrics.json 的主结果为直接版；metrics.json.variants 包含两版完整绩效。"
        "另有 original_nav.csv、original_trades.csv、annual_returns.csv、bank_weekly_kdj.csv、inputs/、code_snapshot/"
        "及 source_manifest.json（SHA256）。统一命令另保存 run_manifest.json 的请求、配置与执行口径。", "",
    ]
    lines += ["分红来源："]
    if bank_code == "601939.SH":
        lines.append("[建设银行官方分红记录](https://accounts2.ccb.com/chn/home/investor/summary/fhqk/index.shtml)，"
                     "与 Tushare 已实施事件核对日期、每股税前金额及无送转。")
    elif bank_code == "600036.SH":
        lines.append("[招商银行官方分红记录](https://english.cmbchina.com/cmbir/intro.aspx?curchnl=Dividend&type=StockInfo)，"
                     "分红表逐行另列公司 A 股实施公告核对除息日及无送转。"
                     "2025 中期分红在 20260116 实施，区间内不提前入账。")
    lines.append("")
    return "\n".join(lines)


def run_comparison(amv_path: Path, primary_path: Path, stock_data_dir: Path, dividends_path: Path,
                   output_dir: Path, *, bank_code: str, bank_name: str,
                   start_date: str = "20200102", end_date: str = "20251231",
                   initial_cash: float = 200_000, fees: FeeConfig | None = None,
                   bank_fees: FeeConfig | None = None, task_id: str | None = None) -> dict:
    if bank_code not in weekly.STOCK_BANK_CODES:
        raise ValueError(f"不支持的银行股票: {bank_code}")
    if not np.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("初始资金必须为有限正数")
    start, end = pd.to_datetime(start_date, format="%Y%m%d"), pd.to_datetime(end_date, format="%Y%m%d")
    if start > end or start < HISTORY_START or end > AUDITED_END:
        raise ValueError("银行行情/分红核对区间为 20190101—20251231，开始日期不得晚于结束日期")
    fees = fees or FeeConfig.etf_legacy()
    bank_fees = bank_fees or FeeConfig.stock_legacy().with_overrides(
        commission_rate=fees.commission_rate, min_commission=fees.min_commission, slippage_rate=fees.slippage_rate,
    )
    primary = weekly._normalize_intraday(pd.read_csv(primary_path))
    primary = primary.loc[primary.date.dt.normalize().between(start, end)].reset_index(drop=True)
    if primary.empty:
        raise ValueError("请求区间没有主仓行情")
    dates = set(primary.date.dt.normalize())
    signals = weekly.generate_amv_signals(pd.read_csv(amv_path))
    stock_history, audit = load_stock_history(stock_data_dir, end, code=bank_code)
    for label, available in (("0AMV", set(signals.date)), (bank_name, set(stock_history.date.dt.normalize()))):
        missing = sorted(dates - available)
        if missing:
            raise ValueError(f"{label} 缺少主仓交易日: " + ", ".join(f"{date:%Y%m%d}" for date in missing[:10]))
    signals = signals.loc[signals.date.isin(dates)].reset_index(drop=True)
    stock = stock_history.loc[stock_history.date.dt.normalize().isin(dates)].reset_index(drop=True)
    dividends = load_stock_dividends(dividends_path)
    daily = stock_history.assign(session=stock_history.date.dt.normalize()).groupby("session").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last"),
    ).reset_index().rename(columns={"session": "date"})
    kdj = compute_dynamic_weekly_kdj(daily, cash_dividends=dividends)
    j = kdj.set_index("date").J
    invalid_j = j.loc[sorted(dates)]
    invalid_j = invalid_j.index[~np.isfinite(invalid_j)]
    if len(invalid_j):
        raise ValueError(f"{bank_name} 周线 KDJ 预热不足或没有有效价格区间: "
                         + ", ".join(f"{date:%Y%m%d}" for date in invalid_j[:10]))
    result_d = run_defensive_backtest(primary, stock, signals, bank_code, initial_cash, fees, bank_fees, dividends)
    result_j = weekly.run_bank_kdj_backtest(primary, stock, signals, j, initial_cash, fees,
        bank_code=bank_code, bank_fees=bank_fees, dividends=dividends, bank_take_profit=True)
    original = weekly.run_full_position_backtest(primary, signals, initial_cash, fees)
    direct_nav = result_d.nav.copy()
    direct_nav["position_code"] = np.select(
        [direct_nav.primary_quantity > 0, direct_nav.defensive_quantity > 0], [weekly.PRIMARY, bank_code], default="cash",
    )
    direct_nav["bank_weekly_j"] = direct_nav.date.map(j)
    direct_trades = _paired_events(result_d.trades, fees, bank_fees)
    variants = {
        "direct": (direct_nav, direct_trades, result_d.open_positions),
        "weekly_j": (result_j.nav, result_j.trades, result_j.open_position),
    }
    parameters = {"primary": weekly.PRIMARY, "bank_code": bank_code, "bank_stop_loss": None,
        "bank_take_profit_pct": 8, "calendar": "all_primary_sessions", "lot_size": 100,
        "indicator_price_basis": "forward_adjusted_cash_dividends_as_of_date",
        "execution_price_basis": audit["price_basis"], "dividend_basis": "gross_cash_once_on_ex_date",
        "execution_mode": "legacy_same_close_idealized"}
    variant_metrics = {key: _metrics(nav, trades, initial_cash, position, bank_code,
                                   {**parameters, **RULES[key]})
                       for key, (nav, trades, position) in variants.items()}
    metrics = {**variant_metrics["direct"], "bank_name": bank_name, "variants": variant_metrics,
               "original_strategy": weekly.compute_performance_metrics(
                   original.nav, original.trades, initial_cash, original.open_position is not None),
               "fees": {"primary": asdict(fees), "stock": asdict(bank_fees)}}
    annual = weekly._annual_returns(original.nav, initial_cash, "cash_return_pct")
    output_dir.mkdir(parents=True, exist_ok=True)
    for key, (nav, trades, _) in variants.items():
        sub = output_dir / key
        sub.mkdir(exist_ok=True)
        _decorate_nav(nav, initial_cash).to_csv(sub / "nav.csv", index=False, encoding="utf-8-sig")
        trades.to_csv(sub / "trades.csv", index=False, encoding="utf-8-sig")
        _write_json(sub / "metrics.json", {**variant_metrics[key], "bank_name": bank_name, "fees": metrics["fees"]})
        annual = annual.merge(weekly._annual_returns(nav, initial_cash, f"{key}_return_pct"), on="year", validate="one_to_one")
    events = result_d.trades
    if events.empty:
        events = events.reindex(columns=["date", "time", "code", "side", "quantity", "signal_price",
                                        "exec_price", "cash_flow", "reason", "dividend_income",
                                        "pnl", "pnl_pct", "hold_sessions"])
    events.to_csv(output_dir / "direct/events.csv", index=False, encoding="utf-8-sig")
    for filename in ("nav.csv", "trades.csv"):
        (output_dir / filename).write_bytes((output_dir / "direct" / filename).read_bytes())
    original.nav.to_csv(output_dir / "original_nav.csv", index=False, encoding="utf-8-sig")
    original_trades = original.trades
    if original_trades.empty:
        original_trades = original_trades.reindex(columns=direct_trades.columns)
    original_trades.to_csv(output_dir / "original_trades.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(output_dir / "annual_returns.csv", index=False, encoding="utf-8-sig")
    kdj.to_csv(output_dir / "bank_weekly_kdj.csv", index=False, encoding="utf-8-sig", float_format="%.17g")
    _write_json(output_dir / "metrics.json", metrics)
    (output_dir / "report.md").write_text(_report(bank_name, bank_code, metrics, annual, metrics["fees"]), encoding="utf-8")
    for key in variants:
        specific = {**metrics, "variants": {key: variant_metrics[key]}}
        (output_dir / key / "report.md").write_text(_report(bank_name, bank_code, specific, annual, metrics["fees"]), encoding="utf-8")
    extra_sources = ("python/strategies/amv_winning/bank_comparison.py",)
    if task_id is not None:
        extra_sources += (f"python/strategies/{task_id}/runner.py", f"python/strategies/{task_id}/config.yaml")
    snapshot_stock_inputs(output_dir, stock_history, dividends_path, audit,
        amv_path=amv_path, primary_path=primary_path, code=bank_code, extra_sources=extra_sources)
    return metrics


def run_bank_task(request: RunRequest, *, bank_code: str, bank_name: str) -> Path:
    if request.execution_mode != "legacy_same_close_idealized":
        raise ValueError("银行比较入口只支持 legacy_same_close_idealized")
    settings = yaml.safe_load(request.config_path.read_text(encoding="utf-8"))
    paths = settings["paths"]
    def source(key):
        path = Path(paths[key])
        return path if path.is_absolute() else ROOT / path
    bank_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=request.fees.commission_rate, min_commission=request.fees.min_commission,
        slippage_rate=request.fees.slippage_rate,
    ).with_overrides(**settings.get("bank_fees", {}))
    run_comparison(source("amv_csv"), source("primary_csv"), source("stock_5m_dir"),
        source("stock_dividends_csv"), request.output_dir, bank_code=bank_code, bank_name=bank_name,
        start_date=request.start_date, end_date=request.end_date, initial_cash=settings.get("initial_cash", 200_000),
        fees=request.fees, bank_fees=bank_fees, task_id=request.task_id)
    return request.output_dir
