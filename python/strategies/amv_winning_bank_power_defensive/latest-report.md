# 最新运行报告：amv_winning_bank_power_defensive

- 任务类型：`strategy`
- 运行时间（UTC）：`2026-09-27T14:16:58.828281+00:00`
- 请求区间：`20220516` ～ `20251231`
- 运行目录：[data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f)
- 运行清单：[data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/run_manifest.json](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/run_manifest.json)
- 输入数据：
  - [data/backtest_data/0AMV-260612.csv](../../../data/backtest_data/0AMV-260612.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512100.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512100.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/512800.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/512800.SH.csv)
  - [data/backtest_data/ETF_60min_2005_2025/561560.SH.csv](../../../data/backtest_data/ETF_60min_2005_2025/561560.SH.csv)
- 关键结果文件：
  - [data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/metrics.json](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/metrics.json)
  - [data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/nav.csv](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/nav.csv)
  - [data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/trades.csv](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/trades.csv)

## 本次报告

### [data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/report.md](../../../data/backtest_runs/amv_winning_bank_power_defensive__20260927T141658Z__57c5614f/report.md)

# 0AMV 离场后银行与电力 ETF 各半防守

区间：2022-05-16 至 2025-12-31；共同交易日：884。

| 方案 | 累计收益 | 年化收益 | 最大回撤 |
| --- | ---: | ---: | ---: |
| 银行/电力 ETF 各半 | 58.69% | 13.57% | -16.53% |
| 原策略持现金 | 48.76% | 11.56% | -10.83% |

0AMV 跌破 MA10 或 MACD 死叉时，以当时可用现金的各 50% 买入 512800.SH 与 561560.SH；下一次有效买入信号卖出两只防守 ETF，买回 512100.SH。防守期间不再平衡，不设独立止盈止损。512100 沿用 2.5% 盘中硬止损和盈利后跟踪止盈；盘中止损后，当天有 0AMV 离场信号仍进入防守。

0AMV 日收盘信号按同日收盘价成交是理想化假设；三只 ETF 均按 ETF 费用和整百份交易。银行 ETF 于 2025-07-04 登记、2025-07-07 生效的 1:2 份额拆分已处理。两只 ETF 的 2023、2025 年年报显示 2022—2025 年未实施基金现金分配；区间内不另计成分股分红。仅使用三只 ETF 与 0AMV 均有数据的共同交易日。现金对照调用原版独立 runner；原版与防守分支在主仓盘中止损后同日能否按买入信号回补上有差异，不能把两者收益差全部归因于防守标的。未模拟涨跌停、停牌不可成交及尾盘流动性冲击。
