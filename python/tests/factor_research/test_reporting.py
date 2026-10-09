import json

import pandas as pd
import pytest

from python.factor_research.reporting import write_experiment_artifacts


def test_writer_creates_reproducible_artifacts_and_refuses_overwrite(tmp_path):
    output = tmp_path / "run"
    write_experiment_artifacts(output, pd.DataFrame({"date": ["2024-01-02"], "factor": [1]}), pd.DataFrame({"factor": ["factor"]}), {"git_commit": "abc"})

    assert {path.name for path in output.iterdir()} == {"observations.csv", "factor_summary.csv", "metadata.json", "report.md"}
    assert json.loads((output / "metadata.json").read_text())["git_commit"] == "abc"
    with pytest.raises(FileExistsError):
        write_experiment_artifacts(output, pd.DataFrame(), pd.DataFrame(), {})
