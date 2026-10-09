from __future__ import annotations

import pandas as pd
import pytest

from python.scoring.data_source import TencentMinuteSource, _to_tencent_code


class _Response:
    def __init__(self, bars: list[list[str]]):
        self.bars = bars

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return {"code": 0, "data": {"sh601288": {"m5": self.bars}}}


def test_shanghai_etf_uses_sh_market_prefix() -> None:
    assert _to_tencent_code("512100") == "sh512100"
    assert _to_tencent_code("512890") == "sh512890"


def test_minute_range_pages_backward_and_keeps_both_end_dates(monkeypatch) -> None:
    source = TencentMinuteSource()
    pages = {
        "202601060000": [
            ["202601031500", "5", "5", "5", "5", "100"],
            ["202601051500", "6", "6", "6", "6", "100"],
        ],
        "202601031500": [
            ["202601011500", "3", "3", "3", "3", "100"],
            ["202601021500", "4", "4", "4", "4", "100"],
        ],
    }
    seen = []

    def get(_url, *, params, timeout):
        anchor = params["param"].split(",")[2]
        seen.append(anchor)
        return _Response(pages[anchor])

    monkeypatch.setattr(source.session, "get", get)
    monkeypatch.setattr(source, "rate_limit_delay", 0)
    bars = source.fetch_minute_kline_range("601288", "20260102", "20260105", "5m")

    assert seen == ["202601060000", "202601031500"]
    assert bars.index.tolist() == list(pd.to_datetime([
        "2026-01-02 15:00", "2026-01-03 15:00", "2026-01-05 15:00",
    ]))
    assert bars["close"].tolist() == [4.0, 5.0, 6.0]


def test_minute_range_rejects_missing_start_history(monkeypatch) -> None:
    source = TencentMinuteSource()
    monkeypatch.setattr(source, "rate_limit_delay", 0)
    monkeypatch.setattr(source.session, "get", lambda *_args, **_kwargs: _Response([]))

    with pytest.raises(ValueError, match="历史分钟线不足"):
        source.fetch_minute_kline_range("601288", "20260102", "20260105", "5m")
