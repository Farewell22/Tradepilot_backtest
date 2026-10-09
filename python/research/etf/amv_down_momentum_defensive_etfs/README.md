# amv_down_momentum_defensive_etfs

检验 0AMV MACD 死叉后的红利、煤炭 ETF 远期总收益。

## 运行

```bash
./scripts/backtest.sh run research amv_down_momentum_defensive_etfs --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/ETF_60min_2005_2025/510880.SH.csv`
- `data/backtest_data/ETF_60min_2005_2025/515220.SH.csv`
- `data/backtest_data/ETF_60min_2005_2025/512100.SH.csv`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
