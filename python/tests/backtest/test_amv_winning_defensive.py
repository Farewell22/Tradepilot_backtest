from __future__ import annotations

import pandas as pd
import pytest
import hashlib
import json

from python.backtest.broker import FeeConfig
from python.run_backtest import RunRequest
from python.task_registry import TASKS, _run_amv_winning_defensive
from python.strategies.amv_winning_defensive.runner import load_dividend_events, run_defensive_backtest


def _bars(prices: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-02", periods=len(prices), freq="D")
    return pd.DataFrame({
        "date": dates + pd.Timedelta(hours=15),
        "open": prices, "high": prices, "low": prices, "close": prices,
        "volume": [1_000_000] * len(prices),
    })


def _signals(*, buys: tuple[int, ...] = (), ma10: tuple[int, ...] = (),
             macd: tuple[int, ...] = (), days: int = 4) -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-02", periods=days, freq="D"),
        "buy_signal": [i in buys for i in range(days)],
        "exit_ma10": [i in ma10 for i in range(days)],
        "exit_macd": [i in macd for i in range(days)],
    })


def _zero_fees() -> FeeConfig:
    return FeeConfig(commission_rate=0, min_commission=0, stamp_duty_rate=0,
                     transfer_fee_rate=0, slippage_rate=0)


@pytest.mark.parametrize("defensive_code", ["512890.SH", "601288.SH"])
def test_ma10_exit_rotates_to_defense_and_buy_rotates_back(defensive_code: str) -> None:
    result = run_defensive_backtest(
        _bars([10] * 4), _bars([5] * 4),
        _signals(buys=(0, 3), ma10=(1,)), defensive_code,
        initial_cash=100_000, primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )

    assert result.trades[["date", "code", "side"]].values.tolist() == [
        ["20240102", "512100.SH", "buy"],
        ["20240103", "512100.SH", "sell"],
        ["20240103", defensive_code, "buy"],
        ["20240105", defensive_code, "sell"],
        ["20240105", "512100.SH", "buy"],
    ]
    assert result.nav.loc[1, "defensive_quantity"] == 20_000
    assert result.nav.loc[3, "defensive_quantity"] == 0
    assert result.nav.loc[3, "nav"] == 100_000


