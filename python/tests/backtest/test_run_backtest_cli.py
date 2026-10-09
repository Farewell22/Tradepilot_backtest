import json
import importlib
import subprocess
from pathlib import Path

from python.backtest.broker import FeeConfig
from python.run_backtest import TaskSpec, main


def test_cli_runs_registered_task_with_default_dates_and_manifest(tmp_path):
    def write_result(request):
        (request.output_dir / "report.txt").write_text("ok\n", encoding="utf-8")
        return request.output_dir

    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=write_result,
        default_fees=FeeConfig.etf_legacy(), execution_mode="next_available_bar",
    )}
    status = main(["run", "strategy", "sample", "--output-root", str(tmp_path)], tasks=tasks)
    assert status == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1
    manifest = json.loads((runs[0] / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["task_id"] == "sample"
    assert manifest["start_date"] == "20200101"
    assert manifest["end_date"] == "20251231"
    assert manifest["fees"]["stamp_duty_rate"] == 0.0
    assert manifest["status"] == "complete"


def test_manifest_records_effective_config_and_sources(tmp_path):
    config = tmp_path / "params.yaml"
    config.write_text("threshold: 3\n", encoding="utf-8")
    source = tmp_path / "prices.csv"
    source.write_text("date,close\n", encoding="utf-8")
    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=lambda request: request.output_dir,
        default_fees=FeeConfig.stock_legacy(), execution_mode="next_available_bar",
        default_config=config, data_sources=(source,),
    )}
    assert main(["run", "strategy", "sample", "--output-root", str(tmp_path / "runs")], tasks=tasks) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["config_snapshot"] == "threshold: 3\n"
    assert manifest["data_sources"] == [str(source)]


def test_custom_config_data_paths_replace_default_preflight_and_manifest(tmp_path):
    config = tmp_path / "custom.yaml"
    source = tmp_path / "custom.csv"
    source.write_text("date,close\n", encoding="utf-8")
    config.write_text(f"paths:\n  etf_csv: {source}\n", encoding="utf-8")
    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=lambda request: request.output_dir,
        default_fees=FeeConfig.stock_legacy(), execution_mode="legacy",
        data_sources=(tmp_path / "absent-default.csv",), source_path_keys=("etf_csv",),
    )}
    assert main(["run", "strategy", "sample", "--config", str(config),
                 "--output-root", str(tmp_path / "runs")], tasks=tasks) == 0
    manifest = json.loads((next((tmp_path / "runs").iterdir()) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["data_sources"] == [str(source)]


def test_cli_rejects_invalid_period_before_creating_output(tmp_path):
    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=lambda request: request.output_dir,
        default_fees=FeeConfig.stock_legacy(), execution_mode="next_available_bar",
    )}
    status = main(["run", "strategy", "sample", "--start", "20251301", "--output-root", str(tmp_path)], tasks=tasks)
    assert status == 2
    assert list(tmp_path.iterdir()) == []


def test_research_fee_override_is_rejected_when_task_does_not_execute_with_fees(tmp_path):
    tasks = {("research", "observation"): TaskSpec(
        task_id="observation", kind="research", handler=lambda request: request.output_dir,
        default_fees=FeeConfig.stock_legacy(), execution_mode="research_observation_window",
    )}
    assert main(["run", "research", "observation", "--slippage-rate", "0", "--output-root", str(tmp_path)], tasks=tasks) == 2
    assert list(tmp_path.iterdir()) == []


def test_builtin_catalog_lists_migrated_strategy_and_research(capsys):
    assert main(["list", "strategies"]) == 0
    strategies = capsys.readouterr().out.splitlines()
    assert set(strategies) == {
        "amv_winning", "amv_winning_rotation", "amv_winning_defensive_5d",
        "amv_winning_defensive", "amv_winning_defensive_3d", "amv_winning_bank_power_defensive",
        "amv_winning_defensive_corr60", "amv_winning_defensive_corr60_ma5", "amv_winning_defensive_corr60_ma5_15",
        "amv_winning_defensive_single_day",
        "amv_winning_defensive_second_entry",
        "amv_winning_defensive_ma20_entry",
        "amv_winning_defensive_csi2000",
        "amv_winning_defensive_chinext",
        "amv_winning_ccb", "amv_winning_cmb",
        "amv_below_ma_defensive_etfs",
        "etf_amv", "green_doji",
    }
    assert main(["list", "research"]) == 0
    research = capsys.readouterr().out.splitlines()
    assert "amv_3d_momentum" in research
    assert "etf_rs20_rotation" in research


def test_shell_entry_works_from_another_directory():
    script = Path(__file__).resolve().parents[3] / "scripts/backtest.sh"
    result = subprocess.run(["bash", str(script), "list", "strategies"], cwd="/tmp", capture_output=True, text=True)
    assert result.returncode == 0
    assert "etf_amv" in result.stdout.splitlines()


