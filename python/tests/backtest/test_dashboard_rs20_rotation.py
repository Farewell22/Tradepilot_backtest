from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from python.backtest_dashboard import service
from python.backtest_dashboard.api import app


@pytest.fixture
def rs20_run_dir(tmp_path: Path) -> Path:
    """A complete class-2/OOS artifact set produced by the RS20 runner."""
    run_dir = tmp_path / "rs20_rotation"
    run_dir.mkdir()
    pd.DataFrame([{
        "signal_type": "class_2", "stage": "oos", "stage_start": "2024-01-01",
        "stage_end": "2025-12-31", "entry_signal_count": 7,
        "fallback_510300_count": 1, "ignored_buy_signal_count": 2,
        "oos_exit_row_count": 4, "final_value": 240481.71,
        "total_return_pct": 20.24, "annualized_return_pct": 9.67,
        "max_drawdown_pct": -13.70, "closed_trade_count": 4,
        "win_rate_pct": 75.0,
    }]).to_csv(run_dir / "summary.csv", index=False)
    pd.DataFrame({
        "date": ["2024-01-02", "2024-01-03"], "nav": [200000.0, 202000.0],
        "return_pct": [0.0, 1.0], "drawdown_pct": [0.0, 0.0],
    }).to_csv(run_dir / "nav_class_2_oos.csv", index=False)
    pd.DataFrame({
        "year": [2024], "return_pct": [5.0], "max_drawdown_pct": [-2.0],
        "end_nav": [210000.0],
    }).to_csv(run_dir / "annual_class_2_oos.csv", index=False)
    pd.DataFrame([{
        "code": "512660.SH", "name": "军工", "buy_date": "20240102",
        "sell_date": "20240103", "buy_signal_type": "class_2",
        "selection_type": "rs20_top1", "rs20": 0.035, "candidate_count": 6,
        "is_fallback": False, "pnl_pct": 2.0, "hold_days": 1,
        "sell_reason": "trend_exit_ma10_le_ma30", "is_partial_exit": False,
    }]).to_csv(run_dir / "trades_class_2_oos.csv", index=False)
    return run_dir


def test_load_rs20_rotation_reads_signal_stage_artifacts(rs20_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails if the loader selects the wrong class/stage files or drops RS20 metadata."""
    monkeypatch.setattr(service, "RS20_ROTATION_RUN_DIR", rs20_run_dir, raising=False)

    result = service.load_rs20_etf_rotation("oos", "class_2")

    assert result.signal_type == "class_2"
    assert result.stage == "oos"
    assert result.summary.entry_signal_count == 7
    assert result.summary.oos_exit_row_count == 4
    assert result.nav[-1].nav == 202000.0
    assert result.annual[0].year == 2024
    assert result.trades[0].code == "512660.SH"
    assert result.trades[0].rs20 == pytest.approx(0.035)
    assert result.trades[0].candidate_count == 6
    assert result.trades[0].is_fallback is False


def test_load_rs20_rotation_returns_an_empty_trade_list_for_an_empty_artifact(
    rs20_run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if a valid no-trade backtest artifact causes pandas EmptyDataError."""
    (rs20_run_dir / "trades_class_2_oos.csv").write_text("", encoding="utf-8")
    monkeypatch.setattr(service, "RS20_ROTATION_RUN_DIR", rs20_run_dir, raising=False)

    result = service.load_rs20_etf_rotation("oos", "class_2")

    assert result.trades == []


def test_rs20_rotation_route_returns_selected_signal_artifacts(rs20_run_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails if the public route does not expose the requested signal-class result."""
    monkeypatch.setattr(service, "RS20_ROTATION_RUN_DIR", rs20_run_dir, raising=False)

    response = TestClient(app).get(
        "/api/v1/backtest/curves/rs20-etf-rotation/oos",
        params={"signal_type": "class_2"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["signal_type"] == "class_2"
    assert payload["summary"]["stage_end"] == "2025-12-31"
    assert payload["trades"][0]["selection_type"] == "rs20_top1"


@pytest.mark.parametrize(
    ("stage", "signal_type"),
    [("invalid", "class_2"), ("oos", "class_1")],
)
def test_rs20_rotation_rejects_unknown_stage_or_signal_type(
    stage: str, signal_type: str, rs20_run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if an unsupported selector can be used to address arbitrary artifacts."""
    monkeypatch.setattr(service, "RS20_ROTATION_RUN_DIR", rs20_run_dir, raising=False)

    response = TestClient(app).get(
        f"/api/v1/backtest/curves/rs20-etf-rotation/{stage}",
        params={"signal_type": signal_type},
    )

    assert response.status_code == 404
    assert "必须" in response.json()["detail"]
