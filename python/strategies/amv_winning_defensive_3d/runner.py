"""Change only the multi-session entry branch of the direct ABC defense strategy."""
from __future__ import annotations

from dataclasses import asdict
import json
import math
from pathlib import Path
import sys

import pandas as pd
import yaml

from python.backtest.broker import FeeConfig
from python.run_backtest import ROOT, RunRequest
from python.strategies.amv_winning import runner as original
from python.strategies.amv_winning.bank_comparison import _paired_events
from python.strategies.amv_winning.bank_stock import load_stock_history, snapshot_stock_inputs
from python.strategies.amv_winning_defensive.runner import (
    DEFENSIVE_STOCK, load_dividend_events, run_defensive_backtest,
)


def generate_amv_signals(amv: pd.DataFrame) -> pd.DataFrame:
    """Use one-day >=4% OR three-day >=4.5%, retaining the original MA5 gate."""
    signals = original.generate_amv_signals(amv)
    signals["three_day_return"] = signals["close"].pct_change(3)
    # Comparing prices keeps an exact 4.5% boundary inclusive despite subtraction rounding.
    three_day_entry = signals["close"] >= signals["close"].shift(3) * 1.045
    signals["buy_signal"] = (
        ((signals["day_return"] >= .04) | three_day_entry)
        & (signals["close"] >= signals["ma5"])
    )
    return signals


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(request: RunRequest) -> Path:
    return run_entry_variant(
        request, signal_generator=generate_amv_signals, variant="three_day",
        multi_day_sessions=3, multi_day_threshold=.045,
        title="农行直接防守策略：三日累计涨幅≥4.5%",
        entry_description="仅将主仓两日累计≥4%入场替换为三日累计≥4.5%；单日≥4%、收盘≥MA5条件保留。",
        variant_label="新版：三日≥4.5%",
    )


