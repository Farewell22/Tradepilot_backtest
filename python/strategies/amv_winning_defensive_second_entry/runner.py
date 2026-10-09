"""Add the existing class-2 AMV gap entry to the single-day ABC strategy."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.factors.amv_gap import MIN_HISTORY, QUANTILE_LOOKBACK, generate_buy_signals
from python.run_backtest import ROOT, RunRequest
from python.strategies.amv_winning import runner as original
from python.strategies.amv_winning.bank_comparison import _paired_events
from python.strategies.amv_winning.bank_stock import load_stock_history, snapshot_stock_inputs
from python.strategies.amv_winning_defensive.runner import (
    DEFENSIVE_STOCK, load_dividend_events, run_defensive_backtest,
)
from python.strategies.amv_winning_defensive_single_day import runner as single_day


TASK_ID = "amv_winning_defensive_second_entry"
NEXT_OPEN_MODE = "next_open_amv_abc_t1"
LEGACY_MODE = "legacy_same_close_idealized"
EVENT_COLUMNS = ["date", "time", "code", "side", "quantity", "signal_price", "exec_price",
                 "cash_flow", "reason", "dividend_income", "pnl", "pnl_pct", "hold_sessions",
                 "signal_date", "entry_signal_date", "entry_branch"]


def generate_amv_signals(amv: pd.DataFrame) -> pd.DataFrame:
    """Class-2 first entry uses strictly prior bullish-regime observations."""
    signals = single_day.generate_amv_signals(amv)
    gap_signals = generate_buy_signals(signals[["date", "close"]]).set_index("date")
    signals["ma30"] = signals.close.rolling(30).mean()
    signals["gap10"] = signals.close / signals.ma10 - 1
    signals["gap10_rank"] = signals.date.map(gap_signals.gap10_rank)
    signals["gap_signal_type"] = signals.date.map(gap_signals.signal_type).fillna("")
    signals["single_day_entry"] = signals.buy_signal
    signals["second_entry"] = (
        signals.gap_signal_type.eq("class_2") & (signals.close >= signals.ma5)
    )
    signals["buy_signal"] = signals.single_day_entry | signals.second_entry
    signals["entry_branch"] = ""
    signals.loc[signals.second_entry, "entry_branch"] = "class_2_gap"
    # If both entry conditions hold, attribute to the original entry.
    signals.loc[signals.single_day_entry, "entry_branch"] = "single_day_ge_4pct"
    return signals


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _save_variant(target: Path, result, signals: pd.DataFrame, initial_cash: float,
                  etf_fees: FeeConfig, stock_fees: FeeConfig, *, second_entry: bool,
                  execution_mode: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    target.mkdir(parents=True, exist_ok=True)
    # Empty ledgers otherwise infer float keys, incompatible with empty pairs.
    events = result.trades.reindex(columns=EVENT_COLUMNS).astype({"code": object, "date": object})
    pairs = _paired_events(events, etf_fees, stock_fees)
    buys = events.loc[events.side.eq("buy"), ["code", "date", "signal_date", "entry_branch"]]
    buys = buys.rename(columns={"date": "buy_date", "signal_date": "entry_signal_date"})
    pairs = pairs.merge(buys, on=["code", "buy_date"], how="left", validate="one_to_one")
    nav = result.nav.copy()
    nav["return_pct"] = (nav.nav / initial_cash - 1) * 100
    nav["drawdown_pct"] = (nav.nav / nav.nav.cummax().clip(lower=initial_cash) - 1) * 100
    nav["position_code"] = "cash"
    nav.loc[nav.primary_quantity > 0, "position_code"] = original.PRIMARY
    nav.loc[nav.defensive_quantity > 0, "position_code"] = DEFENSIVE_STOCK
    primary_pairs = pairs.loc[pairs.code.eq(original.PRIMARY)].copy()
    for name, frame in (("nav", nav), ("trades", events), ("paired_trades", pairs),
                        ("primary_trades", primary_pairs), ("amv_signals", signals)):
        frame.to_csv(target / f"{name}.csv", index=False, encoding="utf-8-sig")
    metrics = original.compute_performance_metrics(nav, pairs, initial_cash,
                                                   bool(result.open_positions))
    metrics.update(
        actual_start=nav.date.iloc[0].strftime("%Y%m%d"),
        actual_end=nav.date.iloc[-1].strftime("%Y%m%d"), sessions=len(nav),
        execution_mode=execution_mode, open_positions=result.open_positions,
        dividend_income=float(nav.dividend_income.iloc[-1]), bank_code=DEFENSIVE_STOCK,
        primary_entry_count=int((events.side.eq("buy") & events.code.eq(original.PRIMARY)).sum()),
        primary_metrics=original.compute_performance_metrics(nav, primary_pairs, initial_cash,
                                                              original.PRIMARY in result.open_positions),
        exposure_by_position_pct=nav.position_code.value_counts(normalize=True).mul(100).to_dict(),
        fees={"primary": asdict(etf_fees), "stock": asdict(stock_fees)},
        parameters={"single_day_threshold": .04, "multi_day_sessions": None,
                    "second_entry": "class_2_gap" if second_entry else None,
                    "gap_rank_lower": .60 if second_entry else None,
                    "gap_rank_upper_exclusive": .80 if second_entry else None,
                    "quantile_lookback_regime_observations": QUANTILE_LOOKBACK,
                    "quantile_min_history": MIN_HISTORY, "entry_ma5": True,
                    "second_entry_ma10_gt_ma30": second_entry,
                    "primary_hard_stop_pct": .025, "primary_profit_arm_pct": .05,
                    "bank_take_profit": "8pct_net_price_pnl_excluding_dividends",
                    "post_take_profit": "cash_until_primary_entry", "bank_stop_loss": None,
                    "calendar": "all_primary_sessions"},
    )
    _write_json(target / "metrics.json", metrics)
    return metrics, primary_pairs, events


def run(request: RunRequest) -> Path:
    if request.execution_mode != NEXT_OPEN_MODE:
        raise ValueError(f"本策略主结果成交口径必须为 {NEXT_OPEN_MODE}")
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
    # Warm all signal history before cutting the requested trading calendar.
    amv = pd.read_csv(paths["amv_csv"])
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
    variants, annual, stats, comparison = {}, None, [], None
    cases = (
        ("second_entry", combined, "next_open", output),
        ("single_day", baseline, "next_open", output / "baseline"),
        ("legacy_second_entry", combined, "same_close", output / "legacy_same_close/second_entry"),
        ("legacy_single_day", baseline, "same_close", output / "legacy_same_close/single_day"),
    )
    for name, signals, timing, target in cases:
        result = run_defensive_backtest(primary, stock, signals, DEFENSIVE_STOCK,
                                        initial_cash, request.fees, stock_fees, dividends,
                                        execution_timing=timing)
        mode = NEXT_OPEN_MODE if timing == "next_open" else LEGACY_MODE
        m, primary_pairs, events = _save_variant(
            target, result, signals, initial_cash, request.fees, stock_fees,
            second_entry="second_entry" in name, execution_mode=mode,
        )
        variants[name] = m
        yearly = original._annual_returns(result.nav, initial_cash, f"{name}_return_pct")
        annual = yearly if annual is None else annual.merge(yearly, on="year", validate="one_to_one")
        daily = result.nav[["date", "nav"]].rename(columns={"nav": f"{name}_nav"})
        comparison = daily if comparison is None else comparison.merge(daily, on="date", validate="one_to_one")
        for branch, group in primary_pairs.groupby("entry_branch"):
            stats.append({"variant": name, "entry_branch": branch, "closed_positions": len(group),
                          "wins": int((group.pnl > 0).sum()),
                          "win_rate_pct": float((group.pnl > 0).mean() * 100),
                          "avg_net_pnl_pct": float(group.pnl_pct.mean()),
                          "total_pnl": float(group.pnl.sum())})
        if timing == "next_open":
            orders = events.loc[events.time.eq("open")]
            if not (orders.signal_date < orders.date).all():
                raise AssertionError("次日开盘订单使用了尚未确认的信号")
    stats_frame = pd.DataFrame(stats, columns=["variant", "entry_branch", "closed_positions",
                                               "wins", "win_rate_pct", "avg_net_pnl_pct", "total_pnl"])
    stats_frame.to_csv(output / "signal_trade_stats.csv", index=False, encoding="utf-8-sig")
    annual.to_csv(output / "annual_returns.csv", index=False, encoding="utf-8-sig")
    comparison.to_csv(output / "comparison_nav.csv", index=False, encoding="utf-8-sig")
    _write_json(output / "metrics.json", {**variants["second_entry"], "variants": variants})
    _write_json(output / "verification.json", {
        "calendar_identical": len(comparison) == len(dates), "sessions": len(dates),
        "next_open_signal_dates_before_fills": True,
        "base_single_day_signals_retained": bool((~baseline.buy_signal | combined.buy_signal).all()),
        "legacy_baseline_included": True,
    })
    lines = ["# 农行直接防守：单日≥4%或二类P60–P80买点", "",
             f"区间 {variants['second_entry']['actual_start']}—{variants['second_entry']['actual_end']}，"
             f"{len(dates)}个交易日，初始资金 {initial_cash:,.0f} 元。", "",
             "主仓买点一为0AMV单日≥4%；买点二为MA10>MA30、正gap10首次进入[P60,P80)。"
             "两类均要求收盘≥MA5，离场优先，全仓整手买入512100；同时满足时归因于买点一。", "",
             "| 成交口径 | 入场规则 | 总收益 | 年化 | 最大回撤 | 夏普 | 主仓买入次数 | 主仓闭合胜率 |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for name in ("single_day", "second_entry", "legacy_single_day", "legacy_second_entry"):
        m = variants[name]
        label = "单日+二类" if "second_entry" in name else "仅单日"
        timing = "同日收盘（理想化）" if name.startswith("legacy") else "次日开盘（主结果）"
        lines.append(f"| {timing} | {label} | {m['total_return_pct']:.2f}% | "
                     f"{m['annualized_return_pct']:.2f}% | {m['max_drawdown_pct']:.2f}% | "
                     f"{m['sharpe_ratio']:.3f} | {m['primary_entry_count']} | "
                     f"{m['primary_metrics']['win_rate_pct']:.2f}% |")
    lines += ["", "## 主仓完整交易：按入场买点统计", "", stats_frame.to_markdown(index=False, floatfmt=".2f"),
              "", "## 年度收益", "", annual.to_markdown(index=False, floatfmt=".2f"),
              "", "## 规则与限制", "",
              "主结果与单日基线均从现金启动，信号于收盘确认、下一共同交易日开盘执行；"
              "区间最后一天的信号不再执行。主仓买入日不可卖出，遵守T+1。",
              "0AMV低于MA10或MACD死叉优先离场，次日开盘转农行。主仓盘中2.5%硬止损；"
              "浮盈超过5%后次日起按前日实体低点跟踪退出。盘中退出当天的主仓买入信号被取消，"
              "若有0AMV离场信号仍于次日转农行。",
              "农行无止损，费用后净价差8%止盈（现金股息不计入阈值）；止盈后现金锁定直到"
              "有效主仓买点。再次进场时先卖出全部农行，再全仓买入512100。",
              "750个历史有效MA10>MA30观察值计算分位，至少250个预热，仅使用此前数据。"
              "P80上界不含、已有主仓时不重复开仓。",
              "同日收盘对照保留原策略理想化时点；两种成交口径分别比较，不将差异全部归于新买点。",
              "交易费用、100份/股整手、农行税前现金股息及主仓份额合并沿用原模型。"
              "农行除息日开盘卖出仍享有此前持仓股息，当日新买入不享有。"
              "ETF现金派息仍沿用原策略未单独记账的口径。",
              "年化按365自然日，夏普按243交易日。期末持仓估值但不计作闭合交易。"
              "固定旧税费、未完整模拟股息税和到账延迟、涨跌停、停牌及成交容量。",
              "新增分支交易会改变后续主仓与农行路径，其逐笔盈亏不等于相对基线的增量收益。",
              "inputs/、code_snapshot/和source_manifest.json保存输入、代码与SHA256；"
              "baseline/是次日开盘单日版，legacy_same_close/是两组原成交口径对照。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    snapshot_stock_inputs(output, stock, paths["stock_dividends_csv"], audit,
                          amv_path=paths["amv_csv"], primary_path=paths["primary_csv"],
                          extra_sources=(f"python/strategies/{TASK_ID}/runner.py",
                                         f"python/strategies/{TASK_ID}/config.yaml",
                                         "python/strategies/amv_winning_defensive_single_day/runner.py",
                                         "python/strategies/amv_winning/bank_comparison.py",
                                         "python/factors/amv_gap.py"))
    return output


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", TASK_ID, *sys.argv[1:]]))
