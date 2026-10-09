# etf_amount_ratio_rotation

研究 0AMV 二、三类买点后的低成交额轮动。

## 运行

```bash
./scripts/backtest.sh run research etf_amount_ratio_rotation --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/ETF_60min_2005_2025`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
