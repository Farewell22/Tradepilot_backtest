"""RS20 rolling percentile versus two ETFs' future total returns."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

from python.factors.relative_strength import forward_return, relative_strength, rolling_percentile, total_return_index
from .statistics import (BLOCK_LENGTH, BOOTSTRAP_REPEATS, HORIZONS, SEED, analyze, bootstrap_effects)

ROOT = Path(__file__).resolve().parents[4]
TASK_DIR = Path(__file__).resolve().parent
CODES = ("512100.SH", "510050.SH")
KNOWN_SUSPENSIONS = {"512100.SH": {pd.Timestamp("2022-09-02")}, "510050.SH": set()}


def daily_prices(raw: pd.DataFrame) -> pd.DataFrame:
    aliases = {"时间": "timestamp", "日期": "timestamp", "date": "timestamp", "开盘价": "open",
               "收盘价": "close", "最高价": "high", "最低价": "low", "成交量": "volume"}
    frame = raw.rename(columns=aliases).copy()
    required = ["timestamp", "open", "close", "high", "low", "volume"]
    if not set(required).issubset(frame):
        raise ValueError(f"60分钟行情缺少列: {set(required) - set(frame.columns)}")
    frame = frame[required]
    frame["timestamp"] = pd.to_datetime(frame.timestamp, errors="raise")
    if frame.timestamp.isna().any() or frame.timestamp.duplicated().any():
        raise ValueError("行情时间必须有效且唯一")
    for col in required[1:]:
        frame[col] = pd.to_numeric(frame[col], errors="raise")
    if not np.isfinite(frame[required[1:]].to_numpy(dtype=float)).all():
        raise ValueError("行情价格及成交量必须有限")
    if (frame[["open", "close", "high", "low"]] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError("行情价格必须为正，成交量非负")
    if ((frame.high < frame[["open", "close", "low"]].max(axis=1)) |
            (frame.low > frame[["open", "close", "high"]].min(axis=1))).any():
        raise ValueError("行情OHLC范围无效")
    frame = frame.sort_values("timestamp")
    frame["date"] = frame.timestamp.dt.normalize()
    daily = frame.groupby("date", sort=True).agg(open=("open", "first"), close=("close", "last"),
                                                 volume=("volume", "sum"), bars=("timestamp", "size"))
    if daily.empty or not daily.bars.eq(4).all():
        raise ValueError("每日应有完整4根60分钟K线")
    expected = {"10:30:00", "11:30:00", "14:00:00", "15:00:00"}
    slots = frame.timestamp.dt.strftime("%H:%M:%S").groupby(frame.date).agg(set)
    if not slots.map(lambda values: values == expected).all():
        raise ValueError("60分钟行情时段必须为10:30、11:30、14:00、15:00")
    return daily.reset_index()


def align_daily(daily: dict[str, pd.DataFrame]):
    if set(daily) != set(CODES):
        raise ValueError("研究需要512100和510050的行情")
    frames = {code: frame.set_index("date").sort_index() for code, frame in daily.items()}
    if any(frame.empty for frame in frames.values()):
        raise ValueError("两只ETF没有共同日期")
    for frame in frames.values():
        if frame.index.has_duplicates or frame.index.isna().any():
            raise ValueError("ETF日线日期必须唯一且有效")
    if not frames[CODES[0]].index.equals(frames[CODES[1]].index):
        raise ValueError("两只ETF出现未知日期缺口，不允许压缩交易窗口")
    start, end = frames[CODES[0]].index.min(), frames[CODES[0]].index.max()
    excluded = set()
    for code, frame in frames.items():
        zero = set(frame.index[frame.volume.le(0)])
        unknown = zero - KNOWN_SUSPENSIONS[code]
        if unknown:
            raise ValueError(f"{code}存在未知零成交日期: {sorted(unknown)}")
        excluded.update(zero)
    aligned = {code: frame.loc[~frame.index.isin(excluded)].reset_index() for code, frame in frames.items()}
    audit = {"common_raw_start": str(start.date()), "common_raw_end": str(end.date()),
             "common_raw_sessions": len(frames[CODES[0]]),
             "common_valid_sessions": len(aligned[CODES[0]]),
             "excluded_common_dates": [str(date.date()) for date in sorted(excluded)],
             "calendar": "shared positive-volume ETF sessions; unknown mismatches fail"}
    return aligned, audit


def build_observations(small: pd.Series, large: pd.Series, start_date: str, end_date: str,
                       *, horizons=HORIZONS) -> pd.DataFrame:
    rows = pd.DataFrame({"date": small.index, "session_index": np.arange(len(small)),
                         "total_return_1000": small.to_numpy(), "total_return_50": large.to_numpy()})
    rs = relative_strength(small, large)
    percentile = rolling_percentile(rs)
    rows["past_return_1000_20d"] = (small / small.shift(20) - 1).to_numpy()
    rows["past_return_50_20d"] = (large / large.shift(20) - 1).to_numpy()
    rows["rs20"] = rs.to_numpy()
    rows["rs20_percentile"] = percentile.to_numpy()
    rows["percentile_bin"] = (np.floor(percentile / 10).clip(upper=9) + 1).to_numpy()
    for horizon in horizons:
        rows[f"exit_date_{horizon}d"] = pd.Series(small.index).shift(-horizon)
        rows[f"return_1000_{horizon}d"] = forward_return(small, horizon).to_numpy()
        rows[f"return_50_{horizon}d"] = forward_return(large, horizon).to_numpy()
        rows[f"spread_{horizon}d"] = rows[f"return_1000_{horizon}d"] - rows[f"return_50_{horizon}d"]
    # Build history and labels first: requested dates constrain observations only.
    rows = rows.loc[rows.date.between(pd.Timestamp(start_date), pd.Timestamp(end_date)) &
                    rows.rs20_percentile.notna()].copy()
    rows["percentile_bin"] = rows.percentile_bin.astype(int)
    return rows.reset_index(drop=True)


def load_actions(path: Path) -> pd.DataFrame:
    events = pd.read_csv(path, keep_default_na=False)
    required = {"code", "kind", "record_date", "ex_date", "pay_date", "price_effective_date",
                "cash_per_share", "share_ratio", "source_url"}
    if not required.issubset(events):
        raise ValueError(f"公司行动表缺少列: {required - set(events.columns)}")
    for row in events.itertuples(index=False):
        record, ex, quote = map(pd.Timestamp, (row.record_date, row.ex_date, row.price_effective_date))
        if row.code not in CODES or row.kind not in {"dividend", "consolidation"}:
            raise ValueError("公司行动代码或类型无效")
        if pd.isna(record) or pd.isna(ex) or pd.isna(quote) or record >= ex or quote < ex:
            raise ValueError("公司行动日期顺序无效")
        if not row.source_url or float(row.share_ratio) <= 0 or float(row.cash_per_share) < 0:
            raise ValueError("公司行动必须有来源及有效比例/金额")
        if row.kind == "dividend" and (quote != ex or float(row.share_ratio) != 1):
            raise ValueError("派息必须在除息日计入且份额比例为1")
        if row.kind == "consolidation" and float(row.cash_per_share) != 0:
            raise ValueError("份额合并不应包含现金派息")
    return events


def _snapshot(output_dir: Path, inputs: list[Path]):
    hashes = {"inputs": {}, "code": {}}
    for path in inputs:
        target = output_dir / "inputs" / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes["inputs"][str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    sources = [ROOT / "python/factors/relative_strength.py", ROOT / "python/task_registry.py",
               ROOT / "python/run_backtest.py", ROOT / "python/backtest/report_publication.py",
               ROOT / "python/requirements.txt", ROOT / "scripts/backtest.sh", *TASK_DIR.glob("*.py")]
    for path in sources:
        relative = path.relative_to(ROOT)
        target = output_dir / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        hashes["code"][str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output_dir / "execution_metadata.json").write_text(json.dumps(hashes, indent=2, ensure_ascii=False), encoding="utf-8")


def format_report(rows, summary, effects, audit, metadata, output_dir):
    columns = ["target", "horizon", "labeled", "spearman_ic", "ic_ci_low", "ic_ci_high",
               "high_minus_low_pct", "spread_ci_low_pct", "spread_ci_high_pct",
               "nonoverlap_ic_min", "nonoverlap_ic_max"]
    table = effects.loc[effects.stage.eq("all"), columns].round(4).to_markdown(index=False)
    report = f"""# RS20滚动百分位与中证1000／上证50远期收益

