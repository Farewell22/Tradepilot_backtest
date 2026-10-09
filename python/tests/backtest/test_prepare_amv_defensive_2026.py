from __future__ import annotations

import pandas as pd
import pytest
import hashlib
import json

from python.strategies.amv_winning_defensive.prepare_2026 import prepare_inputs, validate_session_bars


def _bars(dates: list[str], times: list[str]) -> pd.DataFrame:
    index = pd.to_datetime([f"{date} {time}" for date in dates for time in times])
    return pd.DataFrame({"open": 5.0, "high": 5.1, "low": 4.9,
                         "close": 5.0, "volume": 100.0}, index=index)


def test_session_validation_rejects_missing_day() -> None:
    frame = _bars(["2026-01-05"], ["10:30", "11:30", "14:00", "15:00"])
    with pytest.raises(ValueError, match="缺失交易日.*2026-01-06"):
        validate_session_bars(frame, {pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")},
                              "512100.SH", "60m")


def test_session_validation_accepts_complete_etf_days() -> None:
    frame = _bars(["2026-01-05", "2026-01-06"], ["10:30", "11:30", "14:00", "15:00"])
    validate_session_bars(frame, {pd.Timestamp("2026-01-05"), pd.Timestamp("2026-01-06")},
                          "512100.SH", "60m")


def test_prepare_reuses_verified_input_snapshot(tmp_path) -> None:
    output = tmp_path / "snapshot"
    output.mkdir()
    item = output / "sample.csv"
    item.write_text("date,close\n", encoding="utf-8")
    manifest = {"start_date": "20260101", "end_date": "20260629",
                "generated_sha256": {str(item): hashlib.sha256(item.read_bytes()).hexdigest()}}
    (output / "source_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    assert prepare_inputs("20260101", "20260629", output) == manifest


def test_five_minute_validation_rejects_replaced_intraday_bar() -> None:
    morning = pd.date_range("2026-01-05 09:35", "2026-01-05 11:30", freq="5min")
    afternoon = pd.date_range("2026-01-05 13:05", "2026-01-05 15:00", freq="5min")
    times = sorted({*morning, *afternoon} - {pd.Timestamp("2026-01-05 10:00")}
                   | {pd.Timestamp("2026-01-05 10:02")})
    frame = pd.DataFrame({"open": 5.0, "high": 5.1, "low": 4.9,
                          "close": 5.0, "volume": 100.0}, index=times)

    with pytest.raises(ValueError, match="5 分钟行情不完整"):
        validate_session_bars(frame, {pd.Timestamp("2026-01-05")}, "601288.SH", "5m")
