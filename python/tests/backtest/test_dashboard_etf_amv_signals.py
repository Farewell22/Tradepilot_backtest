import pandas as pd

from python.backtest_dashboard import service


def test_load_etf_amv_signals_exposes_low_momentum_warning_types(tmp_path, monkeypatch):
    etf_path = tmp_path / "510300.csv"
    pd.DataFrame({
        "时间": ["2024-01-02"], "开盘": [3.0], "最高": [3.1], "最低": [2.9],
        "收盘": [3.05], "成交量": [100],
    }).to_csv(etf_path, index=False)
    points = pd.DataFrame({
        "date": [pd.Timestamp("2024-01-02")],
        "signal_type": [pd.NA],
        "sell_types": [[]],
        "sell_warning_types": [[]],
        "sell_momentum_warning_types": [["sell_1"]],
    })
    monkeypatch.setattr(service, "ETF_DATA_PATH", etf_path)
    monkeypatch.setattr("python.factor_research.data.load_amv_csv", lambda _: pd.DataFrame())
    monkeypatch.setattr("python.factors.amv_buy_points.analyze_amv_buy_points", lambda _: (points, pd.DataFrame()))

    result = service.load_etf_amv_signals()

    assert result.points[0].sell_momentum_warning_types == ["sell_1"]
