"""Eight defensive ETF variants, their buy/hold and market/cash comparisons."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import numpy as np
import pandas as pd

from python.backtest.broker import FeeConfig
from python.backtest.corporate_actions import CorporateAction, load_corporate_actions
from python.backtest.engine import Engine
from python.backtest.market_data import normalize_etf_history, normalize_etf_intraday
from python.backtest.models import Portfolio
from python.factors.amv_ma_regime import compute_amv_ma_regimes
from python.strategies.amv_below_ma_defensive_etfs.strategy import AmvBelowMaStrategy


SOURCE_DIR = Path(__file__).resolve().parent
NAMES = {"512800.SH": "银行", "561560.SH": "电力", "515220.SH": "煤炭", "512890.SH": "红利低波", "510300.SH": "沪深300"}
TARGETS = tuple(code for code in NAMES if code != "510300.SH")
INITIAL_CASH = 200_000.0
FILL_COLUMNS = ["date", "time", "code", "side", "quantity", "signal_date", "signal_time", "signal_price", "exec_price", "cash_flow", "fees", "slippage_cost", "nav_before", "nav_after", "reason", "episode_id"]
EPISODE_COLUMNS = ["episode_id", "code", "period", "entry_date", "exit_date", "status", "entry_nav", "end_nav", "return_pct", "hold_sessions", "reinvestment_count", "dividend_income", "costs"]
LEDGER_COLUMNS = ["date", "code", "kind", "action", "record_date", "ex_date", "pay_date", "amount", "quantity", "split_ratio", "episode_id", "holding_id", "source_url"]


def load_action_inputs():
    actions = load_corporate_actions(SOURCE_DIR / "corporate_actions.csv")
    audit = json.loads((SOURCE_DIR / "corporate_action_audit.json").read_text(encoding="utf-8"))
    if set(audit["funds"]) != set(NAMES) or any(not item.get("sources") for item in audit["funds"].values()):
        raise ValueError("corporate action audit must cover all five funds with sources")
    for code, item in audit["funds"].items():
        actual = sum(action.code == code and action.kind == "dividend" for action in actions)
        if actual != item["dividend_events"]:
            raise ValueError(f"dividend event count disagrees with audit: {code}")
    return actions, audit


def execution_bars(daily: pd.DataFrame, code: str) -> pd.DataFrame:
    opening = daily.loc[:, ["date", "open"]].copy()
    opening["timestamp"] = opening.date + pd.Timedelta(hours=9, minutes=30)
    for column in ("high", "low", "close"):
        opening[column] = opening.open
    closing = daily.loc[:, ["date", "open", "high", "low", "close"]].copy()
    closing["timestamp"] = closing.date + pd.Timedelta(hours=15)
    result = pd.concat([opening, closing], ignore_index=True)
    result["code"] = code
    return result.sort_values("timestamp")


def run_variant(daily: pd.DataFrame, signals: pd.DataFrame, code: str, period: int | None,
                actions: list[CorporateAction], *, initial_cash=INITIAL_CASH, fees=None) -> Portfolio:
    if period not in (30, 60, None) or daily.empty:
        raise ValueError("variant requires daily bars and MA30, MA60 or buy/hold")
    strategy = AmvBelowMaStrategy(code, period, signals)
    first = pd.Timestamp(daily.date.iloc[0]).normalize()
    previous = signals.loc[signals.date < first]
    initial_orders = []
    if previous.empty:
        raise ValueError("pre-start AMV history is required for the first opening")
    previous_date = pd.Timestamp(previous.date.iloc[-1])
    if strategy.eligible(previous_date):
        initial_orders.append((previous_date + pd.Timedelta(hours=15), strategy.entry(previous_date)))
    return Engine(fees or FeeConfig.etf_legacy()).run(
        execution_bars(daily, code), strategy, initial_cash,
        initial_orders=initial_orders, corporate_actions=[action for action in actions if action.code == code],
        enforce_t1=True,
    )


def summarize_variant(result: Portfolio, code: str, period: int | None, initial_cash: float):
    nav = pd.DataFrame(result.daily_snapshots)
    values = nav.nav.astype(float)
    final_nav = float(values.iloc[-1])
    days = (pd.Timestamp(nav.date.iloc[-1]) - pd.Timestamp(nav.date.iloc[0])).days
    drawdown = values / values.cummax().clip(lower=initial_cash) - 1
    daily_return = values.pct_change()
    daily_return.iloc[0] = values.iloc[0] / initial_cash - 1
    deviation = daily_return.std()
    index = {date: i for i, date in enumerate(nav.date)}
    episodes = []
    for entry in result.fills:
        if entry["side"] != "buy" or entry["reason"] != "entry":
            continue
        fills = [fill for fill in result.fills if fill["episode_id"] == entry["episode_id"]]
        sales = [fill for fill in fills if fill["side"] == "sell"]
        last = sales[-1] if sales else None
        exit_date = last["date"] if last else str(nav.date.iloc[-1])
        end_nav = last["nav_after"] if last else final_nav
        income = sum(event["amount"] for event in result.corporate_action_ledger
                     if event["episode_id"] == entry["episode_id"] and event["action"] == "accrued")
        episodes.append({"episode_id": entry["episode_id"], "code": code, "period": period or 0,
            "entry_date": entry["date"], "exit_date": exit_date if last else "", "status": "closed" if last else "open",
            "entry_nav": entry["nav_before"], "end_nav": end_nav,
            "return_pct": (end_nav / entry["nav_before"] - 1) * 100,
            "hold_sessions": index[exit_date] - index[entry["date"]],
            "reinvestment_count": sum(fill["reason"] == "dividend_reinvestment" for fill in fills),
            "dividend_income": income, "costs": sum(fill["fees"] + fill["slippage_cost"] for fill in fills)})
    closed = [episode for episode in episodes if episode["status"] == "closed"]
    summary = {"code": code, "name": NAMES.get(code, code), "period": period or 0,
        "mode": f"ma{period}" if period else "buy_hold", "initial_cash": initial_cash, "final_nav": final_nav,
        "total_return_pct": (final_nav / initial_cash - 1) * 100,
        "annualized_return_pct": ((final_nav / initial_cash) ** (365 / days) - 1) * 100 if days else 0.,
        "max_drawdown_pct": float(drawdown.min() * 100),
        "sharpe": float(daily_return.mean() / deviation * np.sqrt(252)) if deviation > 0 else 0.,
        "closed_episodes": len(closed), "open_episodes": len(episodes) - len(closed),
        "win_rate_pct": sum(episode["return_pct"] > 0 for episode in closed) / len(closed) * 100 if closed else np.nan,
        "mean_episode_return_pct": float(np.mean([episode["return_pct"] for episode in closed])) if closed else np.nan,
        "mean_hold_sessions": float(np.mean([episode["hold_sessions"] for episode in closed])) if closed else np.nan,
        "exposure_pct": float(nav.invested.mean() * 100), "dividend_income": result.dividend_income_total,
        "dividend_receivable": result.dividend_receivable,
        "commission_and_taxes": sum(fill["fees"] for fill in result.fills),
        "slippage_cost": sum(fill["slippage_cost"] for fill in result.fills),
        "reinvestment_count": sum(fill["reason"] == "dividend_reinvestment" for fill in result.fills)}
    return summary, episodes


def _snapshot(output_dir: Path, paths: list[Path]) -> dict:
    root = SOURCE_DIR.parents[2]
    snapshots = output_dir / "source_snapshot"
    hashes = {}
    for path in paths:
        path = path.absolute()
        try:
            relative = path.relative_to(root)
        except ValueError:
            parent_id = hashlib.sha256(str(path.parent).encode("utf-8")).hexdigest()[:16]
            relative = Path("external_inputs") / parent_id / path.name
        destination = snapshots / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = path.read_bytes()
        destination.write_bytes(content)
        hashes[str(relative)] = hashlib.sha256(content).hexdigest()
    return hashes


def _plot(nav: pd.DataFrame, output_dir: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    for period in (30, 60):
        fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
        for code in NAMES:
            frame = nav.loc[(nav.code == code) & (nav.period == period)]
            dates = pd.to_datetime(frame.date, format="%Y%m%d")
            axes[0].plot(dates, frame.normalized_nav, label=code, linewidth=1.2)
            axes[1].plot(dates, frame.drawdown_pct, linewidth=1.0)
        axes[0].axhline(1, color="gray", linestyle=":", label="Cash")
        axes[0].set_title(f"0AMV below MA{period}: total return after costs, dividends reinvested")
        axes[0].set_ylabel("NAV / initial cash")
        axes[1].set_ylabel("Drawdown (%)")
        axes[0].legend(ncol=3)
        for axis in axes:
            axis.grid(alpha=.25)
        fig.tight_layout()
        fig.savefig(output_dir / f"ma{period}_nav_drawdown.png", dpi=160)
        plt.close(fig)


def _report(summary, annual, metadata):
    display = summary.loc[summary.code.isin(TARGETS) & (summary.period > 0),
        ["name", "code", "mode", "total_return_pct", "annualized_return_pct", "max_drawdown_pct", "closed_episodes", "win_rate_pct", "exposure_pct", "dividend_income", "reinvestment_count"]]
    display = display.rename(columns={"name": "ETF", "code": "代码", "mode": "规则", "total_return_pct": "含分红收益%", "annualized_return_pct": "年化%", "max_drawdown_pct": "最大回撤%", "closed_episodes": "已结束区间", "win_rate_pct": "区间胜率%", "exposure_pct": "持仓时间%", "dividend_income": "分红收入元", "reinvestment_count": "分红补买次数"})
    comparison = summary[["name", "code", "mode", "total_return_pct", "max_drawdown_pct", "dividend_income", "excess_buy_hold_pp", "excess_market_timing_pp"]]
    lines = ["# 0AMV 低于 MA30、MA60 时的防守 ETF 回测", "",
        f"区间：{metadata['actual_start']}—{metadata['actual_end']}，{metadata['trading_days']} 个交易日；每组初始资金 200,000 元。",
        "MA30、MA60 分别独立回测。0AMV 收盘低于对应简单均线，下一交易日开盘买入；回到均线上或相等，下一交易日开盘卖出。首日依据区间前一交易日信号建仓。", "",
        "## 四只 ETF 主结果", "", display.to_markdown(index=False, floatfmt=".2f"), "",
        "## 同期基准与超额收益", "",
        "`buy_hold` 为首日开盘买入并再投资分红；现金为零收益。超额收益单位为百分点，分别对比自身买入持有和 510300 同均线择时。", "",
        comparison.to_markdown(index=False, floatfmt=".2f"), "",
        "## 分红与执行口径", "",
        "登记日收盘确定分红资格，除息日记应收款，到账日收盘转入现金。若仍满足持有条件，下一交易日开盘使用分红和剩余现金补买；退出优先。不足一手余额等待后续派息或开仓。",
        "分红金额是账户实际获得的 ETF 派息，成份股分红留存在基金中的部分已反映在基金资产中。基金年报核实银行、电力、红利低波在本区间没有向持有人现金派息；煤炭及沪深300派息已逐笔核算。",
        "银行和煤炭的 1:2 份额拆分已按登记日资格调整份额及单位成本，避免将价格折半当作亏损。现金、持仓市值及应收分红共同组成净值，到账和再投资不会再次确认收入。",
        f"本次费用：{json.dumps(metadata['fees'], ensure_ascii=False)}。按100份买入，按批次检查T+1。费用覆盖也作用于所有非现金基准。",
        "区间胜率按完整持有区间计算，分红补买仍属于同一区间；期末未卖出区间单独列示。持有区间收益按该区间账户财富变化计算，包含现金及应收款。",
        "年化采用自然日365天口径；夏普采用252个交易日、无风险收益为零。每日最大回撤包含初始资金基线。", "",
        "## 年度收益", "", annual.to_markdown(index=False, floatfmt=".2f"), "",
        "## 曲线", "",
        *[f"![MA{period} NAV and drawdown]({quote(str(Path(metadata['output_dir']) / f'ma{period}_nav_drawdown.png'))})\n" for period in (30, 60)],
        "## 数据与复现", "",
        "行情为未复权价格；分红/拆分表与来源核对记录见 corporate_action_audit.json。原始输入和运行代码快照及 SHA-256 见 execution_metadata.json 和 source_snapshot/；统一入口另生成 run_manifest.json。",
        "",
        *[f"- {NAMES[code]}（{code}）：核对 {item['dividend_events']} 次现金派息、{item['split_events']} 次拆分。" + "、".join(f"[来源{index}]({url})" for index, url in enumerate(item['sources'], 1))
          for code, item in metadata['corporate_action_audit']['funds'].items()],
        "",
        "本回测使用日开盘作为成交价格，未模拟涨跌停成交限制、盘口容量和订单排队。数据覆盖缺口会报错。2022年为5月16日起的部分年度。", ""]
    return "\n".join(lines)


def run_backtest(amv_path: Path, etf_dir: Path, output_dir: Path, *, start_date="20220516", end_date="20251231", fees=None):
    fees = fees or FeeConfig.etf_legacy()
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    if start > end:
        raise ValueError("start date must not follow end date")
    actions, audit = load_action_inputs()
    if start < pd.Timestamp(audit["coverage_start"]) or end > pd.Timestamp(audit["coverage_end"]):
        raise ValueError("requested interval is outside verified corporate-action coverage")
    signals = compute_amv_ma_regimes(pd.read_csv(amv_path))
    calendar = pd.DatetimeIndex(signals.loc[signals.date.between(start, end), "date"])
    prior = signals.loc[signals.date < start]
    if calendar.empty or prior.empty or prior.ma60.isna().iloc[-1]:
        raise ValueError("AMV calendar or MA60 warmup is missing")
    inputs = [amv_path, SOURCE_DIR / "corporate_actions.csv", SOURCE_DIR / "corporate_action_audit.json"]
    prices = {}
    for code in NAMES:
        path = etf_dir / f"{code}.csv"
        raw = pd.read_csv(path)
        intraday = normalize_etf_intraday(raw)
        if intraday.date.duplicated().any():
            raise ValueError(f"duplicate intraday timestamp: {code}")
        active = intraday.loc[intraday.date.dt.normalize().between(start, end)]
        if not np.isfinite(active[["open", "high", "low", "close", "volume"]].to_numpy(dtype=float)).all():
            raise ValueError(f"non-finite intraday OHLCV: {code}")
        if (active.volume < 0).any():
            raise ValueError(f"negative intraday volume: {code}")
        slots = active.date - active.date.dt.normalize()
        expected_slots = pd.to_timedelta(["10:30:00", "11:30:00", "14:00:00", "15:00:00"])
        if not slots.isin(expected_slots).all():
            raise ValueError(f"unexpected intraday slots: {code}")
        counts = intraday.groupby(intraday.date.dt.normalize()).size()
        if not counts.reindex(calendar).eq(4).all():
            raise ValueError(f"missing or incomplete daily bars: {code}")
        etf_calendar = counts.loc[counts.index.to_series().between(start, end)].index
        if not etf_calendar.equals(calendar):
            raise ValueError(f"ETF and AMV calendar mismatch: {code}")
        daily = normalize_etf_history(raw).set_index("date").reindex(calendar)
        if daily.isna().any().any() or not (daily.volume > 0).all():
            raise ValueError(f"missing or untradeable prices: {code}")
        prices[code] = daily.reset_index()
        inputs.append(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows, nav_rows, fills, episodes, ledger = [], [], [], [], []
    for period in (30, 60, None):
        for code in NAMES:
            result = run_variant(prices[code], signals, code, period, actions, fees=fees)
            summary, account_episodes = summarize_variant(result, code, period, INITIAL_CASH)
            curve = f"{code}_{summary['mode']}"
            summary["curve"] = curve
            summary_rows.append(summary)
            for row in result.daily_snapshots:
                nav_rows.append({**row, "code": code, "period": period or 0, "mode": summary["mode"], "curve": curve})
            fills.extend({**row, "curve": curve} for row in result.fills)
            episodes.extend({**row, "curve": curve} for row in account_episodes)
            ledger.extend({**row, "curve": curve} for row in result.corporate_action_ledger)
    cash = Portfolio(INITIAL_CASH, INITIAL_CASH)
    cash.daily_snapshots = [dict(date=date.strftime("%Y%m%d"), nav=INITIAL_CASH, cash=INITIAL_CASH, dividend_receivable=0., dividend_income=0., invested=False, quantity=0) for date in calendar]
    cash_summary, _ = summarize_variant(cash, "CASH", None, INITIAL_CASH)
    cash_summary.update(mode="cash", curve="cash", name="现金")
    summary_rows.append(cash_summary)
    nav_rows.extend({**row, "code": "CASH", "period": 0, "mode": "cash", "curve": "cash"} for row in cash.daily_snapshots)
    summary = pd.DataFrame(summary_rows)
    holds = summary.loc[summary["mode"] == "buy_hold"].set_index("code").total_return_pct
    market = summary.loc[(summary.code == "510300.SH") & (summary.period > 0)].set_index("period").total_return_pct
    summary["excess_buy_hold_pp"] = summary.total_return_pct - summary.code.map(holds)
    summary["excess_market_timing_pp"] = summary.total_return_pct - summary.period.map(market)
    nav = pd.DataFrame(nav_rows)
    nav["normalized_nav"] = nav.nav / INITIAL_CASH
    nav["drawdown_pct"] = (nav.nav / nav.groupby("curve").nav.cummax().clip(lower=INITIAL_CASH) - 1) * 100
    annual_rows = []
    for curve, frame in nav.groupby("curve", sort=False):
        changes = frame.nav.pct_change()
        changes.iloc[0] = frame.nav.iloc[0] / INITIAL_CASH - 1
        returns = changes.groupby(pd.to_datetime(frame.date, format="%Y%m%d").dt.year).apply(lambda value: ((1 + value).prod() - 1) * 100)
        annual_rows.extend({"curve": curve, "year": int(year), "return_pct": value} for year, value in returns.items())
    annual = pd.DataFrame(annual_rows).pivot(index="year", columns="curve", values="return_pct").reset_index()
    metadata = {"actual_start": str(calendar[0].date()), "actual_end": str(calendar[-1].date()),
        "output_dir": str(output_dir.resolve()), "input_paths": [str(path.absolute()) for path in inputs],
        "trading_days": len(calendar), "initial_cash": INITIAL_CASH, "fees": asdict(fees),
        "signal": "0AMV daily close strictly below own SMA30/SMA60, inclusive of signal day",
        "execution": "signal close to next session 09:30 open; previous close seeds first opening",
        "dividend": "record-close eligibility; ex-date receivable; pay-date close cash; following-open reinvestment; exit priority",
        "terminal": "mark positions and receivables; no forced sale", "unmodeled": ["limit-lock executions", "order-book capacity"],
        "source_sha256": {}, "corporate_action_audit": audit}
    root = SOURCE_DIR.parents[2]
    code_paths = [root / path for path in ("python/backtest/engine.py", "python/backtest/models.py", "python/backtest/corporate_actions.py", "python/backtest/broker.py", "python/backtest/market_data.py", "python/factors/amv_ma_regime.py", "python/task_registry.py", "python/run_backtest.py")]
    code_paths.extend([SOURCE_DIR / "strategy.py", SOURCE_DIR / "runner.py"])
    metadata["source_sha256"] = _snapshot(output_dir, inputs + code_paths)
    for name, frame in (("summary", summary), ("nav", nav), ("trades", pd.DataFrame(fills, columns=FILL_COLUMNS + ["curve"])),
                        ("episodes", pd.DataFrame(episodes, columns=EPISODE_COLUMNS + ["curve"])), ("corporate_action_ledger", pd.DataFrame(ledger, columns=LEDGER_COLUMNS + ["curve"])), ("annual_returns", annual)):
        frame.to_csv(output_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
    (output_dir / "execution_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "corporate_action_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _plot(nav, output_dir)
    (output_dir / "report.md").write_text(_report(summary, annual, metadata), encoding="utf-8")
    return summary
