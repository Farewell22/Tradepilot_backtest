"""Compare the approved MA20-confirmation entry against single-day ABC defense."""
from __future__ import annotations

import math
from pathlib import Path
import sys

import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.factors.amv_confirmation import (
    CONFIRMATION_SESSIONS, MOMENTUM_THRESHOLD, generate_ma20_confirmations,
)
from python.run_backtest import ROOT, RunRequest
from python.strategies.amv_winning import runner as original
from python.strategies.amv_winning.bank_stock import load_stock_history, snapshot_stock_inputs
from python.strategies.amv_winning_defensive.runner import (
    DEFENSIVE_STOCK, load_dividend_events, run_defensive_backtest,
)
from python.strategies.amv_winning_defensive_second_entry.runner import (
    NEXT_OPEN_MODE, _save_variant, _write_json,
)
from python.strategies.amv_winning_defensive_single_day import runner as single_day


TASK_ID = "amv_winning_defensive_ma20_entry"
ENTRY_BRANCH = "ma20_confirmation_5d"


def generate_amv_signals(amv: pd.DataFrame) -> pd.DataFrame:
    signals = single_day.generate_amv_signals(amv)
    confirmed = generate_ma20_confirmations(signals[["date", "close"]]).set_index("date")
    for column in ("ma20", "ma60", "momentum_3", "cross_ma20", "ma20_confirmed", "ma20_cross_date"):
        signals[column] = signals.date.map(confirmed[column])
    signals["single_day_entry"] = signals.buy_signal
    signals["second_entry"] = signals.ma20_confirmed & (signals.close >= signals.ma5)
    signals["buy_signal"] = signals.single_day_entry | signals.second_entry
    signals["entry_branch"] = ""
    signals.loc[signals.second_entry, "entry_branch"] = ENTRY_BRANCH
    signals.loc[signals.single_day_entry, "entry_branch"] = "single_day_ge_4pct"
    return signals


