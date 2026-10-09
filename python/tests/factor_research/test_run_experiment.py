import yaml
import pandas as pd

from python.factor_research.run_experiment import main


def test_cli_writes_one_immutable_run_from_cached_inputs(tmp_path):
    amv = tmp_path / "amv.csv"
    pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "close": [10, 20, 30]}).to_csv(amv, index=False)
    cache = tmp_path / "indices"; cache.mkdir()
    for code in ("sh000001", "sz399001"):
        pd.DataFrame({"date": ["2024-01-02", "2024-01-03", "2024-01-04"], "open": [1, 1, 1], "high": [1, 1, 1], "low": [1, 1, 1], "close": [100, 110, 121], "volume": [1, 1, 1]}).to_csv(cache / f"{code}.csv", index=False)
    market = tmp_path / "market" / "2024"; market.mkdir(parents=True)
    for date, close in zip(("20240102", "20240103", "20240104"), (10, 11, 12)):
        pd.DataFrame({"code": ["AAA"], "date": [date], "trade_time": ["15:00"], "close": [close]}).to_parquet(market / f"{date}.parquet", index=False)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump({"sample": {"start_date": "20240102", "end_date": "20240104"}, "paths": {"amv_csv": str(amv), "market_data_root": str(market.parent), "index_cache_root": str(cache), "output_root": str(tmp_path / "runs")}, "factors": {"ma_windows": [2], "return_windows": [1]}, "evaluation": {"horizons": [1], "groups": 2}, "indices": ["sh000001", "sz399001"]}))

    assert main(["--config", str(config)]) == 0
    run = next((tmp_path / "runs").iterdir())
    assert (run / "metadata.json").exists()
    assert (run / "factor_summary.csv").exists()
