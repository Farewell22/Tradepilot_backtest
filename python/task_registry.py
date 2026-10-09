"""Explicit catalog and adapters for existing backtest and research tasks."""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

from python.backtest.broker import FeeConfig
from python.research.date_scope import date_window, scoped_ranges
from python.run_backtest import ROOT, RunRequest, TaskSpec


DATA = ROOT / "data" / "backtest_data"
ETF_DIR = DATA / "ETF_60min_2005_2025"
RESEARCH_MODULES = {
    "amv_3d_momentum": "python.research.amv.amv_3d_momentum.study",
    "amv_buy_reentry_filters": "python.research.amv.amv_buy_reentry_filters.study",
    "amv_quantile_window_impact": "python.research.amv.amv_quantile_window_impact.study",
    "amv_sell_momentum": "python.research.amv.amv_sell_momentum.study",
    "ma10_above_ma30_gap": "python.research.amv.ma10_above_ma30_gap.study",
    "ma10_below_ma30_gap": "python.research.amv.ma10_below_ma30_gap.study",
    "ma10_gap": "python.research.amv.ma10_gap.study",
    "etf_amount_ratio_rotation": "python.research.etf.etf_amount_ratio_rotation.study",
    "amv_buy_etf_cross_section": "python.research.etf.amv_buy_etf_cross_section.study",
    "amv_down_momentum_defensive_etfs": "python.research.etf.amv_down_momentum_defensive_etfs.study",
    "etf_kdj_rotation": "python.research.etf.etf_kdj_rotation.study",
    "etf_rs20_rotation": "python.research.etf.etf_rs20_rotation.study",
    "etf_amv_correlation": "python.research.etf.etf_amv_correlation.study",
    "etf_relative_volume": "python.research.etf.etf_relative_volume.study",
    "industry_etf_relative_strength": "python.research.etf.industry_etf_relative_strength.study",
    "etf_size_rs20_percentile": "python.research.etf.etf_size_rs20_percentile.study",
    "industry_etf_policy_support": "python.research.policy.industry_etf_policy_support.study",
    "n_pullback_amv_entry": "python.research.stock.n_pullback_amv_entry.study",
    "amv_entry_corr60": "python.research.etf.amv_entry_corr60.study",
}


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"必需数据不存在: {path}")
    return path


def _run_etf_amv(request: RunRequest) -> Path:
    from python.strategies.etf_amv.runner import load_settings, run_stage
    settings = load_settings(request.config_path or ROOT / "python/config/etf_0amv.yaml")
    with date_window(request.start_date, request.end_date):
        samples = scoped_ranges({name: (sample["start_date"], sample["end_date"]) for name, sample in settings["sample"].items()})
    if not samples:
        raise ValueError("所选日期与策略训练/样本外区间没有交集")
    settings["paths"]["output_root"] = str(request.output_dir)
    for stage, (start, end) in samples.items():
        settings["sample"][stage] = {**settings["sample"][stage], "start_date": start.replace("-", ""), "end_date": end.replace("-", "")}
        run_stage(stage, settings, refresh=False, fees=request.fees)
    return request.output_dir


def _run_green_doji(request: RunRequest) -> Path:
    if request.config_path is not None:
        raise ValueError("green_doji 不接受 --config")
    from python.strategies.green_doji.strategy import run_backtest
    run_backtest(start_date=request.start_date, end_date=request.end_date, output_dir=str(request.output_dir), fees=request.fees)
    return request.output_dir


def _run_amv_winning(request: RunRequest) -> Path:
    import yaml
    from python.strategies.amv_winning.runner import AGRICULTURAL_BANK, run_research
    config_path = request.config_path or ROOT / "python/strategies/amv_winning/config.yaml"
    settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = settings["paths"]
    bank_code = settings.get("bank_code", AGRICULTURAL_BANK)
    if bank_code != AGRICULTURAL_BANK:
        raise ValueError("amv_winning 正式入口的备选持仓必须为 601288.SH")
    take_profit = settings.get("bank_take_profit", True)
    if not isinstance(take_profit, bool):
        raise ValueError("bank_take_profit 必须为布尔值")

    def source(key: str) -> Path:
        path = Path(paths[key])
        return _require(path if path.is_absolute() else ROOT / path)

    stock_fees = FeeConfig.stock_legacy().with_overrides(
        commission_rate=request.fees.commission_rate, min_commission=request.fees.min_commission,
        slippage_rate=request.fees.slippage_rate,
    ).with_overrides(**settings.get("bank_fees", {}))
    run_research(
        source("amv_csv"), source("primary_csv"),
        request.output_dir, request.output_dir / "report.md",
        initial_cash=settings.get("initial_cash", 200_000),
        start_date=request.start_date, end_date=request.end_date, fees=request.fees,
        bank_code=bank_code, stock_data_dir=source("stock_5m_dir"),
        stock_dividends_path=source("stock_dividends_csv"),
        bank_take_profit=take_profit, bank_fees=stock_fees,
    )
    return request.output_dir


