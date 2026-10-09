# ma10_gap

比较 510300 与 0AMV 趋势信号的 MA10 乖离度过滤方案。

## 运行

```bash
./scripts/backtest.sh run research ma10_gap --start YYYYMMDD --end YYYYMMDD
```

默认输入：

- `data/backtest_data/0AMV-260612.csv`
- `data/backtest_data/510300.SH.csv`

实现位于 `study.py`。每次运行的完整结果保存在 `data/factor_research_runs/`；
最近一次通过统一命令成功运行的完整报告保存在本目录的 `latest-report.md`。
