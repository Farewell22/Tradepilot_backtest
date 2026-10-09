from pathlib import Path

from fastapi.testclient import TestClient

from python.backtest_dashboard import service
from python.backtest_dashboard.api import app


def test_nested_cli_runs_are_discoverable_and_resolve_without_splitting_parent_id(tmp_path: Path, monkeypatch):
    root = tmp_path / "backtest_runs"
    gate = root / "sample_nested__20260923T090000Z__abc12345" / "train" / "baseline"
    gate.mkdir(parents=True)
    (gate / "report.txt").write_text("总收益率: 3.0\n", encoding="utf-8")
    stage = root / "etf_amv__20260923T090000Z__def67890" / "oos"
    stage.mkdir(parents=True)
    (stage / "report.txt").write_text("总收益率: 4.0\n", encoding="utf-8")
    monkeypatch.setattr(service, "RUNS_DIR", root)

    ids = {run.run_id for run in service.list_runs() if run.has_report}
    assert "sample_nested__20260923T090000Z__abc12345__train__baseline" in ids
    assert "etf_amv__20260923T090000Z__def67890__oos" in ids
    for run_id in ids:
        assert service.get_run_path(run_id).joinpath("report.txt").exists()
    assert len(service.all_summaries()) == 2
    response = TestClient(app).get("/api/v1/backtest/years/summary")
    assert response.status_code == 200
    assert len(response.json()) == 2