def _run_amv_winning_defensive(request: RunRequest) -> Path:
    import yaml
    from python.strategies.amv_winning_defensive.runner import run_research
    config_path = request.config_path or ROOT / "python/strategies/amv_winning_defensive/config.yaml"
    settings = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    paths = settings["paths"]

    def source(key: str) -> Path:
        path = Path(paths[key])
        return _require(path if path.is_absolute() else ROOT / path)

    run_research(
        source("amv_csv"), source("primary_csv"), source("defensive_etf_csv"),
        source("stock_5m_dir"),
        request.output_dir,
        start_date=request.start_date, end_date=request.end_date, fees=request.fees,
        stock_dividends_path=source("stock_dividends_csv"),
    )
    return request.output_dir


def _run_amv_winning_bank_power_defensive(request: RunRequest) -> Path:
    if request.config_path is not None:
        raise ValueError("amv_winning_bank_power_defensive 不接受 --config")
    from python.strategies.amv_winning_bank_power_defensive.runner import run_research
    run_research(
        _require(DATA / "0AMV-260612.csv"),
        _require(ETF_DIR / "512100.SH.csv"),
        _require(ETF_DIR / "512800.SH.csv"),
        _require(ETF_DIR / "561560.SH.csv"),
        request.output_dir,
        start_date=request.start_date, end_date=request.end_date, fees=request.fees,
    )
    return request.output_dir


def _run_amv_winning_rotation(request: RunRequest) -> Path:
    if request.config_path is not None:
        raise ValueError("amv_winning_rotation 不接受 --config")
    from python.strategies.amv_winning_rotation.runner import run_research
    run_research(
        _require(DATA / "0AMV-260612.csv"),
        _require(ETF_DIR / "512100.SH.csv"),
        _require(ETF_DIR / "510880.SH.csv"),
        _require(ETF_DIR / "515220.SH.csv"),
        request.output_dir,
        start_date=request.start_date, end_date=request.end_date, fees=request.fees,
    )
    return request.output_dir


def _run_amv_winning_defensive_5d(request: RunRequest) -> Path:
    if request.config_path is not None:
        raise ValueError("amv_winning_defensive_5d 不接受 --config")
    from python.strategies.amv_winning_defensive_5d.runner import run_research
    run_research(
        _require(DATA / "0AMV-260612.csv"),
        _require(ETF_DIR / "512100.SH.csv"),
        _require(ETF_DIR / "510880.SH.csv"),
        _require(ETF_DIR / "515220.SH.csv"),
        request.output_dir,
        start_date=request.start_date, end_date=request.end_date, fees=request.fees,
    )
    return request.output_dir


def _research_handler(module_name: str):
    def run(request: RunRequest) -> Path:
        module = importlib.import_module(module_name)
        if request.config_path is not None and request.task_id != "ma10_gap":
            raise ValueError(f"{request.task_id} 不接受 --config")
        if request.task_id == "ma10_gap":
            result = module.run_research(
                request.config_path or ROOT / "python/config/etf_0amv.yaml",
                request.output_dir, start_date=request.start_date, end_date=request.end_date,
                fees=request.fees,
            )
            result.to_csv(request.output_dir / "summary.csv", index=False, encoding="utf-8-sig")
            return request.output_dir
        paths = {
            "amv_path": DATA / "0AMV-260612.csv",
            "etf_path": DATA / "510300.SH.csv",
            "etf_dir": ETF_DIR,
            "reference_path": ETF_DIR / "510300.SH.csv",
            "output_dir": request.output_dir,
        }
        signature = inspect.signature(module.run_research)
        arguments = {name: _require(paths[name]) if name != "output_dir" else paths[name]
                     for name, parameter in signature.parameters.items()
                     if name in paths and (parameter.default is inspect.Parameter.empty or name == "output_dir")}
        missing = [name for name, parameter in signature.parameters.items()
                   if parameter.default is inspect.Parameter.empty and name not in arguments]
        if missing:
            raise ValueError(f"研究任务缺少输入映射: {', '.join(missing)}")
        if "fees" in signature.parameters:
            arguments["fees"] = request.fees
        with date_window(request.start_date, request.end_date):
            module.run_research(**arguments)
        return request.output_dir
    return run


