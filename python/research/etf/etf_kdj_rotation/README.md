# etf_kdj_rotation

在 0AMV 二、三类买点后研究行业 ETF 相对强弱替换。

## 运行

```bash
./scripts/backtest.sh run research etf_kdj_rotation --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/ETF_60min_2005_2025`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
