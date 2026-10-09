"""Auditable event study using reviewed policy text and as-of ETF links."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
import shutil
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from python.factors.relative_strength import total_return_index


ROOT = Path(__file__).resolve().parents[4]
TASK_DIR = Path(__file__).resolve().parent
HORIZONS = (20, 60, 120, 250)
BENCHMARK = "510300.SH"
BAR_TIMES = {"10:30:00", "11:30:00", "14:00:00", "15:00:00"}
CHINA = ZoneInfo("Asia/Shanghai")
ACTION_COLUMNS = ["code", "kind", "record_date", "ex_date", "pay_date", "price_effective_date",
                  "cash_per_share", "share_ratio", "source_url"]


def daily_prices(path: Path) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig")
    raw = raw.rename(columns={"时间": "timestamp", "开盘价": "open", "收盘价": "close", "成交量": "volume"})
    required = {"timestamp", "open", "close", "volume"}
    if not required.issubset(raw):
        raise ValueError(f"{path.name} 缺少列: {sorted(required - set(raw))}")
    raw["timestamp"] = pd.to_datetime(raw.timestamp, errors="raise")
    for col in ("open", "close", "volume"):
        raw[col] = pd.to_numeric(raw[col], errors="raise")
    if (raw.timestamp.isna().any() or raw.timestamp.duplicated().any() or
            not np.isfinite(raw[["open", "close", "volume"]].to_numpy()).all() or
            (raw[["open", "close"]] <= 0).any().any() or (raw.volume < 0).any()):
        raise ValueError(f"{path.name} 行情日期、价格或成交量无效")
    raw = raw.sort_values("timestamp")
    raw["date"] = raw.timestamp.dt.normalize()
    grouped = raw.groupby("date")
    slots = raw.timestamp.dt.strftime("%H:%M:%S").groupby(raw.date).agg(set)
    daily = grouped.agg(open=("open", "first"), close=("close", "last"), volume=("volume", "sum"))
    daily["bars_complete"] = grouped.size().eq(4) & slots.map(lambda values: values == BAR_TIMES)
    return daily.reset_index()


def load_events(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"缺少已审核政策导出: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len({row["event_id"] for row in rows}) != len(rows):
        raise ValueError("政策导出存在重复 event_id")
    if path.name == "approved_events.jsonl":
        expected = []
        for pointer_path in sorted((path.parent / "documents").glob("*/current_approval.txt")):
            version = pointer_path.read_text(encoding="utf-8").strip()
            approval = json.loads((pointer_path.parent / "approved" / f"{version}.json").read_text(encoding="utf-8"))
            stable = {key: value for key, value in approval.items() if key != "approved_at"}
            digest = hashlib.sha256((json.dumps(stable, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()).hexdigest()[:16]
            if digest != version:
                raise ValueError("政策审批快照被改动")
            expected.extend({**event, "approval_version": version} for event in approval["events"])
        if rows != expected:
            raise ValueError("政策导出不是当前审批事件的完整集合，请重新 export")
    for row in rows:
        if row.get("review_status") != "approved" or not row.get("approval_version"):
            raise ValueError("研究仅接受经审核的政策事件")
        if path.name == "approved_events.jsonl":
            folder = path.parent / "documents" / row["document_id"]
            pointer = (folder / "current_approval.txt").read_text(encoding="utf-8").strip()
            if pointer != row["approval_version"]:
                raise ValueError("政策导出与当前审批版本不一致，请重新 export")
            approved = json.loads((folder / "approved" / f"{pointer}.json").read_text(encoding="utf-8"))
            stable = {key: value for key, value in approved.items() if key != "approved_at"}
            digest = hashlib.sha256((json.dumps(stable, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()).hexdigest()[:16]
            if digest != pointer or row not in [{**event, "approval_version": pointer} for event in approved["events"]]:
                raise ValueError("政策审批快照或导出被改动")
            own_raw = next((folder / "raw").glob(f"{row['raw_sha256']}.*"), None)
            own_body = folder / f"{row['raw_sha256']}.txt"
            if (own_raw is None or hashlib.sha256(own_raw.read_bytes()).hexdigest() != row["raw_sha256"] or
                    not own_body.is_file() or hashlib.sha256(own_body.read_bytes()).hexdigest() != approved["body_sha256"]):
                raise ValueError("当前政策原文或正文快照与审批记录不一致")
            early = row.get("first_public_evidence")
            if row["first_public_url"] != row["source_url"]:
                if not early:
                    raise ValueError("较早来源缺少审批时的证据快照")
                early_dir = path.parent / "documents" / early["document_id"]
                early_raw = early_dir / early["raw_file"]
                early_body = early_dir / early["body_file"]
                if (not early_raw.is_file() or not early_body.is_file() or
                        hashlib.sha256(early_raw.read_bytes()).hexdigest() != early["raw_sha256"] or
                        hashlib.sha256(early_body.read_bytes()).hexdigest() != early["body_sha256"]):
                    raise ValueError("较早政策来源与审批时快照不一致")
    return rows


def load_action_book(actions_path: Path, audit_path: Path) -> tuple[pd.DataFrame, dict]:
    actions = pd.read_csv(actions_path, keep_default_na=False)
    if not set(ACTION_COLUMNS).issubset(actions):
        raise ValueError("公司行动表缺少必需列")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    if not isinstance(audit.get("funds"), dict):
        raise ValueError("公司行动审计缺少 funds")
    if actions.duplicated(["code", "kind", "price_effective_date"]).any():
        raise ValueError("公司行动表存在重复生效日")
    for row in actions.itertuples(index=False):
        if row.kind not in {"dividend", "consolidation", "split"} or not row.source_url:
            raise ValueError("公司行动类型或来源无效")
        record, ex, effective = map(pd.Timestamp, (row.record_date, row.ex_date, row.price_effective_date))
        ratio, cash = float(row.share_ratio), float(row.cash_per_share)
        if record >= ex or effective < ex or ratio <= 0 or cash < 0:
            raise ValueError("公司行动日期、比例或现金无效")
        if row.kind == "dividend" and (not row.pay_date or pd.Timestamp(row.pay_date) < ex or cash <= 0 or ratio != 1 or effective != ex):
            raise ValueError("派息日期、金额或份额比例无效")
        if row.kind in {"consolidation", "split"} and cash != 0:
            raise ValueError("拆并份额不能同时记入现金派息")
    return actions, audit


def _entry_date(public_at: str, sessions: pd.DatetimeIndex) -> pd.Timestamp | None:
    public = datetime.fromisoformat(public_at)
    if public.tzinfo is not None:
        public = public.astimezone(CHINA)
    day = pd.Timestamp(public.date())
    # An unqualified date is conservatively visible only after that close.
    before_open = len(public_at) > 10 and public.timetz().replace(tzinfo=None) < time(9, 30)
    candidate = sessions[(sessions >= day) if before_open else (sessions > day)]
    return candidate[0] if len(candidate) else None


def _audit_reason(code: str, entry: pd.Timestamp, exit_date: pd.Timestamp, audit: dict) -> str | None:
    record = audit.get("funds", {}).get(code)
    if not record or record.get("status") != "verified" or not record.get("source_url"):
        return "CORPORATE_ACTION_AUDIT_MISSING"
    if pd.Timestamp(record["coverage_start"]) > entry or pd.Timestamp(record["coverage_end"]) < exit_date:
        return "CORPORATE_ACTION_AUDIT_OUT_OF_RANGE"
    return None


def event_window(event: dict, code: str, daily: pd.DataFrame, benchmark: pd.DataFrame,
                 actions: pd.DataFrame, audit: dict, horizon: int) -> dict:
    base = {"event_id": event["event_id"], "document_id": event["document_id"],
            "first_public_at": event["first_public_at"], "theme_id": event["theme_id"],
            "industry_id": event["industry_id"], "support_type": event["support_type"],
            "change_vs_previous": event["change_vs_previous"], "policy_direction": event.get("policy_direction"),
            "new_support": event.get("new_support"),
            "etf_code": code, "horizon": horizon,
            "entry_date": None, "exit_date": None, "etf_return": None,
            "benchmark_return": None, "excess_return": None, "pre20_excess": None, "missing_reason": None}
    own = daily.set_index("date").sort_index()
    ref = benchmark.set_index("date").sort_index()
    if own.empty or ref.empty:
        base["missing_reason"] = "PRICE_FILE_MISSING"
        return base
    sessions = ref.index
    entry = _entry_date(event["first_public_at"], sessions)
    if entry is None:
        base["missing_reason"] = "NO_POST_EVENT_SESSION"
        return base
    base["entry_date"] = entry.strftime("%Y-%m-%d")
    if (entry not in own.index or own.at[entry, "volume"] <= 0 or ref.at[entry, "volume"] <= 0 or
            ("bars_complete" in own and not own.at[entry, "bars_complete"]) or
            ("bars_complete" in ref and not ref.at[entry, "bars_complete"])):
        base["missing_reason"] = "ENTRY_NOT_TRADABLE"
        return base
    position = sessions.get_loc(entry)
    if position + horizon - 1 >= len(sessions):
        base["missing_reason"] = "WINDOW_NOT_MATURE"
        return base
    exit_date = sessions[position + horizon - 1]
    base["exit_date"] = exit_date.strftime("%Y-%m-%d")
    selected = sessions[position:position + horizon]
    if not selected.isin(own.index).all() or (own.loc[selected, "volume"] <= 0).any() or (ref.loc[selected, "volume"] <= 0).any():
        base["missing_reason"] = "MISSING_OR_SUSPENDED_SESSION"
        return base
    if (("bars_complete" in own and not own.loc[selected, "bars_complete"].all()) or
            ("bars_complete" in ref and not ref.loc[selected, "bars_complete"].all())):
        base["missing_reason"] = "INCOMPLETE_INTRADAY_BARS"
        return base
    for audited_code in (code, BENCHMARK):
        reason = _audit_reason(audited_code, entry, exit_date, audit)
        if reason:
            base["missing_reason"] = reason + ":" + audited_code
            return base
    def combined_actions(fund_code: str) -> pd.DataFrame:
        subset = actions.loc[actions.code.eq(fund_code)].copy()
        if subset.empty:
            return subset
        subset["share_ratio"] = pd.to_numeric(subset.share_ratio)
        subset["cash_per_share"] = pd.to_numeric(subset.cash_per_share)
        return subset.groupby("price_effective_date", as_index=False).agg(
            share_ratio=("share_ratio", "prod"), cash_per_share=("cash_per_share", "sum"))

    own_actions = combined_actions(code)
    ref_actions = combined_actions(BENCHMARK)
    own_index = total_return_index(own.loc[entry:exit_date].reset_index(), own_actions)
    ref_index = total_return_index(ref.loc[entry:exit_date].reset_index(), ref_actions)
    own_return = own_index.at[exit_date] / own_index.at[entry] * own.at[entry, "close"] / own.at[entry, "open"] - 1
    ref_return = ref_index.at[exit_date] / ref_index.at[entry] * ref.at[entry, "close"] / ref.at[entry, "open"] - 1
    base.update(etf_return=float(own_return), benchmark_return=float(ref_return),
                excess_return=float(own_return - ref_return))
    if position >= 21:
        pre_start, pre_end = sessions[position - 21], sessions[position - 1]
        pre_sessions = sessions[position - 21:position]
        if (pre_start in own.index and pre_sessions.isin(own.index).all() and
                own.loc[pre_sessions, "volume"].gt(0).all() and ref.loc[pre_sessions, "volume"].gt(0).all() and
                ("bars_complete" not in own or own.loc[pre_sessions, "bars_complete"].all()) and
                ("bars_complete" not in ref or ref.loc[pre_sessions, "bars_complete"].all()) and
                _audit_reason(code, pre_start, pre_end, audit) is None and
                _audit_reason(BENCHMARK, pre_start, pre_end, audit) is None):
            past_own = total_return_index(own.loc[pre_start:pre_end].reset_index(), own_actions)
            past_ref = total_return_index(ref.loc[pre_start:pre_end].reset_index(), ref_actions)
            pre_own = past_own.at[pre_end] / past_own.at[pre_start] - 1
            pre_ref = past_ref.at[pre_end] / past_ref.at[pre_start] - 1
            base["pre20_excess"] = float(pre_own - pre_ref)
    return base


def _csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows).reindex(columns=columns).to_csv(path, index=False, encoding="utf-8-sig")


def run_research(events_path: Path, etf_dir: Path, actions_path: Path, audit_path: Path,
                 output_dir: Path, *, start_date: str, end_date: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    events = load_events(events_path)
    actions, audit = load_action_book(actions_path, audit_path)
    def local_event_day(row: dict) -> pd.Timestamp:
        published = datetime.fromisoformat(row["first_public_at"])
        return pd.Timestamp((published.astimezone(CHINA) if published.tzinfo else published).date())

    selected = [row for row in events if pd.Timestamp(start_date) <= local_event_day(row) <= pd.Timestamp(end_date)]
    selected.sort(key=lambda row: (row["first_public_at"], row["event_id"]))
    duplicates = []
    unique = []
    seen = set()
    for row in selected:
        key = (row["theme_id"], row["first_public_at"])
        (duplicates if key in seen else unique).append(row)
        seen.add(key)
    _csv(output_dir / "policy_documents.csv", [{"document_id": e["document_id"], "document_stage": e["document_stage"],
                                                  "published_at": e["published_at"], "source_url": e["source_url"],
                                                  "raw_sha256": e["raw_sha256"]} for e in {r["document_id"]: r for r in unique}.values()],
         ["document_id", "document_stage", "published_at", "source_url", "raw_sha256"])
    _csv(output_dir / "policy_clauses.csv", unique, ["event_id", "document_id", "section", "quote", "first_public_at",
                                                  "first_public_url", "policy_action", "support_type"])
    _csv(output_dir / "policy_industry_labels.csv", unique, ["event_id", "theme_id", "industry_id", "relation",
                                                          "support_type", "policy_direction", "change_vs_previous",
                                                          "new_support", "mapping_reason", "review_status"])
    _csv(output_dir / "policy_concepts.csv", unique, ["theme_id", "industry_id", "first_public_at", "mapping_reason"])
    _csv(output_dir / "concept_relations.csv", [dict(event_id=e["event_id"], **r) for e in unique for r in e.get("concept_relations", [])],
         ["event_id", "from_concept", "to_concept", "relation", "source_url", "public_at"])
    _csv(output_dir / "company_exposures.csv", [dict(event_id=e["event_id"], **r) for e in unique for r in e.get("company_exposures", [])],
         ["event_id", "company_code", "theme_id", "tier", "source_url", "public_at", "reason"])
    links = [dict(event_id=e["event_id"], theme_id=e["theme_id"], **link) for e in unique for link in e.get("etf_links", [])]
    _csv(output_dir / "etf_exposures_asof.csv", links, ["event_id", "theme_id", "etf_code", "listed_at",
                                                        "exposure_source_url", "exposure_public_at", "exposure_asof",
                                                        "exposure_method", "exposure_reason", "matched_company_codes",
                                                        "direct_weight", "supply_weight"])
    _csv(output_dir / "unmapped_policy_themes.csv", [e for e in unique if e["etf_status"] != "VERIFIED"],
         ["event_id", "theme_id", "industry_id", "etf_status", "mapping_reason"])
    codes = sorted({link["etf_code"] for link in links} | {BENCHMARK})
    daily: dict[str, pd.DataFrame] = {}
    coverage = []
    for code in codes:
        path = etf_dir / f"{code}.csv"
        if not path.exists():
            coverage.append({"etf_code": code, "status": "PRICE_FILE_MISSING"})
            continue
        frame = daily_prices(path)
        daily[code] = frame
        coverage.append({"etf_code": code, "status": "available", "first_date": frame.date.min(),
                         "last_date": frame.date.max(), "sessions": len(frame),
                         "zero_volume_sessions": int(frame.volume.le(0).sum()),
                         "incomplete_bar_sessions": int(frame.bars_complete.eq(False).sum()),
                         "action_audit_status": audit.get("funds", {}).get(code, {}).get("status", "missing")})
    _csv(output_dir / "etf_coverage.csv", coverage, ["etf_code", "status", "first_date", "last_date", "sessions",
                                                    "zero_volume_sessions", "incomplete_bar_sessions", "action_audit_status"])
    observations = []
    for event in unique:
        for link in event.get("etf_links", []):
            code = link["etf_code"]
            for horizon in HORIZONS:
                if code not in daily or BENCHMARK not in daily:
                    observations.append({"event_id": event["event_id"], "theme_id": event["theme_id"],
                                         "etf_code": code, "horizon": horizon, "missing_reason": "PRICE_FILE_MISSING"})
                else:
                    observations.append(event_window(event, code, daily[code], daily[BENCHMARK], actions, audit, horizon))
    columns = ["event_id", "document_id", "first_public_at", "theme_id", "industry_id", "support_type",
               "policy_direction", "change_vs_previous", "new_support", "etf_code", "horizon", "entry_date", "exit_date", "etf_return",
               "benchmark_return", "excess_return", "pre20_excess", "missing_reason"]
    _csv(output_dir / "observations.csv", observations, columns)
    valid = pd.DataFrame(observations).reindex(columns=columns)
    valid = valid.loc[valid.missing_reason.isna() & valid.excess_return.notna()]
    if valid.empty:
        summary = []
    else:
        summary = valid.groupby(["policy_direction", "change_vs_previous", "new_support", "horizon"], dropna=False).agg(
            observations=("excess_return", "size"), events=("event_id", "nunique"),
            mean_excess=("excess_return", "mean"), median_excess=("excess_return", "median"),
            mean_etf_return=("etf_return", "mean"), mean_benchmark_return=("benchmark_return", "mean")
        ).reset_index().to_dict("records")
    _csv(output_dir / "summary.csv", summary, ["policy_direction", "change_vs_previous", "new_support", "horizon", "observations", "events",
                                             "mean_excess", "median_excess", "mean_etf_return", "mean_benchmark_return"])
    if valid.empty:
        event_summary = []
        controls = []
    else:
        event_summary = valid.groupby(["event_id", "first_public_at", "policy_direction", "change_vs_previous", "new_support", "horizon"], dropna=False).agg(
            etfs=("etf_code", "nunique"), mean_excess=("excess_return", "mean"),
            median_excess=("excess_return", "median")
        ).reset_index().to_dict("records")
        control_rows = pd.DataFrame(event_summary)
        control_rows["event_date"] = control_rows.first_public_at.map(
            lambda value: local_event_day({"first_public_at": value}).strftime("%Y-%m-%d"))
        control_rows["group"] = control_rows.new_support.map(
            lambda value: "new_support" if value == 1 else "continued" if value == 0 else "other")
        paired = control_rows.groupby(["event_date", "horizon", "group"], dropna=False).mean_excess.mean().unstack("group")
        controls = [{"event_date": date, "horizon": horizon,
                     "new_support_excess": row.get("new_support"), "continued_excess": row.get("continued"),
                     "same_day_difference": row.get("new_support") - row.get("continued")}
                    for (date, horizon), row in paired.iterrows() if pd.notna(row.get("new_support")) and pd.notna(row.get("continued"))]
    _csv(output_dir / "event_summary.csv", event_summary,
         ["event_id", "first_public_at", "policy_direction", "change_vs_previous", "new_support",
          "horizon", "etfs", "mean_excess", "median_excess"])
    _csv(output_dir / "same_day_controls.csv", controls,
         ["event_date", "horizon", "new_support_excess", "continued_excess", "same_day_difference"])
    if event_summary:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axis = plt.subplots(figsize=(8, 4.5))
        for event_id, group in pd.DataFrame(event_summary).groupby("event_id"):
            axis.plot(group.horizon, group.mean_excess.mul(100), marker="o", label=event_id)
        axis.axhline(0, color="grey", linewidth=.8)
        axis.set(xlabel="Trading days from next open", ylabel="Excess total return (percentage points)",
                 title="Policy event ETF excess return")
        axis.set_xticks(HORIZONS)
        if len(event_summary) <= 40:
            axis.legend(fontsize=6, loc="best")
        figure.tight_layout()
        figure.savefig(output_dir / "event_excess.png", dpi=160)
        plt.close(figure)
    missing = Counter(row.get("missing_reason") for row in observations if row.get("missing_reason"))
    statuses = Counter(row["etf_status"] for row in unique)
    metadata = {"selected_events": len(selected), "unique_events": len(unique), "duplicate_theme_events": len(duplicates),
                "event_statuses": dict(statuses), "missing_by_reason": dict(missing),
                "valid_observations": len(valid), "horizons": HORIZONS, "primary_horizon": 60,
                "return_basis": "next eligible open to horizon-th close; ex-close dividend reinvestment; zero fees"}
    (output_dir / "research_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = ("# 政策支持行业 ETF 事件研究\n\n"
              f"政策事件 {len(unique)} 条；已核验 ETF 观测 {len(valid)} 条；60 日为预先指定主窗口。\n\n"
              "## 分类结果\n\n" + (pd.DataFrame(summary).to_markdown(index=False) if summary else "暂无可计算的收益观测。") + "\n\n" +
              ("![逐事件超额收益](event_excess.png)\n\n" if event_summary else "") +
              "## 覆盖与排除\n\n" + json.dumps(metadata, ensure_ascii=False, indent=2) + "\n\n"
              "## 口径与限制\n\n"
              "只有审批事件且 ETF 上市、历史暴露和公司行动覆盖都核验时才计算收益。"
              "日期精度的消息保守地视为收盘后公开；第 1 个交易日为入场日。"
              "收益为统计标签，忽略交易费用，分红在除息日收盘再投资。"
              "样本按事件展示；同一规划下多只 ETF 不是独立政策冲击。"
              "未核验关联、未上市工具和未成熟窗口不填零，也不推断政策因果效应。\n")
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    snapshots = {}
    for path in (events_path, actions_path, audit_path):
        target = output_dir / "inputs" / path.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path, target)
        snapshots[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    if events_path.name == "approved_events.jsonl":
        for event in unique:
            document = events_path.parent / "documents" / event["document_id"]
            source_files = [next((document / "raw").glob(f"{event['raw_sha256']}.*")),
                            document / f"{event['raw_sha256']}.txt"]
            early = event.get("first_public_evidence")
            if early:
                earlier = events_path.parent / "documents" / early["document_id"]
                source_files.extend([earlier / early["raw_file"], earlier / early["body_file"]])
            for source in source_files:
                relative = source.relative_to(events_path.parent)
                target = output_dir / "inputs" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                snapshots[str(source.resolve())] = hashlib.sha256(source.read_bytes()).hexdigest()
    for code in daily:
        path = etf_dir / f"{code}.csv"
        snapshots[str(path.resolve())] = hashlib.sha256(path.read_bytes()).hexdigest()
    for source in (Path(__file__), ROOT / "python/factors/relative_strength.py",
                   ROOT / "python/policy_news/store.py", ROOT / "python/policy_news/extract.py",
                   ROOT / "python/policy_news/mapping.py", ROOT / "python/policy_news/__main__.py",
                   ROOT / "python/task_registry.py", ROOT / "python/run_backtest.py"):
        relative = source.relative_to(ROOT)
        target = output_dir / "source_snapshot" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        snapshots[str(relative)] = hashlib.sha256(source.read_bytes()).hexdigest()
    (output_dir / "execution_metadata.json").write_text(json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_dir