def _run_amv_below_ma_defensive_etfs(request: RunRequest) -> Path:
    if request.config_path is not None:
        raise ValueError("amv_below_ma_defensive_etfs 不接受 --config")
    from python.strategies.amv_below_ma_defensive_etfs.runner import run_backtest
    run_backtest(_require(DATA / "0AMV-260612.csv"), ETF_DIR, request.output_dir,
                 start_date=request.start_date, end_date=request.end_date, fees=request.fees)
    return request.output_dir


TASKS: dict[tuple[str, str], TaskSpec] = {}
for task_id, handler, fees, mode in (
    ("etf_amv", _run_etf_amv, FeeConfig.stock_legacy(), "legacy_etf_amv"),
    ("green_doji", _run_green_doji, FeeConfig.stock_legacy(), "legacy_green_doji"),
    ("amv_winning", _run_amv_winning, FeeConfig.etf_legacy(), "legacy_same_close_idealized"),
    ("amv_winning_defensive", _run_amv_winning_defensive, FeeConfig.etf_legacy(), "legacy_same_close_idealized"),
    ("amv_winning_bank_power_defensive", _run_amv_winning_bank_power_defensive, FeeConfig.etf_legacy(), "legacy_same_close_idealized"),
    ("amv_winning_rotation", _run_amv_winning_rotation, FeeConfig.etf_legacy(), "legacy_same_close_idealized"),
    ("amv_winning_defensive_5d", _run_amv_winning_defensive_5d, FeeConfig.etf_legacy(), "next_open_defensive_5d"),
):
    strategy_configs = {
        "etf_amv": ROOT / "python/config/etf_0amv.yaml",
        "amv_winning_defensive": ROOT / "python/strategies/amv_winning_defensive/config.yaml",
        "amv_winning": ROOT / "python/strategies/amv_winning/config.yaml",
    }
    strategy_sources = {
        "etf_amv": (DATA / "0AMV-260612.csv", DATA / "510300.SH.csv"),
        "green_doji": (DATA / "5m_price",),
        "amv_winning": (DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                        ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
        "amv_winning_defensive": (
            DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv",
            ETF_DIR / "512890.SH.csv", DATA / "5m_price",
            ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv",
        ),
        "amv_winning_bank_power_defensive": (
            DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv",
            ETF_DIR / "512800.SH.csv", ETF_DIR / "561560.SH.csv",
        ),
        "amv_winning_rotation": (
            DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv",
            ETF_DIR / "510880.SH.csv", ETF_DIR / "515220.SH.csv",
        ),
        "amv_winning_defensive_5d": (
            DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv",
            ETF_DIR / "510880.SH.csv", ETF_DIR / "515220.SH.csv",
        ),
    }
    TASKS[("strategy", task_id)] = TaskSpec(
        task_id, "strategy", handler, fees, mode,
        default_config=strategy_configs.get(task_id), data_sources=strategy_sources[task_id],
        source_path_keys=("amv_csv", "etf_csv") if task_id == "etf_amv" else (
            ("amv_csv", "primary_csv", "stock_5m_dir", "stock_dividends_csv") if task_id == "amv_winning" else
            ("amv_csv", "primary_csv", "defensive_etf_csv", "stock_5m_dir", "stock_dividends_csv")
            if task_id == "amv_winning_defensive" else ()
        ),
        report_dir=ROOT / "python" / "strategies" / task_id,
    )

def _bank_comparison_handler(task_id: str):
    def run(request: RunRequest) -> Path:
        return importlib.import_module(f"python.strategies.{task_id}.runner").run(request)
    return run


_csi2000_dir = ROOT / "python/strategies/amv_winning_defensive_csi2000"
TASKS[("strategy", "amv_winning_defensive_csi2000")] = TaskSpec(
    "amv_winning_defensive_csi2000", "strategy",
    _bank_comparison_handler("amv_winning_defensive_csi2000"),
    FeeConfig.etf_legacy(), "legacy_same_close_idealized",
    default_config=_csi2000_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "563300.SH.csv",
                  ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "baseline_primary_csv", "stock_5m_dir", "stock_dividends_csv"),
    report_dir=_csi2000_dir, default_start_date="20230914",
)


