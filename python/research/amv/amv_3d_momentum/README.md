# amv_3d_momentum

检验 0AMV 三日动量与沪深300 ETF 远期收益的关系。

## 运行

```bash
./scripts/backtest.sh run research amv_3d_momentum --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/510300.SH.csv`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
