#!/usr/bin/env python3
"""Summarize TradePilot backtest run directories into diagnostic JSON.

Backtest results differ per task: trades may be paired rows or an event ledger,
nav may be a single series or several legs, metrics.json exists for only a few
tasks, and reports are .md or .txt. This script absorbs that variation and
prints objective grouped statistics to stdout. It writes nothing — writing the
review report is the caller's job.

It deliberately stops at descriptive statistics. Explaining *why* a group of
trades lost money requires reading the strategy source and mapping each
sell_reason to the code branch that produced it; that interpretation is left to
the model.

Usage:
    analyze_run.py <run_dir> [<run_dir2> ...] [--top N] [--trades] [--pretty]
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from pathlib import Path

import pandas as pd

HOLD_BUCKETS = [(0, 1), (2, 3), (4, 7), (8, 14), (15, 30), (31, 10**9)]
BUCKET_LABELS = ["1", "2-3", "4-7", "8-14", "15-30", "31+"]


def _read_csv(path: Path) -> pd.DataFrame | None:
    """Read a result CSV. Returns None for the '(no_trades)' placeholder."""
    text = path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not text or text.startswith("(no_trades)") or text.startswith("no_trades"):
        return None
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:  # noqa: BLE001 - tolerance is the point here
        return pd.DataFrame({"__parse_error__": [str(exc)]})


def _to_date(values: pd.Series) -> pd.Series:
    """Parse dates that may be YYYYMMDD ints/strings or ISO timestamps."""
    text = values.astype(str).str.strip()
    compact = text.str.fullmatch(r"\d{8}").fillna(False)
    parsed = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    if compact.any():
        parsed.loc[compact] = pd.to_datetime(text[compact], format="%Y%m%d", errors="coerce")
    if (~compact).any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # mixed ISO/naive strings; alignment already checked
            parsed.loc[~compact] = pd.to_datetime(text[~compact], errors="coerce")
    return parsed


def _find_result_dir(run_dir: Path) -> tuple[Path, Path | None]:
    """Return (dir holding the result files, dir holding run_manifest.json).

    Multi-stage tasks (etf_amv) nest their per-stage results one level down,
    keeping run_manifest.json at the top.
    """
    names = {p.name for p in run_dir.iterdir()} if run_dir.is_dir() else set()
    if {"trades.csv", "nav.csv"} & names:
        return run_dir, run_dir
    manifest = run_dir / "run_manifest.json"
    for child in sorted(p for p in run_dir.iterdir() if p.is_dir()):
        child_names = {p.name for p in child.iterdir()}
        if {"trades.csv", "nav.csv"} & child_names:
            return child, (run_dir if manifest.exists() else child)
    return run_dir, run_dir if manifest.exists() else None


def _load_manifest(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _pick_nav_column(columns: list[str]) -> tuple[str | None, list[str]]:
    """Choose the primary nav column; return (column, all nav-like columns)."""
    nav_like = [c for c in columns if c == "nav" or c.endswith("_nav")]
    if "nav" in columns:
        return "nav", nav_like
    if "original_nav" in columns:
        return "original_nav", nav_like
    return (nav_like[0], nav_like) if nav_like else (None, [])


def _metric_blocks(metrics: dict) -> tuple[dict, dict, list[str]]:
    """Split metrics.json into (primary, benchmark, variant keys).

    Shapes seen in this repo: a flat dict, a flat dict plus nested comparison
    blocks (original_strategy), and a wrapper whose only metrics live under a
    nested key (original).
    """
    variant_keys = [
        k for k, v in metrics.items()
        if isinstance(v, dict) and "total_return_pct" in v
    ]
    benchmark = metrics.get("benchmark") if isinstance(metrics.get("benchmark"), dict) else {}
    if "total_return_pct" in metrics:
        primary = {k: v for k, v in metrics.items() if not isinstance(v, dict)}
        return primary, benchmark, [k for k in variant_keys if k != "benchmark"]
    order = [k for k in ("original", "strategy", "main") if k in variant_keys]
    order += [k for k in variant_keys if k not in order and k != "benchmark"]
    if not order:
        return {}, benchmark, []
    return metrics[order[0]], benchmark, [k for k in order if k != order[0]]


def _normalize_trades(frame: pd.DataFrame | None) -> tuple[pd.DataFrame, str | None, list[str]]:
    """Normalize a trades table into paired rows.

    Returns (normalized, format name, warnings). Two shapes are supported:
    paired trades (buy_date/sell_date columns) and an event ledger (a 'side'
    column with one row per buy or sell).
    """
    warnings: list[str] = []
    columns = ["code", "buy_date", "sell_date", "sell_reason", "pnl", "pnl_pct", "hold_days"]
    if frame is None:
        return pd.DataFrame(columns=columns), "no_trades", warnings
    if "__parse_error__" in frame.columns:
        return pd.DataFrame(columns=columns), "unparsed", [f"trades.csv 解析失败: {frame.iloc[0, 0]}"]

    if "side" in frame.columns:
        ledger = frame.copy()
        ledger["side"] = ledger["side"].astype(str).str.lower()
        ledger = ledger.assign(_date=_to_date(ledger["date"])).sort_values("_date", kind="stable")
        key_col = "code" if "code" in ledger.columns else None
        pending: dict[str, list] = {}
        rows = []
        for row in ledger.to_dict("records"):
            key = str(row[key_col]) if key_col else ""
            if row["side"] == "buy":
                pending.setdefault(key, []).append(row)
            elif row["side"] == "sell":
                queue = pending.setdefault(key, [])
                entry = queue.pop(0) if queue else None
                buy_date = _to_date(pd.Series([entry["date"]])).iloc[0] if entry else pd.NaT
                sell_date = _to_date(pd.Series([row["date"]])).iloc[0]
                rows.append({
                    "code": row.get("code", "") if key_col else "",
                    "buy_date": buy_date.strftime("%Y-%m-%d") if pd.notna(buy_date) else "",
                    "sell_date": sell_date.strftime("%Y-%m-%d") if pd.notna(sell_date) else "",
                    "sell_reason": row.get("reason", ""),
                    "pnl": row.get("pnl"),
                    "pnl_pct": row.get("pnl_pct"),
                    "hold_days": row.get("hold_sessions"),
                })
        out = pd.DataFrame(rows, columns=columns)
        for col in ("pnl", "pnl_pct", "hold_days"):
            out[col] = pd.to_numeric(out[col], errors="coerce")
        buys = int((frame["side"].astype(str).str.lower() == "buy").sum())
        unmatched = sum(len(q) for q in pending.values())
        warnings.append(
            f"trades.csv 为事件流水格式（每行一次买卖）：{buys} 次买入、{len(out)} 次卖出；"
            f"已按标的 FIFO 配对恢复 buy_date（未平仓 {unmatched} 笔）"
        )
        return out.reset_index(drop=True), "ledger", warnings

    if "buy_date" not in frame.columns:
        return pd.DataFrame(columns=columns), "unknown", ["trades.csv 列结构未知，未能归一化"]

    hold = "hold_days" if "hold_days" in frame.columns else (
        "hold_sessions" if "hold_sessions" in frame.columns else None
    )
    if hold is None:
        warnings.append("trades.csv 缺少持仓天数列（hold_days / hold_sessions）")
    if "code" not in frame.columns:
        warnings.append("trades.csv 无 code 列（单标的策略），code 置空")
    if "sell_date" not in frame.columns:
        warnings.append("trades.csv 无 sell_date 列")

    out = pd.DataFrame({
        "code": frame["code"] if "code" in frame.columns else "",
        "buy_date": _to_date(frame["buy_date"]).dt.strftime("%Y-%m-%d").fillna(""),
        "sell_date": (_to_date(frame["sell_date"]).dt.strftime("%Y-%m-%d").fillna("")
                      if "sell_date" in frame.columns else ""),
        "sell_reason": frame["sell_reason"] if "sell_reason" in frame.columns else "",
        "pnl": pd.to_numeric(frame.get("pnl"), errors="coerce"),
        "pnl_pct": pd.to_numeric(frame.get("pnl_pct"), errors="coerce"),
        "hold_days": pd.to_numeric(frame[hold], errors="coerce") if hold else pd.NA,
    }).reset_index(drop=True)

    open_mask = out["sell_date"].fillna("") == ""
    if open_mask.any():
        out.loc[open_mask, "sell_reason"] = "(open)"
        warnings.append(f"含 {int(open_mask.sum())} 笔未平仓持仓，已标记为 (open)")
    return out, "paired", warnings


def _group_stats(trades: pd.DataFrame, group_col: str, sort: str = "pnl") -> list[dict]:
    """Win rate, average pnl and total pnl per group.

    sort="pnl" ranks by how much the group moved the needle; sort="key" keeps
    the natural group order (useful for years).
    """
    total = float(trades["pnl"].sum())
    rows = []
    for key, part in trades.groupby(group_col, dropna=False, observed=True):
        pnl = part["pnl"]
        rows.append({
            group_col: str(key),
            "n": int(len(part)),
            "win_rate_pct": round(float((pnl > 0).mean() * 100), 2),
            "avg_pnl_pct": round(float(part["pnl_pct"].mean()), 3),
            "total_pnl": round(float(pnl.sum()), 2),
            "total_pnl_share_pct": round(float(pnl.sum() / total * 100), 2) if total else None,
            "avg_hold_days": round(float(part["hold_days"].mean()), 2) if part["hold_days"].notna().any() else None,
        })
    if sort == "key":
        return sorted(rows, key=lambda r: r[group_col])
    return sorted(rows, key=lambda r: abs(r["total_pnl"]), reverse=True)


def _drawdown(nav: pd.Series, dates: pd.Series, initial: float) -> dict:
    cummax = nav.cummax().clip(lower=initial)
    dd = nav / cummax - 1
    trough = int(dd.idxmin())
    peak = int(nav.loc[:trough].idxmax())
    after = nav.loc[trough:]
    recovered = after[after >= nav.loc[peak]]
    underwater = nav < cummax
    longest = run = 0
    for flag in underwater:
        run = run + 1 if flag else 0
        longest = max(longest, run)
    return {
        "max_drawdown_pct": round(float(dd.min() * 100), 2),
        "peak_date": str(dates.loc[peak])[:10],
        "trough_date": str(dates.loc[trough])[:10],
        "recovery_date": str(dates.loc[recovered.index[0]])[:10] if len(recovered) else None,
        "longest_underwater_sessions": int(longest),
    }


def _concentration(trades: pd.DataFrame) -> dict:
    pnl = trades["pnl"].dropna().sort_values(ascending=False)
    total = float(pnl.sum())
    if pnl.empty or total <= 0:
        return {"note": "总盈亏非正，集中度不适用"}
    top_n = max(1, int(len(pnl) * 0.1))
    return {
        "top_decile_n": int(top_n),
        "top_decile_pnl": round(float(pnl.head(top_n).sum()), 2),
        "top_decile_share_pct": round(float(pnl.head(top_n).sum() / total * 100), 2),
        "losing_n": int((pnl <= 0).sum()),
    }


def _derive_metrics(nav: pd.Series, dates: pd.Series, initial: float, trades: pd.DataFrame) -> dict:
    """Fallback metrics when metrics.json is absent. Mirrors python/backtest/metrics.py."""
    final = float(nav.iloc[-1])
    n_days = len(nav)
    ret = nav.pct_change().dropna()
    cummax = nav.cummax().clip(lower=initial)
    pnl = trades["pnl"].dropna()
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    avg_win = float(trades.loc[trades["pnl"] > 0, "pnl_pct"].mean()) if len(wins) else 0.0
    avg_loss = float(trades.loc[trades["pnl"] <= 0, "pnl_pct"].mean()) if len(losses) else 0.0
    return {
        "initial_cash": round(initial, 2),
        "final_nav": round(final, 2),
        "total_return_pct": round((final / initial - 1) * 100, 2),
        "annualized_return_pct": round(((final / initial) ** (1 / (n_days / 243.0)) - 1) * 100, 2) if final > 0 else None,
        "max_drawdown_pct": round(float((nav / cummax - 1).min() * 100), 2),
        "sharpe_ratio": round(float(ret.mean() / ret.std(ddof=1) * (243 ** 0.5)), 3) if len(ret) > 1 and ret.std(ddof=1) > 0 else None,
        "closed_trade_count": int(len(pnl)),
        "win_count": int(len(wins)),
        "loss_count": int(len(losses)),
        "win_rate_pct": round(len(wins) / len(pnl) * 100, 2) if len(pnl) else None,
        "avg_win_pct": round(avg_win, 3),
        "avg_loss_pct": round(avg_loss, 3),
        "profit_loss_ratio": round(abs(avg_win / avg_loss), 3) if avg_loss < 0 else None,
        "avg_hold_sessions": round(float(trades["hold_days"].mean()), 2) if trades["hold_days"].notna().any() else None,
        "n_trading_days": int(n_days),
    }


def analyze(run_dir: Path, top_n: int, include_trades: bool) -> dict:
    warnings: list[str] = []
    if not run_dir.exists():
        return {"path": str(run_dir), "error": "目录不存在"}

    result_dir, manifest_dir = _find_result_dir(run_dir)
    if result_dir != run_dir:
        warnings.append(f"结果文件位于子目录 {result_dir.name}/（多阶段任务）")
    manifest = _load_manifest((manifest_dir / "run_manifest.json") if manifest_dir else None)
    if not manifest:
        warnings.append("未找到 run_manifest.json：任务名、费用与执行口径未知")

    files = {p.name for p in result_dir.iterdir()}

    # --- nav -------------------------------------------------------------
    nav_frame = _read_csv(result_dir / "nav.csv") if "nav.csv" in files else None
    nav_col, nav_like = (None, [])
    if nav_frame is not None and not nav_frame.empty and "__parse_error__" not in nav_frame.columns:
        nav_col, nav_like = _pick_nav_column(list(nav_frame.columns))
    if nav_col is None:
        warnings.append("未找到可用的 nav.csv")
        nav = dates = None
    else:
        if nav_col != "nav":
            warnings.append(f"nav.csv 无 nav 列，使用 {nav_col}（其他列：{', '.join(c for c in nav_like if c != nav_col)}）")
        nav = pd.to_numeric(nav_frame[nav_col], errors="coerce").dropna().reset_index(drop=True)
        dates = _to_date(nav_frame.loc[nav.index, "date"]).reset_index(drop=True)

    # --- trades ----------------------------------------------------------
    trades_files = sorted(n for n in files if n.startswith("trades") and n.endswith(".csv"))
    primary = "trades.csv" if "trades.csv" in trades_files else (
        "trades_original.csv" if "trades_original.csv" in trades_files
        else (trades_files[0] if trades_files else None)
    )
    if primary is None:
        warnings.append("未找到 trades 文件")
        if manifest.get("kind") == "research":
            warnings.append("该运行是研究任务，可能只产出汇总表而非逐笔交易")
    elif len(trades_files) > 1:
        warnings.append(f"存在多个 trades 文件，只分析 {primary}；其余：{', '.join(t for t in trades_files if t != primary)}")
    trades, trade_format, trade_warnings = _normalize_trades(
        _read_csv(result_dir / primary) if primary else None
    )
    warnings.extend(trade_warnings)

    # --- metrics ---------------------------------------------------------
    raw_metrics, source = {}, "derived"
    if "metrics.json" in files:
        try:
            raw_metrics = json.loads((result_dir / "metrics.json").read_text(encoding="utf-8"))
            source = "metrics.json"
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"metrics.json 解析失败，改为从 nav.csv 推导: {exc}")
    if source == "metrics.json":
        primary_metrics, benchmark, variants = _metric_blocks(raw_metrics)
        if not primary_metrics and not variants:
            warnings.append("metrics.json 无可识别的指标块，改为从 nav.csv 推导")
            source = "derived"
    if source == "derived":
        if nav is None or nav.empty:
            primary_metrics, benchmark, variants = {}, {}, []
        else:
            initial = float(nav.iloc[0]) if nav.iloc[0] > 0 else 200000.0
            primary_metrics = _derive_metrics(nav, dates, initial, trades)
            benchmark, variants = {}, []
            warnings.append("metrics.json 缺失，指标由 nav.csv 推导；年化按 243 交易日折算，可能与策略自身口径不同")

    initial_cash = primary_metrics.get("initial_cash")
    if initial_cash is None and nav is not None and not nav.empty:
        initial_cash = float(nav.iloc[0])

    start_date = manifest.get("start_date")
    end_date = manifest.get("end_date")
    if (not start_date or not end_date) and nav is not None and not nav.empty:
        start_date = start_date or str(dates.iloc[0])[:10]
        end_date = end_date or str(dates.iloc[-1])[:10]
        warnings.append("请求区间未知，已用 nav.csv 的实际首尾交易日代替")

    report = {
        "path": str(run_dir),
        "result_dir": str(result_dir),
        "task_id": manifest.get("task_id") or run_dir.name.split("__")[0],
        "start_date": start_date,
        "end_date": end_date,
        "execution_mode": manifest.get("execution_mode"),
        "status": manifest.get("status"),
        "git_revision": (manifest.get("git_revision") or "")[:8] or None,
        "git_dirty": manifest.get("git_dirty"),
        "fees": manifest.get("fees"),
        "metrics_source": source,
        "metrics": primary_metrics or None,
        "benchmark": benchmark or None,
        "metric_variants": {k: raw_metrics[k] for k in variants} if variants else None,
        "nav_columns": nav_like,
        "trades_source": primary,
        "trades_format": trade_format,
        "report_file": next((n for n in ("report.md", "report.txt") if n in files), None),
        "warnings": warnings,
    }

    if nav is not None and not nav.empty:
        report["drawdown"] = _drawdown(nav, dates, initial_cash or 200000.0)

    if not trades.empty:
        report["trade_count"] = int(len(trades))
        report["by_exit_reason"] = _group_stats(trades, "sell_reason")
        dated = trades.assign(
            year=(_to_date(trades["sell_date"].fillna("").replace("", pd.NA)).dt.year
                  .fillna(_to_date(trades["buy_date"]).dt.year))
        )
        report["by_year"] = _group_stats(dated.dropna(subset=["year"]).assign(year=lambda d: d["year"].astype(int)), "year", "key")
        if trades["hold_days"].notna().any():
            bucketed = trades.assign(bucket=pd.cut(
                trades["hold_days"], bins=[b[0] - 0.5 for b in HOLD_BUCKETS] + [HOLD_BUCKETS[-1][1]],
                labels=BUCKET_LABELS,
            ))
            report["by_hold_bucket"] = _group_stats(bucketed.dropna(subset=["bucket"]), "bucket")
        if trades["code"].astype(str).str.strip().any() and trades["code"].astype(str).nunique() > 1:
            report["by_symbol"] = _group_stats(trades, "code")
        report["pnl_concentration"] = _concentration(trades)
        pnl_sorted = trades.dropna(subset=["pnl"]).sort_values("pnl")
        cols = ["code", "buy_date", "sell_date", "sell_reason", "pnl", "pnl_pct", "hold_days"]
        report["worst_trades"] = pnl_sorted.head(top_n)[cols].to_dict("records")
        report["best_trades"] = pnl_sorted.tail(top_n)[cols].iloc[::-1].to_dict("records")
        if include_trades:
            report["trades"] = trades[cols].to_dict("records")
    else:
        report["trade_count"] = 0

    return report


def compare(reports: list[dict]) -> dict:
    """Align headline metrics across runs for side-by-side reading."""
    fields = [
        ("task_id", "任务"), ("start_date", "起始"), ("end_date", "结束"),
        ("execution_mode", "执行口径"), ("total_return_pct", "总收益率%"),
        ("annualized_return_pct", "年化%"), ("max_drawdown_pct", "最大回撤%"),
        ("sharpe_ratio", "夏普"), ("closed_trade_count", "交易数"),
        ("win_rate_pct", "胜率%"), ("profit_loss_ratio", "盈亏比"),
        ("avg_hold_sessions", "平均持仓"), ("exposure_pct", "资金暴露%"),
    ]
    table = {}
    for key, label in fields:
        row = []
        for rep in reports:
            metrics = rep.get("metrics") or {}
            value = rep.get(key) if key in ("task_id", "start_date", "end_date", "execution_mode") else metrics.get(key)
            row.append(value)
        table[label] = row

    notes = []
    ranges = {(r.get("start_date"), r.get("end_date")) for r in reports}
    if len(ranges) > 1:
        notes.append(
            "各运行区间不一致，收益/回撤不可直接横向比较；"
            f"区间: {', '.join(f'{s}~{e}' for s, e in sorted(ranges, key=lambda x: str(x[0])))}"
        )
    modes = {r.get("execution_mode") for r in reports}
    if len(modes) > 1:
        notes.append(f"各运行执行口径不一致: {', '.join(str(m) for m in modes)}，成交假设不同")
    return {
        "runs": [r.get("task_id") or r.get("path") for r in reports],
        "metrics": table,
        "notes": notes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("run_dirs", nargs="+", type=Path, help="回测运行目录（可多个，用于横向对比）")
    parser.add_argument("--top", type=int, default=15, help="输出最赚/最亏各前 N 笔（默认 15）")
    parser.add_argument("--trades", action="store_true", help="额外输出全部归一化逐笔交易")
    parser.add_argument("--pretty", action="store_true", help="缩进打印")
    args = parser.parse_args()

    reports = [analyze(d, args.top, args.trades) for d in args.run_dirs]
    payload = {"runs": reports}
    if len(reports) > 1:
        payload["comparison"] = compare(reports)
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