_chinext_dir = ROOT / "python/strategies/amv_winning_defensive_chinext"
TASKS[("strategy", "amv_winning_defensive_chinext")] = TaskSpec(
    "amv_winning_defensive_chinext", "strategy",
    _bank_comparison_handler("amv_winning_defensive_chinext"),
    FeeConfig.etf_legacy(), "legacy_same_close_idealized",
    default_config=_chinext_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "159915.SZ.csv",
                  ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "baseline_primary_csv", "stock_5m_dir", "stock_dividends_csv"),
    report_dir=_chinext_dir, default_start_date="20230914",
)


_three_day_dir = ROOT / "python/strategies/amv_winning_defensive_3d"
TASKS[("strategy", "amv_winning_defensive_3d")] = TaskSpec(
    "amv_winning_defensive_3d", "strategy", _bank_comparison_handler("amv_winning_defensive_3d"),
    FeeConfig.etf_legacy(), "legacy_same_close_idealized",
    default_config=_three_day_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "stock_data", "stock_dividends_csv"),
    report_dir=_three_day_dir, default_start_date="20200102",
)


_single_day_dir = ROOT / "python/strategies/amv_winning_defensive_single_day"
TASKS[("strategy", "amv_winning_defensive_single_day")] = TaskSpec(
    "amv_winning_defensive_single_day", "strategy",
    _bank_comparison_handler("amv_winning_defensive_single_day"),
    FeeConfig.etf_legacy(), "legacy_same_close_idealized",
    default_config=_single_day_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "stock_data", "stock_dividends_csv"),
    report_dir=_single_day_dir, default_start_date="20200102",
)


_second_entry_dir = ROOT / "python/strategies/amv_winning_defensive_second_entry"
TASKS[("strategy", "amv_winning_defensive_second_entry")] = TaskSpec(
    "amv_winning_defensive_second_entry", "strategy",
    _bank_comparison_handler("amv_winning_defensive_second_entry"),
    FeeConfig.etf_legacy(), "next_open_amv_abc_t1",
    default_config=_second_entry_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "stock_data", "stock_dividends_csv"),
    report_dir=_second_entry_dir, default_start_date="20200102",
)


_ma20_entry_dir = ROOT / "python/strategies/amv_winning_defensive_ma20_entry"
TASKS[("strategy", "amv_winning_defensive_ma20_entry")] = TaskSpec(
    "amv_winning_defensive_ma20_entry", "strategy",
    _bank_comparison_handler("amv_winning_defensive_ma20_entry"),
    FeeConfig.etf_legacy(), "next_open_amv_abc_t1",
    default_config=_ma20_entry_dir / "config.yaml",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    source_path_keys=("amv_csv", "primary_csv", "stock_data", "stock_dividends_csv"),
    report_dir=_ma20_entry_dir, default_start_date="20200102",
)


for _bank_task, _bank_code in (("amv_winning_ccb", "601939"), ("amv_winning_cmb", "600036")):
    _bank_dir = ROOT / "python/strategies" / _bank_task
    TASKS[("strategy", _bank_task)] = TaskSpec(
        _bank_task, "strategy", _bank_comparison_handler(_bank_task),
        FeeConfig.etf_legacy(), "legacy_same_close_idealized",
        default_config=_bank_dir / "config.yaml",
        data_sources=(DATA / "0AMV-260612.csv", ETF_DIR / "512100.SH.csv", DATA / "5m_price",
                      _bank_dir / f"dividends_{_bank_code}.csv"),
        source_path_keys=("amv_csv", "primary_csv", "stock_5m_dir", "stock_dividends_csv"),
        report_dir=_bank_dir, default_start_date="20200102",
    )


_defensive_ma_dir = ROOT / "python/strategies/amv_below_ma_defensive_etfs"
TASKS[("strategy", "amv_below_ma_defensive_etfs")] = TaskSpec(
    "amv_below_ma_defensive_etfs", "strategy", _run_amv_below_ma_defensive_etfs,
    FeeConfig.etf_legacy(), "next_open_dividend_reinvestment",
    data_sources=(DATA / "0AMV-260612.csv",
                  *(ETF_DIR / f"{code}.csv" for code in ("512800.SH", "561560.SH", "515220.SH", "512890.SH", "510300.SH")),
                  _defensive_ma_dir / "corporate_actions.csv", _defensive_ma_dir / "corporate_action_audit.json"),
    report_dir=_defensive_ma_dir,
    default_start_date="20220516", default_end_date="20251231",
)


