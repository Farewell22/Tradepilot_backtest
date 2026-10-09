"""Per-run observation-date bounds for legacy research tasks."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from typing import Iterator, Mapping

import pandas as pd


_WINDOW: ContextVar[tuple[str, str] | None] = ContextVar("research_date_window", default=None)


@contextmanager
def date_window(start: str, end: str) -> Iterator[None]:
    token = _WINDOW.set((start, end))
    try:
        yield
    finally:
        _WINDOW.reset(token)


def scoped_ranges(
    samples: Mapping[str, tuple[str | None, str | None]], *, include_all: bool = False
) -> dict[str, tuple[str | None, str | None]]:
    ranges = dict(samples)
    if include_all:
        ranges["all"] = (None, None)
    window = _WINDOW.get()
    if window is None:
        return ranges
    requested_start = datetime.strptime(window[0], "%Y%m%d").date()
    requested_end = datetime.strptime(window[1], "%Y%m%d").date()
    result = {}
    for stage, (start, end) in ranges.items():
        lower = max(requested_start, datetime.fromisoformat(start).date()) if start else requested_start
        upper = min(requested_end, datetime.fromisoformat(end).date()) if end else requested_end
        if lower <= upper:
            result[stage] = (lower.isoformat(), upper.isoformat())
    return result


def scope_frame_dates(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    """Limit dated diagnostic artifacts to the requested execution window."""
    window = _WINDOW.get()
    if window is None:
        return frame
    dates = pd.to_datetime(frame[column], errors="raise")
    start, end = (pd.Timestamp(value) for value in window)
    return frame.loc[dates.between(start, end)].copy()
