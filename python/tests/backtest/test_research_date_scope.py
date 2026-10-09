from python.research.date_scope import date_window, scoped_ranges
from python.research.date_scope import scope_frame_dates
import pandas as pd


def test_research_windows_clip_train_oos_and_all_without_leaking():
    samples = {"train": ("2015-01-01", "2023-12-31"), "oos": ("2024-01-01", "2025-12-31")}
    with date_window("20200101", "20251231"):
        assert scoped_ranges(samples, include_all=True) == {
            "train": ("2020-01-01", "2023-12-31"),
            "oos": ("2024-01-01", "2025-12-31"),
            "all": ("2020-01-01", "2025-12-31"),
        }
    assert scoped_ranges(samples, include_all=True)["all"] == (None, None)


def test_selection_artifacts_are_clipped_by_execution_date():
    rows = pd.DataFrame({"execution_date": ["2023-12-29", "2024-01-02", "2024-04-01"]})
    with date_window("20240101", "20240331"):
        clipped = scope_frame_dates(rows, "execution_date")
    assert clipped["execution_date"].tolist() == ["2024-01-02"]
    assert scope_frame_dates(rows, "execution_date").equals(rows)