for task_id, module_name in RESEARCH_MODULES.items():
    if task_id in {"etf_size_rs20_percentile", "industry_etf_policy_support", "n_pullback_amv_entry", "amv_entry_corr60"}:
        # Explicit handlers and inputs are registered below.
        continue
    research_sources = (DATA / "0AMV-260612.csv", ETF_DIR) if task_id in {
        "etf_amount_ratio_rotation", "amv_buy_etf_cross_section", "etf_kdj_rotation", "etf_rs20_rotation",
        "etf_amv_correlation", "etf_relative_volume", "industry_etf_relative_strength",
    } else (DATA / "0AMV-260612.csv", DATA / "510300.SH.csv")
    if task_id == "amv_down_momentum_defensive_etfs":
        research_sources = (DATA / "0AMV-260612.csv", *(ETF_DIR / f"{code}.csv" for code in ("510880.SH", "515220.SH", "512100.SH")))
    TASKS[("research", task_id)] = TaskSpec(
        task_id, "research", _research_handler(module_name), FeeConfig.stock_legacy(), "research_observation_window",
        default_config=ROOT / "python/config/etf_0amv.yaml" if task_id == "ma10_gap" else None,
        data_sources=research_sources,
        supports_fee_override=task_id in {"ma10_gap", "ma10_above_ma30_gap", "etf_kdj_rotation"},
        source_path_keys=("amv_csv", "etf_csv") if task_id == "ma10_gap" else (),
        report_dir=ROOT.joinpath(*module_name.split(".")[:-1]),
    )


def _run_etf_size_rs20_percentile(request: RunRequest) -> Path:
    from python.research.etf.etf_size_rs20_percentile.study import run_research
    if request.config_path is not None:
        raise ValueError("etf_size_rs20_percentile 不接受 --config")
    return run_research(ETF_DIR, request.output_dir,
                        start_date=request.start_date, end_date=request.end_date)


_size_rs20_dir = ROOT / "python/research/etf/etf_size_rs20_percentile"
TASKS[("research", "etf_size_rs20_percentile")] = TaskSpec(
    "etf_size_rs20_percentile", "research", _run_etf_size_rs20_percentile,
    FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
              transfer_fee_rate=0, slippage_rate=0),
    "research_close_to_close_total_return",
    data_sources=(ETF_DIR / "512100.SH.csv", ETF_DIR / "510050.SH.csv",
                  _size_rs20_dir / "corporate_actions.csv", _size_rs20_dir / "corporate_action_audit.json"),
    report_dir=_size_rs20_dir, default_start_date="20200101", default_end_date="20251231",
)


def _run_industry_etf_policy_support(request: RunRequest) -> Path:
    from python.research.policy.industry_etf_policy_support.study import run_research
    if request.config_path is not None:
        raise ValueError("industry_etf_policy_support 不接受 --config")
    task_dir = ROOT / "python/research/policy/industry_etf_policy_support"
    return run_research(
        ROOT / "data/policy_news/approved_events.jsonl", ETF_DIR,
        task_dir / "inputs/corporate_actions.csv", task_dir / "inputs/corporate_action_audit.json",
        request.output_dir, start_date=request.start_date, end_date=request.end_date,
    )


_policy_research_dir = ROOT / "python/research/policy/industry_etf_policy_support"
TASKS[("research", "industry_etf_policy_support")] = TaskSpec(
    "industry_etf_policy_support", "research", _run_industry_etf_policy_support,
    FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
              transfer_fee_rate=0, slippage_rate=0),
    "research_policy_next_open_total_return",
    data_sources=(ROOT / "data/policy_news/approved_events.jsonl", ETF_DIR,
                  _policy_research_dir / "inputs/corporate_actions.csv",
                  _policy_research_dir / "inputs/corporate_action_audit.json"),
    report_dir=_policy_research_dir, default_start_date="20201103", default_end_date="20260930",
)


def _run_n_pullback_amv_entry(request: RunRequest) -> Path:
    from python.research.stock.n_pullback_amv_entry.study import run_research
    if request.config_path is not None:
        raise ValueError("n_pullback_amv_entry使用冻结输入，不接受--config")
    return run_research(request.output_dir, start_date=request.start_date, end_date=request.end_date)