def test_successful_run_publishes_latest_report_with_run_and_source_paths(tmp_path):
    source = tmp_path / "prices.csv"
    source.write_text("date,close\n", encoding="utf-8")
    report_dir = tmp_path / "strategy"

    def write_result(request):
        (request.output_dir / "report.md").write_text("# 本次收益\n\n42%\n", encoding="utf-8")
        (request.output_dir / "nav.csv").write_text("date,nav\n", encoding="utf-8")
        (request.output_dir / "trades_variant.csv").write_text("date,code\n", encoding="utf-8")
        return request.output_dir

    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=write_result,
        default_fees=FeeConfig.etf_legacy(), execution_mode="next_available_bar",
        data_sources=(source,), report_dir=report_dir,
    )}
    runs_root = tmp_path / "runs"
    assert main(["run", "strategy", "sample", "--output-root", str(runs_root)], tasks=tasks) == 0
    run_dir = next(runs_root.iterdir())
    latest = report_dir / "latest-report.md"
    body = latest.read_text(encoding="utf-8")
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert "# 本次收益\n\n42%" in body
    assert str(run_dir) in body
    assert str(source) in body
    assert "run_manifest.json" in body
    assert "nav.csv" in body
    assert "trades_variant.csv" in body
    assert manifest["published_report_path"] == str(latest)


def test_multistage_text_reports_are_included_in_latest_report(tmp_path):
    report_dir = tmp_path / "strategy"

    def write_result(request):
        for stage in ("train", "oos"):
            stage_dir = request.output_dir / stage
            stage_dir.mkdir()
            (stage_dir / "report.txt").write_text(f"{stage} result\n", encoding="utf-8")
        return request.output_dir

    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=write_result,
        default_fees=FeeConfig.etf_legacy(), execution_mode="next_available_bar",
        report_dir=report_dir,
    )}
    assert main(["run", "strategy", "sample", "--output-root", str(tmp_path / "runs")], tasks=tasks) == 0
    body = (report_dir / "latest-report.md").read_text(encoding="utf-8")
    assert "train/report.txt" in body and "oos/report.txt" in body
    assert "```text\ntrain result\n```" in body
    assert "```text\noos result\n```" in body


def test_failed_run_does_not_replace_previous_latest_report(tmp_path):
    report_dir = tmp_path / "strategy"
    report_dir.mkdir()
    latest = report_dir / "latest-report.md"
    latest.write_text("previous success\n", encoding="utf-8")

    def fail(_request):
        raise RuntimeError("simulated failure")

    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=fail,
        default_fees=FeeConfig.etf_legacy(), execution_mode="next_available_bar",
        report_dir=report_dir,
    )}
    assert main(["run", "strategy", "sample", "--output-root", str(tmp_path / "runs")], tasks=tasks) == 1
    assert latest.read_text(encoding="utf-8") == "previous success\n"
    manifest = json.loads((next((tmp_path / "runs").iterdir()) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"


def test_missing_run_report_keeps_previous_latest_report(tmp_path):
    report_dir = tmp_path / "strategy"
    report_dir.mkdir()
    latest = report_dir / "latest-report.md"
    latest.write_text("previous success\n", encoding="utf-8")
    tasks = {("strategy", "sample"): TaskSpec(
        task_id="sample", kind="strategy", handler=lambda request: request.output_dir,
        default_fees=FeeConfig.etf_legacy(), execution_mode="next_available_bar",
        report_dir=report_dir,
    )}
    assert main(["run", "strategy", "sample", "--output-root", str(tmp_path / "runs")], tasks=tasks) == 1
    assert latest.read_text(encoding="utf-8") == "previous success\n"
    manifest = json.loads((next((tmp_path / "runs").iterdir()) / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert "report.md 或 report.txt" in manifest["error"]
    assert "published_report_path" not in manifest


def test_builtin_tasks_have_own_source_directory_for_latest_report():
    from python.run_backtest import ROOT
    from python.task_registry import RESEARCH_MODULES, TASKS

    assert set(RESEARCH_MODULES) == {task_id for kind, task_id in TASKS if kind == "research"}
    assert len([spec for spec in TASKS.values() if spec.kind == "strategy"]) == 19
    for (kind, task_id), spec in TASKS.items():
        assert spec.report_dir is not None
        assert spec.report_dir.is_dir()
        assert spec.report_dir.name == task_id
        if kind == "strategy":
            assert spec.report_dir.parent == ROOT / "python" / "strategies"
        else:
            assert spec.report_dir.parent.parent == ROOT / "python" / "research"
            assert spec.report_dir.parent.name in {"amv", "etf", "policy", "stock"}
            module = importlib.import_module(RESEARCH_MODULES[task_id])
            assert Path(module.__file__).parent == spec.report_dir