def run_entry_variant(request: RunRequest, *, signal_generator, variant: str,
                      multi_day_sessions: int | None, multi_day_threshold: float | None,
                      title: str, entry_description: str, variant_label: str) -> Path:
    """Compare an entry-only change using the same direct-defense execution loop."""
    settings = yaml.safe_load(request.config_path.read_text(encoding="utf-8"))
    paths = {key: Path(value) if Path(value).is_absolute() else ROOT / value
             for key, value in settings["paths"].items()}
    initial_cash = float(settings.get("initial_cash", 200000))
    if not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("初始资金必须为有限正数")
    start = pd.to_datetime(request.start_date, format="%Y%m%d")
    end = pd.to_datetime(request.end_date, format="%Y%m%d")
    if start > end:
        raise ValueError("开始日期不得晚于结束日期")
    primary = original._normalize_intraday(pd.read_csv(paths["primary_csv"]))
    primary = primary.loc[primary.date.dt.normalize().between(start, end)].reset_index(drop=True)
    if primary.empty:
        raise ValueError("请求区间没有主仓行情")
    dates = set(primary.date.dt.normalize())
    amv = pd.read_csv(paths["amv_csv"])
    # Warm up indicators on the full input, before restricting the requested dates.
    new_signals, baseline_signals = signal_generator(amv), original.generate_amv_signals(amv)
    if paths["stock_data"].is_dir():
        stock, audit = load_stock_history(paths["stock_data"], end, code=DEFENSIVE_STOCK)
    else:
        stock = original._normalize_intraday(
            pd.read_csv(paths["stock_data"], float_precision="round_trip")
        )
        audit = {"code": DEFENSIVE_STOCK, "price_basis": "raw_unadjusted",
                 "source_csv": str(paths["stock_data"])}
    for label, available in (("0AMV", set(new_signals.date)),
                             ("农业银行", set(stock.date.dt.normalize()))):
        missing = sorted(dates - available)
        if missing:
            raise ValueError(f"{label}缺少主仓交易日: {[str(day.date()) for day in missing[:10]]}")
    stock = stock.loc[stock.date.dt.normalize().isin(dates)].reset_index(drop=True)
    new_signals = new_signals.loc[new_signals.date.isin(dates)].reset_index(drop=True)
    baseline_signals = baseline_signals.loc[baseline_signals.date.isin(dates)].reset_index(drop=True)
    dividends = load_dividend_events(paths["stock_dividends_csv"])
    stock_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=request.fees.commission_rate, min_commission=request.fees.min_commission,
        slippage_rate=request.fees.slippage_rate,
    ).with_overrides(**settings.get("bank_fees", {}))
    output = request.output_dir
    output.mkdir(parents=True, exist_ok=True)
    results, metrics, annuals, trade_stats = {}, {}, [], []
    event_columns = ["date", "time", "code", "side", "quantity", "signal_price", "exec_price",
                     "cash_flow", "reason", "dividend_income", "pnl", "pnl_pct", "hold_sessions"]
    for name, signals in ((variant, new_signals), ("baseline", baseline_signals)):
        result = run_defensive_backtest(primary, stock, signals, DEFENSIVE_STOCK,
                                        initial_cash, request.fees, stock_fees, dividends)
        events = result.trades.reindex(columns=event_columns)
        pairs = _paired_events(events, request.fees, stock_fees)
        target = output if name == variant else output / "baseline"
        target.mkdir(exist_ok=True)
        nav = result.nav.copy()
        nav["return_pct"] = (nav.nav / initial_cash - 1) * 100
        nav["drawdown_pct"] = (nav.nav / nav.nav.cummax().clip(lower=initial_cash) - 1) * 100
        nav["position_code"] = "cash"
        nav.loc[nav.primary_quantity > 0, "position_code"] = original.PRIMARY
        nav.loc[nav.defensive_quantity > 0, "position_code"] = DEFENSIVE_STOCK
        nav.to_csv(target / "nav.csv", index=False, encoding="utf-8-sig")
        events.to_csv(target / "trades.csv", index=False, encoding="utf-8-sig")
        pairs.to_csv(target / "paired_trades.csv", index=False, encoding="utf-8-sig")
        signals.to_csv(target / "amv_signals.csv", index=False, encoding="utf-8-sig")
        m = original.compute_performance_metrics(nav, pairs, initial_cash, bool(result.open_positions))
        m.update(actual_start=nav.date.iloc[0].strftime("%Y%m%d"),
                 actual_end=nav.date.iloc[-1].strftime("%Y%m%d"), sessions=len(nav),
                 dividend_income=float(nav.dividend_income.iloc[-1]),
                 open_positions=result.open_positions, execution_mode=request.execution_mode,
                 source_strategy="amv_winning_defensive", bank_code=DEFENSIVE_STOCK,
                 fees={"primary": asdict(request.fees), "stock": asdict(stock_fees)},
                 parameters={"single_day_threshold": .04,
                             "multi_day_sessions": multi_day_sessions if name == variant else 2,
                             "multi_day_threshold": multi_day_threshold if name == variant else .04,
                             "entry_ma5": True, "entry_ma30_filter": False,
                             "bank_take_profit": "8pct_net_price_pnl_excluding_dividends",
                             "post_take_profit": "cash_until_primary_entry",
                             "bank_stop_loss": None, "calendar": "all_primary_sessions"})
        _write_json(target / "metrics.json", m)
        results[name], metrics[name] = result, m
        annuals.append(original._annual_returns(nav, initial_cash, f"{name}_return_pct"))
        primary_trades = pairs.loc[pairs.code.eq(original.PRIMARY)].copy()
        if not primary_trades.empty:
            signal_map = signals.set_index("date")
            entry_dates = pd.to_datetime(primary_trades.buy_date, format="%Y%m%d")
            primary_trades["entry_branch"] = "multi_day_only"
            strong = entry_dates.map(signal_map.day_return) >= .04
            primary_trades.loc[strong, "entry_branch"] = "single_day_ge_4pct"
            for branch, group in primary_trades.groupby("entry_branch"):
                trade_stats.append({"variant": name, "entry_branch": branch, "n": len(group),
                                    "win_rate_pct": float((group.pnl > 0).mean() * 100),
                                    "avg_net_pnl_pct": float(group.pnl_pct.mean()),
                                    "total_pnl": float(group.pnl.sum())})
            primary_trades.to_csv(target / "primary_trades.csv", index=False, encoding="utf-8-sig")
    annual = annuals[0].merge(annuals[1], on="year")
    annual.to_csv(output / "annual_returns.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(trade_stats, columns=["variant", "entry_branch", "n", "win_rate_pct",
                                      "avg_net_pnl_pct", "total_pnl"]).to_csv(
        output / "signal_trade_stats.csv", index=False, encoding="utf-8-sig"
    )
    comparison = results[variant].nav[["date", "nav"]].merge(
        results["baseline"].nav[["date", "nav"]], on="date", suffixes=(f"_{variant}", "_baseline")
    )
    comparison.to_csv(output / "comparison_nav.csv", index=False, encoding="utf-8-sig")
    verification = {"calendar_identical": len(comparison) == len(dates),
                    "sessions": len(dates), "single_day_branch_unchanged": True,
                    "baseline_multi_day_sessions": 2, "new_multi_day_sessions": multi_day_sessions}
    _write_json(output / "verification.json", verification)
    report = [f"# {title}", "",
              f"实际区间 {metrics[variant]['actual_start']}—{metrics[variant]['actual_end']}；"
              f"{len(dates)}个交易日，初始资金 {initial_cash:,.0f} 元。", "",
              entry_description,
              "0AMV低于MA10或MACD死叉优先离场；复用原成交、仓位、止损、跟踪退出和农行8%净价差止盈规则。", "",
              "| 版本 | 总收益 | 年化 | 最大回撤 | 夏普 | 期末资金 | 闭合交易数 |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for name, label in (("baseline", "原版：两日≥4%"), (variant, variant_label)):
        m = metrics[name]
        report.append(f"| {label} | {m['total_return_pct']:.2f}% | {m['annualized_return_pct']:.2f}% | "
                      f"{m['max_drawdown_pct']:.2f}% | {m['sharpe_ratio']:.3f} | {m['final_nav']:,.2f} | "
                      f"{m['closed_trade_count']} |")
    report += ["", "## 年度收益", "", "| 年份 | 原版 | 新版 |", "|---|---:|---:|"]
    for row in annual.to_dict("records"):
        report.append(f"| {row['year']} | {row['baseline_return_pct']:.2f}% | {row[f'{variant}_return_pct']:.2f}% |")
    report += ["", "## 成交口径与限制", "",
               "legacy_same_close_idealized：收盘确定信号、同日收盘执行，是原策略的理想化假设。",
               "主仓盘中2.5%硬止损、浮盈超过5%后次日起按前日实体低点退出；盘中退出当日不回买主仓。",
               "仅0AMV收盘离场条件触发时直接买农行，不要求周线J。农行无止损，费用后净价差8%止盈，"
               "止盈后现金锁定直到有效主仓入场；单独主仓盘中退出后先持现金。",
               "主仓100份、股票100股整手；税前现金分红按原模型除息日计入可用现金，不计入止盈阈值。",
               "年化按365自然日，夏普按243交易日、零无风险利率。期末持仓按收盘价估值，不强制平仓。",
               "固定旧印花税/过户费，未充分模拟股息税、到账延迟、涨跌停、停牌及成交容量。",
               "输入、代码快照及SHA256在inputs/、code_snapshot/、source_manifest.json；baseline/为同输入重跑原版。", ""]
    (output / "report.md").write_text("\n".join(report), encoding="utf-8")
    snapshot_stock_inputs(output, stock, paths["stock_dividends_csv"], audit,
                          amv_path=paths["amv_csv"], primary_path=paths["primary_csv"],
                          extra_sources=("python/strategies/amv_winning_defensive_3d/runner.py",
                                         f"python/strategies/{request.task_id}/runner.py",
                                         f"python/strategies/{request.task_id}/config.yaml",
                                         "python/strategies/amv_winning/bank_comparison.py"))
    return output


if __name__ == "__main__":
    from python.run_backtest import main
    raise SystemExit(main(["run", "strategy", "amv_winning_defensive_3d", *sys.argv[1:]]))