_n_pullback_dir = ROOT / "python/research/stock/n_pullback_amv_entry"
_n_pullback_source = ROOT / "data/backtest_runs/amv_winning_defensive__20260928T143530Z__de469ebc"
TASKS[("research", "n_pullback_amv_entry")] = TaskSpec(
    "n_pullback_amv_entry", "research", _run_n_pullback_amv_entry,
    FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
              transfer_fee_rate=0, slippage_rate=0),
    "research_next_market_open_adjusted_price",
    data_sources=(_n_pullback_source / "run_manifest.json", _n_pullback_source / "trades_601288.SH.csv",
                  DATA / "5m_price"),
    report_dir=_n_pullback_dir,
)


def _run_amv_entry_corr60(request: RunRequest) -> Path:
    from python.research.etf.amv_entry_corr60.study import run_research
    if request.config_path is not None:
        raise ValueError("amv_entry_corr60 不接受 --config；辅助资料通过 prepare 命令导入")
    return run_research(request.output_dir, start_date=request.start_date, end_date=request.end_date, price_mode="local_screen")


_corr60_dir = ROOT / "python/research/etf/amv_entry_corr60"
_corr60_cache = ROOT / "data/factor_research_data/amv_entry_corr60"
TASKS[("research", "amv_entry_corr60")] = TaskSpec(
    "amv_entry_corr60", "research", _run_amv_entry_corr60,
    FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
              transfer_fee_rate=0, slippage_rate=0),
    "research_actual_entry_corr60_next_market_open_clean_price",
    data_sources=(DATA / "0AMV-260612.csv", ETF_DIR, DATA / "5m_price",
                  ROOT / "python/strategies/amv_winning_defensive/config.yaml",
                  ROOT / "python/strategies/amv_winning_defensive/dividends_601288.csv"),
    report_dir=_corr60_dir, default_start_date="20190118", default_end_date="20251231",
)


def _run_amv_winning_defensive_corr60(request: RunRequest) -> Path:
    from python.strategies.amv_winning_defensive_corr60.runner import run
    return run(request)


_corr60_strategy_dir = ROOT / 'python/strategies/amv_winning_defensive_corr60'
TASKS[('strategy', 'amv_winning_defensive_corr60')] = TaskSpec(
    'amv_winning_defensive_corr60', 'strategy', _run_amv_winning_defensive_corr60,
    FeeConfig.etf_legacy(), 'legacy_same_close_idealized',
    default_config=_corr60_strategy_dir / 'config.yaml',
    source_path_keys=('amv_csv', 'etf_dir', 'primary_csv', 'defensive_etf_csv',
                      'stock_5m_dir', 'stock_dividends_csv'),
    report_dir=_corr60_strategy_dir, default_start_date='20190118', default_end_date='20251231',
)



def _run_amv_winning_defensive_corr60_ma5(request: RunRequest) -> Path:
    from python.strategies.amv_winning_defensive_corr60_ma5.runner import run
    return run(request)


_ma5_strategy_dir = ROOT / 'python/strategies/amv_winning_defensive_corr60_ma5'
TASKS[('strategy', 'amv_winning_defensive_corr60_ma5')] = TaskSpec(
    'amv_winning_defensive_corr60_ma5', 'strategy', _run_amv_winning_defensive_corr60_ma5,
    FeeConfig.etf_legacy(), 'legacy_same_close_idealized',
    default_config=_ma5_strategy_dir / 'config.yaml',
    source_path_keys=('amv_csv', 'etf_dir', 'primary_csv', 'defensive_etf_csv',
                      'stock_5m_dir', 'stock_dividends_csv'),
    report_dir=_ma5_strategy_dir, default_start_date='20190118', default_end_date='20251231',
)


def _run_amv_winning_defensive_corr60_ma5_15(request: RunRequest) -> Path:
    from python.strategies.amv_winning_defensive_corr60_ma5_15.runner import run
    return run(request)


_ma5_15_strategy_dir = ROOT / 'python/strategies/amv_winning_defensive_corr60_ma5_15'
TASKS[('strategy', 'amv_winning_defensive_corr60_ma5_15')] = TaskSpec(
    'amv_winning_defensive_corr60_ma5_15', 'strategy', _run_amv_winning_defensive_corr60_ma5_15,
    FeeConfig.etf_legacy(), 'legacy_same_close_idealized',
    default_config=_ma5_15_strategy_dir / 'config.yaml',
    source_path_keys=('amv_csv', 'etf_dir', 'primary_csv', 'defensive_etf_csv',
                      'stock_5m_dir', 'stock_dividends_csv'),
    report_dir=_ma5_15_strategy_dir, default_start_date='20190118', default_end_date='20251231',
)
