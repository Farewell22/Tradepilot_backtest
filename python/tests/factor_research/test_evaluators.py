import pandas as pd
import pytest

from python.factor_research.evaluators import evaluate_factor


def test_evaluate_factor_reports_correlation_and_quintile_spread():
    observations = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=10),
            "factor": list(range(10)),
            "target": list(range(10)),
        }
    )

    result = evaluate_factor(observations, "factor", "target", groups=5)

    assert result["evaluable"] is True
    assert result["pearson_correlation"] == pytest.approx(1.0)
    assert result["spearman_correlation"] == pytest.approx(1.0)
    assert result["q5_minus_q1"] > 0
