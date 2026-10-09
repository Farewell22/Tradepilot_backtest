"""Frozen strategy-entry dates × historical A-share N pullback research."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

from python.factors.n_pullback import detect_pivots, evaluate_structure
from .data import CACHE, PREPARATION_VERSION, ROOT, SOURCE_RUN, STOCK_DIR, forward_labels, load_events, prepare_data, sha256
from .statistics import HORIZONS, event_statistics, summarize

THRESHOLDS = (.03, .05, .08)


def build_observations(daily, events, calendar):
    rows = []
    total = daily.code.nunique()
    for number, (code, raw) in enumerate(daily.groupby("code", sort=True, observed=True), 1):
        frame = raw.loc[raw.valid].sort_values("date").reset_index(drop=True)
        indices = frame.index[frame.date.isin(events)].to_numpy()
        if not len(indices):
            continue
        label_rows = forward_labels(frame, frame.loc[indices, "date"], calendar).set_index("date")
        for threshold in THRESHOLDS:
            pivots = detect_pivots(frame, threshold)
            for index in indices:
                date = frame.date.iloc[index]
                structure = evaluate_structure(frame, int(index), threshold, pivots=pivots)
                rows.append({"code": code, "date": date, "threshold": threshold,
                             **structure, **label_rows.loc[date].to_dict()})
        if number % 500 == 0:
            print(f"factors {number}/{total}", flush=True)
    if not rows:
        raise ValueError("开仓日无可用股票样本")
    return pd.DataFrame(rows).sort_values(["threshold", "date", "code"]).reset_index(drop=True)


def markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in values) + " |")
    return "\n".join(lines)


def write_report(output_dir, events, observations, summary, audit):
    selected = summary.loc[summary.threshold.eq(.05) & summary.stage.eq("all")].copy()
    selected = selected[selected.group.isin(["universe", "all_n", "intact", "broken", "intact-broken", "Q1", "Q5", "Q5-Q1", "IC"])]
    table = selected[["horizon", "group", "event_count", "stock_observations", "mean_return", "mean_excess", "win_rate", "mean_mae", "ci_low", "ci_high", "clusters"]].copy()
    numeric = ["mean_return", "mean_excess", "win_rate", "mean_mae", "ci_low", "ci_high"]
    for name in numeric:
        table[name] = table[name].mul(np.where(selected.group.eq("IC"), 1., 100.)).round(4)
    table.columns = ["窗口", "组", "日期数", "股票观察数", "平均收益%/IC", "超额收益%", "上涨比例%", "平均MAE%", "下界%/IC", "上界%/IC", "时间簇"]
    counts = observations.loc[observations.threshold.eq(.05)].status.value_counts()
    robust = summary.loc[summary.stage.eq("all") & summary.group.isin(["intact-broken", "Q5-Q1", "IC"]),
                         ["threshold", "horizon", "group", "event_count", "mean_return", "ci_low", "ci_high"]].copy()
    for name in ("mean_return", "ci_low", "ci_high"):
        robust[name] = robust[name].round(6)
    stage = summary.loc[summary.threshold.eq(.05) & summary.group.isin(["intact-broken", "Q5-Q1", "IC"])
                        & ~summary.stage.eq("all"), ["stage", "horizon", "group", "event_count", "mean_return"]].copy()
    stage["mean_return"] = stage.mean_return.round(6)
    lines = ["# 三轮N型守前低：AMV主仓开仓日截面研究", "",
             f"观察日期：{events.min().date()}—{events.max().date()}，共{len(events)}个冻结主仓实际开仓日。", "",
             "## 定义与口径", "",
             "F=min(L1/L0−1,L2/L1−1,L3/L2−1)，H1<H2<H3且每段上涨幅度为正；日内反弹确认后跳空导致的零/负上涨腿记为非N型。5%收盘反转确认波段，第三轮低点截至当日计算；收盘突破H3不再视为当前回调。252根有效日K窗口，504个市场日预热。", "",
             "收益为观察日次一市场交易日开盘到第5/10/20个市场交易日收盘的复权价格收益，不计费用；缺失端点不顺延。基准为同日、同窗口、满足252根历史的全部可用A股等权收益，不要求N型。", "",
             "逐日期先计算截面均值，再日期等权汇总。上涨比例为个股上涨比例的日期平均；不是策略交易胜率。MAE为完整窗口内最低价/次日开盘−1，正值意味着整个窗口最低价仍高于入场开盘；缺失中间日不估计MAE。", "",
             "均值95%区间按重叠收益窗口连接成簇，簇bootstrap 2000次、种子42；少于10簇不报区间。IC行以相关系数而非百分数显示。", "",
             "## 全区间结果（5%波段）", "", markdown_table(table), "",
             "## 因子覆盖", "", markdown_table(counts.rename_axis("status").rename("observations").reset_index()), "",
             "## 预定3%/8%稳健性（下表收益为小数，IC为系数）", "", markdown_table(robust), "",
             "## 年度与分阶段（收益为小数，IC为系数）", "", markdown_table(stage), "",
             "## 数据审计与限制", "",
             f"- 数据与源文件SHA-256见input_audit.json；记录{len(audit)}个源/缓存项。原策略同日收盘口径只用于选取日期，本研究不使用其成交价或卖出规则。",
             "- 批量获取时Tushare账号返回40203限频，实际复权来源改为新浪公开hfq.js事件；明确事件自生效日起延续，不填造未知事件。来源与取得时间保存在缓存及审计中，复权缺失不降级。",
             "- 证券类型修正：689xxx为科创板存托凭证，排除出A股股票池；原始日线缓存保留，审计逐日记录excluded_cdr_rows。依据[上交所2020年市场资料第23页](https://www.sse.com.cn/aboutus/publication/factbook/documents/c/10170562/files/da4f403a0b7443fa9b2ba2e002d38f10.pdf)。",
             "- 股票池来自当日历史行情，不使用当前上市名单。保留ST；历史ST、涨跌停可成交性和退市清算收益未建模。退市等缺失标签不能视为零收益，需结合missing_labels和coverage.csv解释。",
             "- 有效日K要求完整48根5分钟记录（可额外有09:30）；无效日不造价。缺失/停牌日会使有效日K窗口跨越更长自然时间，结构仍可能受数据覆盖选择影响。",
             "- 股票×日期数量不等于独立时间样本；分阶段比较是描述性检验，不把已经看过的2024—2025年宣传为严格未知样本外。多窗口/阈值未作多重检验校正，不依据收益优化参数。",
             "- 相同因子值按平均秩分组，不拆同分；因此部分日期可能没有完整五组。结构不足等状态是缺失因子，不是低分。", "",
             "## 产物", "",
             "observations.parquet：所有状态、因子、标签及逐轮明细；events.csv：冻结开仓日；coverage.csv：逐日状态计数；event_statistics.csv：逐日截面统计；summary.csv：日期等权汇总；input_audit.json与source_snapshot/：复现依据；figures/：分组收益图及最多12张典型结构图。", ""]
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def load_prepared(events, cache, stock_dir):
    prepared = cache / "prepared.parquet"
    manifest_path = cache / "preparation_manifest.json"
    if prepared.exists() and manifest_path.exists():
        meta = json.loads(manifest_path.read_text())
        cached_events = pd.DatetimeIndex(pd.to_datetime(meta.get("events", [])))
        if (meta.get("preparation_version") == PREPARATION_VERSION
                and events.isin(cached_events).all() and meta.get("prepared_sha256") == sha256(prepared)):
            for record in meta["audits"]:
                path = Path(record.get("source_path", record.get("path", "")))
                checksum = record.get("source_sha256", record.get("sha256"))
                if not path.is_file() or sha256(path) != checksum:
                    raise ValueError(f"输入源已改变，请重新准备缓存: {path}")
            paths = sorted(stock_dir.glob("*/*.parquet"))
            calendar = pd.DatetimeIndex([pd.Timestamp(p.stem) for p in paths])
            return pd.read_parquet(prepared), calendar, meta["audits"]
    return prepare_data(events, stock_dir, cache)


def run_research(output_dir: Path, *, start_date="20200101", end_date="20251231",
                 source_run: Path = SOURCE_RUN, stock_dir: Path = STOCK_DIR, cache: Path = CACHE,
                 prepared_daily=None, calendar=None, bootstrap_repeats=2000, render=True) -> Path:
    events = load_events(source_run, start_date, end_date)
    output_dir.mkdir(parents=True, exist_ok=True)
    if prepared_daily is None:
        daily, calendar, audit = load_prepared(events, cache, stock_dir)
    else:
        if calendar is None:
            raise ValueError("注入行情必须同时提供市场日历")
        daily, audit = prepared_daily.copy(), []
    daily = daily.sort_values(["code", "date"]).reset_index(drop=True)
    daily["code"] = daily.code.astype("category")
    observations = build_observations(daily, events, calendar)
    if not observations.date.isin(events).all():
        raise AssertionError("观察日期越出冻结开仓日期")
    for threshold in THRESHOLDS:
        observed_dates = observations.loc[observations.threshold.eq(threshold), "date"]
        missing = events[~events.isin(observed_dates)]
        if len(missing):
            raise ValueError(f"波段阈值{threshold}缺失完整开仓日: {missing.strftime('%Y-%m-%d').tolist()}")
    observations.to_parquet(output_dir / "observations.parquet", index=False)
    pd.DataFrame({"date": events}).to_csv(output_dir / "events.csv", index=False)
    coverage = observations.groupby(["threshold", "date", "status"]).size().rename("n").reset_index()
    coverage.to_csv(output_dir / "coverage.csv", index=False)
    events_stats = event_statistics(observations)
    summary = summarize(events_stats, calendar, repeats=bootstrap_repeats)
    events_stats.to_csv(output_dir / "event_statistics.csv", index=False)
    summary.to_csv(output_dir / "summary.csv", index=False)
    source_files = [source_run / "run_manifest.json", source_run / "trades_601288.SH.csv"]
    audit.extend({"source_path": str(p.resolve()), "source_sha256": sha256(p)} for p in source_files)
    (output_dir / "input_audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    sources = [Path(__file__), Path(__file__).with_name("data.py"), Path(__file__).with_name("statistics.py"),
               Path(__file__).with_name("plots.py"), ROOT / "python/factors/n_pullback.py",
               ROOT / "python/task_registry.py", ROOT / "python/run_backtest.py"]
    code_hashes = {}
    for source in sources:
        if source.exists():
            target = output_dir / "source_snapshot" / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            code_hashes[str(source.relative_to(ROOT))] = sha256(target)
    (output_dir / "source_snapshot/manifest.json").write_text(json.dumps(code_hashes, indent=2) + "\n")
    (output_dir / "research_metadata.json").write_text(json.dumps({
        "source_run": str(source_run), "source_execution_mode": "legacy_same_close_idealized",
        "factor_mode": "causal_close_confirmed_reversal", "label_mode": "next_market_open_adjusted_price",
        "adjustment_provider": "sina_hfq_events", "universe_excludes": ["689xxx.SH CDR"], "thresholds": THRESHOLDS, "horizons": HORIZONS,
        "event_count": len(events), "bootstrap_repeats": bootstrap_repeats, "bootstrap_seed": 42,
        "observation_count": len(observations)}, indent=2) + "\n")
    write_report(output_dir, events, observations, summary, audit)
    if render:
        from .plots import render_figures
        render_figures(output_dir, daily, observations, summary)
    print(f"research complete: {output_dir}; events={len(events)} rows={len(observations)}", flush=True)
    return output_dir