def run(request: RunRequest) -> Path:
    if request.execution_mode != NEXT_OPEN_MODE:
        raise ValueError(f"主结果成交口径必须为 {NEXT_OPEN_MODE}")
    config = request.config_path or Path(__file__).with_name("config.yaml")
    settings = yaml.safe_load(config.read_text(encoding="utf-8"))
    paths = {key: Path(value) if Path(value).is_absolute() else ROOT / value
             for key, value in settings["paths"].items()}
    initial_cash = float(settings.get("initial_cash", 200000))
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("初始资金必须为有限正数")
    start, end = (pd.to_datetime(value, format="%Y%m%d")
                  for value in (request.start_date, request.end_date))
    if start > end:
        raise ValueError("开始日期不得晚于结束日期")
    primary = original._normalize_intraday(pd.read_csv(paths["primary_csv"]))
    primary = primary.loc[primary.date.dt.normalize().between(start, end)].reset_index(drop=True)
    if primary.empty:
        raise ValueError("请求区间没有主仓行情")
    dates = set(primary.date.dt.normalize())
    amv = pd.read_csv(paths["amv_csv"])
    # Compute full history first, including crosses before the requested start.
    combined = generate_amv_signals(amv)
    baseline = single_day.generate_amv_signals(amv)
    baseline["entry_branch"] = ""
    baseline.loc[baseline.buy_signal, "entry_branch"] = "single_day_ge_4pct"
    if paths["stock_data"].is_dir():
        stock, audit = load_stock_history(paths["stock_data"], end, code=DEFENSIVE_STOCK)
    else:
        stock = original._normalize_intraday(pd.read_csv(paths["stock_data"], float_precision="round_trip"))
        audit = {"code": DEFENSIVE_STOCK, "price_basis": "raw_unadjusted",
                 "source_csv": str(paths["stock_data"])}
    for label, available in (("0AMV", set(combined.date)),
                             ("农业银行", set(stock.date.dt.normalize()))):
        missing = sorted(dates - available)
        if missing:
            raise ValueError(f"{label}缺少主仓交易日: {[str(day.date()) for day in missing[:10]]}")
    stock = stock.loc[stock.date.dt.normalize().isin(dates)].reset_index(drop=True)
    combined = combined.loc[combined.date.isin(dates)].reset_index(drop=True)
    baseline = baseline.loc[baseline.date.isin(dates)].reset_index(drop=True)
    dividends = load_dividend_events(paths["stock_dividends_csv"])
    stock_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=request.fees.commission_rate, min_commission=request.fees.min_commission,
        slippage_rate=request.fees.slippage_rate,
    ).with_overrides(**settings.get("bank_fees", {}))
    output = request.output_dir
    output.mkdir(parents=True, exist_ok=True)
    variants, stats, annual, comparison = {}, [], None, None
    for name, signals, target in (("second_entry", combined, output),
                                  ("single_day", baseline, output / "baseline")):
        result = run_defensive_backtest(primary, stock, signals, DEFENSIVE_STOCK,
                                        initial_cash, request.fees, stock_fees, dividends,
                                        execution_timing="next_open")
        metrics, primary_pairs, events = _save_variant(
            target, result, signals, initial_cash, request.fees, stock_fees,
            second_entry=False, execution_mode=NEXT_OPEN_MODE,
        )
        # Reuse the established ledger exporter; replace its gap-specific metadata.
        parameters = metrics["parameters"]
        for key in ("gap_rank_lower", "gap_rank_upper_exclusive", "quantile_lookback_regime_observations",
                    "quantile_min_history", "second_entry_ma10_gt_ma30"):
            parameters.pop(key, None)
        parameters.update(second_entry=ENTRY_BRANCH if name == "second_entry" else None,
                          confirmation_window_sessions=CONFIRMATION_SESSIONS if name == "second_entry" else None,
                          confirmation_momentum_sessions=3 if name == "second_entry" else None,
                          confirmation_momentum_threshold=MOMENTUM_THRESHOLD if name == "second_entry" else None,
                          confirmation_requires_above_ma60=name == "second_entry")
        _write_json(target / "metrics.json", metrics)
        variants[name] = metrics
        yearly = original._annual_returns(result.nav, initial_cash, f"{name}_return_pct")
        annual = yearly if annual is None else annual.merge(yearly, on="year", validate="one_to_one")
        daily = result.nav[["date", "nav"]].rename(columns={"nav": f"{name}_nav"})
        comparison = daily if comparison is None else comparison.merge(daily, on="date", validate="one_to_one")
        for branch, group in primary_pairs.groupby("entry_branch"):
            stats.append({"variant": name, "entry_branch": branch, "closed_positions": len(group),
                          "wins": int((group.pnl > 0).sum()),
                          "win_rate_pct": float((group.pnl > 0).mean() * 100),
                          "avg_net_pnl_pct": float(group.pnl_pct.mean()), "total_pnl": float(group.pnl.sum())})
        orders = events.loc[events.time.eq("open")]
        if not (orders.signal_date < orders.date).all():
            raise AssertionError("开盘订单使用了尚未确认的信号")
    stats_frame = pd.DataFrame(stats, columns=["variant", "entry_branch", "closed_positions", "wins",
                                               "win_rate_pct", "avg_net_pnl_pct", "total_pnl"])
    stats_frame.to_csv(output / "signal_trade_stats.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(output / "annual_returns.csv", index=False, encoding="utf-8-sig")
    comparison.to_csv(output / "comparison_nav.csv", index=False, encoding="utf-8-sig")
    _write_json(output / "metrics.json", {**variants["second_entry"], "variants": variants})
    _write_json(output / "verification.json", {
        "calendar_identical": len(comparison) == len(dates), "sessions": len(dates),
        "next_open_signal_dates_before_fills": True,
        "base_single_day_signals_retained": bool((~baseline.buy_signal | combined.buy_signal).all()),
        "confirmation_window_includes_cross_day": True,
    })
    lines = ["# 农行直接防守：单日≥4%或MA20上穿后5日确认", "",
             f"区间 {variants['second_entry']['actual_start']}—{variants['second_entry']['actual_end']}，"
             f"{len(dates)}个交易日，初始资金 {initial_cash:,.0f} 元。", "",
             "第二买点：0AMV上穿MA20，从上穿当日起5个交易日内首次同时满足三日动量>4%"
             "且收盘>MA60。两种买点均要求收盘≥MA5、离场优先，全仓整手买512100；"
             "同时满足时归因于原单日买点。", "",
             "| 入场规则 | 总收益 | 年化 | 最大回撤 | 夏普 | 主仓买入次数 | 主仓闭合胜率 |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for name in ("single_day", "second_entry"):
        m = variants[name]
        lines.append(f"| {'仅单日' if name == 'single_day' else '单日+MA20确认'} | "
                     f"{m['total_return_pct']:.2f}% | {m['annualized_return_pct']:.2f}% | "
                     f"{m['max_drawdown_pct']:.2f}% | {m['sharpe_ratio']:.3f} | "
                     f"{m['primary_entry_count']} | {m['primary_metrics']['win_rate_pct']:.2f}% |")
    lines += ["", "## 主仓完整交易归因", "", stats_frame.to_markdown(index=False, floatfmt=".2f"),
              "", "## 年度收益", "", annual.to_markdown(index=False, floatfmt=".2f"),
              "", "## 执行与限制", "",
              "两组均信号收盘确认、下一共同交易日开盘执行，主仓买入日不可卖出。期末信号不执行。",
              "0AMV低于MA10或MACD死叉优先离场转农行；主仓盘中2.5%硬止损，"
              "盈利超过5%后按原规则激活前日实体低点跟踪退出。盘中退出取消当日主仓买入信号。",
              "农行无止损、费用后净价差8%止盈，股息不计入阈值；止盈后持现金直到主仓买点。",
              "年化按365自然日，夏普按243交易日。100份/股整手、费用、主仓份额合并及"
              "农行税前现金分红沿用原模型，ETF现金派息未单独记账。未完整模拟股息税、"
              "到账延迟、停牌涨跌停和成交容量。新增交易盈亏不等于组合相对基线的增量收益。",
              "根目录为实验组，baseline/为同口径单日组；inputs/、code_snapshot/和"
              "source_manifest.json保存本次输入、代码及SHA256。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    snapshot_stock_inputs(output, stock, paths["stock_dividends_csv"], audit,
                          amv_path=paths["amv_csv"], primary_path=paths["primary_csv"],
                          extra_sources=(f"python/strategies/{TASK_ID}/runner.py",
                                         f"python/strategies/{TASK_ID}/config.yaml",
                                         "python/factors/amv_confirmation.py",
                                         "python/strategies/amv_winning_defensive_single_day/runner.py",
                                         "python/strategies/amv_winning_defensive_second_entry/runner.py",
                                         "python/strategies/amv_winning/bank_comparison.py"))
    return output


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", TASK_ID, *sys.argv[1:]]))
