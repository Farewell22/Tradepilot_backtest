# ma10_above_ma30_gap

回测 MA10 高于 MA30 时的乖离度分层买点及既有卖点。

## 运行

```bash
./scripts/backtest.sh run research ma10_above_ma30_gap --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/510300.SH.csv`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