def test_intraday_hard_stop_holds_cash_without_amv_exit() -> None:
    primary = _bars([10, 10, 10])
    primary["low"] = primary["low"].astype(float)
    primary.loc[1, "low"] = 9.7
    result = run_defensive_backtest(
        primary, _bars([5, 5, 5]), _signals(buys=(0,), days=3),
        "512890.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )

    assert result.trades.loc[1, "reason"] == "hard_stop_2.5pct"
    assert result.trades.loc[1, "signal_price"] == pytest.approx(9.75)
    assert len(result.trades) == 2
    assert result.nav.loc[1, "defensive_quantity"] == 0
    assert result.nav.loc[1, "cash"] == result.nav.loc[1, "nav"]


def test_profit_trail_holds_cash_without_amv_exit() -> None:
    primary = _bars([10.0, 10.4, 10.25])
    primary.loc[1, ["open", "high", "low"]] = [10.3, 10.6, 10.3]
    primary.loc[2, ["open", "high", "low"]] = [10.4, 10.5, 10.2]
    result = run_defensive_backtest(
        primary, _bars([5.0] * 3), _signals(buys=(0,), days=3),
        "601288.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.trades.loc[1, "reason"] == "profit_trail_body_break_5pct"
    assert result.trades.loc[1, "signal_price"] == pytest.approx(10.3)
    assert len(result.trades) == 2
    assert result.nav.loc[2, "defensive_quantity"] == 0


def test_hard_stop_plus_amv_close_exit_rotates_to_defense() -> None:
    primary = _bars([10.0, 10.0])
    primary.loc[1, "low"] = 9.7
    result = run_defensive_backtest(
        primary, _bars([5.0, 5.0]), _signals(buys=(0,), ma10=(1,), days=2),
        "601288.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.trades[["code", "side"]].values.tolist() == [
        ["512100.SH", "buy"], ["512100.SH", "sell"], ["601288.SH", "buy"],
    ]
    assert result.trades.loc[1, "reason"] == "hard_stop_2.5pct"
    assert result.trades.loc[2, "reason"] == "amv_close_below_ma10"


def test_amv_exit_after_hard_stop_enters_defense_from_cash() -> None:
    primary = _bars([10.0, 10.0, 10.0])
    primary.loc[1, "low"] = 9.7
    result = run_defensive_backtest(
        primary, _bars([5.0] * 3), _signals(buys=(0,), macd=(2,), days=3),
        "601288.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.nav.loc[1, "defensive_quantity"] == 0
    assert result.trades.loc[2, "date"] == "20240104"
    assert result.trades.loc[2, "code"] == "601288.SH"
    assert result.trades.loc[2, "reason"] == "amv_macd_dead_cross"


def test_exit_wins_when_buy_and_exit_coincide() -> None:
    result = run_defensive_backtest(
        _bars([10, 10]), _bars([5, 5]),
        _signals(buys=(0, 1), macd=(1,), days=2), "512890.SH",
        initial_cash=100_000, primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.trades["code"].tolist() == ["512100.SH", "512100.SH", "512890.SH"]


def test_stock_fees_and_dividend_are_accounted_for() -> None:
    stock_fees = FeeConfig(commission_rate=0, min_commission=0,
                           stamp_duty_rate=0.001, transfer_fee_rate=0.00001,
                           slippage_rate=0)
    result = run_defensive_backtest(
        _bars([10] * 4), _bars([5] * 4),
        _signals(buys=(0, 3), ma10=(1,)), "601288.SH",
        initial_cash=100_000, primary_fees=_zero_fees(), defensive_fees=stock_fees,
        dividends={pd.Timestamp("2024-01-04"): 0.1},
    )
    assert result.nav.loc[2, "dividend_income"] == pytest.approx(1_990)
    assert result.trades.loc[3, "reason"] == "amv_buy_signal_rotate_back"
    assert result.trades.loc[3, "cash_flow"] < 99_500
    assert result.nav.loc[3, "cash"] >= 0


def test_bank_take_profit_stays_in_cash_until_next_buy_signal() -> None:
    bank = _bars([5.0, 5.0, 5.1, 5.1, 5.1, 5.1, 5.1])
    bank.loc[2, ["open", "high", "low"]] = [5.2, 5.6, 5.1]
    result = run_defensive_backtest(
        _bars([10.0] * 7), bank,
        _signals(buys=(0, 4), ma10=(1, 2, 3, 5), days=7),
        "601288.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
        dividends={pd.Timestamp("2024-01-04"): 0.1,
                   pd.Timestamp("2024-01-05"): 0.1},
    )

    bank_sells = result.trades.loc[
        (result.trades["code"] == "601288.SH") & (result.trades["side"] == "sell")
    ]
    assert len(bank_sells) == 1
    assert bank_sells.iloc[0]["reason"] == "bank_take_profit_8pct"
    assert bank_sells.iloc[0]["date"] == "20240104"
    assert bank_sells.iloc[0]["signal_price"] == pytest.approx(5.40)
    assert bank_sells.iloc[0]["pnl_pct"] == pytest.approx(10.0)  # 8% price + 2% cash dividend
    assert result.nav.loc[2, "cash"] == pytest.approx(110_000)
    assert result.nav.loc[3, "cash"] == pytest.approx(110_000)
    assert result.nav.loc[3, "dividend_income"] == pytest.approx(2_000)
    assert result.trades[["date", "code", "side"]].values.tolist() == [
        ["20240102", "512100.SH", "buy"],
        ["20240103", "512100.SH", "sell"],
        ["20240103", "601288.SH", "buy"],
        ["20240104", "601288.SH", "sell"],
        ["20240106", "512100.SH", "buy"],
        ["20240107", "512100.SH", "sell"],
        ["20240107", "601288.SH", "buy"],
    ]


def test_bank_take_profit_uses_net_fees_and_gap_open() -> None:
    bank = _bars([5.0, 5.0, 5.4, 5.6])
    bank.loc[2, "high"] = 5.45
    bank.loc[3, ["open", "high", "low"]] = [5.6, 5.7, 5.5]
    fees = FeeConfig(commission_rate=0, min_commission=0,
                     stamp_duty_rate=0.01, transfer_fee_rate=0,
                     slippage_rate=0)
    result = run_defensive_backtest(
        _bars([10.0] * 4), bank, _signals(buys=(0,), ma10=(1, 2, 3), days=4),
        "601288.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=fees,
    )

    sells = result.trades.loc[
        (result.trades["code"] == "601288.SH") & (result.trades["side"] == "sell")
    ]
    assert len(sells) == 1
    assert sells.iloc[0]["date"] == "20240105"
    assert sells.iloc[0]["signal_price"] == pytest.approx(5.6)
    assert sells.iloc[0]["pnl_pct"] == pytest.approx(10.88)


def test_bank_take_profit_does_not_apply_to_defensive_etf() -> None:
    defensive = _bars([5.0, 5.0, 5.6])
    result = run_defensive_backtest(
        _bars([10.0] * 3), defensive,
        _signals(buys=(0,), ma10=(1, 2), days=3),
        "512890.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.trades["side"].tolist() == ["buy", "sell", "buy"]
    assert result.nav.loc[2, "defensive_quantity"] == 20_000


def test_dividend_loader_reads_per_share_ex_dates(tmp_path) -> None:
    path = tmp_path / "dividends.csv"
    path.write_text("ex_date,cash_per_share,source\n2024-01-04,0.1,official\n", encoding="utf-8")
    assert load_dividend_events(path) == {pd.Timestamp("2024-01-04"): 0.1}


def test_defensive_etf_split_doubles_shares_without_halving_nav() -> None:
    primary, defensive = _bars([10, 10]), _bars([10, 5])
    for frame in (primary, defensive):
        frame["date"] = pd.to_datetime(["2021-10-21 15:00", "2021-10-25 15:00"])
    signals = _signals(ma10=(0,), days=2)
    signals["date"] = pd.to_datetime(["2021-10-21", "2021-10-25"])
    result = run_defensive_backtest(
        primary, defensive, signals, "512890.SH", initial_cash=100_000,
        primary_fees=_zero_fees(), defensive_fees=_zero_fees(),
    )
    assert result.nav.loc[1, "defensive_quantity"] == 20_000
    assert result.nav.loc[1, "nav"] == pytest.approx(100_000)


def test_defensive_task_accepts_configured_data_sources(tmp_path, monkeypatch) -> None:
    from python.strategies.amv_winning_defensive import runner

    keys = ("amv_csv", "primary_csv", "defensive_etf_csv", "stock_5m_dir", "stock_dividends_csv")
    inputs = {key: tmp_path / key for key in keys}
    for key, path in inputs.items():
        if key == "stock_5m_dir":
            path.mkdir()
        else:
            path.touch()
    config = tmp_path / "config.yaml"
    config.write_text("paths:\n" + "".join(
        f"  {key}: {path}\n" for key, path in inputs.items()
    ), encoding="utf-8")
    calls = []
    monkeypatch.setattr(runner, "run_research", lambda *args, **kwargs: calls.append((args, kwargs)))
    request = RunRequest("amv_winning_defensive", "strategy", "20260101", "20260629",
                         tmp_path / "run", FeeConfig.etf_legacy(), "legacy_same_close_idealized", config)

    _run_amv_winning_defensive(request)

    assert TASKS[("strategy", "amv_winning_defensive")].source_path_keys == keys
    assert calls[0][0][:4] == tuple(inputs[key] for key in keys[:4])
    assert calls[0][1]["stock_dividends_path"] == inputs["stock_dividends_csv"]


def test_research_code_snapshot_preserves_untracked_strategy(tmp_path) -> None:
    from python.strategies.amv_winning_defensive import runner

    assert hasattr(runner, "write_code_snapshot")
    manifest_path = runner.write_code_snapshot(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    key = "python/strategies/amv_winning_defensive/runner.py"
    copy = tmp_path / "code_snapshot" / key
    original = runner.Path(runner.__file__)
    assert copy.read_bytes() == original.read_bytes()
    assert manifest["sha256"][key] == hashlib.sha256(original.read_bytes()).hexdigest()