观察区间：{metadata['actual_start']}—{metadata['actual_end']}，共{len(rows)}个有效共同交易日。
对象：512100.SH与510050.SH。每日收盘计算RS20＝两只ETF过去20个共同交易日总收益之差，
再计算包含当日的100日经验百分位；相同值取中间位置。P90表示相对强度处于近期高位，
不代表小盘已经上涨，也不代表随后一定上涨。

未来5、10、20、60日收益为总收益指数T(t+H)/T(t)−1，从当日收盘起算。
1000与50是各自绝对收益，spread是1000减50的收益差。费用为零；这是预测关系研究。

## 全样本效应

{table}

相关系数为时间序列Spearman；最高档减最低档为各组平均远期收益差（百分点）。
95%置信区间使用{metadata['block_length']}日移动分块bootstrap、{metadata['bootstrap_repeats']}次重复、随机种子{metadata['bootstrap_seed']}；
不足240个有效观测不计算区间。年度结果仅描述；全样本及两个时期计算区间。
非重叠IC范围包含全部H个起始相位，不能挑选其中最好的一组解释有效性。

## 百分位十档条件收益

"""
    for target, title in (("1000", "中证1000"), ("50", "上证50"), ("spread", "中证1000减上证50")):
        groups = summary.loc[summary.stage.eq("all") & summary.target.eq(target)]
        report += f"### {title}\n\n"
        report += groups[["percentile_bin", "horizon", "labeled", "missing_labels", "mean_pct", "median_pct",
                          "positive_rate_pct", "p10_pct", "p90_pct", "baseline_mean_pct",
                          "mean_minus_baseline_pct"]].round(3).to_markdown(index=False) + "\n\n"
    report += "## 年度与时期检查\n\n"
    report += "### 时期效应及95%区间\n\n"
    report += effects.loc[effects.stage.isin(["2020_2023", "2024_2025"]),
                          ["stage", *columns]].round(4).to_markdown(index=False)
    report += "\n\n### 年度描述统计\n\n"
    report += effects.loc[effects.stage.str.fullmatch(r"\d{4}"),
                          ["stage", "target", "horizon", "labeled", "baseline_mean_pct", "spearman_ic",
                           "high_minus_low_pct"]].round(4).to_markdown(index=False)
    report += f"\n\n![分组收益曲线]({(output_dir / 'quantile_returns.png').resolve()})\n\n"
    report += f"![年度相关性]({(output_dir / 'annual_stability.png').resolve()})\n\n"
    report += "## 数据口径及局限\n\n"
    report += f"- 行情未复权，份额合并和现金分红通过公司行动表独立校正；零成交剔除日：{audit['excluded_common_dates']}。\n"
    report += f"- 未来不足标签数：{metadata['missing_labels_by_horizon']}。每个期限单独处理，不按60日统一删样本。\n"
    report += "- 分红按除息日收盘立即再投资，忽略现金实际到账延迟；份额按连续比例计算，忽略账户零碎份额进位。\n"
    report += "- 2022-09-02停牌报价仍为旧份额口径，合并比例0.36555在2022-09-05复牌新报价边界应用。\n"
    report += "- 交易日按共同有效ETF交易日计数，跨停牌日的期限与交易所自然交易日相差一天。\n"
    report += "- 2020—2023与2024—2025是时间稳定性检查，未使用后段拟合阈值，也不称为未触碰样本外。\n"
    report += "- 每日远期窗口重叠；多期限、多收益目标为探索比较，不能凭单个显著值选规则。\n"
    report += "- 两只ETF同时包含行业及风格差异，结果是组合关联与预测性，不能归因为纯市值效应或因果关系。\n"
    report += "- 官方事件与核对来源见corporate_action_audit.json；逐日观察、分组、年度、全部非重叠相位、输入及代码校验值均随运行保存。\n"
    return report


def run_research(etf_dir: Path, output_dir: Path, *, start_date="20200101", end_date="20251231",
                 actions_path: Path | None = None, action_audit_path: Path | None = None,
                 bootstrap_repeats=BOOTSTRAP_REPEATS) -> Path:
    actions_path = actions_path or TASK_DIR / "corporate_actions.csv"
    action_audit_path = action_audit_path or TASK_DIR / "corporate_action_audit.json"
    action_audit = json.loads(action_audit_path.read_text(encoding="utf-8"))
    start, end = pd.Timestamp(start_date), pd.Timestamp(end_date)
    lower, upper = map(pd.Timestamp, (action_audit["coverage_start"], action_audit["coverage_end"]))
    if start > end or start < lower or end > upper:
        raise ValueError("请求日期超出公司行动核对范围或顺序无效")
    actions = load_actions(actions_path)
    daily = {}
    outside_rows = {}
    for code in CODES:
        raw = pd.read_csv(etf_dir / f"{code}.csv")
        timestamp_column = next((col for col in ("时间", "timestamp", "date", "日期") if col in raw), None)
        if timestamp_column is None:
            raise ValueError("行情缺少时间列")
        dates = pd.to_datetime(raw[timestamp_column], errors="raise").dt.normalize()
        if dates.isna().any():
            raise ValueError("行情日期不能为空")
        selected = dates.between(lower, upper)
        outside_rows[code] = int((~selected).sum())
        daily[code] = daily_prices(raw.loc[selected])
    aligned, audit = align_daily(daily)
    totals = {code: total_return_index(aligned[code], actions.loc[actions.code.eq(code)]) for code in CODES}
    rows = build_observations(totals[CODES[0]], totals[CODES[1]], start_date, end_date)
    if rows.empty:
        raise ValueError("所选日期无完成119日预热的研究观测")
    summary, effects, phases = analyze(rows, bootstrap_repeats=bootstrap_repeats)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in (("observations.csv", rows), ("summary.csv", summary), ("effects.csv", effects), ("nonoverlap.csv", phases)):
        frame.to_csv(output_dir / filename, index=False, encoding="utf-8-sig")
    audit["corporate_actions"] = action_audit
    audit["intraday_rows_outside_audited_coverage"] = outside_rows
    audit["rows_before_scope"] = len(totals[CODES[0]])
    metadata = {"task_id": "etf_size_rs20_percentile", "codes": CODES, "requested_start": str(start.date()),
                "requested_end": str(end.date()), "actual_start": str(rows.date.min().date()),
                "actual_end": str(rows.date.max().date()), "observations": len(rows),
                "factor": "RS20 = T1000(t)/T1000(t-20) - T50(t)/T50(t-20)",
                "percentile": "100 * (count(value < current) + 0.5 * count(value == current)) / 100; t-99..t",
                "return": "T_i(t+H)/T_i(t)-1; current close to future close; ex-close cash reinvestment",
                "horizons": HORIZONS, "percentile_window": 100, "lookback": 20, "warmup_sessions": 119,
                "block_length": BLOCK_LENGTH, "bootstrap_repeats": bootstrap_repeats, "bootstrap_seed": SEED,
                "confidence_level": .95, "fees_applied": False, "annual_confidence_intervals": False,
                "missing_labels_by_horizon": {str(h): int(rows[f"return_1000_{h}d"].isna().sum()) for h in HORIZONS}}
    for file, content in (("data_audit.json", audit), ("metadata.json", metadata)):
        (output_dir / file).write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    _snapshot(output_dir, [*(etf_dir / f"{code}.csv" for code in CODES), actions_path, action_audit_path])
    from .plots import write_figures
    write_figures(summary, effects, output_dir)
    (output_dir / "report.md").write_text(format_report(rows, summary, effects, audit, metadata, output_dir), encoding="utf-8")
    return output_dir
